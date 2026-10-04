//! Identifiers: record IDs (§3.2), group IDs (§5.1), collection IDs (§3.1), scrambled IDs (§9.7).
//!
//! Every ID orders by its raw bytes (§0.2: "ascending by bytes" is lexicographic order of the raw
//! UTF-8 bytes). Rule 3 of §3.2 (not already live) needs index state and lives in `sever-index`.

use core::cmp::Ordering;
use core::fmt;

use zeroize::{Zeroize, ZeroizeOnDrop};

use crate::constants::{
    COLLECTION_ID_BYTES, GROUP_ID_MAX_BYTES, RECORD_ID_MAX_BYTES, RECORD_ID_MIN_BYTES,
    SCRAMBLED_ID_BYTES,
};
use crate::error::{Error, InvalidRecordIdReason};

// ---------------------------------------------------------------------------------------------
// Record IDs (§3.2)
// ---------------------------------------------------------------------------------------------

/// A validated record ID: 1–256 bytes of UTF-8, not a bare decimal integer (§3.2 rules 1–2).
///
/// Ordering is by raw UTF-8 bytes (§0.2), which is what `String`'s `Ord` does. `Debug` shows only
/// the length, so an ID cannot leak into logs or error text by accident (§17). The bytes are
/// zeroed when the value is dropped (§12.6: record ID bytes are wiped on deletion).
#[derive(Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RecordId(String);

impl Drop for RecordId {
    fn drop(&mut self) {
        self.0.zeroize();
    }
}

impl ZeroizeOnDrop for RecordId {}

impl RecordId {
    /// Validates a UTF-8 string against §3.2 rules 1–2.
    pub fn new(id: impl Into<String>) -> Result<Self, Error> {
        let mut id = id.into();
        match check_record_id(&id) {
            Ok(()) => Ok(Self(id)),
            Err(reason) => {
                id.zeroize();
                Err(Error::InvalidRecordId(reason))
            }
        }
    }

    /// Validates raw bytes: they must be UTF-8 (§3.2 rule 1), then as [`RecordId::new`].
    pub fn from_bytes(bytes: &[u8]) -> Result<Self, Error> {
        let s = core::str::from_utf8(bytes)
            .map_err(|_| Error::InvalidRecordId(InvalidRecordIdReason::NotUtf8))?;
        Self::new(s)
    }

    /// The ID as text.
    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// The ID's UTF-8 bytes, the form used in hashes, the canonical blob and the slot payload.
    pub fn as_bytes(&self) -> &[u8] {
        self.0.as_bytes()
    }

    /// Length in bytes (1–256), as written in the blob's `u16be id_len` (§5.5).
    pub fn len_bytes(&self) -> usize {
        self.0.len()
    }
}

impl fmt::Debug for RecordId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "RecordId(<{} bytes>)", self.0.len())
    }
}

/// §3.2 rules 1–2, in order: length first, then shape.
fn check_record_id(id: &str) -> Result<(), InvalidRecordIdReason> {
    // §3.2 rule 1: 1 to 256 bytes (bytes, not characters).
    if id.len() < RECORD_ID_MIN_BYTES {
        return Err(InvalidRecordIdReason::Empty);
    }
    if id.len() > RECORD_ID_MAX_BYTES {
        return Err(InvalidRecordIdReason::TooLong);
    }
    // §3.2 rule 2: reject a full match of ^[+-]?[0-9]+$.
    if is_counter_shaped(id) {
        return Err(InvalidRecordIdReason::CounterShaped);
    }
    Ok(())
}

/// True when `id` fully matches `^[+-]?[0-9]+$`: at most one leading sign, then one or more ASCII
/// digits and nothing else. `[0-9]` is ASCII only, so `is_ascii_digit`, never `is_numeric` (which
/// also accepts digits such as U+0663).
fn is_counter_shaped(id: &str) -> bool {
    let digits = id.strip_prefix(['+', '-']).unwrap_or(id);
    !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit())
}

// ---------------------------------------------------------------------------------------------
// Group IDs (§5.1)
// ---------------------------------------------------------------------------------------------

