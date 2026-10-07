//! L1/L8 tests of the transaction layer on the small fixture (d = 16, 4 frozen groups, spawn
//! target 8): a real Part 1 index, the storage image, the WAL and the payload store on `SimVfs`.

use std::cell::Cell;
use std::sync::{Arc, Mutex};

use sever_appendstore::{AppendStore, FileStore, StoreConfig};
use sever_format::{CollectionMeta, CoreRecord, DbImage, Layout};
use sever_index::{
    DeleteRequest, HmacSha512Scrambler, Index, IndexConfig, InsertRequest, NoExtension, Outcome,
    Placement,
};
use sever_partition::PartitionArtefact;
use sever_spec::spec;
use sever_types::{CollectionId, Error, GroupId};
use sever_vfs::{FaultPlan, SimVfs, Vfs};
use sever_wal::{Wal, WalConfig};

use crate::*;

type Ix = Index<NoExtension, HmacSha512Scrambler>;
const ARTEFACT: &[u8] = include_bytes!("../../../golden/p1_partition_small.svp");

fn rows(key: &str) -> Vec<Vec<f32>> {
    let doc: serde_json::Value =
        serde_json::from_str(include_str!("../../../golden/p1_fixture_vectors.json")).unwrap();
    doc[key]
        .as_array()
        .unwrap()
        .iter()
        .map(|h| {
            let h = h.as_str().unwrap();
            (0..h.len() / 8)
                .map(|i| {
                    let b: Vec<u8> = (0..4)
                        .map(|j| {
                            u8::from_str_radix(&h[8 * i + 2 * j..8 * i + 2 * j + 2], 16).unwrap()
                        })
                        .collect();
                    f32::from_le_bytes(b.try_into().unwrap())
                })
                .collect()
        })
        .collect()
}

/// The transaction layer around one collection, as the engine will hold it.
struct Mini {
    v: SimVfs,
    ix: Ix,
    img: DbImage,
    wal: Wal,
    store: FileStore,
    cid: CollectionId,
    layout: Layout,
    ps: Participants<NoExtension>,
    key: u64,
}

impl Mini {
    fn new() -> Self {
        let v = SimVfs::new();
        let vfs: Arc<dyn Vfs> = Arc::new(v.clone());
        let wal = Wal::create(Arc::clone(&vfs), WalConfig::new(0), 1, 1).unwrap();
        let store = FileStore::create(
            Arc::clone(&vfs),
            StoreConfig {
                dir: "payloads".into(),
                sealer_id: 0,
                segment_bytes: 1 << 20,
            },
        )
        .unwrap();
        let art = PartitionArtefact::parse(ARTEFACT).unwrap();
        let cid = CollectionId::from_bytes([1; 16]);
        let ix = Index::new(
            &art,
            IndexConfig {
                spawning_enabled: true,
                spawn_target: 8,
            },
            NoExtension,
            HmacSha512Scrambler::new(&[7; 64]),
            cid,
        )
        .unwrap();
        let layout = layout_for::<NoExtension>(art.d, &PlaintextSealer);
        let mut m = Self {
            v,
            ix,
            img: DbImage::default(),
            wal,
            store,
            cid,
            layout,
            ps: Vec::new(),
            key: 0,
        };
        let meta = CollectionMeta {
            cid,
            d: art.d as u16,
            spawn_target: 8,
            spawning_enabled: true,
            store_passages: true,
            artefact_sha256: art.sha256_artefact,
        };
        let records = collection_records::<NoExtension>(
            meta,
            ARTEFACT.to_vec(),
            &art.centroids,
            &PlaintextSealer,
        )
        .unwrap();
        m.run(TxnKind::CreateCollection, None, records).unwrap();
        m
    }

    /// Commits `records` (and installs `cs` in the index) through the protocol.
    fn run(
        &mut self,
        kind: TxnKind,
        cs: Option<sever_index::ChangeSet<NoExtension>>,
        records: Vec<CoreRecord>,
    ) -> Result<Acknowledged, Error> {
        let Self {
            ix,
            img,
            wal,
            store,
            cid,
            layout,
            ps,
            ..
        } = self;
        let draft = TxnDraft {
            kind,
            collection: *cid,
            changeset: cs.as_ref(),
            records,
            participant_records: Vec::new(),
            outputs: Vec::new(),
        };
        let apply = |recs: &[CoreRecord]| {
            for r in recs {
                img.apply(r).unwrap();
            }
        };
        let ack = commit(
            draft,
            layout,
            ps,
            Durable { wal, store },
            apply,
            &mut |_| {},
        )?;
        if let Some(cs) = cs {
            ix.apply(cs);
        }
        Ok(ack)
    }

