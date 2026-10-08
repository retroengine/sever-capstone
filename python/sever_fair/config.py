"""Pre-registered settings of the fair-testing system (configs/fair.yaml, FT-8)."""

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG = Path("configs/fair.yaml")
ROLES = ("tester", "judge", "planter", "fixer")
COST_KEYS = ("budget", "on_usage_limit")  # DB-74: when to stop, not what is tested


@dataclass(frozen=True)
class Scope:
    """What one run covers: a whole part, or one module of it."""

    part: int
    module: str | None
    sections: list[str]
    not_sections: list[str]
    plant_paths: list[str]


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]
    sha256: str

    def model(self, role: str) -> str:
        return str(self.raw["models"][role])

    def part(self, n: int) -> dict[str, Any]:
        parts: dict[int, dict[str, Any]] = self.raw["parts"]
        if n not in parts:
            raise SystemExit(f"configs/fair.yaml has no entry for part {n}")
        return parts[n]

    def scope(self, n: int, module: str | None) -> Scope:
        p = self.part(n)
        if module is None:
            return Scope(
                n, None, list(p["sections"]), list(p["not_sections"]), list(p["plant_paths"])
            )
        mods: dict[str, dict[str, list[str]]] = p["modules"]
        if module not in mods:
            raise SystemExit(f"part {n} has no module {module!r}; known: {', '.join(mods)}")
        m = mods[module]
        return Scope(n, module, list(m["sections"]), list(p["not_sections"]), list(m["plant"]))

    @property
    def passrule(self) -> dict[str, Any]:
        rule: dict[str, Any] = self.raw["pass"]
        return rule

    def session_cap(self, role: str) -> float | None:
        caps = self.raw.get("budget", {}).get("session_usd", {})
        cap = caps.get(
            "judge"
            if role in ("triage", "escape", "oracle")
            else "fixer"
            if role in ("test", "code", "gap")
            else role
        )
        return float(cap) if cap is not None else None

    @property
    def command_cap(self) -> float | None:
        cap = self.raw.get("budget", {}).get("command_usd")
        return float(cap) if cap is not None else None

    @property
    def wait_on_limit(self) -> bool:
        return bool(self.raw.get("on_usage_limit", "stop") == "wait")

    def number(self, key: str) -> int:
        return int(self.raw[key])


def testing_digest(raw: dict[str, Any]) -> str:
    """FT-8 digest: every setting that decides what is tested (cost controls excluded)."""
    kept = {k: v for k, v in raw.items() if k not in COST_KEYS}
    return hashlib.sha256(json.dumps(kept, sort_keys=True, default=str).encode()).hexdigest()


def digest_at(root: Path, commit: str) -> str | None:
    """The FT-8 digest of configs/fair.yaml as it was at ``commit``."""
    r = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{CONFIG}"], capture_output=True, check=False
    )
    return testing_digest(yaml.safe_load(r.stdout)) if r.returncode == 0 else None


def load(root: Path) -> Config:
    data = (root / CONFIG).read_bytes()
    raw = yaml.safe_load(data)
    for role in ROLES:
        if role not in raw["models"]:
            raise SystemExit(f"configs/fair.yaml: models.{role} missing")
    if raw["models"]["judge"] == raw["models"]["tester"]:
        raise SystemExit("configs/fair.yaml: the judge must not be the tester's model (FT-5)")
    return Config(raw, testing_digest(raw))