/// A group ID (§5.1): `frozen-NNNN`, `spawn-` + 16 lowercase hex characters, or `holding`.
///
/// Ordering is by the bytes of the text form (§8.1 ranks groups by `(D_g, group-ID bytes)`; §7.3
/// breaks spillover ties by group-ID bytes), not by variant.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub enum GroupId {
    /// A frozen group, by partition label (§5.1: 4 digits, zero-padded; gap G-11).
    Frozen(FrozenLabel),
    /// A spawned group: the first 8 bytes of the founding cohort's SHA-256 (§7.5), shown as 16
    /// lowercase hex characters.
    Spawned([u8; 8]),
    /// The holding area, one per collection.
    Holding,
}

/// A frozen group's partition label, 0–9999, so it always fits `frozen-NNNN` (§5.1). The field is
/// private: the only way to build one is [`GroupId::frozen`], which checks the range.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
pub struct FrozenLabel(u16);

impl FrozenLabel {
    /// The label as a number.
    pub fn get(self) -> u16 {
        self.0
    }
}

/// Largest frozen label that fits `frozen-NNNN` (§5.1).
const FROZEN_LABEL_MAX: u16 = 9_999;

/// One lowercase hex digit for a value 0–15 (§5.1: lowercase).
fn hex_digit(nibble: u8) -> u8 {
    if nibble < 10 {
        b'0' + nibble
    } else {
        b'a' + (nibble - 10)
    }
}

impl GroupId {
    /// The frozen group for partition label `label`, or `None` if it does not fit 4 digits.
    pub fn frozen(label: u16) -> Option<Self> {
        (label <= FROZEN_LABEL_MAX).then_some(Self::Frozen(FrozenLabel(label)))
    }

    /// The text form as bytes, zero-padded to 32 (the stored form of §13.2 and §14.3), and the
    /// number of meaningful bytes. Never more than 32 (§5.1).
    pub fn to_padded_bytes(&self) -> ([u8; GROUP_ID_MAX_BYTES], usize) {
        let mut out = [0u8; GROUP_ID_MAX_BYTES];
        let mut len = 0;
        let mut push = |b: u8| {
            if let Some(slot) = out.get_mut(len) {
                *slot = b;
                len += 1;
            }
        };
        match self {
            Self::Frozen(label) => {
                b"frozen-".iter().for_each(|&b| push(b));
                let l = label.get();
                for div in [1000, 100, 10, 1] {
                    // `l / div % 10` is 0..=9, so the digit is ASCII.
                    push(b'0' + (l / div % 10) as u8);
                }
            }
            Self::Spawned(prefix) => {
                b"spawn-".iter().for_each(|&b| push(b));
                for byte in prefix {
                    push(hex_digit(byte >> 4));
                    push(hex_digit(byte & 0x0f));
                }
            }
            Self::Holding => b"holding".iter().for_each(|&b| push(b)),
        }
        (out, len)
    }

    /// The text form, for example `frozen-0042`.
    pub fn as_text(&self) -> String {
        let (bytes, len) = self.to_padded_bytes();
        bytes
            .get(..len)
            .map(|b| String::from_utf8_lossy(b).into_owned())
            .unwrap_or_default()
    }

    /// Parses the text form strictly: exactly 4 ASCII digits after `frozen-`, exactly 16
    /// lowercase hex characters after `spawn-`, or exactly `holding`.
    pub fn parse(text: &str) -> Option<Self> {
        if text == "holding" {
            return Some(Self::Holding);
        }
        if let Some(digits) = text.strip_prefix("frozen-") {
            if digits.len() != 4 || !digits.bytes().all(|b| b.is_ascii_digit()) {
                return None;
            }
            return digits.parse::<u16>().ok().and_then(Self::frozen);
        }
        let hex = text.strip_prefix("spawn-")?;
        if hex.len() != 16 {
            return None;
        }
        let mut prefix = [0u8; 8];
        for (slot, pair) in prefix.iter_mut().zip(hex.as_bytes().chunks_exact(2)) {
            let [hi, lo] = pair else { return None };
            *slot = (lower_hex_value(*hi)? << 4) | lower_hex_value(*lo)?;
        }
        Some(Self::Spawned(prefix))
    }
}

fn lower_hex_value(c: u8) -> Option<u8> {
    match c {
        b'0'..=b'9' => Some(c - b'0'),
        b'a'..=b'f' => Some(c - b'a' + 10),
        _ => None,
    }
}

