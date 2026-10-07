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
| SR-3.2-3, SR-3.2-4 | not live; re-insert (model) | `test_p1_model_duplicate_live_id_and_reinsert_after_delete` | L1 |  | 1 |
| SR-5.3-1 | insert/delete arithmetic | `test_p1_model_delete_restores_survivors_state`, `test_p1_model_prop_survivors_check_after_any_sequence` | L1, L2, L6 | SB-1, SB-2 | 1 |
| SR-5.4-1 | physical excision | `test_p1_model_delete_restores_survivors_state` | L1 |  | 1 |
| SR-5.4-2 | idempotent delete | `test_p1_model_delete_is_idempotent` | L1 | SB-3 | 1 |
| SR-5.4-3 | empty group = initial state, stays | `test_p1_model_empty_group_returns_to_initial_state_and_stays` | L1 |  | 1 |
| SR-5.5-1 | SEVERC blob layout | `test_p1_model_blob_layout_and_parser_rejections`, `test_p1_model_golden_core_blob` (golden 8) | L1, L3 |  | 1 |
| SR-5.5-2 | blob parser rejections | `test_p1_model_blob_layout_and_parser_rejections` | L1 |  | 1 |
| SR-5.5-3 | five-field equivalence helper | `test_p1_model_equivalence_helper_catches_each_field_alone[*]` | L12 | SB-1 | 1 |
| SR-5.5-4 | insertion-order independence | `test_p1_model_insertion_order_independence` | L6 |  | 1 |
| SR-5.6-1 | room test 2kn < 3N | `test_p1_model_room_test_boundaries` | L1 |  | 1 |
| SR-7.3-1, SR-7.4-1, SR-7.4-2, SR-7.5-2 | holding, flush at target, centroid | `test_p1_model_holding_flushes_exactly_at_target` | L1 |  | 1 |
| SR-7.3-2 | spillover before holding | `test_p1_model_spillover_is_checked_before_holding` | L1 | SB-8 | 1 |
| SR-7.4-3 | holding deletable, not searchable | `test_p1_model_holding_record_is_deletable_and_never_searched` | L1 |  | 1 |
| SR-7.5-1 | spawn ID | `test_p1_model_golden_spawn_id` (golden 7) | L3 |  | 1 |
| SR-7.7-1, SR-7.7-2 | routing pure; creation order irrelevant | `test_p1_model_routing_is_pure_and_ignores_creation_order` | L6 | SB-7 | 1 |
| SR-7.7-3 | same input order → identical index | `test_p1_model_same_input_order_gives_identical_index` | L6 |  | 1 |
| SR-8.1-2 | probe count ⌈k/4⌉ | `test_p1_model_probe_count[*]` | L1 | SB-6 | 1 |
| SR-8.1-4 | deleted never returned | `test_p1_model_deleted_records_never_returned` | L1 | SB-5 | 1 |
| SR-8.2-1 | pinned kernel (model) | `test_p1_model_kernel_matches_explicit_lanes` | L1 | SB-9 | 1 |
| SR-5.3-1, SR-5.4-1 | exact deletion (Rust) | `p1_index_delete_restores_survivors_state`, `p1_index_prop_survivors_check_after_any_sequence` | L1, L2 | SB-1, SB-2 | 1 |
| SR-5.4-2 | idempotent delete (Rust) | `p1_index_delete_is_idempotent`, `p1_index_delete_user_across_groups_with_repeats` | L1 | SB-3 | 1 |
| SR-5.4-3, SR-5.2-1 | empty group (Rust) | `p1_index_empty_group_is_initial_state_and_stays` | L1 |  | 1 |
| SR-5.5-1, SR-5.5-2 | blob + parser (Rust) | `p1_index_blob_parser_rejections`, `p1_index_golden_core_blob` (golden 8) | L1, L3 |  | 1 |
| SR-5.5-3 | equivalence helper (Rust) | `p1_index_equivalence_helper_catches_each_field` | L12 | SB-1 | 1 |
| SR-5.5-4 | order independence (Rust) | `p1_index_prop_insertion_order_independent` | L2 |  | 1 |
| SR-5.6-1 | room test (Rust) | `p1_index_room_test_boundaries` | L1 |  | 1 |
| SR-3.2-3, SR-3.2-4, SR-4.1-0 | duplicates, re-insert, §15.1 order (Rust) | `p1_index_insert_validation_order_and_duplicates` | L1 |  | 1 |
| SR-7.4-1 … SR-7.6-1 | holding, flush, centroid, counters (Rust) | `p1_index_holding_flushes_exactly_at_target`, `p1_index_holding_record_deletable_not_searchable` | L1 |  | 1 |
| SR-7.3-2 | spillover first (Rust) | `p1_index_spillover_before_holding` | L1 | SB-8 | 1 |
| SR-7.7-1, SR-7.7-2 | routing pure (Rust) | `p1_index_routing_ignores_creation_order` | L6 | SB-7 | 1 |
| SR-7.5-1 | spawn ID (Rust) | `p1_index_golden_spawn_id` (golden 7) | L3 |  | 1 |
| §14.4 swap-with-last | locator follows moved slot | `p1_index_locator_follows_moved_slot` | L1 | SB-4 | 1 |
| SR-8.1-4 | mirror excision (Rust) | `p1_index_deleted_record_leaves_the_mirror`, `p1_search_results_order_and_deletion` | L1 | SB-5 | 1 |
| SR-9.7-1 | HMAC scrambler | `p1_index_scrambler_matches_python_hmac`, `p1_index_contracts` (EP-2) | L1, L7 |  | 1 |
| Build §3.4 EP-1, EP-2, EP-4 | contract suites | `p1_index_contracts`, `p1_types_ep4_*` | L7 |  | 1 |
| Build §4.7 L6 | whole-index twin; delete-reinsert | `p1_index_whole_index_twin`, `p1_index_delete_then_reinsert_is_identity` | L6 |  | 1 |
| SR-8.1-2 | probe budget counts empty groups | `p1_search_probe_count`, `p1_search_empty_groups_count_in_the_budget` | L1 | SB-6 | 1 |
| SR-8.2-1 | pinned kernel, scalar = AVX2 | `p1_search_kernel_lane_layout_by_hand`, `p1_search_kernel_scalar_equals_avx2`, `p1_search_prop_kernels_agree` | L1, L2 | SB-9 | 1 |
| SR-8.1-3 | result order | `p1_search_results_order_and_deletion` | L1 |  | 1 |
| Build §4.7 L9 E2E-1.1, 1.4, 1.5, 1.6 | survivors check per touched group; nothing else changes; second delete; no deleted result | `p1_e2e_demo_synthetic_deletion_is_exact`, `p1_e2e_demo_nq10k` (Full tier) | L9 |  | 1 |
| Build §4.7 L9 E2E-1.2; SR-7.4-2, SR-7.5-1 | flush at exactly the spawn target; spawn ID from the spec formula | `p1_e2e_flush_at_exactly_the_spawn_target` | L9 |  | 1 |
| Build §4.7 L9 E2E-1.3; SR-7.4-1, SR-7.4-3 | holding-area record deleted at once; no accumulator or N change | `p1_e2e_holding_record_deleted_at_once` | L9 |  | 1 |
| Build §4.7 L9 E2E-1.5; SR-5.4-2 | delete of an absent record changes nothing | `p1_e2e_delete_absent_is_already_absent` | L9 | SB-3 | 1 |
| Build §4.7 L9 E2E-1.7; SR-17-1, SR-17-2, SR-3.2-1…3, SR-4.1-0…3 | malformed inputs give typed errors naming no ID or value | `p1_e2e_malformed_inputs_typed_errors_without_secrets` | L9 |  | 1 |
| Build §4.9 step 6, P1-T14 | ghost baselines (measure) | `p1_ghost_*`, `p1_e2e_demo_synthetic_ghost_rows` | L1, L9 |  | 1 |
| SR-12.2-1 | every file operation through `Vfs` (with `create_dir`, `remove_dir`, DB-65) | `p2_vfs_ep5_sim_passes_functional_contract`, `p2_vfs_ep5_posix_passes_functional_contract_on_ext4`, `p2_vfs_ep5_posix_passes_functional_contract_on_tmpfs`, `p2_vfs_paths_are_checked_strictly` | L1, L7 | | 2 |
| SR-12.2-2 | `PosixVfs`: real files | `p2_vfs_ep5_posix_passes_functional_contract_on_ext4`, `p2_vfs_ep5_posix_passes_functional_contract_on_tmpfs` | L7 | | 2 |
| SR-12.2-3 | only synced data and synced entries survive a crash | `p2_vfs_ep5_sim_passes_crash_contract`, `p2_vfs_ep5_contract_rejects_a_backend_that_loses_nothing`, `p2_vfs_ep5_contract_rejects_a_backend_that_loses_synced_data`, `p2_vfs_sim_crash_at_every_operation_of_a_durable_create`, `p2_vfs_prop_synced_state_survives_every_policy` | L1, L2, L7 | | 2 |
| SR-12.2-4 | drop, tear, reorder, failed `fsync` | `p2_vfs_ep5_sim_passes_crash_contract`, `p2_vfs_ep5_contract_rejects_a_backend_without_fsync_faults`, `p2_vfs_sim_tears_the_crashing_write_at_the_requested_byte`, `p2_vfs_sim_fails_the_chosen_sync_counting_files_and_directories`, `p2_vfs_sim_failed_dir_sync_never_makes_the_entry_durable` | L1, L7 | | 2 |
| SR-12.2-5 | crash tests deterministic | `p2_vfs_ep5_sim_passes_crash_contract`, `p2_vfs_prop_same_seed_same_disk` | L2, L7 | | 2 |
