//! `sever-checkpoint`: storage checkpoints (Part 2, Build §5.5; spec §12.4, §15.6).
//!
//! A storage checkpoint writes the whole storage image to a new directory and installs it
//! atomically:
//!
//! 1. serialise into `checkpoint/<new>.tmp/`; `fsync` every file and the directories;
//! 2. rename it to `checkpoint/<new>/`; `fsync` `checkpoint/`;
//! 3. write `MANIFEST.tmp` naming the new checkpoint and the first WAL position still needed;
//!    `fsync`; rename to `MANIFEST`; `fsync` the directory;
//! 4. delete older checkpoints (the caller then removes the covered WAL segments).
//!
//! `MANIFEST` is the commit point: a crash at any step leaves the previous checkpoint named by
//! `MANIFEST`, whole (§12.4). Leftover directories are removed at the next load.

use sever_format::codec::bad;
use sever_format::image::{CheckpointMeta, CheckpointStreams};
use sever_format::{CollectionMeta, DbImage, Layout, Manifest, magic, paged};
use sever_types::{CollectionId, Error};
use sever_vfs::{OpenMode, Vfs, VfsError, durable, read_all};

/// The checkpoints directory.
pub const CHECKPOINT_DIR: &str = "checkpoint";
/// The manifest file.
pub const MANIFEST: &str = "MANIFEST";

fn io(_: VfsError) -> Error {
    Error::DurabilityFailure
}

/// `checkpoint/<id, 20 digits>`.
pub fn checkpoint_path(id: u64) -> String {
    format!("{CHECKPOINT_DIR}/{id:020}")
}

/// `partitions/<collection_id as 32 lowercase hex>.svp`.
pub fn partition_name(cid: &CollectionId) -> String {
    let hex: String = cid.as_bytes().iter().map(|b| format!("{b:02x}")).collect();
    format!("{hex}.svp")
}

/// The files of a checkpoint and their magics, in write order.
const FILES: [(&str, [u8; 8]); 6] = [
    ("meta.bin", magic::META),
    ("collections.bin", magic::COLLECTIONS),
    ("groups.bin", magic::GROUPS),
    ("slots.bin", magic::SLOTS),
    ("locator.bin", magic::LOCATOR),
    ("payloads.bin", magic::PAYLOAD_REFS),
];

fn stream<'a>(s: &'a CheckpointStreams, name: &str) -> &'a [u8] {
    match name {
        "meta.bin" => &s.meta,
        "collections.bin" => &s.collections,
        "groups.bin" => &s.groups,
        "slots.bin" => &s.slots,
        "locator.bin" => &s.locator,
        _ => &s.payload_refs,
    }
}

fn stream_mut<'a>(s: &'a mut CheckpointStreams, name: &str) -> &'a mut Vec<u8> {
    match name {
        "meta.bin" => &mut s.meta,
        "collections.bin" => &mut s.collections,
        "groups.bin" => &mut s.groups,
        "slots.bin" => &mut s.slots,
        "locator.bin" => &mut s.locator,
        _ => &mut s.payload_refs,
    }
}

fn write_file(vfs: &dyn Vfs, path: &str, bytes: &[u8]) -> Result<(), Error> {
    let mut f = vfs.open(path, OpenMode::CreateNew).map_err(io)?;
    f.write_at(0, bytes).map_err(io)?;
    durable::sync(f.as_mut()).map_err(io)
}

/// Removes a directory tree (checkpoint directories are two levels deep at most).
fn remove_tree(vfs: &dyn Vfs, dir: &str) -> Result<(), Error> {
    for name in vfs.list(dir).map_err(io)? {
        let path = format!("{dir}/{name}");
        match vfs.unlink(&path) {
            Ok(()) => {}
            Err(VfsError::IsADirectory) => remove_tree(vfs, &path)?,
            Err(e) => return Err(io(e)),
        }
    }
    vfs.remove_dir(dir).map_err(io)
}

/// Creates `checkpoint/` for a new database (durably).
pub fn create_root(vfs: &dyn Vfs) -> Result<(), Error> {
    durable::create_dir(vfs, CHECKPOINT_DIR).map_err(io)
}

