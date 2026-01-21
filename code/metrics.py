from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Deque
from collections import deque
import time


@dataclass
class RollingStats:
    maxlen: int = 5000
    lat_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=5000))
    candidates: Deque[int] = field(default_factory=lambda: deque(maxlen=5000))

    def add(self, latency_ms: float, candidate_count: int) -> None:
        self.lat_ms.append(latency_ms)
        self.candidates.append(candidate_count)

    @staticmethod
    def mean(arr) -> float:
        if not arr:
            return 0.0
        return sum(arr) / len(arr)

    @staticmethod
    def p95(arr) -> float:
        if not arr:
            return 0.0
        s = sorted(arr)
        idx = int(0.95 * (len(s) - 1))
        return s[idx]


@dataclass
class Metrics:
    started_at: float = field(default_factory=time.time)

    total_requests: int = 0
    total_cache_hits: int = 0

    # top queries (normalizadas) con contador
    top_queries: Dict[str, int] = field(default_factory=dict)

    # rolling
    rolling: RollingStats = field(default_factory=RollingStats)

    # tie-break stats (por grupos de empate)
    tie_groups_total: int = 0
    tie_resolved_by_token: int = 0
    tie_resolved_by_edit: int = 0
    tie_resolved_by_id: int = 0

    def inc_request(self, query_norm: str) -> None:
        self.total_requests += 1
        self.top_queries[query_norm] = self.top_queries.get(query_norm, 0) + 1

    def inc_cache_hit(self) -> None:
        self.total_cache_hits += 1

    def add_search_stats(self, latency_ms: float, candidate_count: int) -> None:
        self.rolling.add(latency_ms=latency_ms, candidate_count=candidate_count)

    def add_tie_stats(self, groups_total: int, by_token: int, by_edit: int, by_id: int) -> None:
        self.tie_groups_total += groups_total
        self.tie_resolved_by_token += by_token
        self.tie_resolved_by_edit += by_edit
        self.tie_resolved_by_id += by_id

    def snapshot(self, topk: int = 10) -> Dict:
        uptime_s = time.time() - self.started_at
        cache_hit_rate = (self.total_cache_hits / self.total_requests) if self.total_requests else 0.0

        top = sorted(self.top_queries.items(), key=lambda x: x[1], reverse=True)[:topk]

        # porcentajes de desempate
        denom = self.tie_groups_total if self.tie_groups_total else 0
        tie_pct_token = (self.tie_resolved_by_token / denom) if denom else 0.0
        tie_pct_edit = (self.tie_resolved_by_edit / denom) if denom else 0.0
        tie_pct_id = (self.tie_resolved_by_id / denom) if denom else 0.0

        return {
            "uptime_seconds": round(uptime_s, 2),
            "total_requests": self.total_requests,
            "total_cache_hits": self.total_cache_hits,
            "cache_hit_rate": round(cache_hit_rate, 4),

            "latency_ms_avg": round(self.rolling.mean(self.rolling.lat_ms), 2),
            "latency_ms_p95": round(self.rolling.p95(self.rolling.lat_ms), 2),
            "candidates_avg": round(self.rolling.mean(self.rolling.candidates), 2),
            "candidates_p95": round(self.rolling.p95(self.rolling.candidates), 2),

            "tie_break": {
                "tie_groups_total": self.tie_groups_total,
                "resolved_by_token_pct": round(tie_pct_token, 4),
                "resolved_by_edit_pct": round(tie_pct_edit, 4),
                "resolved_by_id_pct": round(tie_pct_id, 4),
            },

            "top_queries": [{"query": q, "count": c} for q, c in top],
        }
