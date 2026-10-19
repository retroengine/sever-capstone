//! `sever_db::open` on real directories: the order of §15.7 (ENGINE.lock, then the platform
//! checks), the overrides it reports, and the key directory's file modes (§14.1).

#![allow(clippy::unwrap_used, clippy::panic)]

use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

use sever_db::{OpenOptions, open};
use sever_platform::Overrides;
use sever_spec::spec;
use sever_types::Error;

fn fresh(base: &Path, name: &str) -> PathBuf {
    let dir = base.join(name);
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

fn options(dir: &Path, o: Overrides) -> OpenOptions {
    let mut opts = OpenOptions::new(dir.join("data"), dir.join("keys"));
    opts.d = 16;
    opts.overrides = o;
    opts.on_failure = sever_engine::FailurePolicy::Poison;
    opts
}

const MEM: Overrides = Overrides {
    allow_unsafe_memory: true,
    allow_unsafe_fs: false,
};
const BOTH: Overrides = Overrides {
    allow_unsafe_memory: true,
    allow_unsafe_fs: true,
};

fn check_of(r: Result<sever_db::Opened, Error>) -> &'static str {
    match r {
        Err(Error::PlatformUnsafe { check }) => check,
        Err(e) => panic!("not PlatformUnsafe: {e:?}"),
        Ok(_) => panic!("opened"),
    }
}

// oracle: A §15.7 "Recovery steps 1 and 4: run the platform checks (§12.9) and the memory hygiene
// setup (§12.8) after taking ENGINE.lock" and §12.9 (one process per data directory)
#[spec("SR-15.7-3")]
#[test]
fn p4_db_open_takes_the_lock_before_the_platform_checks() {
    // tmpfs fails the §12.9 data-directory check; only the override lets the first opener in.
    let shm = Path::new("/dev/shm");
    assert!(shm.is_dir(), "the test needs a tmpfs at /dev/shm");
    let dir = fresh(shm, &format!("sever-db-p4-lock-{}", std::process::id()));
    let first = open(&options(&dir, BOTH)).unwrap();
    assert!(
        first
            .overridden
            .contains(&"§12.9 data filesystem not ext4 or XFS")
    );
    // A second opener without the override meets the lock first.
    assert_eq!(
        check_of(open(&options(&dir, MEM))),
        "§12.9 ENGINE.lock held by another process"
    );
    drop(first);
    // Once the lock is free, the platform check refuses it.
    assert_eq!(
        check_of(open(&options(&dir, MEM))),
        "§12.9 data filesystem not ext4 or XFS"
    );
    std::fs::remove_dir_all(&dir).unwrap();
}

// oracle: A §14.1 (the key directory's files are mode 0600) and §12.8–12.9 (each override used is
// recorded)
#[test]
fn p4_db_open_on_ext4_keeps_the_key_files_private_and_reports_its_overrides() {
    let dir = fresh(Path::new(env!("CARGO_TARGET_TMPDIR")), "sever-db-p4-real");
    let opened = open(&options(&dir, MEM)).unwrap();
    let cid = opened
        .db
        .create_collection(
            include_bytes!("../../../golden/p1_partition_small.svp"),
            sever_engine::CollectionOptions {
                spawn_target: 8,
                spawning_enabled: true,
                store_passages: true,
            },
        )
        .unwrap();
    assert!(opened.db.engine.collections().contains(&cid));
    assert!(
        opened.overridden.iter().all(|c| c.starts_with("§12.8")),
        "{:?}",
        opened.overridden
    );
    assert_eq!(
        opened.memory_locked,
        !opened.overridden.contains(&"§12.8 mlock")
    );
    drop(opened);
    for f in ["SECRETS", "KEYS"] {
        let mode = std::fs::metadata(dir.join("keys").join(f))
            .unwrap()
            .permissions()
            .mode();
        assert_eq!(mode & 0o777, 0o600, "{f}");
    }
    let again = open(&options(&dir, MEM)).unwrap();
    assert_eq!(again.db.engine.collections(), vec![cid]);
}
