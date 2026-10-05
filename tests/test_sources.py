from datetime import date

from collector.date_range import DateRange
from collector.sources import create_parser
from collector.sources.known_urls import text_hash
from collector.sources.venue_bigsight import parse_list as parse_bigsight
from collector.sources.venue_makuhari import months_in, parse_detail
from collector.sources.venue_makuhari import parse_list as parse_makuhari
from tests.conftest import FakeFetcher, fixture_text

PERIOD = DateRange(date(2026, 10, 5), date(2027, 3, 31))
BIGSIGHT = {
    "id": "bigsight",
    "name": "東京ビッグサイト",
    "type": "venue_bigsight",
    "url": "https://www.bigsight.jp/visitor/event/",
    "venue": "東京ビッグサイト",
}
MAKUHARI = {
    "id": "makuhari",
    "name": "幕張メッセ",
    "type": "venue_makuhari",
    "url": "https://www.m-messe.co.jp/event/",
    "venue": "幕張メッセ",
}


# ------------------------------------------------------------------ ビッグサイト


def test_bigsight_parse_list() -> None:
    events = parse_bigsight(fixture_text("bigsight_list.html"), BIGSIGHT, "https://www.bigsight.jp/visitor/event/search.php")
    assert len(events) == 2  # 開催期間の無いものは除外
    e = events[0]
    assert e.name == "第3回 ローカル5G・無線通信 EXPO"  # アイコンの「新規タブで開きます」を含まない
    assert (e.start_date, e.end_date) == ("2026-11-11", "2026-11-13")
    assert e.url == "https://example.com/wireless-expo/"
    assert e.venue == "東京ビッグサイト"
    assert "無線通信" in e.description
    assert "東1-3ホール" in e.reason


def test_bigsight_collect_stops_on_empty_page() -> None:
    list_url = "https://www.bigsight.jp/visitor/event/search.php"
    fetcher = FakeFetcher({(list_url, (("page", 1),)): fixture_text("bigsight_list.html"), (list_url, (("page", 2),)): "<html></html>"})
    result = create_parser(BIGSIGHT, fetcher, {}).collect(PERIOD)
    assert len(result.events) == 2
    assert [c[1] for c in fetcher.calls] == [{"page": 1}, {"page": 2}]
    assert result.errors == []


def test_bigsight_http_error_is_recorded() -> None:
    result = create_parser(BIGSIGHT, FakeFetcher({}), {}).collect(PERIOD)
    assert result.events == []
    assert "HTTP 404" in result.errors[0]


# ------------------------------------------------------------------ 幕張


def test_makuhari_months() -> None:
    assert months_in(DateRange(date(2026, 11, 20), date(2027, 2, 28))) == ["202611", "202612", "202701", "202702"]


def test_makuhari_parse_list_filters_category() -> None:
    events, last_page = parse_makuhari(fixture_text("makuhari_list.html"), MAKUHARI, "https://www.m-messe.co.jp/event/", ["展示会・見本市"])
    assert [e.name for e in events] == ["第5回 AI・IoT ソリューション展 秋", "国際テスト工具フェア"]
    assert last_page == 2
    assert events[0].description == "https://www.m-messe.co.jp/event/detail/1001"


def test_makuhari_parse_detail() -> None:
    url, desc = parse_detail(fixture_text("makuhari_detail.html"), "https://www.m-messe.co.jp/event/detail/1001")
    assert url == "https://example.org/ai-iot-expo/?x=1"  # 公式URL（トラッキング用クエリを除去）
    assert desc.startswith("AI、IoT")


def test_makuhari_collect_and_resolve() -> None:
    base = "https://www.m-messe.co.jp/event/"
    routes = {
        (base, (("month", "202611"), ("page", 1))): fixture_text("makuhari_list.html"),
        (base, (("month", "202611"), ("page", 2))): "<html></html>",
        "https://www.m-messe.co.jp/event/detail/1001": fixture_text("makuhari_detail.html"),
    }
    parser = create_parser(MAKUHARI, FakeFetcher(routes), {})
    result = parser.collect(DateRange(date(2026, 11, 1), date(2026, 11, 30)))
    assert [e.name for e in result.events] == ["第5回 AI・IoT ソリューション展 秋"]  # 12月開催は期間外
    parser.resolve_url(result.events[0])
    assert result.events[0].url == "https://example.org/ai-iot-expo/?x=1"


# ------------------------------------------------------------------ 汎用・既知URL・無効化


