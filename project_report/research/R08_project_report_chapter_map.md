# R08 · Mapping these docs onto a B.Tech/M.Tech project report

| Chapter | Feed from | Figures / tables to include |
|---|---|---|
| Abstract | [R06](R06_paper_draft.md) abstract | — |
| 1 Introduction | [01](../01_overview_and_core_idea.md), [R01](R01_motivation_and_problem.md) | four-part flow diagram (01) |
| 2 Literature Survey | [R02](R02_related_work.md), [B04](../background/B04_cryptography_basics.md), [B07](../background/B07_privacy_and_the_right_to_erasure.md) | comparison table (R02 §8) |
| 3 Problem Statement and Objectives | [R01](R01_motivation_and_problem.md) §5, CLAUDE.md §6.1 claims | objectives = the four claims |
| 4 System Requirements | [03](../03_tech_stack_and_toolchain.md), [R05](R05_experimental_methodology.md) (hardware), [07f](../07f_platform_safety_and_forensics.md) (platform) | toolchain/version table; hardware table |
| 5 System Design | [04](../04_architecture.md), [05](../05_part1_the_idea.md), [06](../06_part2_the_database.md), [07a](../07a_crypto_overview.md)–[07e](../07e_encryption_and_crypto_shredding.md) | crate graph; routing flowchart; txn sequence; key hierarchy; certificate format; verifier flow |
| 6 Implementation | [02](../02_repository_map.md), [08](../08_interfaces_sdk_cli_studio.md), [09](../09_coding_style_and_engineering_rules.md) | crate table; CLI table; code excerpts |
| 7 Testing | [10](../10_testing_methodology.md), [07g](../07g_crypto_attack_testing.md), [12](../12_bugs_found_and_fixed.md) | L1–L14 table; sabotage tables; attack register |
| 8 Results and Discussion | [11](../11_results.md), [14](../14_status_gaps_and_pending.md) | per-part result tables; EX-7 cost table; EX-6 recall per rung |
| 9 Conclusion | [R06](R06_paper_draft.md) §VIII | — |
| 10 Future Scope | [14](../14_status_gaps_and_pending.md) §3–§5 | — |
| References | [R07](R07_references.bib) | — |
| Appendices | [13](../13_timeline.md), [16](../16_glossary.md), [17](../17_verification_log.md) | timeline Gantt; glossary |
