from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Protocol, Tuple
import os
import sqlite3
import pandas as pd

from matching import normalize

# -----------------------
# Domain model
# -----------------------

@dataclass(frozen=True)
class NameRecord:
    id: int
    full_name: str
    normalized_name: str


class NameRepository(Protocol):
    def iter_records(self) -> Iterable[NameRecord]:
        ...


# -----------------------
# CSV repository (in-memory)
# -----------------------

class CSVRepository:
    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self._records: List[NameRecord] = []

    def load(self) -> None:
        df = pd.read_csv(self.csv_path)
        if not {"ID", "Full Name"}.issubset(df.columns):
            raise RuntimeError("El CSV debe contener columnas 'ID' y 'Full Name'")

        # Precomputo de normalizados (una sola vez)
        df["normalized_name"] = df["Full Name"].astype(str).apply(normalize)

        self._records = [
            NameRecord(
                id=int(row["ID"]),
                full_name=str(row["Full Name"]),
                normalized_name=str(row["normalized_name"]),
            )
            for _, row in df.iterrows()
        ]

    def iter_records(self) -> Iterable[NameRecord]:
        return iter(self._records)


# -----------------------
# SQLite repository
# -----------------------

class SQLiteRepository:
    """
    SQLite como storage persistente.
    - Crea tabla si no existe
    - Importa CSV si tabla vacía (o si force_reload=True)
    - Lee records desde SQLite (iterable)
    """

    def __init__(self, db_path: str, csv_path: str, force_reload: bool = False):
        self.db_path = db_path
        self.csv_path = csv_path
        self.force_reload = force_reload

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS names (
                    id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_names_norm ON names(normalized_name)")
            conn.commit()

        if self.force_reload:
            self._reload_from_csv()
            return

        # Importar solo si está vacío
        if self._count_rows() == 0:
            self._reload_from_csv()

    def _count_rows(self) -> int:
        with self._connect() as conn:
            cur = conn.execute("SELECT COUNT(1) FROM names")
            return int(cur.fetchone()[0])

    def _reload_from_csv(self) -> None:
        df = pd.read_csv(self.csv_path)
        if not {"ID", "Full Name"}.issubset(df.columns):
            raise RuntimeError("El CSV debe contener columnas 'ID' y 'Full Name'")

        df["normalized_name"] = df["Full Name"].astype(str).apply(normalize)

        rows: List[Tuple[int, str, str]] = []
        for _, r in df.iterrows():
            rows.append((int(r["ID"]), str(r["Full Name"]), str(r["normalized_name"])))

        with self._connect() as conn:
            conn.execute("DELETE FROM names")
            conn.executemany(
                "INSERT INTO names (id, full_name, normalized_name) VALUES (?, ?, ?)",
                rows,
            )
            conn.commit()

    def iter_records(self) -> Iterable[NameRecord]:
        # Streaming con cursor (no carga todo en RAM)
        conn = self._connect()
        cur = conn.execute("SELECT id, full_name, normalized_name FROM names")
        try:
            for row in cur:
                yield NameRecord(id=int(row[0]), full_name=row[1], normalized_name=row[2])
        finally:
            cur.close()
            conn.close()


# -----------------------
# Factory
# -----------------------

def build_repository() -> NameRepository:
    storage = os.getenv("STORAGE", "csv").strip().lower()
    csv_path = os.getenv("CSV_PATH", "names_dataset.csv")
    if storage == "csv":
        repo = CSVRepository(csv_path)
        repo.load()
        return repo

    if storage == "sqlite":
        db_path = os.getenv("SQLITE_PATH", "names.db")
        force_reload = os.getenv("SQLITE_FORCE_RELOAD", "false").strip().lower() in {"1", "true", "yes", "y"}
        repo = SQLiteRepository(db_path=db_path, csv_path=csv_path, force_reload=force_reload)
        repo.init_db()
        return repo

    raise RuntimeError("STORAGE inválido. Usar STORAGE=csv o STORAGE=sqlite")
