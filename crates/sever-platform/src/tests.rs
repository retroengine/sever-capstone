//! The startup rules on a fake probe. Expected outcomes come from spec §12.8–12.9 and the P4-T8
//! register (`spec/registers_p4.yaml`, PL-1 … PL-13), written out by hand (oracle A); filesystem
//! magic numbers from the kernel's `include/uapi/linux/magic.h` and OpenZFS (oracle B), typed in
//! here rather than taken from `rules`.

use std::cell::RefCell;
use std::path::{Path, PathBuf};

use sever_spec::spec;
use sever_types::Error;

use crate::probe::{Hibernation, PlatformProbe, ProbeError, Swap, parse_swaps};
use crate::rules::{hibernation_enabled, key_fs_ok, swap_entry_encrypted};
use crate::*;

const EXT4: i64 = 0xEF53;
const XFS: i64 = 0x5846_5342;
const BTRFS: i64 = 0x9123_683E;
const TMPFS: i64 = 0x0102_1994;
const ZFS: i64 = 0x2FC1_2FC1;
const F2FS: i64 = 0xF2F5_2010;
const OVERLAYFS: i64 = 0x794C_7630;
const V9FS: i64 = 0x0102_1997; // a Windows drive under WSL (drvfs over 9p)

fn swap(name: &str, kind: &str, dm_uuid: Option<&str>) -> Swap {
    Swap {
        name: name.into(),
        kind: kind.into(),
        dm_uuid: dm_uuid.map(Into::into),
    }
}

fn hib(state: &str, resume: &str) -> Hibernation {
    Hibernation {
        state: Some(state.into()),
        resume: Some(resume.into()),
    }
}

/// A machine described by its answers. `calls` records what `startup` asked or did, in order.
struct Fake {
    data_fs: i64,
    key_fs: i64,
    keys_no_cow: Option<bool>,
    dir_no_cow: bool,
    swaps: Result<Vec<Swap>, ProbeError>,
    hibernation: Hibernation,
    core_ok: bool,
    lock_ok: bool,
    calls: RefCell<Vec<&'static str>>,
}

/// PL-7: swap off, hibernation off, data and keys on ext4.
fn safe() -> Fake {
    Fake {
        data_fs: EXT4,
        key_fs: EXT4,
        keys_no_cow: Some(false),
        dir_no_cow: false,
        swaps: Ok(vec![]),
        hibernation: hib("freeze mem\n", "0:0\n"),
        core_ok: true,
        lock_ok: true,
        calls: RefCell::default(),
    }
}

fn data() -> PathBuf {
    PathBuf::from("/srv/sever/data")
}

fn keys() -> PathBuf {
    PathBuf::from("/srv/sever/keys")
}

impl PlatformProbe for Fake {
    fn filesystem(&self, dir: &Path) -> Result<i64, ProbeError> {
        self.calls.borrow_mut().push("filesystem");
        if dir == data() {
            Ok(self.data_fs)
        } else if dir == keys() {
            Ok(self.key_fs)
        } else {
            Err(ProbeError)
        }
    }
    fn no_cow(&self, path: &Path) -> Result<Option<bool>, ProbeError> {
        self.calls.borrow_mut().push("no_cow");
        if path == keys().join("KEYS") {
            Ok(self.keys_no_cow)
        } else if path == keys() {
            Ok(Some(self.dir_no_cow))
        } else {
            Ok(None)
        }
    }
    fn swaps(&self) -> Result<Vec<Swap>, ProbeError> {
        self.calls.borrow_mut().push("swaps");
        self.swaps.clone()
    }
    fn hibernation(&self) -> Result<Hibernation, ProbeError> {
        self.calls.borrow_mut().push("hibernation");
        Ok(self.hibernation.clone())
    }
    fn disable_core_dumps(&self) -> Result<(), ProbeError> {
        self.calls.borrow_mut().push("disable_core_dumps");
        if self.core_ok {
            Ok(())
        } else {
            Err(ProbeError)
        }
    }
    fn lock_memory(&self) -> Result<(), ProbeError> {
        self.calls.borrow_mut().push("lock_memory");
        if self.lock_ok {
            Ok(())
        } else {
            Err(ProbeError)
        }
    }
}

const NONE: Overrides = Overrides {
    allow_unsafe_memory: false,
    allow_unsafe_fs: false,
};
const MEM: Overrides = Overrides {
    allow_unsafe_memory: true,
    allow_unsafe_fs: false,
};
const FS: Overrides = Overrides {
    allow_unsafe_memory: false,
    allow_unsafe_fs: true,
};

