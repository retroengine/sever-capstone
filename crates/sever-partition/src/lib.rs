//! `sever-partition`: parse and validate the partition artefact `partition.svp` (Part 1,
//! Build §4.4; spec §6.3).
//!
//! The engine never fits a model; it imports this artefact, built offline by the Python builder
//! C-15 (spec §6.1). Parsing works on bytes; reading the file is the composition root's job, so
//! this crate has no file I/O.

use sever_types::Error;
use sha2::{Digest, Sha256};

/// §6.3: the file magic.
pub const MAGIC: &[u8; 8] = b"SVDBPART";
/// §6.3: the only format version.
pub const FORMAT_VERSION: u16 = 1;
/// §5.1 (`frozen-NNNN`): labels 0–9999, so at most 10,000 frozen groups (gap G-11).
pub const MAX_FROZEN_GROUPS: u16 = 10_000;

/// A validated partition artefact (§6.3 fields, in file order).
#[derive(Clone, PartialEq)]
pub struct PartitionArtefact {
    /// Dimension `d`: a multiple of 8, at least 8 (§8.2, DB-49).
    pub d: usize,
    /// Number of frozen groups, 1 to 10,000.
    pub k_frozen: usize,
    /// The run seed (not the derived k-means seed).
    pub seed: u64,
    /// The drift threshold τ (§6.2 step 6).
    pub tau: f64,
    /// The pooled Ledoit–Wolf shrinkage intensity (§6.2 step 4).
    pub lw_shrinkage: f64,
    /// Reference rows used.
    pub m: u64,
    /// SHA-256 of the reference embedding file.
    pub sha256_reference: [u8; 32],
    /// The encoder, for example `sentence-transformers/all-MiniLM-L6-v2@<commit>`.
    pub encoder: String,
    /// Centroids `μ_0 … μ_{k−1}`, row-major in label order: `k_frozen × d` values.
    pub centroids: Vec<f64>,
    /// The precision matrix `P`, row-major: `d × d` values, used as stored (§6.2 step 5).
    pub precision: Vec<f64>,
    /// SHA-256 of every preceding byte. Recorded in the collection metadata and every ledger entry.
    pub sha256_artefact: [u8; 32],
}

impl core::fmt::Debug for PartitionArtefact {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(
            f,
            "PartitionArtefact(d = {}, k_frozen = {}, seed = {}, tau = {})",
            self.d, self.k_frozen, self.seed, self.tau
        )
    }
}

fn bad(what: &'static str) -> Error {
    Error::IntegrityViolation { invariant: what }
}

/// A forward-only reader over the artefact bytes. Every read is bounds-checked.
struct Reader<'a> {
    bytes: &'a [u8],
    pos: usize,
}

impl<'a> Reader<'a> {
    fn take(&mut self, n: usize) -> Result<&'a [u8], Error> {
        let end = self
            .pos
            .checked_add(n)
            .ok_or_else(|| bad("§6.3 artefact truncated"))?;
        let out = self
            .bytes
            .get(self.pos..end)
            .ok_or_else(|| bad("§6.3 artefact truncated"))?;
        self.pos = end;
        Ok(out)
    }
    fn array<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        self.take(N)?
            .try_into()
            .map_err(|_| bad("§6.3 artefact truncated"))
    }
    fn u16(&mut self) -> Result<u16, Error> {
        Ok(u16::from_be_bytes(self.array()?))
    }
    fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_be_bytes(self.array()?))
    }
    fn f64(&mut self) -> Result<f64, Error> {
        Ok(f64::from_be_bytes(self.array()?))
    }
    fn f64s(&mut self, n: usize) -> Result<Vec<f64>, Error> {
        let mut out = Vec::with_capacity(n);
        for _ in 0..n {
            out.push(self.f64()?);
        }
        Ok(out)
    }
}

