// CSV生成（ブラウザ側）。列構成は collector/exporter.py と一致させること。
// 共通仕様：UTF-8 BOM付き、CRLF、全フィールドをダブルクォート。
(function () {
  "use strict";

  const EXCEL_COLUMNS = ["No", "イベント名", "開始日", "終了日", "会場", "SA部アサイン", "コムシスアサイン", "対応カテゴリ", "概要", "URL"];
  const DETAIL_COLUMNS = EXCEL_COLUMNS.concat([
    "総合展名", "構成展名", "都道府県", "地方区分", "ステータス", "信頼度", "収集元",
    "検出キーワード", "判定理由", "初回検出日", "最終更新日", "イベントID",
  ]);
  const STATUS_LABELS = { new: "新規", updated: "更新", unchanged: "変更なし", needs_review: "要確認", excluded: "除外" };

  const slash = (iso) => (iso ? iso.replace(/-/g, "/") : "");

  function excelRow(e) {
    return ["", e.event_name, slash(e.start_date), slash(e.end_date), e.venue, "", "",
      (e.categories || []).join("・"), e.summary, e.url];
  }

  function detailRow(e) {
    return excelRow(e).concat([
      e.parent_event_name, e.sub_event_name, e.prefecture, e.region,
      STATUS_LABELS[e.status] || e.status, String(e.confidence ?? ""), e.source,
      (e.keywords || []).join("・"), e.reason, slash(e.first_seen), slash(e.last_updated), e.id,
    ]);
  }

  function quote(value) {
    return '"' + String(value ?? "").replace(/"/g, '""') + '"';
  }

  function toCsv(header, rows) {
    return "﻿" + [header].concat(rows).map((r) => r.map(quote).join(",")).join("\r\n") + "\r\n";
  }

  function today() {
    const d = new Date();
    return d.getFullYear() + String(d.getMonth() + 1).padStart(2, "0") + String(d.getDate()).padStart(2, "0");
  }

  function download(kind, header, rows) {
    const blob = new Blob([toCsv(header, rows)], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `展示会リスト_${kind}_${today()}.csv`;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 0);
  }

  window.CsvExport = {
    EXCEL_COLUMNS, DETAIL_COLUMNS, STATUS_LABELS,
    excelRow, detailRow, toCsv,
    downloadExcel: (kind, events) => download(kind, EXCEL_COLUMNS, events.map(excelRow)),
    downloadDetail: (kind, events) => download(kind, DETAIL_COLUMNS, events.map(detailRow)),
  };
})();
