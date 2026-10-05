from datetime import date

import pytest

from collector.date_range import DateRange, add_months_end, compute_period


@pytest.mark.parametrize(
    ("today", "months", "expected"),
    [
        (date(2026, 6, 22), 5, date(2026, 11, 30)),  # 設計書の例
        (date(2026, 10, 5), 5, date(2027, 3, 31)),  # 年跨ぎ
        (date(2026, 1, 31), 5, date(2026, 6, 30)),  # 月末起点
        (date(2027, 9, 1), 5, date(2028, 2, 29)),  # うるう年
        (date(2026, 9, 1), 5, date(2027, 2, 28)),  # 平年2月
        (date(2026, 12, 31), 0, date(2026, 12, 31)),
        (date(2026, 8, 15), 12, date(2027, 8, 31)),
    ],
)
def test_add_months_end(today: date, months: int, expected: date) -> None:
    assert add_months_end(today, months) == expected


def test_compute_period() -> None:
    period = compute_period(date(2026, 6, 22), 5)
    assert period.to_dict() == {"from": "2026-06-22", "to": "2026-11-30"}


def test_overlaps() -> None:
    period = DateRange(date(2026, 10, 5), date(2027, 3, 31))
    assert period.overlaps(date(2026, 10, 1), date(2026, 10, 6))  # 開催中
    assert not period.overlaps(date(2026, 9, 1), date(2026, 9, 3))
    assert period.overlaps(date(2027, 3, 31), None)
    assert not period.overlaps(None, None)
