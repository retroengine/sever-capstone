"""The clean-room sandbox (FT-1) and its canary (FT-2).

Every session and every measured test run is a ``bwrap`` process whose file system is built from an
explicit list of mounts: the system directories (read-only), the uv-managed CPython the virtual
environments point at (read-only), and the folders of the run that the stage may see. Nothing else
exists inside, so the repository, the home folder, ``~/.claude`` and ``/mnt`` cannot be read by any
tool, path trick or subprocess. The environment is built from scratch too (no inherited variables),
and a credential reaches a session through the process environment, never through argv.
"""

import glob
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

HOME_IN = "/home/tester"
CLAUDE_IN = "/opt/claude"
VENV_IN = "/opt/venv"
AUTH_FILE = Path.home() / ".config/sever-fair/auth.env"
AUTH_KEYS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")


@dataclass
class Box:
    """One sandbox: mounts as (kind, host path, sandbox path), environment, network."""

    mounts: list[tuple[str, str, str]] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    net: bool = False
    cwd: str = "/"

    def ro(self, host: Path | str, inside: str | None = None) -> "Box":
        self.mounts.append(("--ro-bind", str(host), inside or str(host)))
        return self

    def rw(self, host: Path | str, inside: str | None = None) -> "Box":
        self.mounts.append(("--bind", str(host), inside or str(host)))
        return self

    def argv(self, cmd: list[str]) -> list[str]:
        a = ["bwrap", "--die-with-parent", "--new-session", "--unshare-all"]
        if self.net:
            a.append("--share-net")
        a += ["--ro-bind", "/usr", "/usr", "--ro-bind", "/etc", "/etc"]
        for top in ("bin", "lib", "lib64", "sbin"):
            p = Path("/") / top
            if p.is_symlink():
                a += ["--symlink", os.readlink(p), f"/{top}"]
            elif p.exists():
                a += ["--ro-bind", str(p), f"/{top}"]
        a += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", HOME_IN]
        for kind, host, inside in self.mounts:
            a += [kind, host, inside]
        a += ["--chdir", self.cwd]
        return a + cmd

    def environ(self) -> dict[str, str]:
        base = {
            "PATH": "/room/bin:/opt/venv/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": HOME_IN,
            "LANG": "C.UTF-8",
            "TMPDIR": "/tmp",
            "PYTHONHASHSEED": "0",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        return base | self.env

    def run(
        self, cmd: list[str], log: Path, timeout: int, extra_env: dict[str, str] | None = None
    ) -> int:
        log.parent.mkdir(parents=True, exist_ok=True)
        env = self.environ() | (extra_env or {})
        with log.open("ab") as f:
            try:
                return subprocess.run(
                    self.argv(cmd),
                    env=env,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                ).returncode
            except subprocess.TimeoutExpired:
                f.write(b"\n[sever_fair] TIMEOUT\n")
                return 124


def python_base(venv: Path) -> Path:
    """The CPython install a uv venv points at; mounted read-only at its own path."""
    for line in (venv / "pyvenv.cfg").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            return Path(value.strip()).parent
    raise SystemExit(f"{venv}: no home in pyvenv.cfg")


def with_python(box: Box, venv: Path) -> Box:
    return box.ro(python_base(venv)).ro(venv, VENV_IN)


def claude_dir() -> Path:
    """The folder holding the headless ``claude`` binary (CLAUDE_BIN overrides)."""
    if env := os.environ.get("CLAUDE_BIN"):
        return Path(env).parent
    pattern = str(Path.home() / ".vscode-server/extensions/anthropic.claude-code-*")
    found = sorted(
        glob.glob(pattern + "/resources/native-binary/claude"),
        key=lambda p: [
            int(x) if x.isdigit() else 0
            for x in p.split("claude-code-")[1].split("-")[0].split(".")
        ],
    )
    if found:
        return Path(found[-1]).parent
    which = shutil.which("claude")
    if which:
        return Path(which).resolve().parent
    raise SystemExit("no claude binary found; set CLAUDE_BIN")


def auth_env() -> dict[str, str]:
    """The sandbox credential (docs/FAIR_TESTING.md §4): from the environment or auth.env."""
    out = {k: os.environ[k] for k in AUTH_KEYS if os.environ.get(k)}
    if not out and AUTH_FILE.exists():
        for line in AUTH_FILE.read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key in AUTH_KEYS and value:
                out[key] = value.strip().strip('"')
    return out


def forbidden_paths(repo: Path) -> list[str]:
    """Paths a canary must not reach (FT-2)."""
    home = Path.home()
    paths = {str(home / ".claude"), str(home / ".config"), str(home / ".ssh"), "/mnt", str(repo)}
    paths |= {p for p in glob.glob(str(home / "sever-db*"))}
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        paths |= {ln.split(" ", 1)[1] for ln in out.splitlines() if ln.startswith("worktree ")}
    except OSError:
        pass
    return sorted(paths)


CANARY = r"""
fail=0
for p in "$@"; do
  if [ -e "$p" ] || ls "$p" >/dev/null 2>&1; then echo "REACHABLE $p"; fail=1
  else echo "absent $p"; fi
done
[ -d /room ] && echo "room present" || { echo "ROOM MISSING"; fail=1; }
exit $fail
"""


def canary(box: Box, repo: Path, log: Path, allow: list[str] | None = None) -> bool:
    """FT-2: every forbidden path is absent inside ``box``; the room is present."""
    allowed = set(allow or [])
    paths = [p for p in forbidden_paths(repo) if p not in allowed]
    rc = box.run(["/bin/sh", "-c", CANARY, "canary", *paths], log, timeout=60)
    return rc == 0
