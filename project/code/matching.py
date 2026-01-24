# code/matching.py
from __future__ import annotations

import re
import unicodedata
from typing import List

# -------------------------
# Normalización "strict" (igual al notebook)
# -------------------------
TITLE_PAT = re.compile(r"^(dr|dra|sr|sra|srta|ing|lic|prof)\.?\s+", re.IGNORECASE)
NON_LETTER = re.compile(r"[^a-zA-Z\s]")
MULTISPACE = re.compile(r"\s+")


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s)
        if not unicodedata.combining(c)
    )


def normalize_strict(name: str) -> str:
    """
    Normalización fuerte (dataset + query):
      - lower
      - strip accents
      - elimina títulos al inicio (dr/dra/sr/sra/...)
      - elimina símbolos/puntuación (deja letras y espacios)
      - colapsa espacios
    """
    s = str(name).strip().lower()
    s = strip_accents(s)
    s = TITLE_PAT.sub("", s)
    s = NON_LETTER.sub(" ", s)
    s = MULTISPACE.sub(" ", s).strip()
    return s


# Backward-compatible: la API importaba normalize()
normalize = normalize_strict


def char_ngrams(s: str, n: int = 3) -> List[str]:
    """
    N-grams de caracteres para candidate generation.
    Nota: dejamos espacios adentro; ya vienen colapsados por normalize().
    """
    if not s:
        return []
    if len(s) <= n:
        return [s]
    return [s[i:i + n] for i in range(len(s) - n + 1)]
