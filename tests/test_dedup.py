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


# ------------------------------------------------------------------ 同じ開催枠での重複（総合展名の書き方違い）


def sub_ev(parent: str, sub: str, **kw) -> Event:
    return ev(f"{parent} - {sub}", year="2026", **{"parent_event_name": parent, "sub_event_name": sub, **kw})


def test_same_slot_matches_any_candidate_not_only_best() -> None:
    """別都市の同名展（開始日が違う）が一番似ていても、同じ開催枠の候補と同一判定する。"""
    tokyo = sub_ev(
        "Japan DX & AX Week",
        "AI・業務自動化 展",
        id="evt_tokyo001",
        start_date="2026-10-21",
        end_date="2026-10-23",
        venue="幕張メッセ",
        url="",
    )
    kansai = sub_ev(
        "Japan DX & AX Week",
        "AI・業務自動化 展",
        id="evt_kansai01",
        start_date="2026-11-18",
        end_date="2026-11-20",
        venue="インテックス大阪",
        url="",
    )
    incoming = sub_ev(
        "Japan DX & AX Week 関西展",
        "AI・業務自動化 展",
        id="evt_new00001",
        start_date="2026-11-18",
        end_date="2026-11-20",
        venue="インテックス大阪",
        url="",
    )
    result, stats = merge([tokyo, kansai], [incoming])
    assert set(result) == {"evt_tokyo001", "evt_kansai01"} and stats.new == 0 and stats.needs_review == 0


def test_region_sub_name_is_ignored_in_core_key() -> None:
    from collector.dedup import core_key

    a = sub_ev("営業・デジタルマーケティング Week", "関西")
    b = sub_ev("Japan IT Week 関西", "営業・デジタルマーケティング Week")
    assert core_key(a) == core_key(b)


def test_different_sub_events_are_not_merged() -> None:
    from collector.dedup import is_same_event

    a = sub_ev("JAPAN BUILD", "建設DX展", start_date="2026-12-02", venue="東京ビッグサイト")
    b = sub_ev("JAPAN BUILD", "住宅DX展", start_date="2026-12-02", venue="東京ビッグサイト")
    assert not is_same_event(a, b, 90)


def test_explicit_different_years_are_not_merged() -> None:
    from collector.dedup import is_same_event

    a = ev("nano tech 2026（第26回）", start_date="2026-12-16")
    b = ev("nano tech 2027（第26回）", start_date="2026-12-16")
    assert not is_same_event(a, b, 90)


def test_consolidate_merges_and_keeps_history() -> None:
    from collector.dedup import consolidate

    a = sub_ev(
        "Japan DX & AX Week",
        "現場DX EXPO",
        id="evt_aaaaaaaa",
        first_seen="2026-10-05",
        history=[{"date": "2026-10-05", "change": "新規検出"}],
        url="",
    )
    b = sub_ev(
        "Japan DX & AX Week 関西展", "現場DX EXPO", id="evt_bbbbbbbb", first_seen="2026-10-12", url="https://example.com/x", summary="説明"
    )
    other = ev("別の展示会", id="evt_cccccccc", start_date="2026-11-12")
    out, report = consolidate([a, b, other], JUDGE, TODAY)
    assert {e.id for e in out} == {"evt_aaaaaaaa", "evt_cccccccc"} and len(report) == 1
    keeper = next(e for e in out if e.id == "evt_aaaaaaaa")
    assert keeper.url == "https://example.com/x" and keeper.summary == "説明"  # 空の項目は統合した側から埋める
    assert keeper.first_seen == "2026-10-05"
    assert any("統合：evt_bbbbbbbb" in h["change"] for h in keeper.history)


def test_consolidate_clears_review_caused_by_merged_duplicate() -> None:
    from collector.dedup import consolidate

    a = sub_ev("Japan DX & AX Week", "現場DX EXPO", id="evt_aaaaaaaa", status="unchanged")
    b = sub_ev(
        "Japan DX & AX Week 関西展",
        "現場DX EXPO",
        id="evt_bbbbbbbb",
        status="needs_review",
        reason="公式ページに記載／要確認：類似イベントあり：evt_aaaaaaaa「Japan DX & AX Week - 現場DX EXPO」",
        first_seen="2026-09-01",
    )
    out, _ = consolidate([a, b], JUDGE, TODAY)
    assert len(out) == 1 and out[0].status == "unchanged" and "要確認" not in out[0].reason


def test_consolidate_keeps_review_when_other_reasons_remain() -> None:
    from collector.dedup import consolidate

    a = sub_ev("Japan DX & AX Week", "現場DX EXPO", id="evt_aaaaaaaa")
    b = sub_ev(
        "Japan DX & AX Week 関西展",
        "現場DX EXPO",
        id="evt_bbbbbbbb",
        status="needs_review",
        reason="要確認：重複疑い：evt_zzzzzzzz「別」、信頼度50",
        confidence=50,
    )
    out, _ = consolidate([a, b], JUDGE, TODAY)
    assert len(out) == 1 and out[0].confidence == 90  # 統合しても、残す側の状態は変えない


def test_consolidate_ignores_excluded() -> None:
    from collector.dedup import consolidate

    a = ev("無線EXPO", id="evt_aaaaaaaa", status="excluded")
    b = ev("無線EXPO", id="evt_bbbbbbbb")
    out, report = consolidate([a, b], JUDGE, TODAY)
    assert len(out) == 2 and report == []  # 除外済みは統合しない


def undated(name: str, **kw) -> Event:
    base = {"start_date": "", "end_date": "", "date_status": "unknown", "year": "", "venue": ""}
    return ev(name, **{**base, **kw})


