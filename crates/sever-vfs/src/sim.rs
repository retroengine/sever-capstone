//! `SimVfs` (spec §12.2): an in-memory, seeded file system with a conservative crash model.
//!
//! Every file has two views. The **current** view is what reads see (the page cache). The
//! **durable** view is what is certainly on disk. Each write goes to the current view and is
//! queued as *pending*; `fsync` moves the file's pending writes into its durable view. Directories
//! work the same way: creations, renames and unlinks change the current entries and are queued
//! until `fsync_dir` of that directory.
//!
//! A simulated crash keeps the durable views, plus whatever part of the pending changes the
//! [`CrashPolicy`] lets through: none (`DropAll`, the conservative reading of §12.2), all in
//! order (`KeepAll`), or a seeded choice (`Random`) that drops writes, reorders the rest and tears
//! any of them at any byte, and keeps a random prefix of each directory's changes. A file whose
//! directory entry was never made durable is gone, whatever its data.
//!
//! A failed `fsync` behaves as Linux does after a write-back error: the pending writes are
//! dropped from the durable path but stay visible to reads, so a retried `fsync` "succeeds"
//! without saving them. This is why a failed `fsync` must abort the process (§12.7, SB-14).

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::io::ErrorKind;
use std::sync::{Arc, Mutex, MutexGuard};

use crate::rng::SplitMix64;
use crate::{OpenMode, Vfs, VfsError, VfsFile, VfsOp, check_path};

/// Files larger than this are refused (`FileTooLarge`): the simulation holds everything in RAM.
const MAX_FILE: u64 = 1 << 32;

type Ino = u64;
const ROOT: Ino = 0;

/// What survives a simulated crash, beyond the durable state.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum CrashPolicy {
    /// Nothing unsynced survives: only `fsync`ed data and `fsync_dir`ed entries (spec §12.2).
    DropAll,
    /// Every unsynced change reached the disk, in order (except writes lost to a failed `fsync`).
    KeepAll,
    /// Seeded: each unsynced write is kept or dropped, the kept ones land in a shuffled order and
    /// each may be torn at any byte; each directory keeps a random prefix of its unsynced changes.
    Random(u64),
}

/// Faults to inject, counted from the moment the plan is set ([`SimVfs::set_faults`]).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct FaultPlan {
    /// The process crashes **during** the n-th mutating operation (1-based): the operation does
    /// not complete and every later call returns [`VfsError::Crashed`]. Mutating operations are
    /// `write_at`, `append`, `truncate`, `fsync`, `fsync_dir`, `rename`, `unlink`, `create_dir`,
    /// `remove_dir`, and an `open` that creates a file.
    pub crash_at_op: Option<u64>,
    /// When the crashing operation is a write: how many of its leading bytes reach the page cache
    /// first (clamped to its length). They are unsynced, so the [`CrashPolicy`] decides their fate.
    pub tear_bytes: usize,
    /// The n-th `fsync` or `fsync_dir` (1-based) fails with [`VfsError::Io`].
    pub fail_sync_at: Option<u64>,
}

/// Counters since creation or [`SimVfs::reset_stats`] (overview T-11: bytes and `fsync`s per
/// operation).
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct SimStats {
    /// Mutating operations (see [`FaultPlan::crash_at_op`]).
    pub mutating_ops: u64,
    /// File `fsync`s.
    pub fsyncs: u64,
    /// Directory `fsync`s.
    pub dir_fsyncs: u64,
    /// Bytes passed to `write_at` and `append`.
    pub bytes_written: u64,
}

#[derive(Clone, Debug)]
enum DataOp {
    Write { off: u64, data: Vec<u8> },
    SetLen(u64),
}

#[derive(Clone, Debug, Default)]
struct FileNode {
    current: Vec<u8>,
    durable: Vec<u8>,
    pending: Vec<DataOp>,
}

#[derive(Clone, Debug)]
enum DirOp {
    Put(String, Ino),
    Remove(String),
    /// A rename inside one directory is one atomic change.
    Rename(String, String),
}

#[derive(Clone, Debug, Default)]
struct DirNode {
    current: BTreeMap<String, Ino>,
    durable: BTreeMap<String, Ino>,
    pending: Vec<DirOp>,
}

