#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Passage search: split fetched pages into passages and keep only the ones that
answer the query, instead of handing the LLM whole pages.

Keywords go first (BM25, cheap and precise). The embedder only runs when the
keywords leave too many candidates to choose from, or match nothing at all
(paraphrased questions). On its own, MobileBERT ranks passages too loosely.
"""

import math, re
from collections import Counter
from typing import Callable, Dict, List, Tuple

import numpy as np

_WORD = re.compile(r"[a-z0-9][a-z0-9+#_.-]*[a-z0-9+#]|[a-z0-9]")
_STOP = set("""a an and are as at be by can do does for from has have how i in is it its
of on or that the their this to was what when where which who why will with you your""".split())

PASSAGE_CHARS = 600
MAX_PASSAGE_CHARS = 1200
# shorter bits (bylines, dates) keep merging with what follows: on their own,
# BM25's length normalisation lets a lone heading-matching date win
MIN_PASSAGE_CHARS = 200
MIN_KEEP_CHARS = 60


def tokens(text: str) -> List[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP]


def build_passages(url: str, blocks: List[Tuple[str, str]]) -> List[Dict]:
    """Merge small blocks under the same heading up to ~600 chars, and split huge
    ones on sentences, so passages are comparable in size."""
    passages = []

    def emit(heading, text):
        if len(text) < MIN_KEEP_CHARS:
            return
        if len(text) <= MAX_PASSAGE_CHARS:
            passages.append({"url": url, "heading": heading, "text": text})
            return
        buf = ""
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if buf and len(buf) + len(sentence) > PASSAGE_CHARS:
                passages.append({"url": url, "heading": heading, "text": buf.strip()})
                buf = ""
            buf += sentence + " "
        if buf.strip():
            passages.append({"url": url, "heading": heading, "text": buf.strip()[:MAX_PASSAGE_CHARS]})

    cur_heading, buf = "", ""
    for heading, text in blocks:
        full = len(buf) + len(text) > PASSAGE_CHARS
        if buf and len(buf) >= MIN_PASSAGE_CHARS and (heading != cur_heading or full):
            emit(cur_heading, buf.strip())
            buf = ""
        if not buf:
            cur_heading = heading
        buf += text + " "
    if buf.strip():
        emit(cur_heading, buf.strip())

    # the same snippet often repeats on a page (summaries, "related" boxes)
    seen, unique = set(), []
    for p in passages:
        key = " ".join(p["text"].lower().split())[:200]
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def keyword_scores(query: str, keywords: List[str], passages: List[Dict]) -> List[float]:
    """BM25 over the passages for the query terms plus the caller's keywords, with
    a bonus when a multi-word keyword appears verbatim."""
    terms = Counter(tokens(query))
    for k in keywords:
        for t in tokens(k):
            terms[t] += 2  # the LLM's keywords say more about intent than filler words
    docs = [tokens(f"{p['heading']} {p['text']}") for p in passages]
    n = len(docs)
    if not n or not terms:
        return [0.0] * n
    avg_len = sum(len(d) for d in docs) / n
    df = Counter(t for d in docs for t in set(d))
    k1, b = 1.5, 0.75
    phrases = [k.lower() for k in keywords if " " in k.strip()]
    scores = []
    for d, p in zip(docs, passages):
        tf = Counter(d)
        s = 0.0
        for t, weight in terms.items():
            if tf[t]:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += weight * idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg_len))
        low = p["text"].lower()
        s += sum(3.0 for ph in phrases if ph in low)
        scores.append(s)
    return scores


def select(query: str, passages: List[Dict], kscores: List[float], max_passages: int,
           embed: Callable[[List[str]], np.ndarray]) -> Tuple[List[Dict], str]:
    """Pick the best passages. Returns them with a score, plus which tier decided."""
    hits = sorted((i for i, s in enumerate(kscores) if s > 0), key=lambda i: -kscores[i])

    if hits and len(hits) <= max_passages:
        return [dict(passages[i], score=round(kscores[i], 3)) for i in hits], "keywords"

    if hits:
        # too many keyword hits: let the embedder break ties among the best of them
        cand = hits[: min(48, max_passages * 4)]
        tier = "keywords+semantic"
    else:
        # nothing matched literally, probably a paraphrase: semantic over everything
        cand = list(range(min(len(passages), 96)))
        tier = "semantic"
    if not cand:
        return [], tier

    vecs = embed([query] + [f"{passages[i]['heading']} {passages[i]['text']}" for i in cand])
    sem = vecs[1:] @ vecs[0]
    if tier == "semantic":
        combined = sem
    else:
        k = np.array([kscores[i] for i in cand])
        norm = lambda x: (x - x.min()) / (x.max() - x.min() + 1e-9)
        combined = 0.5 * norm(k) + 0.5 * norm(sem)
    order = np.argsort(-combined)[:max_passages]
    return [dict(passages[cand[j]], score=round(float(combined[j]), 3)) for j in order], tier
