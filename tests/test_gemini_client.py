import json
from datetime import date

import pytest

from collector.date_range import DateRange
from collector.gemini_client import GeminiClient, GeminiUnavailable, RateLimitError
from collector.sources.base import CandidatePage, RawEvent

CFG = {"max_requests_per_run": 5, "sleep_sec": 0, "max_input_chars": 100}
PAGE = CandidatePage(
    url="https://example.com/",
    title="t",
    text="本文" * 200,
    source_id="s",
    source_name="主催者HP：s",
    source_type="organizer",
    venue_hint="幕張メッセ",
)
PERIOD = DateRange(date(2026, 10, 5), date(2027, 3, 31))
EVENT = {"event_name": "無線EXPO", "start_date": "2026-11-11", "categories": ["無線・通信"], "confidence": 90}


class Script:
    """呼ばれるたびに次の応答（文字列 or 例外）を返すモック。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def __call__(self, prompt, schema):
        self.prompts.append(prompt)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def client(script: Script, **cfg) -> GeminiClient:
    return GeminiClient({**CFG, **cfg}, transport=script, sleep=lambda s: None)


def test_extract_events_ok() -> None:
    script = Script(json.dumps([EVENT]))
    c = client(script)
    assert c.extract_events(PAGE, PERIOD, ["無線・通信"]) == [EVENT]
    assert c.requests_made == 1
    prompt = script.prompts[0]
    assert "2026-10-05 ～ 2027-03-31" in prompt
    assert "幕張メッセ" in prompt
    assert prompt.split("ページ本文：", 1)[1].strip() == "本文" * 50  # max_input_chars で切り詰め


def test_invalid_json_retried_once() -> None:
    c = client(Script("not json", json.dumps([EVENT])))
    assert c.extract_events(PAGE, PERIOD, []) == [EVENT]
    assert c.requests_made == 2


def test_invalid_json_twice_fails() -> None:
    c = client(Script("x", "y"))
    with pytest.raises(GeminiUnavailable, match="JSON不正"):
        c.extract_events(PAGE, PERIOD, [])


def test_rate_limit_backoff_then_success() -> None:
    sleeps: list[float] = []
    c = GeminiClient(CFG, transport=Script(RateLimitError(), RateLimitError(), json.dumps([])), sleep=sleeps.append)
    assert c.extract_events(PAGE, PERIOD, []) == []
    assert sleeps == [10, 20]  # 指数バックオフ


def test_rate_limit_persistent_marks_exhausted() -> None:
    c = client(Script(*[RateLimitError()] * 4), max_requests_per_run=10)
    with pytest.raises(GeminiUnavailable):
        c.extract_events(PAGE, PERIOD, [])
    assert c.exhausted and not c.available


def test_max_requests_per_run() -> None:
    c = client(Script(*[json.dumps([])] * 3), max_requests_per_run=2)
    c.extract_events(PAGE, PERIOD, [])
    c.extract_events(PAGE, PERIOD, [])
    with pytest.raises(GeminiUnavailable):
        c.extract_events(PAGE, PERIOD, [])


def test_server_error_is_unavailable_not_crash() -> None:
    c = client(Script(ConnectionError("boom")))
    with pytest.raises(GeminiUnavailable):
        c.extract_events(PAGE, PERIOD, [])


def test_disabled_without_key(monkeypatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    c = GeminiClient({"enabled": True})
    assert not c.available and "未設定" in c.disabled_reason


def test_enrich_events_indexes() -> None:
    raws = [
        RawEvent(
            name=f"展{i}",
            start_date="2026-11-11",
            end_date="2026-11-11",
            venue="",
            url="",
            description="",
            source_id="s",
            source_name="s",
            source_type="venue",
        )
        for i in range(2)
    ]
    c = client(Script(json.dumps([{"index": 1, "relevant": False}, {"index": 0, "relevant": True, "categories": ["AI・DX"]}, {"bad": 1}])))
    result = c.enrich_events(raws, ["AI・DX"])
    assert set(result) == {0, 1} and result[1]["relevant"] is False
