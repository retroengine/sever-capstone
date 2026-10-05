//! The composition root: Part 1's index with its only entropy supplied here (Build §4.4).

use rand_core::{OsRng, RngCore};
use sever_index::{HmacSha512Scrambler, Index, IndexConfig, NoExtension};
use sever_partition::PartitionArtefact;
use sever_types::constants::{COLLECTION_ID_BYTES, SCRAMBLE_KEY_BYTES};
use sever_types::{CollectionId, Error};
use zeroize::Zeroizing;

/// Part 1's index: no extension, HMAC-SHA-512 scrambling.
pub type P1Index = Index<NoExtension, HmacSha512Scrambler>;

fn os_fill(buf: &mut [u8]) -> Result<(), Error> {
    OsRng
        .try_fill_bytes(buf)
        .map_err(|_| Error::PlatformUnsafe {
            check: "OS CSPRNG unavailable",
        })
}

/// A new, empty index over `artefact`. §9.7: `k_scramble` is 64 bytes from the OS CSPRNG; §3.1:
/// `collection_id` is 16 random bytes from the OS CSPRNG. Neither ever comes from a seed
/// (CLAUDE.md §6.2), and the key is wiped from this frame when the scrambler has taken it.
pub fn new_index(artefact: &PartitionArtefact, cfg: IndexConfig) -> Result<P1Index, Error> {
    let mut key = Zeroizing::new([0u8; SCRAMBLE_KEY_BYTES]);
    os_fill(key.as_mut())?;
    let mut cid = [0u8; COLLECTION_ID_BYTES];
    os_fill(&mut cid)?;
    Index::new(
        artefact,
        cfg,
        NoExtension,
        HmacSha512Scrambler::new(&key),
        CollectionId::from_bytes(cid),
    )
}
