//! L1 and L2 tests of `SimVfs` (spec §12.2). The EP-5 contract runs in `contract.rs`.

use proptest::prelude::*;
use sever_spec::spec;

use crate::{CrashPolicy, FaultPlan, OpenMode, SimVfs, Vfs, VfsError, VfsOp, read_all};

fn snapshot(vfs: &dyn Vfs) -> Vec<(String, Option<Vec<u8>>)> {
    fn walk(vfs: &dyn Vfs, dir: &str, out: &mut Vec<(String, Option<Vec<u8>>)>) {
        for name in vfs.list(dir).unwrap() {
            let path = if dir.is_empty() {
                name
            } else {
                format!("{dir}/{name}")
            };
            match vfs.open(&path, OpenMode::Existing) {
                Ok(f) => out.push((path, Some(read_all(f.as_ref()).unwrap()))),
                Err(VfsError::IsADirectory) => {
                    out.push((path.clone(), None));
                    walk(vfs, &path, out);
                }
                Err(e) => panic!("{e}"),
            }
        }
    }
    let mut out = Vec::new();
    walk(vfs, "", &mut out);
    out
}

/// fsyncs every file and every directory.
fn sync_everything(vfs: &dyn Vfs) {
    for (path, kind) in snapshot(vfs) {
        match kind {
            Some(_) => vfs
                .open(&path, OpenMode::Existing)
                .unwrap()
                .fsync()
                .unwrap(),
            None => vfs.fsync_dir(&path).unwrap(),
        }
    }
    vfs.fsync_dir("").unwrap();
}

/// The protocol of a durable file creation, one mutating operation per step:
/// create_dir, fsync_dir root, create, write, fsync, fsync_dir.
fn durable_create(vfs: &SimVfs) -> Result<(), VfsError> {
    vfs.create_dir("d")?;
    vfs.fsync_dir("")?;
    let mut f = vfs.open("d/a", OpenMode::CreateNew)?;
    f.write_at(0, b"payload")?;
    f.fsync()?;
    vfs.fsync_dir("d")
}

#[test]
#[spec("SR-12.2-3")]
fn p2_vfs_sim_crash_at_every_operation_of_a_durable_create() {
    let dry = SimVfs::new();
    dry.set_faults(FaultPlan::default());
    durable_create(&dry).unwrap();
    assert_eq!(dry.ops_since_plan(), 6);

    for k in 1..=6 {
        let v = SimVfs::new();
        v.set_faults(FaultPlan {
            crash_at_op: Some(k),
            ..FaultPlan::default()
        });
        assert_eq!(durable_create(&v), Err(VfsError::Crashed), "k = {k}");
        assert_eq!(v.ops_since_plan(), k, "the crash happens during op {k}");
        assert!(v.is_crashed());
        v.restart(CrashPolicy::DropAll);
        // The directory is durable once op 2 completed; the file never is, because the crash
        // always comes before the final fsync_dir completes.
        let want_dir: &[&str] = if k > 2 { &["d"] } else { &[] };
        assert_eq!(v.list("").unwrap(), want_dir, "k = {k}");
        if k > 2 {
            assert!(v.list("d").unwrap().is_empty(), "k = {k}");
        }
    }

    let done = SimVfs::new();
    durable_create(&done).unwrap();
    done.restart(CrashPolicy::DropAll);
    assert_eq!(
        read_all(done.open("d/a", OpenMode::Existing).unwrap().as_ref()).unwrap(),
        b"payload"
    );
}

#[test]
#[spec("SR-12.2-4")]
fn p2_vfs_sim_tears_the_crashing_write_at_the_requested_byte() {
    for tear in [0usize, 1, 37, 99, 100, 500] {
        let v = SimVfs::new();
        let mut f = v.open("w", OpenMode::CreateNew).unwrap();
        v.fsync_dir("").unwrap();
        f.fsync().unwrap();
        v.set_faults(FaultPlan {
            crash_at_op: Some(1),
            tear_bytes: tear,
            ..FaultPlan::default()
        });
        assert_eq!(f.append(&[7u8; 100]), Err(VfsError::Crashed));
        v.restart(CrashPolicy::KeepAll);
        let got = read_all(v.open("w", OpenMode::Existing).unwrap().as_ref()).unwrap();
        assert_eq!(got, vec![7u8; tear.min(100)], "tear = {tear}");
    }
}

