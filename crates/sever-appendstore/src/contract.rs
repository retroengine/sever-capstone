//! The EP-8 contract suite (Build §3.4, test level L7): what every [`AppendStore`] must do.
//! Part 3's log-leaf and certificate stores run it unchanged.

use crate::{AppendStore, StoreRef};

/// Why a store failed the EP-8 contract.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Ep8Violation {
    /// A call that must succeed failed.
    Failed(&'static str),
    /// A record read back differs from the one appended.
    ReadBack,
    /// Two appends returned overlapping references.
    Overlap,
    /// A reference that was altered (offset or length) still read successfully.
    AlteredRefAccepted,
}

/// EP-8: append, sync and read back records of every size, including empty and large values;
/// references never overlap; an altered reference is refused. `store` must be empty and writable.
pub fn ep8_contract(store: &mut dyn AppendStore) -> Result<(), Ep8Violation> {
    let values: Vec<(u64, Vec<u8>)> = vec![
        (0, vec![]),
        (1, b"a".to_vec()),
        (u64::MAX, vec![0x5a; 3_000]),
        (7, (0..=255).collect()),
        (8, vec![0; 70_000]),
    ];
    let mut refs: Vec<StoreRef> = Vec::new();
    for (k, v) in &values {
        refs.push(
            store
                .append(*k, v)
                .map_err(|_| Ep8Violation::Failed("append"))?,
        );
    }
    store.sync().map_err(|_| Ep8Violation::Failed("sync"))?;
    store
        .sync()
        .map_err(|_| Ep8Violation::Failed("sync twice"))?;
    for ((k, v), r) in values.iter().zip(&refs) {
        let rec = store.read(r).map_err(|_| Ep8Violation::Failed("read"))?;
        if rec.key != *k || rec.bytes != *v || r.len as usize != v.len() {
            return Err(Ep8Violation::ReadBack);
        }
    }
    for (i, a) in refs.iter().enumerate() {
        for b in refs.iter().skip(i + 1) {
            let end = |r: &StoreRef| r.offset + 16 + u64::from(r.len);
            if a.segment == b.segment && a.offset < end(b) && b.offset < end(a) {
                return Err(Ep8Violation::Overlap);
            }
        }
    }
    for r in &refs {
        for altered in [
            StoreRef {
                len: r.len + 1,
                ..*r
            },
            StoreRef {
                offset: r.offset + 1,
                ..*r
            },
        ] {
            if store.read(&altered).is_ok() {
                return Err(Ep8Violation::AlteredRefAccepted);
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{DEFAULT_SEGMENT_BYTES, FileStore, StoreConfig};
    use sever_format::StoreRecord;
    use sever_spec::spec;
    use sever_types::Error;
    use sever_vfs::SimVfs;
    use std::sync::Arc;

    fn file_store(segment_bytes: u64) -> FileStore {
        FileStore::create(
            Arc::new(SimVfs::new()),
            StoreConfig {
                dir: "payloads".into(),
                sealer_id: 0,
                segment_bytes,
            },
        )
        .unwrap()
    }

    #[test]
    #[spec("SR-14.8-1")]
    fn p2_store_ep8_file_store_passes_contract() {
        assert_eq!(ep8_contract(&mut file_store(DEFAULT_SEGMENT_BYTES)), Ok(()));
        // With a tiny segment size every record rolls over to a new segment.
        assert_eq!(ep8_contract(&mut file_store(64)), Ok(()));
    }

    /// Deliberately wrong: reads ignore the reference and return the last record.
    struct Forgetful(Vec<StoreRecord>);
    impl AppendStore for Forgetful {
        fn append(&mut self, key: u64, bytes: &[u8]) -> Result<StoreRef, Error> {
            self.0.push(StoreRecord {
                key,
                bytes: bytes.to_vec(),
            });
            Ok(StoreRef {
                segment: 1,
                offset: 16 * self.0.len() as u64 * 100_000,
                len: bytes.len() as u32,
            })
        }
        fn sync(&mut self) -> Result<(), Error> {
            Ok(())
        }
        fn read(&self, _at: &StoreRef) -> Result<StoreRecord, Error> {
            self.0.last().cloned().ok_or(Error::DurabilityFailure)
        }
    }

    // Build §3.4: a deliberately wrong implementation fails the contract.
    #[test]
    fn p2_store_ep8_contract_rejects_a_wrong_store() {
        assert_eq!(
            ep8_contract(&mut Forgetful(Vec::new())),
            Err(Ep8Violation::ReadBack)
        );
    }
}
