import csv
import io
from datetime import date

from collector.exporter import (
    DETAIL_COLUMNS,
    EXCEL_COLUMNS,
    archive_events,
    load_events,
    read_json,
    write_events,
)
from collector.models import Event


def _event(**kw) -> Event:
    base = dict(
        id="evt_00000001",
        event_name="Japan IT Week 秋 - 情報セキュリティ EXPO",
        parent_event_name="Japan IT Week 秋",
        sub_event_name="情報セキュリティ EXPO",
        start_date="2026-10-21",
        end_date="2026-10-23",
        date_status="fixed",
        venue="幕張メッセ",
        prefecture="千葉県",
        region="関東",
        categories=["AI・DX", "セキュリティ"],
        summary='説明に "引用符" と,カンマ',
        url="https://example.com/",
        status="new",
        first_seen="2026-10-05",
        last_updated="2026-10-05",
    )
    base.update(kw)
    return Event(**base)


def test_csv_format(tmp_path) -> None:
    events = [
        _event(),
        _event(
            id="evt_00000002",
            event_name="未定展",
            parent_event_name="未定展",
            sub_event_name="",
            start_date="",
            end_date="",
            date_status="unknown",
        ),
        _event(id="evt_00000003", status="excluded"),
    ]
    write_events(events, tmp_path)

    raw = (tmp_path / "events.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM
    assert b"\r\n" in raw and raw.count(b"\n") == raw.count(b"\r\n")  # CRLF のみ
    text = raw.decode("utf-8-sig")
    lines = text.split("\r\n")
    assert all(line.startswith('"') for line in lines if line)  # 全フィールド引用符

    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == EXCEL_COLUMNS
    assert len(rows) == 3  # 見出し＋2件（excluded は出さない）
    first = dict(zip(rows[0], rows[1], strict=True))
    assert first["No"] == ""
    assert first["SA部アサイン"] == "" and first["コムシスアサイン"] == ""
    assert first["開始日"] == "2026/10/21" and first["終了日"] == "2026/10/23"
    assert first["対応カテゴリ"] == "AI・DX・セキュリティ"
    assert first["イベント名"] == "Japan IT Week 秋 - 情報セキュリティ EXPO"
    assert first["概要"] == '説明に "引用符" と,カンマ'
    undated = dict(zip(rows[0], rows[2], strict=True))
    assert undated["開始日"] == "" and undated["終了日"] == ""  # 日程未定は末尾・空欄


def test_detail_csv_columns(tmp_path) -> None:
    write_events([_event()], tmp_path)
    rows = list(csv.reader(io.StringIO((tmp_path / "events_detail.csv").read_text(encoding="utf-8-sig"))))
    assert rows[0] == DETAIL_COLUMNS
    row = dict(zip(rows[0], rows[1], strict=True))
    assert row["ステータス"] == "新規"
    assert row["イベントID"] == "evt_00000001"
    assert row["地方区分"] == "関東"


def test_events_json_keeps_excluded(tmp_path) -> None:
    write_events([_event(), _event(id="evt_00000003", status="excluded")], tmp_path)
    assert {e.id for e in load_events(tmp_path / "events.json")} == {"evt_00000001", "evt_00000003"}


def test_archive(tmp_path) -> None:
    events = [
        _event(id="evt_old", start_date="2026-08-01", end_date="2026-09-04"),  # 31日前に終了
        _event(id="evt_edge", start_date="2026-09-05", end_date="2026-09-05"),  # ちょうど30日前
        _event(id="evt_now"),
        _event(id="evt_undated", start_date="", end_date=""),
    ]
    remaining = archive_events(events, date(2026, 10, 5), 30, tmp_path)
    assert {e.id for e in remaining} == {"evt_edge", "evt_now", "evt_undated"}
    assert [d["id"] for d in read_json(tmp_path / "2026.json", [])] == ["evt_old"]