#[test]
#[spec("SR-12.2-4")]
fn p2_vfs_sim_fails_the_chosen_sync_counting_files_and_directories() {
    let v = SimVfs::new();
    let mut f = v.open("f", OpenMode::CreateNew).unwrap();
    v.set_faults(FaultPlan {
        fail_sync_at: Some(3),
        ..FaultPlan::default()
    });
    f.fsync().unwrap(); // sync 1
    v.fsync_dir("").unwrap(); // sync 2
    assert_eq!(
        f.fsync(),
        Err(VfsError::Io {
            op: VfsOp::Fsync,
            kind: std::io::ErrorKind::Other
        })
    );
    f.fsync().unwrap(); // sync 4 succeeds
    assert!(!v.is_crashed(), "a failed fsync is an error, not a crash");
}

#[test]
#[spec("SR-12.2-4")]
fn p2_vfs_sim_failed_dir_sync_never_makes_the_entry_durable() {
    let v = SimVfs::new();
    v.open("f", OpenMode::CreateNew).unwrap().fsync().unwrap();
    v.set_faults(FaultPlan {
        fail_sync_at: Some(1),
        ..FaultPlan::default()
    });
    assert!(v.fsync_dir("").is_err());
    v.fsync_dir("").unwrap(); // the forbidden retry reports success
    assert_eq!(v.list("").unwrap(), ["f"], "still visible before the crash");
    v.restart(CrashPolicy::KeepAll);
    assert!(v.list("").unwrap().is_empty(), "but never durable");
}

#[test]
fn p2_vfs_sim_later_writes_after_a_failed_fsync_can_still_be_saved() {
    let v = SimVfs::new();
    let mut f = v.open("f", OpenMode::CreateNew).unwrap();
    v.fsync_dir("").unwrap();
    f.write_at(0, b"aaaa").unwrap();
    v.set_faults(FaultPlan {
        fail_sync_at: Some(1),
        ..FaultPlan::default()
    });
    assert!(f.fsync().is_err());
    f.write_at(2, b"bb").unwrap();
    f.fsync().unwrap();
    v.restart(CrashPolicy::DropAll);
    let got = read_all(v.open("f", OpenMode::Existing).unwrap().as_ref()).unwrap();
    assert_eq!(
        got, b"\0\0bb",
        "only the write after the failure reached the disk"
    );
}

#[test]
fn p2_vfs_sim_fork_is_independent() {
    let a = SimVfs::new();
    a.open("x", OpenMode::CreateNew).unwrap();
    let b = a.fork();
    b.open("y", OpenMode::CreateNew).unwrap();
    a.unlink("x").unwrap();
    assert!(a.list("").unwrap().is_empty());
    assert_eq!(b.list("").unwrap(), ["x", "y"]);
}

#[test]
fn p2_vfs_sim_clones_share_one_disk() {
    let a = SimVfs::new();
    let b = a.clone();
    a.open("x", OpenMode::CreateNew).unwrap();
    assert_eq!(b.list("").unwrap(), ["x"]);
    b.crash();
    assert_eq!(a.list(""), Err(VfsError::Crashed));
}

#[test]
fn p2_vfs_sim_restart_clears_the_fault_plan() {
    let v = SimVfs::new();
    v.set_faults(FaultPlan {
        crash_at_op: Some(2),
        fail_sync_at: Some(1),
        ..FaultPlan::default()
    });
    v.restart(CrashPolicy::DropAll);
    assert_eq!(v.ops_since_plan(), 0);
    v.create_dir("a").unwrap();
    v.fsync_dir("").unwrap();
    v.create_dir("b").unwrap();
}

#[test]
fn p2_vfs_sim_unlinked_file_handle_still_works_until_restart() {
    let v = SimVfs::new();
    let mut f = v.open("f", OpenMode::CreateNew).unwrap();
    v.unlink("f").unwrap();
    f.write_at(0, b"orphan").unwrap();
    assert_eq!(read_all(f.as_ref()).unwrap(), b"orphan");
    v.restart(CrashPolicy::KeepAll);
    assert!(f.len().is_err());
    assert!(v.list("").unwrap().is_empty());
}

