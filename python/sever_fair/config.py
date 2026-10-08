"""Pre-registered settings of the fair-testing system (configs/fair.yaml, FT-8)."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG = Path("configs/fair.yaml")
ROLES = ("tester", "judge", "planter", "fixer")


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

    def number(self, key: str) -> int:
        return int(self.raw[key])


def load(root: Path) -> Config:
    data = (root / CONFIG).read_bytes()
    raw = yaml.safe_load(data)
    for role in ROLES:
        if role not in raw["models"]:
            raise SystemExit(f"configs/fair.yaml: models.{role} missing")
    if raw["models"]["judge"] == raw["models"]["tester"]:
        raise SystemExit("configs/fair.yaml: the judge must not be the tester's model (FT-5)")
    return Config(raw, hashlib.sha256(data).hexdigest())