fn run(f: &Fake, o: Overrides) -> Result<StartupReport, Error> {
    startup(f, &data(), &keys(), o)
}

fn refused(f: &Fake, o: Overrides) -> Option<&'static str> {
    match run(f, o) {
        Err(Error::PlatformUnsafe { check }) => Some(check),
        Err(e) => panic!("not PlatformUnsafe: {e:?}"),
        Ok(_) => None,
    }
}

/// One refusal row: refused with `check` and no flag; refused still under the other flag; started
/// under its own flag, with `check` (only) recorded as overridden.
fn assert_refusal_row(row: &str, f: &Fake, check: &str, own: Overrides, other: Overrides) {
    assert_eq!(refused(f, NONE), Some(check), "{row} without a flag");
    assert_eq!(refused(f, other), Some(check), "{row} under the other flag");
    let r = run(f, own).unwrap_or_else(|e| panic!("{row} under its flag: {e:?}"));
    assert_eq!(r.overridden, vec![check], "{row}: what the ledger records");
}

fn assert_starts(row: &str, f: &Fake) {
    let r = run(f, NONE).unwrap_or_else(|e| panic!("{row} refused: {e:?}"));
    assert!(r.overridden.is_empty(), "{row}: {:?}", r.overridden);
    assert!(r.locked.is_some(), "{row}: memory not locked");
}

// oracle: A §12.8 and spec/registers_p4.yaml PL-1, PL-2, PL-6, PL-7, PL-9, PL-10
#[spec("SR-12.8-4", "SR-12.8-5", "SR-12.8-6", "SR-17-6")]
#[test]
fn p4_platform_memory_rows_of_the_register_refuse_and_start_as_listed() {
    let pl1 = Fake {
        swaps: Ok(vec![swap("/dev/sda2", "partition", None)]),
        ..safe()
    };
    assert_refusal_row("PL-1", &pl1, "§12.8 swap not encrypted", MEM, FS);
    let pl2 = Fake {
        hibernation: hib("freeze mem disk\n", "8:3\n"),
        ..safe()
    };
    assert_refusal_row("PL-2", &pl2, "§12.8 hibernation enabled", MEM, FS);
    let pl6 = Fake {
        lock_ok: false,
        ..safe()
    };
    assert_refusal_row("PL-6", &pl6, "§12.8 mlock", MEM, FS);
    assert!(
        run(&pl6, MEM).unwrap().locked.is_none(),
        "PL-6: no lock, no proof"
    );

    assert_starts("PL-7", &safe());
    let pl9 = Fake {
        swaps: Ok(vec![swap(
            "/dev/dm-1",
            "partition",
            Some("CRYPT-LUKS2-3f9a0c1e5b7d4a2f8e6c9b0a1d3e5f7a-cryptswap"),
        )]),
        ..safe()
    };
    assert_starts("PL-9", &pl9);
    let pl10 = Fake {
        swaps: Ok(vec![swap("/dev/zram0", "partition", None)]),
        ..safe()
    };
    assert_starts("PL-10", &pl10);
}

// oracle: A §12.9 and spec/registers_p4.yaml PL-3, PL-4, PL-5, PL-8, PL-11, PL-12, PL-13
#[spec("SR-12.9-1", "SR-12.9-3", "SR-12.9-4", "SR-17-6")]
#[test]
fn p4_platform_filesystem_rows_of_the_register_refuse_and_start_as_listed() {
    let key_check = "§12.9 key filesystem does not overwrite in place";
    let pl3 = Fake {
        key_fs: ZFS,
        ..safe()
    };
    assert_refusal_row("PL-3", &pl3, key_check, FS, MEM);
    let pl4 = Fake {
        key_fs: BTRFS,
        keys_no_cow: Some(false),
        ..safe()
    };
    assert_refusal_row("PL-4", &pl4, key_check, FS, MEM);
    let pl5 = Fake {
        data_fs: TMPFS,
        ..safe()
    };
    assert_refusal_row(
        "PL-5",
        &pl5,
        "§12.9 data filesystem not ext4 or XFS",
        FS,
        MEM,
    );
    let pl13 = Fake {
        key_fs: TMPFS,
        ..safe()
    };
    assert_refusal_row("PL-13", &pl13, key_check, FS, MEM);

    let pl8 = Fake {
        data_fs: XFS,
        key_fs: XFS,
        ..safe()
    };
    assert_starts("PL-8", &pl8);
    let pl11 = Fake {
        key_fs: BTRFS,
        keys_no_cow: Some(true),
        ..safe()
    };
    assert_starts("PL-11", &pl11);
    let pl12 = Fake {
        data_fs: EXT4,
        key_fs: XFS,
        ..safe()
    };
    assert_starts("PL-12", &pl12);
}

