import unicodedata
from rapidfuzz import fuzz


def normalize(text: str) -> str:
    """
    Normaliza strings para matching:
    - strip
    - lowercase
    - elimina acentos/diacríticos
    - colapsa espacios múltiples
    """
    text = (text or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


def combined_score(query_norm: str, cand_norm: str, w_token: float = 0.65) -> float:
    """
    Score 0..100 combinando:
      - token_set_ratio: robusto a orden/omisiones (token similarity)
      - ratio: distancia de edición global (Levenshtein/Indel-like)

    Parámetros:
      - query_norm, cand_norm: deben venir ya normalizados con normalize()
      - w_token: peso del componente token (0..1). El resto se asigna al componente edit.
    """
    if not (0.0 <= w_token <= 1.0):
        raise ValueError("w_token debe estar entre 0 y 1")

    token_score = float(fuzz.token_set_ratio(query_norm, cand_norm))
    edit_score = float(fuzz.ratio(query_norm, cand_norm))
    return w_token * token_score + (1.0 - w_token) * edit_score


def char_ngrams(text: str, n: int = 3) -> set[str]:
    """
    Genera n-grams de caracteres con padding simple.
    Se usa para candidate generation (índice invertido).

    Ej:
      text="juan" n=3 -> {" ju", "jua", "uan", "an ", "n  "} (según padding)
    """
    if n <= 0:
        raise ValueError("n debe ser > 0")

    t = f" {text} "
    if len(t) < n:
        return {t}
    return {t[i : i + n] for i in range(len(t) - n + 1)}