impl DirNode {
    fn put(&mut self, name: &str, ino: Ino) {
        self.current.insert(name.to_owned(), ino);
        self.pending.push(DirOp::Put(name.to_owned(), ino));
    }
    fn remove(&mut self, name: &str) {
        self.current.remove(name);
        self.pending.push(DirOp::Remove(name.to_owned()));
    }
}

#[derive(Clone, Debug)]
enum Node {
    File(FileNode),
    Dir(DirNode),
}

#[derive(Clone, Debug)]
struct State {
    nodes: BTreeMap<Ino, Node>,
    next_ino: Ino,
    generation: u64,
    crashed: bool,
    plan: FaultPlan,
    ops: u64,
    syncs: u64,
    stats: SimStats,
}

fn apply_data(buf: &mut Vec<u8>, op: &DataOp) {
    match op {
        DataOp::Write { off, data } => {
            // Offsets were checked against MAX_FILE when the write was issued.
            let start = usize::try_from(*off).unwrap_or(usize::MAX);
            let end = start.saturating_add(data.len());
            if buf.len() < end {
                buf.resize(end, 0);
            }
            if let Some(dst) = buf.get_mut(start..end) {
                dst.copy_from_slice(data);
            }
        }
        DataOp::SetLen(len) => buf.resize(usize::try_from(*len).unwrap_or(usize::MAX), 0),
    }
}

fn apply_dir(map: &mut BTreeMap<String, Ino>, op: &DirOp) {
    match op {
        DirOp::Put(name, ino) => {
            map.insert(name.clone(), *ino);
        }
        DirOp::Remove(name) => {
            map.remove(name);
        }
        DirOp::Rename(from, to) => {
            if let Some(ino) = map.remove(from) {
                map.insert(to.clone(), ino);
            }
        }
    }
}

fn too_large(op: VfsOp) -> VfsError {
    VfsError::Io {
        op,
        kind: ErrorKind::FileTooLarge,
    }
}

impl State {
    fn new() -> Self {
        let mut nodes = BTreeMap::new();
        nodes.insert(ROOT, Node::Dir(DirNode::default()));
        Self {
            nodes,
            next_ino: ROOT + 1,
            generation: 0,
            crashed: false,
            plan: FaultPlan::default(),
            ops: 0,
            syncs: 0,
            stats: SimStats::default(),
        }
    }

    fn alive(&self) -> Result<(), VfsError> {
        if self.crashed {
            Err(VfsError::Crashed)
        } else {
            Ok(())
        }
    }

    fn handle_alive(&self, generation: u64) -> Result<(), VfsError> {
        self.alive()?;
        if generation == self.generation {
            Ok(())
        } else {
            Err(VfsError::Crashed)
        }
    }

    /// Counts one mutating operation; `true` means the process dies during it.
    fn begin_mut(&mut self) -> Result<bool, VfsError> {
        self.alive()?;
        self.ops += 1;
        self.stats.mutating_ops += 1;
        Ok(self.plan.crash_at_op == Some(self.ops))
    }

    /// Counts one `fsync` or `fsync_dir`; `true` means it fails.
    fn begin_sync(&mut self) -> bool {
        self.syncs += 1;
        self.plan.fail_sync_at == Some(self.syncs)
    }

    fn die(&mut self) -> VfsError {
        self.crashed = true;
        VfsError::Crashed
    }

    fn dir(&self, ino: Ino) -> Result<&DirNode, VfsError> {
        match self.nodes.get(&ino) {
            Some(Node::Dir(d)) => Ok(d),
            Some(Node::File(_)) => Err(VfsError::NotADirectory),
            None => Err(VfsError::NotFound),
        }
    }

    fn dir_mut(&mut self, ino: Ino) -> Result<&mut DirNode, VfsError> {
        match self.nodes.get_mut(&ino) {
            Some(Node::Dir(d)) => Ok(d),
            Some(Node::File(_)) => Err(VfsError::NotADirectory),
            None => Err(VfsError::NotFound),
        }
    }

    fn file(&self, ino: Ino) -> Result<&FileNode, VfsError> {
        match self.nodes.get(&ino) {
            Some(Node::File(f)) => Ok(f),
            Some(Node::Dir(_)) => Err(VfsError::IsADirectory),
            None => Err(VfsError::NotFound),
        }
    }