    fn insert(&mut self, id: &str, v: &[f32], passage: Option<&[u8]>) -> Result<Placement, Error> {
        let cs = self.ix.plan_insert(InsertRequest {
            record_id: id.into(),
            vector: v.to_vec(),
            credential: (),
        })?;
        let placement = match cs.outcomes.first() {
            Some(Outcome::Placed(p)) => *p,
            _ => panic!("an insert places"),
        };
        let coll = self.img.collection(&self.cid).unwrap();
        let (store, key) = (&mut self.store, &mut self.key);
        let records = changeset_records(
            coll,
            &self.layout,
            &cs,
            &PlaintextSealer,
            passage,
            &mut |b| {
                *key += 1;
                store.append(*key, b)
            },
        )?;
        self.run(TxnKind::Insert, Some(cs), records)?;
        Ok(placement)
    }

    fn delete(&mut self, ids: &[&str]) -> Result<Vec<Outcome>, Error> {
        let cs = self.ix.plan_delete_many(
            ids.iter()
                .map(|i| DeleteRequest {
                    record_id: (*i).into(),
                })
                .collect(),
        )?;
        let out = cs.outcomes.clone();
        if cs.is_noop() {
            return Ok(out);
        }
        let coll = self.img.collection(&self.cid).unwrap();
        let records =
            changeset_records(coll, &self.layout, &cs, &PlaintextSealer, None, &mut |_| {
                panic!("a delete stores no passage")
            })?;
        self.run(TxnKind::Delete, Some(cs), records)?;
        Ok(out)
    }

    /// A fresh index rebuilt from the image alone.
    fn rebuilt(&self, img: &DbImage) -> Ix {
        let art = PartitionArtefact::parse(ARTEFACT).unwrap();
        let mut ix = Index::new(
            &art,
            IndexConfig {
                spawning_enabled: true,
                spawn_target: 8,
            },
            NoExtension,
            HmacSha512Scrambler::new(&[7; 64]),
            self.cid,
        )
        .unwrap();
        let coll = img.collection(&self.cid).unwrap();
        let groups =
            decode_collection::<NoExtension>(coll, &self.layout, &PlaintextSealer).unwrap();
        ix.apply(rebuild_changeset(
            art.d,
            groups,
            sever_index::Counters {
                big_n: coll.big_n,
                k: coll.k,
            },
        ));
        ix
    }

    /// The image rebuilt from the WAL alone, as recovery does it.
    fn replayed(&self) -> DbImage {
        let vfs: Arc<dyn Vfs> = Arc::new(self.v.fork());
        let (_, txns, _) = Wal::recover(vfs, WalConfig::new(0), 1, 1).unwrap();
        let mut img = DbImage::default();
        for r in txns.iter().flat_map(|t| &t.records) {
            let layout_of = |c: &CollectionId| img.collection(c).map(|_| self.layout);
            let rec = CoreRecord::parse(r.ty, &r.payload, &layout_of).unwrap();
            img.apply(&rec).unwrap();
        }
        img
    }

    /// The image, the index rebuilt from it, and the WAL replay all agree with the live index.
    fn check(&self) {
        let rebuilt = self.rebuilt(&self.img);
        assert_eq!(rebuilt.stats(), self.ix.stats());
        assert_eq!(rebuilt.group_ids(), self.ix.group_ids());
        for g in self.ix.group_ids() {
            assert_eq!(rebuilt.blob(&g), self.ix.blob(&g), "{}", g.as_text());
            assert_eq!(rebuilt.group_len(&g), self.ix.group_len(&g));
        }
        rebuilt.check_invariants().unwrap();
        assert_eq!(self.replayed(), self.img, "WAL replay = image");
        let coll = self.img.collection(&self.cid).unwrap();
        for g in &coll.groups {
            assert_eq!(
                g.header.n,
                g.slots.len() as u64,
                "{}",
                g.header.group_id.as_text()
            );
        }
        for (sid, (g, i)) in &coll.locator {
            let slot = &coll.group(g).unwrap().slots[*i as usize];
            assert_eq!(&slot.scrambled_id, sid, "INV-7");
        }
        let slots: usize = coll.groups.iter().map(|g| g.slots.len()).sum();
        assert_eq!(coll.locator.len(), slots, "INV-7: one entry per slot");
    }
}

