//! The zeroization check of Build 3-4 §2.8 L8: a test `SecretMemory` provider, installed as the
//! process's provider (DB-50), counts what Part 4's secret types allocate from it and checks that
//! every buffer is all zero when it comes back. This binary holds one test, so nothing else
//! allocates from the provider while it counts.

use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};

use sever_keys::Key;
use sever_seal::block::BucketKey;
use sever_spec::spec;
use sever_types::{SecretMemory, SecretRegion, install_provider};

#[derive(Default)]
struct Counts {
    allocated: AtomicUsize,
    released: AtomicUsize,
    released_dirty: AtomicUsize,
}

struct Auditing(Arc<Counts>);

struct Region(Vec<u8>, Arc<Counts>);

impl SecretRegion for Region {
    fn bytes(&self) -> &[u8] {
        &self.0
    }
    fn bytes_mut(&mut self) -> &mut [u8] {
        &mut self.0
    }
}

impl Drop for Region {
    fn drop(&mut self) {
        self.1.released.fetch_add(1, Ordering::SeqCst);
        if self.0.iter().any(|&b| b != 0) {
            self.1.released_dirty.fetch_add(1, Ordering::SeqCst);
        }
    }
}

impl SecretMemory for Auditing {
    fn allocate(&self, len: usize) -> Box<dyn SecretRegion> {
        self.0.allocated.fetch_add(1, Ordering::SeqCst);
        Box::new(Region(vec![0; len], Arc::clone(&self.0)))
    }
}

// oracle: A §12.8 "Every secret type implements Zeroize and ZeroizeOnDrop" and "Key material …
// live[s] in mlocked pages" (every key comes from the installed provider, DB-50)
#[spec("SR-12.8-1", "SR-12.8-2")]
#[test]
fn p4_platform_every_key_comes_from_the_provider_and_is_zero_when_released() {
    let counts = Arc::new(Counts::default());
    assert!(install_provider(Box::new(Auditing(Arc::clone(&counts)))).is_ok());
    {
        let g = Key::generate();
        let r = Key::from_bytes(&[0x5a; 32]);
        let d = g.duplicate();
        let b = BucketKey::generate(7);
        assert_eq!(
            counts.allocated.load(Ordering::SeqCst),
            4,
            "each key is one region"
        );
        for k in [&g, &r, &d, &b.key] {
            assert!(k.as_bytes().iter().any(|&x| x != 0));
        }
    }
    assert_eq!(
        counts.released.load(Ordering::SeqCst),
        4,
        "every key went back"
    );
    assert_eq!(
        counts.released_dirty.load(Ordering::SeqCst),
        0,
        "and all zero"
    );
}
