"""Gemini API による構造化（C-04）。

- APIキー・モデル名は環境変数（settings.yaml の gemini.api_key_env / model_env で名前を指定）
- 1回の実行あたりのリクエスト数を max_requests_per_run で制限。上限到達後は呼ばない
- Gemini が使えなくなったら（上限・枠切れ・エラー続き）、fallbacks に書いた OpenAI 互換API（Groq等）に自動で切り替える
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
from dataclasses import dataclass
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

OPENAI_JSON_NOTE = '\n出力は {"items": [ ... ]} の形のJSONオブジェクトにすること（items に上記のJSON配列を入れる）。\n'


@dataclass
class Provider:
    """LLMの呼び出し先1つ分。上から順に使い、使えなくなったら次へ切り替える。"""

    name: str
    transport: Transport
    max_requests: int = 150
    sleep_sec: float = 5
    max_input_chars: int = 12000
    json_note: str = ""
    requests_made: int = 0
    exhausted: bool = False
    last_call: float = 0.0
    note: str = ""

    @property
    def usable(self) -> bool:
        return not self.exhausted and self.requests_made < self.max_requests


def _gemini_transport(api_key: str, model: str, timeout_sec: float) -> Transport:
    from google import genai
    from google.genai import errors, types

    client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_sec * 1000)))

    def call(prompt: str, schema: dict[str, Any]) -> str:
        try:
            res = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.1),
            )
        except errors.ClientError as exc:
            if exc.code == 429:
                raise RateLimitError(str(exc.code)) from None
            raise
        return res.text or ""

    return call


def _openai_compatible_transport(endpoint: str, api_key: str, model: str, timeout_sec: float) -> Transport:
    """Groq など OpenAI 互換の Chat Completions API。JSONモード（json_object）を使う。"""
    import requests

    def call(prompt: str, schema: dict[str, Any]) -> str:
        res = requests.post(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            },
            timeout=timeout_sec,
        )
        if res.status_code == 429:
            raise RateLimitError("429")
        res.raise_for_status()
        return res.json()["choices"][0]["message"]["content"] or ""

    return call


def build_providers(cfg: dict[str, Any]) -> tuple[list[Provider], list[str]]:
    """settings.yaml の gemini 節（＋fallbacks）から呼び出し先を組み立てる。(使える呼び出し先, 使えない理由) を返す。"""
    timeout = float(cfg.get("request_timeout_sec", 60))
    providers: list[Provider] = []
    skipped: list[str] = []
    entries = [{"name": "gemini", "type": "gemini", **cfg}, *(cfg.get("fallbacks") or [])]
    for entry in entries:
        name = entry.get("name", entry.get("type", "?"))
        if entry.get("enabled", True) is False:
            skipped.append(f"{name}: 無効化")
            continue
        key = os.environ.get(entry.get("api_key_env", ""), "")
        model = os.environ.get(entry.get("model_env", ""), "") or entry.get("default_model", "")
        if not key or not model:
            skipped.append(f"{name}: {entry.get('api_key_env')} / {entry.get('model_env')} が未設定")
            continue
        if entry.get("type", "gemini") == "gemini":
            transport, note = _gemini_transport(key, model, timeout), ""
        else:
            transport, note = _openai_compatible_transport(entry["endpoint"], key, model, timeout), OPENAI_JSON_NOTE
        providers.append(
            Provider(
                name=f"{name}:{model}",
                transport=transport,
                max_requests=int(entry.get("max_requests_per_run", 150)),
                sleep_sec=float(entry.get("sleep_sec", 5)),
                max_input_chars=int(entry.get("max_input_chars", cfg.get("max_input_chars", 12000))),
                json_note=note,
            )
        )
    return providers, skipped


def _unwrap(data: Any) -> Any:
    """OpenAI互換APIは JSONオブジェクトしか返せないため {"items": [...]} を配列に戻す。"""
    if isinstance(data, dict):
        for key in ("items", "events", "results", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return data


class GeminiClient:
    """Gemini を主に使い、使えなくなったら fallbacks（Groq等）へ自動で切り替える。

    切り替える条件：1回あたりの上限到達／レート制限が続く（枠切れ）／通信・サーバエラーが続く。
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        providers: list[Provider] | None = None,
    ) -> None:
        self._sleep = sleep
        budget = float(cfg.get("time_budget_minutes", 0)) * 60
        self._deadline = time.monotonic() + budget if budget > 0 else None
        self.disabled_reason = ""
        self.skipped: list[str] = []
        if providers is not None:
            self.providers = providers
        elif transport is not None:
            self.providers = [
                Provider(
                    name="test",
                    transport=transport,
                    max_requests=int(cfg.get("max_requests_per_run", 150)),
                    sleep_sec=float(cfg.get("sleep_sec", 5)),
                    max_input_chars=int(cfg.get("max_input_chars", 12000)),
                )
            ]
        elif not cfg.get("enabled", True):
            self.providers = []
            self.disabled_reason = "settings.yaml で無効化"
        else:
            self.providers, self.skipped = build_providers(cfg)
            if not self.providers:
                self.disabled_reason = "APIキー・モデルが未設定（" + "／".join(self.skipped) + "）"

    # ------------------------------------------------------------ 状態
    @property
    def requests_made(self) -> int:
        return sum(p.requests_made for p in self.providers)

    @property
    def usage(self) -> dict[str, int]:
        return {p.name: p.requests_made for p in self.providers}

    @property
    def exhausted(self) -> bool:
        return bool(self.providers) and all(p.exhausted for p in self.providers)

    @property
    def out_of_time(self) -> bool:
        return self._deadline is not None and time.monotonic() > self._deadline

    @property
    def available(self) -> bool:
        return not self.disabled_reason and not self.out_of_time and any(p.usable for p in self.providers)

    @property
    def unavailable_reason(self) -> str:
        if self.out_of_time:
            return "時間上限（time_budget_minutes）に到達"
        if self.exhausted:
            return "枠切れ（全ての呼び出し先）"
        return "1回あたりの上限に到達"

    # ------------------------------------------------------------ 呼び出し
    def _call(self, make_prompt: Callable[[int], str], schema: dict[str, Any]) -> Any:
        """JSONを返す。呼び出し先を上から順に試す。

        - JSON不正：同じ呼び出し先で1回だけ再試行し、それでも不正ならこのページは諦める
        - 429：指数バックオフ（3回）後、その呼び出し先を枠切れにして次へ
        - 通信・サーバエラー：その呼び出し先で2回続いたら枠切れ扱いにして次へ
        """
        if not self.available:
            raise GeminiUnavailable(self.disabled_reason or self.unavailable_reason)
        for provider in self.providers:
            if not provider.usable:
                continue
            prompt = make_prompt(provider.max_input_chars) + provider.json_note
            parse_attempts = backoff = errors = 0
            while provider.usable:
                if self.out_of_time:
                    raise GeminiUnavailable(self.unavailable_reason)
                wait = provider.sleep_sec - (time.monotonic() - provider.last_call)
                if provider.last_call and wait > 0:
                    self._sleep(wait)
                provider.last_call = time.monotonic()
                provider.requests_made += 1
                try:
                    raw = provider.transport(prompt, schema)
                except RateLimitError:
                    if backoff >= 3:
                        provider.exhausted = True
                        provider.note = "レート制限が続くため枠切れと判断"
                        break
                    self._sleep(10 * 2**backoff)
                    backoff += 1
                    continue
                except Exception as exc:  # 通信・サーバエラー
                    errors += 1
                    log.warning("%s 呼び出し失敗: %s", provider.name, type(exc).__name__)
                    if errors >= 2:
                        provider.exhausted = True
                        provider.note = f"エラーが続いたため停止（{type(exc).__name__}）"
                        break
                    continue
                try:
                    return _unwrap(json.loads(raw))
                except json.JSONDecodeError:
                    parse_attempts += 1
                    if parse_attempts > 1:
                        raise GeminiUnavailable(f"JSON不正（{provider.name}、再試行後も失敗）") from None
        raise GeminiUnavailable(self.unavailable_reason)

    def extract_events(self, page: CandidatePage, period: DateRange, categories: list[str]) -> list[dict[str, Any]]:
        venue_note = f"- 会場が書かれていない場合、このページは「{page.venue_hint}」のイベント一覧\n" if page.venue_hint else ""

        def make_prompt(limit: int) -> str:
            return EXTRACT_PROMPT.format(
                period_from=period.start.isoformat(),
                period_to=period.end.isoformat(),
                category_list="／".join(categories),
                venue_note=venue_note,
                url=page.url,
                text=page.text[:limit],
            )

        data = self._call(make_prompt, EXTRACT_SCHEMA)
        return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []

    def enrich_events(self, events: list[RawEvent], categories: list[str]) -> dict[int, dict[str, Any]]:
        payload = [{"index": i, "name": e.name, "description": e.description[:300], "url": e.url} for i, e in enumerate(events)]
        prompt = ENRICH_PROMPT.format(category_list="／".join(categories), events_json=json.dumps(payload, ensure_ascii=False))
        data = self._call(lambda _limit: prompt, ENRICH_SCHEMA)
        result: dict[int, dict[str, Any]] = {}
        for d in data if isinstance(data, list) else []:
            if isinstance(d, dict) and isinstance(d.get("index"), int):
                result[d["index"]] = d
        return result
