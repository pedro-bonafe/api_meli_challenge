# code/storage.py
from __future__ import annotations

import os
import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Protocol, Dict, Any, Optional, Tuple

from .matching import normalize  # normalize estricto (ver matching.py)


# -------------------------------------------------------------------
# Core types expected by SearchEngine
# -------------------------------------------------------------------

@dataclass(frozen=True)
class NameRecord:
    id: int
    full_name: str
    normalized_name: str  # lo que se indexa (strict_key o normalize(full_name))


class NameRepository(Protocol):
    def iter_records(self) -> Iterable[NameRecord]:
        ...


class InMemoryNameRepository:
    def __init__(self, records: List[NameRecord]):
        self._records = records

    def iter_records(self) -> Iterable[NameRecord]:
        return self._records


# -------------------------------------------------------------------
# Internal state (para stats en /metrics)
# -------------------------------------------------------------------

_REPO_STATS: Dict[str, Any] = {}


def get_repo_stats() -> Dict[str, Any]:
    """
    Info del repo cargado (para /metrics).
    """
    return dict(_REPO_STATS) if _REPO_STATS else {}


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _csv_read_dicts(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = [r for r in reader]
    return rows, fieldnames


def _pick_dataset_path(data_root: Path, mode: str) -> Path:
    """
    mode:
      - original -> data/raw/names_dataset.csv
      - standardized / standardized+dedupe -> data/clean/names_dataset_standardized.csv
    """
    if mode in ("standardized", "standardized+dedupe"):
        return data_root / "clean" / "names_dataset_standardized.csv"
    return data_root / "raw" / "names_dataset.csv"


def _build_records_from_csv(path: Path, mode: str) -> List[NameRecord]:
    rows, cols = _csv_read_dicts(path)

    # CSV original típico: ["ID", "Full Name"] o ["id","name"]
    # CSV clean típico: ["ID","Full Name","name_strict","strict_key", ...]
    colset = {c.strip() for c in cols}

    def get_first(row: Dict[str, str], *cands: str) -> Optional[str]:
        for c in cands:
            if c in row and row[c] not in (None, ""):
                return row[c]
        return None

    records: List[NameRecord] = []

    for r in rows:
        raw_id = get_first(r, "id", "ID", "Id", "ID ")
        raw_name = get_first(r, "name", "Full Name", "full_name", "FullName", "nombre", "Name")

        if raw_id is None or raw_name is None:
            # si faltan columnas, levantamos un error bien claro
            raise ValueError(
                f"CSV debe tener columnas de id y name. Found={cols}. "
                f"Ejemplos soportados: ('id','name') o ('ID','Full Name')."
            )

        rid = int(str(raw_id).strip())
        full_name = str(raw_name)

        if mode in ("standardized", "standardized+dedupe"):
            # En clean, preferimos usar lo ya calculado en el notebook:
            # - normalized_name: strict_key (clave fuerte)
            # - full_name: podés devolver Full Name original (más “humano”)
            strict_key = get_first(r, "strict_key")
            if strict_key:
                normalized_name = str(strict_key)
            else:
                # fallback (si por algún motivo el archivo clean no tuviera strict_key)
                normalized_name = normalize(full_name)
        else:
            # original: normalizamos en runtime (estricto)
            normalized_name = normalize(full_name)

        records.append(NameRecord(id=rid, full_name=full_name, normalized_name=normalized_name))

    return records


# -------------------------------------------------------------------
# SQLITE (api_sqlite)
# -------------------------------------------------------------------

def _ensure_sqlite_db(sqlite_path: Path) -> None:
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.cursor()

        # Si la tabla no existe, creamos el esquema nuevo
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS names (
                id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL
            )
            """
        )

        # Chequeo columnas reales existentes
        cur.execute("PRAGMA table_info(names)")
        cols = [row[1] for row in cur.fetchall()]  # row[1]=name
        colset = set(cols)

        # Si es tabla vieja (no tiene full_name), intentamos migrar
        if "full_name" not in colset:
            # Creamos tabla nueva
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS names_new (
                    id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL
                )
                """
            )

            # Elegimos desde qué columnas migrar (según lo que exista)
            # Caso 1: tabla vieja tenía 'name' y 'normalized_name'
            if "name" in colset and "normalized_name" in colset:
                cur.execute(
                    """
                    INSERT INTO names_new(id, full_name, normalized_name)
                    SELECT id, name, normalized_name FROM names
                    """
                )

            # Caso 2: tabla vieja tenía 'Full Name' (raro pero posible) y 'normalized_name'
            elif "Full Name" in colset and "normalized_name" in colset:
                cur.execute(
                    """
                    INSERT INTO names_new(id, full_name, normalized_name)
                    SELECT id, "Full Name", normalized_name FROM names
                    """
                )

            # Caso 3: tabla vieja tenía solo 'name' (sin normalized)
            elif "name" in colset:
                cur.execute(
                    """
                    INSERT INTO names_new(id, full_name, normalized_name)
                    SELECT id, name, '' FROM names
                    """
                )

            # Caso 4: tabla vieja tenía solo 'Full Name'
            elif "Full Name" in colset:
                cur.execute(
                    """
                    INSERT INTO names_new(id, full_name, normalized_name)
                    SELECT id, "Full Name", '' FROM names
                    """
                )
            else:
                # No sabemos migrar: la dejamos vacía y se recarga desde CSV más abajo
                pass

            # Swap
            cur.execute("DROP TABLE names")
            cur.execute("ALTER TABLE names_new RENAME TO names")

        # Índice
        cur.execute("CREATE INDEX IF NOT EXISTS idx_names_norm ON names(normalized_name)")
        conn.commit()
    finally:
        conn.close()


