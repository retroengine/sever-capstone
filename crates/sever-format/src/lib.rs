//! `sever-format`: byte-exact, checksummed, versioned storage formats with strict parsers (Part 2,
//! Build §5.5; spec §14 without §14.5 and §14.7).
//!
//! Every file in the data directory starts with a magic number, the `u16be` format version and the
//! `u16be sealer_id` (spec §14, DB-48), and every record on disk carries a CRC-32C (§12.7). Every
//! parser is strict: wrong magic, version, sealer, length, CRC, padding or trailing bytes are all
//! rejected with `IntegrityViolation` naming the check (never a value, §17).
//!
//! The extension's and the sealer's bytes are opaque here (DB-46): a [`Layout`] gives their sizes,
//! so the same code reads and writes Part 2's plaintext database and the released encrypted one.

pub mod codec;
pub mod file;
pub mod group;
pub mod image;
pub mod paged;
pub mod slot;
pub mod store;
pub mod wal;

pub use codec::{Reader, Writer, bad, crc};
pub use file::{FileHeader, Manifest, Secrets, SegmentHeader};
pub use group::{GroupHeader, KindByte};
pub use image::{
    CheckpointMeta, CheckpointStreams, CollectionImage, CollectionMeta, DbImage, GroupImage,
    PayloadRef,
};
pub use slot::{SlotBytes, SlotPayload};
pub use store::StoreRecord;
pub use wal::{CoreRecord, RecordType, WalParse, WalRecord};

/// The format version of every Part 2 structure (spec §14: "a `u16be` format version").
pub const FORMAT_VERSION: u16 = 1;

/// `sealer_id` of the plaintext sealer (DB-48).
pub const SEALER_PLAINTEXT: u16 = 0;
/// `sealer_id` of AES-256-GCM-SIV as in §13.2 (DB-48; Part 4).
pub const SEALER_AES_GCM_SIV: u16 = 1;

/// Magic numbers, 8 ASCII bytes each (spec §14: every file has one).
pub mod magic {
    /// `MANIFEST` (§14.1).
    pub const MANIFEST: [u8; 8] = *b"SVDBMANI";
    /// A WAL segment `wal/<seq>.wal` (§14.6).
    pub const WAL_SEGMENT: [u8; 8] = *b"SVDBWALS";
    /// An append store `*.store` (§14.8).
    pub const STORE: [u8; 8] = *b"SVDBSTOR";
    /// `SECRETS` in the key directory (§14.1).
    pub const SECRETS: [u8; 8] = *b"SVDBSECR";
    /// Storage checkpoint `meta.bin`.
    pub const META: [u8; 8] = *b"SVDBMETA";
    /// Storage checkpoint `collections.bin`.
    pub const COLLECTIONS: [u8; 8] = *b"SVDBCOLL";
    /// Storage checkpoint `groups.bin`.
    pub const GROUPS: [u8; 8] = *b"SVDBGRPS";
    /// Storage checkpoint `slots.bin`.
    pub const SLOTS: [u8; 8] = *b"SVDBSLOT";
    /// Storage checkpoint `locator.bin`.
    pub const LOCATOR: [u8; 8] = *b"SVDBLOCA";
    /// Storage checkpoint `payloads.bin` (passage references).
    pub const PAYLOAD_REFS: [u8; 8] = *b"SVDBPREF";
}

/// Size of the record ID field of a slot payload: IDs are zero-padded to 256 bytes (§14.4).
pub const PADDED_ID_BYTES: usize = 256;

