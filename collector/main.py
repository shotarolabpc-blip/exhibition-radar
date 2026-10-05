"""収集処理のエントリポイント（python -m collector.main）。

処理フロー（設計書8.1）：
 1. 設定読込、対象期間算出
 2. 既存 docs/data/events.json 読込
 3. overrides.yaml 読込
 4. 収集元ごとにパーサー実行（1収集元の失敗で全体を止めない）
 5. 候補ページ・イベントに対しキーワード一次判定
 6. 閾値以上のみ Gemini で構造化（上限到達時は残りを次回に持ち越す）
 7. 正規化（日付、会場、地域、URL、イベント名）
 8. 重複判定・差分判定・ステータス付与
 9. overrides 適用
10. 期限切れイベントのアーカイブ
11. events.json / events.csv / events_detail.csv / runs.json 出力
12. 終了コード：致命的エラー時のみ非0（全収集元失敗・件数急減）
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from collector.date_range import DateRange, compute_period
from collector.dedup import Merger, demote_previous
from collector.exporter import append_run, archive_events, load_events, publishable, read_json, write_events, write_json
from collector.fetcher import Fetcher
from collector.gemini_client import GeminiClient, GeminiUnavailable
from collector.keyword_filter import score_text
from collector.models import Event, compose_event_name, make_event_id
from collector.normalizer import (
    clean_text,
    normalize_categories,
    normalize_event_name,
    normalize_url,
    normalize_venue,
    parse_dates,
    split_event_name,
    url_key,
)
from collector.overrides import apply_overrides, fixes_by_id, is_excluded
from collector.region import resolve_region
from collector.settings import Config, load_config, load_overrides
from collector.sources import create_parser
from collector.sources.base import CandidatePage, RawEvent

log = logging.getLogger("collector")
JST = timezone(timedelta(hours=9))
ENRICH_BATCH = 15


class FatalError(Exception):
    """サイトを更新してはいけない致命的エラー。"""


# ---------------------------------------------------------------- Event 生成


def _year_of(start: date | None, parsed_year: int | None, name: str) -> str:
    if start:
        return str(start.year)
    if parsed_year:
        return str(parsed_year)
    m = re.search(r"(?<!\d)(20\d{2})(?!\d)", name)
    return m.group(1) if m else ""


def build_event(
    *,
    name: str,
    parent: str,
    sub: str,
    start_text: str,
    end_text: str,
    date_status: str,
    venue_raw: str,
    url: str,
    categories: Any,
    summary: str,
    source: str,
    source_type: str,
    confidence: int,
    reason: str,
    keywords: list[str],
    cfg: Config,
) -> Event | None:
    name = normalize_event_name(name)
    if not name:
        return None
    if not parent:
        parent, sub = split_event_name(name)
    parent, sub = normalize_event_name(parent), normalize_event_name(sub)
    ps = parse_dates(start_text)
    pe = parse_dates(end_text) if end_text else ps
    start = ps.start
    end = pe.end or pe.start or start
    if start and end and end < start:
        end = start
    if start is None:
        date_status = "unknown"
    elif date_status not in ("fixed", "tentative"):
        date_status = ps.status if ps.status != "unknown" else "fixed"
    venue = normalize_venue(venue_raw, cfg.venues)
    prefecture, region = resolve_region(venue, venue_raw, cfg.venues)
    year = _year_of(start, ps.year, name)
    return Event(
        id=make_event_id(parent, sub, year),
        event_name=compose_event_name(parent, sub),
        parent_event_name=parent,
        sub_event_name=sub,
        start_date=start.isoformat() if start else "",
        end_date=end.isoformat() if end else "",
        date_status=date_status,
        venue=venue,
        prefecture=prefecture,
        region=region,
        categories=normalize_categories(categories, cfg.categories),
        summary=clean_text(summary),
        url=normalize_url(url),
        source=source,
        source_type=source_type,
        keywords=keywords,
        confidence=max(0, min(100, int(confidence or 0))),
        reason=clean_text(reason),
        year=year,
    )


def event_from_gemini(d: dict[str, Any], page: CandidatePage, keywords: list[str], cfg: Config) -> Event | None:
    return build_event(
        name=str(d.get("event_name") or ""),
        parent=str(d.get("parent_event_name") or ""),
        sub=str(d.get("sub_event_name") or ""),
        start_text=str(d.get("start_date") or ""),
        end_text=str(d.get("end_date") or ""),
        date_status=str(d.get("date_status") or ""),
        venue_raw=str(d.get("venue") or page.venue_hint or ""),
        url=str(d.get("url") or "") or page.url,
        categories=d.get("categories") or [],
        summary=str(d.get("summary") or ""),
        source=page.source_name,
        source_type=page.source_type,
        confidence=int(d.get("confidence") or 0),
        reason=str(d.get("reason") or ""),
        keywords=keywords,
        cfg=cfg,
    )


def event_from_raw(raw: RawEvent, cfg: Config) -> Event | None:
    return build_event(
        name=raw.name,
        parent=raw.parent_event_name,
        sub=raw.sub_event_name,
        start_text=raw.start_date,
        end_text=raw.end_date,
        date_status=raw.date_status,
        venue_raw=raw.venue,
        url=raw.url,
        categories=raw.categories or f"{raw.name} {raw.description}",
        summary=raw.summary or raw.description,
        source=raw.source_name,
        source_type=raw.source_type,
        confidence=raw.confidence,
        reason=raw.reason,
        keywords=raw.keywords,
        cfg=cfg,
    )


def in_scope(e: Event, period: DateRange) -> bool:
    """今後の期間内、または日程未定の次回開催。過去回・期間より先は今回は扱わない。"""
    if not e.start_date:
        return True
    end = date.fromisoformat(e.end_date or e.start_date)
    start = date.fromisoformat(e.start_date)
    return end >= period.start and start <= period.end


# ---------------------------------------------------------------- 実行


class Collector:
    def __init__(self, cfg: Config, today: date, gemini: GeminiClient, fetcher: Fetcher, only: set[str] | None = None) -> None:
        self.cfg = cfg
        self.today = today
        self.period = compute_period(today, int(cfg.section("period").get("months_ahead", 5)))
        self.gemini = gemini
        self.fetcher = fetcher
        self.only = only
        self.judge = cfg.section("judge")
        self.threshold = int(self.judge.get("keyword_score_threshold", 40))
        self.errors: list[str] = []
        self.source_counts: dict[str, int] = {}
        self.sources_total = 0
        self.sources_failed = 0
        self.gemini_pending = 0

    # -------------------------------------------------- 収集
    def collect(self, context: dict[str, Any]) -> tuple[list[CandidatePage], list[tuple[RawEvent, Any]]]:
        pages: list[CandidatePage] = []
        raw_events: list[tuple[RawEvent, Any]] = []
        for source in self.cfg.sources:
            if not source.get("enabled", True) or (self.only and source["id"] not in self.only):
                continue
            self.sources_total += 1
            try:
                parser = create_parser(source, self.fetcher, context)
                res = parser.collect(self.period)
            except Exception as exc:  # 1収集元の失敗で全体を止めない
                log.exception("収集元 %s で例外", source["id"])
                self.errors.append(f"{source['id']}: {type(exc).__name__}: {exc}")
                self.sources_failed += 1
                self.source_counts[source["id"]] = 0
                continue
            count = len(res.pages) + len(res.events)
            self.source_counts[source["id"]] = count
            self.errors.extend(res.errors)
            if res.errors and count == 0:
                self.sources_failed += 1
            pages.extend(res.pages)
            raw_events.extend((e, parser) for e in res.events)
            log.info("%s: ページ %d件 / イベント %d件 / エラー %d件", source["id"], len(res.pages), len(res.events), len(res.errors))
        return pages, raw_events

    def check_zero_parse(self, previous_counts: dict[str, int]) -> None:
        """前回1件以上あった収集元が0件ならエラーとして記録する（サイレント失敗防止）。known_urls は差分のみのため対象外。"""
        for sid, count in self.source_counts.items():
            src = next((s for s in self.cfg.sources if s["id"] == sid), {})
            if src.get("type") == "known_urls":
                continue
            if count == 0 and previous_counts.get(sid, 0) > 0:
                self.errors.append(f"{sid}: パース0件（前回 {previous_counts[sid]}件）。サイト構造変更の可能性")

    # -------------------------------------------------- 構造化イベント
    def process_raw(self, raw_events: list[tuple[RawEvent, Any]]) -> list[Event]:
        kw_cfg = self.cfg.keywords
        kept: list[RawEvent] = []
        for raw, parser in raw_events:
            kr = score_text(raw.name, raw.description, kw_cfg)
            if kr.score < self.threshold:
                continue
            raw.keywords = kr.keywords
            if hasattr(parser, "resolve_url"):
                parser.resolve_url(raw)
            kept.append(raw)

        for i in range(0, len(kept), ENRICH_BATCH):
            batch = kept[i : i + ENRICH_BATCH]
            if not self.gemini.available:
                break
            try:
                enrich = self.gemini.enrich_events(batch, self.cfg.category_names)
            except GeminiUnavailable as exc:
                self.errors.append(f"gemini: {exc}")
                break
            for j, raw in enumerate(batch):
                info = enrich.get(j)
                if not info:
                    continue
                if info.get("relevant") is False:
                    raw.confidence = -1  # 除外マーク
                    continue
                raw.categories = info.get("categories") or []
                raw.summary = clean_text(info.get("summary") or "")
                raw.confidence = min(raw.confidence, int(info.get("confidence") or raw.confidence))
                raw.reason += "（Geminiで関連性を確認）"

        events = []
        for raw in kept:
            if raw.confidence < 0:
                continue
            e = event_from_raw(raw, self.cfg)
            if e and in_scope(e, self.period):
                events.append(e)
        return events

    # -------------------------------------------------- 候補ページ
    def process_pages(self, pages: list[CandidatePage], page_state: dict[str, dict[str, str]]) -> list[Event]:
        kw_cfg = self.cfg.keywords
        scored: list[tuple[CandidatePage, list[str]]] = []
        for page in pages:
            kr = score_text(page.title, page.text, kw_cfg)
            if not page.skip_keyword_filter and kr.score < self.threshold:
                self._mark_done(page, page_state)
                continue
            scored.append((page, kr.keywords))
        # 会場・主催者（既定priority=0→3扱い）＞ 過去回の既知URL（2）＞ 掲載中の既知URL（1）
        scored.sort(key=lambda pk: -(pk[0].priority or 3))

        events: list[Event] = []
        for page, keywords in scored:
            if not self.gemini.available:
                self.gemini_pending += 1
                continue
            try:
                items = self.gemini.extract_events(page, self.period, self.cfg.category_names)
            except GeminiUnavailable as exc:
                self.errors.append(f"gemini: {exc}（{page.url}）")
                self.gemini_pending += 1
                continue
            self._mark_done(page, page_state)
            for d in items:
                e = event_from_gemini(d, page, keywords, self.cfg)
                if e and in_scope(e, self.period):
                    events.append(e)
        return events

    @staticmethod
    def _mark_done(page: CandidatePage, page_state: dict[str, dict[str, str]]) -> None:
        if page.content_hash:
            for key in (page.url,):
                page_state.setdefault(key, {})["hash"] = page.content_hash


def _previous_source_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    for run in runs:
        if run.get("type") != "import" and run.get("source_counts"):
            return run["source_counts"]
    return {}


def run(
    cfg: Config,
    today: date,
    *,
    dry_run: bool = False,
    only: set[str] | None = None,
    use_gemini: bool = True,
    fetcher: Any = None,
    gemini: GeminiClient | None = None,
) -> dict[str, Any]:
    data_dir = cfg.docs_data_dir
    page_state_path = cfg.root_dir / "data" / "page_state.json"
    existing = load_events(data_dir / "events.json")
    prev_count = len(publishable(existing))
    runs = read_json(data_dir / "runs.json", [])
    overrides = load_overrides(cfg.root_dir / "data" / "overrides.yaml")
    page_state: dict[str, dict[str, str]] = read_json(page_state_path, {})

    if gemini is None:
        gemini_cfg = dict(cfg.section("gemini"))
        if not use_gemini:
            gemini_cfg["enabled"] = False
        gemini = GeminiClient(gemini_cfg)
    if gemini.disabled_reason:
        log.warning("Gemini 無効：%s（構造化サイトのHTML抽出のみ行う）", gemini.disabled_reason)
    for reason in gemini.skipped:
        log.info("LLM呼び出し先を使わない：%s", reason)
    fetch_cfg = cfg.section("fetch")
    if fetcher is None:
        fetcher = Fetcher(fetch_cfg, cfg.path(fetch_cfg.get("cache_dir", "data/cache")))
    collector = Collector(cfg, today, gemini, fetcher, only)

    live_keys = {url_key(e.url) for e in existing if e.url and e.status != "excluded"}
    context = {
        "max_pages_per_source": fetch_cfg.get("max_pages_per_source", 100),
        "max_input_chars": cfg.section("gemini").get("max_input_chars", 12000),
        "known_urls": cfg.known_urls,
        "page_state": page_state,
        "live_url_keys": live_keys,
    }
    pages, raw_events = collector.collect(context)
    collector.check_zero_parse(_previous_source_counts(runs))
    if collector.sources_total and collector.sources_failed == collector.sources_total:
        raise FatalError("全収集元が失敗したため更新しない：" + "; ".join(collector.errors[:10]))

    incoming = collector.process_raw(raw_events) + collector.process_pages(pages, page_state)
    incoming = [e for e in incoming if not is_excluded(e, overrides)]

    today_s = today.isoformat()
    demote_previous(existing)
    merger = Merger(existing, cfg.section("judge"), today_s, fixes_by_id(overrides))
    for e in incoming:
        merger.add(e)
    merged = apply_overrides(merger.result(), overrides, cfg.venues, cfg.categories, today_s)
    remaining = (
        archive_events(merged, today, int(cfg.section("period").get("archive_after_days", 30)), cfg.archive_dir) if not dry_run else merged
    )

    new_count = len(publishable(remaining))
    max_drop = float(cfg.section("output").get("max_drop_ratio", 0.5))
    if prev_count and new_count <= prev_count * (1 - max_drop):
        raise FatalError(f"掲載件数が {prev_count}→{new_count} に急減したため更新しない")

    pub = publishable(remaining)
    summary = {
        "run_at": datetime.now(JST).isoformat(timespec="seconds"),
        "type": "collect",
        "period": collector.period.to_dict(),
        "sources_total": collector.sources_total,
        "sources_failed": collector.sources_failed,
        "pages_fetched": fetcher.pages_fetched,
        "gemini_requests": gemini.requests_made,
        "llm_usage": gemini.usage,
        "gemini_pending": collector.gemini_pending,
        "new": sum(1 for e in pub if e.status == "new"),
        "updated": sum(1 for e in pub if e.status == "updated"),
        "needs_review": sum(1 for e in pub if e.status == "needs_review"),
        "total": new_count,
        "archived": len(merged) - len(remaining),
        "source_counts": collector.source_counts,
        "errors": collector.errors,
    }
    if not dry_run:
        write_events(remaining, data_dir)
        write_json(page_state_path, dict(sorted(page_state.items())))
        append_run(data_dir, summary, int(cfg.section("output").get("runs_keep", 100)))
    return summary


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="展示会情報を収集して docs/data を更新する")
    parser.add_argument("--dry-run", action="store_true", help="ファイルを書き込まない")
    parser.add_argument("--sources", help="実行する収集元IDをカンマ区切りで指定（省略時は全件）")
    parser.add_argument("--no-gemini", action="store_true", help="Geminiを使わない")
    parser.add_argument("--today", help="基準日 YYYY-MM-DD（テスト用）")
    args = parser.parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = load_config()
    today = date.fromisoformat(args.today) if args.today else datetime.now(JST).date()
    only = set(args.sources.split(",")) if args.sources else None
    try:
        summary = run(cfg, today, dry_run=args.dry_run, only=only, use_gemini=not args.no_gemini)
    except FatalError as exc:
        log.error("%s", exc)
        return 1
    for key in (
        "period",
        "sources_total",
        "sources_failed",
        "pages_fetched",
        "gemini_requests",
        "gemini_pending",
        "new",
        "updated",
        "needs_review",
        "total",
    ):
        log.info("%s: %s", key, summary[key])
    log.info("llm_usage: %s", summary["llm_usage"])
    for err in summary["errors"]:
        log.warning("error: %s", err)
    return 0


if __name__ == "__main__":
    sys.exit(main())
