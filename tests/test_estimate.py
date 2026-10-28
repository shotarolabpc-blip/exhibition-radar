from datetime import date

from collector.estimate import estimate_for, fill_estimates
from collector.models import Event

JUDGE = {"fuzzy_duplicate_threshold": 90}
TODAY = date(2026, 10, 28)


def ev(name: str, start: str = "", end: str = "", **kw) -> Event:
    base = dict(
        id=f"evt_{abs(hash((name, start))) % 10**8:08d}",
        event_name=name,
        parent_event_name=name,
        start_date=start,
        end_date=end or start,
        venue="東京ビッグサイト",
        status="unchanged",
    )
    base.update(kw)
    return Event(**base)


def test_estimate_from_last_year_same_period() -> None:
    past = ev("Japan IT Week 春", "2026-04-08", "2026-04-10")
    target = ev("Japan IT Week 春", venue="")
    text, basis = estimate_for(target, [past], TODAY, 90)
    assert text == "2027年4月上旬ごろ"
    assert "2026/04/08〜2026/04/10" in basis and "参考" in basis


def test_thirds_of_month() -> None:
    for start, expected in [("2026-05-10", "2027年5月上旬ごろ"), ("2026-05-11", "2027年5月中旬ごろ"), ("2026-05-21", "2027年5月下旬ごろ")]:
        assert estimate_for(ev("A展"), [ev("A展", start)], TODAY, 90)[0] == expected


def test_no_estimate_when_upcoming_same_event_exists_or_too_old() -> None:
    past = ev("A展", "2026-04-08")
    upcoming = ev("A展", "2026-12-02", id="evt_00000009")
    assert estimate_for(ev("A展"), [past, upcoming], TODAY, 90) == ("", "")  # 今後の同名があれば、そちらが次回
    assert estimate_for(ev("A展"), [ev("A展", "2023-04-08")], TODAY, 90) == ("", "")  # 2年より前は推定しない
    assert estimate_for(ev("A展"), [ev("無関係な展示会", "2026-04-08")], TODAY, 90) == ("", "")


def test_older_basis_is_shifted_to_future() -> None:
    text, _ = estimate_for(ev("A展"), [ev("A展", "2025-03-05")], TODAY, 90)
    assert text == "2027年3月上旬ごろ"  # 今日（2026-10-28）より後の最初の同時期


def test_leap_day() -> None:
    assert estimate_for(ev("A展"), [ev("A展", "2026-02-28")], date(2027, 1, 1), 90)[0] == "2027年2月下旬ごろ"


def test_core_match_requires_same_venue() -> None:
    past = Event(
        id="evt_00000001",
        event_name="Japan IT Week 春 - 組込みEXPO",
        parent_event_name="Japan IT Week 春",
        sub_event_name="組込みEXPO",
        start_date="2026-04-08",
        end_date="2026-04-10",
        venue="東京ビッグサイト",
    )
    same_venue = Event(
        id="evt_00000002",
        event_name="Japan IT Week - 組込みEXPO",
        parent_event_name="Japan IT Week",
        sub_event_name="組込みEXPO",
        venue="東京ビッグサイト",
        date_status="unknown",
    )
    other_venue = Event(
        id="evt_00000003",
        event_name="Japan IT Week - 組込みEXPO",
        parent_event_name="Japan IT Week",
        sub_event_name="組込みEXPO",
        venue="インテックス大阪",
        date_status="unknown",
    )
    assert estimate_for(same_venue, [past], TODAY, 90)[0] == "2027年4月上旬ごろ"
    assert estimate_for(other_venue, [past], TODAY, 90) == ("", "")


def test_fill_estimates_resets_and_skips_dated() -> None:
    dated = ev("A展", "2026-12-02", estimate="古い予想", estimate_basis="x")
    undated = ev("B展", estimate="古い予想")
    archived = [ev("B展", "2026-03-01")]
    assert fill_estimates([dated, undated], archived, TODAY, JUDGE) == 1
    assert dated.estimate == "" and undated.estimate == "2027年3月上旬ごろ"
