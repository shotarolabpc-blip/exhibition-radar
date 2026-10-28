"""日程未定イベントの「予想時期（参考）」。

前回（過去）の開催時期から、次回の時期を月と上旬・中旬・下旬の粒度で推定する。
開始日・終了日の欄には入れず、estimate / estimate_basis に別項目として保存する（日付は推測で補完しない）。

推定する条件（誤った予想を出さないため、厳しめにしている）：
- 日程未定のイベントであること
- 名称がほぼ同じ（類似度が duplicate 閾値以上）の過去の開催が見つかること。
  名称で見つからない場合は、構成展名が同じで会場も両方にあって同じ場合に限る
- 今後（または開催中）の同名の確定済みイベントが無いこと（あれば、そちらが次回であり、この行は重複の可能性が高い）
- 前回の開始日が2年以内であること（古い開催からの推定は当てにならない）
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from rapidfuzz import fuzz

from collector.dedup import MIN_CORE_LEN, core_key, similarity
from collector.models import Event

MAX_AGE_DAYS = 730


def _shift_year(d: date, years: int) -> date:
    year = d.year + years
    day = min(d.day, calendar.monthrange(year, d.month)[1])
    return date(year, d.month, day)


def _third(day: int) -> str:
    return "上旬" if day <= 10 else "中旬" if day <= 20 else "下旬"


def _venue_same(a: Event, b: Event) -> bool:
    return bool(a.venue) and a.venue == b.venue


def _match(past: Event, target: Event, threshold: float) -> int:
    """2=名称がほぼ同じ、1=構成展名と会場が同じ、0=別物。会場が両方にあって違う場合は別の開催（東京展と大阪展など）"""
    if past.venue and target.venue and past.venue != target.venue:
        return 0
    if similarity(past.event_name, target.event_name) >= threshold:
        return 2
    ka, kb = core_key(past), core_key(target)
    if min(len(ka), len(kb)) >= MIN_CORE_LEN and fuzz.ratio(ka, kb) >= threshold and _venue_same(past, target):
        return 1
    return 0


def estimate_for(target: Event, pool: list[Event], today: date, threshold: float) -> tuple[str, str]:
    """(予想時期, 根拠) を返す。推定できなければ ("", "")。"""
    today_s = today.isoformat()
    oldest = (today - timedelta(days=MAX_AGE_DAYS)).isoformat()
    past: list[tuple[int, Event]] = []
    for c in pool:
        if c.id == target.id or not c.start_date:
            continue
        level = _match(c, target, threshold)
        if not level:
            continue
        if (c.end_date or c.start_date) >= today_s:
            return "", ""  # 今後の同名イベントがある：そちらが次回
        if c.start_date >= oldest:
            past.append((level, c))
    if not past:
        return "", ""
    level = max(lv for lv, _ in past)
    basis = max((c for lv, c in past if lv == level), key=lambda c: c.start_date)

    start = date.fromisoformat(basis.start_date)
    years = 1
    while _shift_year(start, years) < today:
        years += 1
    expected = _shift_year(start, years)
    end = basis.end_date or basis.start_date
    period = basis.start_date.replace("-", "/") + ("" if end == basis.start_date else "〜" + end.replace("-", "/"))
    return (
        f"{expected.year}年{expected.month}月{_third(expected.day)}ごろ",
        f"前回（{period}）の同じ時期から推定した参考値です。日程は公式発表で確認してください",
    )


def fill_estimates(events: list[Event], archived: list[Event], today: date, judge: dict[str, Any]) -> int:
    """日程未定のイベントに予想時期を付ける（付け直す）。付いた件数を返す。"""
    threshold = float(judge.get("fuzzy_duplicate_threshold", 90))
    pool = [e for e in [*events, *archived] if e.status != "excluded"]
    count = 0
    for e in events:
        e.estimate = e.estimate_basis = ""
        if e.start_date or e.status == "excluded":
            continue
        e.estimate, e.estimate_basis = estimate_for(e, pool, today, threshold)
        count += bool(e.estimate)
    return count
