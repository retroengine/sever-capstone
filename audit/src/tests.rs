//! Tests of the auditor. Expected values: the certificate model's scripted log and faults
//! (`golden/p3_audit.json`, written by `sever_refmodel_certs.audit` with the kinds that model
//! reports; B-shared), and the register of faults (`spec/registers_p3.yaml`).

use std::collections::BTreeSet;

use serde_json::Value;
use sever_spec::spec;

use crate::anchors::Anchors;
use crate::audit::{Export, audit};
use crate::gens::Generators;
use crate::hex;

const AUDIT: &str = include_str!("../../golden/p3_audit.json");
const REGISTER: &str = include_str!("../../spec/registers_p3.yaml");

fn golden() -> Value {
    serde_json::from_str(AUDIT).unwrap()
}

fn anchors(v: &Value) -> Anchors {
    Anchors::from_json(&v["anchors"].to_string()).unwrap()
}

fn export(v: &Value) -> Export {
    Export::from_json(&v.to_string()).unwrap()
}

fn certs(v: &Value) -> Vec<Vec<u8>> {
    v.as_array()
        .unwrap()
        .iter()
        .map(|h| hex::decode(h.as_str().unwrap()).unwrap())
        .collect()
}

#[test]
// oracle: B-shared golden p3_audit.json: sever_refmodel_certs.audit's honest scripted log (groups, a flush, chained and holding deletions, checkpoints) has no findings
#[spec("SR-11.3-10")]
fn p3_audit_an_honest_log_has_no_findings() {
    let v = golden();
    let a = anchors(&v);
    let gens = Generators::derive(a.d).unwrap();
    let e = export(&v["honest"]);
    assert!(e.leaves.len() > 10);
    let found = audit(&e, &a, &gens, &certs(&v["certificates"]));
    assert_eq!(found, vec![]);
}

#[test]
// oracle: B-shared golden p3_audit.json (each fault's export and the kinds the model reports); A the register's faults AF-1 … AF-5 (spec/registers_p3.yaml; §11.3 "what it does not prove")
#[spec("SR-11.3-10", "SR-10.2-2", "SR-10.1-2", "SR-21-15")]
fn p3_audit_reports_every_injected_fault() {
    let v = golden();
    let a = anchors(&v);
    let gens = Generators::derive(a.d).unwrap();
    let register: BTreeSet<String> = REGISTER
        .lines()
        .filter_map(|l| l.split("{id: ").nth(1)?.split(',').next())
        .filter(|id| id.starts_with("AF-"))
        .map(str::to_owned)
        .collect();
    let mut seen = BTreeSet::new();
    for f in v["faults"].as_array().unwrap() {
        let id = f["id"].as_str().unwrap();
        let found = audit(&export(&f["export"]), &a, &gens, &certs(&f["held"]));
        let kinds: BTreeSet<&str> = found.iter().map(|x| x.kind).collect();
        let want: BTreeSet<&str> = f["model_kinds"]
            .as_array()
            .unwrap()
            .iter()
            .map(|k| k.as_str().unwrap())
            .collect();
        assert!(kinds.contains(id), "{id} not reported: {found:?}");
        assert_eq!(kinds, want, "{id}: {found:?}");
        seen.insert(id.to_owned());
    }
    assert_eq!(seen, register, "every registered fault is injected");
}
