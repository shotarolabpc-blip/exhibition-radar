"""収集処理全体（外部通信なし：FakeFetcher＋Geminiモック）。"""

import json
from datetime import date

import pytest

from collector.exporter import load_events, read_json, write_events
from collector.gemini_client import GeminiClient
from collector.main import FatalError, run
from collector.models import Event, make_event_id
from collector.settings import Config
from tests.conftest import FakeFetcher, fixture_text

TODAY = date(2026, 10, 5)
LIST_URL = "https://www.bigsight.jp/visitor/event/search.php"
ORG_URL = "https://organizer.example/"
ORG_HTML = "<html><head><title>ワイヤレス EXPO</title></head><body>ワイヤレス・5G・IoTの展示会。会期未定。</body></html>"


def make_cfg(tmp_path, cfg: Config, sources=None) -> Config:
    (tmp_path / "data").mkdir()
    (tmp_path / "docs" / "data").mkdir(parents=True)
    (tmp_path / "data" / "overrides.yaml").write_text("exclude: []\nfix: []\nmerge: []\nconfirm: []\n", encoding="utf-8")
    sources = sources or [
        {
            "id": "bigsight",
            "name": "東京ビッグサイト",
            "type": "venue_bigsight",
            "url": "https://www.bigsight.jp/visitor/event/",
            "list_url": LIST_URL,
            "venue": "東京ビッグサイト",
        },
        {"id": "org", "name": "テスト主催者", "type": "organizer_generic", "url": ORG_URL},
    ]
    return Config(**{**cfg.__dict__, "root_dir": tmp_path, "sources": sources, "known_urls": []})


def routes():
    return {(LIST_URL, (("page", 1),)): fixture_text("bigsight_list.html"), (LIST_URL, (("page", 2),)): "<html></html>", ORG_URL: ORG_HTML}


def gemini_with(*responses) -> GeminiClient:
    queue = list(responses)
    return GeminiClient({"max_requests_per_run": 10, "sleep_sec": 0}, transport=lambda p, s: queue.pop(0), sleep=lambda s: None)


ENRICH = json.dumps([{"index": 0, "relevant": True, "categories": ["無線・通信"], "summary": "無線通信の展示会。", "confidence": 95}])
EXTRACT = json.dumps(
    [
        {
            "event_name": "ワイヤレス EXPO 2027",
            "start_date": "",
            "date_status": "unknown",
            "venue": "",
            "categories": ["無線・通信"],
            "summary": "次回開催は未定。",
            "url": "",
            "confidence": 80,
            "reason": "公式ページ",
        }
    ]
)


def test_full_run(tmp_path, cfg) -> None:
    c = make_cfg(tmp_path, cfg)
    summary = run(c, TODAY, fetcher=FakeFetcher(routes()), gemini=gemini_with(ENRICH, EXTRACT))
    events = {e.event_name: e for e in load_events(tmp_path / "docs" / "data" / "events.json")}
    # ビッグサイト：無線EXPOは採用、フラワーフェスタはキーワード判定で除外
    wireless = events["第3回 ローカル5G・無線通信 EXPO"]
    assert wireless.status == "new"
    assert wireless.categories == ["無線・通信"] and wireless.summary == "無線通信の展示会。"
    assert (wireless.prefecture, wireless.region) == ("東京都", "関東")
    assert "フラワーフェスタ 2026" not in events
    # 主催者ページ：日程未定の次回開催（URLはページURLで補う）
    nxt = events["ワイヤレス EXPO 2027"]
    assert nxt.date_status == "unknown" and nxt.year == "2027" and nxt.url == ORG_URL
    assert summary["new"] == 2 and summary["gemini_requests"] == 2
    assert summary["source_counts"] == {"bigsight": 2, "org": 1}
    runs = read_json(tmp_path / "docs" / "data" / "runs.json", [])
    assert runs[0]["type"] == "collect"
    assert (tmp_path / "docs" / "data" / "events.csv").exists()


