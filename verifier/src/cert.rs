//! The certificate's strict parser (spec §11.1) and its `insert_inclusion` field (§11.2), written
//! from the spec text. Parsing is step 1 of §11.3; every failure here is a step-1 rejection.

/// Length of an insert leaf (§10.2).
pub const INSERT_LEAF_LEN: usize = 209;
/// Length of an encoded log checkpoint (§11.2).
pub const CHECKPOINT_LEN: usize = 116;
/// Length of one cosignature entry of tag 7 (§11.1).
pub const COSIGNATURE_LEN: usize = 69;
/// The trailer's tag (§11.1).
pub const TRAILER: u8 = 0xFF;

/// A log checkpoint as tag 6 carries it (§10.3, §11.2).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Checkpoint {
    /// Leaves covered.
    pub tree_size: u64,
    /// RFC 9162 root.
    pub root: [u8; 32],
    /// Issue time.
    pub timestamp_ms: u64,
    /// The operator epoch that signed it.
    pub epoch: u32,
    /// The operator's signature over the §9.8 message.
    pub signature: [u8; 64],
}

/// Tag 6 (§11.2).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Inclusion {
    /// `insert_leaf` (209 bytes, §10.2).
    pub leaf: [u8; INSERT_LEAF_LEN],
    /// `leaf_index`.
    pub leaf_index: u64,
    /// The log checkpoint the path leads to.
    pub checkpoint: Checkpoint,
    /// The RFC 9162 inclusion path.
    pub path: Vec<[u8; 32]>,
}

/// One entry of tag 7 (§11.1).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Cosignature {
    /// `witness_index`.
    pub witness_index: u8,
    /// `witness_epoch`.
    pub witness_epoch: u32,
    /// The signature over `DST_COSIGN ‖` the checkpoint message (§9.8).
    pub signature: [u8; 64],
}

/// A strictly parsed certificate (§11.1). Points and scalars are still bytes; §11.3 step 1 decodes
/// them.
#[derive(Clone, Debug)]
pub struct Certificate {
    /// Tag 1, `C_t`.
    pub c_t: [u8; 32],
    /// Tag 2, `C_S_pre` (`None` when empty).
    pub c_s_pre: Option<[u8; 32]>,
    /// Tag 3, `C_S_post` (`None` when empty).
    pub c_s_post: Option<[u8; 32]>,
    /// Tag 4, the proof (empty for a holding-area deletion).
    pub proof: Vec<u8>,
    /// Tag 5, the user's insert signature.
    pub user_signature: [u8; 64],
    /// Tag 6.
    pub inclusion: Inclusion,
    /// Tag 7.
    pub cosignatures: Vec<Cosignature>,
    /// Tag 8, the operator epoch that signs this certificate.
    pub key_period: u32,
    /// Tag 9.
    pub scrambled_id: [u8; 64],
    /// Tag 10, this deletion's own leaf index.
    pub database_lsn: u64,
    /// Tag 11, 0 or 1.
    pub group_emptied: u8,
    /// Tag 12, 0 (from a group) or 1 (from the holding area).
    pub deletion_kind: u8,
    /// Tag 13.
    pub collection_id: [u8; 16],
    /// Every byte before the trailer (what the operator signs after `DST_CERT`).
    pub body: Vec<u8>,
    /// The trailer's signature.
    pub signature: [u8; 64],
}

/// Why parsing failed (no input bytes, §17).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ParseError(pub &'static str);

struct Reader<'a> {
    b: &'a [u8],
    at: usize,
}