impl Ord for GroupId {
    fn cmp(&self, other: &Self) -> Ordering {
        // §0.2: by bytes. Group IDs contain no zero byte, so comparing the zero-padded forms is
        // the same as comparing the unpadded text.
        self.to_padded_bytes().0.cmp(&other.to_padded_bytes().0)
    }
}

impl PartialOrd for GroupId {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl fmt::Display for GroupId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.as_text())
    }
}

impl fmt::Debug for GroupId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "GroupId({self})")
    }
}

// ---------------------------------------------------------------------------------------------
// Collection IDs (§3.1) and scrambled IDs (§9.7)
// ---------------------------------------------------------------------------------------------

/// A collection ID: 16 bytes (§3.1). Generating it from the OS CSPRNG is `create_collection`'s
/// job (Part 2); Part 1 has no randomness source.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct CollectionId([u8; COLLECTION_ID_BYTES]);

impl CollectionId {
    /// Wraps 16 bytes.
    pub fn from_bytes(bytes: [u8; COLLECTION_ID_BYTES]) -> Self {
        Self(bytes)
    }

    /// The 16 bytes, as concatenated into hashes and signatures (§9.7, §9.8).
    pub fn as_bytes(&self) -> &[u8; COLLECTION_ID_BYTES] {
        &self.0
    }
}

impl fmt::Debug for CollectionId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("CollectionId(")?;
        self.0.iter().try_for_each(|b| write!(f, "{b:02x}"))?;
        f.write_str(")")
    }
}

/// A scrambled record ID: `HMAC-SHA-512(k_scramble, collection_id ‖ record_id_bytes)`, 64 bytes
/// (§9.7). Every table, WAL record and log leaf names records only by this value. Computing it is
/// EP-2 (`IdScrambler`, in `sever-index`).
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ScrambledId([u8; SCRAMBLED_ID_BYTES]);

impl ScrambledId {
    /// Wraps 64 bytes.
    pub fn from_bytes(bytes: [u8; SCRAMBLED_ID_BYTES]) -> Self {
        Self(bytes)
    }

    /// The 64 bytes.
    pub fn as_bytes(&self) -> &[u8; SCRAMBLED_ID_BYTES] {
        &self.0
    }
}