    fn file_mut(&mut self, ino: Ino) -> Result<&mut FileNode, VfsError> {
        match self.nodes.get_mut(&ino) {
            Some(Node::File(f)) => Ok(f),
            Some(Node::Dir(_)) => Err(VfsError::IsADirectory),
            None => Err(VfsError::NotFound),
        }
    }

    fn is_dir(&self, ino: Ino) -> bool {
        matches!(self.nodes.get(&ino), Some(Node::Dir(_)))
    }

    /// Follows `comps` through the current entries.
    fn walk(&self, comps: &[&str]) -> Result<Ino, VfsError> {
        let mut cur = ROOT;
        for c in comps {
            cur = *self.dir(cur)?.current.get(*c).ok_or(VfsError::NotFound)?;
        }
        Ok(cur)
    }

    /// The parent directory and last name of a non-root path.
    fn walk_parent<'p>(&self, path: &'p str) -> Result<(Ino, &'p str), VfsError> {
        let comps = check_path(path)?;
        let (name, dirs) = comps.split_last().ok_or(VfsError::InvalidPath)?;
        let parent = self.walk(dirs)?;
        self.dir(parent)?;
        Ok((parent, name))
    }

    fn child(&self, parent: Ino, name: &str) -> Option<Ino> {
        self.dir(parent)
            .ok()
            .and_then(|d| d.current.get(name).copied())
    }

    fn new_node(&mut self, node: Node) -> Ino {
        let ino = self.next_ino;
        self.next_ino += 1;
        self.nodes.insert(ino, node);
        ino
    }

    fn write(
        &mut self,
        generation: u64,
        ino: Ino,
        at: Option<u64>,
        data: &[u8],
    ) -> Result<u64, VfsError> {
        self.handle_alive(generation)?;
        let off = match at {
            Some(off) => off,
            None => self.file(ino)?.current.len() as u64,
        };
        self.file(ino)?;
        off.checked_add(data.len() as u64)
            .filter(|end| *end <= MAX_FILE)
            .ok_or(too_large(VfsOp::Write))?;
        let crash = self.begin_mut()?;
        let landed = if crash {
            data.get(..self.plan.tear_bytes.min(data.len()))
                .unwrap_or_default()
        } else {
            data
        };
        if !landed.is_empty() {
            self.stats.bytes_written += landed.len() as u64;
            let op = DataOp::Write {
                off,
                data: landed.to_vec(),
            };
            let f = self.file_mut(ino)?;
            apply_data(&mut f.current, &op);
            f.pending.push(op);
        }
        if crash { Err(self.die()) } else { Ok(off) }
    }

    /// The state after a power cut and reboot under `policy`.
    fn restart(&mut self, policy: CrashPolicy) {
        let mut rng = SplitMix64::new(match policy {
            CrashPolicy::Random(seed) => seed,
            _ => 0,
        });
        // 1. Directory entries: the durable entries plus a prefix of the unsynced changes.
        let mut dirs: BTreeMap<Ino, BTreeMap<String, Ino>> = BTreeMap::new();
        for (ino, node) in &self.nodes {
            if let Node::Dir(d) = node {
                let keep = match policy {
                    CrashPolicy::DropAll => 0,
                    CrashPolicy::KeepAll => d.pending.len(),
                    CrashPolicy::Random(_) => rng.below(d.pending.len() as u64 + 1) as usize,
                };
                let mut m = d.durable.clone();
                for op in d.pending.iter().take(keep) {
                    apply_dir(&mut m, op);
                }
                dirs.insert(*ino, m);
            }
        }
        // 2. File contents: the durable bytes plus the unsynced writes the policy lets through.
        let mut files: BTreeMap<Ino, Vec<u8>> = BTreeMap::new();
        for (ino, node) in &self.nodes {
            if let Node::File(f) = node {
                let mut bytes = f.durable.clone();
                match policy {
                    CrashPolicy::DropAll => {}
                    CrashPolicy::KeepAll => {
                        f.pending.iter().for_each(|op| apply_data(&mut bytes, op))
                    }
                    CrashPolicy::Random(_) => {
                        let mut kept: Vec<DataOp> = f
                            .pending
                            .iter()
                            .filter(|_| rng.one_in(2))
                            .cloned()
                            .collect();
                        for i in (1..kept.len()).rev() {
                            kept.swap(i, rng.below(i as u64 + 1) as usize);
                        }
                        for mut op in kept {
                            if let DataOp::Write { data, .. } = &mut op {
                                if data.len() > 1 && rng.one_in(4) {
                                    data.truncate(1 + rng.below(data.len() as u64 - 1) as usize);
                                }
                            }
                            apply_data(&mut bytes, &op);
                        }
                    }
                }
                files.insert(*ino, bytes);
            }
        }
        // 3. Keep what is reachable from the root; a directory reached twice (possible after a
        //    half-durable move between directories) keeps its first entry, in name order.
        let mut reachable = BTreeSet::from([ROOT]);
        let mut queue = VecDeque::from([ROOT]);
        while let Some(d) = queue.pop_front() {
            let names: Vec<(String, Ino)> = dirs
                .get(&d)
                .map(|m| m.iter().map(|(k, v)| (k.clone(), *v)).collect())
                .unwrap_or_default();
            for (name, child) in names {
                let seen_dir = dirs.contains_key(&child) && reachable.contains(&child);
                let known = dirs.contains_key(&child) || files.contains_key(&child);
                if seen_dir || !known {
                    if let Some(m) = dirs.get_mut(&d) {
                        m.remove(&name);
                    }
                    continue;
                }
                if reachable.insert(child) && dirs.contains_key(&child) {
                    queue.push_back(child);
                }
            }
        }
        let mut nodes = BTreeMap::new();
        for ino in reachable {
            if let Some(m) = dirs.remove(&ino) {
                nodes.insert(
                    ino,
                    Node::Dir(DirNode {
                        current: m.clone(),
                        durable: m,
                        pending: Vec::new(),
                    }),
                );
            } else if let Some(b) = files.remove(&ino) {
                nodes.insert(
                    ino,
                    Node::File(FileNode {
                        current: b.clone(),
                        durable: b,
                        pending: Vec::new(),
                    }),
                );
            }
        }
        self.nodes = nodes;
        self.generation += 1;
        self.crashed = false;
        self.plan = FaultPlan::default();
        self.ops = 0;
        self.syncs = 0;
    }
}

