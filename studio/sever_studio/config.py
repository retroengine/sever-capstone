"""Where Studio finds what it uses: written once by ``studio/studio.sh setup`` (DB-119).

Studio uses SEVER-DB only as a company's application would: the SDK wheel installed in its own
environment, the released programs (``sever-verify``, ``sever-audit``, Part 3's attack generator)
run from the paths below, and the data from one folder. ``studio.sh`` is the only code that knows
the repository; Studio's own code never builds anything or reads a path outside this file.

``config.toml``::

    [paths]
    data = "…/studio/vendor/data"          # datasets/, artefacts/, golden/ beneath it
    verify = "…/studio/vendor/bin/sever-verify"
    audit = "…/studio/vendor/bin/sever-audit"
    attacks = "…/studio/vendor/bin/sever-crashkit-p3"
    register = "…/studio/vendor/data/registers_p3.yaml"
    evidence = "…/studio/vendor/evidence"  # optional: the Evidence screen is hidden without it
"""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

#: ``studio/config.toml``, unless ``SEVER_STUDIO_CONFIG`` names another file.
DEFAULT = Path(__file__).resolve().parents[1] / "config.toml"


class ConfigMissingError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    data: Path
    verify: Path
    audit: Path
    attacks: Path
    register: Path
    evidence: Path | None = None


def load(path: Path | None = None) -> Config:
    path = path or Path(os.environ.get("SEVER_STUDIO_CONFIG", DEFAULT))
    if not path.exists():
        raise ConfigMissingError(f"no {path.name}: run studio/studio.sh setup first")
    p = tomllib.loads(path.read_text("utf-8"))["paths"]
    ev = p.get("evidence")
    return Config(
        data=Path(p["data"]),
        verify=Path(p["verify"]),
        audit=Path(p["audit"]),
        attacks=Path(p["attacks"]),
        register=Path(p["register"]),
        evidence=Path(ev) if ev and Path(ev).exists() else None,
    )
