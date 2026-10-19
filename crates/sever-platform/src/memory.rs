//! The EP-4 provider of Part 4 (spec §12.8; overview DB-50, DB-93).
//!
//! Startup locks the whole process with `mlockall(MCL_CURRENT | MCL_FUTURE | MCL_ONFAULT)`
//! (DB-93), so every page the engine touches afterwards is locked: the key ring, the AES key
//! schedules, and the decrypted accumulators that the frozen Part 1 index keeps in ordinary
//! vectors. [`MlockProvider`] can only be made from the [`LockedMemory`] proof that the lock took
//! effect; its regions come from that locked heap and [`sever_types::SecretBuf`] zeroes them before
//! they are released.

use sever_types::{SecretMemory, SecretRegion};

/// Proof that the process's memory is locked; made only by [`crate::startup`].
#[derive(Debug)]
pub struct LockedMemory(pub(crate) ());

/// EP-4: secret buffers in locked memory.
#[derive(Debug)]
pub struct MlockProvider(());

impl MlockProvider {
    /// The provider, once memory is locked.
    pub fn new(_locked: &LockedMemory) -> Self {
        Self(())
    }
}

struct LockedRegion(Box<[u8]>);

impl SecretRegion for LockedRegion {
    fn bytes(&self) -> &[u8] {
        &self.0
    }
    fn bytes_mut(&mut self) -> &mut [u8] {
        &mut self.0
    }
}

impl SecretMemory for MlockProvider {
    fn allocate(&self, len: usize) -> Box<dyn SecretRegion> {
        Box::new(LockedRegion(vec![0u8; len].into_boxed_slice()))
    }
}