// oracle: A §12.8 "every active entry of /proc/swaps is a zram device or a device-mapper device
// whose dm/uuid starts with CRYPT-; anything else, a swap file included, is unencrypted"
#[spec("SR-12.8-5")]
#[test]
fn p4_platform_swap_is_encrypted_only_on_zram_or_dm_crypt() {
    let cases = [
        (swap("/dev/zram0", "partition", None), true),
        (swap("/dev/zram12", "partition", None), true),
        (
            swap("/dev/dm-0", "partition", Some("CRYPT-PLAIN-swap")),
            true,
        ),
        (swap("/dev/dm-0", "partition", Some("LVM-abcdef")), false),
        (
            swap("/dev/dm-0", "partition", Some("crypt-plain-swap")),
            false,
        ),
        (swap("/dev/sda2", "partition", None), false),
        (swap("/dev/nvme0n1p3", "partition", None), false),
        (swap("/swapfile", "file", None), false),
        (swap("/zram0", "file", None), false), // a swap file named like a device
        (swap("/dev/zramx", "partition", None), false),
    ];
    for (s, want) in &cases {
        assert_eq!(swap_entry_encrypted(s), *want, "{s:?}");
    }
    // Every entry must be encrypted; swap off is safe.
    let off = Fake { ..safe() };
    assert_eq!(refused(&off, NONE), None);
    let mixed = Fake {
        swaps: Ok(vec![
            swap("/dev/zram0", "partition", None),
            swap("/swapfile", "file", None),
        ]),
        ..safe()
    };
    assert_eq!(refused(&mixed, NONE), Some("§12.8 swap not encrypted"));
}

// oracle: A §12.8 "Hibernation is enabled when /sys/power/state lists disk and /sys/power/resume
// is not 0:0"
#[spec("SR-12.8-5")]
#[test]
fn p4_platform_hibernation_needs_disk_listed_and_a_resume_device() {
    let cases = [
        (hib("freeze mem disk\n", "8:3\n"), true),
        (hib("disk\n", "259:2\n"), true),
        (hib("freeze mem disk\n", "0:0\n"), false), // this laptop: listed, but nowhere to resume
        (hib("freeze mem\n", "8:3\n"), false),
        (hib("freeze mem diskette\n", "8:3\n"), false), // a word, not a substring
        (Hibernation::default(), false),
    ];
    for (h, want) in &cases {
        assert_eq!(hibernation_enabled(h), *want, "{h:?}");
    }
}

// oracle: A §12.9 "an allow-list: ext4, XFS, and btrfs only when KEYS carries the
// no-copy-on-write attribute. Anything else (ZFS, btrfs without it, tmpfs, f2fs, overlayfs, a
// Windows drive under WSL) is refused"
#[spec("SR-12.9-3")]
#[test]
fn p4_platform_key_filesystem_is_an_allow_list() {
    for (magic, no_cow, want) in [
        (EXT4, false, true),
        (XFS, false, true),
        (BTRFS, true, true),
        (BTRFS, false, false),
        (ZFS, true, false),
        (TMPFS, false, false),
        (F2FS, false, false),
        (OVERLAYFS, false, false),
        (V9FS, false, false),
    ] {
        assert_eq!(key_fs_ok(magic, no_cow), want, "{magic:#x} no_cow={no_cow}");
    }
}

// oracle: A §12.9 (btrfs only when KEYS carries no-CoW) and overview DB-93 (before KEYS exists,
// the directory's attribute, which a new file inherits)
#[spec("SR-12.9-3")]
#[test]
fn p4_platform_btrfs_before_keys_exists_reads_the_directory_attribute() {
    let inherits = Fake {
        key_fs: BTRFS,
        keys_no_cow: None,
        dir_no_cow: true,
        ..safe()
    };
    assert_eq!(refused(&inherits, NONE), None);
    let plain_dir = Fake {
        key_fs: BTRFS,
        keys_no_cow: None,
        dir_no_cow: false,
        ..safe()
    };
    assert_eq!(
        refused(&plain_dir, NONE),
        Some("§12.9 key filesystem does not overwrite in place")
    );
    // Once KEYS exists its own attribute decides, whatever the directory says.
    let file_wins = Fake {
        key_fs: BTRFS,
        keys_no_cow: Some(false),
        dir_no_cow: true,
        ..safe()
    };
    assert!(refused(&file_wins, NONE).is_some());
}