#[test]
#[spec("SR-12.3-1", "SR-15.1-1", "SR-15.2-1", "SR-15.3-1", "SR-12.6-1")]
fn p2_txn_after_images_reproduce_the_index_through_inserts_flushes_and_deletes() {
    let mut m = Mini::new();
    m.check();
    let (inside, outside) = (rows("ref"), rows("live"));
    let mut placements = Vec::new();
    for (i, v) in inside.iter().enumerate().take(60) {
        placements.push(
            m.insert(&format!("in-{i}"), v, Some(format!("text {i}").as_bytes()))
                .unwrap(),
        );
    }
    for (i, v) in outside.iter().enumerate() {
        placements.push(m.insert(&format!("out-{i}"), v, None).unwrap());
        if i % 5 == 0 {
            m.check();
        }
    }
    assert!(
        placements
            .iter()
            .any(|p| matches!(p, Placement::Spawned(_))),
        "flushes happened"
    );
    assert!(placements.iter().any(|p| matches!(p, Placement::Holding)));
    m.check();
    // Deletes: members of frozen and spawned groups, holding records, absent IDs, and one
    // delete_user over many groups.
    for i in (0..60).step_by(3) {
        assert!(matches!(
            m.delete(&[&format!("in-{i}")]).unwrap()[0],
            Outcome::Deleted { .. }
        ));
    }
    let mut extra = 0;
    while m.ix.stats().holding == 0 {
        let v = &outside[extra % outside.len()];
        m.insert(&format!("extra-{extra}"), v, None).unwrap();
        extra += 1;
        assert!(extra < 1_000, "nothing ever stays in the holding area");
    }
    let holding: Vec<String> = (0..120)
        .map(|i| format!("out-{i}"))
        .chain((0..extra).map(|i| format!("extra-{i}")))
        .filter(|id| m.ix.location(id) == Some(GroupId::Holding))
        .collect();
    assert!(!holding.is_empty());
    m.delete(&[&holding[0]]).unwrap();
    assert_eq!(
        m.delete(&["never-inserted"]).unwrap(),
        vec![Outcome::AlreadyAbsent]
    );
    let cohort: Vec<String> = (1..120).step_by(2).map(|i| format!("out-{i}")).collect();
    let refs: Vec<&str> = cohort.iter().map(String::as_str).collect();
    m.delete(&refs).unwrap();
    m.check();
    // Re-insert after delete (§3.2 rule 3 applies only to live IDs).
    m.insert("in-0", &inside[0], None).unwrap();
    m.check();
}

#[test]
#[spec("SR-14.6-3")]
fn p2_txn_passage_text_is_stored_before_commit_and_referenced() {
    let mut m = Mini::new();
    let v = &rows("ref")[0];
    m.insert("doc", v, Some(b"the passage")).unwrap();
    let coll = m.img.collection(&m.cid).unwrap();
    assert_eq!(coll.payload_refs.len(), 1);
    let at = coll.payload_refs.values().next().unwrap();
    assert_eq!(m.store.read(at).unwrap().bytes, b"the passage");
    m.delete(&["doc"]).unwrap();
    assert!(m.img.collection(&m.cid).unwrap().payload_refs.is_empty());
}

