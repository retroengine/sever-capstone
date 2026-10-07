//! L1/L10 tests of storage checkpoints on `SimVfs` (spec §12.4, §15.6).

use sever_format::group::encode_accumulator;
use sever_format::{CoreRecord, GroupHeader, PayloadRef, SlotBytes, SlotPayload};
use sever_spec::spec;
use sever_types::{GroupId, RecordId, ScrambledId};
use sever_vfs::{CrashPolicy, FaultPlan, SimVfs};

use super::*;

const D: usize = 8;

fn layout(_: &CollectionMeta) -> Layout {
    Layout::plain(D)
}

fn header(id: GroupId, n: u64) -> GroupHeader {
    let holding = id == GroupId::Holding;
    GroupHeader {
        group_id: id,
        seal_version: 0,
        n,
        ext_public: vec![],
        centroid: vec![if holding { 0.0 } else { 0.5 }; D],
        sealed_accumulator: if holding {
            vec![]
        } else {
            encode_accumulator(&[n as i64; D], &[])
        },
    }
}

/// An image with `collections` collections and `members` records in frozen-0000 each.
fn image(collections: u8, members: u8) -> DbImage {
    let l = Layout::plain(D);
    let mut img = DbImage::default();
    for c in 1..=collections {
        let cid = CollectionId::from_bytes([c; 16]);
        let g = GroupId::frozen(0).unwrap();
        let mut recs = vec![
            CoreRecord::CollectionCreate {
                meta: CollectionMeta {
                    cid,
                    d: D as u16,
                    spawn_target: 8,
                    spawning_enabled: true,
                    store_passages: true,
                    artefact_sha256: [c; 32],
                },
                artefact: vec![c; 100],
            },
            CoreRecord::GroupCreate {
                cid,
                header: header(g, 0),
                bucket_block: vec![],
            },
            CoreRecord::GroupCreate {
                cid,
                header: header(GroupId::Holding, 0),
                bucket_block: vec![],
            },
        ];
        for m in 0..members {
            let sid = ScrambledId::from_bytes([m.wrapping_add(c * 50); 64]);
            recs.push(CoreRecord::SlotPut {
                cid,
                group: g,
                index: u64::from(m),
                slot: SlotBytes {
                    scrambled_id: sid,
                    envelope: vec![],
                    sealed_payload: SlotPayload {
                        record_id: RecordId::new(format!("doc-{m}")).unwrap(),
                        x: vec![i32::from(m); D],
                        ext_secret: vec![],
                    }
                    .encode(&l)
                    .unwrap(),
                },
            });
            recs.push(CoreRecord::LocatorPut {
                cid,
                scrambled_id: sid,
                group: g,
                index: u64::from(m),
            });
            recs.push(CoreRecord::PayloadRef {
                cid,
                scrambled_id: sid,
                at: PayloadRef {
                    segment: 1,
                    offset: 16 + 30 * u64::from(m),
                    len: 14,
                },
            });
        }
        recs.push(CoreRecord::GroupHeader {
            cid,
            header: header(g, u64::from(members)),
        });
        recs.push(CoreRecord::Counters {
            cid,
            big_n: u64::from(members),
            k: 1,
        });
        for r in &recs {
            img.apply(r).unwrap();
        }
    }
    img
}

fn meta(id: u64, next_wal_seq: u64) -> CheckpointMeta {
    CheckpointMeta {
        checkpoint_id: id,
        next_wal_seq,
        next_txn_id: id * 10,
        config_hash: [9; 32],
    }
}

fn fresh() -> SimVfs {
    let v = SimVfs::new();
    create_root(&v).unwrap();
    v
}

fn load_current(v: &SimVfs) -> (CheckpointMeta, DbImage) {
    let m = read_manifest(v, 0).unwrap().expect("a manifest");
    load(v, &m, &layout).unwrap()
}

#[test]
#[spec("SR-15.6-1", "SR-15.6-2", "SR-15.6-3", "SR-14.9-1", "SR-14.1-1")]
fn p2_checkpoint_write_then_load_round_trips() {
    let v = fresh();
    assert_eq!(read_manifest(&v, 0).unwrap(), None, "no database yet");
    let img = image(2, 5);
    write(&v, 0, &img, &meta(1, 40), &layout).unwrap();
    v.restart(CrashPolicy::DropAll);
    assert_eq!(load_current(&v), (meta(1, 40), img));
    let names = v.list(&checkpoint_path(1)).unwrap();
    assert_eq!(
        names,
        [
            "collections.bin",
            "groups.bin",
            "locator.bin",
            "meta.bin",
            "partitions",
            "payloads.bin",
            "slots.bin"
        ]
    );
    assert_eq!(
        v.list(&format!("{}/partitions", checkpoint_path(1)))
            .unwrap()
            .len(),
        2
    );
}