def _sqlite_has_rows(sqlite_path: Path) -> bool:
    if not sqlite_path.exists():
        return False
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(1) FROM names")
        n = int(cur.fetchone()[0])
        return n > 0
    finally:
        conn.close()


def _load_sqlite_from_csv(sqlite_path: Path, csv_path: Path, mode: str) -> int:
    records = _build_records_from_csv(csv_path, mode=mode)

    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM names")
        cur.executemany(
            "INSERT INTO names(id, full_name, normalized_name) VALUES(?,?,?)",
            [(r.id, r.full_name, r.normalized_name) for r in records],
        )
        conn.commit()
        return len(records)
    finally:
        conn.close()


def _read_sqlite_records(sqlite_path: Path) -> List[NameRecord]:
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, full_name, normalized_name FROM names")
        out = [NameRecord(id=int(i), full_name=str(n), normalized_name=str(nn)) for (i, n, nn) in cur.fetchall()]
        return out
    finally:
        conn.close()


# -------------------------------------------------------------------
# Public factory
# -------------------------------------------------------------------

def build_repository() -> NameRepository:
    """
    Devuelve SIEMPRE un NameRepository (no dict).
    Config por env:
      - STORAGE=csv|sqlite
      - DATA_ROOT=/app/data
      - DATASET_MODE=original|standardized|standardized+dedupe
      - SQLITE_PATH=/data/names.db
      - SQLITE_FORCE_RELOAD=true|false
    """
    storage = os.getenv("STORAGE", "csv").strip().lower()
    data_root = Path(os.getenv("DATA_ROOT", "/app/data"))
    mode = os.getenv("DATASET_MODE", "original").strip().lower()

    if mode not in ("original", "standardized", "standardized+dedupe"):
        mode = "original"

    dataset_path = _pick_dataset_path(data_root, mode=mode)

    if storage == "sqlite":
        sqlite_path = Path(os.getenv("SQLITE_PATH", "/data/names.db"))
        force_reload = os.getenv("SQLITE_FORCE_RELOAD", "false").strip().lower() == "true"

        _ensure_sqlite_db(sqlite_path)

        if force_reload or not _sqlite_has_rows(sqlite_path):
            loaded_n = _load_sqlite_from_csv(sqlite_path, dataset_path, mode=mode)
        else:
            loaded_n = -1  # no recargó

        records = _read_sqlite_records(sqlite_path)

        _REPO_STATS.update(
            {
                "storage": "sqlite",
                "dataset_mode": mode,
                "data_root": str(data_root),
                "dataset_path": str(dataset_path),
                "sqlite_path": str(sqlite_path),
                "sqlite_loaded_rows": loaded_n,
                "records": len(records),
            }
        )
        return InMemoryNameRepository(records)

    # default: CSV -> memoria
    records = _build_records_from_csv(dataset_path, mode=mode)

    _REPO_STATS.update(
        {
            "storage": "csv",
            "dataset_mode": mode,
            "data_root": str(data_root),
            "dataset_path": str(dataset_path),
            "records": len(records),
        }
    )

    return InMemoryNameRepository(records)
