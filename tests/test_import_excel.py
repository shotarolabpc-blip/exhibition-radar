import csv
from datetime import date

from collector.import_excel import read_csv_rows, row_to_event, run_import
from collector.models import make_event_id
from collector.settings import Config


def _write_csv(
    path, rows, header=("No", "イベント名", "開始日", "終了日", "会場", "SA部アサイン", "コムシスアサイン", "対応カテゴリ", "概要", "URL")
):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def test_assignment_columns_are_not_read(tmp_path) -> None:
    path = tmp_path / "list.csv"
    _write_csv(
        path,
        [["1", "CEATEC 2026", "2026-10-13", "2026-10-16", "幕張メッセ", "山田", "佐藤", "IT全般", "概要", "https://www.ceatec.com/ja/"]],
    )
    rows = read_csv_rows(path)
    assert set(rows[0]) == {"イベント名", "開始日", "終了日", "会場", "対応カテゴリ", "概要", "URL"}
    assert "山田" not in rows[0].values() and "佐藤" not in rows[0].values()


def test_row_to_event(cfg: Config) -> None:
    e = row_to_event(
        {
            "イベント名": "Japan IT Week 秋 - 情報セキュリティ EXPO",
            "開始日": "2026-10-21",
            "終了日": "2026-10-23",
            "会場": "\t幕張メッセ ",
            "対応カテゴリ": "セキュリティ",
            "概要": "説明",
            "URL": "https://example.com/",
        },
        cfg,
        "2026-10-05",
    )
    assert e is not None
    assert e.id == make_event_id("Japan IT Week 秋", "情報セキュリティ EXPO", "2026")
    assert (e.parent_event_name, e.sub_event_name) == ("Japan IT Week 秋", "情報セキュリティ EXPO")
    assert (e.venue, e.region) == ("幕張メッセ", "関東")
    assert e.status == "unchanged"
    assert e.source_type == "import"


def test_row_to_event_review_cases(cfg: Config) -> None:
    link_text = row_to_event(
        {"イベント名": "某展 2026", "開始日": "2026-11-01", "終了日": "-", "会場": "", "URL": "公式サイト"}, cfg, "2026-10-05"
    )
    assert link_text.status == "needs_review"
    assert link_text.end_date == "2026-11-01"  # 終了日 "-" は1日開催
    month_only = row_to_event({"イベント名": "JANOG60", "開始日": "2027/07", "URL": "https://www.janog.gr.jp/"}, cfg, "2026-10-05")
    assert month_only.start_date == "" and month_only.year == "2027" and month_only.date_status == "unknown"
    no_year = row_to_event({"イベント名": "謎の展示会", "開始日": "", "URL": "https://example.com/"}, cfg, "2026-10-05")
    assert no_year.status == "needs_review"


def test_run_import_separates_editions(tmp_path, cfg: Config) -> None:
    path = tmp_path / "list.csv"
    _write_csv(
        path,
        [
            ["1", "メタバース総合展", "2026-07-03", "2026-07-05", "東京ビッグサイト", "", "", "AI", "", "https://example.com/m"],
            ["2", "メタバース総合展", "2026-11-20", "2026-11-22", "幕張メッセ", "", "", "AI", "", "https://example.com/m"],
            ["3", "メタバース総合展", "2026-11-20", "2026-11-22", "幕張メッセ", "", "", "AI", "", "https://example.com/m"],  # 重複
            ["4", "", "", "", "", "", "", "", "", ""],
        ],
    )
    test_cfg = Config(**{**cfg.__dict__, "root_dir": tmp_path})
    (tmp_path / "config").mkdir()
    summary = run_import(path, test_cfg, date(2026, 10, 5))
    assert summary["unique"] == 2 and summary["duplicates_in_file"] == 1
    assert summary["archived"] == 1 and summary["published"] == 1  # 7月の回はアーカイブ
    assert (tmp_path / "docs" / "data" / "events.csv").exists()
    assert (tmp_path / "config" / "known_urls.yaml").exists()