#[test]
fn p2_vfs_sim_unsynced_unlink_is_undone_by_a_crash() {
    let v = SimVfs::new();
    let mut f = v.open("f", OpenMode::CreateNew).unwrap();
    f.write_at(0, b"keep").unwrap();
    f.fsync().unwrap();
    v.fsync_dir("").unwrap();
    v.unlink("f").unwrap();
    v.restart(CrashPolicy::DropAll);
    let got = read_all(v.open("f", OpenMode::Existing).unwrap().as_ref()).unwrap();
    assert_eq!(got, b"keep");
}

#[test]
fn p2_vfs_sim_directory_rename_is_durable_only_after_fsync_dir() {
    // The storage-checkpoint step of §15.6: write into x.tmp/, rename to x/, fsync the parent.
    for synced in [false, true] {
        let v = SimVfs::new();
        v.create_dir("checkpoint").unwrap();
        v.fsync_dir("").unwrap();
        v.create_dir("checkpoint/7.tmp").unwrap();
        let mut m = v
            .open("checkpoint/7.tmp/meta.bin", OpenMode::CreateNew)
            .unwrap();
        m.write_at(0, b"meta").unwrap();
        m.fsync().unwrap();
        v.fsync_dir("checkpoint/7.tmp").unwrap();
        v.fsync_dir("checkpoint").unwrap();
        v.rename("checkpoint/7.tmp", "checkpoint/7").unwrap();
        if synced {
            v.fsync_dir("checkpoint").unwrap();
        }
        v.restart(CrashPolicy::DropAll);
        let want = if synced {
            "checkpoint/7"
        } else {
            "checkpoint/7.tmp"
        };
        assert_eq!(
            v.list("checkpoint").unwrap(),
            [want.rsplit('/').next().unwrap()]
        );
        let got = read_all(
            v.open(&format!("{want}/meta.bin"), OpenMode::Existing)
                .unwrap()
                .as_ref(),
        )
        .unwrap();
        assert_eq!(got, b"meta");
    }
}

#[test]
fn p2_vfs_sim_counts_operations_bytes_and_syncs() {
    let v = SimVfs::new();
    v.set_faults(FaultPlan::default());
    let mut f = v.open("f", OpenMode::CreateNew).unwrap(); // 1
    f.append(&[0; 10]).unwrap(); // 2
    f.write_at(3, &[1; 5]).unwrap(); // 3
    f.fsync().unwrap(); // 4
    v.fsync_dir("").unwrap(); // 5
    let _ = f.len().unwrap();
    let _ = v.list("").unwrap();
    assert_eq!(
        v.write_sizes(),
        vec![0, 10, 5, 0, 0],
        "per operation, writes only"
    );
    assert_eq!(v.write_log()[1], (Some("f".to_owned()), 10));
    assert_eq!(
        v.stats(),
        crate::SimStats {
            mutating_ops: 5,
            fsyncs: 1,
            dir_fsyncs: 1,
            bytes_written: 15
        }
    );
    v.reset_stats();
    assert_eq!(v.stats(), crate::SimStats::default());
}

#[test]
fn p2_vfs_sim_refuses_files_beyond_the_size_limit() {
    let v = SimVfs::new();
    let mut f = v.open("f", OpenMode::CreateNew).unwrap();
    assert!(matches!(
        f.write_at(1 << 32, b"x"),
        Err(VfsError::Io {
            op: VfsOp::Write,
            ..
        })
    ));
    assert!(f.truncate((1 << 32) + 1).is_err());
}

#[derive(Clone, Debug)]
enum Op {
    CreateDir(usize),
    Write(usize, u8, u8),
    Append(usize, u8),
    Truncate(usize, u8),
    Fsync(usize),
    FsyncDir(usize),
    Rename(usize, usize),
    Unlink(usize),
    RemoveDir(usize),
}

