"""Fresh headless sessions inside the sandbox (FT-1, FT-2, FT-5).

Each session is a new ``claude -p`` process with a new, empty home folder, no MCP servers, no
skills, no settings, and the built-in file and shell tools only. Its prompt is a file in the room;
its transcript (JSON) goes to the run's ``logs/``. In a dry run the same sandbox runs
``stub_agent.py`` instead, so every stage can be exercised offline.
"""

import json
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
        rc = box.run(cmd, log, timeout, extra_env=auth)
        if '"api_error_status":401' in log.read_text(errors="replace"):
            raise SystemExit(
                "the sandbox credential was rejected (401); renew it (docs/FAIR_TESTING.md §4), "
                "check with `scripts/fair.sh doctor --live`, then `scripts/fair.sh resume <run_id>`"
            )
    return Session(role, name, model if not stub else "stub", rc, log, canary_log, _cost(log))


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
