"""Central settings: filesystem paths, .env loading, and YAML config access.

Everything is resolved relative to the project root (the parent of the ``app`` package),
so the CLI works regardless of the current working directory.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path
from typing import Any

import yaml

# --- Paths -----------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
MANUAL_IMPORT_DIR = DATA_DIR / "manual_imports"
PROCESSED_DIR = DATA_DIR / "processed"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "arbitrage.sqlite"
SCHEMA_PATH = PROJECT_ROOT / "app" / "storage" / "schema.sql"

_CONFIG_FILES = {
    "scoring": "scoring.yaml",
    "risk_rules": "risk_rules.yaml",
    "categories": "categories.yaml",
    "suitcase": "suitcase.yaml",
    "sources": "sources.yaml",
}


def ensure_dirs() -> None:
    """Create the data subdirectories if they do not already exist."""
    for d in (RAW_DIR, SNAPSHOT_DIR, MANUAL_IMPORT_DIR, PROCESSED_DIR, EXPORT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_env(path: Path | None = None) -> dict[str, str]:
    """Load a simple ``.env`` file into ``os.environ`` (without overwriting existing vars).

    Returns the parsed key/value mapping. Missing file is fine (returns ``{}``).
    """
    env_path = path or (PROJECT_ROOT / ".env")
    parsed: dict[str, str] = {}
    if not env_path.exists():
        return parsed
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        parsed[key] = value
        os.environ.setdefault(key, value)
    return parsed


@functools.lru_cache(maxsize=None)
def load_config(name: str) -> dict[str, Any]:
    """Load and cache a named YAML config (e.g. ``"scoring"``)."""
    if name not in _CONFIG_FILES:
        raise KeyError(f"Unknown config '{name}'. Known: {sorted(_CONFIG_FILES)}")
    path = CONFIG_DIR / _CONFIG_FILES[name]
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config '{name}' must be a mapping at top level.")
    return data


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    """Load an arbitrary YAML file (used for seed files passed on the CLI)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"YAML file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def jpy_to_usd_rate() -> float:
    """USD per 1 JPY. Env override wins; otherwise a conservative default (~150 JPY/USD)."""
    raw = os.environ.get("JPY_TO_USD_RATE", "").strip()
    try:
        rate = float(raw) if raw else 0.0067
    except ValueError:
        rate = 0.0067
    return rate if rate > 0 else 0.0067


def get_env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def validate_scoring_config() -> list[str]:
    """Sanity-check the scoring config; returns a list of human-readable warnings."""
    warnings: list[str] = []
    cfg = load_config("scoring")
    weights = cfg.get("weights", {})
    total = sum(float(v) for v in weights.values())
    if abs(total - 1.0) > 0.02:
        warnings.append(f"scoring.weights sum to {total:.3f}, expected ~1.0")
    tiers = cfg.get("tiers", {})
    if not {"A", "B", "C"} <= set(tiers):
        warnings.append("scoring.tiers must define A, B, and C cut points")
    return warnings
