//! The contract suites against Part 2's implementations, and against deliberately wrong ones
//! (Build §3.4: a wrong implementation must fail).

use std::sync::Arc;

use sever_format::RecordType;
use sever_index::NoExtension;
use sever_spec::spec;
use sever_types::Error;
use sever_vfs::Vfs;
use zeroize::Zeroizing;

use super::*;
use crate::clock::{SimClock, SystemClock};
use crate::participant::TxnDraft;
use crate::sealer::PlaintextSealer;

#[test]
#[spec("SR-14-1")]
fn p2_txn_ep6_plaintext_sealer_passes_contract() {
    assert_eq!(ep6_sealer_contract(&PlaintextSealer), Ok(()));
}

/// Deliberately wrong: claims no overhead but appends a byte.
struct Padding;
/// Deliberately wrong: claims to encrypt (sealer 1) but binds nothing.
struct Unbound;

macro_rules! plain_except {
    ($t:ty, $id:expr, $pad:expr) => {
        impl Sealer for $t {
            fn sealer_id(&self) -> u16 {
                $id
            }
            fn seal_overhead(&self) -> usize {
                0
            }
            fn envelope_len(&self) -> usize {
                0
            }
            fn seal_record(
                &self,
                o: &RecordOwner<'_>,
                p: &[u8],
            ) -> core::result::Result<(Vec<u8>, Vec<u8>), Error> {
                let (e, mut s) = PlaintextSealer.seal_record(o, p)?;
                s.extend_from_slice($pad);
                Ok((e, s))
            }
            fn open_record(
                &self,
                o: &RecordOwner<'_>,
                e: &[u8],
                s: &[u8],
            ) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
                PlaintextSealer.open_record(o, e, s)
            }
            fn rewrap_record(
                &self,
                a: &RecordOwner<'_>,
                b: &RecordOwner<'_>,
                e: &[u8],
            ) -> core::result::Result<Vec<u8>, Error> {
                PlaintextSealer.rewrap_record(a, b, e)
            }
            fn seal_passage(
                &self,
                o: &RecordOwner<'_>,
                e: &[u8],
                t: &[u8],
            ) -> core::result::Result<Vec<u8>, Error> {
                PlaintextSealer.seal_passage(o, e, t)
            }
            fn open_passage(
                &self,
                o: &RecordOwner<'_>,
                e: &[u8],
                s: &[u8],
            ) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
                PlaintextSealer.open_passage(o, e, s)
            }
            fn next_version(&self, o: &GroupOwner<'_>, p: Option<u64>, d: bool) -> u64 {
                PlaintextSealer.next_version(o, p, d)
            }
            fn seal_accumulator(
                &self,
                o: &GroupOwner<'_>,
                v: u64,
                p: &[u8],
            ) -> core::result::Result<Vec<u8>, Error> {
                PlaintextSealer.seal_accumulator(o, v, p)
            }
            fn open_accumulator(
                &self,
                o: &GroupOwner<'_>,
                v: u64,
                s: &[u8],
            ) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
                PlaintextSealer.open_accumulator(o, v, s)
            }
        }
    };
}
plain_except!(Padding, 0, &[0u8]);
plain_except!(Unbound, 1, &[]);

#[test]
fn p2_txn_ep6_contract_rejects_wrong_sealers() {
    assert_eq!(
        ep6_sealer_contract(&Padding),
        Err(ContractViolation::WrongSize("record"))
    );
    assert_eq!(
        ep6_sealer_contract(&Unbound),
        Err(ContractViolation::OwnerNotBound)
    );
}

#[test]
fn p2_txn_ep9_clocks_pass_contract() {
    assert_eq!(ep9_clock_contract(&SystemClock::default()), Ok(()));
    let c = SimClock::new(1_000);
    assert_eq!(ep9_clock_contract(&c), Ok(()));
    c.advance(5);
    assert_eq!(c.now_ms(), 1_005);
}

