from collector.models import Event
from collector.overrides import apply_overrides


def _ev(id_: str, **kw) -> Event:
    base = dict(id=id_, event_name=id_, parent_event_name=id_, url=f"https://example.com/{id_}", status="unchanged")
    base.update(kw)
    return Event(**base)


def _apply(cfg, events, overrides):
    full = {"exclude": [], "fix": [], "merge": [], "confirm": [], **overrides}
    return {e.id: e for e in apply_overrides(events, full, cfg.venues, cfg.categories, "2026-10-05")}


def test_exclude_by_id_and_url(cfg) -> None:
    result = _apply(
        cfg,
        [_ev("evt_a"), _ev("evt_b", url="https://example.com/old-event/x"), _ev("evt_c")],
        {"exclude": [{"id": "evt_a", "reason": "無関係"}, {"url_contains": "old-event"}]},
    )
    assert result["evt_a"].status == "excluded"
    assert result["evt_b"].status == "excluded"
    assert result["evt_c"].status == "unchanged"
    assert result["evt_a"].history[-1]["change"] == "除外：無関係"


def test_fix_updates_fields_and_region(cfg) -> None:
    result = _apply(
        cfg,
        [_ev("evt_a", venue="東京ビッグサイト", prefecture="東京都", region="関東")],
        {"fix": [{"id": "evt_a", "venue": "インテックス", "categories": ["セキュリティ"]}]},
    )
    e = result["evt_a"]
    assert e.venue == "インテックス大阪"
    assert (e.prefecture, e.region) == ("大阪府", "近畿")
    assert e.categories == ["セキュリティ"]
    assert "人手修正" in e.history[-1]["change"]


def test_fix_is_idempotent(cfg) -> None:
    events = [_ev("evt_a", venue="幕張メッセ")]
    overrides = {"fix": [{"id": "evt_a", "venue": "幕張メッセ"}]}
    result = _apply(cfg, events, overrides)
    assert result["evt_a"].history == []  # 変化なしなら履歴を増やさない


def test_merge(cfg) -> None:
    keep = _ev("evt_keep", history=[{"date": "2026-09-01", "change": "新規検出"}])
    remove = _ev("evt_rm", history=[{"date": "2026-09-02", "change": "新規検出"}])
    result = _apply(cfg, [keep, remove], {"merge": [{"keep": "evt_keep", "remove": "evt_rm", "reason": "重複"}]})
    assert set(result) == {"evt_keep"}
    assert len(result["evt_keep"].history) == 3


def test_confirm(cfg) -> None:
    result = _apply(cfg, [_ev("evt_a", status="needs_review"), _ev("evt_b", status="new")], {"confirm": [{"id": "evt_a"}, {"id": "evt_b"}]})
    assert result["evt_a"].status == "unchanged"
    assert result["evt_a"].history[-1]["change"] == "確認済み"
    assert result["evt_b"].status == "new"  # 要確認以外は変えない


def test_unexclude_when_rule_removed(cfg) -> None:
    result = _apply(cfg, [_ev("evt_a", status="excluded")], {})
    assert result["evt_a"].status == "unchanged"