def test_venue_generic_builds_candidate_page() -> None:
    src = {
        "id": "portmesse",
        "name": "ポートメッセなごや",
        "type": "venue_generic",
        "url": "https://portmesse.example/events",
        "venue": "ポートメッセなごや",
    }
    html = "<html><head><title>イベント</title></head><body><nav>メニュー</nav><p>2026年11月4日 IoT展</p><script>x=1</script></body></html>"
    result = create_parser(src, FakeFetcher({src["url"]: html}), {}).collect(PERIOD)
    page = result.pages[0]
    assert page.skip_keyword_filter is True
    assert page.venue_hint == "ポートメッセなごや"
    assert "IoT展" in page.text and "メニュー" not in page.text and "x=1" not in page.text
    assert page.source_name == "展示会場HP：ポートメッセなごや"


def test_venue_generic_empty_body_is_error() -> None:
    src = {"id": "intex", "name": "インテックス大阪", "type": "venue_generic", "url": "https://intex.example/"}
    result = create_parser(src, FakeFetcher({src["url"]: "<html><body><script>render()</script></body></html>"}), {}).collect(PERIOD)
    assert result.pages == [] and "本文が空" in result.errors[0]


def test_organizer_generic_uses_keyword_filter() -> None:
    src = {"id": "interop", "name": "Interop Tokyo", "type": "organizer_generic", "url": "https://interop.example/"}
    result = create_parser(src, FakeFetcher({src["url"]: "<html><body>Interop</body></html>"}), {}).collect(PERIOD)
    assert result.pages[0].skip_keyword_filter is False
    assert result.pages[0].source_type == "organizer"


def test_known_urls_skips_unchanged_and_prioritizes_past() -> None:
    page_a = "<html><head><title>A展</title></head><body>A展 2027年 開催決定</body></html>"
    page_b = "<html><head><title>B展</title></head><body>B展 2026年</body></html>"
    from collector.fetcher import html_to_text

    unchanged_hash = text_hash(html_to_text(page_b, 12000)[1])
    context = {
        "known_urls": [
            {"url": "https://a.example/", "name": "A展"},
            {"url": "https://b.example/", "name": "B展"},
            {"url": "https://gone.example/", "name": "C展"},
        ],
        "page_state": {"https://b.example/": {"hash": unchanged_hash, "checked": "2026-09-01"}},
        "live_url_keys": set(),
    }
    fetcher = FakeFetcher({"https://a.example/": page_a, "https://b.example/": page_b})
    result = create_parser({"id": "known_urls", "type": "known_urls"}, fetcher, context).collect(PERIOD)
    assert [p.url for p in result.pages] == ["https://a.example/"]  # B は前回から変化なし、C は404
    assert result.pages[0].priority == 2  # 掲載中でない（過去回）URLは優先
    assert result.errors == []  # 個別URLの404は収集元エラーにしない
    assert context["page_state"]["https://gone.example/"]["error"] == "HTTP 404"
    assert context["page_state"]["https://a.example/"]["checked"] == "2026-10-05"


def test_known_urls_rotation_order() -> None:
    context = {
        "known_urls": [{"url": f"https://{c}.example/"} for c in "abc"],
        "page_state": {"https://a.example/": {"checked": "2026-10-01"}, "https://b.example/": {"checked": "2026-09-01"}},
    }
    parser = create_parser({"id": "known_urls", "type": "known_urls", "max_urls_per_run": 2}, FakeFetcher(), context)
    assert [u["url"] for u in parser.ordered_urls()] == ["https://c.example/", "https://b.example/"]  # 未確認→古い順


def test_disabled_sources_report_reason() -> None:
    for type_ in ("jmesse", "venue_pacifico"):
        result = create_parser({"id": type_, "type": type_}, FakeFetcher(), {}).collect(PERIOD)
        assert result.errors and "未対応" in result.errors[0]


def test_bigsight_stops_when_page_param_ignored() -> None:
    list_url = "https://www.bigsight.jp/organizer/buildings/gym-ex/event/"
    src = {**BIGSIGHT, "id": "gymex", "list_url": list_url, "venue": "有明GYM-EX"}
    fetcher = FakeFetcher({list_url: fixture_text("bigsight_list.html")})  # どのページ番号でも同じ内容
    result = create_parser(src, fetcher, {"max_pages_per_source": 50}).collect(PERIOD)
    assert len(result.events) == 2 and len(fetcher.calls) == 2
    assert result.events[0].venue == "有明GYM-EX"
