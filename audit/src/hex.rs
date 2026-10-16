//! Lowercase hexadecimal, for the bundled golden files and the anchors file.

/// Decodes hex text (either case) into bytes.
pub fn decode(s: &str) -> Option<Vec<u8>> {
    let s = s.trim().as_bytes();
    if s.len() % 2 != 0 {
        return None;
    }
    s.chunks(2)
        .map(|p| {
            let hi = char::from(*p.first()?).to_digit(16)?;
            let lo = char::from(*p.get(1)?).to_digit(16)?;
            u8::try_from(hi * 16 + lo).ok()
        })
        .collect()
}

/// Decodes hex text into exactly `N` bytes.
pub fn decode_n<const N: usize>(s: &str) -> Option<[u8; N]> {
    decode(s)?.try_into().ok()
}

/// Lowercase hex of `b`.
pub fn encode(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}
