//! The trust anchors (spec §11.3): the operator's public keys by epoch, each witness's public keys
//! by epoch, and the dimension whose generators the bundled golden file fixes. Read from the JSON
//! that the engine publishes (`sever-db-p3 anchors`; spec §11.3, DB-85):
//! `{"d": N, "gdigest": hex, "operator": {"<epoch>": hex}, "witnesses": [{"<epoch>": hex}, …]}`,
//! the witnesses listed by index.

use std::collections::BTreeMap;

use crate::hex;

/// The anchors.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Anchors {
    /// The dimension.
    pub d: usize,
    /// `gdigest` as published (checked against the verifier's own derivation, §9.6).
    pub gdigest: Option<[u8; 64]>,
    /// The operator's keys by epoch.
    pub operator: BTreeMap<u32, [u8; 32]>,
    /// The witnesses' keys by `(witness_index, epoch)`.
    pub witnesses: BTreeMap<(u8, u32), [u8; 32]>,
}

/// Why the anchors file was refused.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct AnchorsError(pub &'static str);

fn ring(v: &serde_json::Value) -> Result<BTreeMap<u32, [u8; 32]>, AnchorsError> {
    let bad = AnchorsError("a key ring is not {epoch: 64 hex}");
    v.as_object()
        .ok_or(bad)?
        .iter()
        .map(|(e, k)| {
            Ok((
                e.parse().map_err(|_| bad)?,
                hex::decode_n(k.as_str().ok_or(bad)?).ok_or(bad)?,
            ))
        })
        .collect()
}

impl Anchors {
    /// Parses the anchors JSON.
    pub fn from_json(text: &str) -> Result<Self, AnchorsError> {
        let v: serde_json::Value =
            serde_json::from_str(text).map_err(|_| AnchorsError("not JSON"))?;
        let d = v
            .get("d")
            .and_then(serde_json::Value::as_u64)
            .and_then(|d| usize::try_from(d).ok())
            .ok_or(AnchorsError("d is missing"))?;
        let gdigest = match v.get("gdigest") {
            None => None,
            Some(g) => Some(
                g.as_str()
                    .and_then(hex::decode_n)
                    .ok_or(AnchorsError("gdigest is not 128 hex"))?,
            ),
        };
        let operator = ring(
            v.get("operator")
                .ok_or(AnchorsError("operator is missing"))?,
        )?;
        let mut witnesses = BTreeMap::new();
        let list = v
            .get("witnesses")
            .and_then(serde_json::Value::as_array)
            .ok_or(AnchorsError("witnesses is not a list"))?;
        for (i, w) in list.iter().enumerate() {
            let i = u8::try_from(i).map_err(|_| AnchorsError("too many witnesses"))?;
            for (e, k) in ring(w)? {
                witnesses.insert((i, e), k);
            }
        }
        Ok(Self {
            d,
            gdigest,
            operator,
            witnesses,
        })
    }
}
