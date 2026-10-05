//! `#[spec("SR-4.1-3", …)]` (Build §2.2): names the specification requirements a test checks.
//!
//! The attribute changes nothing about the item it marks. `spec-trace` reads it from the source to
//! build `docs/TRACE_PART_N.md`. The arguments are checked here, so a malformed ID does not compile:
//! each must be a string literal of the form `"SR-<section>-<n>"`.

use proc_macro::{TokenStream, TokenTree};

/// Marks a test with the requirement IDs it checks; returns the item unchanged.
#[proc_macro_attribute]
pub fn spec(args: TokenStream, item: TokenStream) -> TokenStream {
    let mut ids = 0usize;
    for tt in args {
        match tt {
            TokenTree::Punct(p) if p.as_char() == ',' => {}
            TokenTree::Literal(lit) => {
                let s = lit.to_string();
                let ok = s.len() > 5
                    && s.starts_with("\"SR-")
                    && s.ends_with('"')
                    && s.bytes().all(|b| b.is_ascii_graphic());
                if !ok {
                    return error(&format!("#[spec]: {s} is not \"SR-<section>-<n>\""));
                }
                ids += 1;
            }
            other => return error(&format!("#[spec]: unexpected `{other}`")),
        }
    }
    if ids == 0 {
        return error("#[spec]: name at least one requirement ID");
    }
    item
}

fn error(msg: &str) -> TokenStream {
    format!("compile_error!({msg:?});")
        .parse()
        .unwrap_or_default()
}
