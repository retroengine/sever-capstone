//! EP-2 `IdScrambler` (Build §3.3) and its only production implementation (spec §9.7).

use hmac::{Hmac, Mac};
use sever_types::constants::SCRAMBLE_KEY_BYTES;
use sever_types::{CollectionId, RecordId, ScrambledId, SecretBuf};
use sha2::Sha512;

/// EP-2: maps a record ID to the 64-byte scrambled ID used everywhere below the API (§9.7).
pub trait IdScrambler: Send + Sync {
    /// The scrambled ID of `record_id` in collection `collection_id`.
    fn scramble(&self, collection_id: &CollectionId, record_id: &RecordId) -> ScrambledId;
}

/// §9.7: `HMAC-SHA-512(k_scramble, collection_id ‖ record_id_bytes)`. The 64-byte key comes from
/// the OS CSPRNG, once per database; Part 1 has no entropy source, so the composition root hands
/// it in (Build §4.4).
pub struct HmacSha512Scrambler {
    key: SecretBuf,
}

impl HmacSha512Scrambler {
    /// Takes `k_scramble`, 64 bytes, copied into secret memory (EP-4).
    pub fn new(k_scramble: &[u8; SCRAMBLE_KEY_BYTES]) -> Self {
        let mut key = SecretBuf::new(SCRAMBLE_KEY_BYTES);
        key.as_bytes_mut().copy_from_slice(k_scramble);
        Self { key }
    }
}

impl IdScrambler for HmacSha512Scrambler {
    fn scramble(&self, collection_id: &CollectionId, record_id: &RecordId) -> ScrambledId {
        // HMAC accepts keys of any length, so `new_from_slice` cannot fail; a 64-byte key is
        // shorter than SHA-512's 128-byte block, so it is used as is (RFC 2104).
        let Ok(mut mac) = Hmac::<Sha512>::new_from_slice(self.key.as_bytes()) else {
            return ScrambledId::from_bytes([0; 64]);
        };
        mac.update(collection_id.as_bytes());
        mac.update(record_id.as_bytes());
        ScrambledId::from_bytes(mac.finalize().into_bytes().into())
    }
}

impl core::fmt::Debug for HmacSha512Scrambler {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str("HmacSha512Scrambler(<key redacted>)")
    }
}
