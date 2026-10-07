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