/// Deliberately wrong: goes back one millisecond on every read.
struct Backwards(std::sync::atomic::AtomicU64);
impl Clock for Backwards {
    fn now_ms(&self) -> u64 {
        self.0.fetch_sub(1, std::sync::atomic::Ordering::SeqCst)
    }
}

#[test]
fn p2_txn_ep9_contract_rejects_a_clock_that_goes_back() {
    assert_eq!(
        ep9_clock_contract(&Backwards(1_000_000.into())),
        Err(ContractViolation::ClockWentBack)
    );
}

/// A correct participant: counts its transactions, durably, through its own EXTENSION records.
struct Counter {
    n: u64,
    pending: u64,
}
impl TxnParticipant<NoExtension> for Counter {
    fn id(&self) -> u16 {
        9
    }
    fn prepare(&mut self, d: &mut TxnDraft<'_, NoExtension>) -> core::result::Result<(), Error> {
        self.pending = self.n + 1;
        let mut payload = 9u16.to_be_bytes().to_vec();
        payload.extend_from_slice(&self.pending.to_be_bytes());
        d.participant_records.push((RecordType::Extension, payload));
        Ok(())
    }
    fn abort(&mut self) {
        self.pending = self.n;
    }
    fn after_commit(&mut self) -> core::result::Result<(), Error> {
        self.n = self.pending;
        Ok(())
    }
    fn replay(&mut self, r: &sever_format::WalRecord) -> core::result::Result<(), Error> {
        let b: [u8; 8] = r
            .payload
            .get(2..10)
            .and_then(|b| b.try_into().ok())
            .ok_or(Error::IntegrityViolation { invariant: "test" })?;
        self.n = u64::from_be_bytes(b);
        Ok(())
    }
}
impl ProbedParticipant for Counter {
    fn digest(&self) -> Vec<u8> {
        self.n.to_be_bytes().to_vec()
    }
}

/// Deliberately wrong: counts in memory only, with no WAL record.
struct Forgetful(u64);
impl TxnParticipant<NoExtension> for Forgetful {
    fn id(&self) -> u16 {
        10
    }
    fn after_commit(&mut self) -> core::result::Result<(), Error> {
        self.0 += 1;
        Ok(())
    }
}
impl ProbedParticipant for Forgetful {
    fn digest(&self) -> Vec<u8> {
        self.0.to_be_bytes().to_vec()
    }
}

#[test]
fn p2_txn_ep7_a_durable_participant_passes_contract() {
    let make =
        |_: Arc<dyn Vfs>| -> Box<dyn ProbedParticipant> { Box::new(Counter { n: 0, pending: 0 }) };
    assert_eq!(ep7_participant_contract(&make), Ok(()));
}

#[test]
fn p2_txn_ep7_contract_rejects_a_participant_that_keeps_state_in_memory() {
    let make = |_: Arc<dyn Vfs>| -> Box<dyn ProbedParticipant> { Box::new(Forgetful(0)) };
    assert_eq!(
        ep7_participant_contract(&make),
        Err(ContractViolation::StateNotRecovered)
    );
}

// ----- EP-6: one deliberately wrong sealer per contract rule (Build §3.4) -----

/// Which single rule a [`Faulty`] sealer breaks; everything else is `PlaintextSealer`.
#[derive(Clone, Copy, Debug)]
enum Fault {
    SealRecordErr,
    OpenRecordErr,
    OpenRecordWrong,
    RewrapErr,
    RewrapLong,
    OpenAfterRewrapErr,
    OpenAfterRewrapWrong,
    SealPassageErr,
    PassageLong,
    OpenPassageErr,
    OpenPassageWrong,
    SealAccErr,
    AccLong,
    OpenAccErr,
    OpenAccWrong,
}

struct Faulty(Fault);

fn oops() -> Error {
    Error::IntegrityViolation { invariant: "test" }
}

fn flipped(mut v: Zeroizing<Vec<u8>>) -> Zeroizing<Vec<u8>> {
    v.push(0);
    v
}

