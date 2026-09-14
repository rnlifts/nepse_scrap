"""Load config/settings.toml, allow NEPSE_* env-var overrides."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config" / "settings.toml"


def _env_override(section: str, key: str, value):
    """NEPSE_<KEY> wins over the file value, cast to the file value's type."""
    env_key = f"NEPSE_{key.upper()}"
    if env_key not in os.environ:
        return value
    raw = os.environ[env_key]
    if isinstance(value, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    if isinstance(value, int):
        return int(raw)
    if isinstance(value, float):
        return float(raw)
    if isinstance(value, list):
        return [x.strip() for x in raw.split(",") if x.strip()]
    return raw


@dataclass
class Config:
    raw: dict

    def get(self, section: str, key: str):
        return _env_override(section, key, self.raw[section][key])

    # convenience accessors -------------------------------------------------
    @property
    def base_url(self) -> str:
        return self.get("source", "base_url")

    @property
    def symbols(self) -> list[str]:
        return self.get("symbols", "list")

    def path(self, section: str, key: str) -> Path:
        p = Path(self.get(section, key))
        return p if p.is_absolute() else PROJECT_ROOT / p


def load_config(path: Path | None = None) -> Config:
    path = path or CONFIG_PATH
    with open(path, "rb") as fh:
        return Config(raw=tomllib.load(fh))
