//! The canonical group blob and the exactness relation (spec §5.5, DB-47).

use sever_quant::QVec;
use sever_types::RecordId;

use crate::changeset::GroupState;
use crate::ext::GroupExtension;

/// §5.5: the blob, generated in memory on demand. Members are sorted by record-ID bytes here.
///
/// ```text
/// magic (6, from the extension) ‖ u16be 1 ‖ u16be d ‖ u64be n ‖ i64be × d S
/// ‖ extension region ‖ u64be member_count ‖ per member: u16be id_len ‖ id ‖ i64be × d x̃
/// ```
pub fn canonical_blob<E: GroupExtension>(
    ext: &E,
    d: usize,
    state: &GroupState<E>,
    members: &[(&RecordId, &QVec)],
) -> Vec<u8> {
    let mut sorted: Vec<&(&RecordId, &QVec)> = members.iter().collect();
    sorted.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes())); // §5.5: ascending by ID bytes
    let mut out = Vec::with_capacity(18 + 8 * d + 8 + members.len() * (2 + 32 + 8 * d));
    out.extend_from_slice(&E::BLOB_MAGIC);
    out.extend_from_slice(&1u16.to_be_bytes()); // format_version
    out.extend_from_slice(&(d as u16).to_be_bytes()); // d ≤ 65,535 by the artefact's u16be
    out.extend_from_slice(&state.n.to_be_bytes());
    for v in &state.s {
        out.extend_from_slice(&v.to_be_bytes());
    }
    ext.blob_region(&state.ext_public, &state.ext_secret, &mut out);
    out.extend_from_slice(&(members.len() as u64).to_be_bytes()); // member_count (= n)
    for (id, x) in sorted {
        out.extend_from_slice(&(id.len_bytes() as u16).to_be_bytes()); // ≤ 256 (§3.2)
        out.extend_from_slice(id.as_bytes());
        for &v in x.as_slice() {
            out.extend_from_slice(&i64::from(v).to_be_bytes()); // x̃ widened from i32
        }
    }
    out
}

/// Why a blob was rejected (§5.5 parser rules, plus the magic of DB-47).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum BlobReject {
    /// The magic is not the expected form's.
    Magic,
    /// The format version is not 1.
    Version,
    /// `member_count ≠ n`.
    CountMismatch,
    /// An ID with zero bytes.
    EmptyId,
    /// IDs not strictly ascending by bytes (unsorted or duplicate).
    Unsorted,
    /// Bytes after the last member.
    TrailingBytes,
    /// Ran out of bytes, or an ID is not UTF-8.
    Truncated,
}

/// A parsed blob: `n`, `S`, the extension region and the members.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParsedBlob {
    /// `n`.
    pub n: u64,
    /// `S`.
    pub s: Vec<i64>,
    /// The extension region's bytes.
    pub region: Vec<u8>,
    /// Members in blob order: ID bytes and `x̃` widened to `i64`.
    pub members: Vec<(Vec<u8>, Vec<i64>)>,
}

/// §5.5 strict parser. `region_len` is the extension region's fixed length for this magic.
pub fn parse_blob(
    blob: &[u8],
    magic: &[u8; 6],
    region_len: usize,
) -> Result<ParsedBlob, BlobReject> {
    let mut pos = 0usize;
    let mut take = |n: usize| -> Result<&[u8], BlobReject> {
        let end = pos.checked_add(n).ok_or(BlobReject::Truncated)?;
        let out = blob.get(pos..end).ok_or(BlobReject::Truncated)?;
        pos = end;
        Ok(out)
    };
    if take(6)? != magic {
        return Err(BlobReject::Magic);
    }
    let be16 = |b: &[u8]| {
        b.try_into()
            .map(u16::from_be_bytes)
            .map_err(|_| BlobReject::Truncated)
    };
    let be64 = |b: &[u8]| {
        b.try_into()
            .map(u64::from_be_bytes)
            .map_err(|_| BlobReject::Truncated)
    };
    let bei64 = |b: &[u8]| {
        b.try_into()
            .map(i64::from_be_bytes)
            .map_err(|_| BlobReject::Truncated)
    };
    if be16(take(2)?)? != 1 {
        return Err(BlobReject::Version);
    }
    let d = usize::from(be16(take(2)?)?);
    let n = be64(take(8)?)?;
    let s = take(8 * d)?
        .chunks_exact(8)
        .map(bei64)
        .collect::<Result<Vec<_>, _>>()?;
    let region = take(region_len)?.to_vec();
    let count = be64(take(8)?)?;
    if count != n {
        return Err(BlobReject::CountMismatch);
    }
    let mut members: Vec<(Vec<u8>, Vec<i64>)> = Vec::new();
    for _ in 0..count {
        let len = usize::from(be16(take(2)?)?);
        if len == 0 {
            return Err(BlobReject::EmptyId);
        }
        let id = take(len)?.to_vec();
        if core::str::from_utf8(&id).is_err() {
            return Err(BlobReject::Truncated);
        }
        if let Some((prev, _)) = members.last() {
            if id.as_slice() <= prev.as_slice() {
                return Err(BlobReject::Unsorted);
            }
        }
        let x = take(8 * d)?
            .chunks_exact(8)
            .map(bei64)
            .collect::<Result<Vec<_>, _>>()?;
        members.push((id, x));
    }
    if pos != blob.len() {
        return Err(BlobReject::TrailingBytes);
    }
    Ok(ParsedBlob {
        n,
        s,
        region,
        members,
    })
}