/// Steps 1–3 of §15.6: writes `img` as checkpoint `meta.checkpoint_id` and installs it. When this
/// returns `Ok`, `MANIFEST` names the new checkpoint durably; older checkpoints still exist.
pub fn write(
    vfs: &dyn Vfs,
    sealer_id: u16,
    img: &DbImage,
    meta: &CheckpointMeta,
    layout_of: &dyn Fn(&CollectionMeta) -> Layout,
) -> Result<(), Error> {
    let streams = img.to_streams(meta, layout_of)?;
    let dir = checkpoint_path(meta.checkpoint_id);
    let tmp = format!("{dir}.tmp");
    // A leftover from an interrupted attempt with the same ID is garbage.
    match vfs.list(&tmp) {
        Ok(_) => remove_tree(vfs, &tmp)?,
        Err(VfsError::NotFound) => {}
        Err(e) => return Err(io(e)),
    }
    // 1. Serialise into <new>.tmp/ and fsync every file and directory.
    vfs.create_dir(&tmp).map_err(io)?;
    for (name, m) in FILES {
        let bytes = paged::encode(&m, sealer_id, meta.next_wal_seq, stream(&streams, name));
        write_file(vfs, &format!("{tmp}/{name}"), &bytes)?;
    }
    let parts = format!("{tmp}/partitions");
    vfs.create_dir(&parts).map_err(io)?;
    for (cid, artefact) in &streams.artefacts {
        write_file(vfs, &format!("{parts}/{}", partition_name(cid)), artefact)?;
    }
    durable::sync_dir(vfs, &parts).map_err(io)?;
    durable::sync_dir(vfs, &tmp).map_err(io)?;
    durable::sync_dir(vfs, CHECKPOINT_DIR).map_err(io)?;
    // 2. Rename into place; fsync checkpoint/.
    durable::rename(vfs, &tmp, &dir).map_err(io)?;
    // 3. Install MANIFEST (tmp, fsync, rename, fsync the directory).
    let manifest = Manifest {
        sealer_id,
        checkpoint_id: meta.checkpoint_id,
        first_wal_seq: meta.next_wal_seq,
    };
    durable::replace_file(vfs, MANIFEST, &manifest.encode()).map_err(io)
}

/// Step 4 of §15.6 (checkpoints only): removes every checkpoint directory other than `keep`,
/// including leftover `.tmp` directories. Each removal is made durable.
pub fn remove_others(vfs: &dyn Vfs, keep: u64) -> Result<u64, Error> {
    let keep_name = format!("{keep:020}");
    let mut removed = 0;
    for name in vfs.list(CHECKPOINT_DIR).map_err(io)? {
        if name != keep_name {
            remove_tree(vfs, &format!("{CHECKPOINT_DIR}/{name}"))?;
            removed += 1;
        }
    }
    if removed > 0 {
        durable::sync_dir(vfs, CHECKPOINT_DIR).map_err(io)?;
    }
    Ok(removed)
}

/// Reads `MANIFEST`. `Ok(None)` when there is none: no database exists here.
pub fn read_manifest(vfs: &dyn Vfs, sealer_id: u16) -> Result<Option<Manifest>, Error> {
    match vfs.open(MANIFEST, OpenMode::Existing) {
        Ok(f) => {
            let bytes = read_all(f.as_ref()).map_err(|_| bad("§14.1 MANIFEST"))?;
            Manifest::parse(&bytes, sealer_id).map(Some)
        }
        Err(VfsError::NotFound) => Ok(None),
        Err(_) => Err(bad("§14.1 MANIFEST")),
    }
}

/// Loads the checkpoint `MANIFEST` names (§15.7 step 3). Every file must parse strictly, carry
/// the manifest's WAL position, and agree with the manifest's ID.
pub fn load(
    vfs: &dyn Vfs,
    manifest: &Manifest,
    layout_of: &dyn Fn(&CollectionMeta) -> Layout,
) -> Result<(CheckpointMeta, DbImage), Error> {
    let dir = checkpoint_path(manifest.checkpoint_id);
    let read = |path: &str| -> Result<Vec<u8>, Error> {
        let f = vfs
            .open(path, OpenMode::Existing)
            .map_err(|_| bad("§14.1 checkpoint file missing"))?;
        read_all(f.as_ref()).map_err(|_| bad("§14.1 checkpoint file"))
    };
    let mut streams = CheckpointStreams::default();
    for (name, m) in FILES {
        let (seq, s) = paged::decode(&read(&format!("{dir}/{name}"))?, &m, manifest.sealer_id)?;
        if seq != manifest.first_wal_seq {
            return Err(bad("§15.6 checkpoint WAL position"));
        }
        *stream_mut(&mut streams, name) = s;
    }
    let parts = format!("{dir}/partitions");
    let mut names = vfs
        .list(&parts)
        .map_err(|_| bad("§14.1 partitions missing"))?;
    names.sort();
    for name in names {
        let bytes = read(&format!("{parts}/{name}"))?;
        // The collection whose ID gives this name; matched again by from_streams.
        let hex = name
            .strip_suffix(".svp")
            .ok_or(bad("§14.1 partition name"))?;
        let mut id = [0u8; 16];
        if hex.len() != 32 {
            return Err(bad("§14.1 partition name"));
        }
        for (i, b) in id.iter_mut().enumerate() {
            *b = hex
                .get(2 * i..2 * i + 2)
                .and_then(|h| u8::from_str_radix(h, 16).ok())
                .ok_or(bad("§14.1 partition name"))?;
        }
        let cid = CollectionId::from_bytes(id);
        if partition_name(&cid) != name {
            return Err(bad("§14.1 partition name"));
        }
        streams.artefacts.push((cid, bytes));
    }
    let (meta, img) = DbImage::from_streams(&streams, layout_of)?;
    if meta.checkpoint_id != manifest.checkpoint_id || meta.next_wal_seq != manifest.first_wal_seq {
        return Err(bad("§15.6 checkpoint does not match MANIFEST"));
    }
    Ok((meta, img))
}

#[cfg(test)]
mod tests;
