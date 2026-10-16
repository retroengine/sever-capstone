# Soundness of the deletion proof (spec §9.5)

Written for: a reader who knows Schnorr proofs and wants to check the argument behind SEVER-DB's
certificate proof. Every claim below names the executable test that backs it (Build 3-4 P3-G9,
gate P3-T11). This is the author's own argument, not an independent review (overview L-21).

## 1. The statement

Public: generators `H, G_0 … G_{d−1}` (§9.2), the group's commitment after the deletion `C_S_post`,
and the deletion context `ctx` (152 bytes: `C_S_pre ‖ C_t ‖ scrambled_id ‖ u64be(database_lsn) ‖
collection_id`). The prover claims to know an opening `(r, s_0 … s_{d−1})` with

  `C_S_post = r·H + Σ_i s_i·G_i`.

This is a proof of knowledge of a representation (Okamoto; Camenisch–Stadler), the multi-secret form
of Schnorr's proof. The interactive Σ-protocol is:

1. Prover: nonces `(k_r, k_0 … k_{d−1})`, sends `A = k_r·H + Σ_i k_i·G_i`.
2. Verifier: a challenge `c ∈ Z_ℓ`.
3. Prover: `z_r = k_r + c·r`, `z_i = k_i + c·s_i` (mod ℓ).
4. Verifier accepts iff `z_r·H + Σ_i z_i·G_i = A + c·C_S_post`.

§9.5 makes it non-interactive with Fiat–Shamir: `c = from_bytes_mod_order_wide(SHA-512(DST_POSK ‖
C_S_post ‖ A ‖ ctx))`, binding the statement, the commitment `A` and the whole deletion context.

## 2. Completeness

An honest prover's response satisfies step 4 identically:
`z_r·H + Σ z_i·G_i = (k_r + c·r)·H + Σ (k_i + c·s_i)·G_i = A + c·(r·H + Σ s_i·G_i) = A + c·C_S_post`.
Nothing depends on the values, so it holds for every opening, including the empty group (`r = 0`,
`s = 0`, `C_S_post` the identity, §5.4).

*Test:* `crates/sever-crypto/src/tests.rs::p3_crypto_soundness_completeness_for_random_states`
(random openings, including the empty group, through the engine's hedged prover and verifier).

## 3. Special soundness (an extractor)

Given two accepting transcripts `(A, c, z)` and `(A, c', z')` with the same `A` and `c ≠ c'`:

  `z_r·H + Σ z_i·G_i = A + c·C_S_post` and `z'_r·H + Σ z'_i·G_i = A + c'·C_S_post`.

Subtracting, `(z_r − z'_r)·H + Σ (z_i − z'_i)·G_i = (c − c')·C_S_post`, so

  `r = (z_r − z'_r)/(c − c')`, `s_i = (z_i − z'_i)/(c − c')` (mod ℓ)

is an opening of `C_S_post`. Hence a prover that can answer two challenges for one `A` knows an
opening; with Fiat–Shamir in the random-oracle model, the forking lemma turns a forger into such a
pair. Two openings of one commitment would give a discrete-log relation among `H, G_0 …`, which no one
knows because the generators are hashed from a public string (§2.3, §9.2), so the extracted opening
is *the* opening: the operator knows the group's real `(r_agg, S)` after the deletion.

This is also why a reused nonce vector is fatal (§9.5 "Soundness note", §9.6): two proofs with one `A`
are exactly the extractor's input, and anyone holding both certificates learns the group's sum.

*Test:* `crates/sever-crypto/src/tests.rs::p3_crypto_soundness_extractor_recovers_the_opening` — two
proofs of one state with one nonce vector under two contexts (so two challenges); both verify; the
extractor above recovers `r_post` and every `scalar(S_post_i)` exactly.

## 4. Honest-verifier zero knowledge (a simulator)

Without any opening: pick `c` and `z_r, z_0 … z_{d−1}` uniformly in `Z_ℓ`, set
`A = z_r·H + Σ z_i·G_i − c·C_S_post`. Then `(A, c, z)` satisfies step 4. In a real transcript,
`(c, z)` are uniform (the `k` are uniform and independent of `c`) and `A` is the unique point that
makes step 4 hold; in the simulated one, the same. So the two distributions are identical, and a
transcript teaches nothing an observer could not compute alone. Under Fiat–Shamir the simulator
programs the random oracle at `(DST_POSK ‖ C_S_post ‖ A ‖ ctx)` to answer `c` (random-oracle model);
`A` is uniform, so the point was unqueried except with negligible probability.

What the certificate reveals beyond the proof is listed in spec §11.3: `C_S_pre`, `C_S_post`, `C_t`
(hiding Pedersen commitments, §9.3) and whether the group emptied (tag 11).

*Test:* `crates/sever-crypto/src/tests.rs::p3_crypto_soundness_simulator_transcripts_verify` —
simulated transcripts, made with no opening, pass the engine's own verification equation for random
challenges, and the simulated `A` is not the identity.

## 5. What the hedged nonces add (§9.6)

Soundness and zero knowledge assume uniform, never-reused nonces. §9.6 derives them from the secret
witness, the statement and context, and 32 bytes of OS entropy through a Merlin transcript. With a
working random source, two proofs never share a nonce vector, even of one statement; with a broken
one, two proofs share it only if witness, statement and context all repeat, and then the challenge
repeats too, so the extractor's input (one `A`, two challenges) never arises. The prover accepts only
`StrictProofRng`, so a seeded generator cannot reach it (SB-18; `nonce.rs` compile-fail doc tests).

*Tests:* SB-18 (`two proofs of the same statement have different A`), the compile-fail doc tests in
`crates/sever-crypto/src/nonce.rs`, and `SeededNonceForbidden` in the SDK
(`python/sever_db_p3/tests`).

## 6. Limits

- Random-oracle model for Fiat–Shamir; discrete-log hardness in ristretto255.
- No independent cryptographic review (overview L-21, R-1).
- A valid proof shows the operator knows an opening of `C_S_post`; it does not show the operator kept
  no copy of the deleted data (§11.3 "What no certificate can prove").