impl PartitionArtefact {
    /// Parses `partition.svp` and runs the checks `create_collection` MUST run (§6.3): the
    /// artefact hash, `d`, and a finite precision matrix. Also checks the magic, the version, the
    /// exact length, `k_frozen`, and that centroids and τ are finite.
    pub fn parse(bytes: &[u8]) -> Result<Self, Error> {
        // §6.3: sha256_artefact is the SHA-256 of every preceding byte. Checked first, so no field
        // of a corrupted file is ever trusted.
        let body_len = bytes
            .len()
            .checked_sub(32)
            .ok_or_else(|| bad("§6.3 artefact truncated"))?;
        let (body, digest) = bytes.split_at(body_len);
        let computed: [u8; 32] = Sha256::digest(body).into();
        if computed.as_slice() != digest {
            return Err(bad("§6.3 sha256_artefact mismatch"));
        }

        let mut r = Reader {
            bytes: body,
            pos: 0,
        };
        if r.take(8)? != MAGIC {
            return Err(bad("§6.3 artefact magic"));
        }
        if r.u16()? != FORMAT_VERSION {
            return Err(bad("§6.3 artefact version"));
        }
        let d = usize::from(r.u16()?);
        // §8.2 (d a multiple of 8) and DB-49 (any such d).
        if d == 0 || d % 8 != 0 {
            return Err(bad("§6.3 artefact d"));
        }
        let k_raw = r.u16()?;
        if k_raw == 0 || k_raw > MAX_FROZEN_GROUPS {
            return Err(bad("§6.3 artefact k_frozen"));
        }
        let k_frozen = usize::from(k_raw);
        let seed = r.u64()?;
        let tau = r.f64()?;
        let lw_shrinkage = r.f64()?;
        let m = r.u64()?;
        let sha256_reference = r.array::<32>()?;
        let enc_len = usize::from(r.u16()?);
        let encoder = core::str::from_utf8(r.take(enc_len)?)
            .map_err(|_| bad("§6.3 artefact encoder"))?
            .to_owned();
        let centroids = r.f64s(k_frozen * d)?;
        let precision = r.f64s(d * d)?;
        if r.pos != body.len() {
            return Err(bad("§6.3 artefact trailing bytes"));
        }
        // §6.3: P has finite entries. Centroids and τ too, since routing uses them.
        if !precision.iter().all(|v| v.is_finite()) {
            return Err(bad("§6.3 artefact precision not finite"));
        }
        if !centroids.iter().all(|v| v.is_finite()) || !tau.is_finite() || tau < 0.0 {
            return Err(bad("§6.3 artefact centroids or tau"));
        }
        let sha256_artefact = computed;
        Ok(Self {
            d,
            k_frozen,
            seed,
            tau,
            lw_shrinkage,
            m,
            sha256_reference,
            encoder,
            centroids,
            precision,
            sha256_artefact,
        })
    }

    /// Centroid of frozen group `label` (`d` values), or `None` past `k_frozen`.
    pub fn centroid(&self, label: usize) -> Option<&[f64]> {
        let start = label.checked_mul(self.d)?;
        self.centroids.get(start..start.checked_add(self.d)?)
    }

