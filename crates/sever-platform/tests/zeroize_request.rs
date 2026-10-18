//! `Zeroize` on Part 4's secret types wipes them on request, not only on drop (spec §12.8).

use sever_keys::Key;
use sever_seal::block::BucketKey;
use sever_spec::spec;
use zeroize::{Zeroize, ZeroizeOnDrop};

fn both<T: Zeroize + ZeroizeOnDrop>(_: &T) {}

// oracle: A §12.8 "Every secret type implements Zeroize and ZeroizeOnDrop"
#[spec("SR-12.8-1")]
#[test]
fn p4_platform_secret_types_zeroize_on_request() {
    let mut k = Key::generate();
    both(&k);
    assert!(k.as_bytes().iter().any(|&b| b != 0));
    k.zeroize();
    assert_eq!(k.as_bytes(), [0u8; 32]);

    let mut b = BucketKey::generate(1);
    both(&b);
    assert!(b.key.as_bytes().iter().any(|&x| x != 0));
    b.zeroize();
    assert_eq!(b.key.as_bytes(), [0u8; 32]);
}
