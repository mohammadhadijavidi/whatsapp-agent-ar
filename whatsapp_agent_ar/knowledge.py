"""Knowledge-base retrieval over the business FAQ (BM25, no API key needed)."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from .arabic import tokens
from .business import FAQ


@dataclass
class Hit:
    faq: FAQ
    score: float
    confidence: float  # 0..1, share of query tokens covered by the entry


class KnowledgeBase:
    """BM25 over each FAQ entry (questions weighted x2 + answer)."""

    def __init__(self, faq: list[FAQ], k1: float = 1.4, b: float = 0.6):
        self.faq = faq
        self.k1, self.b = k1, b
        self.docs: list[Counter] = []
        for f in faq:
            toks = []
            for q in f.questions:
                toks += tokens(q) * 2
            toks += tokens(f.answer) + tokens(f.answer_en)
            self.docs.append(Counter(toks))
        self.avgdl = sum(sum(d.values()) for d in self.docs) / max(1, len(self.docs))
        df: Counter = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def search(self, query: str, k: int = 3) -> list[Hit]:
        q = list(dict.fromkeys(tokens(query)))
        if not q:
            return []
        hits = []
        for f, d in zip(self.faq, self.docs):
            dl = sum(d.values())
            score = 0.0
            covered = 0
            for t in q:
                tf = d.get(t, 0)
                if not tf:
                    continue
                covered += 1
                score += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if score > 0:
                hits.append(Hit(f, score, covered / len(q)))
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def best(self, query: str, min_score: float = 1.0, min_confidence: float = 0.34) -> Hit | None:
        """Best entry if it is a confident match, else None (so we never guess)."""
        hits = self.search(query, k=1)
        if hits and hits[0].score >= min_score and hits[0].confidence >= min_confidence:
            return hits[0]
        return None