// oracle: A §12.8 "At startup the engine sets RLIMIT_CORE = 0 and PR_SET_DUMPABLE = 0"
#[spec("SR-12.8-3")]
#[test]
fn p4_platform_startup_turns_core_dumps_off_before_anything_else() {
    let f = safe();
    run(&f, NONE).unwrap();
    assert_eq!(f.calls.borrow().first(), Some(&"disable_core_dumps"));
    let cannot = Fake {
        core_ok: false,
        ..safe()
    };
    assert_eq!(refused(&cannot, NONE), Some("§12.8 core dumps"));
    assert_eq!(refused(&cannot, FS), Some("§12.8 core dumps"));
    assert_eq!(
        run(&cannot, MEM).unwrap().overridden,
        vec!["§12.8 core dumps"]
    );
}

// oracle: A §12.8 "Key material and decrypted accumulators live in mlocked pages" and overview
// DB-93 (the whole process is locked once, at startup)
#[spec("SR-12.8-2")]
#[test]
fn p4_platform_startup_locks_memory_once_and_only_then_hands_out_the_proof() {
    let f = safe();
    let r = run(&f, NONE).unwrap();
    let locks = f
        .calls
        .borrow()
        .iter()
        .filter(|c| **c == "lock_memory")
        .count();
    assert_eq!(locks, 1);
    assert!(r.locked.is_some());
    let fails = Fake {
        lock_ok: false,
        ..safe()
    };
    assert!(run(&fails, MEM).unwrap().locked.is_none());
}

// oracle: A §12.8 (refuse when swap is unencrypted); a probe that cannot answer is not evidence of
// safety, so the check fails closed
#[spec("SR-12.8-4")]
#[test]
fn p4_platform_a_probe_that_cannot_answer_fails_closed() {
    let f = Fake {
        swaps: Err(ProbeError),
        ..safe()
    };
    assert_eq!(refused(&f, NONE), Some("§12.8 swap not encrypted"));
    let unknown_data_dir = startup(&safe(), Path::new("/elsewhere"), &keys(), NONE);
    assert_eq!(
        unknown_data_dir.err(),
        Some(Error::PlatformUnsafe {
            check: "§12.9 data filesystem not ext4 or XFS"
        })
    );
}

// oracle: A §12.8 and §12.9; each override is recorded (DB-90), all of them when several apply
#[spec("SR-12.8-4", "SR-12.9-4")]
#[test]
fn p4_platform_every_overridden_check_is_reported_in_order() {
    let worst = Fake {
        data_fs: V9FS,
        key_fs: V9FS,
        swaps: Ok(vec![swap("/dev/sdc", "partition", None)]),
        hibernation: hib("freeze mem disk\n", "8:33\n"),
        lock_ok: false,
        ..safe()
    };
    let both = Overrides {
        allow_unsafe_memory: true,
        allow_unsafe_fs: true,
    };
    assert_eq!(
        run(&worst, both).unwrap().overridden,
        vec![
            "§12.8 swap not encrypted",
            "§12.8 hibernation enabled",
            "§12.8 mlock",
            "§12.9 data filesystem not ext4 or XFS",
            "§12.9 key filesystem does not overwrite in place",
        ]
    );
}

// oracle: B proc(5) `/proc/swaps` (a header line, then Filename Type Size Used Priority; the
// kernel escapes space, tab, newline and backslash in names as \ooo)
#[spec("SR-12.8-5")]
#[test]
fn p4_platform_proc_swaps_is_parsed_with_escaped_names() {
    let text = "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n\
                /dev/sdc                                partition\t3145728\t\t2297796\t\t-2\n\
                /var/my\\040swap                         file\t\t1048576\t\t0\t\t-3\n\
                /dev/zram0                              partition\t4194300\t\t0\t\t100\n";
    assert_eq!(
        parse_swaps(text),
        vec![
            ("/dev/sdc".to_owned(), "partition".to_owned()),
            ("/var/my swap".to_owned(), "file".to_owned()),
            ("/dev/zram0".to_owned(), "partition".to_owned()),
        ]
    );
    assert!(parse_swaps("Filename\tType\tSize\tUsed\tPriority\n").is_empty());
}

// oracle: D the frozen EP-4 suite on the provider (Build 3-4 §2.8 L7)
#[test]
fn p4_platform_ep4_mlock_provider_passes_contract() {
    let p = MlockProvider::new(&LockedMemory(()));
    sever_types::contract::ep4_provider_contract(&p).unwrap();
}
