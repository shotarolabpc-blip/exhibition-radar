// 展示会レーダー 画面処理（ビルド不要・外部ライブラリなし）
(function () {
  "use strict";

  const REGIONS = ["北海道・東北", "関東", "中部", "近畿", "中国・四国", "九州・沖縄", "オンライン", "不明"];
  const CATEGORIES = ["無線・通信", "AI・DX", "IoT・センサ", "セキュリティ", "ドローン・ロボット", "スマートシティ・自治体DX", "映像・放送", "その他IT"];
  const STATUS_FILTERS = [
    ["new", "新規"], ["updated", "更新"], ["unchanged", "変更なし"], ["needs_review", "要確認"], ["undated", "日程未定"],
  ];
  const STATUS_ORDER = { new: 0, updated: 1, needs_review: 2, unchanged: 3 };
  const DEFAULT_PRESET = "m5";

  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const slash = (iso) => (iso ? iso.replace(/-/g, "/") : "未定");

  let events = [];
  let runs = [];
  const expanded = new Set();
  const state = {
    q: "", from: "", to: "", preset: DEFAULT_PRESET, undated: true,
    regions: new Set(REGIONS), cats: new Set(), venues: new Set(), statuses: new Set(),
    group: false, sort: "start_date", dir: 1,
  };

  // ------------------------------------------------------------ 日付ユーティリティ
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const monthEnd = (d, add) => new Date(d.getFullYear(), d.getMonth() + add + 1, 0);
  function presetRange(preset) {
    const t = new Date();
    switch (preset) {
      case "this": return [iso(new Date(t.getFullYear(), t.getMonth(), 1)), iso(monthEnd(t, 0))];
      case "next": return [iso(new Date(t.getFullYear(), t.getMonth() + 1, 1)), iso(monthEnd(t, 1))];
      case "m3": return [iso(t), iso(monthEnd(t, 3))];
      case "m5": return [iso(t), iso(monthEnd(t, 5))];
      default: return ["", ""];
    }
  }

  // ------------------------------------------------------------ URLパラメータ
  function readUrl() {
    const p = new URLSearchParams(location.search);
    const list = (k) => (p.get(k) ? p.get(k).split(",").filter(Boolean) : null);
    state.q = p.get("q") || "";
    state.preset = p.has("preset") ? p.get("preset") : (p.has("from") || p.has("to") ? "" : DEFAULT_PRESET);
    if (state.preset) [state.from, state.to] = presetRange(state.preset);
    else { state.from = p.get("from") || ""; state.to = p.get("to") || ""; }
    state.undated = p.get("undated") !== "0";
    state.regions = new Set(list("region") || REGIONS);
    state.cats = new Set(list("cat") || []);
    state.venues = new Set(list("venue") || []);
    state.statuses = new Set(list("status") || []);
    state.group = p.get("group") === "1";
    state.sort = p.get("sort") || "start_date";
    state.dir = p.get("dir") === "desc" ? -1 : 1;
  }

  function writeUrl() {
    const p = new URLSearchParams();
    if (state.q) p.set("q", state.q);
    if (state.preset) { if (state.preset !== DEFAULT_PRESET) p.set("preset", state.preset); }
    else { if (state.from) p.set("from", state.from); if (state.to) p.set("to", state.to); if (!state.from && !state.to) p.set("preset", "all"); }
    if (!state.undated) p.set("undated", "0");
    if (state.regions.size !== REGIONS.length) p.set("region", [...state.regions].join(","));
    if (state.cats.size) p.set("cat", [...state.cats].join(","));
    if (state.venues.size) p.set("venue", [...state.venues].join(","));
    if (state.statuses.size) p.set("status", [...state.statuses].join(","));
    if (state.group) p.set("group", "1");
    if (state.sort !== "start_date") p.set("sort", state.sort);
    if (state.dir < 0) p.set("dir", "desc");
    const qs = p.toString();
    history.replaceState(null, "", qs ? `?${qs}` : location.pathname);
  }

  // ------------------------------------------------------------ 絞り込み
  function matches(e) {
    if (e.status === "excluded") return false;
    if (state.q) {
      const hay = `${e.event_name} ${e.summary} ${e.venue} ${(e.categories || []).join(" ")} ${e.prefecture}`.toLowerCase();
      if (!state.q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w))) return false;
    }
    if (!e.start_date) {
      if (!state.undated) return false;
    } else {
      const end = e.end_date || e.start_date;
      if (state.from && end < state.from) return false;
      if (state.to && e.start_date > state.to) return false;
    }
    if (!state.regions.has(e.region || "不明")) return false;
    if (state.cats.size && !(e.categories || []).some((c) => state.cats.has(c))) return false;
    if (state.venues.size && !state.venues.has(e.venue || "（会場未定）")) return false;
    if (state.statuses.size) {
      const ok = (state.statuses.has(e.status)) || (state.statuses.has("undated") && e.date_status === "unknown");
      if (!ok) return false;
    }
    return true;
  }

  function sortValue(e, key) {
    switch (key) {
      case "status": return STATUS_ORDER[e.status] ?? 9;
      case "categories": return (e.categories || []).join("・");
      case "start_date": case "end_date": return e[key] || "9999-99-99";
      default: return e[key] || "";
    }
  }

  function compare(a, b) {
    const va = sortValue(a, state.sort), vb = sortValue(b, state.sort);
    const r = typeof va === "number" ? va - vb : String(va).localeCompare(String(vb), "ja");
    if (r) return r * state.dir;
    return (a.start_date || "9999").localeCompare(b.start_date || "9999") || a.event_name.localeCompare(b.event_name, "ja");
  }

  function filtered() {
    return events.filter(matches).sort(compare);
  }

  // ------------------------------------------------------------ 描画
  function badges(e) {
    const out = [];
    if (e.status === "new") out.push('<span class="badge new">NEW</span>');
    else if (e.status === "updated") out.push('<span class="badge upd">UPD</span>');
    else if (e.status === "needs_review") out.push('<span class="badge review">要確認</span>');
    if (e.date_status === "unknown") out.push('<span class="badge undated">日程未定</span>');
    else if (e.date_status === "tentative") out.push('<span class="badge undated">予定</span>');
    return out.join("");
  }

  function eventRow(e, cls = "") {
    const name = e.url
      ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.event_name)}</a>`
      : esc(e.event_name);
    return `<tr class="ev ${cls}" data-id="${esc(e.id)}" tabindex="0">
      <td class="col-status">${badges(e)}</td>
      <td class="col-name">${name}</td>
      <td class="col-date">${slash(e.start_date)}</td>
      <td class="col-date">${e.start_date ? slash(e.end_date || e.start_date) : "未定"}</td>
      <td>${esc(e.venue)}</td>
      <td class="col-region">${esc(e.region)}</td>
      <td class="col-cat">${esc((e.categories || []).join("・"))}</td>
    </tr>`;
  }

  function groupRows(list) {
    const groups = new Map();
    for (const e of list) {
      const key = e.parent_event_name || e.event_name;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(e);
    }
    const html = [];
    for (const [key, items] of groups) {
      if (items.length === 1) { html.push(eventRow(items[0])); continue; }
      const open = expanded.has(key);
      const starts = items.map((e) => e.start_date).filter(Boolean).sort();
      const ends = items.map((e) => e.end_date || e.start_date).filter(Boolean).sort();
      const venues = [...new Set(items.map((e) => e.venue).filter(Boolean))].join("・");
      const cats = [...new Set(items.flatMap((e) => e.categories || []))].join("・");
      const flags = items.some((e) => e.status === "new") ? '<span class="badge new">NEW</span>' : "";
      html.push(`<tr class="group-row" data-group="${esc(key)}" tabindex="0" aria-expanded="${open}">
        <td class="col-status">${flags}</td>
        <td class="col-name"><span class="caret">${open ? "▼" : "▶"}</span> ${esc(key)} <span class="muted">（構成展 ${items.length}件）</span></td>
        <td class="col-date">${starts.length ? slash(starts[0]) : "未定"}</td>
        <td class="col-date">${ends.length ? slash(ends[ends.length - 1]) : "未定"}</td>
        <td>${esc(venues)}</td>
        <td class="col-region">${esc([...new Set(items.map((e) => e.region))].join("・"))}</td>
        <td class="col-cat">${esc(cats)}</td>
      </tr>`);
      if (open) for (const e of items) html.push(eventRow(e, "child"));
    }
    return html.join("");
  }

  let current = [];
  function render() {
    current = filtered();
    $("tbody").innerHTML = state.group ? groupRows(current) : current.map((e) => eventRow(e)).join("");
    $("empty").hidden = current.length > 0;
    $("count").textContent = `${current.length}件を表示（全${events.filter((e) => e.status !== "excluded").length}件）`;
    document.querySelectorAll("th[data-sort]").forEach((th) => {
      const active = th.dataset.sort === state.sort;
      th.setAttribute("aria-sort", active ? (state.dir > 0 ? "ascending" : "descending") : "none");
    });
    document.querySelectorAll(".presets button").forEach((b) => b.classList.toggle("active", b.dataset.preset === state.preset));
    writeUrl();
  }

  function renderHeader() {
    const run = runs[0];
    const live = events.filter((e) => e.status !== "excluded");
    const count = (s) => live.filter((e) => e.status === s).length;
    $("lastUpdated").textContent = run
      ? `最終更新：${run.run_at.slice(0, 16).replace("T", " ").replace(/-/g, "/")}${run.type === "import" ? "（初期取込）" : ""}`
      : "最終更新：—";
    const errors = run ? (run.errors || []).length : 0;
    $("stats").innerHTML = [
      ["掲載", live.length], ["今回新規", count("new")], ["更新", count("updated")],
      ["要確認", count("needs_review")], ["収集エラー", errors],
    ].map(([k, v]) => `<li><span class="k">${k}</span> <span class="v">${v}</span>件</li>`).join("")
      .replace(/(収集エラー<\/span> <span class="v">\d+<\/span>)件/, "$1");
  }

  function fillMulti(id, options, selected, onChange) {
    const root = $(id);
    const panel = root.querySelector(".multi-panel");
    panel.innerHTML = options.map(([value, label]) =>
      `<label><input type="checkbox" value="${esc(value)}" ${selected.has(value) ? "checked" : ""}> ${esc(label)}</label>`).join("");
    const update = () => {
      const vals = [...panel.querySelectorAll("input:checked")].map((i) => i.value);
      root.querySelector(".multi-value").textContent = vals.length ? `${vals.length}件選択` : "すべて";
    };
    panel.addEventListener("change", () => {
      selected.clear();
      panel.querySelectorAll("input:checked").forEach((i) => selected.add(i.value));
      update();
      onChange();
    });
    update();
  }

  function initControls() {
    $("q").value = state.q;
    $("from").value = state.from;
    $("to").value = state.to;
    $("undated").checked = state.undated;
    $("group").checked = state.group;

    $("regionBoxes").innerHTML = REGIONS.map((r) =>
      `<label class="check"><input type="checkbox" value="${esc(r)}" ${state.regions.has(r) ? "checked" : ""}> ${esc(r)}</label>`).join("");

    const venueCounts = new Map();
    events.filter((e) => e.status !== "excluded").forEach((e) => {
      const v = e.venue || "（会場未定）";
      venueCounts.set(v, (venueCounts.get(v) || 0) + 1);
    });
    const venueOpts = [...venueCounts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ja")).map(([v, n]) => [v, `${v}（${n}）`]);

    fillMulti("catSelect", CATEGORIES.map((c) => [c, c]), state.cats, render);
    fillMulti("venueSelect", venueOpts, state.venues, render);
    fillMulti("statusSelect", STATUS_FILTERS, state.statuses, render);
  }

  function bindEvents() {
    let timer;
    $("q").addEventListener("input", (ev) => { clearTimeout(timer); timer = setTimeout(() => { state.q = ev.target.value.trim(); render(); }, 150); });
    document.querySelectorAll(".presets button").forEach((b) => b.addEventListener("click", () => {
      state.preset = b.dataset.preset;
      [state.from, state.to] = presetRange(state.preset);
      $("from").value = state.from; $("to").value = state.to;
      render();
    }));
    ["from", "to"].forEach((id) => $(id).addEventListener("change", (ev) => { state[id] = ev.target.value; state.preset = ""; render(); }));
    $("undated").addEventListener("change", (ev) => { state.undated = ev.target.checked; render(); });
    $("group").addEventListener("change", (ev) => { state.group = ev.target.checked; render(); });
    $("regionBoxes").addEventListener("change", () => {
      state.regions = new Set([...$("regionBoxes").querySelectorAll("input:checked")].map((i) => i.value));
      render();
    });
    $("clear").addEventListener("click", () => {
      history.replaceState(null, "", location.pathname);
      readUrl(); initControls(); render();
    });
    document.querySelectorAll("th[data-sort]").forEach((th) => th.addEventListener("click", () => {
      if (state.sort === th.dataset.sort) state.dir *= -1; else { state.sort = th.dataset.sort; state.dir = 1; }
      render();
    }));
    document.addEventListener("click", (ev) => {
      document.querySelectorAll("details.multi[open]").forEach((d) => { if (!d.contains(ev.target)) d.open = false; });
    });

    const activate = (ev) => {
      if (ev.target.closest("a")) return;
      const g = ev.target.closest("tr.group-row");
      if (g) {
        const key = g.dataset.group;
        expanded.has(key) ? expanded.delete(key) : expanded.add(key);
        render();
        return;
      }
      const tr = ev.target.closest("tr.ev");
      if (tr) showDetail(events.find((e) => e.id === tr.dataset.id));
    };
    $("tbody").addEventListener("click", activate);
    $("tbody").addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); activate(ev); } });

    $("detailClose").addEventListener("click", () => $("detail").close());
    $("detail").addEventListener("click", (ev) => { if (ev.target === $("detail")) $("detail").close(); });

    $("dlView").addEventListener("click", () => CsvExport.downloadDetail("表示中", current));
    $("dlExcel").addEventListener("click", () => CsvExport.downloadExcel("Excel転記用", current));
    $("dlNew").addEventListener("click", () => {
      const list = events.filter((e) => e.status === "new" || e.status === "updated").sort(compare);
      if (!list.length) { alert("直近の収集で新規・更新になったイベントはありません。"); return; }
      CsvExport.downloadExcel("新規更新", list);
    });
  }

  function showDetail(e) {
    if (!e) return;
    $("detailTitle").textContent = e.event_name;
    const row = (k, v) => (v ? `<dt>${k}</dt><dd>${v}</dd>` : "");
    const period = e.start_date ? `${slash(e.start_date)} 〜 ${slash(e.end_date || e.start_date)}` : "未定";
    const history = (e.history || []).slice().reverse().map((h) => `<li><time>${esc(slash(h.date))}</time> ${esc(h.change)}</li>`).join("");
    $("detailBody").innerHTML = `
      <p class="detail-badges">${badges(e)}</p>
      <dl>
        ${row("会期", esc(period) + (e.date_status === "tentative" ? "（予定）" : ""))}
        ${row("会場", esc([e.venue, e.prefecture && e.prefecture !== e.venue ? `（${e.prefecture}）` : ""].join("")))}
        ${row("地域", esc(e.region))}
        ${row("カテゴリ", esc((e.categories || []).join("・")))}
        ${row("概要", esc(e.summary))}
        ${row("公式URL", e.url ? `<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.url)}</a>` : "")}
        ${row("判定理由", esc(e.reason))}
        ${row("信頼度", esc(e.confidence))}
        ${row("収集元", esc(e.source))}
        ${row("検出キーワード", esc((e.keywords || []).join("・")))}
        ${row("初回検出日", esc(slash(e.first_seen)))}
        ${row("最終更新日", esc(slash(e.last_updated)))}
        ${row("最終確認日", esc(slash(e.last_checked)))}
        ${row("イベントID", `<code>${esc(e.id)}</code>`)}
      </dl>
      ${history ? `<h3>更新履歴</h3><ul class="history">${history}</ul>` : ""}`;
    $("detail").showModal();
  }

  async function load() {
    try {
      const [ev, rn] = await Promise.all([
        fetch("data/events.json", { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(`events.json: HTTP ${r.status}`); return r.json(); }),
        fetch("data/runs.json", { cache: "no-cache" }).then((r) => (r.ok ? r.json() : [])).catch(() => []),
      ]);
      events = ev; runs = rn;
    } catch (err) {
      $("lastUpdated").textContent = "データを読み込めませんでした";
      $("empty").hidden = false;
      $("empty").textContent = `データの読み込みに失敗しました（${err.message}）。ローカルで開く場合は README の手順で簡易サーバを起動してください。`;
      return;
    }
    readUrl();
    renderHeader();
    initControls();
    bindEvents();
    render();
  }

  load();
})();
