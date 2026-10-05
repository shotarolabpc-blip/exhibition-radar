"""キーワード一次判定（C-03）。config/keywords.yaml の重みで関連性スコア（0〜100）を出す。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from collector.normalizer import nfkc


@dataclass
class KeywordResult:
    score: int
    keywords: list[str] = field(default_factory=list)


def _contains(term: str, text: str) -> bool:
    t = nfkc(term).lower()
    if t.isascii() and len(t) <= 3:
        # "AI" "IT" "5G" などの短い英数字は単語境界で判定（"MAIL" 等の誤検出防止）
        return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text) is not None
    return t in text


def score_text(title: str, body: str, cfg: dict[str, Any]) -> KeywordResult:
    title_n = nfkc(title or "").lower()
    body_n = nfkc(body or "").lower()
    multiplier = float(cfg.get("title_multiplier", 2))

    total = 0.0
    found: list[str] = []
    for term, weight in (cfg.get("weights") or {}).items():
        if _contains(term, title_n):
            total += weight * multiplier
            found.append(term)
        elif _contains(term, body_n):
            total += weight
            found.append(term)
    for term, weight in (cfg.get("negative") or {}).items():
        if _contains(term, title_n) or _contains(term, body_n):
            total += weight

    event_terms = cfg.get("event_terms") or []
    if event_terms and not any(_contains(t, title_n) or _contains(t, body_n) for t in event_terms):
        total /= 2
    return KeywordResult(score=max(0, min(100, round(total))), keywords=found)
