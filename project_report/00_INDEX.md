# SEVER-DB project report — index

Evidence-based documentation of the SEVER-DB repository at commit `4a03951` (tag `v1.0.0` = `7942c1d`),
written 1–6 Nov 2026. Evidence tags: `[CODE]`, `[DATA]`, `[RUN]`, `[DOC]`, `[INFERRED]`, `[NOT FOUND]`,
`[CITATION NEEDED]`. Examples marked "Illustrative" are not from the repository.

## Reading paths

**(1) Beginner, from zero:** [B00](background/B00_START_HERE.md) → [B01](background/B01_vectors_embeddings_and_search.md)
→ [B03](background/B03_floating_point_vs_exact_integers.md) → [B02](background/B02_how_databases_store_and_delete.md)
→ [B07](background/B07_privacy_and_the_right_to_erasure.md) → [01](01_overview_and_core_idea.md)
→ [B06](background/B06_rust_and_python_for_this_project.md) → [05](05_part1_the_idea.md) → [06](06_part2_the_database.md)
→ [B04](background/B04_cryptography_basics.md) → [07a](07a_crypto_overview.md)–[07g](07g_crypto_attack_testing.md)
→ [B05](background/B05_software_testing_concepts.md) → [10](10_testing_methodology.md) → [11](11_results.md) → [14](14_status_gaps_and_pending.md).

**(2) Guide, fast overview (≈ 30 min):** [01](01_overview_and_core_idea.md) → [04](04_architecture.md)
→ [11](11_results.md) → [12](12_bugs_found_and_fixed.md) → [14](14_status_gaps_and_pending.md).

**(3) Paper writing:** [R01](research/R01_motivation_and_problem.md) → [R02](research/R02_related_work.md)
→ [R03](research/R03_contributions_and_novelty.md) → [R04](research/R04_threat_model_and_security_analysis.md)
→ [R05](research/R05_experimental_methodology.md) → [R06](research/R06_paper_draft.md) + [11](11_results.md)
→ [R07](research/R07_references.bib), [R09](research/R09_figures_and_tables_list.md).

## Project documents

| File | What it covers |
|---|---|
| [01_overview_and_core_idea.md](01_overview_and_core_idea.md) | The ghost problem, the core idea, the four parts and their verified status |
| [02_repository_map.md](02_repository_map.md) | Every folder, crate and Python package |
| [03_tech_stack_and_toolchain.md](03_tech_stack_and_toolchain.md) | Languages, locked versions, tools |
| [04_architecture.md](04_architecture.md) | Crate graph, layering, extension points, end-to-end flows |
| [05_part1_the_idea.md](05_part1_the_idea.md) | Partition, Q24, routing, exact sums, blob, search, ghost demo |
| [06_part2_the_database.md](06_part2_the_database.md) | VFS, formats, WAL, checkpoints, commit point, recovery, errata |
| [07a_crypto_overview.md](07a_crypto_overview.md) | Every cryptographic primitive; randomness and seeds |
| [07b_pedersen_commitments_and_proofs.md](07b_pedersen_commitments_and_proofs.md) | Commitments, the proof of knowledge, G-34 |
| [07c_transparency_log_and_signatures.md](07c_transparency_log_and_signatures.md) | RFC 9162 log, checkpoints, simulated witnesses, signatures |
| [07d_deletion_certificate_and_verification.md](07d_deletion_certificate_and_verification.md) | Certificate bytes, verifier steps, independence, auditor |
| [07e_encryption_and_crypto_shredding.md](07e_encryption_and_crypto_shredding.md) | AES-256-GCM-SIV key hierarchy, rotation, phases A/C, INV-14 |
| [07f_platform_safety_and_forensics.md](07f_platform_safety_and_forensics.md) | Startup refusals, overrides, forensic scanner, EX-2 |
| [07g_crypto_attack_testing.md](07g_crypto_attack_testing.md) | AT-1…AT-20, AF-1…AF-5, SB-16…SB-30 |
| [08_interfaces_sdk_cli_studio.md](08_interfaces_sdk_cli_studio.md) | CLIs, Python SDKs, errors, Studio, try-it-yourself |
| [09_coding_style_and_engineering_rules.md](09_coding_style_and_engineering_rules.md) | Lints, errors, no-I/O core, sabotage flags, tagging, freeze |
| [10_testing_methodology.md](10_testing_methodology.md) | L1–L14, counts, traceability, oracles, crash, fuzz, mutation, red proofs, fair testing, CI |
| [11_results.md](11_results.md) | Every result with ledger line; README vs ledger check |
| [12_bugs_found_and_fixed.md](12_bugs_found_and_fixed.md) | Bugs found by tests, with fix commits and regression tests |
| [13_timeline.md](13_timeline.md) | Dates, tags, milestones from git |
| [14_status_gaps_and_pending.md](14_status_gaps_and_pending.md) | Honest status, pending items, limits, mismatches |
| [15_prerequisites.md](15_prerequisites.md) | What to learn first, with verified free resources |
| [16_glossary.md](16_glossary.md) | Every term and ID scheme |
| [17_verification_log.md](17_verification_log.md) | What was read, run, checked, and what could not be verified |

## Background (`background/`)

| File | Topic |
|---|---|
| [B00_START_HERE.md](background/B00_START_HERE.md) | Learning path |
| [B01_vectors_embeddings_and_search.md](background/B01_vectors_embeddings_and_search.md) | Embeddings, distance, IVF, Recall@10 |
| [B02_how_databases_store_and_delete.md](background/B02_how_databases_store_and_delete.md) | fsync, WAL, checkpoints, soft delete |
| [B03_floating_point_vs_exact_integers.md](background/B03_floating_point_vs_exact_integers.md) | Float rounding, Q24, exact sums |
| [B04_cryptography_basics.md](background/B04_cryptography_basics.md) | Hashes to transparency logs |
| [B05_software_testing_concepts.md](background/B05_software_testing_concepts.md) | Testing techniques |
| [B06_rust_and_python_for_this_project.md](background/B06_rust_and_python_for_this_project.md) | Rust and Python tooling |
| [B07_privacy_and_the_right_to_erasure.md](background/B07_privacy_and_the_right_to_erasure.md) | GDPR, DPDP, embedding inversion |

## Research (`research/`)

| File | Topic |
|---|---|
| [R01](research/R01_motivation_and_problem.md) | Motivation and problem statement |
| [R02](research/R02_related_work.md) | Related work and comparison table |
| [R03](research/R03_contributions_and_novelty.md) | Contributions and strength of claims |
| [R04](research/R04_threat_model_and_security_analysis.md) | Threat model |
| [R05](research/R05_experimental_methodology.md) | Datasets, protocol, targets, hardware |
| [R06](research/R06_paper_draft.md) | IEEE-style paper draft |
| [R07](research/R07_references.bib) | BibTeX (verified only) |
| [R08](research/R08_project_report_chapter_map.md) | Report chapter map |
| [R09](research/R09_figures_and_tables_list.md) | Figures and tables |
| [R10](research/R10_viva_and_guide_questions.md) | 44 viva questions with answers |

Working notes (raw, evidence-tagged): [_notes/](_notes/).