// SB-15 must turn this red.
#[test]
#[spec("SR-12.3-2", "SR-15.8-1")]
fn p2_txn_nothing_reaches_memory_before_the_commit_point() {
    let mut m = Mini::new();
    let v = rows("ref")[0].clone();
    let cs =
        m.ix.plan_insert(InsertRequest {
            record_id: "a".into(),
            vector: v,
            credential: (),
        })
        .unwrap();
    let coll = m.img.collection(&m.cid).unwrap();
    let records = changeset_records(
        coll,
        &m.layout,
        &cs,
        &PlaintextSealer,
        None,
        &mut |_| unreachable!(),
    )
    .unwrap();
    let applied = Cell::new(false);
    let mut seen = Vec::new();
    let draft = TxnDraft {
        kind: TxnKind::Insert,
        collection: m.cid,
        changeset: Some(&cs),
        records,
        participant_records: Vec::new(),
        outputs: Vec::new(),
    };
    commit(
        draft,
        &m.layout,
        &mut m.ps,
        Durable {
            wal: &mut m.wal,
            store: &mut m.store,
        },
        |_| applied.set(true),
        &mut |s| seen.push((s, applied.get())),
    )
    .unwrap();
    for (step, was_applied) in seen {
        let after = matches!(step, Step::Applied | Step::PhaseC);
        assert_eq!(was_applied, after, "at {step:?}");
    }
}

#[test]
#[spec("SR-12.7-2", "SR-15.8-1")]
fn p2_txn_a_failed_wal_write_changes_nothing_in_memory() {
    let mut m = Mini::new();
    let before = m.img.clone();
    let stats = m.ix.stats();
    m.v.set_faults(FaultPlan {
        fail_sync_at: Some(1),
        ..FaultPlan::default()
    });
    assert_eq!(
        m.insert("x", &rows("ref")[0], None),
        Err(Error::DurabilityFailure)
    );
    assert_eq!(m.img, before);
    assert_eq!(m.ix.stats(), stats);
    assert_eq!(
        m.insert("y", &rows("ref")[1], None),
        Err(Error::DurabilityFailure),
        "poisoned"
    );
}

