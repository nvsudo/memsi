"""Settings: memsi.yaml + .env + environment overrides."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class Thresholds(BaseModel):
    duplicate: float = 0.92
    conflict_low: float = 0.75


class AutoApproveRule(BaseModel):
    type: str
    min_confidence: float = 0.9
    sources: list[str] = Field(default_factory=list)  # empty = any source
    require_no_neighbours: bool = True


class ReadFilter(BaseModel):
    sensitivity_max: str = "private"


class RecallConfig(BaseModel):
    budget_tokens: int = 1500
    always_scopes: list[str] = Field(default_factory=lambda: ["personal", "work"])
    type_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "identity": 3, "preference": 2, "decision": 2, "project": 1.5,
            "fact": 1, "procedure": 1, "relationship": 1,
        }
    )
    recency_half_life_days: float = 60


class Settings(BaseModel):
    owner: str = "me"
    backend: str = "memory"  # redis | memory
    redis_url: str = "redis://localhost:6379"
    embedder: str = "hash"  # hash | bge-small | ollama
    data_dir: Path = Path(".memsi")
    backups_dir: Path = Path("~/.memsi/backups")
    thresholds: Thresholds = Field(default_factory=Thresholds)
    auto_approve: list[AutoApproveRule] = Field(default_factory=list)
    never_auto_approve_types: list[str] = Field(default_factory=lambda: ["identity", "relationship"])
    read_filters: dict[str, ReadFilter] = Field(default_factory=dict)
    recall: RecallConfig = Field(default_factory=RecallConfig)
    pending_expiry_days: int = 7
    config_path: Optional[Path] = None

    def read_filter_for(self, app: Optional[str]) -> ReadFilter:
        if app and app in self.read_filters:
            return self.read_filters[app]
        return ReadFilter()


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def find_config_path(explicit: Optional[str] = None) -> Optional[Path]:
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get("MEMSI_CONFIG"):
        candidates.append(Path(os.environ["MEMSI_CONFIG"]))
    candidates += [Path.cwd() / "memsi.yaml", Path.home() / ".memsi" / "memsi.yaml"]
    for c in candidates:
        if c.exists():
            return c
    return None


def load_settings(explicit: Optional[str] = None) -> Settings:
    path = find_config_path(explicit)
    raw: dict = {}
    if path:
        raw = yaml.safe_load(path.read_text()) or {}
        _load_dotenv(path.parent / ".env")
    _load_dotenv(Path.cwd() / ".env")

    if os.environ.get("MEMSI_OWNER"):
        raw["owner"] = os.environ["MEMSI_OWNER"]
    if os.environ.get("MEMSI_BACKEND"):
        raw["backend"] = os.environ["MEMSI_BACKEND"]
    if os.environ.get("REDIS_URL"):
        raw["redis_url"] = os.environ["REDIS_URL"]
    if os.environ.get("MEMSI_EMBEDDER"):
        raw["embedder"] = os.environ["MEMSI_EMBEDDER"]
    if os.environ.get("MEMSI_DATA_DIR"):
        raw["data_dir"] = os.environ["MEMSI_DATA_DIR"]

    s = Settings(**raw)
    s.config_path = path
    if path and not Path(s.data_dir).is_absolute():
        s.data_dir = path.parent / s.data_dir
    return s
