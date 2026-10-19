//! The refusal rules of spec §12.8–12.9 (as fixed by overview DB-90 and DB-93), each a pure
//! function of the probe's answers.

use crate::probe::{Hibernation, Swap};

/// `statfs` magic of ext2/3/4.
pub const EXT4_SUPER_MAGIC: i64 = 0xEF53;
/// `statfs` magic of XFS.
pub const XFS_SUPER_MAGIC: i64 = 0x5846_5342;
/// `statfs` magic of btrfs.
pub const BTRFS_SUPER_MAGIC: i64 = 0x9123_683E;

/// §12.8: one swap entry is encrypted when it is a zram device or a device-mapper device whose
/// `dm/uuid` starts with `CRYPT-`. Anything else, a swap file included, is not.
pub fn swap_entry_encrypted(s: &Swap) -> bool {
    let base = s.name.rsplit('/').next().unwrap_or_default();
    let zram = s.kind == "partition"
        && base
            .strip_prefix("zram")
            .is_some_and(|n| !n.is_empty() && n.bytes().all(|c| c.is_ascii_digit()));
    let dm_crypt = s
        .dm_uuid
        .as_deref()
        .is_some_and(|u| u.starts_with("CRYPT-"));
    zram || dm_crypt
}

/// §12.8: swap is safe when it is off or every active entry is encrypted.
pub fn swap_safe(entries: &[Swap]) -> bool {
    entries.iter().all(swap_entry_encrypted)
}

/// §12.8: hibernation is enabled when `/sys/power/state` lists `disk` and `/sys/power/resume` is
/// not `0:0`.
pub fn hibernation_enabled(h: &Hibernation) -> bool {
    let lists_disk = h
        .state
        .as_deref()
        .is_some_and(|s| s.split_whitespace().any(|w| w == "disk"));
    let resume_set = h.resume.as_deref().is_none_or(|r| r.trim() != "0:0");
    lists_disk && resume_set
}

/// §12.9: the data directory is on ext4 or XFS.
pub fn data_fs_ok(magic: i64) -> bool {
    magic == EXT4_SUPER_MAGIC || magic == XFS_SUPER_MAGIC
}

/// §12.9: the key file's filesystem overwrites in place: ext4, XFS, and btrfs only when `KEYS`
/// carries the no-copy-on-write attribute.
pub fn key_fs_ok(magic: i64, keys_no_cow: bool) -> bool {
    data_fs_ok(magic) || (magic == BTRFS_SUPER_MAGIC && keys_no_cow)
}
