from datetime import date

import pytest

from collector.normalizer import (
    clean_text,
    normalize_categories,
    normalize_url,
    normalize_venue,
    parse_dates,
    split_event_name,
    url_key,
)
from collector.region import resolve_region

# ------------------------------------------------------------------ 日付


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("2026-10-21", date(2026, 10, 21), date(2026, 10, 21)),
        ("2026/10/21～2026/10/23", date(2026, 10, 21), date(2026, 10, 23)),
        ("2026年10月21日(水)～23日(金)", date(2026, 10, 21), date(2026, 10, 23)),
        ("2026年10月21日（水）〜10月23日（金）", date(2026, 10, 21), date(2026, 10, 23)),
        ("２０２６年１０月２１日～２３日", date(2026, 10, 21), date(2026, 10, 23)),  # 全角
        ("令和8年10月21日～23日", date(2026, 10, 21), date(2026, 10, 23)),  # 和暦
        ("令和元年5月1日", date(2019, 5, 1), date(2019, 5, 1)),
        ("2026.10.21 - 10.23", date(2026, 10, 21), date(2026, 10, 23)),
        ("会期：2026年12月30日(水)～1月2日(土)", date(2026, 12, 30), date(2027, 1, 2)),  # 年跨ぎ
        ("2026年10月21日(Wed)〜23日(Fri) 10:00～17:00", date(2026, 10, 21), date(2026, 10, 23)),
        ("2026年10月21日(水・祝)", date(2026, 10, 21), date(2026, 10, 21)),
    ],
)
def test_parse_dates(text: str, start: date, end: date) -> None:
    parsed = parse_dates(text)
    assert (parsed.start, parsed.end) == (start, end)
    assert parsed.status == "fixed"


def test_parse_dates_year_omitted_requires_default_year() -> None:
    assert parse_dates("10月21日～23日").start is None  # 年を推測しない
    parsed = parse_dates("10月21日(水)～23日(金)", default_year=2026)
    assert (parsed.start, parsed.end) == (date(2026, 10, 21), date(2026, 10, 23))


def test_parse_dates_month_only_keeps_year_without_date() -> None:
    parsed = parse_dates("2027/07")
    assert parsed.start is None
    assert parsed.year == 2027
    assert parsed.status == "unknown"


@pytest.mark.parametrize("text", ["", "-", "未定", None, "日程調整中"])
def test_parse_dates_unknown(text: str | None) -> None:
    assert parse_dates(text).start is None


def test_parse_dates_tentative() -> None:
    parsed = parse_dates("2026年11月5日～7日（予定）")
    assert parsed.start == date(2026, 11, 5)
    assert parsed.status == "tentative"


def test_parse_dates_excel_serial() -> None:
    assert parse_dates(46316).start == date(2026, 10, 21)
    assert parse_dates("46316").start == date(2026, 10, 21)


def test_parse_dates_invalid_day() -> None:
    assert parse_dates("2026/02/30").start is None


# ------------------------------------------------------------------ テキスト・イベント名


def test_clean_text() -> None:
    assert clean_text("\t東京ビッグサイト  東展示棟 ") == "東京ビッグサイト 東展示棟"


def test_split_event_name() -> None:
    assert split_event_name("Japan IT Week 秋 - 情報セキュリティ EXPO") == ("Japan IT Week 秋", "情報セキュリティ EXPO")
    assert split_event_name("CEATEC 2026") == ("CEATEC 2026", "")
    assert split_event_name("ものづくり ワールド -クルマの先端技術展") == ("ものづくり ワールド -クルマの先端技術展", "")


# ------------------------------------------------------------------ URL


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.ceatec.com/ja/", "https://www.ceatec.com/ja/"),
        ("HTTPS://WWW.Example.COM/Event?utm_source=x&id=3#top", "https://www.example.com/Event?id=3"),
        ("[公式サイト](https://example.com/expo)", "https://example.com/expo"),
        ("公式：https://example.com/a）", "https://example.com/a"),
        ("https://example.com", "https://example.com/"),
        ("公式サイト", ""),
        ("", ""),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_url_key() -> None:
    assert url_key("https://www.example.com/expo/") == url_key("http://example.com/expo/index.html")
    assert url_key("https://example.com/a") != url_key("https://example.com/b")


# ------------------------------------------------------------------ 会場・地域


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("東京ビックサイト", "東京ビッグサイト"),
        ("\t東京ビッグサイト 東展示棟", "東京ビッグサイト"),
        ("東京国際展示場（東京ビッグサイト）", "東京ビッグサイト"),
        ("インテックス大阪 6号館 C・Dゾーン", "インテックス大阪"),
        ("ポートメッセ 名古屋", "ポートメッセなごや"),
        ("Aichi Sky Expo [愛知県国際展示場]ホールC/D", "Aichi Sky Expo"),
        ("（仮）神戸国際展示場1・2号館（神戸ポートアイランド）", "神戸国際展示場"),
        ("まいドーム大阪", "マイドームおおさか"),
        ("Web開催", "オンライン"),
        ("どこかの公民館", "どこかの公民館"),
    ],
)
def test_normalize_venue(cfg, raw: str, expected: str) -> None:
    assert normalize_venue(raw, cfg.venues) == expected


@pytest.mark.parametrize(
    ("venue", "raw", "expected"),
    [
        ("幕張メッセ", "幕張メッセ", ("千葉県", "関東")),
        ("マリンメッセ福岡", "マリンメッセ福岡", ("福岡県", "九州・沖縄")),
        ("オンライン", "オンライン", ("", "オンライン")),
        ("沖縄県那覇市", "沖縄県那覇市", ("沖縄県", "九州・沖縄")),
        ("金沢（石川）", "金沢（石川）", ("石川県", "中部")),
        ("今治市（愛媛）", "今治市（愛媛）", ("愛媛県", "中国・四国")),
        ("東京都内某所", "東京都内某所", ("東京都", "関東")),  # 「京都」と誤判定しない
        ("どこかの公民館", "どこかの公民館", ("", "")),
    ],
)
def test_resolve_region(cfg, venue: str, raw: str, expected: tuple[str, str]) -> None:
    assert resolve_region(venue, raw, cfg.venues) == expected


# ------------------------------------------------------------------ カテゴリ


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("AI・IoT・ビッグデータ", ["AI・DX", "IoT・センサ"]),
        ("セキュリティ", ["セキュリティ"]),
        ("5G、ローカル5G", ["無線・通信"]),
        ("農業", ["その他IT"]),
        ("", ["その他IT"]),
        (["AI・DX", "セキュリティ"], ["AI・DX", "セキュリティ"]),
        ("SMART FACTORY", ["その他IT"]),  # "AR" を部分一致させない
        ("ドローン/ロボット", ["ドローン・ロボット"]),
    ],
)
def test_normalize_categories(cfg, raw, expected: list[str]) -> None:
    assert normalize_categories(raw, cfg.categories) == expected
