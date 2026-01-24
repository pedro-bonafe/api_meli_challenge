# code/storage.py
from __future__ import annotations

import os
import csv
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Iterable, Protocol

from .matching import normalize

# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # /app (porque /app/code/storage.py -> parents[1] = /app)
DATA_ROOT = Path(os.getenv("DATA_ROOT", str(PROJECT_ROOT / "data")))

RAW_DATA = DATA_ROOT / "raw"
CLEAN_DATA = DATA_ROOT / "clean"

DATASET_MODE = os.getenv("DATASET_MODE", "original").strip().lower()
# Valores aceptados:
#   - original
#   - standardized
#   - standardized+dedupe


# -------------------------------------------------------------------
# Repo state (para auditoría dedupe y métricas)
# -------------------------------------------------------------------

@dataclass
class RepoStats:
    mode: str
    sot_rows: int
    search_rows: int
    dedupe_groups: int
    dedupe_ratio: float  # search_rows / sot_rows


_LAST_STATS: Optional[RepoStats] = None
_GROUP_IDS_BY_REP_ID: Dict[int, List[int]] = {}


# -------------------------------------------------------------------
# Core types expected by SearchEngine
# -------------------------------------------------------------------

@dataclass(frozen=True)
class NameRecord:
    id: int
    full_name: str
    normalized_name: str


class NameRepository(Protocol):
    def iter_records(self) -> Iterable[NameRecord]:
        ...


class InMemoryNameRepository:
    def __init__(self, records: List[NameRecord]):
        self._records = records

    def iter_records(self) -> Iterable[NameRecord]:
        return self._records


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _read_csv_rows(path: str) -> List[Tuple[int, str]]:
    """
    Lee un CSV con columnas esperadas: id, name
    (tolerante: ignora columnas extra).
    """
    rows: List[Tuple[int, str]] = []
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV sin encabezados.")

        cols = {c.strip().lower(): c for c in reader.fieldnames}
        id_col = cols.get("id") or cols.get("idx") or cols.get("index")
        name_col = cols.get("name") or cols.get("nombre") or cols.get("full name") or cols.get("full_name") or cols.get("fullname")

        if not id_col or not name_col:
            raise ValueError(
                f"CSV debe tener columnas 'id' y 'name' (o equivalentes). Found={reader.fieldnames}"
            )

        for r in reader:
            try:
                _id = int(str(r[id_col]).strip())
            except Exception:
                continue

            name = str(r[name_col]).strip()
            if not name:
                continue

            rows.append((_id, name))
    return rows


def _strict_key(name: str) -> str:
    """
    Clave “fuerte” para dedupe.
    En este challenge la definimos como normalize() (estricta).
    """
    return normalize(name)


def _resolve_dataset_path(mode: str, dataset_path: Optional[str]) -> Path:
    if dataset_path:
        return Path(dataset_path)

    # default: según modo, elegimos raw o clean
    if mode == "original":
        return RAW_DATA / "names_dataset.csv"
    else:
        return CLEAN_DATA / "names_dataset_standardized.csv"


# -------------------------------------------------------------------
# Public API
# -------------------------------------------------------------------

def build_repository(dataset_path: Optional[str] = None) -> NameRepository:
    """
    Construye un repo que consume SearchEngine: NameRepository (iter_records()).

    Según DATASET_MODE:
      - original: full_name=original; normalized_name=normalize(original)
      - standardized: full_name=original; normalized_name=normalize(original) (pero viene de clean)
      - standardized+dedupe: deduplica por strict_key(normalize) y usa rep_id (id mínimo del grupo)
    """
    global _LAST_STATS, _GROUP_IDS_BY_REP_ID

    mode = DATASET_MODE
    if mode not in ("original", "standardized", "standardized+dedupe"):
        mode = "original"

    path = _resolve_dataset_path(mode, dataset_path)
    rows = _read_csv_rows(str(path))

    # ---- original / standardized (1:1) ----
    if mode in ("original", "standardized"):
        records = [
            NameRecord(id=_id, full_name=name, normalized_name=normalize(name))
            for _id, name in rows
            if normalize(name)
        ]

        _LAST_STATS = RepoStats(
            mode=mode,
            sot_rows=len(rows),
            search_rows=len(records),
            dedupe_groups=0,
            dedupe_ratio=(len(records) / len(rows)) if rows else 1.0,
        )
        _GROUP_IDS_BY_REP_ID = {}
        return InMemoryNameRepository(records)

    # ---- standardized+dedupe ----
    _GROUP_IDS_BY_REP_ID = {}
    groups: Dict[str, List[Tuple[int, str]]] = {}

    for _id, name in rows:
        k = _strict_key(name)
        if not k:
            continue
        groups.setdefault(k, []).append((_id, name))

    records: List[NameRecord] = []
    for k, members in groups.items():
        members_sorted = sorted(members, key=lambda x: x[0])
        rep_id = members_sorted[0][0]
        rep_name = members_sorted[0][1]  # dejamos “algo humano” en el output
        records.append(NameRecord(id=rep_id, full_name=rep_name, normalized_name=k))
        _GROUP_IDS_BY_REP_ID[rep_id] = [m[0] for m in members_sorted]

    _LAST_STATS = RepoStats(
        mode=mode,
        sot_rows=len(rows),
        search_rows=len(records),
        dedupe_groups=len(records),
        dedupe_ratio=(len(records) / len(rows)) if rows else 1.0,
    )
    return InMemoryNameRepository(records)


def get_repo_stats() -> Optional[dict]:
    if _LAST_STATS is None:
        return None
    return {
        "dataset_mode": _LAST_STATS.mode,
        "sot_rows": _LAST_STATS.sot_rows,
        "search_rows": _LAST_STATS.search_rows,
        "dedupe_groups": _LAST_STATS.dedupe_groups,
        "dedupe_ratio": _LAST_STATS.dedupe_ratio,
    }


def get_group_ids(rep_id: int) -> Optional[List[int]]:
    return _GROUP_IDS_BY_REP_ID.get(rep_id)