/// Records every hook it sees.
struct Recorder(Arc<Mutex<Vec<&'static str>>>, bool);
impl TxnParticipant<NoExtension> for Recorder {
    fn id(&self) -> u16 {
        7
    }
    fn prepare(&mut self, d: &mut TxnDraft<'_, NoExtension>) -> Result<(), Error> {
        self.0.lock().unwrap().push("prepare");
        d.participant_records
            .push((sever_format::RecordType::Extension, vec![0, 7, 42]));
        d.outputs.push((7, 0, b"receipt".to_vec()));
        if self.1 {
            return Err(Error::IntegrityViolation { invariant: "test" });
        }
        Ok(())
    }
    fn sync_stores(&mut self) -> Result<(), Error> {
        self.0.lock().unwrap().push("sync_stores");
        Ok(())
    }
    fn phase_a(&mut self) -> Result<(), Error> {
        self.0.lock().unwrap().push("phase_a");
        Ok(())
    }
    fn abort(&mut self) {
        self.0.lock().unwrap().push("abort");
    }
    fn after_commit(&mut self) -> Result<(), Error> {
        self.0.lock().unwrap().push("after_commit");
        Ok(())
    }
}

#[test]
#[spec("SR-14.6-2")]
fn p2_txn_participants_run_in_protocol_order_and_their_records_are_logged() {
    let mut m = Mini::new();
    let log = Arc::new(Mutex::new(Vec::new()));
    m.ps.push(Box::new(Recorder(Arc::clone(&log), false)));
    m.insert("a", &rows("ref")[0], None).unwrap();
    assert_eq!(
        *log.lock().unwrap(),
        ["prepare", "sync_stores", "phase_a", "after_commit"]
    );
    let vfs: Arc<dyn Vfs> = Arc::new(m.v.fork());
    let (_, txns, _) = Wal::recover(vfs, WalConfig::new(0), 1, 1).unwrap();
    let last = txns.last().unwrap().records.last().unwrap();
    assert_eq!(last.ty, sever_format::RecordType::Extension);
    assert_eq!(
        last.payload,
        vec![0, 7, 42],
        "carried verbatim, after the core records"
    );
    assert!(Recorder(log, false).owns(last));
}

#[test]
fn p2_txn_a_failing_prepare_aborts_with_nothing_written() {
    let mut m = Mini::new();
    let log = Arc::new(Mutex::new(Vec::new()));
    m.ps.push(Box::new(Recorder(Arc::clone(&log), true)));
    let next = m.wal.next_wal_seq();
    assert!(m.insert("a", &rows("ref")[0], None).is_err());
    assert_eq!(*log.lock().unwrap(), ["prepare", "abort"]);
    assert_eq!(m.wal.next_wal_seq(), next);
    assert_eq!(m.ix.location("a"), None);
}

#[test]
fn p2_txn_layout_follows_extension_and_sealer() {
    assert_eq!(
        layout_for::<NoExtension>(384, &PlaintextSealer),
        Layout::plain(384)
    );
}

#[test]
#[spec("SR-14.3-1", "SR-7.4-1")]
fn p2_txn_holding_header_counts_its_records() {
    let mut m = Mini::new();
    let holding_n = |m: &Mini| {
        let c = m.img.collection(&m.cid).unwrap();
        (
            c.group(&GroupId::Holding).unwrap().header.n,
            m.ix.stats().holding,
        )
    };
    let mut ids = Vec::new();
    for (i, v) in rows("live").iter().enumerate() {
        let id = format!("o-{i}");
        if m.insert(&id, v, None).unwrap() == Placement::Holding {
            ids.push(id);
        }
        let (n, live) = holding_n(&m);
        assert_eq!(n, live, "after insert {i}");
        if live >= 3 {
            break;
        }
    }
    assert!(
        holding_n(&m).1 >= 3,
        "the fixture puts records in the holding area"
    );
    m.delete(&[ids.last().unwrap()]).unwrap();
    let (n, live) = holding_n(&m);
    assert_eq!(n, live, "after a holding deletion");
    m.check();
}

// ----- small fixed rules -----

#[test]
fn p2_txn_system_clock_is_wall_clock_milliseconds() {
    // EP-9: time for log checkpoints and key epochs, in ms since the Unix epoch.
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis() as u64;
    let t = SystemClock::default().now_ms();
    assert!(t.abs_diff(now) < 60_000, "{t} vs {now}");
}

#[test]
#[spec("SR-14-1")]
fn p2_txn_plaintext_sealer_refuses_any_envelope_bytes() {
    // DB-48: with the plaintext sealer the wrapped record key is empty (§14.4).
    let (cid, g, sid) = (
        CollectionId::from_bytes([1; 16]),
        GroupId::Holding,
        sever_types::ScrambledId::from_bytes([2; 64]),
    );
    let o = RecordOwner {
        collection: &cid,
        group: &g,
        scrambled_id: &sid,
    };
    let (env, sealed) = PlaintextSealer.seal_record(&o, b"abc").unwrap();
    assert!(env.is_empty());
    assert!(PlaintextSealer.open_record(&o, &[0], &sealed).is_err());
    assert!(PlaintextSealer.rewrap_record(&o, &o, &[0]).is_err());
    assert!(PlaintextSealer.seal_passage(&o, &[0], b"t").is_err());
    assert!(PlaintextSealer.open_passage(&o, &[0], b"t").is_err());
    assert_eq!(
        PlaintextSealer.rewrap_record(&o, &o, &[]).unwrap(),
        Vec::<u8>::new()
    );
}

#[test]
fn p2_txn_no_extension_stores_no_bytes() {
    // DB-46: with no extension (Parts 1–2) every extension field is empty, and a non-empty one
    // is corrupt.
    type N = sever_index::NoExtension;
    assert!(<N as StoredExtension>::decode_public(&[]).is_ok());
    assert!(<N as StoredExtension>::decode_public(&[0]).is_err());
    assert!(<N as StoredExtension>::decode_group_secret(&[0]).is_err());
    assert!(<N as StoredExtension>::decode_record_secret(&[0]).is_err());
}

/// A participant with only the trait's defaults.
struct Plain;
impl TxnParticipant<sever_index::NoExtension> for Plain {
    fn id(&self) -> u16 {
        0x0102
    }
}

#[test]
fn p2_txn_a_participant_owns_only_its_extension_records() {
    // DB-45: EXTENSION payloads start with u16be participant_id.
    let rec = |ty, payload: Vec<u8>| sever_format::WalRecord {
        ty,
        wal_seq: 1,
        txn_id: 1,
        payload,
    };
    use sever_format::RecordType as T;
    assert!(Plain.owns(&rec(T::Extension, vec![1, 2, 9])));
    assert!(!Plain.owns(&rec(T::Extension, vec![1, 3, 9])));
    assert!(!Plain.owns(&rec(T::Extension, vec![1])));
    assert!(!Plain.owns(&rec(T::LogLeaf, vec![1, 2])));
    assert!(Plain.owned_types().is_empty());
}