impl Sealer for Faulty {
    fn sealer_id(&self) -> u16 {
        0
    }
    fn seal_overhead(&self) -> usize {
        0
    }
    fn envelope_len(&self) -> usize {
        0
    }
    fn seal_record(
        &self,
        o: &RecordOwner<'_>,
        p: &[u8],
    ) -> core::result::Result<(Vec<u8>, Vec<u8>), Error> {
        match self.0 {
            Fault::SealRecordErr => Err(oops()),
            _ => PlaintextSealer.seal_record(o, p),
        }
    }
    fn open_record(
        &self,
        o: &RecordOwner<'_>,
        e: &[u8],
        s: &[u8],
    ) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
        let moved = *o.group != sever_types::GroupId::Holding;
        let r = PlaintextSealer.open_record(o, e, s)?;
        match self.0 {
            Fault::OpenRecordErr => Err(oops()),
            Fault::OpenRecordWrong if !moved => Ok(flipped(r)),
            Fault::OpenAfterRewrapErr if moved => Err(oops()),
            Fault::OpenAfterRewrapWrong if moved => Ok(flipped(r)),
            _ => Ok(r),
        }
    }
    fn rewrap_record(
        &self,
        a: &RecordOwner<'_>,
        b: &RecordOwner<'_>,
        e: &[u8],
    ) -> core::result::Result<Vec<u8>, Error> {
        let mut r = PlaintextSealer.rewrap_record(a, b, e)?;
        match self.0 {
            Fault::RewrapErr => Err(oops()),
            Fault::RewrapLong => {
                r.push(0);
                Ok(r)
            }
            _ => Ok(r),
        }
    }
    fn seal_passage(
        &self,
        o: &RecordOwner<'_>,
        e: &[u8],
        t: &[u8],
    ) -> core::result::Result<Vec<u8>, Error> {
        let mut r = PlaintextSealer.seal_passage(o, e, t)?;
        match self.0 {
            Fault::SealPassageErr => Err(oops()),
            Fault::PassageLong => {
                r.push(0);
                Ok(r)
            }
            _ => Ok(r),
        }
    }
    fn open_passage(
        &self,
        o: &RecordOwner<'_>,
        e: &[u8],
        s: &[u8],
    ) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
        let r = PlaintextSealer.open_passage(o, e, s)?;
        match self.0 {
            Fault::OpenPassageErr => Err(oops()),
            Fault::OpenPassageWrong => Ok(flipped(r)),
            _ => Ok(r),
        }
    }
    fn next_version(&self, o: &GroupOwner<'_>, p: Option<u64>, d: bool) -> u64 {
        PlaintextSealer.next_version(o, p, d)
    }
    fn seal_accumulator(
        &self,
        o: &GroupOwner<'_>,
        v: u64,
        p: &[u8],
    ) -> core::result::Result<Vec<u8>, Error> {
        let mut r = PlaintextSealer.seal_accumulator(o, v, p)?;
        match self.0 {
            Fault::SealAccErr => Err(oops()),
            Fault::AccLong => {
                r.push(0);
                Ok(r)
            }
            _ => Ok(r),
        }
    }
    fn open_accumulator(
        &self,
        o: &GroupOwner<'_>,
        v: u64,
        s: &[u8],
    ) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
        let r = PlaintextSealer.open_accumulator(o, v, s)?;
        match self.0 {
            Fault::OpenAccErr => Err(oops()),
            Fault::OpenAccWrong => Ok(flipped(r)),
            _ => Ok(r),
        }
    }
}

