"""Gemini API による構造化（C-04）。

- APIキー・モデル名は環境変数（settings.yaml の gemini.api_key_env / model_env で名前を指定）
- 1回の実行あたりのリクエスト数を max_requests_per_run で制限。上限到達後は呼ばない
- 構造化出力（JSONスキーマ指定）を使い、JSONの解析に失敗したら1回だけ再試行
- レート制限（429）は指数バックオフ。続く場合は「枠切れ」とみなし以降は呼ばない
- 送信するのは公開Webページの本文とURLのみ。APIキーはログに出さない
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from typing import Any

from collector.date_range import DateRange
from collector.sources.base import CandidatePage, RawEvent

log = logging.getLogger(__name__)

EXTRACT_PROMPT = """あなたは日本国内の展示会情報を整理する担当者です。
以下の公開Webページから、IT・無線・AI・DX・IoT・セキュリティ・ロボット・ドローン・スマートシティに関連する展示会を抽出してください。

条件：
- 日本国内開催のみ
- 対象期間：{period_from} ～ {period_to}（日程未定の次回開催も含める）
- 総合展と構成展がある場合は構成展ごとに分解し、event_nameは「総合展名 - 構成展名」
- 構成展がない場合はevent_nameにイベント名のみ
- 不明な項目は空文字。日付を推測しない
- 過年度の開催情報は除外
- categoriesは次から選択：{category_list}
- summaryは150〜250字の日本語
- 出力はJSON配列のみ
{venue_note}
項目：event_name, parent_event_name, sub_event_name, start_date(YYYY-MM-DD), end_date(YYYY-MM-DD), date_status(fixed/tentative/unknown), venue, categories, summary, url, confidence(0-100), reason

ページURL：{url}
ページ本文：
{text}
"""

ENRICH_PROMPT = """あなたは日本国内の展示会情報を整理する担当者です。
以下は展示会場の公式サイトに掲載されたイベント一覧です。各イベントについて判定してください。

- relevant：IT・無線・AI・DX・IoT・セキュリティ・ロボット・ドローン・スマートシティに関連する展示会なら true
- categories：次から選択（複数可）：{category_list}
- summary：150〜250字の日本語の概要。名称と説明文に書かれた内容だけを使い、書かれていない事実（出展社数・来場者数等）を作らない。情報が少なければ短くてよい
- confidence：関連性判定の確信度（0-100）
- 出力は index を含むJSON配列のみ

