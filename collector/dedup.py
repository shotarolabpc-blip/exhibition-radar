"""重複・差分判定とステータス付与（C-07）。

判定（設計書8.4を基本に、運用上のノイズを減らすため一部調整）：
- 同一（ID）：ID一致かつ同じ開催回 → 差分比較
- 同一（URL）：URL一致（normalizer.url_family：同じホスト＋同じファイル名）かつ開催年一致かつ名称類似度 ≥ fuzzy_review_threshold → 差分比較
  （総合展の構成展は同じURLを共有することがあるため名称でも確認する）
- 同一（名称）：名称類似度 ≥ fuzzy_duplicate_threshold かつ開始日一致かつ会場一致 → 差分比較
  ※設計書では「重複疑い→要確認」だが、会場HPと主催者HPで同じ回を拾うたびに要確認になるのを避けるため同一扱いにした
- 重複疑い：類似度 ≥ fuzzy_duplicate_threshold だが開始日が未定/不一致 → 新規＋要確認
- 要確認：類似度 fuzzy_review_threshold 〜 fuzzy_duplicate_threshold-1 → 新規＋要確認
  ※ただし双方に公式URLがあり別URLなら別イベントとして新規（同シリーズの構成展が毎回要確認になるのを避ける）
- 新規：上記に該当しない

更新判定の対象は 日付・会場・URL・概要。ただし概要は既存が空のときだけ埋める
（Gemini の要約は実行ごとに表現が揺れ、毎回「更新」になってしまうため）。
値が食い違う場合は収集元の優先度（主催者公式HP ＞ 展示会場HP ＞ J-messe ＞ 既存リスト取込）が同じか高い方を採用する。
URLだけは、既存が空の場合か、主催者公式ページ（organizer / known_url）から取れた場合に限って差し替える。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from collector.models import Event, edition_id, is_same_edition
from collector.normalizer import match_key, url_family
from collector.sources.base import SOURCE_PRIORITY

FIELD_LABELS = {
    "start_date": "開始日",
    "end_date": "終了日",
    "date_status": "日程状態",
    "venue": "会場",
    "url": "URL",
    "summary": "概要",
}


def name_key(name: str) -> str:
    """類似度比較用の名称キー（回数・西暦・記号・空白を除く）。"""
    key = match_key(name)
    key = re.sub(r"第\d+回", "", key)
    key = re.sub(r"(?<!\d)(20\d{2}|'\d{2}|’\d{2})(?!\d)", "", key)
    return re.sub(r"[\-‐―－–—・/／|｜:：()（）\[\]［］【】「」『』\"'.,、。&＆!！?？~〜]+", "", key)


def similarity(a: str, b: str) -> float:
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return 0.0
    return fuzz.ratio(ka, kb)


def priority(event: Event) -> int:
    return SOURCE_PRIORITY.get(event.source_type, 0)


@dataclass
class MergeStats:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    needs_review: int = 0
    notes: list[str] = field(default_factory=list)


def demote_previous(events: list[Event]) -> None:
    """前回の new/updated を unchanged に戻す（「今回新規・更新」を直近実行分だけにする）。"""
    for e in events:
        if e.status in ("new", "updated"):
            e.status = "unchanged"


class Merger:
    def __init__(self, existing: list[Event], judge: dict[str, Any], today: str, fixes: dict[str, dict[str, Any]] | None = None) -> None:
        self.events: dict[str, Event] = {e.id: e for e in existing}
        self.dup_threshold = float(judge.get("fuzzy_duplicate_threshold", 90))
        self.review_threshold = float(judge.get("fuzzy_review_threshold", 75))
        self.confidence_threshold = int(judge.get("confidence_review_threshold", 70))
        self.today = today
        self.fixes = fixes or {}
        self.stats = MergeStats()
        self._touched: set[str] = set()

    # ------------------------------------------------------------ 照合
    def _by_url(self, inc: Event) -> Event | None:
        key = url_family(inc.url)
        if not key or not inc.year:
            return None
        for e in self.events.values():
            if e.year == inc.year and url_family(e.url) == key and similarity(e.event_name, inc.event_name) >= self.review_threshold:
                return e
        return None

    def _best_fuzzy(self, inc: Event) -> tuple[Event | None, float]:
        best: Event | None = None
        best_score = 0.0
        # 除外済み（excluded）とも照合する。再検出で新規として復活させないため
        for e in self.events.values():
            if inc.year and e.year and e.year != inc.year:
                continue
            score = similarity(e.event_name, inc.event_name)
            if score > best_score:
                best, best_score = e, score
        return best, best_score

    def find_match(self, inc: Event) -> tuple[Event | None, str]:
        """(既存イベント, 判定) を返す。判定：same / duplicate / similar / new"""
        same_id = self.events.get(inc.id)
        if same_id is not None:
            if is_same_edition(same_id, inc):
                return same_id, "same"
            inc.id = edition_id(inc)
            same_id = self.events.get(inc.id)
            if same_id is not None and is_same_edition(same_id, inc):
                return same_id, "same"

        by_url = self._by_url(inc)
        if by_url is not None and is_same_edition(by_url, inc):
            return by_url, "same"

        best, score = self._best_fuzzy(inc)
        if best is None:
            return None, "new"
        if score >= self.dup_threshold:
            same_start = bool(best.start_date) and best.start_date == inc.start_date
            same_venue = not best.venue or not inc.venue or best.venue == inc.venue
            if same_start and same_venue:
                return best, "same"
            return best, "duplicate"
        if score >= self.review_threshold:
            if inc.url and best.url and url_family(inc.url) != url_family(best.url):
                return None, "new"  # 公式URLが別々なら別イベント（同シリーズの構成展など）
            return best, "similar"
        return None, "new"

    # ------------------------------------------------------------ 反映
    def add(self, inc: Event) -> Event:
        match, verdict = self.find_match(inc)
        if verdict == "same" and match is not None:
            self._update(match, inc)
            return match
        self._insert(inc, verdict, match)
        return inc

    def _insert(self, inc: Event, verdict: str, match: Event | None) -> None:
        reasons: list[str] = []
        if verdict == "duplicate" and match is not None:
            reasons.append(f"重複疑い：{match.id}「{match.event_name}」")
        elif verdict == "similar" and match is not None:
            reasons.append(f"類似イベントあり：{match.id}「{match.event_name}」")
        if inc.confidence < self.confidence_threshold:
            reasons.append(f"信頼度{inc.confidence}")
        if not inc.year:
            reasons.append("開催年が不明")
        inc.status = "needs_review" if reasons else "new"
        if reasons:
            inc.reason = (inc.reason + "／" if inc.reason else "") + "要確認：" + "、".join(reasons)
        inc.first_seen = inc.last_updated = inc.last_checked = self.today
        inc.history = [{"date": self.today, "change": f"新規検出（{inc.source}）"}]
        if inc.id in self.events:  # 別の回とIDが衝突
            inc.id = edition_id(inc)
        self.events[inc.id] = inc
        self._touched.add(inc.id)
        if inc.status == "new":
            self.stats.new += 1
        else:
            self.stats.needs_review += 1

    def _update(self, ex: Event, inc: Event) -> None:
        fixed_fields = set(self.fixes.get(ex.id, {}))
        inc_pri, ex_pri = priority(inc), priority(ex)
        changes: list[str] = []
        date_confirmed = False

        for name in ("start_date", "end_date", "date_status", "venue", "url", "summary"):
            if name in fixed_fields:
                continue
            new, old = getattr(inc, name), getattr(ex, name)
            if not new or new == old:
                continue
            if name == "summary" and old:
                continue
            if name == "date_status":
                if new == "unknown" or (old == "fixed" and inc_pri < ex_pri):
                    continue
            elif old and inc_pri < ex_pri:
                continue
            if name == "url" and old and (inc_pri <= ex_pri or inc_pri < SOURCE_PRIORITY["organizer"]):
                continue  # URLは主催者公式ページから取れた場合のみ差し替える（会場HPの案内ページURLで揺れないように）
            if name == "date_status" and old == "unknown" and new in ("fixed", "tentative"):
                date_confirmed = True
            setattr(ex, name, new)
            if name != "date_status":
                changes.append(f"{FIELD_LABELS[name]}：{old or '（なし）'}→{new}" if name != "summary" else "概要を追加")

        if "venue" in [c.split("：")[0] for c in changes] or (not ex.region and inc.region):
            ex.prefecture, ex.region = inc.prefecture or ex.prefecture, inc.region or ex.region
        if "categories" not in fixed_fields and inc.categories and (not ex.categories or ex.categories == ["その他IT"]):
            ex.categories = inc.categories
        ex.keywords = sorted(set(ex.keywords) | set(inc.keywords))
        ex.confidence = max(ex.confidence, inc.confidence)
        if not ex.year and inc.year:
            ex.year = inc.year
        if inc_pri >= ex_pri:
            ex.source, ex.source_type = inc.source, inc.source_type
            if inc.reason:
                ex.reason = inc.reason
        ex.last_checked = self.today

        if date_confirmed:
            changes.insert(0, "日程確定")
        if changes and ex.id not in self._touched:
            ex.last_updated = self.today
            ex.add_history(self.today, "更新：" + "、".join(changes))
            if ex.status in ("unchanged", "new"):
                ex.status = "updated"
                self.stats.updated += 1
        elif changes:
            ex.add_history(self.today, "更新：" + "、".join(changes))
        self._touched.add(ex.id)

    def result(self) -> list[Event]:
        return list(self.events.values())
