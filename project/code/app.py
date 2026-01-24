# code/app.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Dict, Optional, Tuple, List, Any
from collections import OrderedDict
import os
import time

from .matching import normalize
from .storage import build_repository, get_repo_stats
from .search_engine import SearchEngine, SearchConfig
from .metrics import Metrics

app = FastAPI(
    title="Name Matching API",
    description=(
        "Matching de nombres usando (token_set_ratio + ratio) con candidate generation por n-grams, "
        "cache LRU, explicabilidad y métricas."
    ),
    version="1.4.1"
)

engine: Optional[SearchEngine] = None
metrics = Metrics()


# -----------------------
# LRU cache
# -----------------------

class LRUCache:
    def __init__(self, maxsize: int = 256):
        self.maxsize = maxsize
        self._data: "OrderedDict[Tuple, Dict[str, Any]]" = OrderedDict()

    def get(self, key: Tuple):
        v = self._data.get(key)
        if v is None:
            return None
        self._data.move_to_end(key)
        return v

    def set(self, key: Tuple, value: Dict[str, Any]):
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.maxsize:
            self._data.popitem(last=False)


CACHE_MAX = int(os.getenv("CACHE_MAX", "256"))
cache = LRUCache(maxsize=CACHE_MAX)


# -----------------------
# API Models
# -----------------------

class MatchRequest(BaseModel):
    name: str = Field(..., examples=["Juan Carlos Perez"])
    threshold: float = Field(70, ge=0, le=100)
    limit: int = Field(10, ge=1, le=100)
    w_token: float = Field(0.65, ge=0, le=1)
    explain: bool = Field(False, description="Si true, incluye token_score y edit_score por resultado.")
    include_by_id: bool = Field(
        True,
        description="Si true, incluye results_by_id (mapa por ID). El orden garantizado está en results (lista)."
    )


class MatchHit(BaseModel):
    id: int
    name: str
    similarity: float
    token_score: Optional[float] = None
    edit_score: Optional[float] = None
    w_token: Optional[float] = None


class MatchById(BaseModel):
    name: str
    similarity: float
    token_score: Optional[float] = None
    edit_score: Optional[float] = None
    w_token: Optional[float] = None


class MatchResponse(BaseModel):
    results: List[MatchHit]
    results_by_id: Optional[Dict[int, MatchById]] = None


# -----------------------
# Tie-break stats helper
# -----------------------

def compute_tie_break_stats(matches: List[Dict[str, Any]]) -> Tuple[int, int, int, int]:
    """
    Empates por similarity visible (2 decimales) y cómo se resolvieron.
    """
    if not matches:
        return (0, 0, 0, 0)

    groups_total = by_token = by_edit = by_id = 0
    i = 0
    n = len(matches)

    while i < n:
        sim = matches[i].get("similarity")
        j = i + 1
        while j < n and matches[j].get("similarity") == sim:
            j += 1

        if (j - i) > 1:
            groups_total += 1

            token_vals = {matches[k].get("token_score") for k in range(i, j)}
            if len(token_vals) > 1:
                by_token += 1
            else:
                edit_vals = {matches[k].get("edit_score") for k in range(i, j)}
                if len(edit_vals) > 1:
                    by_edit += 1
                else:
                    by_id += 1

        i = j

    return (groups_total, by_token, by_edit, by_id)


# -----------------------
# Startup
# -----------------------

@app.on_event("startup")
def startup():
    global engine
    repo = build_repository()
    ngram_n = int(os.getenv("NGRAM_N", "3"))
    max_candidates = int(os.getenv("MAX_CANDIDATES", "2000"))
    engine = SearchEngine(repo=repo, config=SearchConfig(ngram_n=ngram_n, max_candidates=max_candidates))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def get_metrics():
    snap = metrics.snapshot(topk=10)
    snap["repo"] = get_repo_stats()
    return snap


# -----------------------
# Core match (shared)
# -----------------------

def run_match(
    name: str,
    threshold: float,
    limit: int,
    w_token: float,
    explain: bool,
    include_by_id: bool
) -> Dict[str, Any]:
    assert engine is not None, "SearchEngine no inicializado"

    # normalización estricta del input del cliente (como definimos en ipynb)
    q_norm = normalize(name)
    metrics.inc_request(q_norm)

    key = (q_norm, float(threshold), int(limit), float(w_token), bool(explain), bool(include_by_id))
    cached = cache.get(key)
    if cached is not None:
        metrics.inc_cache_hit()
        return cached

    t0 = time.perf_counter()
    matches, candidate_count = engine.search_explain(
        query_norm=q_norm,
        threshold=threshold,
        limit=limit,
        w_token=w_token
    )
    latency_ms = (time.perf_counter() - t0) * 1000.0
    metrics.add_search_stats(latency_ms=latency_ms, candidate_count=candidate_count)

    tie_groups_total, by_token, by_edit, by_id = compute_tie_break_stats(matches)
    metrics.add_tie_stats(tie_groups_total, by_token, by_edit, by_id)

    if explain:
        results_list: List[Dict[str, Any]] = [
            {
                "id": m["id"],
                "name": m["name"],
                "similarity": m["similarity"],
                "token_score": m["token_score"],
                "edit_score": m["edit_score"],
                "w_token": m["w_token"],
            }
            for m in matches
        ]
    else:
        results_list = [
            {"id": m["id"], "name": m["name"], "similarity": m["similarity"]}
            for m in matches
        ]

    payload: Dict[str, Any] = {"results": results_list}

    if include_by_id:
        if explain:
            payload["results_by_id"] = {
                r["id"]: {
                    "name": r["name"],
                    "similarity": r["similarity"],
                    "token_score": r.get("token_score"),
                    "edit_score": r.get("edit_score"),
                    "w_token": r.get("w_token"),
                }
                for r in results_list
            }
        else:
            payload["results_by_id"] = {
                r["id"]: {"name": r["name"], "similarity": r["similarity"]}
                for r in results_list
            }

    cache.set(key, payload)
    return payload


@app.post("/match", response_model=MatchResponse, response_model_exclude_none=True)
def match_post(payload: MatchRequest):
    return run_match(
        name=payload.name,
        threshold=payload.threshold,
        limit=payload.limit,
        w_token=payload.w_token,
        explain=payload.explain,
        include_by_id=payload.include_by_id
    )


@app.get("/match", response_model=MatchResponse, response_model_exclude_none=True)
def match_get(
    name: str,
    threshold: float = 70,
    limit: int = 10,
    w_token: float = 0.65,
    explain: bool = False,
    include_by_id: bool = True
):
    if not (0 <= threshold <= 100):
        raise HTTPException(status_code=422, detail="threshold debe estar entre 0 y 100")
    if not (1 <= limit <= 100):
        raise HTTPException(status_code=422, detail="limit debe estar entre 1 y 100")
    if not (0 <= w_token <= 1):
        raise HTTPException(status_code=422, detail="w_token debe estar entre 0 y 1")

    return run_match(
        name=name,
        threshold=threshold,
        limit=limit,
        w_token=w_token,
        explain=explain,
        include_by_id=include_by_id
    )
