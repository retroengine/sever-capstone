//! Big-endian, fixed-width encoding (spec §0.2) with a strict reader: every parse names the check
//! that failed (fixed text, never a value, §17) and rejects trailing bytes.

use sever_types::{CollectionId, Error, GroupId, ScrambledId};

/// The error every parser returns: `IntegrityViolation` naming the failed check.
pub fn bad(check: &'static str) -> Error {
    Error::IntegrityViolation { invariant: check }
}

/// CRC-32C (Castagnoli) of `bytes` (spec §12.7: every record on disk has one).
pub fn crc(bytes: &[u8]) -> u32 {
    crc32c::crc32c(bytes)
}

/// Appends fixed-width big-endian fields to a buffer.
#[derive(Default, Debug, Clone)]
pub struct Writer(pub Vec<u8>);

impl Writer {
    /// An empty buffer.
    pub fn new() -> Self {
        Self(Vec::new())
    }
    /// Raw bytes.
    pub fn bytes(&mut self, b: &[u8]) -> &mut Self {
        self.0.extend_from_slice(b);
        self
    }
    /// `u8`.
    pub fn u8(&mut self, v: u8) -> &mut Self {
        self.0.push(v);
        self
    }
    /// `u16be`.
    pub fn u16(&mut self, v: u16) -> &mut Self {
        self.bytes(&v.to_be_bytes())
    }
    /// `u32be`.
    pub fn u32(&mut self, v: u32) -> &mut Self {
        self.bytes(&v.to_be_bytes())
    }
    /// `u64be`.
    pub fn u64(&mut self, v: u64) -> &mut Self {
        self.bytes(&v.to_be_bytes())
    }
    /// `i32be`.
    pub fn i32(&mut self, v: i32) -> &mut Self {
        self.bytes(&v.to_be_bytes())
    }
    /// `i64be`.
    pub fn i64(&mut self, v: i64) -> &mut Self {
        self.bytes(&v.to_be_bytes())
    }
    /// `f64be` (IEEE 754 bits, big-endian, as in the artefact of §6.3).
    pub fn f64(&mut self, v: f64) -> &mut Self {
        self.bytes(&v.to_bits().to_be_bytes())
    }
    /// A group ID, zero-padded to 32 bytes (§14.3).
    pub fn group_id(&mut self, g: &GroupId) -> &mut Self {
        let (padded, _) = g.to_padded_bytes();
        self.bytes(&padded)
    }
    /// A collection ID (16 bytes).
    pub fn collection(&mut self, c: &CollectionId) -> &mut Self {
        self.bytes(c.as_bytes())
    }
    /// A scrambled ID (64 bytes).
    pub fn scrambled(&mut self, s: &ScrambledId) -> &mut Self {
        self.bytes(s.as_bytes())
    }
    /// `u32be len ‖ bytes`. Lengths above `u32::MAX` cannot occur (every buffer is below 4 GiB).
    pub fn var(&mut self, b: &[u8]) -> &mut Self {
        self.u32(u32::try_from(b.len()).unwrap_or(u32::MAX));
        self.bytes(b)
    }
    /// The buffer.
    pub fn finish(self) -> Vec<u8> {
        self.0
    }
}

/// Reads fixed-width big-endian fields; every failure is `IntegrityViolation { check }`.
#[derive(Debug, Clone)]
pub struct Reader<'a> {
    rest: &'a [u8],
    check: &'static str,
}

impl<'a> Reader<'a> {
    /// Reads `bytes`; `check` names the structure in every error.
    pub fn new(bytes: &'a [u8], check: &'static str) -> Self {
        Self { rest: bytes, check }
    }
    /// Bytes not read yet.
    pub fn remaining(&self) -> usize {
        self.rest.len()
    }
    /// The next `n` bytes.
    pub fn take(&mut self, n: usize) -> Result<&'a [u8], Error> {
        let (head, tail) = self.rest.split_at_checked(n).ok_or(bad(self.check))?;
        self.rest = tail;
        Ok(head)
    }
    /// The next `N` bytes as an array.
    pub fn array<const N: usize>(&mut self) -> Result<[u8; N], Error> {
        let mut out = [0u8; N];
        out.copy_from_slice(self.take(N)?);
        Ok(out)
    }
    /// `u8`.
    pub fn u8(&mut self) -> Result<u8, Error> {
        Ok(u8::from_be_bytes(self.array()?))
    }
    /// `u16be`.
    pub fn u16(&mut self) -> Result<u16, Error> {
        Ok(u16::from_be_bytes(self.array()?))
    }
    /// `u32be`.
    pub fn u32(&mut self) -> Result<u32, Error> {
        Ok(u32::from_be_bytes(self.array()?))
    }
    /// `u64be`.
    pub fn u64(&mut self) -> Result<u64, Error> {
        Ok(u64::from_be_bytes(self.array()?))
    }
    /// `i32be`.
    pub fn i32(&mut self) -> Result<i32, Error> {
        Ok(i32::from_be_bytes(self.array()?))
    }
    /// `i64be`.
    pub fn i64(&mut self) -> Result<i64, Error> {
        Ok(i64::from_be_bytes(self.array()?))
    }
    /// `f64be`.
    pub fn f64(&mut self) -> Result<f64, Error> {
        Ok(f64::from_bits(self.u64()?))
    }
    /// A zero-padded group ID (§14.3), parsed strictly: the text form, then only zero bytes, and
    /// re-encoding gives the same 32 bytes.
    pub fn group_id(&mut self) -> Result<GroupId, Error> {
        let raw: [u8; 32] = self.array()?;
        let len = raw.iter().position(|&b| b == 0).unwrap_or(raw.len());
        let text = raw
            .get(..len)
            .and_then(|t| core::str::from_utf8(t).ok())
            .ok_or(bad(self.check))?;
        let g = GroupId::parse(text).ok_or(bad(self.check))?;
        if g.to_padded_bytes().0 == raw {
            Ok(g)
        } else {
            Err(bad(self.check))
        }
    }
    /// A collection ID.
    pub fn collection(&mut self) -> Result<CollectionId, Error> {
        Ok(CollectionId::from_bytes(self.array()?))
    }
    /// A scrambled ID.
    pub fn scrambled(&mut self) -> Result<ScrambledId, Error> {
        Ok(ScrambledId::from_bytes(self.array()?))
    }
    /// `u32be len ‖ bytes`.
    pub fn var(&mut self) -> Result<&'a [u8], Error> {
        let n = usize::try_from(self.u32()?).map_err(|_| bad(self.check))?;
        self.take(n)
    }
    /// A count that must be at most `max` (so a corrupt count cannot make a parser allocate).
    pub fn count(&mut self, max: usize) -> Result<usize, Error> {
        let n = usize::try_from(self.u64()?).map_err(|_| bad(self.check))?;
        if n <= max {
            Ok(n)
        } else {
            Err(bad(self.check))
        }
    }
    /// Succeeds only when every byte was read (strict parsers reject trailing bytes).
    pub fn end(self) -> Result<(), Error> {
        if self.rest.is_empty() {
            Ok(())
        } else {
            Err(bad(self.check))
        }
    }
}
