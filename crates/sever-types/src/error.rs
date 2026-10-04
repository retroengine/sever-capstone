//! The typed errors of spec §17.
//!
//! Every row of the §17 table is a variant here, including the ones raised only by later parts, so
//! that a later part never has to edit this frozen enum (Build §0.3). No message carries a record
//! ID, a vector value, a key, `r_t` or passage text (§17); messages are fixed text.

use core::fmt;

/// Why a record ID was rejected (§3.2 rules 1–2). Carries no part of the ID (§17).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum InvalidRecordIdReason {
    /// §3.2 rule 1: zero bytes.
    Empty,
    /// §3.2 rule 1: more than 256 bytes.
    TooLong,
    /// §3.2 rule 1: the bytes are not valid UTF-8.
    NotUtf8,
    /// §3.2 rule 2: a bare decimal integer, `^[+-]?[0-9]+$`.
    CounterShaped,
}

impl fmt::Display for InvalidRecordIdReason {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Empty => "empty",
            Self::TooLong => "longer than 256 bytes",
            Self::NotUtf8 => "not valid UTF-8",
            Self::CounterShaped => "a bare decimal integer",
        })
    }
}

/// Every error SEVER-DB raises (§17: "Every error is typed").
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum Error {
    /// §4.1 fails: the vector does not have `d` components (see gap G-8).
    #[error("vector has the wrong dimension")]
    WrongDimension,
    /// §4.1 step 1: a component is NaN or infinite.
    #[error("vector has a non-finite component")]
    NonFinite,
    /// §4.1 step 3: `|norm − 1| > 8 · 2^−23`.
    #[error("vector is not normalised")]
    NotNormalised,
    /// §3.2 rules 1–2 fail.
    #[error("invalid record id: {0}")]
    InvalidRecordId(InvalidRecordIdReason),
    /// §3.2 rule 3 fails. `same_commitment` says whether the live record has the supplied `C_t`
    /// (a retried insert, which the SDK treats as success, §15.1).
    #[error("duplicate record (same commitment: {same_commitment})")]
    DuplicateRecord {
        /// Whether the live record's commitment equals the supplied one.
        same_commitment: bool,
    },
    /// §9.3: supplied `C_t` ≠ recomputed `C_t` at insert.
    #[error("commitment does not match the vector")]
    CommitmentMismatch,
    /// §9.8: the insert signature fails.
    #[error("bad user signature")]
    BadUserSignature,
    /// §5.6: the insert would make `n > 1,000,000`.
    #[error("group capacity exceeded")]
    GroupCapacityExceeded,
    /// No such collection.
    #[error("unknown collection")]
    UnknownCollection,
    /// §9.6: an attempt to supply randomness to proof generation.
    #[error("seeded nonces are forbidden")]
    SeededNonceForbidden,
    /// A §12.8 or §12.9 check fails. `check` names the rule, never a value.
    #[error("platform unsafe: {check}")]
    PlatformUnsafe {
        /// Which check failed, as fixed text (for example `"swap not encrypted"`).
        check: &'static str,
    },
    /// An invariant (§21) or the delete-time `C_t` check (§15.3 step 2) fails; the engine stops
    /// serving. `invariant` names the rule, never a value.
    #[error("integrity violation: {invariant}")]
    IntegrityViolation {
        /// Which rule failed, as fixed text (for example `"INV-6"`).
        invariant: &'static str,
    },
    /// `fsync` failed; the process aborts (§12.7).
    #[error("durability failure")]
    DurabilityFailure,
}

#[cfg(test)]
mod tests {
    use super::*;

    /// One value of every variant, in §17 table order.
    fn every_error() -> Vec<Error> {
        vec![
            Error::WrongDimension,
            Error::NonFinite,
            Error::NotNormalised,
            Error::InvalidRecordId(InvalidRecordIdReason::Empty),
            Error::InvalidRecordId(InvalidRecordIdReason::TooLong),
            Error::InvalidRecordId(InvalidRecordIdReason::NotUtf8),
            Error::InvalidRecordId(InvalidRecordIdReason::CounterShaped),
            Error::DuplicateRecord {
                same_commitment: true,
            },
            Error::DuplicateRecord {
                same_commitment: false,
            },
            Error::CommitmentMismatch,
            Error::BadUserSignature,
            Error::GroupCapacityExceeded,
            Error::UnknownCollection,
            Error::SeededNonceForbidden,
            Error::PlatformUnsafe {
                check: "swap not encrypted",
            },
            Error::IntegrityViolation { invariant: "INV-6" },
            Error::DurabilityFailure,
        ]
    }

    // spec: SR-17-1 — each §17 row exists as its own variant (13 rows; three carry details).
    #[test]
    fn p1_types_every_spec_17_row_is_a_variant() {
        let names: Vec<String> = every_error()
            .iter()
            .map(|e| {
                format!("{e:?}")
                    .split([' ', '(', '{'])
                    .next()
                    .unwrap_or("")
                    .to_owned()
            })
            .collect();
        for row in [
            "WrongDimension",
            "NonFinite",
            "NotNormalised",
            "InvalidRecordId",
            "DuplicateRecord",
            "CommitmentMismatch",
            "BadUserSignature",
            "GroupCapacityExceeded",
            "UnknownCollection",
            "SeededNonceForbidden",
            "PlatformUnsafe",
            "IntegrityViolation",
            "DurabilityFailure",
        ] {
            assert!(
                names.iter().any(|n| n == row),
                "§17 row {row} has no variant"
            );
        }
    }

    // spec: SR-17-2 — no variant stores caller data, so every message is fixed text. The check
    // that a rejected ID never reaches the message is in `id.rs`.
    #[test]
    fn p1_types_error_messages_are_fixed_text() {
        for e in every_error() {
            let msg = e.to_string();
            assert!(!msg.is_empty());
            assert!(msg.is_ascii(), "message should be plain fixed text: {msg}");
        }
    }
}
