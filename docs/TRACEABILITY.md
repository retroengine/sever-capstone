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
| SR-4.1-0 | dimension check (step 0) | `p1_quant_wrong_dimension_is_rejected_first`, `p1_quant_quantise_runs_the_check` | L1 | | 1 |
| SR-4.1-1 | every component finite | `p1_quant_non_finite_is_rejected` | L1 | | 1 |
| SR-4.1-2 | f64 sequential norm | `p1_quant_norm_is_summed_in_f64_sequentially` | L1 | | 1 |
| SR-4.1-3 | 8-ULP tolerance | `p1_quant_tolerance_boundaries`, `p1_quant_prop_unit_vectors_pass` | L1, L2 | | 1 |
| SR-4.2-1 | Q24, ties to even | `p1_quant_golden_half_steps_round_to_even` (golden 5), `p1_quant_ties_to_even_by_hand`, `p1_quant_prop_round_trip_within_half_step` | L1, L2, L3 | | 1 |
| SR-4.2-2 | |x̃| ≤ 2^24 + 16 | `p1_quant_bound_is_reached_at_tolerance_edge`, `p1_quant_from_stored_checks_dimension_and_bound` | L1 | | 1 |
| SR-4.3-1 | dequantise f64 exact | `p1_quant_dequantise`, `p1_quant_prop_round_trip_within_half_step` | L1, L2 | | 1 |
| SR-4.3-2 | dequantise f32, ties to even above 2^24 | `p1_quant_dequantise` | L1 | | 1 |
| SR-6.2-1 … SR-6.2-6 | builder steps 1–6 | `test_p1_partition_small_build_is_consistent`, `test_p1_partition_build_refuses_unnormalised_reference_rows`, `test_p1_partition_build_is_deterministic` | L1 |  | 1 |
| SR-6.2-4 | one pooled LW fit | `test_p1_partition_sb10_per_group_averaging_is_refused` | L12 | SB-10 | 1 |
| SR-6.2-7 | independent LW oracle | `test_p1_partition_oracle_agrees_with_sklearn`, `test_p1_partition_real_seed42_rebuild_is_byte_identical` (slow) | L1, L8 | SB-10 | 1 |
| SR-6.3-1 | artefact layout | `test_p1_partition_artefact_layout_by_offset`, `p1_partition_parses_the_python_builders_file` | L3, L8 |  | 1 |
| SR-6.3-2 | hash, d, finite P checked | `test_p1_partition_artefact_decoder_rejects_bad_files`, `p1_partition_every_bit_flip_is_detected`, `p1_partition_rejects_bad_fields_even_with_valid_hash` | L1, L2 |  | 1 |
| SR-7.2-1 | pinned Mahalanobis order | `test_p1_partition_mahalanobis_is_the_pinned_sequential_order` | L1 |  | 1 |
| SR-7.2-2 | q < 0 → IntegrityViolation | `test_p1_partition_negative_q_is_an_integrity_violation` | L1 |  | 1 |
| SR-OV-10.6-1 | sub-seed derivation | `test_p1_seeds_sub_seed_reproduces_the_p0_corpus_seed` | L1 |  | 1 |