impl fmt::Debug for ScrambledId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("ScrambledId(")?;
        self.0
            .iter()
            .take(8)
            .try_for_each(|b| write!(f, "{b:02x}"))?;
        f.write_str("…)")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;

    fn reason(id: &str) -> Option<InvalidRecordIdReason> {
        match RecordId::new(id) {
            Ok(_) => None,
            Err(Error::InvalidRecordId(r)) => Some(r),
            Err(other) => panic!("unexpected error {other:?}"),
        }
    }

    // spec: SR-3.2-2 — the examples written in §3.2 itself.
    #[test]
    fn p1_types_record_id_spec_examples() {
        for ok in ["doc0", "nq-1234", "0b8c7e4e-2f0a-4c43-9a43-7d0c8f8b5e10"] {
            assert_eq!(reason(ok), None, "{ok} must be accepted");
        }
        for counter in ["1", "007", "-3", "+3"] {
            assert_eq!(
                reason(counter),
                Some(InvalidRecordIdReason::CounterShaped),
                "{counter}"
            );
        }
    }

    // spec: SR-3.2-2 — equivalence classes around the regex (Build §2.2): full match only, one
    // sign at most, ASCII digits only.
    #[test]
    fn p1_types_record_id_counter_shape_is_a_full_ascii_match() {
        let cases: &[(&str, bool)] = &[
            ("3a", false),       // trailing letter breaks a full match
            ("a3", false),       // leading letter
            ("+", false),        // sign without digits
            ("-", false),        //
            ("+-3", false),      // two signs
            ("3 ", false),       // trailing space
            (" 3", false),       // leading space
            ("1.5", false),      // a decimal point is not a digit
            ("\u{663}", false),  // ARABIC-INDIC DIGIT THREE: not in [0-9]
            ("\u{ff13}", false), // FULLWIDTH DIGIT THREE: not in [0-9]
            ("0", true),
            ("-0", true),
            ("+007", true),
            ("12345678901234567890123", true), // longer than any integer type
        ];
        for &(id, counter) in cases {
            let want = counter.then_some(InvalidRecordIdReason::CounterShaped);
            assert_eq!(reason(id), want, "{id:?}");
        }
    }

    // spec: SR-3.2-1 — boundaries in bytes: 0, 1, 256, 257; multi-byte characters count in bytes.
    #[test]
    fn p1_types_record_id_length_boundaries_in_bytes() {
        assert_eq!(reason(""), Some(InvalidRecordIdReason::Empty));
        assert_eq!(reason("a"), None);
        assert_eq!(reason(&"a".repeat(256)), None);
        assert_eq!(
            reason(&"a".repeat(257)),
            Some(InvalidRecordIdReason::TooLong)
        );
        // "é" is 2 bytes: 128 of them are 256 bytes (accepted), 129 are 258 bytes (rejected).
        assert_eq!(reason(&"é".repeat(128)), None);
        assert_eq!(
            reason(&"é".repeat(129)),
            Some(InvalidRecordIdReason::TooLong)
        );
        // Rule 1 is checked before rule 2: 257 digits is TooLong, not CounterShaped.
        assert_eq!(
            reason(&"7".repeat(257)),
            Some(InvalidRecordIdReason::TooLong)
        );
    }

    // spec: SR-3.2-1 — invalid UTF-8 is rejected.
    #[test]
    fn p1_types_record_id_rejects_invalid_utf8() {
        let err = RecordId::from_bytes(&[0x64, 0x6f, 0xff]).unwrap_err();
        assert_eq!(err, Error::InvalidRecordId(InvalidRecordIdReason::NotUtf8));
        assert!(RecordId::from_bytes(b"doc0").is_ok());
    }

    // spec: SR-0.2-3 — order is by raw UTF-8 bytes: uppercase before lowercase, no numeric sort.
    #[test]
    fn p1_types_record_ids_sort_by_bytes() {
        let mut ids: Vec<RecordId> = ["doc2", "doc10", "Doc2", "doc1", "\u{e9}a", "z"]
            .into_iter()
            .map(|s| RecordId::new(s).unwrap())
            .collect();
        ids.sort();
        let got: Vec<&str> = ids.iter().map(RecordId::as_str).collect();
        // 'D' = 0x44 < 'd' = 0x64 < 'z' = 0x7a < 'é' = 0xc3 0xa9; '1' = 0x31 < '2' = 0x32.
        assert_eq!(got, ["Doc2", "doc1", "doc10", "doc2", "z", "\u{e9}a"]);
    }

    // spec: SR-17-2 — a rejected ID never appears in the error, and Debug never shows an ID.
    #[test]
    fn p1_types_record_id_never_leaks_into_text() {
        let err = RecordId::new("98765432").unwrap_err();
        assert!(!err.to_string().contains("98765432"));
        assert!(!format!("{err:?}").contains("98765432"));
        let id = RecordId::new("secret-doc").unwrap();
        assert!(!format!("{id:?}").contains("secret-doc"));
    }

    proptest! {
        // spec: SR-3.2-2 — anything built from the regex is rejected.
        #[test]
        fn p1_types_prop_counter_shaped_always_rejected(id in "[+-]?[0-9]{1,200}") {
            prop_assert_eq!(reason(&id), Some(InvalidRecordIdReason::CounterShaped));
        }

        // spec: SR-3.2-1, SR-3.2-2 — the rules exactly: accepted iff 1–256 bytes and not a full
        // regex match (checked against an independent statement of the rule).
        #[test]
        fn p1_types_prop_record_id_rule_is_exact(id in "\\PC{0,300}") {
            let n = id.len();
            let bytes = id.as_bytes();
            let body = match bytes.first() {
                Some(b'+' | b'-') => &bytes[1..],
                _ => bytes,
            };
            let counter = !body.is_empty() && body.iter().all(u8::is_ascii_digit);
            let expect_ok = (1..=256).contains(&n) && !counter;
            prop_assert_eq!(RecordId::new(id.clone()).is_ok(), expect_ok);
        }

        // spec: SR-0.2-3 — RecordId order equals raw byte order.
        #[test]
        fn p1_types_prop_record_id_order_is_byte_order(a in "[a-zA-Z\u{e0}-\u{ff}]{1,20}",
                                                       b in "[a-zA-Z\u{e0}-\u{ff}]{1,20}") {
            let (ra, rb) = (RecordId::new(a.clone()).unwrap(), RecordId::new(b.clone()).unwrap());
            prop_assert_eq!(ra.cmp(&rb), a.as_bytes().cmp(b.as_bytes()));
        }
    }

    // spec: SR-5.1-1, SR-5.1-2, SR-5.1-3 — the three text forms.
    #[test]
    fn p1_types_group_id_text_forms() {
        assert_eq!(GroupId::frozen(42).unwrap().as_text(), "frozen-0042");
        assert_eq!(GroupId::frozen(0).unwrap().as_text(), "frozen-0000");
        assert_eq!(GroupId::frozen(9_999).unwrap().as_text(), "frozen-9999");
        assert_eq!(GroupId::frozen(10_000), None);
        let spawned = GroupId::Spawned([0x9c, 0x1e, 0x00, 0xff, 0x0a, 0xb0, 0x12, 0x34]);
        assert_eq!(spawned.as_text(), "spawn-9c1e00ff0ab01234");
        assert_eq!(GroupId::Holding.as_text(), "holding");
    }

    // spec: SR-5.1-4 — at most 32 bytes, stored zero-padded to 32.
    #[test]
    fn p1_types_group_id_fits_32_bytes_zero_padded() {
        for g in [
            GroupId::frozen(7).unwrap(),
            GroupId::Spawned([0xff; 8]),
            GroupId::Holding,
        ] {
            let (bytes, len) = g.to_padded_bytes();
            assert!(len <= 32);
            assert_eq!(&bytes[..len], g.as_text().as_bytes());
            assert!(bytes[len..].iter().all(|&b| b == 0));
        }
        assert_eq!(GroupId::Spawned([0; 8]).to_padded_bytes().1, 22);
    }

    // spec: SR-5.1-1, SR-5.1-2, SR-5.1-3 — strict parsing round-trips and rejects near misses.
    #[test]
    fn p1_types_group_id_parse_is_strict() {
        for g in [
            GroupId::frozen(0).unwrap(),
            GroupId::frozen(9_999).unwrap(),
            GroupId::Spawned([0xab; 8]),
            GroupId::Holding,
        ] {
            assert_eq!(GroupId::parse(&g.as_text()), Some(g));
        }
        for bad in [
            "frozen-42",
            "frozen-00042",
            "frozen-004a",
            "Frozen-0042",
            "spawn-9C1E00FF0AB01234",
            "spawn-9c1e",
            "spawn-9c1e00ff0ab012345",
            "spawn-9c1e00ff0ab0123g",
            "holding ",
            "Holding",
            "",
            "frozen-\u{663}\u{663}\u{663}\u{663}",
        ] {
            assert_eq!(GroupId::parse(bad), None, "{bad:?}");
        }
    }

    // spec: SR-0.2-3 — group IDs order by their bytes, not by kind or number.
    #[test]
    fn p1_types_group_ids_sort_by_bytes() {
        let mut gs = vec![
            GroupId::Holding,
            GroupId::Spawned([0x00; 8]),
            GroupId::frozen(10).unwrap(),
            GroupId::frozen(9).unwrap(),
        ];
        gs.sort();
        // "frozen-0009" < "frozen-0010" < "holding" < "spawn-…" ('f' < 'h' < 's').
        assert_eq!(
            gs,
            [
                GroupId::frozen(9).unwrap(),
                GroupId::frozen(10).unwrap(),
                GroupId::Holding,
                GroupId::Spawned([0; 8]),
            ]
        );
    }

    // spec: SR-3.1-1, SR-9.7-1 — fixed widths of 16 and 64 bytes, ordered by bytes.
    #[test]
    fn p1_types_fixed_width_ids() {
        let c = CollectionId::from_bytes([7; 16]);
        assert_eq!(c.as_bytes().len(), 16);
        let (a, b) = (
            ScrambledId::from_bytes([1; 64]),
            ScrambledId::from_bytes([2; 64]),
        );
        assert_eq!(a.as_bytes().len(), 64);
        assert!(a < b);
    }
}