#[test]
fn p2_txn_ep6_contract_rejects_each_wrong_sealer_for_its_rule() {
    use ContractViolation::{Failed, RoundTrip, WrongSize};
    for (f, want) in [
        (Fault::SealRecordErr, Failed("seal_record")),
        (Fault::OpenRecordErr, Failed("open_record")),
        (Fault::OpenRecordWrong, RoundTrip("record")),
        (Fault::RewrapErr, Failed("rewrap_record")),
        (Fault::RewrapLong, WrongSize("envelope")),
        (Fault::OpenAfterRewrapErr, Failed("open after rewrap")),
        (Fault::OpenAfterRewrapWrong, RoundTrip("rewrap")),
        (Fault::SealPassageErr, Failed("seal_passage")),
        (Fault::PassageLong, WrongSize("passage")),
        (Fault::OpenPassageErr, Failed("open_passage")),
        (Fault::OpenPassageWrong, RoundTrip("passage")),
        (Fault::SealAccErr, Failed("seal_accumulator")),
        (Fault::AccLong, WrongSize("accumulator")),
        (Fault::OpenAccErr, Failed("open_accumulator")),
        (Fault::OpenAccWrong, RoundTrip("accumulator")),
    ] {
        assert_eq!(ep6_sealer_contract(&Faulty(f)), Err(want), "{f:?}");
    }
}

/// A toy encrypting sealer (`sealer_id` 1): every value carries an 8-byte tag of its owner, so
/// opening under another owner fails. `rotate` and `bind_acc` switch off one rule each.
struct Tagged {
    rotate: bool,
    bind_acc: bool,
}

fn tag(parts: &[&[u8]]) -> [u8; 8] {
    let mut h = 0xcbf2_9ce4_8422_2325u64; // FNV-1a
    for p in parts {
        for &b in *p {
            h = (h ^ u64::from(b)).wrapping_mul(0x0100_0000_01b3);
        }
        h = (h ^ 0xff).wrapping_mul(0x0100_0000_01b3);
    }
    h.to_be_bytes()
}

fn owner_tag(o: &RecordOwner<'_>) -> [u8; 8] {
    tag(&[
        o.collection.as_bytes(),
        &o.group.to_padded_bytes().0,
        o.scrambled_id.as_bytes(),
    ])
}

fn untag(s: &[u8], want: [u8; 8]) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
    match s.split_last_chunk::<8>() {
        Some((body, t)) if *t == want => Ok(Zeroizing::new(body.to_vec())),
        _ => Err(oops()),
    }
}

impl Tagged {
    fn acc_tag(&self, o: &GroupOwner<'_>, v: u64) -> [u8; 8] {
        let (v, n) = if self.bind_acc { (v, o.n) } else { (0, 0) };
        tag(&[
            o.collection.as_bytes(),
            &o.group.to_padded_bytes().0,
            &v.to_be_bytes(),
            &n.to_be_bytes(),
        ])
    }
}

impl Sealer for Tagged {
    fn sealer_id(&self) -> u16 {
        1
    }
    fn seal_overhead(&self) -> usize {
        8
    }
    fn envelope_len(&self) -> usize {
        8
    }
    fn seal_record(
        &self,
        o: &RecordOwner<'_>,
        p: &[u8],
    ) -> core::result::Result<(Vec<u8>, Vec<u8>), Error> {
        let data = tag(&[o.collection.as_bytes(), o.scrambled_id.as_bytes(), &[1]]);
        Ok((owner_tag(o).to_vec(), [p, &data].concat()))
    }
    fn open_record(
        &self,
        o: &RecordOwner<'_>,
        e: &[u8],
        s: &[u8],
    ) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
        if e != owner_tag(o) {
            return Err(oops());
        }
        untag(
            s,
            tag(&[o.collection.as_bytes(), o.scrambled_id.as_bytes(), &[1]]),
        )
    }
    fn rewrap_record(
        &self,
        a: &RecordOwner<'_>,
        b: &RecordOwner<'_>,
        e: &[u8],
    ) -> core::result::Result<Vec<u8>, Error> {
        if e != owner_tag(a) {
            return Err(oops());
        }
        Ok(owner_tag(b).to_vec())
    }
    fn seal_passage(
        &self,
        o: &RecordOwner<'_>,
        e: &[u8],
        t: &[u8],
    ) -> core::result::Result<Vec<u8>, Error> {
        if e != owner_tag(o) {
            return Err(oops());
        }
        Ok([
            t,
            &tag(&[o.collection.as_bytes(), o.scrambled_id.as_bytes(), &[2]]),
        ]
        .concat())
    }
    fn open_passage(
        &self,
        o: &RecordOwner<'_>,
        e: &[u8],
        s: &[u8],
    ) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
        if e != owner_tag(o) {
            return Err(oops());
        }
        untag(
            s,
            tag(&[o.collection.as_bytes(), o.scrambled_id.as_bytes(), &[2]]),
        )
    }
    fn next_version(&self, _: &GroupOwner<'_>, p: Option<u64>, d: bool) -> u64 {
        match p {
            Some(v) if d && self.rotate => v + 1,
            Some(v) => v,
            None => 1,
        }
    }
    fn seal_accumulator(
        &self,
        o: &GroupOwner<'_>,
        v: u64,
        p: &[u8],
    ) -> core::result::Result<Vec<u8>, Error> {
        Ok([p, &self.acc_tag(o, v)].concat())
    }
    fn open_accumulator(
        &self,
        o: &GroupOwner<'_>,
        v: u64,
        s: &[u8],
    ) -> core::result::Result<Zeroizing<Vec<u8>>, Error> {
        untag(s, self.acc_tag(o, v))
    }
}

