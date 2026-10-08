//! The group header (spec §14.3, DB-46): `group_id (32, zero-padded) ‖ u8 kind ‖ u64be
//! seal_version ‖ u64be n ‖ extension public state ‖ centroid as d × f64be ‖ sealed accumulator`
//! (the accumulator is absent for the holding area).

use sever_types::{Error, GroupId};

use crate::Layout;
use crate::codec::{Reader, Writer, bad};

/// The `kind` byte of §14.3.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum KindByte {
    /// 0: a frozen group.
    Frozen = 0,
    /// 1: a spawned group.
    Spawned = 1,
    /// 2: the holding area.
    Holding = 2,
}

impl KindByte {
    /// The kind every group ID implies (§5.1).
    pub fn of(id: &GroupId) -> Self {
        match id {
            GroupId::Frozen(_) => Self::Frozen,
            GroupId::Spawned(_) => Self::Spawned,
            GroupId::Holding => Self::Holding,
        }
    }
}

/// One group header. The accumulator bytes are as the sealer produced them (DB-46): with the
/// plaintext sealer, `S as d × i64be ‖ extension secret`.
#[derive(Clone, Debug, PartialEq)]
pub struct GroupHeader {
    /// The group.
    pub group_id: GroupId,
    /// Maintained by the sealer (DB-46): the group key version under AES-GCM-SIV, 0 in plaintext.
    pub seal_version: u64,
    /// The member count `n`.
    pub n: u64,
    /// Extension public state (Part 3: `C_S`); `layout.ext_public` bytes.
    pub ext_public: Vec<u8>,
    /// The centroid, `d` values (all zero for the holding area).
    pub centroid: Vec<f64>,
    /// The sealed accumulator; empty for the holding area.
    pub sealed_accumulator: Vec<u8>,
}

impl GroupHeader {
    /// The kind byte, derived from the ID.
    pub fn kind(&self) -> KindByte {
        KindByte::of(&self.group_id)
    }

    /// Encodes under `layout`. Fails if a field has the wrong size for the layout.
    pub fn encode(&self, layout: &Layout) -> Result<Vec<u8>, Error> {
        let holding = self.kind() == KindByte::Holding;
        let acc = if holding {
            0
        } else {
            layout.accumulator_len() + layout.seal_overhead
        };
        if self.ext_public.len() != layout.ext_public
            || self.centroid.len() != layout.d
            || self.sealed_accumulator.len() != acc
            || (holding && self.centroid.iter().any(|&c| c.to_bits() != 0))
        {
            return Err(bad("§14.3 group header fields"));
        }
        let mut w = Writer(Vec::with_capacity(layout.header_len(holding)));
        w.group_id(&self.group_id)
            .u8(self.kind() as u8)
            .u64(self.seal_version)
            .u64(self.n)
            .bytes(&self.ext_public);
        for &c in &self.centroid {
            w.f64(c);
        }
        w.bytes(&self.sealed_accumulator);
        Ok(w.finish())
    }

    /// Parses exactly one header from `bytes`.
    pub fn parse(bytes: &[u8], layout: &Layout) -> Result<Self, Error> {
        let mut r = Reader::new(bytes, "§14.3 group header");
        let h = Self::read(&mut r, layout)?;
        r.end()?;
        Ok(h)
    }

    /// Reads one header from `r`.
    pub fn read(r: &mut Reader<'_>, layout: &Layout) -> Result<Self, Error> {
        let group_id = r.group_id()?;
        let kind = r.u8()?;
        if kind != KindByte::of(&group_id) as u8 {
            return Err(bad("§14.3 group kind"));
        }
        let holding = kind == KindByte::Holding as u8;
        let seal_version = r.u64()?;
        let n = r.u64()?;
        let ext_public = r.take(layout.ext_public)?.to_vec();
        let mut centroid = Vec::with_capacity(layout.d);
        for _ in 0..layout.d {
            centroid.push(r.f64()?);
        }
        if holding && centroid.iter().any(|&c| c.to_bits() != 0) {
            return Err(bad("§14.3 holding centroid"));
        }
        let acc = if holding {
            0
        } else {
            layout.accumulator_len() + layout.seal_overhead
        };
        let sealed_accumulator = r.take(acc)?.to_vec();
        Ok(Self {
            group_id,
            seal_version,
            n,
            ext_public,
            centroid,
            sealed_accumulator,
        })
    }
}

/// The plaintext accumulator `S as d × i64be ‖ extension secret` (§14.3).
pub fn encode_accumulator(s: &[i64], ext_secret: &[u8]) -> Vec<u8> {
    let mut w = Writer(Vec::with_capacity(8 * s.len() + ext_secret.len()));
    for &v in s {
        w.i64(v);
    }
    w.bytes(ext_secret);
    w.finish()
}

