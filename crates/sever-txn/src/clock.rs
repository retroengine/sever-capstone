//! EP-9 `Clock` (Build §3.3): time for log checkpoints and key epochs (Parts 3 and 4). The index
//! never reads a clock (§7: routing is a pure function of `(x̃, state)`).

use std::sync::atomic::{AtomicU64, Ordering};

/// EP-9: milliseconds since the Unix epoch, never decreasing.
pub trait Clock: Send + Sync {
    /// The current time.
    fn now_ms(&self) -> u64;
}

/// The operating system's clock, made non-decreasing (a wall clock can step back).
#[derive(Debug, Default)]
pub struct SystemClock {
    last: AtomicU64,
}

impl Clock for SystemClock {
    fn now_ms(&self) -> u64 {
        let t = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| u64::try_from(d.as_millis()).unwrap_or(u64::MAX));
        // fetch_max returns the previous maximum; the result is max(previous, t).
        self.last.fetch_max(t, Ordering::SeqCst).max(t)
    }
}

/// A simulated clock for deterministic tests: starts at a fixed time and moves only when told.
#[derive(Debug, Default)]
pub struct SimClock {
    now: AtomicU64,
}

impl SimClock {
    /// A clock at `start_ms`.
    pub fn new(start_ms: u64) -> Self {
        Self {
            now: AtomicU64::new(start_ms),
        }
    }
    /// Moves the clock forward by `ms`.
    pub fn advance(&self, ms: u64) {
        self.now.fetch_add(ms, Ordering::SeqCst);
    }
}

impl Clock for SimClock {
    fn now_ms(&self) -> u64 {
        self.now.load(Ordering::SeqCst)
    }
}