def test_consolidate_undated_into_single_dated_event() -> None:
    from collector.dedup import consolidate

    dated = ev("JAPAN BUILD - 住宅DX展", id="evt_dated001", start_date="2026-12-02")
    out, report = consolidate([dated, undated("JAPAN BUILD - 住宅DX展", id="evt_undated1")], JUDGE, TODAY)
    assert [e.id for e in out] == ["evt_dated001"] and len(report) == 1


def test_consolidate_undated_not_linked_when_ambiguous_or_venue_differs() -> None:
    from collector.dedup import consolidate

    tokyo = ev("農業WEEK - スマート農業EXPO", id="evt_tokyo001", start_date="2026-10-07", venue="幕張メッセ")
    osaka = ev("農業WEEK - スマート農業EXPO", id="evt_osaka001", start_date="2027-02-01", venue="インテックス大阪")
    out, _ = consolidate([tokyo, osaka, undated("農業WEEK - スマート農業EXPO", id="evt_undated1")], JUDGE, TODAY)
    assert len(out) == 3  # 同名の確定済みが複数あるので、どれに当たるか決められない
    kumamoto = ev("無線EXPO", id="evt_kuma0001", start_date="2026-11-01", venue="グランメッセ熊本")
    out, _ = consolidate([kumamoto, undated("無線EXPO", id="evt_undated2", venue="幕張メッセ")], JUDGE, TODAY)
    assert len(out) == 2  # 会場が両方にあって違う


def test_consolidate_undated_duplicates_with_same_name() -> None:
    from collector.dedup import consolidate

    out, _ = consolidate(
        [undated("未定展A", id="evt_aaaaaaaa"), undated("未定展A", id="evt_bbbbbbbb"), undated("未定展B", id="evt_cccccccc")], JUDGE, TODAY
    )
    assert len(out) == 2


def test_undated_event_matches_when_date_is_confirmed_without_year() -> None:
    existing = undated("EC・店舗 Week - 売れるEC EXPO", id="evt_aaaaaaaa", status="needs_review")
    incoming = sub_ev("EC・店舗 Week", "売れるEC EXPO", id="evt_bbbbbbbb", start_date="2026-10-21", end_date="2026-10-23")
    result, stats = merge([existing], [incoming])
    assert set(result) == {"evt_aaaaaaaa"} and stats.new == 0
    assert result["evt_aaaaaaaa"].start_date == "2026-10-21"


def test_different_editions_are_not_flagged_as_duplicates() -> None:
    tokyo = sub_ev(
        "Security Days", "セキュリティ展", id="evt_tokyo001", start_date="2026-10-21", venue="幕張メッセ", url="https://a.example/x"
    )
    nagoya = sub_ev(
        "Security Days",
        "セキュリティ展 名古屋",
        id="evt_nagoya01",
        start_date="2026-12-10",
        venue="ポートメッセなごや",
        url="https://a.example/y",
    )
    result, stats = merge([tokyo], [nagoya])
    assert len(result) == 2 and stats.needs_review == 0


# ------------------------------------------------------------------ 要確認の自動解除


def review(name: str, reason: str, **kw) -> Event:
    return ev(name, status="needs_review", reason=reason, source_type="organizer", first_seen="2026-09-01", **kw)


def test_resolve_reviews_clears_stale_flag_without_reason() -> None:
    from collector.dedup import resolve_reviews

    stale = review("無線EXPO", "公式ページに記載", id="evt_aaaaaaaa")  # 理由が上書きされて旗だけが残った状態
    assert resolve_reviews([stale], JUDGE, TODAY) == 1
    assert stale.status == "unchanged" and stale.history[-1]["change"].startswith("要確認の理由がなくなった")


def test_resolve_reviews_keeps_real_reasons() -> None:
    from collector.dedup import resolve_reviews

    low = review("A展", "x／要確認：信頼度40", id="evt_aaaaaaaa", confidence=40)
    no_year = review("B展", "x", id="evt_bbbbbbbb", year="")
    assert resolve_reviews([low, no_year], JUDGE, TODAY) == 0
    assert low.status == no_year.status == "needs_review"
    assert resolve_reviews([no_year], {**JUDGE, "year_unknown_needs_review": False}, TODAY) == 1  # 設定で年不明を許容


def test_resolve_reviews_duplicate_reference() -> None:
    from collector.dedup import resolve_reviews

    other = ev("無線EXPO 関西", id="evt_0000a001", start_date="2026-12-10", venue="インテックス大阪")
    gone = review("無線EXPO", "x／要確認：重複疑い：evt_0000dead「消えた」", id="evt_aaaaaaaa")
    different_edition = review(
        "無線EXPO", "x／要確認：重複疑い：evt_0000a001「無線EXPO 関西」", id="evt_bbbbbbbb", start_date="2026-10-21", venue="幕張メッセ"
    )
    still = review("無線EXPO", "x／要確認：重複疑い：evt_0000a002「同じ頃」", id="evt_cccccccc", start_date="2026-10-21")
    close = ev("無線EXPO（別表記）", id="evt_0000a002", start_date="2026-10-22")
    assert resolve_reviews([gone, different_edition, still, other, close], JUDGE, TODAY) == 2
    assert [e.status for e in (gone, different_edition, still)] == ["unchanged", "unchanged", "needs_review"]


def test_resolve_reviews_leaves_import_reviews() -> None:
    from collector.dedup import resolve_reviews

    imported = ev(
        "取込展", id="evt_aaaaaaaa", status="needs_review", source_type="import", reason="既存の展示会イベントリストから取込（URLなし）"
    )
    assert resolve_reviews([imported], JUDGE, TODAY) == 0 and imported.status == "needs_review"