impl<'a> Reader<'a> {
    fn take(&mut self, n: usize, why: &'static str) -> Result<&'a [u8], ParseError> {
        let end = self.at.checked_add(n).ok_or(ParseError(why))?;
        let s = self.b.get(self.at..end).ok_or(ParseError(why))?;
        self.at = end;
        Ok(s)
    }
    fn array<const N: usize>(&mut self, why: &'static str) -> Result<[u8; N], ParseError> {
        self.take(N, why)?.try_into().map_err(|_| ParseError(why))
    }
    fn u8(&mut self, why: &'static str) -> Result<u8, ParseError> {
        Ok(u8::from_be_bytes(self.array(why)?))
    }
    fn u32(&mut self, why: &'static str) -> Result<u32, ParseError> {
        Ok(u32::from_be_bytes(self.array(why)?))
    }
    fn u64(&mut self, why: &'static str) -> Result<u64, ParseError> {
        Ok(u64::from_be_bytes(self.array(why)?))
    }
    fn done(&self) -> bool {
        self.at == self.b.len()
    }
}

fn fixed<const N: usize>(v: &[u8], why: &'static str) -> Result<[u8; N], ParseError> {
    v.try_into().map_err(|_| ParseError(why))
}

fn optional32(v: &[u8], why: &'static str) -> Result<Option<[u8; 32]>, ParseError> {
    if v.is_empty() {
        Ok(None)
    } else {
        fixed(v, why).map(Some)
    }
}

fn bit(v: &[u8], why: &'static str) -> Result<u8, ParseError> {
    match fixed::<1>(v, why)? {
        [b @ (0 | 1)] => Ok(b),
        _ => Err(ParseError(why)),
    }
}

/// Parses tag 6 (§11.2): version 1, the leaf, its index, the checkpoint, the path; nothing after.
pub fn parse_inclusion(v: &[u8]) -> Result<Inclusion, ParseError> {
    let mut r = Reader { b: v, at: 0 };
    if r.u8("tag 6 truncated")? != 1 {
        return Err(ParseError("tag 6 version is not 1"));
    }
    let leaf = r.array::<INSERT_LEAF_LEN>("tag 6 truncated")?;
    let leaf_index = r.u64("tag 6 truncated")?;
    let checkpoint = Checkpoint {
        tree_size: r.u64("tag 6 truncated")?,
        root: r.array("tag 6 truncated")?,
        timestamp_ms: r.u64("tag 6 truncated")?,
        epoch: r.u32("tag 6 truncated")?,
        signature: r.array("tag 6 truncated")?,
    };
    let n = r.u8("tag 6 truncated")?;
    let path = (0..n)
        .map(|_| r.array::<32>("tag 6 truncated"))
        .collect::<Result<Vec<_>, _>>()?;
    if !r.done() {
        return Err(ParseError("tag 6 has trailing bytes"));
    }
    Ok(Inclusion {
        leaf,
        leaf_index,
        checkpoint,
        path,
    })
}

fn parse_cosignatures(v: &[u8]) -> Result<Vec<Cosignature>, ParseError> {
    let mut r = Reader { b: v, at: 0 };
    let n = r.u8("tag 7 is empty")?;
    if v.len() != 1 + COSIGNATURE_LEN * usize::from(n) {
        return Err(ParseError("tag 7 length is not 1 + 69 × count"));
    }
    (0..n)
        .map(|_| {
            Ok(Cosignature {
                witness_index: r.u8("tag 7 truncated")?,
                witness_epoch: r.u32("tag 7 truncated")?,
                signature: r.array("tag 7 truncated")?,
            })
        })
        .collect()
}

/// Parses a certificate of dimension `d` strictly (§11.1): tags 1 … 13 in ascending order, each
/// exactly once, every fixed-size field at its length, tags 11 and 12 in {0, 1}, then the trailer
/// `0xFF ‖ u32be 64 ‖ signature`, and nothing after it.
pub fn parse(cert: &[u8], d: usize) -> Result<Certificate, ParseError> {
    let mut r = Reader { b: cert, at: 0 };
    let mut values: Vec<&[u8]> = Vec::with_capacity(13);
    for tag in 1u8..=13 {
        if r.u8("a tag is missing")? != tag {
            return Err(ParseError("a tag is missing, repeated or out of order"));
        }
        let len = usize::try_from(r.u32("a length is truncated")?)
            .map_err(|_| ParseError("a length is too large"))?;
        values.push(r.take(len, "a value is truncated")?);
    }
    let body_len = r.at;
    if r.u8("the trailer is missing")? != TRAILER {
        return Err(ParseError("the trailer is missing or a tag is repeated"));
    }
    if r.u32("the trailer is truncated")? != 64 {
        return Err(ParseError("the trailer's length is not 64"));
    }
    let signature = r.array("the trailer is truncated")?;
    if !r.done() {
        return Err(ParseError("trailing bytes after the trailer"));
    }
    let [t1, t2, t3, t4, t5, t6, t7, t8, t9, t10, t11, t12, t13] = values[..] else {
        return Err(ParseError("a tag is missing"));
    };
    let proof_len = d
        .checked_add(2)
        .and_then(|n| n.checked_mul(32))
        .ok_or(ParseError("dimension"))?;
    if !t4.is_empty() && t4.len() != proof_len {
        return Err(ParseError("tag 4 length is not 32 + 32 + 32·d"));
    }
    Ok(Certificate {
        c_t: fixed(t1, "tag 1 length is not 32")?,
        c_s_pre: optional32(t2, "tag 2 length is not 0 or 32")?,
        c_s_post: optional32(t3, "tag 3 length is not 0 or 32")?,
        proof: t4.to_vec(),
        user_signature: fixed(t5, "tag 5 length is not 64")?,
        inclusion: parse_inclusion(t6)?,
        cosignatures: parse_cosignatures(t7)?,
        key_period: u32::from_be_bytes(fixed(t8, "tag 8 length is not 4")?),
        scrambled_id: fixed(t9, "tag 9 length is not 64")?,
        database_lsn: u64::from_be_bytes(fixed(t10, "tag 10 length is not 8")?),
        group_emptied: bit(t11, "tag 11 is not one byte 0 or 1")?,
        deletion_kind: bit(t12, "tag 12 is not one byte 0 or 1")?,
        collection_id: fixed(t13, "tag 13 length is not 16")?,
        body: cert.get(..body_len).unwrap_or_default().to_vec(),
        signature,
    })
}