#[test]
#[spec("SR-12.4-2", "SR-15.6-2", "SR-15.6-3")]
fn p2_checkpoint_interrupted_at_every_operation_leaves_old_or_new() {
    let base = fresh();
    let (old_img, new_img) = (image(1, 3), image(2, 4));
    write(&base, 0, &old_img, &meta(1, 10), &layout).unwrap();
    let dry = base.fork();
    dry.set_faults(FaultPlan::default());
    write(&dry, 0, &new_img, &meta(2, 50), &layout).unwrap();
    remove_others(&dry, 2).unwrap();
    let ops = dry.ops_since_plan();
    for k in 1..=ops {
        for policy in [
            CrashPolicy::DropAll,
            CrashPolicy::KeepAll,
            CrashPolicy::Random(k),
        ] {
            let v = base.fork();
            v.set_faults(FaultPlan {
                crash_at_op: Some(k),
                tear_bytes: 100,
                ..FaultPlan::default()
            });
            let _ =
                write(&v, 0, &new_img, &meta(2, 50), &layout).and_then(|()| remove_others(&v, 2));
            v.restart(policy);
            let got = load_current(&v);
            assert!(
                got == (meta(1, 10), old_img.clone()) || got == (meta(2, 50), new_img.clone()),
                "k = {k}, {policy:?}"
            );
            // Cleanup at the next start leaves exactly the current checkpoint.
            remove_others(&v, got.0.checkpoint_id).unwrap();
            assert_eq!(
                v.list(CHECKPOINT_DIR).unwrap(),
                [format!("{:020}", got.0.checkpoint_id)]
            );
            // And the next checkpoint (same ID as the interrupted one) still installs.
            write(&v, 0, &new_img, &meta(3, 60), &layout).unwrap();
            assert_eq!(load_current(&v), (meta(3, 60), new_img.clone()));
        }
    }
}

#[test]
#[spec("SR-14-2", "SR-12.7-4")]
fn p2_checkpoint_corruption_is_refused() {
    let v = fresh();
    write(&v, 0, &image(1, 3), &meta(1, 10), &layout).unwrap();
    let m = read_manifest(&v, 0).unwrap().unwrap();
    for name in ["meta.bin", "groups.bin", "slots.bin", "locator.bin"] {
        let w = v.fork();
        let path = format!("{}/{name}", checkpoint_path(1));
        let mut f = w.open(&path, OpenMode::Existing).unwrap();
        let mut b = [0u8; 1];
        f.read_at(16_384 + 30, &mut b).unwrap();
        f.write_at(16_384 + 30, &[b[0] ^ 0x10]).unwrap();
        assert!(load(&w, &m, &layout).is_err(), "{name}");
    }
    let w = v.fork();
    w.unlink(&format!("{}/locator.bin", checkpoint_path(1)))
        .unwrap();
    assert_eq!(
        load(&w, &m, &layout).err(),
        Some(bad("§14.1 checkpoint file missing"))
    );
    let w = v.fork();
    let parts = format!("{}/partitions", checkpoint_path(1));
    w.rename(
        &format!(
            "{parts}/{}",
            partition_name(&CollectionId::from_bytes([1; 16]))
        ),
        &format!(
            "{parts}/{}",
            partition_name(&CollectionId::from_bytes([2; 16]))
        ),
    )
    .unwrap();
    assert!(
        load(&w, &m, &layout).is_err(),
        "artefact under another collection's name"
    );
}

#[test]
#[spec("SR-14-2")]
fn p2_checkpoint_refuses_another_sealer() {
    let v = fresh();
    write(&v, 0, &image(1, 1), &meta(1, 10), &layout).unwrap();
    assert_eq!(read_manifest(&v, 1).err(), Some(bad("DB-48 sealer_id")));
    let m = read_manifest(&v, 0).unwrap().unwrap();
    let other = Manifest { sealer_id: 1, ..m };
    assert_eq!(
        load(&v, &other, &layout).err(),
        Some(bad("DB-48 sealer_id"))
    );
}

#[test]
fn p2_checkpoint_manifest_must_match_its_checkpoint() {
    let v = fresh();
    write(&v, 0, &image(1, 1), &meta(1, 10), &layout).unwrap();
    let m = read_manifest(&v, 0).unwrap().unwrap();
    let wrong_pos = Manifest {
        first_wal_seq: 11,
        ..m
    };
    assert!(load(&v, &wrong_pos, &layout).is_err());
    let missing = Manifest {
        checkpoint_id: 5,
        ..m
    };
    assert!(load(&v, &missing, &layout).is_err());
}

#[test]
fn p2_checkpoint_partition_names_are_hex() {
    let cid = CollectionId::from_bytes([0xab; 16]);
    assert_eq!(partition_name(&cid), format!("{}.svp", "ab".repeat(16)));
}
