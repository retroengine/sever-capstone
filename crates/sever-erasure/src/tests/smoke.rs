use super::harness::*;

#[test]
fn p4_erasure_smoke_insert_delete_reopen() {
    let disks = Disks::new();
    let vs = vectors();
    let (db, _) = disks.open(1 << 30).unwrap();
    let cid = db.create_collection(ARTEFACT, OPTS).unwrap();
    for (i, v) in vs.iter().take(40).enumerate() {
        insert(&db, cid, &format!("r{i}"), v).unwrap();
    }
    for i in [3, 7, 11] {
        db.delete(cid, &format!("r{i}")).unwrap();
    }
    let before = db.canonical_state(cid).unwrap();
    let passage = db.passage(cid, "r5").unwrap();
    db.close().unwrap();
    let (db, _) = disks.open(1 << 30).unwrap();
    assert_eq!(db.canonical_state(cid).unwrap(), before);
    assert_eq!(db.passage(cid, "r5").unwrap(), passage);
    assert_eq!(passage, Some(b"passage of r5".to_vec()));
}
