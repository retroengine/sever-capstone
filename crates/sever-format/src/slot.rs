//! The slot (spec §14.4): `scrambled_id (64) ‖ envelope ‖ sealed payload ‖ zero padding to a
//! multiple of 8`, and the payload plaintext `u16be id_len ‖ id zero-padded to 256 ‖ x̃ as
//! d × i32be ‖ extension record secret` (DB-46).

use sever_types::{Error, RecordId, ScrambledId};

use crate::codec::{Reader, Writer, bad};
use crate::{Layout, PADDED_ID_BYTES};

/// A slot as stored: the sealer's bytes are opaque here.
#[derive(Clone, PartialEq, Eq)]
pub struct SlotBytes {
    /// §9.7: the only name below the API.
    pub scrambled_id: ScrambledId,
    /// The wrapped record key (`layout.envelope` bytes; empty with the plaintext sealer).
    pub envelope: Vec<u8>,
    /// The sealed payload (`layout.payload_len() + layout.seal_overhead` bytes).
    pub sealed_payload: Vec<u8>,
}

impl core::fmt::Debug for SlotBytes {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "SlotBytes({:?})", self.scrambled_id)
    }
}

impl SlotBytes {
    /// Encodes to exactly `layout.slot_len()` bytes.
    pub fn encode(&self, layout: &Layout) -> Result<Vec<u8>, Error> {
        if self.envelope.len() != layout.envelope
            || self.sealed_payload.len() != layout.payload_len() + layout.seal_overhead
        {
            return Err(bad("§14.4 slot fields"));
        }
        let mut w = Writer(Vec::with_capacity(layout.slot_len()));
        w.scrambled(&self.scrambled_id)
            .bytes(&self.envelope)
            .bytes(&self.sealed_payload);
        w.0.resize(layout.slot_len(), 0);
        Ok(w.finish())
    }

    /// Parses exactly one slot.
    pub fn parse(bytes: &[u8], layout: &Layout) -> Result<Self, Error> {
        let mut r = Reader::new(bytes, "§14.4 slot");
        let s = Self::read(&mut r, layout)?;
        r.end()?;
        Ok(s)
    }

    /// Reads one slot from `r`; the padding must be zero.
    pub fn read(r: &mut Reader<'_>, layout: &Layout) -> Result<Self, Error> {
        let scrambled_id = r.scrambled()?;
        let envelope = r.take(layout.envelope)?.to_vec();
        let sealed_payload = r
            .take(layout.payload_len() + layout.seal_overhead)?
            .to_vec();
        let pad = layout.slot_len() - 64 - layout.envelope - sealed_payload.len();
        if r.take(pad)?.iter().any(|&b| b != 0) {
            return Err(bad("§14.4 slot padding"));
        }
        Ok(Self {
            scrambled_id,
            envelope,
            sealed_payload,
        })
    }
}

/// The payload plaintext of one record.
#[derive(Clone, PartialEq, Eq)]
pub struct SlotPayload {
    /// The record ID (§3.2).
    pub record_id: RecordId,
    /// `x̃`, `d` values.
    pub x: Vec<i32>,
    /// The extension's record secret (`layout.ext_record_secret` bytes; Part 3: leaf index,
    /// `has_rt`, `r_t`).
    pub ext_secret: Vec<u8>,
}

impl core::fmt::Debug for SlotPayload {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.write_str("SlotPayload(redacted)")
    }
}

impl SlotPayload {
    /// Encodes to exactly `layout.payload_len()` bytes.
    pub fn encode(&self, layout: &Layout) -> Result<Vec<u8>, Error> {
        let id = self.record_id.as_bytes();
        if self.x.len() != layout.d || self.ext_secret.len() != layout.ext_record_secret {
            return Err(bad("§14.4 payload fields"));
        }
        let id_len = u16::try_from(id.len()).map_err(|_| bad("§14.4 payload fields"))?;
        let mut w = Writer(Vec::with_capacity(layout.payload_len()));
        w.u16(id_len).bytes(id);
        w.0.resize(2 + PADDED_ID_BYTES, 0);
        for &v in &self.x {
            w.i32(v);
        }
        w.bytes(&self.ext_secret);
        Ok(w.finish())
    }

