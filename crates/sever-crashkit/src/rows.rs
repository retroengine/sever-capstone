//! Vector sources for the stream: the small fixture (JSON) and a corpus `.npy` file.

use std::path::Path;

use sever_tracekit::Npy;

/// Row `i` of the stream's vectors.
pub trait Rows {
    /// The vector of row `i`.
    fn row(&self, i: usize) -> Result<Vec<f32>, String>;
}

/// The small fixture (`golden/p1_fixture_vectors.json`): `ref` rows, then `live` rows, d = 16.
pub struct FixtureRows(Vec<Vec<f32>>);

impl FixtureRows {
    /// Reads the fixture.
    pub fn read(path: &Path) -> Result<Self, String> {
        let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
        let doc: serde_json::Value = serde_json::from_str(&text).map_err(|e| e.to_string())?;
        let mut rows = Vec::new();
        for key in ["ref", "live"] {
            for h in doc
                .get(key)
                .and_then(serde_json::Value::as_array)
                .ok_or("fixture rows")?
            {
                let h = h.as_str().ok_or("fixture row")?;
                let bytes: Vec<u8> = (0..h.len() / 2)
                    .map(|i| {
                        h.get(2 * i..2 * i + 2)
                            .and_then(|x| u8::from_str_radix(x, 16).ok())
                    })
                    .collect::<Option<_>>()
                    .ok_or("fixture hex")?;
                rows.push(
                    bytes
                        .chunks_exact(4)
                        .map(|c| <[u8; 4]>::try_from(c).map(f32::from_le_bytes))
                        .collect::<Result<Vec<f32>, _>>()
                        .map_err(|_| "fixture row")?,
                );
            }
        }
        Ok(Self(rows))
    }
}

impl Rows for FixtureRows {
    fn row(&self, i: usize) -> Result<Vec<f32>, String> {
        self.0.get(i).cloned().ok_or_else(|| format!("row {i}"))
    }
}

/// A corpus `.npy` matrix (row-addressable, read on demand).
pub struct NpyRows(pub Npy);

impl Rows for NpyRows {
    fn row(&self, i: usize) -> Result<Vec<f32>, String> {
        self.0.row(i).map_err(|e| e.0)
    }
}
