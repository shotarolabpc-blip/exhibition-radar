"""対象期間の算出（C-01）。"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def overlaps(self, start: date | None, end: date | None) -> bool:
        """会期 [start, end] が期間と重なるか。end が無ければ start のみで判定する。"""
        if start is None:
            return False
        last = end or start
        return start <= self.end and last >= self.start

    def to_dict(self) -> dict[str, str]:
        return {"from": self.start.isoformat(), "to": self.end.isoformat()}


def add_months_end(d: date, months: int) -> date:
    """d の months か月後の月末日を返す。"""
    index = d.month - 1 + months
    year = d.year + index // 12
    month = index % 12 + 1
    return date(year, month, calendar.monthrange(year, month)[1])


def compute_period(today: date, months_ahead: int) -> DateRange:
    """実行日〜months_ahead か月後の月末。"""
    return DateRange(start=today, end=add_months_end(today, months_ahead))