/// The sizes that depend on the dimension, the group extension (EP-1) and the sealer (EP-6).
///
/// With the released configuration (`d = 384`, commitment extension, AES-GCM-SIV) the sizes are
/// those of spec §14.3–§14.4 and Appendix A; Part 2 (no extension, plaintext sealer) gets the
/// Part 2 rows of Appendix A (DB-46).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Layout {
    /// Dimension `d`.
    pub d: usize,
    /// Extension public group state in the header (Part 3: `C_S`, 32).
    pub ext_public: usize,
    /// Extension secret group state, sealed with `S` (Part 3: `r_agg`, 32).
    pub ext_group_secret: usize,
    /// Extension secret per record, at the end of the slot payload (Part 3: 41).
    pub ext_record_secret: usize,
    /// The wrapped record key in each slot (AES-GCM-SIV: 60; plaintext: 0).
    pub envelope: usize,
    /// What sealing adds to a sealed value (AES-GCM-SIV: 12-byte nonce + 16-byte tag; plaintext: 0).
    pub seal_overhead: usize,
}

impl Layout {
    /// Part 2's layout: no extension, plaintext sealer.
    pub fn plain(d: usize) -> Self {
        Self {
            d,
            ext_public: 0,
            ext_group_secret: 0,
            ext_record_secret: 0,
            envelope: 0,
            seal_overhead: 0,
        }
    }

    /// Slot payload plaintext: `u16be id_len ‖ id padded to 256 ‖ x̃ as d × i32be ‖ extension
    /// record secret` (§14.4, DB-46).
    pub fn payload_len(&self) -> usize {
        2 + PADDED_ID_BYTES + 4 * self.d + self.ext_record_secret
    }

    /// A slot: `scrambled_id ‖ envelope ‖ sealed payload`, zero-padded to a multiple of 8 (§14.4).
    pub fn slot_len(&self) -> usize {
        (64 + self.envelope + self.payload_len() + self.seal_overhead).div_ceil(8) * 8
    }

    /// Accumulator plaintext: `S as d × i64be ‖ extension group secret` (§14.3).
    pub fn accumulator_len(&self) -> usize {
        8 * self.d + self.ext_group_secret
    }

    /// A group header (§14.3); the holding area has no accumulator.
    pub fn header_len(&self, holding: bool) -> usize {
        let acc = if holding {
            0
        } else {
            self.accumulator_len() + self.seal_overhead
        };
        32 + 1 + 8 + 8 + self.ext_public + 8 * self.d + acc
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_spec::spec;

    /// The released layout of spec §14.3–§14.4.
    fn released() -> Layout {
        Layout {
            d: 384,
            ext_public: 32,
            ext_group_secret: 32,
            ext_record_secret: 41,
            envelope: 60,
            seal_overhead: 28,
        }
    }

    #[test]
    // oracle: A Appendix A, §14.3 and §14.4 released totals
    #[spec("SR-14.3-1", "SR-14.4-1")]
    fn p2_format_released_sizes_match_appendix_a() {
        let l = released();
        assert_eq!(l.payload_len(), 1_835);
        assert_eq!(l.slot_len(), 1_992);
        assert_eq!(l.accumulator_len(), 3_104);
        assert_eq!(l.accumulator_len() + l.seal_overhead, 3_132);
        assert_eq!(l.header_len(false), 6_285);
    }

    #[test]
    // oracle: A Appendix A Part 2 rows (DB-46)
    #[spec("SR-14.3-1", "SR-14.4-1")]
    fn p2_format_part2_sizes_match_appendix_a() {
        let l = Layout::plain(384);
        assert_eq!(l.payload_len(), 1_794);
        assert_eq!(l.slot_len(), 1_864);
        assert_eq!(l.header_len(false), 6_193);
        assert_eq!(l.header_len(true), 32 + 1 + 8 + 8 + 3_072);
    }

    #[test]
    fn p2_format_slots_are_8_aligned_for_every_small_dimension() {
        for d in (8..=64).step_by(8) {
            assert_eq!(Layout::plain(d).slot_len() % 8, 0);
            assert_eq!(released_at(d).slot_len() % 8, 0);
        }
    }

    fn released_at(d: usize) -> Layout {
        Layout { d, ..released() }
    }
}