/// A frozen snapshot of one group with every exactness field stored as data, so each can be
/// corrupted on its own in the sabotage test (§5.5).
#[derive(Clone)]
pub struct GroupSnapshot<E: GroupExtension> {
    /// (1) `S`.
    pub s: Vec<i64>,
    /// (2) `n`.
    pub n: u64,
    /// (3) The extension's public state: `C_S` from Part 3 on (`()` in Part 1).
    pub ext_public: E::GroupPublic,
    /// (4) The canonical blob.
    pub blob: Vec<u8>,
    /// (5) The member ID list, ascending by bytes.
    pub member_ids: Vec<RecordId>,
}

/// The field in which two snapshots differ (the first one found, in §5.5 order).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Field {
    /// (1) `S`.
    S,
    /// (2) `n`.
    N,
    /// (3) `C_S` (the extension's public state).
    CommitmentS,
    /// (4) The canonical blob.
    Blob,
    /// (5) The member ID list.
    MemberIds,
}

/// §5.5: two group states are equivalent iff all five fields are equal. Each is compared on its
/// own; fields 1, 2, 3 and 5 are also inside field 4, and the redundancy is deliberate.
pub fn assert_state_equivalent<E: GroupExtension>(
    a: &GroupSnapshot<E>,
    b: &GroupSnapshot<E>,
) -> Result<(), Field> {
    if a.s != b.s {
        return Err(Field::S);
    }
    if a.n != b.n {
        return Err(Field::N);
    }
    if a.ext_public != b.ext_public {
        return Err(Field::CommitmentS);
    }
    if a.blob != b.blob {
        return Err(Field::Blob);
    }
    if a.member_ids != b.member_ids {
        return Err(Field::MemberIds);
    }
    Ok(())
}

/// The snapshot of a group built from `members` alone, starting from §5.2's initial state: the
/// "as if never inserted" side of the survivors check (Build §4.7 L6).
pub fn snapshot_from_members<E: GroupExtension>(
    ext: &E,
    d: usize,
    members: &[(&RecordId, &QVec, &E::RecordSecret)],
) -> GroupSnapshot<E> {
    let mut state = GroupState::<E>::empty(d);
    let mut sorted: Vec<_> = members.iter().collect();
    sorted.sort_by(|a, b| a.0.as_bytes().cmp(b.0.as_bytes()));
    for (_, x, rec) in &sorted {
        for (acc, &v) in state.s.iter_mut().zip(x.as_slice()) {
            *acc += i64::from(v);
        }
        state.n += 1;
        ext.add(&mut state.ext_public, &mut state.ext_secret, x, rec);
    }
    let pairs: Vec<(&RecordId, &QVec)> = members.iter().map(|(id, x, _)| (*id, *x)).collect();
    let blob = canonical_blob(ext, d, &state, &pairs);
    let member_ids = sorted.iter().map(|(id, _, _)| (*id).clone()).collect();
    GroupSnapshot {
        s: state.s,
        n: state.n,
        ext_public: state.ext_public,
        blob,
        member_ids,
    }
}