/// The in-memory backend. Clones share one file system (so a test can keep a handle on the
/// engine's disk); [`SimVfs::fork`] makes an independent copy.
#[derive(Clone, Debug)]
pub struct SimVfs {
    state: Arc<Mutex<State>>,
}

impl Default for SimVfs {
    fn default() -> Self {
        Self::new()
    }
}

impl SimVfs {
    /// An empty file system: only the root directory, which is durable.
    pub fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(State::new())),
        }
    }

    fn lock(&self) -> MutexGuard<'_, State> {
        // A panic while holding the lock leaves a consistent state (every method mutates only
        // after its checks), so a poisoned lock is still usable.
        self.state.lock().unwrap_or_else(|p| p.into_inner())
    }

    /// An independent copy of the whole simulation (files, pending changes, faults, crash flag).
    /// Handles opened on `self` stay bound to `self`.
    pub fn fork(&self) -> Self {
        let copy = self.lock().clone();
        Self {
            state: Arc::new(Mutex::new(copy)),
        }
    }

    /// Installs `plan` and restarts its operation and `fsync` counts from zero.
    pub fn set_faults(&self, plan: FaultPlan) {
        let mut st = self.lock();
        st.plan = plan;
        st.ops = 0;
        st.syncs = 0;
    }

    /// Mutating operations since the fault plan was set (or since the last restart).
    pub fn ops_since_plan(&self) -> u64 {
        self.lock().ops
    }

    /// The simulated process dies now: every later call, and every open handle, returns
    /// [`VfsError::Crashed`] until [`SimVfs::restart`].
    pub fn crash(&self) {
        self.lock().crashed = true;
    }

    /// True after a crash, until the restart.
    pub fn is_crashed(&self) -> bool {
        self.lock().crashed
    }

    /// Power cut (if the process has not crashed already) and reboot: the file system becomes
    /// what `policy` lets survive, every handle from before stays dead, and the fault plan is
    /// cleared.
    pub fn restart(&self, policy: CrashPolicy) {
        self.lock().restart(policy);
    }

    /// The counters.
    pub fn stats(&self) -> SimStats {
        self.lock().stats
    }

    /// Sets the counters to zero.
    pub fn reset_stats(&self) {
        self.lock().stats = SimStats::default();
    }
}

