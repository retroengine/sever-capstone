//! The wrapped-key store's recovery scan (DB-91) after a crash: a record the crash cut short at
//! the end of the newest segment was never synced, so it is dropped, as Part 2's append store
//! drops a torn tail (§12.2: only synced data survives a crash); damage in an older segment,
//! which was synced, is refused. Found by the Part 4 crash campaign (a `Random` crash during the
//! phase C append left a record with a complete length and a failing CRC).

use std::sync::Arc;

use sever_types::Error;
use sever_vfs::{OpenMode, SimVfs, Vfs};

use crate::store::{DIR, WrappedStore};

fn values(n: usize) -> Vec<Vec<u8>> {
    (0..n)
        .map(|i| vec![u8::try_from(i).unwrap(); 300])
        .collect()
}

fn segments(v: &SimVfs) -> Vec<String> {
    let mut s: Vec<String> = v.list(DIR).unwrap();
    s.sort();
    s
}

/// A record header with a complete length and a body that fails its CRC, at the end of `seg`.
fn tear(v: &SimVfs, seg: &str) {
    let mut f = v.open(&format!("{DIR}/{seg}"), OpenMode::Existing).unwrap();
    let mut rec = 99u64.to_be_bytes().to_vec();
    rec.extend_from_slice(&40u32.to_be_bytes());
    rec.extend_from_slice(&[0xA5; 44]); // 40 bytes of value and a 4-byte CRC that does not match
    f.append(&rec).unwrap();
    f.fsync().unwrap();
}

// oracle: A §12.2 (only synced data survives a crash; a cut-off tail is not data) and DB-91 (the
// store is scanned in order at recovery, like Part 2's append stores)
#[test]
fn p4_erasure_store_drops_a_torn_record_at_the_end_of_the_newest_segment() {
    let v = SimVfs::new();
    let (mut s, got) = WrappedStore::open(Arc::new(v.clone()), 1 << 20).unwrap();
    assert!(got.is_empty());
    s.append(&values(3)).unwrap();
    drop(s);
    let last = segments(&v).last().cloned().unwrap();
    tear(&v, &last);
    let (mut s, got) = WrappedStore::open(Arc::new(v.clone()), 1 << 20).unwrap();
    assert_eq!(
        got,
        values(3),
        "the torn record is dropped, the synced ones kept"
    );
    s.append(&values(4)[3..]).unwrap();
    drop(s);
    let (_, got) = WrappedStore::open(Arc::new(v.clone()), 1 << 20).unwrap();
    assert_eq!(got, values(4), "appends continue after the cut");
}

// oracle: A §12.2 and §17 IntegrityViolation: synced data that fails its check is corruption
#[test]
fn p4_erasure_store_refuses_a_damaged_record_in_an_older_segment() {
    let v = SimVfs::new();
    let (mut s, _) = WrappedStore::open(Arc::new(v.clone()), 1024).unwrap();
    for chunk in values(8).chunks(1) {
        s.append(chunk).unwrap();
    }
    drop(s);
    let segs = segments(&v);
    assert!(segs.len() >= 2, "{segs:?}");
    let mut f = v
        .open(&format!("{DIR}/{}", segs[0]), OpenMode::Existing)
        .unwrap();
    f.write_at(16 + 12 + 5, &[0x5A]).unwrap(); // inside the first record's value
    f.fsync().unwrap();
    drop(f);
    assert!(matches!(
        WrappedStore::open(Arc::new(v.clone()), 1024),
        Err(Error::IntegrityViolation { .. })
    ));
}

/// A disk with FUSE's (and NFS's) open-file semantics: a file unlinked while it is open stays in
/// its directory as a hidden entry until it is closed (libfuse without `hard_remove`, NFS "silly
/// rename"), so the directory cannot be removed while a file under it is open. Found by EX-2 on a
/// `fuse2fs` image: compaction removed `wrapped.old` while the old store still had a segment open.
/// Open files by handle number, with their current paths (a rename moves them).
type OpenFiles = Arc<std::sync::Mutex<Vec<(u64, String)>>>;

