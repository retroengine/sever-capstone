//! Secret buffers and extension point EP-4, the secret-memory provider (Build §3.3; overview
//! DB-50).
//!
//! A [`SecretMemory`] provider decides where secret bytes live. Part 1's default,
//! [`HeapProvider`], keeps them on the heap; Part 4 installs a provider that uses `mlock`ed pages
//! (spec §12.8). Whatever the provider, [`SecretBuf`] overwrites its bytes with zeros before
//! handing the region back (spec §12.8: every secret type zeroes on drop).
//!
//! The provider is the only global state in the code base (Build §1.1). It is installed once, by
//! the composition root, at startup. The first secret allocated without an installed provider
//! fixes the heap default, and a later install is refused, so no two secrets can ever come from
//! two different providers.

use core::fmt;
use std::sync::OnceLock;

use zeroize::Zeroize;

/// A block of memory handed out by a [`SecretMemory`] provider. Dropping it returns the memory
/// to the provider (for Part 4: `munlock` and free).
pub trait SecretRegion: Send + Sync {
    /// The bytes, read-only.
    fn bytes(&self) -> &[u8];
    /// The bytes, writable.
    fn bytes_mut(&mut self) -> &mut [u8];
}

/// EP-4: where secret buffers live.
///
/// Contract (checked by `contract::ep4_provider_contract`): `allocate(len)` returns a region of
/// exactly `len` bytes, all zero, that shares no memory with any other live region.
pub trait SecretMemory: Send + Sync {
    /// A fresh, zero-filled region of `len` bytes.
    fn allocate(&self, len: usize) -> Box<dyn SecretRegion>;
}

/// Part 1's default provider: the heap. Secrets are zeroed on release by [`SecretBuf`], but not
/// locked in memory (locking arrives with Part 4).
#[derive(Debug, Default, Clone, Copy)]
pub struct HeapProvider;

struct HeapRegion(Box<[u8]>);

impl SecretRegion for HeapRegion {
    fn bytes(&self) -> &[u8] {
        &self.0
    }
    fn bytes_mut(&mut self) -> &mut [u8] {
        &mut self.0
    }
}

impl SecretMemory for HeapProvider {
    fn allocate(&self, len: usize) -> Box<dyn SecretRegion> {
        Box::new(HeapRegion(vec![0u8; len].into_boxed_slice()))
    }
}

static PROVIDER: OnceLock<Box<dyn SecretMemory>> = OnceLock::new();

/// [`install_provider`] was called after a provider was already fixed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("a secret-memory provider is already installed")]
pub struct ProviderAlreadyInstalled;

/// Installs the process-wide provider. Call it once, from the composition root, before any secret
/// is allocated (DB-50). Refused if a provider is already fixed, including the heap default fixed
/// by an earlier allocation.
pub fn install_provider(provider: Box<dyn SecretMemory>) -> Result<(), ProviderAlreadyInstalled> {
    PROVIDER.set(provider).map_err(|_| ProviderAlreadyInstalled)
}

fn installed_provider() -> &'static dyn SecretMemory {
    PROVIDER.get_or_init(|| Box::new(HeapProvider)).as_ref()
}

/// A fixed-size buffer of secret bytes: zeroed before release, never cloned, never printed.
pub struct SecretBuf {
    region: Box<dyn SecretRegion>,
}

impl SecretBuf {
    /// `len` zero bytes from the installed provider.
    pub fn new(len: usize) -> Self {
        Self::new_in(installed_provider(), len)
    }

    /// `len` zero bytes from a given provider. Used by contract suites and tests; production code
    /// uses [`SecretBuf::new`].
    pub fn new_in(provider: &dyn SecretMemory, len: usize) -> Self {
        Self {
            region: provider.allocate(len),
        }
    }

    /// Length in bytes.
    pub fn len(&self) -> usize {
        self.region.bytes().len()
    }

    /// True when the buffer holds no bytes.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// The secret bytes.
    pub fn as_bytes(&self) -> &[u8] {
        self.region.bytes()
    }

    /// The secret bytes, writable.
    pub fn as_bytes_mut(&mut self) -> &mut [u8] {
        self.region.bytes_mut()
    }
}

impl Drop for SecretBuf {
    fn drop(&mut self) {
        // §12.8: zero before the region goes back to its provider.
        self.region.bytes_mut().zeroize();
    }
}

impl fmt::Debug for SecretBuf {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "SecretBuf(<redacted, {} bytes>)", self.len())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicUsize, Ordering};

    /// A test provider whose regions report, when released, whether they were all zero (the
    /// "zeroization" check of Build 3-4 §2.8, available from Part 1).
    struct Auditing {
        released_dirty: Arc<AtomicUsize>,
        released: Arc<AtomicUsize>,
    }

    struct AuditedRegion {
        bytes: Vec<u8>,
        released_dirty: Arc<AtomicUsize>,
        released: Arc<AtomicUsize>,
    }

    impl SecretRegion for AuditedRegion {
        fn bytes(&self) -> &[u8] {
            &self.bytes
        }
        fn bytes_mut(&mut self) -> &mut [u8] {
            &mut self.bytes
        }
    }

    impl Drop for AuditedRegion {
        fn drop(&mut self) {
            self.released.fetch_add(1, Ordering::SeqCst);
            if self.bytes.iter().any(|&b| b != 0) {
                self.released_dirty.fetch_add(1, Ordering::SeqCst);
            }
        }
    }

    impl SecretMemory for Auditing {
        fn allocate(&self, len: usize) -> Box<dyn SecretRegion> {
            Box::new(AuditedRegion {
                bytes: vec![0; len],
                released_dirty: Arc::clone(&self.released_dirty),
                released: Arc::clone(&self.released),
            })
        }
    }

    // Build §3.3 EP-4, spec §12.8 — every buffer is all zero when it reaches its provider again.
    #[test]
    fn p1_types_secret_buf_is_zero_when_released() {
        let p = Auditing {
            released_dirty: Arc::default(),
            released: Arc::default(),
        };
        for len in [0, 1, 32, 64, 3_104] {
            let mut buf = SecretBuf::new_in(&p, len);
            buf.as_bytes_mut().fill(0xa5);
            assert_eq!(buf.len(), len);
        }
        assert_eq!(p.released.load(Ordering::SeqCst), 5);
        assert_eq!(p.released_dirty.load(Ordering::SeqCst), 0);
    }

    // spec §17 — a secret is never printed.
    #[test]
    fn p1_types_secret_buf_debug_is_redacted() {
        let mut buf = SecretBuf::new_in(&HeapProvider, 4);
        buf.as_bytes_mut()
            .copy_from_slice(&[0xde, 0xad, 0xbe, 0xef]);
        let shown = format!("{buf:?}");
        assert!(!shown.contains("de") && !shown.contains("222"), "{shown}");
    }

    // DB-50 — the provider is fixed once: after the first global allocation (or an install), a
    // second install is refused. (The global is per test binary; this is the only test that
    // touches it.)
    #[test]
    fn p1_types_provider_is_installed_once() {
        let _fixes_default = SecretBuf::new(8);
        assert_eq!(
            install_provider(Box::new(HeapProvider)),
            Err(ProviderAlreadyInstalled)
        );
    }
}
