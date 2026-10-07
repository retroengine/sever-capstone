"""``spec-trace`` for Part 2 (Build §2.2): Part 1's frozen tool, told which sections Part 2 owns.

PYTHONPATH=python uv run python -m sever_testkit_p2.spec_trace report --part 2
PYTHONPATH=python uv run python -m sever_testkit_p2.spec_trace check --part 2 --complete
PYTHONPATH=python uv run python -m sever_testkit_p2.spec_trace candidates --part 2
"""

import sys
from typing import Final

from sever_testkit import spec_trace as frozen

#: Subsections Part 2 owns (CLAUDE.md §6.1: §12, §14 without §14.5 and §14.7, §15, §16.1, §17).
PART2_SECTIONS: Final = [
    "12.1", "12.2", "12.3", "12.4", "12.5", "12.6", "12.7", "12.9",
    "14", "14.1", "14.2", "14.3", "14.4", "14.6", "14.8", "14.9",
    "15.1", "15.2", "15.3", "15.4", "15.6", "15.7", "15.8", "15.9", "16.1", "17",
]  # fmt: skip


def main(argv: list[str]) -> int:
    frozen.PART_SECTIONS.setdefault(2, PART2_SECTIONS)
    return frozen._main(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