イベント一覧（JSON）：
{events_json}
"""

_EVENT_PROPS = {
    "event_name": {"type": "STRING"},
    "parent_event_name": {"type": "STRING"},
    "sub_event_name": {"type": "STRING"},
    "start_date": {"type": "STRING"},
    "end_date": {"type": "STRING"},
    "date_status": {"type": "STRING", "enum": ["fixed", "tentative", "unknown"]},
    "venue": {"type": "STRING"},
    "categories": {"type": "ARRAY", "items": {"type": "STRING"}},
    "summary": {"type": "STRING"},
    "url": {"type": "STRING"},
    "confidence": {"type": "INTEGER"},
    "reason": {"type": "STRING"},
}
EXTRACT_SCHEMA = {"type": "ARRAY", "items": {"type": "OBJECT", "properties": _EVENT_PROPS, "required": ["event_name"]}}
ENRICH_SCHEMA = {
    "type": "ARRAY",
    "items": {
        "type": "OBJECT",
        "properties": {
            "index": {"type": "INTEGER"},
            "relevant": {"type": "BOOLEAN"},
            "categories": {"type": "ARRAY", "items": {"type": "STRING"}},
            "summary": {"type": "STRING"},
            "confidence": {"type": "INTEGER"},
        },
        "required": ["index", "relevant"],
    },
}


class RateLimitError(Exception):
    """429（レート制限・無料枠超過）。"""


class GeminiUnavailable(Exception):
    """上限到達・枠切れ・無効化などで呼び出せない。"""


Transport = Callable[[str, dict[str, Any]], str]


class GeminiClient:
    def __init__(self, cfg: dict[str, Any], transport: Transport | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self.max_requests = int(cfg.get("max_requests_per_run", 150))
        self.sleep_sec = float(cfg.get("sleep_sec", 5))
        self.max_input_chars = int(cfg.get("max_input_chars", 12000))
        self.model = os.environ.get(cfg.get("model_env", "GEMINI_MODEL"), "")
        api_key = os.environ.get(cfg.get("api_key_env", "GEMINI_API_KEY"), "")
        self.requests_made = 0
        self.exhausted = False
        self.disabled_reason = ""
        self._sleep = sleep
        self._last_call = 0.0
        if transport is not None:
            self._transport = transport
        elif not cfg.get("enabled", True):
            self.disabled_reason = "settings.yaml で無効化"
        elif not api_key or not self.model:
            self.disabled_reason = "GEMINI_API_KEY / GEMINI_MODEL が未設定"
        else:
            self._transport = self._make_transport(api_key, self.model)

    @property
    def available(self) -> bool:
        return not self.disabled_reason and not self.exhausted and self.requests_made < self.max_requests

    @staticmethod
    def _make_transport(api_key: str, model: str) -> Transport:
        from google import genai
        from google.genai import errors, types

        client = genai.Client(api_key=api_key)

        def call(prompt: str, schema: dict[str, Any]) -> str:
            try:
                res = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=schema,
                        temperature=0.1,
                    ),
                )
            except errors.ClientError as exc:
                if exc.code == 429:
                    raise RateLimitError(str(exc.code)) from None
                raise
            return res.text or ""

        return call

    def _call(self, prompt: str, schema: dict[str, Any]) -> Any:
        """JSONを返す。JSON不正は1回だけ再試行。429は指数バックオフ（3回）後に枠切れ扱い。"""
        if not self.available:
            raise GeminiUnavailable(self.disabled_reason or ("枠切れ" if self.exhausted else "1回あたりの上限に到達"))
        parse_attempts = 0
        backoff = 0
        while True:
            if not self.available:
                raise GeminiUnavailable("1回あたりの上限に到達")
            wait = self.sleep_sec - (time.monotonic() - self._last_call)
            if self._last_call and wait > 0:
                self._sleep(wait)
            self._last_call = time.monotonic()
            self.requests_made += 1
            try:
                raw = self._transport(prompt, schema)
            except RateLimitError:
                if backoff >= 3:
                    self.exhausted = True
                    raise GeminiUnavailable("レート制限が続くため枠切れと判断") from None
                self._sleep(10 * 2**backoff)
                backoff += 1
                continue
            except Exception as exc:  # ネットワーク・サーバエラー
                raise GeminiUnavailable(f"{type(exc).__name__}") from None
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                parse_attempts += 1
                if parse_attempts > 1:
                    raise GeminiUnavailable("JSON不正（再試行後も失敗）") from None

    def extract_events(self, page: CandidatePage, period: DateRange, categories: list[str]) -> list[dict[str, Any]]:
        venue_note = f"- 会場が書かれていない場合、このページは「{page.venue_hint}」のイベント一覧\n" if page.venue_hint else ""
        prompt = EXTRACT_PROMPT.format(
            period_from=period.start.isoformat(),
            period_to=period.end.isoformat(),
            category_list="／".join(categories),
            venue_note=venue_note,
            url=page.url,
            text=page.text[: self.max_input_chars],
        )
        data = self._call(prompt, EXTRACT_SCHEMA)
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []

    def enrich_events(self, events: list[RawEvent], categories: list[str]) -> dict[int, dict[str, Any]]:
        payload = [{"index": i, "name": e.name, "description": e.description[:300], "url": e.url} for i, e in enumerate(events)]
        prompt = ENRICH_PROMPT.format(category_list="／".join(categories), events_json=json.dumps(payload, ensure_ascii=False))
        data = self._call(prompt, ENRICH_SCHEMA)
        result: dict[int, dict[str, Any]] = {}
        for d in data if isinstance(data, list) else []:
            if isinstance(d, dict) and isinstance(d.get("index"), int):
                result[d["index"]] = d
        return result
