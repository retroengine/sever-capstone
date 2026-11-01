"""Self-checks of the clean-room oracle in sevlib.py against third-party vectors. They do not
touch the engine; they show that a failure elsewhere is not the oracle's fault."""

import hashlib

import sevlib

B_ENC = bytes.fromhex("e2f2ae0a6abc4e71a884a961c500515f58e30b6aa582dd8db6a65945e08d2d76")


def test_ristretto255_multiples_of_the_generator():
    """RFC 9496 Appendix A.1: encodings of 2·B and 3·B; 0·B is the all-zero encoding."""
    B = sevlib.r_decode(B_ENC)
    assert sevlib.r_encode(sevlib.padd(B, B)).hex() == (
        "6a493210f7499cd17fecb510ae0cea23a110e8d5b901f8acadd3095c73a3b919")
    assert sevlib.r_encode(sevlib.pmul(3, B)).hex() == (
        "94741f5d5d52755ece4f23f044ee27d5d1ea1e2bd196b462166b16152a9d0259")
    assert sevlib.r_encode(sevlib.pmul(sevlib.L, B)) == bytes(32)


def test_ristretto255_one_way_map():
    """RFC 9496 Appendix A.3, first vector of the one-way map."""
    x = bytes.fromhex("5d1be09e3d0c82fc538112490e35701979d99e06ca3e2b5b54bffe8b4dc772c1"
                      "4d98b696a1bbfb5ca32c436cc61c16563790306c79eaca7705668b47dffe5bb6")
    assert sevlib.r_encode(sevlib.from_uniform_bytes(x)).hex() == (
        "3066f82a1a747d45120d1740f14358531a8f04bbffe6a819f86dfe50f44a0a46")


def test_expand_message_xmd_sha512():
    """RFC 9380 Appendix K.3, msg = "" and len_in_bytes = 0x20."""
    out = sevlib.expand_message_xmd_sha512(b"", b"QUUX-V01-CS02-with-expander-SHA512-256", 0x20)
    assert out.hex() == "6b9a7312411d92f921c6f68ca0b6380730a1a4d982c507211a90964c394179ba"


def test_ed25519_rfc8032_test_1():
    """RFC 8032 §7.1 TEST 1 (empty message)."""
    pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    sig = bytes.fromhex("e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555"
                        "fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    assert sevlib.ed25519_verify(pk, b"", sig)
    assert not sevlib.ed25519_verify(pk, b"x", sig)


def test_merkle_proofs_round_trip():
    """RFC 9162 §2.1: every PATH and PROOF built here verifies, and a wrong root does not."""
    hs = [sevlib.leaf_hash(bytes([i])) for i in range(20)]
    for n in range(1, 20):
        root = sevlib.mth_hashes(hs[:n])
        for m in range(n):
            assert sevlib.verify_inclusion(m, n, hs[m], sevlib.inclusion_path(hs[:n], m), root)
        for m in range(1, n):
            p = sevlib.consistency_path(hs[:n], m)
            assert sevlib.verify_consistency(m, n, sevlib.mth_hashes(hs[:m]), root, p)
            assert not sevlib.verify_consistency(m, n, sevlib.mth_hashes(hs[:m]), hs[0], p)
    assert sevlib.mth([]) == hashlib.sha256(b"").digest()


def test_scalar_mapping_golden_inputs():
    """§4.5 for the Appendix B vector-4 inputs v ∈ {0, 1, −1, 2^44, −2^44}."""
    L = sevlib.L
    assert [sevlib.scalar_of(v) for v in (0, 1, -1, 2**44, -(2**44))] == [
        0, 1, L - 1, 2**44, L - 2**44]


def test_artefact_parser_matches_its_manifest():
    """The small artefact's JSON manifest lists tau, centroid_0_0 and precision_15_15."""
    import json
    import os

    import helpers as h

    art = sevlib.parse_artefact(h.SMALL)
    meta = json.load(open(os.path.join(h.INPUTS, "p1_partition_small.json")))
    assert (art.d, art.k) == (16, 4)
    assert art.tau == meta["tau"] and art.centroids[0, 0] == meta["centroid_0_0"]
    assert art.P[15, 15] == meta["precision_15_15"]
