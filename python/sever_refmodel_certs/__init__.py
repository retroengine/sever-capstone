"""sever_refmodel_certs: the reference model of Part 3's certificate arithmetic (C-18's Part 3
package; Build 3-4 §1.4, DB-51).

Written from the specification and the RFC texts only, never from engine code: a small pure-Python
ristretto255 (RFC 9496) and ``expand_message_xmd`` (RFC 9380), checked against the RFCs' own test
vectors (``golden/p3_rfc*.json``), then the spec's generators (§9.2), ``scalar(v)`` (§4.5) and
commitments (§9.3). It uses only the standard library. It is slow and meant for small and medium
streams; the expected values it produces are golden files of Appendix B (Build 3-4 §3.4).
"""
