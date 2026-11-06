# B06 · Just enough Rust and Python tooling to read this repository

## In simple words

The engine is written in Rust, a language that catches memory and concurrency mistakes at compile
time. The tooling is Python. They meet through PyO3. You only need the handful of ideas below to read
the code excerpts in this report.

> **Prerequisites.** Any programming language with functions and structs/classes. Free resources:
> *The Rust Programming Language* book (Klabnik, Nichols, Krycho) https://doc.rust-lang.org/book/ and the
> PyO3 user guide https://pyo3.rs/ (both opened 2026-11-01).

## The problem this solves

Code excerpts like `pub fn quantise(x: &[f32], d: usize) -> Result<QVec, Error>` are unreadable without
knowing what `&`, `Result` and `?` mean.

## Rust, one concept at a time

| Concept | Meaning | Tiny example |
|---|---|---|
| **crate** | a Rust package (library or binary) | `crates/sever-quant` |
| **workspace** | several crates built together, one `Cargo.lock` | root `Cargo.toml` `[workspace]` |
| **module** | a file/namespace inside a crate | `mod kernel;` |
| `struct` / `enum` | record type / one-of-several type | `pub struct QVec(Box<[i32]>)`; `enum Error { WrongDimension, … }` |
| `impl` | adds methods to a type | `impl QVec { pub fn dim(&self) -> usize { … } }` |
| **trait** | an interface; types `impl` it | `trait Vfs { fn fsync_dir(&self, dir: &str) -> Result<(), VfsError>; }` |
| generics | code over any type meeting a trait | `Index<E: GroupExtension, S: IdScrambler>` |
| `Result<T, E>` | either `Ok(value)` or `Err(error)` | `Result<QVec, Error>` |
| `?` | "if this is an `Err`, return it now" | `check_normalised(x, d)?;` |
| `Option<T>` | `Some(value)` or `None` | `fn blob(&self, id) -> Option<Vec<u8>>` |
| ownership / borrowing | each value has one owner; `&x` borrows read-only, `&mut x` borrows to change | `fn score(q: &[f32], x: &[f32])` |
| `&[T]` | a borrowed slice (view of an array) | `&[f32]` |
| `pub` | visible outside the module | `pub fn` |
| `unsafe` | the programmer, not the compiler, guarantees memory safety | only in the AVX2 kernel |
| attributes | metadata on items | `#[test]`, `#[spec("SR-17-2")]`, `#[derive(Debug)]` |
| features | optional build switches | `#[cfg(feature = "sabotage-SB-9")]`; `cfg!(feature = "…")` is a constant `true/false` usable in `if` |
| `macro!` | code that writes code | `proptest! { … }`, `assert_eq!(a, b)` |

**Commands:** `cargo build`, `cargo test --workspace`, `cargo fmt --check`, `cargo clippy -- -D warnings`
(lints as errors), `cargo run -p sever-p1 --bin sever-demo -- idea --data synthetic`.

## Python tooling

| Tool | What it is |
|---|---|
| **uv** | creates and syncs the virtual environment from `pyproject.toml` + `uv.lock` (`uv sync --locked`, `uv run …`) |
| **pytest** | test runner; markers like `@pytest.mark.spec("SR-…")` label tests |
| **decorator** | `@something` above a function wraps or labels it (`@pytest.mark.mustfail`) |
| **Hypothesis** | property-based testing library ("generates random inputs within ranges you define") — hypothesis.readthedocs.io, opened 2026-11-01 |
| **PyO3** | Rust library that builds native Python modules in Rust (`#[pyclass]`, `#[pymethods]`, `#[pyfunction]`) |
| **maturin** | builds and installs a PyO3 crate into the venv (`maturin develop -m crates/sever-py/Cargo.toml`) |
| **GIL** | Python's global interpreter lock; PyO3 code can release it while Rust works (`py.detach`) — relevant to erratum E-1 |

## Everyday analogy

*Analogy:* Rust's borrow checker is a librarian who will not let two people write in the same book at
once, or anyone read a book that was thrown away. *Where it stops:* `unsafe` blocks tell the librarian
"trust me" — which is why SEVER-DB allows them in only one file.

## Key points to remember

- `Result` + `?` is how Rust code propagates typed errors without crashing.
- Traits are the extension points (EP-1 … EP-11).
- Cargo features build the sabotage variants.
- PyO3 + maturin turn the Rust engine into the `sever_db` Python package.

## Check your understanding

1. *What does `?` do?* — Returns the error early if the value is `Err`.
2. *What is `&mut self`?* — A method that borrows its object with permission to change it.
3. *How is a sabotage build made?* — `cargo test --features sabotage-SB-N`.