const FILES: [&str; 6] = ["a", "b", "d/a", "d/b", "e/a", "e/f/a"];
const DIRS: [&str; 4] = ["", "d", "e", "e/f"];

fn op() -> impl Strategy<Value = Op> {
    prop_oneof![
        (1..4usize).prop_map(Op::CreateDir),
        (0..6usize, 0..40u8, any::<u8>()).prop_map(|(f, o, b)| Op::Write(f, o, b)),
        (0..6usize, any::<u8>()).prop_map(|(f, b)| Op::Append(f, b)),
        (0..6usize, 0..40u8).prop_map(|(f, l)| Op::Truncate(f, l)),
        (0..6usize).prop_map(Op::Fsync),
        (0..4usize).prop_map(Op::FsyncDir),
        (0..6usize, 0..6usize).prop_map(|(a, b)| Op::Rename(a, b)),
        (0..6usize).prop_map(Op::Unlink),
        (1..4usize).prop_map(Op::RemoveDir),
    ]
}

/// Runs `ops`, ignoring the errors a random sequence naturally hits (missing parents and so on).
fn run(v: &SimVfs, ops: &[Op]) {
    for op in ops {
        let file = |i: usize| FILES[i];
        let _ = match op {
            Op::CreateDir(d) => v.create_dir(DIRS[*d]),
            Op::Write(f, o, b) => v
                .open(file(*f), OpenMode::Create)
                .and_then(|mut h| h.write_at(u64::from(*o), &[*b; 7])),
            Op::Append(f, b) => v
                .open(file(*f), OpenMode::Create)
                .and_then(|mut h| h.append(&[*b; 5]).map(|_| ())),
            Op::Truncate(f, l) => v
                .open(file(*f), OpenMode::Existing)
                .and_then(|mut h| h.truncate(u64::from(*l))),
            Op::Fsync(f) => v
                .open(file(*f), OpenMode::Existing)
                .and_then(|mut h| h.fsync()),
            Op::FsyncDir(d) => v.fsync_dir(DIRS[*d]),
            Op::Rename(a, b) => v.rename(file(*a), file(*b)),
            Op::Unlink(f) => v.unlink(file(*f)),
            Op::RemoveDir(d) => v.remove_dir(DIRS[*d]),
        };
    }
}

fn policy() -> impl Strategy<Value = CrashPolicy> {
    prop_oneof![
        Just(CrashPolicy::DropAll),
        Just(CrashPolicy::KeepAll),
        any::<u64>().prop_map(CrashPolicy::Random),
    ]
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(256))]

    // Once everything is synced, no crash policy changes anything (spec §12.2: fsynced data and
    // fsync_dir'ed entries survive).
    #[test]
    #[spec("SR-12.2-3")]
    fn p2_vfs_prop_synced_state_survives_every_policy(
        ops in prop::collection::vec(op(), 0..60),
        p in policy(),
    ) {
        let v = SimVfs::new();
        run(&v, &ops);
        sync_everything(&v);
        let before = snapshot(&v);
        v.restart(p);
        prop_assert_eq!(snapshot(&v), before);
    }

    // KeepAll is the page-cache view: with no failed fsync, a crash under KeepAll changes nothing.
    #[test]
    fn p2_vfs_prop_keep_all_equals_the_current_view(ops in prop::collection::vec(op(), 0..60)) {
        let v = SimVfs::new();
        run(&v, &ops);
        let before = snapshot(&v);
        v.restart(CrashPolicy::KeepAll);
        prop_assert_eq!(snapshot(&v), before);
    }

    // Two runs with the same ops and seed give the same disk (spec §12.2: deterministic).
    #[test]
    #[spec("SR-12.2-5")]
    fn p2_vfs_prop_same_seed_same_disk(
        ops in prop::collection::vec(op(), 0..60),
        seed in any::<u64>(),
    ) {
        let (a, b) = (SimVfs::new(), SimVfs::new());
        run(&a, &ops);
        run(&b, &ops);
        a.restart(CrashPolicy::Random(seed));
        b.restart(CrashPolicy::Random(seed));
        prop_assert_eq!(snapshot(&a), snapshot(&b));
    }
}
