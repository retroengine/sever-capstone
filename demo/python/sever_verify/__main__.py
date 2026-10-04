"""Verify deletion certificates offline:

    PYTHONPATH=python python -m sever_verify <anchors.json> <certificate.cert> [more.cert ...]

With one certificate, every §11.3 step is printed. With several, one line each. Exit code 0 if every
certificate is accepted, 1 if any is rejected. Needs no database and no engine code.
"""

import json
import sys
from pathlib import Path

from sever_verify.certificate import FAIL, PASS, verify


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    anchors = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    paths = [Path(p) for p in argv[1:]]
    rejected = 0
    for path in paths:
        data = path.read_bytes()
        report = verify(data, anchors)
        rejected += not report.accepted
        verdict = "ACCEPTED" if report.accepted else "REJECTED"
        if len(paths) == 1:
            print(f"certificate {path.name}, {len(data):,} bytes")
            for step, status, detail in report.steps:
                mark = {PASS: "✓", FAIL: "✗"}.get(status, "-")
                print(f"  {mark} {status:<11} {step}{'  (' + detail + ')' if detail else ''}")
            print(verdict)
        else:
            failed = [s for s, status, _ in report.steps if status == FAIL]
            print(f"{path.name}: {verdict}" + (f" (failed: {'; '.join(failed)})" if failed else ""))
    if len(paths) > 1:
        print(f"{len(paths) - rejected} accepted, {rejected} rejected")
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
