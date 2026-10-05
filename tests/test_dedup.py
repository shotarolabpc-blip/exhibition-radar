from collector.dedup import Merger, demote_previous, name_key, similarity
from collector.models import Event, make_event_id

JUDGE = {"fuzzy_duplicate_threshold": 90, "fuzzy_review_threshold": 75, "confidence_review_threshold": 70}
TODAY = "2026-10-05"


def ev(name: str, year: str = "2026", **kw) -> Event:
    parent, _, sub = name.partition(" - ")
    base = dict(
        id=make_event_id(parent, sub, year),
        event_name=name,
        parent_event_name=parent,
        sub_event_name=sub,
        start_date="2026-11-11",
        end_date="2026-11-13",
        date_status="fixed",
        venue="幕張メッセ",
        prefecture="千葉県",
        region="関東",
        url="https://example.com/expo/",
        source="展示会場HP：幕張メッセ",
        source_type="venue",
        confidence=90,
        status="unchanged",
        year=year,
    )
    base.update(kw)
    return Event(**base)


def merge(existing, incoming, fixes=None):
    m = Merger(existing, JUDGE, TODAY, fixes)
    for e in incoming:
        m.add(e)
    return {e.id: e for e in m.result()}, m.stats


def test_name_key_ignores_ordinal_and_year() -> None:
    assert name_key("第5回 AI・IoT展 2026") == name_key("AI IoT展")
    assert similarity("第3回 ローカル5G EXPO", "ローカル5G EXPO 2026") == 100


def test_new_event() -> None:
    result, stats = merge([], [ev("無線EXPO")])
    e = next(iter(result.values()))
    assert e.status == "new" and stats.new == 1
    assert e.first_seen == TODAY
    assert e.history[0]["change"].startswith("新規検出")


def test_unchanged_when_same() -> None:
    existing = ev("無線EXPO")
    result, stats = merge([existing], [ev("無線EXPO")])
    assert result[existing.id].status == "unchanged"
    assert result[existing.id].last_checked == TODAY
    assert stats.updated == 0 and existing.history == []


def test_date_confirmed_is_update_with_history() -> None:
    existing = ev("無線EXPO", start_date="", end_date="", date_status="unknown", source_type="import", source="既存Excel取込")
    result, stats = merge([existing], [ev("無線EXPO")])
    e = result[existing.id]
    assert e.status == "updated" and stats.updated == 1
    assert (e.start_date, e.date_status) == ("2026-11-11", "fixed")
    assert e.history[-1]["change"].startswith("更新：日程確定")
    assert e.id == existing.id  # IDは維持


def test_venue_change_from_lower_priority_is_ignored() -> None:
    existing = ev("無線EXPO", source_type="organizer", venue="東京ビッグサイト")
    result, _ = merge(
        [existing], [ev("無線EXPO", source_type="venue", venue="東京ビッグサイト", start_date="2026-11-12", end_date="2026-11-13")]
    )
    assert result[existing.id].start_date == "2026-11-11"  # 主催者HPの値を会場HPで上書きしない


def test_url_only_replaced_by_organizer() -> None:
    existing = ev("無線EXPO", source_type="import", url="https://example.com/expo/")
    result, _ = merge([existing], [ev("無線EXPO", source_type="venue", url="https://example.com/hub/lp/expo.html")])
    assert result[existing.id].url == "https://example.com/expo/"
    result, _ = merge([existing], [ev("無線EXPO", source_type="organizer", url="https://example.com/2026/")])
    assert result[existing.id].url == "https://example.com/2026/"


def test_summary_only_filled_when_empty() -> None:
    existing = ev("無線EXPO", summary="既存の概要")
    result, _ = merge([existing], [ev("無線EXPO", summary="Geminiの別表現の概要")])
    assert result[existing.id].summary == "既存の概要"
    assert result[existing.id].status == "unchanged"


def test_fixed_fields_are_not_overwritten() -> None:
    existing = ev("無線EXPO", venue="幕張メッセ", source_type="import")
    result, _ = merge(
        [existing], [ev("無線EXPO", venue="東京ビッグサイト")], fixes={existing.id: {"id": existing.id, "venue": "幕張メッセ"}}
    )
    assert result[existing.id].venue == "幕張メッセ"


def test_same_name_different_edition_gets_separate_id() -> None:
    tokyo = ev("メタバース総合展", start_date="2026-07-01", end_date="2026-07-03", venue="東京ビッグサイト")
    makuhari = ev("メタバース総合展", start_date="2026-11-20", end_date="2026-11-22", venue="幕張メッセ")
    result, _ = merge([tokyo], [makuhari])
    assert len(result) == 2


def test_match_by_url_family() -> None:
    existing = ev(
        "AI時代の経営変革 EXPO（EC・店舗 Week 秋 内）",
        url="https://www.japan-it.jp/dx/ja-jp/exhibit/data.html",
        start_date="2026-10-21",
        end_date="2026-10-23",
    )
    incoming = ev(
        "第3回 AI時代の経営変革 EXPO 秋",
        url="https://www.japan-it.jp/hub/ja-jp/visit/data.html",
        start_date="2026-10-21",
        end_date="2026-10-23",
    )
    result, stats = merge([existing], [incoming])
    assert len(result) == 1 and stats.new == 0


def test_fuzzy_same_when_start_and_venue_match() -> None:
    existing = ev("第8回 組込み・エッジAI EXPO", url="")
    result, stats = merge([existing], [ev("組込み・エッジAI EXPO 2026", url="https://example.com/esec/")])
    assert len(result) == 1 and stats.new == 0
    assert result[existing.id].url == "https://example.com/esec/"  # 空なら埋める


def test_duplicate_suspected_when_dates_differ() -> None:
    existing = ev("無線EXPO 秋", url="")
    result, stats = merge([existing], [ev("無線 EXPO 秋 2026", url="", start_date="2026-11-25", end_date="2026-11-26")])
    assert len(result) == 2 and stats.needs_review == 1
    flagged = next(e for e in result.values() if e.id != existing.id)
    assert flagged.status == "needs_review" and "重複疑い" in flagged.reason


def test_similar_needs_review_only_without_distinct_urls() -> None:
    existing = ev("医療DX EXPO", url="")
    result, stats = merge([existing], [ev("第2回 医療DX EXPO【東京】", url="https://example.com/mdx/")])
    assert stats.needs_review == 1
    existing2 = ev("スマートビルディング EXPO", url="https://example.com/sb.html")
    result, stats = merge([existing2], [ev("スマートホーム EXPO", url="https://example.com/ho.html")])
    assert stats.needs_review == 0 and stats.new == 1


def test_low_confidence_and_unknown_year_need_review() -> None:
    result, stats = merge([], [ev("謎EXPO", confidence=50), ev("年不明展", year="", start_date="", end_date="")])
    assert stats.needs_review == 2
    assert all(e.status == "needs_review" for e in result.values())


def test_demote_previous() -> None:
    events = [ev("A展", status="new"), ev("B展", status="updated"), ev("C展", status="needs_review")]
    demote_previous(events)
    assert [e.status for e in events] == ["unchanged", "unchanged", "needs_review"]


def test_excluded_is_not_resurrected() -> None:
    existing = ev("除外展", status="excluded")
    result, stats = merge([existing], [ev("除外展")])
    assert len(result) == 1 and stats.new == 0