    /// Row `a` of `P` (`d` values), or `None` past `d`.
    pub fn precision_row(&self, a: usize) -> Option<&[f64]> {
        let start = a.checked_mul(self.d)?;
        self.precision.get(start..start.checked_add(self.d)?)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use sever_spec::spec;

    /// The small artefact the Python builder wrote (d = 16, k = 4), and the builder's own summary
    /// of it: an independent cross-check of the byte layout (Build §4.7 L8, builder to importer).
    const SMALL: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");
    const SMALL_JSON: &str = include_str!("../../../golden/p1_partition_small.json");

    type Mutation = Box<dyn Fn(&mut Vec<u8>)>;

    fn rehash(mut body: Vec<u8>) -> Vec<u8> {
        body.truncate(body.len() - 32);
        let h: [u8; 32] = Sha256::digest(&body).into();
        body.extend_from_slice(&h);
        body
    }

    // the Python builder's file parses, and every field matches the
    // builder's summary.
    #[spec("SR-6.3-1", "SR-6.3-2")]
    #[test]
    fn p1_partition_parses_the_python_builders_file() {
        let a = PartitionArtefact::parse(SMALL).unwrap();
        let j: serde_json::Value = serde_json::from_str(SMALL_JSON).unwrap();
        assert_eq!(a.d, 16);
        assert_eq!(a.k_frozen, 4);
        assert_eq!(a.seed, j["seed"].as_u64().unwrap());
        assert_eq!(a.tau, j["tau"].as_f64().unwrap());
        assert_eq!(a.lw_shrinkage, j["lw_shrinkage"].as_f64().unwrap());
        assert_eq!(a.m, j["m"].as_u64().unwrap());
        assert_eq!(a.encoder, j["encoder"].as_str().unwrap());
        let hex: String = a
            .sha256_artefact
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        assert_eq!(hex, j["sha256_artefact"].as_str().unwrap());
        assert_eq!(
            a.centroid(0).unwrap()[0],
            j["centroid_0_0"].as_f64().unwrap()
        );
        assert_eq!(
            a.precision_row(15).unwrap()[15],
            j["precision_15_15"].as_f64().unwrap()
        );
        assert!(a.centroid(4).is_none());
        assert!(a.precision_row(16).is_none());
    }

    // every single-bit flip anywhere in the file is caught by the hash.
    #[spec("SR-6.3-2")]
    #[test]
    fn p1_partition_every_bit_flip_is_detected() {
        for byte in 0..SMALL.len() {
            for bit in [0, 7] {
                let mut f = SMALL.to_vec();
                f[byte] ^= 1 << bit;
                assert!(
                    PartitionArtefact::parse(&f).is_err(),
                    "flip at {byte}.{bit}"
                );
            }
        }
    }

    // with a valid hash, the field checks still refuse bad content.
    #[spec("SR-6.3-2", "SR-8.2-2")]
    #[test]
    fn p1_partition_rejects_bad_fields_even_with_valid_hash() {
        let cases: Vec<(&str, Mutation)> = vec![
            ("magic", Box::new(|f| f[0] = b'X')),
            ("version", Box::new(|f| f[9] = 2)),
            ("d = 12", Box::new(|f| f[11] = 12)),
            ("d = 0", Box::new(|f| f[11] = 0)),
            ("k = 0", Box::new(|f| f[13] = 0)),
            (
                "k = 10001",
                Box::new(|f| f[12..14].copy_from_slice(&10_001u16.to_be_bytes())),
            ),
            ("encoder not UTF-8", Box::new(|f| f[80] = 0xff)),
            (
                "P NaN",
                Box::new(|f| {
                    let at = f.len() - 32 - 8;
                    f[at..at + 8].copy_from_slice(&f64::NAN.to_be_bytes());
                }),
            ),
            (
                "P inf",
                Box::new(|f| {
                    let at = f.len() - 32 - 8;
                    f[at..at + 8].copy_from_slice(&f64::INFINITY.to_be_bytes());
                }),
            ),
            (
                "tau NaN",
                Box::new(|f| f[22..30].copy_from_slice(&f64::NAN.to_be_bytes())),
            ),
            ("trailing byte", Box::new(|f| f.insert(f.len() - 32, 0))),
            (
                "one byte short",
                Box::new(|f| {
                    f.remove(f.len() - 33);
                }),
            ),
        ];
        for (name, mutate) in cases {
            let mut f = SMALL.to_vec();
            mutate(&mut f);
            let f = rehash(f);
            assert!(PartitionArtefact::parse(&f).is_err(), "{name} accepted");
        }
        assert!(PartitionArtefact::parse(&[]).is_err());
        assert!(PartitionArtefact::parse(&[0; 31]).is_err());
    }

    // spec §17 — the error names the rule, never a value.
    #[test]
    fn p1_partition_errors_name_the_rule() {
        let mut f = SMALL.to_vec();
        f[200] ^= 1;
        let e = PartitionArtefact::parse(&f).unwrap_err();
        assert_eq!(
            e.to_string(),
            "integrity violation: §6.3 sha256_artefact mismatch"
        );
    }
}