    /// Parses a payload: `id_len` in 1–256, a valid record ID (§3.2), zero padding, `d` values.
    pub fn parse(bytes: &[u8], layout: &Layout) -> Result<Self, Error> {
        let mut r = Reader::new(bytes, "§14.4 payload");
        let id_len = usize::from(r.u16()?);
        let padded = r.take(PADDED_ID_BYTES)?;
        let (id, pad) = padded
            .split_at_checked(id_len)
            .ok_or(bad("§14.4 payload id length"))?;
        if id_len == 0 || pad.iter().any(|&b| b != 0) {
            return Err(bad("§14.4 payload id padding"));
        }
        let record_id = RecordId::from_bytes(id).map_err(|_| bad("§14.4 payload record id"))?;
        let mut x = Vec::with_capacity(layout.d);
        for _ in 0..layout.d {
            x.push(r.i32()?);
        }
        let ext_secret = r.take(layout.ext_record_secret)?.to_vec();
        r.end()?;
        Ok(Self {
            record_id,
            x,
            ext_secret,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use proptest::prelude::*;
    use sever_spec::spec;

    fn payload(id: &str, d: usize) -> SlotPayload {
        SlotPayload {
            record_id: RecordId::new(id).unwrap(),
            x: (0..d as i32).map(|i| i * 1000 - 3).collect(),
            ext_secret: vec![],
        }
    }

    #[test]
    #[spec("SR-14.4-1", "SR-14.4-2")]
    fn p2_format_payload_layout_by_offset() {
        let l = Layout::plain(8);
        let b = payload("doc-7", 8).encode(&l).unwrap();
        assert_eq!(b.len(), l.payload_len());
        assert_eq!(&b[..2], &5u16.to_be_bytes(), "id_len");
        assert_eq!(&b[2..7], b"doc-7");
        assert!(b[7..258].iter().all(|&x| x == 0), "id zero-padded to 256");
        assert_eq!(
            &b[258..262],
            &(-3i32).to_be_bytes(),
            "x̃[0] right after the id"
        );
        assert_eq!(&b[262..266], &997i32.to_be_bytes());
    }

    #[test]
    #[spec("SR-14.4-1")]
    fn p2_format_extension_secret_goes_last() {
        let l = Layout {
            ext_record_secret: 41,
            ..Layout::plain(8)
        };
        let mut p = payload("a", 8);
        p.ext_secret = (0..41).collect();
        let b = p.encode(&l).unwrap();
        assert_eq!(&b[b.len() - 41..], p.ext_secret.as_slice());
        assert_eq!(SlotPayload::parse(&b, &l).unwrap(), p);
    }

    #[test]
    fn p2_format_payload_rejects_bad_ids() {
        let l = Layout::plain(8);
        let good = payload("abc", 8).encode(&l).unwrap();
        let mut zero_len = good.clone();
        zero_len[..2].copy_from_slice(&0u16.to_be_bytes());
        assert!(SlotPayload::parse(&zero_len, &l).is_err());
        let mut too_long = good.clone();
        too_long[..2].copy_from_slice(&257u16.to_be_bytes());
        assert!(SlotPayload::parse(&too_long, &l).is_err());
        let mut dirty = good.clone();
        dirty[100] = 1;
        assert_eq!(
            SlotPayload::parse(&dirty, &l),
            Err(bad("§14.4 payload id padding"))
        );
        let mut counter = good.clone();
        counter[2..5].copy_from_slice(b"123");
        assert!(SlotPayload::parse(&counter, &l).is_err(), "§3.2 rule 2");
        let mut not_utf8 = good;
        not_utf8[2] = 0xff;
        assert!(SlotPayload::parse(&not_utf8, &l).is_err());
    }

    #[test]
    fn p2_format_payload_ids_of_256_bytes_fit() {
        let l = Layout::plain(8);
        let id = "é".repeat(128); // 256 bytes of UTF-8
        let p = payload(&id, 8);
        assert_eq!(SlotPayload::parse(&p.encode(&l).unwrap(), &l).unwrap(), p);
    }

    #[test]
    #[spec("SR-14.4-1")]
    fn p2_format_slot_layout_and_padding() {
        let l = Layout::plain(8);
        let s = SlotBytes {
            scrambled_id: ScrambledId::from_bytes([7; 64]),
            envelope: vec![],
            sealed_payload: payload("a", 8).encode(&l).unwrap(),
        };
        let b = s.encode(&l).unwrap();
        assert_eq!(b.len(), l.slot_len());
        assert_eq!(&b[..64], &[7; 64]);
        assert_eq!(&b[64..64 + l.payload_len()], s.sealed_payload.as_slice());
        assert_eq!(SlotBytes::parse(&b, &l).unwrap(), s);
        let mut dirty = b.clone();
        *dirty.last_mut().unwrap() = 1;
        if l.slot_len() > 64 + l.payload_len() {
            assert_eq!(SlotBytes::parse(&dirty, &l), Err(bad("§14.4 slot padding")));
        }
    }

    #[test]
    fn p2_format_debug_never_shows_payload_content() {
        let p = payload("secret-id", 8);
        assert!(!format!("{p:?}").contains("secret"));
    }

    proptest! {
        #[test]
        fn p2_format_prop_payload_round_trips(
            id in "[a-z][a-z0-9_-]{0,40}",
            x in prop::collection::vec(-(1i32 << 24)..=(1 << 24), 16),
        ) {
            let l = Layout::plain(16);
            let p = SlotPayload { record_id: RecordId::new(id).unwrap(), x, ext_secret: vec![] };
            prop_assert_eq!(SlotPayload::parse(&p.encode(&l).unwrap(), &l).unwrap(), p);
        }
    }
}
