# code/search_engine.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Tuple
from collections import defaultdict

from .storage import NameRecord, NameRepository
from .matching import char_ngrams
from rapidfuzz import fuzz


@dataclass(frozen=True)
class SearchConfig:
    ngram_n: int = 3
    max_candidates: int = 2000  # cap por seguridad


class SearchEngine:
    """
    - Índice invertido por n-grams
    - Candidate generation + scoring explicable
    - Orden determinístico:
        1) similarity RAW desc
        2) token_score RAW desc
        3) edit_score RAW desc
        4) id asc
    """

    def __init__(self, repo: NameRepository, config: SearchConfig = SearchConfig()):
        self.repo = repo
        self.config = config

        self.records_by_id: Dict[int, NameRecord] = {}
        self.inverted: Dict[str, set[int]] = defaultdict(set)

        self._build_index()

    def _build_index(self) -> None:
        n = self.config.ngram_n
        for rec in self.repo.iter_records():
            self.records_by_id[rec.id] = rec
            for ng in char_ngrams(rec.normalized_name, n=n):
                self.inverted[ng].add(rec.id)

    def candidate_ids(self, query_norm: str) -> List[int]:
        n = self.config.ngram_n
        grams = char_ngrams(query_norm, n=n)

        candidate_ids = set()
        for g in grams:
            candidate_ids |= self.inverted.get(g, set())

        if not candidate_ids:
            return list(self.records_by_id.keys())

        if len(candidate_ids) > self.config.max_candidates:
            return sorted(candidate_ids)[: self.config.max_candidates]

        return list(candidate_ids)

    def search_explain(
        self,
        query_norm: str,
        threshold: float,
        limit: int,
        w_token: float = 0.65,
    ) -> Tuple[List[Dict], int]:
        cand_ids = self.candidate_ids(query_norm)
        candidate_count = len(cand_ids)

        scored: List[Dict] = []

        for rid in cand_ids:
            rec = self.records_by_id[rid]

            token_score_raw = float(fuzz.token_set_ratio(query_norm, rec.normalized_name))
            edit_score_raw = float(fuzz.ratio(query_norm, rec.normalized_name))
            combined_raw = w_token * token_score_raw + (1 - w_token) * edit_score_raw

            if combined_raw >= threshold:
                scored.append({
                    "id": rec.id,
                    "name": rec.full_name,

                    "_similarity_raw": combined_raw,
                    "_token_raw": token_score_raw,
                    "_edit_raw": edit_score_raw,

                    "similarity": round(combined_raw, 2),
                    "token_score": round(token_score_raw, 2),
                    "edit_score": round(edit_score_raw, 2),
                    "w_token": round(float(w_token), 3),
                })

        scored.sort(
            key=lambda m: (
                -m["_similarity_raw"],
                -m["_token_raw"],
                -m["_edit_raw"],
                m["id"],
            )
        )

        for m in scored:
            m.pop("_similarity_raw", None)
            m.pop("_token_raw", None)
            m.pop("_edit_raw", None)

        return scored[:limit], candidate_count