def test_second_run_demotes_new_and_detects_date_confirmation(tmp_path, cfg) -> None:
    c = make_cfg(tmp_path, cfg)
    run(c, TODAY, fetcher=FakeFetcher(routes()), gemini=gemini_with(ENRICH, EXTRACT))
    confirmed = EXTRACT.replace('"start_date": ""', '"start_date": "2027-02-10", "end_date": "2027-02-12"').replace('"unknown"', '"fixed"')
    run(c, date(2026, 10, 12), fetcher=FakeFetcher(routes()), gemini=gemini_with(ENRICH, confirmed))
    events = {e.event_name: e for e in load_events(tmp_path / "docs" / "data" / "events.json")}
    assert events["第3回 ローカル5G・無線通信 EXPO"].status == "unchanged"
    nxt = events["ワイヤレス EXPO 2027"]
    assert nxt.status == "updated" and nxt.start_date == "2027-02-10"
    assert "日程確定" in nxt.history[-1]["change"]


def test_without_gemini_structured_sources_still_work(tmp_path, cfg) -> None:
    c = make_cfg(tmp_path, cfg)
    summary = run(c, TODAY, fetcher=FakeFetcher(routes()), use_gemini=False)
    events = {e.event_name: e for e in load_events(tmp_path / "docs" / "data" / "events.json")}
    assert "第3回 ローカル5G・無線通信 EXPO" in events
    assert summary["gemini_pending"] == 1  # 主催者ページは次回に持ち越し


def test_all_sources_failed_is_fatal_and_keeps_data(tmp_path, cfg) -> None:
    c = make_cfg(tmp_path, cfg)
    existing = Event(
        id=make_event_id("既存展", "", "2026"), event_name="既存展", parent_event_name="既存展", start_date="2026-11-01", year="2026"
    )
    write_events([existing], tmp_path / "docs" / "data")
    before = (tmp_path / "docs" / "data" / "events.json").read_text(encoding="utf-8")
    with pytest.raises(FatalError, match="全収集元"):
        run(c, TODAY, fetcher=FakeFetcher({}), use_gemini=False)
    assert (tmp_path / "docs" / "data" / "events.json").read_text(encoding="utf-8") == before


def test_large_drop_is_fatal(tmp_path, cfg) -> None:
    c = make_cfg(tmp_path, cfg)
    existing = [
        Event(
            id=f"evt_{i:08d}", event_name=f"展{i}", parent_event_name=f"展{i}", start_date="2026-08-01", end_date="2026-08-02", year="2026"
        )
        for i in range(10)
    ]
    write_events(existing, tmp_path / "docs" / "data")  # すべて30日以上前に終了→アーカイブで急減
    with pytest.raises(FatalError, match="急減"):
        run(c, TODAY, fetcher=FakeFetcher(routes()), use_gemini=False)


def test_zero_parse_is_recorded(tmp_path, cfg) -> None:
    c = make_cfg(tmp_path, cfg)
    (tmp_path / "docs" / "data" / "runs.json").write_text(
        json.dumps([{"type": "collect", "source_counts": {"bigsight": 5, "org": 1}}]), encoding="utf-8"
    )
    r = routes()
    r[(LIST_URL, (("page", 1),))] = "<html><body>リニューアルしました</body></html>"
    summary = run(c, TODAY, fetcher=FakeFetcher(r), use_gemini=False)
    assert any("パース0件" in err for err in summary["errors"])


def test_overrides_exclude_applies_to_incoming(tmp_path, cfg) -> None:
    c = make_cfg(tmp_path, cfg)
    (tmp_path / "data" / "overrides.yaml").write_text('exclude:\n  - url_contains: "wireless-expo"\n', encoding="utf-8")
    run(c, TODAY, fetcher=FakeFetcher(routes()), use_gemini=False)
    names = [e.event_name for e in load_events(tmp_path / "docs" / "data" / "events.json")]
    assert "第3回 ローカル5G・無線通信 EXPO" not in names