/// Parses a plaintext accumulator into `S` and the extension secret.
pub fn parse_accumulator(bytes: &[u8], layout: &Layout) -> Result<(Vec<i64>, Vec<u8>), Error> {
    let mut r = Reader::new(bytes, "§14.3 accumulator");
    let mut s = Vec::with_capacity(layout.d);
    for _ in 0..layout.d {
        s.push(r.i64()?);
    }
    let ext = r.take(layout.ext_group_secret)?.to_vec();
    r.end()?;
    Ok((s, ext))
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_spec::spec;

    fn header(id: GroupId, d: usize) -> GroupHeader {
        let holding = id == GroupId::Holding;
        GroupHeader {
            group_id: id,
            seal_version: 0,
            n: 3,
            ext_public: vec![],
            centroid: if holding {
                vec![0.0; d]
            } else {
                (0..d).map(|i| i as f64 / 7.0).collect()
            },
            sealed_accumulator: if holding {
                vec![]
            } else {
                encode_accumulator(&vec![-5; d], &[])
            },
        }
    }

    #[test]
    // oracle: A §14.3 table with the plaintext sealer and no extension (DB-46, DB-48), offsets by hand
    #[spec("SR-14.3-1")]
    fn p2_format_group_header_layout_by_offset() {
        let l = Layout::plain(16);
        let h = header(GroupId::frozen(42).unwrap(), 16);
        let b = h.encode(&l).unwrap();
        assert_eq!(b.len(), l.header_len(false));
        assert_eq!(&b[..11], b"frozen-0042");
        assert!(b[11..32].iter().all(|&x| x == 0), "zero-padded to 32");
        assert_eq!(b[32], 0, "kind frozen");
        assert_eq!(&b[33..41], &0u64.to_be_bytes(), "seal_version");
        assert_eq!(&b[41..49], &3u64.to_be_bytes(), "n");
        assert_eq!(&b[49..57], &(0.0f64).to_bits().to_be_bytes(), "centroid[0]");
        assert_eq!(&b[57..65], &(1.0f64 / 7.0).to_bits().to_be_bytes());
        assert_eq!(&b[49 + 128..49 + 136], &(-5i64).to_be_bytes(), "S[0]");
        assert_eq!(GroupHeader::parse(&b, &l).unwrap(), h);
    }

    #[test]
    fn p2_format_group_header_round_trips_every_kind() {
        let l = Layout::plain(8);
        for id in [
            GroupId::frozen(0).unwrap(),
            GroupId::Spawned([0xab; 8]),
            GroupId::Holding,
        ] {
            let h = header(id, 8);
            let b = h.encode(&l).unwrap();
            assert_eq!(b.len(), l.header_len(id == GroupId::Holding));
            assert_eq!(GroupHeader::parse(&b, &l).unwrap(), h);
        }
    }

    #[test]
    fn p2_format_group_header_rejects_bad_fields() {
        let l = Layout::plain(8);
        let mut b = header(GroupId::Spawned([1; 8]), 8).encode(&l).unwrap();
        b[32] = 0; // kind byte says frozen, ID says spawned
        assert_eq!(GroupHeader::parse(&b, &l), Err(bad("§14.3 group kind")));

        let mut h = header(GroupId::Holding, 8);
        let mut b = h.encode(&l).unwrap();
        b[49] = 0x3f; // a non-zero holding centroid
        assert_eq!(
            GroupHeader::parse(&b, &l),
            Err(bad("§14.3 holding centroid"))
        );
        h.centroid[0] = 1.0;
        assert!(h.encode(&l).is_err());

        let mut b = header(GroupId::frozen(1).unwrap(), 8).encode(&l).unwrap();
        b[20] = b'x'; // garbage inside the zero padding
        assert!(GroupHeader::parse(&b, &l).is_err());
        let b = header(GroupId::frozen(1).unwrap(), 8).encode(&l).unwrap();
        assert!(GroupHeader::parse(&b[..b.len() - 1], &l).is_err(), "short");
        let mut long = b.clone();
        long.push(0);
        assert!(GroupHeader::parse(&long, &l).is_err(), "trailing byte");
    }

    #[test]
    fn p2_format_accumulator_round_trips() {
        let l = Layout {
            ext_group_secret: 3,
            ..Layout::plain(8)
        };
        let s: Vec<i64> = (0..8).map(|i| (i - 4) * (1 << 40)).collect();
        let b = encode_accumulator(&s, &[1, 2, 3]);
        assert_eq!(b.len(), l.accumulator_len());
        assert_eq!(parse_accumulator(&b, &l).unwrap(), (s, vec![1, 2, 3]));
        assert!(parse_accumulator(&b[1..], &l).is_err());
    }
}