impl Vfs for SimVfs {
    fn open(&self, path: &str, mode: OpenMode) -> Result<Box<dyn VfsFile>, VfsError> {
        let mut st = self.lock();
        st.alive()?;
        if path.is_empty() {
            return Err(VfsError::IsADirectory);
        }
        let (parent, name) = st.walk_parent(path)?;
        let ino = match (st.child(parent, name), mode) {
            (Some(ino), _) if st.is_dir(ino) => return Err(VfsError::IsADirectory),
            (Some(_), OpenMode::CreateNew) => return Err(VfsError::AlreadyExists),
            (Some(ino), _) => ino,
            (None, OpenMode::Existing) => return Err(VfsError::NotFound),
            (None, _) => {
                if st.begin_mut()? {
                    return Err(st.die());
                }
                let ino = st.new_node(Node::File(FileNode::default()));
                st.dir_mut(parent)?.put(name, ino);
                ino
            }
        };
        Ok(Box::new(SimFile {
            state: Arc::clone(&self.state),
            ino,
            generation: st.generation,
        }))
    }

    fn fsync_dir(&self, dir: &str) -> Result<(), VfsError> {
        let mut st = self.lock();
        st.alive()?;
        let ino = st.walk(&check_path(dir)?)?;
        st.dir(ino)?;
        if st.begin_mut()? {
            return Err(st.die());
        }
        st.stats.dir_fsyncs += 1;
        let fail = st.begin_sync();
        let d = st.dir_mut(ino)?;
        if fail {
            // Like a failed write-back: the changes stay visible but never become durable.
            d.pending.clear();
            return Err(VfsError::Io {
                op: VfsOp::FsyncDir,
                kind: ErrorKind::Other,
            });
        }
        for op in std::mem::take(&mut d.pending) {
            apply_dir(&mut d.durable, &op);
        }
        Ok(())
    }

    fn rename(&self, from: &str, to: &str) -> Result<(), VfsError> {
        let mut st = self.lock();
        st.alive()?;
        let (f, t) = (check_path(from)?, check_path(to)?);
        if f.is_empty() || t.is_empty() || t.starts_with(&f) {
            return Err(VfsError::InvalidPath);
        }
        let (pf, fname) = st.walk_parent(from)?;
        let (pt, tname) = st.walk_parent(to)?;
        let ino = st.child(pf, fname).ok_or(VfsError::NotFound)?;
        if let Some(existing) = st.child(pt, tname) {
            if st.is_dir(existing) {
                return Err(VfsError::IsADirectory);
            }
            if st.is_dir(ino) {
                return Err(VfsError::AlreadyExists);
            }
        }
        if st.begin_mut()? {
            return Err(st.die());
        }
        if pf == pt {
            let d = st.dir_mut(pf)?;
            apply_dir(
                &mut d.current,
                &DirOp::Rename(fname.to_owned(), tname.to_owned()),
            );
            d.pending
                .push(DirOp::Rename(fname.to_owned(), tname.to_owned()));
        } else {
            st.dir_mut(pf)?.remove(fname);
            st.dir_mut(pt)?.put(tname, ino);
        }
        Ok(())
    }

    fn unlink(&self, path: &str) -> Result<(), VfsError> {
        let mut st = self.lock();
        st.alive()?;
        if path.is_empty() {
            return Err(VfsError::IsADirectory);
        }
        let (parent, name) = st.walk_parent(path)?;
        let ino = st.child(parent, name).ok_or(VfsError::NotFound)?;
        if st.is_dir(ino) {
            return Err(VfsError::IsADirectory);
        }
        if st.begin_mut()? {
            return Err(st.die());
        }
        st.dir_mut(parent)?.remove(name);
        Ok(())
    }