struct HiddenWhileOpen {
    inner: SimVfs,
    open: OpenFiles,
    next: std::sync::atomic::AtomicU64,
}

struct Tracked {
    inner: Box<dyn sever_vfs::VfsFile>,
    id: u64,
    open: OpenFiles,
}

impl Drop for Tracked {
    fn drop(&mut self) {
        self.open.lock().unwrap().retain(|(id, _)| *id != self.id);
    }
}

impl sever_vfs::VfsFile for Tracked {
    fn read_at(&self, off: u64, buf: &mut [u8]) -> Result<usize, sever_vfs::VfsError> {
        self.inner.read_at(off, buf)
    }
    fn write_at(&mut self, off: u64, d: &[u8]) -> Result<(), sever_vfs::VfsError> {
        self.inner.write_at(off, d)
    }
    fn append(&mut self, d: &[u8]) -> Result<u64, sever_vfs::VfsError> {
        self.inner.append(d)
    }
    fn truncate(&mut self, l: u64) -> Result<(), sever_vfs::VfsError> {
        self.inner.truncate(l)
    }
    fn len(&self) -> Result<u64, sever_vfs::VfsError> {
        self.inner.len()
    }
    fn fsync(&mut self) -> Result<(), sever_vfs::VfsError> {
        self.inner.fsync()
    }
}

impl Vfs for HiddenWhileOpen {
    fn open(
        &self,
        path: &str,
        mode: OpenMode,
    ) -> Result<Box<dyn sever_vfs::VfsFile>, sever_vfs::VfsError> {
        let inner = self.inner.open(path, mode)?;
        let id = self.next.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        self.open.lock().unwrap().push((id, path.to_owned()));
        Ok(Box::new(Tracked {
            inner,
            id,
            open: Arc::clone(&self.open),
        }))
    }
    fn fsync_dir(&self, d: &str) -> Result<(), sever_vfs::VfsError> {
        self.inner.fsync_dir(d)
    }
    fn rename(&self, from: &str, to: &str) -> Result<(), sever_vfs::VfsError> {
        // An open file moves with its directory.
        let mut o = self.open.lock().unwrap();
        for (_, p) in o.iter_mut() {
            if let Some(rest) = p.strip_prefix(&format!("{from}/")) {
                *p = format!("{to}/{rest}");
            }
        }
        drop(o);
        self.inner.rename(from, to)
    }
    fn unlink(&self, p: &str) -> Result<(), sever_vfs::VfsError> {
        self.inner.unlink(p)
    }
    fn list(&self, d: &str) -> Result<Vec<String>, sever_vfs::VfsError> {
        self.inner.list(d)
    }
    fn create_dir(&self, p: &str) -> Result<(), sever_vfs::VfsError> {
        self.inner.create_dir(p)
    }
    fn remove_dir(&self, p: &str) -> Result<(), sever_vfs::VfsError> {
        let prefix = format!("{p}/");
        if self
            .open
            .lock()
            .unwrap()
            .iter()
            .any(|(_, o)| o.starts_with(&prefix))
        {
            return Err(sever_vfs::VfsError::DirectoryNotEmpty);
        }
        self.inner.remove_dir(p)
    }
}

// oracle: A §14.8 (compaction swaps in a store holding exactly the live values) and §12.2 (a
// directory is removed only once it is empty; the platform decides when an open file's entry goes)
#[test]
fn p4_erasure_store_compaction_closes_the_old_store_before_removing_it() {
    let v = HiddenWhileOpen {
        inner: SimVfs::new(),
        open: Arc::default(),
        next: std::sync::atomic::AtomicU64::new(0),
    };
    let sim = v.inner.clone();
    let (mut s, _) = WrappedStore::open(Arc::new(v), 1 << 20).unwrap();
    s.append(&values(5)).unwrap();
    s.compact(&values(2)).unwrap();
    s.append(&values(3)[2..]).unwrap();
    drop(s);
    let (_, got) = WrappedStore::open(Arc::new(sim), 1 << 20).unwrap();
    assert_eq!(got, values(3));
}