#[test]
fn p2_txn_ep6_contract_checks_rotation_and_accumulator_binding() {
    let good = Tagged {
        rotate: true,
        bind_acc: true,
    };
    assert_eq!(
        ep6_sealer_contract(&good),
        Ok(()),
        "a binding, rotating sealer passes"
    );
    assert_eq!(
        ep6_sealer_contract(&Tagged {
            rotate: false,
            bind_acc: true
        }),
        Err(ContractViolation::NoRotation)
    );
    assert_eq!(
        ep6_sealer_contract(&Tagged {
            rotate: true,
            bind_acc: false
        }),
        Err(ContractViolation::OwnerNotBound)
    );
}

// ----- EP-7: participants that break the protocol's other rules -----

/// Deliberately wrong: refuses every transaction in `prepare`.
struct Refuses;
impl TxnParticipant<NoExtension> for Refuses {
    fn id(&self) -> u16 {
        11
    }
    fn prepare(&mut self, _: &mut TxnDraft<'_, NoExtension>) -> core::result::Result<(), Error> {
        Err(oops())
    }
}
impl ProbedParticipant for Refuses {
    fn digest(&self) -> Vec<u8> {
        Vec::new()
    }
}

/// Deliberately wrong: durable like `Counter`, but its own invariant check always fails.
struct Inconsistent(Counter);
impl TxnParticipant<NoExtension> for Inconsistent {
    fn id(&self) -> u16 {
        self.0.id()
    }
    fn prepare(&mut self, d: &mut TxnDraft<'_, NoExtension>) -> core::result::Result<(), Error> {
        self.0.prepare(d)
    }
    fn abort(&mut self) {
        self.0.abort();
    }
    fn after_commit(&mut self) -> core::result::Result<(), Error> {
        self.0.after_commit()
    }
    fn replay(&mut self, r: &sever_format::WalRecord) -> core::result::Result<(), Error> {
        self.0.replay(r)
    }
    fn check_invariants(&self) -> core::result::Result<(), Error> {
        Err(oops())
    }
}
impl ProbedParticipant for Inconsistent {
    fn digest(&self) -> Vec<u8> {
        self.0.digest()
    }
}

#[test]
fn p2_txn_ep7_contract_rejects_a_participant_that_refuses_or_is_inconsistent() {
    let make = |_: Arc<dyn Vfs>| -> Box<dyn ProbedParticipant> { Box::new(Refuses) };
    assert_eq!(
        ep7_participant_contract(&make),
        Err(ContractViolation::Failed("transaction"))
    );
    let make = |_: Arc<dyn Vfs>| -> Box<dyn ProbedParticipant> {
        Box::new(Inconsistent(Counter { n: 0, pending: 0 }))
    };
    assert_eq!(
        ep7_participant_contract(&make),
        Err(ContractViolation::InvariantFailed)
    );
}
