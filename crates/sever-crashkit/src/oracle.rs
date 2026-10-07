//! The oracle file of `sever_refmodel_durable` and the state digest both sides compute.

use std::path::Path;

use serde_json::Value;
use sever_engine::hooks::CanonicalState;
use sha2::{Digest, Sha256};

/// One operation of the stream.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OracleOp {
    /// Insert `id` with vector row `row`.
    Insert {
        /// The record ID.
        id: String,
        /// Its row in the vector source.
        row: usize,
    },
    /// `delete_user` of these IDs, in order (one transaction).
    DeleteUser(Vec<String>),
    /// `delete` of one ID.
    Delete(String),
}

/// The oracle: the stream and the state digest before the first and after every operation.
#[derive(Clone, Debug)]
pub struct Oracle {
    /// The header line.
    pub header: Value,
    /// The operations.
    pub ops: Vec<OracleOp>,
    /// `digests[i]` is the state after the first `i` operations (`digests.len() == ops.len() + 1`).
    pub digests: Vec<[u8; 32]>,
}

fn hex32(v: &Value) -> Result<[u8; 32], String> {
    let s = v.as_str().ok_or("digest is not a string")?;
    let mut out = [0u8; 32];
    if s.len() != 64 {
        return Err("digest length".into());
    }
    for (i, b) in out.iter_mut().enumerate() {
        *b = s
            .get(2 * i..2 * i + 2)
            .and_then(|h| u8::from_str_radix(h, 16).ok())
            .ok_or("digest hex")?;
    }
    Ok(out)
}

/// Lowercase hex.
pub fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

impl Oracle {
    /// Reads an oracle file.
    pub fn read(path: &Path) -> Result<Self, String> {
        let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let mut lines = text.lines();
        let header: Value =
            serde_json::from_str(lines.next().ok_or("empty oracle")?).map_err(|e| e.to_string())?;
        if header.get("format").and_then(Value::as_str) != Some("sever-oracle-1") {
            return Err("not a sever-oracle-1 file".into());
        }
        let mut digests = vec![hex32(header.get("s0").ok_or("no s0")?)?];
        let mut ops = Vec::new();
        for line in lines {
            let v: Value = serde_json::from_str(line).map_err(|e| e.to_string())?;
            let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_owned);
            let op = match v.get("t").and_then(Value::as_str) {
                Some("i") => OracleOp::Insert {
                    id: s("id").ok_or("insert id")?,
                    row: v
                        .get("row")
                        .and_then(Value::as_u64)
                        .and_then(|r| usize::try_from(r).ok())
                        .ok_or("insert row")?,
                },
                Some("d") => OracleOp::DeleteUser(
                    v.get("ids")
                        .and_then(Value::as_array)
                        .ok_or("delete_user ids")?
                        .iter()
                        .map(|x| x.as_str().map(str::to_owned).ok_or("id"))
                        .collect::<Result<_, _>>()?,
                ),
                Some("x") => OracleOp::Delete(s("id").ok_or("delete id")?),
                _ => return Err("unknown operation".into()),
            };
            ops.push(op);
            digests.push(hex32(v.get("s").ok_or("no digest")?)?);
        }
        Ok(Self {
            header,
            ops,
            digests,
        })
    }
}

/// The canonical state digest, exactly as `sever_refmodel_durable.oracle.state_digest`:
/// `SHA-256("SEVERDB-STATE-1" ‖ u64be N ‖ u64be k ‖ u32be group_count ‖ per group ascending by
/// ID bytes (u16be len ‖ id ‖ u32be blob_len ‖ blob) ‖ u32be holding_count ‖ per holding ID
/// ascending by bytes (u16be len ‖ id))`.
pub fn state_digest(s: &CanonicalState) -> [u8; 32] {
    let mut h = Sha256::new();
    h.update(b"SEVERDB-STATE-1");
    h.update(s.big_n.to_be_bytes());
    h.update(s.k.to_be_bytes());
    h.update((s.groups.len() as u32).to_be_bytes());
    for (id, blob) in &s.groups {
        h.update((id.len() as u16).to_be_bytes());
        h.update(id.as_bytes());
        h.update((blob.len() as u32).to_be_bytes());
        h.update(blob);
    }
    h.update((s.holding.len() as u32).to_be_bytes());
    for id in &s.holding {
        h.update((id.len() as u16).to_be_bytes());
        h.update(id.as_bytes());
    }
    h.finalize().into()
}
