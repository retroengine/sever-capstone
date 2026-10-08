"""Fresh headless sessions inside the sandbox (FT-1, FT-2, FT-5).

Each session is a new ``claude -p`` process with a new, empty home folder, no MCP servers, no
skills, no settings, and the built-in file and shell tools only. Its prompt is a file in the room;
its transcript (JSON) goes to the run's ``logs/``. In a dry run the same sandbox runs
``stub_agent.py`` instead, so every stage can be exercised offline.
"""

import datetime as dt
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from sever_fair import sandbox
from sever_fair.sandbox import CLAUDE_IN, HOME_IN, Box

PROMPTS = Path(__file__).parent / "prompts"
STUB = Path(__file__).parent / "stub_agent.py"
TOOLS = "Read,Write,Edit,Bash,Glob,Grep"


@dataclass
class Session:
    role: str
    name: str
    model: str
    rc: int
    log: Path
    canary_log: Path
    cost_usd: float | None


class CanaryFailed(SystemExit):
    pass


def prompt(name: str, **fields: object) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").format(**fields)


def run(
    *,
    run_dir: Path,
    repo: Path,
    role: str,
    name: str,
    model: str,
    text: str,
    box: Box,
    prompt_dir: Path,
    stub: bool,
    timeout: int,
    canary_allow: list[str] | None = None,
) -> Session:
    """Runs one fresh session. ``prompt_dir`` must be mounted in ``box``; the prompt lands there."""
    home = run_dir / "homes" / name
    home.mkdir(parents=True, exist_ok=True)
    box.rw(home, HOME_IN)
    logs = run_dir / "logs"
    canary_log = logs / f"{name}.canary.log"
    if not sandbox.canary(box, repo, canary_log, canary_allow):
        raise CanaryFailed(f"FT-2 canary failed for {name}: {canary_log}")
    (prompt_dir / "PROMPT.md").write_text(text, encoding="utf-8")
    inside = _inside(box, prompt_dir)
    log = logs / f"{name}.json"
    if stub:
        box.ro(STUB, "/opt/fair/stub_agent.py")
        cmd = ["/opt/venv/bin/python", "/opt/fair/stub_agent.py", role, inside]
        rc = box.run(cmd, log, timeout)
    else:
        box.ro(sandbox.claude_dir(), CLAUDE_IN)
        box.net = True
        cmd = [
            f"{CLAUDE_IN}/claude",
            "-p",
            f"Read {inside}/PROMPT.md and carry it out completely.",
            "--model",
            model,
            "--tools",
            TOOLS,
            "--strict-mcp-config",
            "--permission-mode",
            "bypassPermissions",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--output-format",
            "json",
        ]
        auth = sandbox.auth_env()
        if not auth:
            raise SystemExit("no sandbox credential; see docs/FAIR_TESTING.md §4 (fair.sh doctor)")
        rc = _run_with_waits(box, cmd, log, timeout, auth)
    return Session(role, name, model if not stub else "stub", rc, log, canary_log, _cost(log))


RESET = re.compile(r"resets\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*\(UTC\)", re.IGNORECASE)
MAX_LIMIT_WAITS = 24  # a usage limit resets every few hours; a long cycle may meet it many times
MAX_ERROR_RETRIES = 3


def reset_wait(message: str, now: dt.datetime) -> float:
    """Seconds until the usage limit named in ``message`` resets, plus two minutes."""
    m = RESET.search(message)
    if not m:
        return 30 * 60.0
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
    at = now.replace(hour=hour, minute=int(m.group(2) or 0), second=0, microsecond=0)
    if at <= now:
        at += dt.timedelta(days=1)
    return (at - now).total_seconds() + 120.0


def _result(log: Path) -> dict[str, object]:
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    start = text.find('{"')
    try:
        data = json.loads(text[start:]) if start >= 0 else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _run_with_waits(box: Box, cmd: list[str], log: Path, timeout: int, auth: dict[str, str]) -> int:
    """One session; on a usage limit it waits for the reset and runs a fresh session again."""
    limit_waits = errors = 0
    while True:
        if log.exists():
            n = len(list(log.parent.glob(log.stem + ".attempt*.json"))) + 1
            log.rename(log.with_name(f"{log.stem}.attempt{n}.json"))
        rc = box.run(cmd, log, timeout, extra_env=auth)
        res = _result(log)
        status = res.get("api_error_status")
        if status == 401:
            raise SystemExit(
                "the sandbox credential was rejected (401); renew it (docs/FAIR_TESTING.md §4), "
                "check with `scripts/fair.sh doctor --live`, then `scripts/fair.sh resume <run_id>`"
            )
        if status == 429 and limit_waits < MAX_LIMIT_WAITS:
            limit_waits += 1
            wait = reset_wait(str(res.get("result", "")), dt.datetime.now(dt.UTC))
            print(
                f"usage limit; waiting {wait / 60:.0f} min for the reset, then a fresh session",
                flush=True,
            )
            time.sleep(wait)
            continue
        if res.get("is_error") and status not in (None, 429) and errors < MAX_ERROR_RETRIES:
            errors += 1
            time.sleep(300)
            continue
        if rc == 0 and res.get("is_error"):
            rc = 1
        return rc


def _inside(box: Box, host: Path) -> str:
    for _, h, i in box.mounts:
        if str(host) == h:
            return i
        if str(host).startswith(h + "/"):
            return i + str(host)[len(h) :]
    raise ValueError(f"{host} is not mounted in the sandbox")


def _cost(log: Path) -> float | None:
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
        start = text.find("{")
        data = json.loads(text[start:]) if start >= 0 else {}
        cost = data.get("total_cost_usd")
        return float(cost) if cost is not None else None
    except (OSError, ValueError):
        return None