    fn list(&self, dir: &str) -> Result<Vec<String>, VfsError> {
        let st = self.lock();
        st.alive()?;
        let ino = st.walk(&check_path(dir)?)?;
        // BTreeMap<String, _> iterates in byte order of the UTF-8 names.
        Ok(st.dir(ino)?.current.keys().cloned().collect())
    }

    fn create_dir(&self, path: &str) -> Result<(), VfsError> {
        let mut st = self.lock();
        st.alive()?;
        if path.is_empty() {
            return Err(VfsError::AlreadyExists);
        }
        let (parent, name) = st.walk_parent(path)?;
        if st.child(parent, name).is_some() {
            return Err(VfsError::AlreadyExists);
        }
        if st.begin_mut()? {
            return Err(st.die());
        }
        let ino = st.new_node(Node::Dir(DirNode::default()));
        st.dir_mut(parent)?.put(name, ino);
        Ok(())
    }

    fn remove_dir(&self, path: &str) -> Result<(), VfsError> {
        let mut st = self.lock();
        st.alive()?;
        if path.is_empty() {
            return Err(VfsError::InvalidPath);
        }
        let (parent, name) = st.walk_parent(path)?;
        let ino = st.child(parent, name).ok_or(VfsError::NotFound)?;
        if !st.dir(ino)?.current.is_empty() {
            return Err(VfsError::DirectoryNotEmpty);
        }
        if st.begin_mut()? {
            return Err(st.die());
        }
        st.dir_mut(parent)?.remove(name);
        Ok(())
    }
}

struct SimFile {
    state: Arc<Mutex<State>>,
    ino: Ino,
    generation: u64,
}

impl SimFile {
    fn lock(&self) -> MutexGuard<'_, State> {
        self.state.lock().unwrap_or_else(|p| p.into_inner())
    }
}

impl VfsFile for SimFile {
    fn read_at(&self, offset: u64, buf: &mut [u8]) -> Result<usize, VfsError> {
        let st = self.lock();
        st.handle_alive(self.generation)?;
        let cur = &st.file(self.ino)?.current;
        let start = usize::try_from(offset).unwrap_or(usize::MAX).min(cur.len());
        let src = cur.get(start..).unwrap_or_default();
        let n = src.len().min(buf.len());
        if let (Some(dst), Some(src)) = (buf.get_mut(..n), src.get(..n)) {
            dst.copy_from_slice(src);
        }
        Ok(n)
    }

    fn write_at(&mut self, offset: u64, data: &[u8]) -> Result<(), VfsError> {
        self.lock()
            .write(self.generation, self.ino, Some(offset), data)
            .map(|_| ())
    }

    fn append(&mut self, data: &[u8]) -> Result<u64, VfsError> {
        self.lock().write(self.generation, self.ino, None, data)
    }

    fn truncate(&mut self, len: u64) -> Result<(), VfsError> {
        let mut st = self.lock();
        st.handle_alive(self.generation)?;
        st.file(self.ino)?;
        if len > MAX_FILE {
            return Err(too_large(VfsOp::Truncate));
        }
        if st.begin_mut()? {
            return Err(st.die());
        }
        let f = st.file_mut(self.ino)?;
        let op = DataOp::SetLen(len);
        apply_data(&mut f.current, &op);
        f.pending.push(op);
        Ok(())
    }

    fn len(&self) -> Result<u64, VfsError> {
        let st = self.lock();
        st.handle_alive(self.generation)?;
        Ok(st.file(self.ino)?.current.len() as u64)
    }

    fn fsync(&mut self) -> Result<(), VfsError> {
        let mut st = self.lock();
        st.handle_alive(self.generation)?;
        st.file(self.ino)?;
        if st.begin_mut()? {
            return Err(st.die());
        }
        st.stats.fsyncs += 1;
        let fail = st.begin_sync();
        let f = st.file_mut(self.ino)?;
        if fail {
            // Linux after a write-back error: the pages are marked clean, the data never reaches
            // the disk, and a retried fsync reports success.
            f.pending.clear();
            return Err(VfsError::Io {
                op: VfsOp::Fsync,
                kind: ErrorKind::Other,
            });
        }
        for op in std::mem::take(&mut f.pending) {
            apply_data(&mut f.durable, &op);
        }
        Ok(())
    }
}
