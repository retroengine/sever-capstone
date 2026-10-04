# Traceability matrix

Every specification requirement (`SR-<section>-<n>`, Build §2.2) is named by at least one test
(Overview P1.G3). Add rows at step 7 of the work loop (CLAUDE.md §4). A requirement with no test is a
gap in the tests.

This file is kept by hand until the `spec-trace` tool exists. From then on, `spec-trace` generates
`docs/TRACE_PART_N.md` from `spec/requirements.yaml` and the test annotations, and fails CI if any
requirement of a finished part has no test.

| Requirement | Spec rule | Test | Level | Sabotage (SB-N) | Part |
|---|---|---|---|---|---|
| SR-0.2-3 | order is raw UTF-8 bytes | `p1_types_record_ids_sort_by_bytes`, `p1_types_prop_record_id_order_is_byte_order`, `p1_types_group_ids_sort_by_bytes` | L1, L2 | | 1 |
| SR-2.2-1 | v1 parameters (Part 1 rows) | `p1_types_v1_parameters_match_spec_table`, `p1_types_tolerance_is_exactly_eight_float32_ulps`, `p1_types_appendix_a_bounds_hold` | L3 | | 1 |
| SR-3.1-1 | collection_id is 16 bytes | `p1_types_fixed_width_ids` | L1 | | 1 |
| SR-3.2-1 | 1–256 bytes of UTF-8 | `p1_types_record_id_length_boundaries_in_bytes`, `p1_types_record_id_rejects_invalid_utf8`, `p1_types_prop_record_id_rule_is_exact` | L1, L2 | | 1 |
| SR-3.2-2 | not `^[+-]?[0-9]+$` | `p1_types_record_id_spec_examples`, `p1_types_record_id_counter_shape_is_a_full_ascii_match`, `p1_types_prop_counter_shaped_always_rejected`, `p1_types_prop_record_id_rule_is_exact` | L1, L2, L3 | | 1 |
| SR-3.2-3 | not already live | — (sever-index) |  | | 1 |
| SR-3.2-4 | re-insert after delete | — (sever-index) |  | | 1 |
| SR-5.1-1 | `frozen-NNNN` | `p1_types_group_id_text_forms`, `p1_types_group_id_parse_is_strict` | L1 | | 1 |
| SR-5.1-2 | `spawn-` + 16 lowercase hex | `p1_types_group_id_text_forms`, `p1_types_group_id_parse_is_strict` | L1 | | 1 |
| SR-5.1-3 | `holding` | `p1_types_group_id_text_forms`, `p1_types_group_id_parse_is_strict` | L1 | | 1 |
| SR-5.1-4 | group IDs ≤ 32 bytes | `p1_types_group_id_fits_32_bytes_zero_padded` | L1 | | 1 |
| SR-9.7-1 | scrambled_id is 64 bytes (HMAC in sever-index) | `p1_types_fixed_width_ids` | L1 | | 1 |
| SR-17-1 | every error typed | `p1_types_every_spec_17_row_is_a_variant` | L3 | | 1 |
| SR-17-2 | no ID, vector, key, r_t or text in errors | `p1_types_error_messages_are_fixed_text`, `p1_types_record_id_never_leaks_into_text`, `p1_types_secret_buf_debug_is_redacted` | L1 | | 1 |
