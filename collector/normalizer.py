"""日付・会場名・URL・イベント名・カテゴリの正規化（C-06）。

方針：日付は推測で補完しない。読み取れなければ None を返す。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# ---------------------------------------------------------------- テキスト

_SPACE_RE = re.compile(r"[\s 　​﻿]+")


def clean_text(text: Any) -> str:
    """制御文字・NBSP・全角空白・連続空白を半角空白1つにまとめる。"""
    if text is None:
        return ""
    return _SPACE_RE.sub(" ", str(text)).strip()


def nfkc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "")


def match_key(text: str) -> str:
    """比較用キー（NFKC・小文字・空白除去）。"""
    return re.sub(r"\s+", "", nfkc(text).lower())


def normalize_event_name(name: Any) -> str:
    return clean_text(name)


def split_event_name(name: str) -> tuple[str, str]:
    """`総合展名 - 構成展名` を分割する。区切りが無ければ (name, "")。"""
    name = normalize_event_name(name)
    if " - " in name:
        parent, sub = name.split(" - ", 1)
        return parent.strip(), sub.strip()
    return name, ""


# ---------------------------------------------------------------- 日付

_ERA_RE = re.compile(r"令和\s*(\d{1,2}|元)\s*年")
_WEEKDAY_RE = re.compile(
    r"[(（]\s*(?:[月火水木金土日祝休・･/,、\s]|mon|tue|wed|thu|fri|sat|sun|\.)+\s*[)）]",
    re.IGNORECASE,
)
_FULL_DATE_RE = re.compile(r"(\d{4})\s*[年/.\-]\s*(\d{1,2})\s*[月/.\-]\s*(\d{1,2})\s*日?")
_MD_DATE_RE = re.compile(r"(?<!\d)(\d{1,2})\s*(?:月\s*(\d{1,2})\s*日?|/\s*(\d{1,2})(?![\d/]))")
_YEAR_MONTH_RE = re.compile(r"(\d{4})\s*(?:年\s*(\d{1,2})\s*月|[/.\-]\s*(\d{1,2})(?![\d/.\-]))")
_RANGE_SEP = r"\s*(?:~|〜|～|-|‐|–|—|―|ー|－|から|至)\s*"
_END_RE = re.compile(_RANGE_SEP + r"(?:(?P<y>\d{4})\s*[年/.\-]\s*)?(?:(?P<m>\d{1,2})\s*[月/.\-]\s*)?(?P<d>\d{1,2})\s*日?(?![\d/.\-月])")
_TENTATIVE_RE = re.compile(r"予定|仮|調整中|TBD|tbd")
_EXCEL_EPOCH = date(1899, 12, 30)


@dataclass
class ParsedDates:
    start: date | None = None
    end: date | None = None
    status: str = "unknown"  # fixed / tentative / unknown
    year: int | None = None  # 開催年（月だけ分かる場合も入る）


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _prepare(text: str) -> str:
    t = nfkc(clean_text(text))
    t = _ERA_RE.sub(lambda m: f"{2018 + (1 if m.group(1) == '元' else int(m.group(1)))}年", t)
    t = _WEEKDAY_RE.sub("", t)
    return t


def excel_serial_to_date(value: float) -> date | None:
    if 20000 <= value <= 80000:
        return _EXCEL_EPOCH + timedelta(days=int(value))
    return None


def parse_dates(text: Any, default_year: int | None = None) -> ParsedDates:
    """会期文字列から開始日・終了日を取り出す。

    対応：ISO・スラッシュ・ドット・和暦（令和）・全角・曜日付き・`～`範囲・終了側の年月省略・
    Excelシリアル値。年省略の日付は default_year が与えられた場合のみ解釈する（推測しない）。
    """
    if isinstance(text, date):
        return ParsedDates(text, text, "fixed", text.year)
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        d = excel_serial_to_date(float(text))
        return ParsedDates(d, d, "fixed", d.year) if d else ParsedDates()
    raw = clean_text(text)
    if not raw or raw in {"-", "－", "未定", "TBD"}:
        return ParsedDates()
    if re.fullmatch(r"\d{5}(\.\d+)?", raw):
        d = excel_serial_to_date(float(raw))
        return ParsedDates(d, d, "fixed", d.year) if d else ParsedDates()

    t = _prepare(raw)
    tentative = bool(_TENTATIVE_RE.search(t))

    start: date | None = None
    pos = 0
    m = _FULL_DATE_RE.search(t)
    if m:
        start = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        pos = m.end()
    elif default_year is not None:
        m2 = _MD_DATE_RE.search(t)
        if m2:
            day = m2.group(2) or m2.group(3)
            start = _safe_date(default_year, int(m2.group(1)), int(day))
            pos = m2.end()

    if start is None:
        ym = _YEAR_MONTH_RE.search(t)
        if ym:
            month = int(ym.group(2) or ym.group(3))
            if 1 <= month <= 12:
                return ParsedDates(None, None, "unknown", int(ym.group(1)))
        y = re.search(r"(20\d{2})\s*年", t)
        return ParsedDates(None, None, "unknown", int(y.group(1)) if y else None)

    end = start
    em = _END_RE.match(t, pos)
    if em:
        y = int(em.group("y")) if em.group("y") else start.year
        mo = int(em.group("m")) if em.group("m") else start.month
        candidate = _safe_date(y, mo, int(em.group("d")))
        if candidate and candidate < start and not em.group("y"):
            # 年跨ぎ（12/30～1/2）
            candidate = _safe_date(y + 1, mo, int(em.group("d")))
        if candidate and candidate >= start:
            end = candidate
    return ParsedDates(start, end, "tentative" if tentative else "fixed", start.year)


def parse_single_date(text: Any) -> date | None:
    """1つの日付だけを表すセル（開始日・終了日の列）を解釈する。"""
    return parse_dates(text).start


def format_date_slash(iso: str) -> str:
    """`2026-10-21` → `2026/10/21`（空ならそのまま空）。"""
    return iso.replace("-", "/") if iso else ""


# ---------------------------------------------------------------- URL

_URL_RE = re.compile(r"https?://[^\s<>\"'（）「」\[\]]+", re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)")
_TRACKING_PARAMS = re.compile(r"^(utm_|fbclid$|gclid$|_ga$|mc_)", re.IGNORECASE)


def normalize_url(raw: Any) -> str:
    """URLを取り出して正規化する。URLが含まれなければ空文字。

    Markdownリンク `[text](url)` にも対応する。フラグメントとトラッキング用クエリを除去する。
    """
    text = clean_text(raw)
    if not text:
        return ""
    md = _MD_LINK_RE.search(text)
    m = md.group(1) if md else (_URL_RE.search(text).group(0) if _URL_RE.search(text) else "")
    if not m:
        return ""
    m = m.rstrip(".,、。)）」】")
    parts = urlsplit(m)
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not _TRACKING_PARAMS.match(k)])
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def url_key(url: str) -> str:
    """URL同一判定用キー（スキーム・www・末尾スラッシュ・index.html を無視）。"""
    if not url:
        return ""
    parts = urlsplit(url.lower())
    host = parts.netloc.removeprefix("www.")
    path = re.sub(r"/(index\.(html?|php))?$", "", parts.path)
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


# ---------------------------------------------------------------- 会場


def _venue_entries(venues_cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """(比較キー, 正規化名) を長いキー順に並べたもの。"""
    entries: list[tuple[str, str]] = []
    for v in venues_cfg.get("venues", []) or []:
        for alias in [v["name"], *(v.get("aliases") or [])]:
            key = match_key(alias)
            if key:
                entries.append((key, v["name"]))
    entries.sort(key=lambda e: len(e[0]), reverse=True)
    return entries


def normalize_venue(raw: Any, venues_cfg: dict[str, Any]) -> str:
    """会場辞書の名前/別名が含まれていれば正規化名を返す。無ければ整形した元の文字列。"""
    text = clean_text(raw)
    text = re.sub(r"^[（(]仮[）)]\s*", "", text)
    if not text:
        return ""
    key = match_key(text)
    for alias_key, name in _venue_entries(venues_cfg):
        if alias_key in key:
            return name
    return text


# ---------------------------------------------------------------- カテゴリ


def _alias_hit(alias: str, text_key: str) -> bool:
    a = match_key(alias)
    if re.fullmatch(r"[a-z0-9]{1,3}", a):
        return re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", text_key) is not None
    return a in text_key


def normalize_categories(raw: Any, categories_cfg: dict[str, Any]) -> list[str]:
    """自由記述のカテゴリを固定カテゴリ（categories.yaml）に割り当てる。

    該当なしの場合は fallback（その他IT）。結果は categories.yaml の並び順。
    """
    text = " ".join(clean_text(x) for x in raw) if isinstance(raw, (list, tuple)) else clean_text(raw)
    fallback = categories_cfg.get("fallback", "その他IT")
    if not text:
        return [fallback]
    text_key = match_key(text)
    result: list[str] = []
    for cat in categories_cfg.get("categories", []) or []:
        name = cat["name"]
        if name == fallback:
            continue
        if match_key(name) in text_key or any(_alias_hit(a, text_key) for a in cat.get("aliases") or []):
            result.append(name)
    return result or [fallback]
