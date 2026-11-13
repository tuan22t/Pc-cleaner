"use strict";
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("token") || (() => { try { return sessionStorage.getItem("pcc_token"); } catch (e) { return ""; } })() || "";
try { sessionStorage.setItem("pcc_token", TOKEN); } catch (e) {}
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const COLORS = ["--c1", "--c2", "--c3", "--c5", "--c6", "--c7", "--c4", "--c8"].map((v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim());
const SELECTABLE = { large: "File lớn", old: "File cũ", dups: "File trùng lặp", similar: "Ảnh giống nhau" };

const state = {
  scanId: null, dirId: 0, view: "home", info: null,
  sel: { large: new Map(), old: new Map(), dups: new Map(), similar: new Map() }, // path -> size
  shown: { large: [], old: [], dups: [], similar: [] },                            // selectable paths on screen
  junk: null, startup: null, startupFilter: "all", restorePointDone: false, org: null,
  polling: null, lastJob: null,
};

async function api(path, body) {
  const opt = { headers: { "X-Token": TOKEN } };
  if (body !== undefined) { opt.method = "POST"; opt.body = JSON.stringify(body); opt.headers["Content-Type"] = "application/json"; }
  const r = await fetch("/api/" + path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

function fmt(n) {
  if (n == null) return "";
  const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return (i ? n.toFixed(n < 10 ? 1 : 0).replace(".", ",") : n) + " " + u[i];
}
const num = (n) => Number(n || 0).toLocaleString("vi-VN");
const fmtDate = (t) => new Date(t * 1000).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
const fmtDay = (t) => new Date(t * 1000).toLocaleDateString("vi-VN");
function ago(t) {
  const d = (Date.now() / 1000 - t) / 86400;
  if (d < 1) return "hôm nay"; if (d < 30) return Math.floor(d) + " ngày trước";
  if (d < 365) return Math.floor(d / 30) + " tháng trước"; return Math.floor(d / 365) + " năm trước";
}
function dur(s) { s = Math.round(s); return s < 60 ? s + " giây" : Math.floor(s / 60) + " phút " + (s % 60) + " giây"; }
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg, opts = {}) {
  const t = $("#toast"); $("#toastMsg").textContent = msg;
  t.className = "toast" + (opts.err ? " err" : "");
  const b = $("#toastAct");
  if (opts.action) { b.textContent = opts.action; b.classList.remove("hidden"); b.onclick = () => { t.classList.add("hidden"); opts.onAction(); }; }
  else b.classList.add("hidden");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), opts.action ? 10000 : 5000);
}
function dialog(title, html, ok = "Đồng ý", cancel = "Hủy", alt = null) {
  return new Promise((res) => {
    $("#modalTitle").textContent = title; $("#modalBody").innerHTML = html;
    $("#modalOk").textContent = ok; $("#modalCancel").textContent = cancel || "";
    $("#modalCancel").classList.toggle("hidden", !cancel);
    $("#modalAlt").textContent = alt || ""; $("#modalAlt").classList.toggle("hidden", !alt);
    $("#modal").classList.remove("hidden"); $("#modalOk").focus();
    const done = (v) => { $("#modal").classList.add("hidden"); $("#modalOk").onclick = $("#modalCancel").onclick = $("#modalAlt").onclick = null; res(v); };
    $("#modalOk").onclick = () => done(true); $("#modalCancel").onclick = () => done(false); $("#modalAlt").onclick = () => done("alt");
  });
}
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#modal").classList.contains("hidden")) $("#modalCancel").click(); });

// ---------- navigation ----------
function show(view) {
  state.view = view;
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  $$("nav a[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  updateActionBar();
  $("main").scrollTop = 0;
  render(view);
}
$$("nav a[data-view]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); if (!a.classList.contains("disabled")) show(a.dataset.view); }));
function updateNav() {
  $$("nav a[data-needs-scan]").forEach((a) => a.classList.toggle("disabled", !state.scanId));
  $("#navHint").classList.toggle("hidden", !!state.scanId);
}

async function render(view) {
  try {
    if (view === "home") return await renderHome();
    if (view === "quarantine") return await renderQuarantine();
    if (view === "junk") return renderJunk();
    if (view === "startup") return await renderStartup();
    if (view === "organize") return renderOrganize();
    if (view === "schedule") return await renderSchedule();
    if (!state.scanId) return show("home");
    if (view === "usage") return await renderUsage();
    if (view === "large") return await renderLarge();
    if (view === "old") return await renderOld();
    if (view === "types") return await renderTypes();
    if (view === "dups") return await renderDups();
    if (view === "similar") return await renderSimilar();
  } catch (e) { toast(e.message, { err: true }); }
}

// ---------- home ----------
async function renderHome() {
  const info = state.info = await api("info");
  $("#pickFolderBtn").classList.toggle("hidden", !info.can_pick_folder);
  $("#locations").innerHTML = info.locations.map((l, i) => {
    const pct = l.total ? (l.used / l.total) * 100 : 0;
    const isHome = l.path === info.home;
    return `<div class="card ${isHome ? "recommended" : ""}">
      ${isHome ? '<span class="ribbon">Nên bắt đầu ở đây</span>' : ""}
      <h3>${isHome ? "👤" : "💽"} ${esc(l.label)}</h3><div class="path">${esc(l.path)}</div>
      <div class="meter ${pct > 90 ? "high" : pct > 75 ? "mid" : ""}"><div style="width:${pct.toFixed(1)}%"></div></div>
      <div class="free">Còn trống <b>${fmt(l.free)}</b> <span class="muted">/ ${fmt(l.total)}</span></div>
      ${pct > 90 ? '<div class="warn-text">⚠️ Ổ đĩa sắp đầy</div>' : ""}
      <button class="btn ${isHome ? "primary" : ""}" data-scan="${esc(l.path)}">Quét ${isHome ? "thư mục này" : "ổ này"}</button>
      ${isHome ? "" : '<div class="hint">Quét cả ổ có thể mất vài phút.</div>'}</div>`;
  }).join("");
  $$("[data-scan]").forEach((b) => b.onclick = () => startScan(b.dataset.scan));
  await loadScans();
  const scans = await api("scans");
  $("#recentScans").innerHTML = scans.length ? `<div class="list">${scans.map((s) => `
    <div class="row"><span class="ico">🗂️</span><div class="name"><div class="t">${esc(s.root)}</div><div class="p">Quét lúc ${fmtDate(s.finished)} · ${num(s.file_count)} file${s.error_count ? ` · bỏ qua ${num(s.error_count)} mục không có quyền đọc` : ""}</div></div>
    <div class="size">${fmt(s.total_size)}</div><button class="btn small" data-open="${s.id}">Xem báo cáo</button></div>`).join("")}</div>`
    : `<div class="list"><div class="empty">Chưa quét lần nào. Hãy bấm “Quét” ở một ô phía trên.</div></div>`;
  $$("[data-open]").forEach((b) => b.onclick = () => { selectScan(+b.dataset.open); show("usage"); });
}
$("#customScanBtn").onclick = () => { const p = $("#customPath").value.trim(); if (p) startScan(p); else { toast("Hãy nhập đường dẫn thư mục trước."); $("#customPath").focus(); } };
$("#customPath").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#customScanBtn").click(); });
$("#pickFolderBtn").onclick = async () => {
  try { const r = await api("pick-folder", {}); if (r.path) startScan(r.path); } catch (e) { toast(e.message, { err: true }); }
};

async function loadScans() {
  const scans = await api("scans");
  $("#scanSelect").innerHTML = scans.length ? scans.map((s) => `<option value="${s.id}">${esc(s.root)} (${fmtDay(s.finished)})</option>`).join("") : `<option value="">Chưa có</option>`;
  if (scans.length && !scans.find((s) => s.id === state.scanId)) state.scanId = scans[0].id;
  if (state.scanId) $("#scanSelect").value = state.scanId;
  updateNav();
}
$("#scanSelect").onchange = (e) => { selectScan(+e.target.value); render(state.view); };
function selectScan(id) { state.scanId = id; state.dirId = 0; Object.values(state.sel).forEach((s) => s.clear()); $("#scanSelect").value = id; updateNav(); updateActionBar(); }

// ---------- background jobs ----------
async function startScan(path) {
  try { await api("scan", { path }); pollJob(); } catch (e) { toast(e.message, { err: true }); }
}
$("#jobCancel").onclick = () => api("cancel", {});
function pollJob() {
  clearInterval(state.polling);
  const tick = async () => {
    const j = await api("job").catch(() => null);
    if (!j) return;
    const bar = $("#jobBar");
    const busy = j.state === "running";
    $$("[data-scan], #customScanBtn, #dupRun, #simRun, #junkRun, #pickFolderBtn").forEach((b) => b.disabled = busy);
    if (busy) {
      bar.classList.remove("hidden");
      const p = j.progress || {}; const el = dur(Date.now() / 1000 - j.started);
      if (j.kind === "scan") {
        $("#jobTitle").textContent = `Đang quét ${j.root} — đã tìm thấy ${num(p.files)} file (${fmt(p.bytes || 0)})`;
        $("#jobDetail").textContent = `${el} · ${p.current || ""}`;
        $(".progress").classList.add("indeterminate"); $("#jobProgress").style.width = "30%";
      } else {
        const pct = p.total ? Math.floor(100 * p.done / p.total) : 0;
        const what = { duplicates: "Đang tìm file trùng", similar: "Đang tìm ảnh giống nhau", junk: "Đang kiểm tra rác hệ thống" }[j.kind] || "Đang xử lý";
        $("#jobTitle").textContent = `${what}: ${p.stage || ""}${p.total ? ` (${pct}%)` : ""}`;
        $("#jobDetail").textContent = `${el}${p.total ? ` · ${num(p.done)}/${num(p.total)} file` : ""}`;
        $(".progress").classList.toggle("indeterminate", !p.total);
        $("#jobProgress").style.width = p.total ? pct + "%" : "30%";
      }
      return;
    }
    clearInterval(state.polling); bar.classList.add("hidden");
    if (state.lastJob === j.started) return;
    state.lastJob = j.started;
    if (j.state === "done" && j.kind === "scan") { await loadScans(); selectScan(j.result); toast("Quét xong. Đây là các thư mục chiếm nhiều chỗ nhất."); show("usage"); }
    else if (j.state === "done" && j.kind === "duplicates") { toast(j.result ? `Tìm thấy ${j.result} nhóm file trùng.` : "Không có file trùng nào. Máy anh/chị khá gọn!"); if (state.view === "dups") renderDups(); }
    else if (j.state === "done" && j.kind === "similar") { toast(j.result ? `Tìm thấy ${j.result} nhóm ảnh giống nhau.` : "Không có ảnh nào giống nhau."); if (state.view === "similar") renderSimilar(); }
    else if (j.state === "done" && j.kind === "junk") { state.junk = j.result; renderJunk(); }
    else if (j.state === "cancelled") toast("Đã dừng lại.");
    else if (j.state === "error") toast("Có lỗi: " + j.error, { err: true });
  };
  tick(); state.polling = setInterval(tick, 400);
}

// ---------- disk usage ----------
function squarify(items, x, y, w, h) {
  const out = []; const total = items.reduce((a, b) => a + b.size, 0); if (!total) return out;
  const scale = (w * h) / total; let rest = items.map((it) => ({ it, a: it.size * scale }));
  while (rest.length) {
    const short = Math.min(w, h); let row = [], best = Infinity;
    for (const r of rest) {
      const test = [...row, r]; const s = test.reduce((a, b) => a + b.a, 0);
      const worst = Math.max(...test.map((t) => Math.max((short * short * t.a) / (s * s), (s * s) / (short * short * t.a))));
      if (worst > best) break; best = worst; row = test;
    }
    rest = rest.slice(row.length);
    const s = row.reduce((a, b) => a + b.a, 0); const thick = s / short; let off = 0;
    for (const r of row) {
      const len = r.a / thick;
      if (w >= h) out.push({ it: r.it, x, y: y + off, w: thick, h: len }); else out.push({ it: r.it, x: x + off, y, w: len, h: thick });
      off += len;
    }
    if (w >= h) { x += thick; w -= thick; } else { y += thick; h -= thick; }
  }
  return out;
}
const revealBtn = (p) => `<button class="btn small ghost" data-reveal="${esc(p)}" title="Mở thư mục chứa file này trong ${state.info && state.info.platform === "mac" ? "Finder" : "File Explorer"}">📂 Xem vị trí</button>`;

async function renderUsage() {
  const d = await api(`scan/${state.scanId}/children?dir=${state.dirId}`);
  $("#crumbs").innerHTML = (d.crumbs.length > 1 ? `<a data-dir="${d.crumbs[d.crumbs.length - 2].id}" class="back">← Quay lại</a>` : "") +
    d.crumbs.map((c, i) => (i ? '<span class="sep">›</span>' : "") + `<a data-dir="${c.id}">${esc(c.name)}</a>`).join("") +
    ` <span class="muted">· tổng ${fmt(d.dir.size)} · ${num(d.dir.count)} file</span>`;
  const total = d.dir.size || 1;
  $("#usageList").innerHTML = `<div class="row head"><span class="ico"></span><div class="name">Tên</div><div class="bar-h">Tỉ lệ</div><div class="size">Dung lượng</div><div class="acts"></div></div>` +
    (d.items.length ? d.items.map((it) => `
    <div class="row ${it.type}" ${it.type === "dir" ? `data-dir="${it.id}" title="Bấm để xem bên trong"` : ""}>
      <span class="ico">${it.type === "dir" ? "📁" : "📄"}</span>
      <div class="name"><div class="t">${esc(it.name)}</div>${it.type === "dir" ? `<div class="p">${num(it.count)} file</div>` : `<div class="p">sửa ${ago(it.mtime)}</div>`}</div>
      <div class="bar" title="${Math.round(100 * it.size / total)}% của thư mục hiện tại"><div style="width:${(100 * it.size / total).toFixed(1)}%"></div></div>
      <div class="size">${fmt(it.size)}</div>
      <div class="acts">${revealBtn(it.path)}</div>
    </div>`).join("") : `<div class="empty">Thư mục này trống.</div>`);
  const tm = $("#treemap"); const W = tm.clientWidth, H = tm.clientHeight;
  const tiles = squarify(d.items.filter((i) => i.size > 0).slice(0, 40), 0, 0, W, H);
  tm.innerHTML = tiles.map((t, i) => `<div class="tile ${t.it.type}" ${t.it.type === "dir" ? `data-dir="${t.it.id}"` : ""} title="${esc(t.it.name)} · ${fmt(t.it.size)}"
     style="left:${t.x}px;top:${t.y}px;width:${t.w}px;height:${t.h}px;background:${COLORS[i % COLORS.length]}">${t.w > 60 && t.h > 30 ? `${t.it.type === "dir" ? "📁 " : ""}${esc(t.it.name)}<small>${fmt(t.it.size)}</small>` : ""}</div>`).join("");
  $$("#view-usage [data-dir]").forEach((el) => el.addEventListener("click", (e) => { if (e.target.closest("button")) return; state.dirId = +el.dataset.dir; renderUsage(); }));
  bindReveal("#view-usage");
}
function bindReveal(scope) {
  $$(scope + " [data-reveal]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); api("reveal", { path: b.dataset.reveal }).catch((er) => toast(er.message, { err: true })); });
}

// ---------- selectable file lists ----------
function fileRows(list, key) {
  const sel = state.sel[key];
  const head = `<div class="row head"><span class="cb"></span><div class="name">Tên file</div><span class="kind">Loại</span><span class="when">Sửa lần cuối</span><div class="size">Dung lượng</div><span class="acts"></span></div>`;
  if (!list.length) return `<div class="empty">Không có file nào phù hợp. Thử chọn mức nhỏ hơn ở phía trên.</div>`;
  return head + list.map((f) => `
    <label class="row ${f.protected ? "locked" : "pick"}" ${f.protected ? 'title="File của hệ thống hoặc chương trình, ứng dụng không cho phép dọn để bảo vệ máy."' : ""}>
      <span class="cb">${f.protected ? "🔒" : `<input type="checkbox" data-sel="${key}" data-size="${f.size}" value="${esc(f.path)}" ${sel.has(f.path) ? "checked" : ""}>`}</span>
      <div class="name"><div class="t">${esc(f.name)}</div><div class="p">${esc(f.path)}</div></div>
      <span class="kind"><span class="tag ${f.protected ? "keep" : ""}">${f.protected ? "Hệ thống" : esc(f.category)}</span></span>
      <span class="when" title="${fmtDay(f.mtime)}">${ago(f.mtime)}</span>
      <div class="size">${fmt(f.size)}</div>
      <span class="acts">${revealBtn(f.path)}</span>
    </label>`).join("");
}
function bindSelection(scope, key) {
  state.shown[key] = $$(scope + ` [data-sel="${key}"]`).map((c) => c.value);
  $$(scope + ` [data-sel="${key}"]`).forEach((c) => c.onchange = () => {
    c.checked ? state.sel[key].set(c.value, +c.dataset.size) : state.sel[key].delete(c.value);
    c.closest(".row, .photo").classList.toggle("checked", c.checked);
    updateActionBar();
  });
  $$(scope + ` [data-sel="${key}"]:checked`).forEach((c) => c.closest(".row, .photo").classList.add("checked"));
  bindReveal(scope); updateActionBar();
}
function updateActionBar() {
  const key = state.view in SELECTABLE ? state.view : null;
  const bar = $("#actionBar");
  if (!key || !state.shown[key].length) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  const sel = state.sel[key]; let total = 0; sel.forEach((s) => total += s);
  $("#selInfo").innerHTML = sel.size ? `Đã chọn <b>${num(sel.size)} file</b> · sẽ giải phóng <b>${fmt(total)}</b>` : `<span class="muted">Chưa chọn file nào</span>`;
  $("#selClean").disabled = !sel.size; $("#selClear").disabled = !sel.size;
  $("#selClean").textContent = sel.size ? `🧹 Dọn ${num(sel.size)} file` : "🧹 Dọn các file đã chọn";
  const all = state.shown[key];
  $("#selAll").checked = all.length > 0 && all.every((p) => sel.has(p));
  $("#selAll").indeterminate = !$("#selAll").checked && all.some((p) => sel.has(p));
  $("#actionBar .selall").classList.toggle("hidden", key === "dups" || key === "similar");
}
$("#selAll").onchange = (e) => {
  const key = state.view; $$(`#view-${key} [data-sel="${key}"]`).forEach((c) => { if (c.checked !== e.target.checked) { c.checked = e.target.checked; c.onchange(); } });
};
$("#selClear").onclick = () => { const key = state.view; $$(`#view-${key} [data-sel="${key}"]:checked`).forEach((c) => { c.checked = false; c.onchange(); }); };

async function renderLarge() {
  const list = await api(`scan/${state.scanId}/large?min=${$("#largeMin").value}`);
  $("#largeList").innerHTML = fileRows(list, "large");
  bindSelection("#view-large", "large");
}
$("#largeMin").onchange = renderLarge;
async function renderOld() {
  const list = await api(`scan/${state.scanId}/old?days=${$("#oldDays").value}&min=${$("#oldMin").value}`);
  $("#oldList").innerHTML = fileRows(list, "old");
  bindSelection("#view-old", "old");
}
$("#oldDays").onchange = $("#oldMin").onchange = renderOld;

async function renderTypes() {
  const d = await api(`scan/${state.scanId}/summary`);
  const bars = (rows, label) => { const m = rows.length ? rows[0].size : 1; return rows.map((r, i) => `
    <div class="b"><div>${esc(label(r))} <span class="muted">· ${num(r.count)} file</span></div>
    <div class="track"><div style="width:${(100 * r.size / m).toFixed(1)}%;background:${COLORS[i % COLORS.length]}"></div></div><div class="v">${fmt(r.size)}</div></div>`).join(""); };
  $("#catList").innerHTML = bars(d.categories, (r) => r.category);
  $("#extList").innerHTML = bars(d.extensions, (r) => (r.ext.startsWith("(") ? r.ext : "." + r.ext));
}

// ---------- duplicates ----------
$("#dupRun").onclick = async () => {
  try { await api("duplicates", { scan_id: state.scanId, min_size: +$("#dupMin").value }); pollJob(); } catch (e) { toast(e.message, { err: true }); }
};
async function renderDups() {
  const d = await api(`scan/${state.scanId}/duplicates`);
  const sel = state.sel.dups; sel.clear();
  $("#dupSummary").innerHTML = d.group_count
    ? `Tìm thấy <b>${num(d.group_count)} nhóm</b> file trùng, dọn bản thừa sẽ giải phóng khoảng <b>${fmt(d.wasted)}</b>.<br><span class="muted">Ứng dụng đã tự chọn sẵn các bản thừa và giữ lại một bản, ưu tiên bản nằm ngoài Downloads/Desktop và không có chữ “copy” (có nhãn “Giữ lại”). Anh/chị có thể đổi lựa chọn.</span>`
    : `<div class="empty">Chưa có kết quả. Bấm “Tìm file trùng” để bắt đầu.</div>`;
  $("#dupList").innerHTML = d.groups.map((g) => {
    let kept = false;
    const rows = g.files.map((f) => {
      let keep = false;
      if (!kept && f.exists) { keep = true; kept = true; }
      if (!keep && !f.protected && f.exists) sel.set(f.path, g.size);
      const name = f.path.split(/[\\/]/).pop();
      const lockTitle = f.protected ? 'title="File của hệ thống, không thể dọn."' : "";
      return `<label class="row ${f.protected || !f.exists ? "locked" : "pick"}" ${lockTitle}>
        <span class="cb">${f.protected ? "🔒" : !f.exists ? "" : `<input type="checkbox" data-sel="dups" data-size="${g.size}" value="${esc(f.path)}" ${sel.has(f.path) ? "checked" : ""}>`}</span>
        <div class="name"><div class="t">${esc(name)}</div><div class="p">${esc(f.path)}</div></div>
        <span class="kind">${keep ? '<span class="tag ok">✓ Giữ lại</span>' : f.protected ? '<span class="tag keep">Hệ thống</span>' : !f.exists ? '<span class="tag">Đã dọn</span>' : '<span class="tag">Bản thừa</span>'}</span>
        <span class="when">${ago(f.mtime)}</span>
        <span class="acts">${f.exists ? revealBtn(f.path) : ""}</span></label>`;
    }).join("");
    return `<div class="group"><div class="group-head"><b>${g.files.length} bản giống hệt nhau</b><span>${fmt(g.size)} mỗi bản</span><span class="muted">thừa ${fmt(g.wasted)}</span></div>${rows}</div>`;
  }).join("");
  bindSelection("#view-dups", "dups");
}

// ---------- cleaning ----------
$("#selClean").onclick = async () => {
  const key = state.view; const sel = state.sel[key]; const files = [...sel.keys()];
  if (!files.length) return;
  let total = 0; sel.forEach((s) => total += s);
  const ok = await dialog(`Dọn ${num(files.length)} file (${fmt(total)})?`,
    `<p>Các file này sẽ được chuyển vào <b>Khu cách ly</b>, <b>chưa bị xóa vĩnh viễn</b>. Nếu cần, anh/chị có thể lấy lại bất cứ lúc nào.</p>
     ${key === "dups" ? "<p class=\"muted\">Trước khi dọn, ứng dụng sẽ kiểm tra lại nội dung từng file và luôn giữ lại ít nhất một bản.</p>" : ""}
     <div class="list small scroll">${files.slice(0, 50).map((f) => `<div class="row">${esc(f)}</div>`).join("")}${files.length > 50 ? `<div class="row muted">… và ${num(files.length - 50)} file khác</div>` : ""}</div>`,
    "🧹 Dọn ngay");
  if (!ok) return;
  try {
    const body = { paths: files, reason: SELECTABLE[key] };
    if (key === "dups") body.dup_scan_id = state.scanId;
    if (key === "similar") body.similar_scan_id = state.scanId;
    const r = await api("quarantine", body);
    sel.clear(); refreshBadge();
    if (r.failed.length) {
      await dialog(r.moved ? `Đã dọn ${num(r.moved)} file, ${num(r.failed.length)} file được giữ nguyên` : "Không dọn được file nào",
        `<p>${r.moved ? `Đã chuyển ${fmt(r.bytes)} vào khu cách ly. ` : ""}Những file dưới đây được giữ nguyên:</p>
         <div class="list small scroll">${r.failed.map((f) => `<div class="row"><div class="name"><div class="t">${esc(f.path)}</div><div class="p">${esc(f.error)}</div></div></div>`).join("")}</div>`, "Đã hiểu", null);
    }
    if (r.moved) toast(`Đã dọn ${num(r.moved)} file (${fmt(r.bytes)}).`, { action: "↩ Hoàn tác", onAction: () => undo(r.batch_id) });
    render(state.view);
  } catch (e) { toast(e.message, { err: true }); }
};
async function undo(batchId) {
  try {
    const r = await api("restore", { batch_id: batchId });
    toast(`Đã trả ${num(r.restored)} file về chỗ cũ.` + (r.failed.length ? ` ${num(r.failed.length)} file không trả về được.` : ""), { err: r.failed.length > 0 });
    refreshBadge(); render(state.view);
  } catch (e) { toast(e.message, { err: true }); }
}

// ---------- quarantine ----------
async function refreshBadge() {
  const batches = await api("batches").catch(() => []);
  const pending = batches.filter((b) => !b.moves).reduce((a, b) => a + (b.pending || 0), 0);
  $("#qBadge").textContent = num(pending); $("#qBadge").classList.toggle("hidden", !pending);
  return batches;
}
async function renderQuarantine() {
  const [batches, log] = await Promise.all([refreshBadge(), api("log")]);
  const visible = batches.filter((b) => b.files > 0);
  const pendingFiles = visible.filter((b) => !b.moves).reduce((a, b) => a + (b.pending || 0), 0);
  const pendingBytes = visible.filter((b) => b.pending && !b.moves).reduce((a, b) => a + (b.bytes || 0), 0);
  $("#qSummary").innerHTML = pendingFiles ? `Đang cất giữ <b>${num(pendingFiles)} file</b> (khoảng ${fmt(pendingBytes)}).` : "";
  $("#batchList").innerHTML = visible.length ? `<div class="row head"><div class="name">Lần dọn</div><span class="kind">Trạng thái</span><div class="size">Dung lượng</div><span class="acts2"></span></div>` + visible.map((b) => `
    <div class="row"><div class="name"><div class="t">${esc(b.reason || "Dọn dẹp")} · ${num(b.files)} file</div><div class="p">${fmtDate(b.ts)}</div></div>
    <span class="kind"><span class="tag ${b.pending ? "" : "ok"}">${b.moves ? (b.pending ? "Đã sắp xếp" : "Đã hoàn tác") : b.pending ? "Đang cất giữ" : b.purged ? "Đã xóa vĩnh viễn" : "Đã lấy lại"}</span></span>
    <div class="size">${fmt(b.bytes)}</div>
    <span class="acts2">${b.pending && b.moves ? `<button class="btn small primary" data-restore="${b.batch_id}">↩ Hoàn tác</button>` : b.pending ? `<button class="btn small primary" data-restore="${b.batch_id}">↩ Lấy lại</button>
    <button class="btn small ghost danger-text" data-purge="${b.batch_id}">Xóa vĩnh viễn</button>` : ""}</span></div>`).join("")
    : `<div class="empty">Khu cách ly đang trống. Các file anh/chị dọn sẽ xuất hiện ở đây.</div>`;
  const kinds = { quarantine: "Đã dọn", restore: "Lấy lại", purge: "Xóa vĩnh viễn", error: "Giữ nguyên", move: "Sắp xếp" };
  $("#logList").innerHTML = log.length ? log.map((a) => `<div class="row"><span class="when">${fmtDate(a.ts)}</span>
    <span class="tag ${a.kind === "error" ? "keep" : ""}">${kinds[a.kind] || a.kind}</span><div class="name"><div class="t">${esc(a.path)}</div>${a.kind === "error" ? `<div class="p">${esc(a.reason || "")}</div>` : ""}</div><div class="size">${a.size ? fmt(a.size) : ""}</div></div>`).join("")
    : `<div class="empty">Chưa có thao tác nào.</div>`;
  $$("[data-restore]").forEach((b) => b.onclick = () => undo(b.dataset.restore));
  $$("[data-purge]").forEach((b) => b.onclick = async () => {
    if (!(await dialog("Xóa vĩnh viễn lần dọn này?", "<p>Các file trong lần dọn này sẽ bị <b>xóa hẳn khỏi máy</b> và <b>không thể lấy lại</b>.</p>", "Xóa vĩnh viễn"))) return;
    const r = await api("purge", { batch_id: b.dataset.purge }).catch((e) => toast(e.message, { err: true }));
    if (r) toast(`Đã giải phóng ${fmt(r.freed)}.`);
    renderQuarantine();
  });
}

// ---------- similar photos ----------
$("#simRun").onclick = async () => {
  try { await api("similar", { scan_id: state.scanId, threshold: +$("#simThreshold").value }); pollJob(); } catch (e) { toast(e.message, { err: true }); }
};
const thumbUrl = (p) => `/api/thumb?t=${encodeURIComponent(TOKEN)}&path=${encodeURIComponent(p)}`;
async function renderSimilar() {
  const d = await api(`scan/${state.scanId}/similar`);
  const sel = state.sel.similar; sel.clear();
  $("#simSummary").innerHTML = d.group_count
    ? `Tìm thấy <b>${num(d.group_count)} nhóm</b> ảnh giống nhau, dọn bớt có thể giải phóng khoảng <b>${fmt(d.saving)}</b>.<br><span class="muted">Ảnh có nhãn “Giữ lại” là ảnh nét nhất (độ phân giải cao nhất) của nhóm. Hãy xem kỹ ảnh trước khi dọn.</span>`
    : `<div class="empty">Chưa có kết quả. Bấm “Tìm ảnh giống nhau” để bắt đầu.</div>`;
  $("#simList").innerHTML = d.groups.map((g) => `<div class="group"><div class="group-head"><b>${g.files.length} ảnh giống nhau</b><span class="muted">dọn bớt được ${fmt(g.saving)}</span></div>
    <div class="photo-grid">${g.files.map((f, i) => {
      const keep = i === 0 && f.exists;
      if (!keep && f.exists && !f.protected) sel.set(f.path, f.size);
      const name = f.path.split(/[\\/]/).pop();
      return `<label class="photo ${keep ? "keep" : ""} ${!f.exists ? "gone" : ""}" title="${esc(f.path)}">
        <div class="ph-img">${f.exists ? `<img loading="lazy" src="${thumbUrl(f.path)}" alt="">` : "Đã dọn"}</div>
        <div class="ph-meta">${f.exists && !f.protected ? `<input type="checkbox" data-sel="similar" data-size="${f.size}" value="${esc(f.path)}" ${sel.has(f.path) ? "checked" : ""}>` : f.protected ? "🔒" : ""}
          <div class="name"><div class="t">${esc(name)}</div><div class="p">${f.width}×${f.height} · ${fmt(f.size)}</div></div></div>
        ${keep ? '<span class="tag ok ph-tag">✓ Giữ lại</span>' : ""}
        ${f.exists ? `<button class="btn small ghost ph-open" data-reveal="${esc(f.path)}" title="Xem vị trí">📂</button>` : ""}
      </label>`;
    }).join("")}</div></div>`).join("");
  bindSelection("#view-similar", "similar");
}

// ---------- system junk ----------
$("#junkRun").onclick = async () => { try { await api("junk-scan", {}); pollJob(); } catch (e) { toast(e.message, { err: true }); } };
function renderJunk() {
  const list = state.junk;
  if (!list) {
    $("#junkList").innerHTML = `<div class="empty">Bấm “Kiểm tra rác hệ thống” để xem máy đang có bao nhiêu rác. Việc kiểm tra chỉ đọc, chưa xóa gì.</div>`;
    $("#junkBar").classList.add("hidden"); $("#junkInfo").textContent = ""; return;
  }
  const total = list.reduce((a, c) => a + c.size, 0);
  $("#junkInfo").innerHTML = `Tìm thấy tổng cộng <b>${fmt(total)}</b>`;
  $("#junkList").innerHTML = list.map((c) => `
    <label class="row ${c.count ? "pick" : "locked"}">
      <span class="cb">${c.count ? `<input type="checkbox" data-junk="${c.id}" data-size="${c.size}" ${c.selected ? "checked" : ""}>` : ""}</span>
      <div class="name"><div class="t">${esc(c.name)} ${c.label === "safe" ? '<span class="tag ok">An toàn</span>' : '<span class="tag warn-tag">Cân nhắc</span>'}${c.admin ? ' <span class="tag" title="Một số file cần quyền quản trị; file không đủ quyền sẽ được bỏ qua.">Cần quyền quản trị</span>' : ""}</div>
        <div class="p wrap">${esc(c.desc)}</div></div>
      <span class="when">${c.count ? num(c.count) + " file" : "Sạch"}</span>
      <div class="size">${c.count ? fmt(c.size) : "—"}</div>
    </label>`).join("") || `<div class="empty">Không tìm thấy rác.</div>`;
  const upd = () => {
    let n = 0, sz = 0; $$("[data-junk]:checked").forEach((c) => { n++; sz += +c.dataset.size; c.closest(".row").classList.add("checked"); });
    $$("[data-junk]:not(:checked)").forEach((c) => c.closest(".row").classList.remove("checked"));
    $("#junkSel").innerHTML = n ? `Đã chọn <b>${n} mục</b> · khoảng <b>${fmt(sz)}</b>` : `<span class="muted">Chưa chọn mục nào</span>`;
    $("#junkClean").disabled = !n;
  };
  $$("[data-junk]").forEach((c) => c.onchange = upd);
  $("#junkBar").classList.toggle("hidden", !list.some((c) => c.count)); upd();
}
$("#junkClean").onclick = async () => {
  const ids = $$("[data-junk]:checked").map((c) => c.dataset.junk);
  if (!ids.length) return;
  if (!(await dialog("Dọn rác hệ thống?", "<p>Các file sẽ được chuyển vào <b>Khu cách ly</b> (lấy lại được). File đang được chương trình khác sử dụng hoặc cần quyền quản trị sẽ được bỏ qua.</p><p class=\"muted\">Nên đóng trình duyệt trước khi dọn bộ nhớ đệm trình duyệt.</p>", "🧹 Dọn ngay"))) return;
  try {
    const r = await api("junk-clean", { ids });
    toast(`Đã dọn ${num(r.moved)} file rác (${fmt(r.bytes)}).${r.skipped ? ` Bỏ qua ${num(r.skipped)} file đang dùng hoặc cần quyền.` : ""}`,
      r.batch_ids.length ? { action: "↩ Hoàn tác", onAction: async () => { for (const b of r.batch_ids) await api("restore", { batch_id: b }); toast("Đã trả lại các file rác về chỗ cũ."); refreshBadge(); } } : {});
    refreshBadge(); state.junk = null; await api("junk-scan", {}); pollJob();
  } catch (e) { toast(e.message, { err: true }); }
};

// ---------- startup programs ----------
const LABELS = { safe: ['ok', "Có thể tắt"], unknown: ['', "Chưa rõ"], keep: ['keep', "Nên giữ"] };
$$("#startupFilter .chip").forEach((b) => b.onclick = () => { state.startupFilter = b.dataset.f; $$("#startupFilter .chip").forEach((x) => x.classList.toggle("active", x === b)); drawStartup(); });
$("#startupReload").onclick = () => { state.startup = null; renderStartup(); };
async function renderStartup() {
  if (!state.startup) {
    $("#startupList").innerHTML = `<div class="empty"><div class="spinner inline"></div> Đang đọc danh sách chương trình…</div>`;
    try { state.startup = await api("startup"); } catch (e) { $("#startupList").innerHTML = `<div class="empty">Không đọc được: ${esc(e.message)}</div>`; return; }
  }
  const plat = state.info ? state.info.platform : "";
  $("#startupNote").innerHTML = plat === "windows"
    ? `<div class="info">Với mục có nhãn <b>Cần quyền quản trị</b>, Windows sẽ hỏi “Cho phép ứng dụng thay đổi thiết bị?”. Trước lần thay đổi đầu tiên, ứng dụng sẽ đề nghị tạo <b>điểm khôi phục hệ thống</b> để có thể quay lại nếu cần.</div>`
    : plat === "mac" ? `<div class="info">macOS có thể hỏi quyền điều khiển “System Events” khi đọc mục đăng nhập. Mục <b>Dịch vụ hệ thống</b> cần nhập mật khẩu máy.</div>`
    : `<div class="info">Tính năng này dành cho Windows và macOS.</div>`;
  drawStartup();
}
function drawStartup() {
  const items = (state.startup && state.startup.items) || [];
  const f = state.startupFilter;
  const shown = items.filter((i) => f === "all" || (f === "off" ? !i.enabled : i.label === f));
  $("#startupList").innerHTML = shown.length ? shown.map((i) => {
    const [cls, txt] = LABELS[i.label] || ["", i.label];
    return `<div class="row ${i.enabled ? "" : "is-off"}">
      <div class="name"><div class="t">${esc(i.name)} <span class="tag ${cls}" title="${esc(i.why)}">${txt}</span>${i.admin ? ' <span class="tag">Cần quyền quản trị</span>' : ""}</div>
        <div class="p">${esc(i.where)}${i.command ? " · " + esc(i.command) : ""}</div><div class="p why">${esc(i.why)}</div></div>
      <label class="switch" title="${i.enabled ? "Đang bật – bấm để tắt" : "Đang tắt – bấm để bật lại"}"><input type="checkbox" data-startup="${esc(i.id)}" ${i.enabled ? "checked" : ""}><span></span></label>
      <span class="state">${i.enabled ? "Đang bật" : "Đã tắt"}</span>
    </div>`;
  }).join("") : `<div class="empty">${items.length ? "Không có mục nào trong nhóm này." : "Không có chương trình nào tự khởi động."}</div>`;
  $$("[data-startup]").forEach((c) => c.onchange = () => toggleStartup(c.dataset.startup, c.checked, c));
}
async function toggleStartup(id, enable, el) {
  const item = state.startup.items.find((i) => i.id === id);
  el.disabled = true;
  try {
    if (!enable && item.admin && state.info.platform === "windows" && !state.restorePointDone) {
      const ans = await dialog("Tạo điểm khôi phục trước?",
        "<p>Mục này cần quyền quản trị. Nên tạo <b>điểm khôi phục hệ thống</b> trước để có thể đưa Windows về trạng thái hiện tại nếu có trục trặc.</p><p class=\"muted\">Windows sẽ hỏi quyền quản trị. Việc tạo mất khoảng một phút.</p>",
        "Tạo điểm khôi phục rồi tắt", "Hủy", "Tắt luôn");
      if (!ans) { el.checked = !enable; return; }
      if (ans === true) {
        toast("Đang tạo điểm khôi phục…");
        const r = await api("restore-point", {});
        if (!r.ok && !(await dialog("Chưa tạo được điểm khôi phục", `<p>${esc(r.error || "")}</p><p>Vẫn tiếp tục tắt? Anh/chị vẫn có thể bật lại mục này trong ứng dụng.</p>`, "Vẫn tắt"))) { el.checked = !enable; return; }
        if (r.ok) toast("Đã tạo điểm khôi phục.");
      }
      state.restorePointDone = true;
    }
    await api("startup-set", { id, enable });
    item.enabled = enable;
    toast(enable ? `Đã bật lại “${item.name}”.` : `Đã tắt “${item.name}”. Lần khởi động sau nó sẽ không tự chạy.`,
      enable ? {} : { action: "↩ Bật lại", onAction: async () => { await api("startup-set", { id, enable: true }); item.enabled = true; drawStartup(); toast(`Đã bật lại “${item.name}”.`); } });
    drawStartup();
  } catch (e) { el.checked = !enable; toast(e.message, { err: true }); }
  finally { el.disabled = false; }
}

// ---------- folder organizer ----------
function renderOrganize() {
  const info = state.info || {}; const sep = info.platform === "windows" ? "\\" : "/";
  $("#orgQuick").innerHTML = ["Downloads", "Desktop", "Documents"].map((n) => `<button class="btn small ghost" data-org="${esc(info.home + sep + n)}">${{ Downloads: "📥 Downloads", Desktop: "🖥️ Desktop", Documents: "📄 Documents" }[n]}</button>`).join(" ");
  $$("[data-org]").forEach((b) => b.onclick = () => { $("#orgPath").value = b.dataset.org; previewOrganize(); });
  $("#orgPick").classList.toggle("hidden", !info.can_pick_folder);
  if (!state.org) { $("#orgSummary").innerHTML = ""; $("#orgList").classList.add("hidden"); $("#orgBar").classList.add("hidden"); }
}
$("#orgPick").onclick = async () => { try { const r = await api("pick-folder", {}); if (r.path) { $("#orgPath").value = r.path; previewOrganize(); } } catch (e) { toast(e.message, { err: true }); } };
$("#orgPreview").onclick = () => previewOrganize();
$("#orgByYear").onchange = () => { if (state.org) previewOrganize(); };
async function previewOrganize() {
  const folder = $("#orgPath").value.trim();
  if (!folder) { toast("Hãy chọn thư mục trước."); return; }
  try { state.org = await api("organize-preview", { folder, by_year: $("#orgByYear").checked }); } catch (e) { toast(e.message, { err: true }); return; }
  const o = state.org;
  if (!o.moves.length) { $("#orgSummary").innerHTML = `<div class="empty">Thư mục này đã gọn gàng: không có file lẻ nào cần sắp xếp.</div>`; $("#orgList").classList.add("hidden"); $("#orgBar").classList.add("hidden"); return; }
  $("#orgSummary").innerHTML = `Sẽ sắp xếp <b>${num(o.moves.length)} file</b> trong <b>${esc(o.folder)}</b> vào các thư mục:<div class="chips static">${o.summary.map((s) => `<span class="chip">📁 ${esc(s.target)} <b>${num(s.count)}</b></span>`).join("")}</div><span class="muted">Thư mục con có sẵn được giữ nguyên. Không file nào bị ghi đè; file trùng tên sẽ được thêm số (2), (3)…</span>`;
  $("#orgList").classList.remove("hidden");
  $("#orgList").innerHTML = `<div class="row head"><span class="cb"><input type="checkbox" id="orgAll" checked></span><div class="name">File</div><span class="arrow"></span><div class="target">Chuyển vào</div><div class="size">Dung lượng</div></div>` +
    o.moves.map((m) => `<label class="row pick checked"><span class="cb"><input type="checkbox" data-orgsel value="${esc(m.src)}" checked></span>
      <div class="name"><div class="t">${esc(m.name)}</div>${m.renamed ? `<div class="p">sẽ đổi tên thành ${esc(m.dest.split(/[\\/]/).pop())} vì trùng tên</div>` : ""}</div>
      <span class="arrow">→</span><div class="target">📁 ${esc(m.target)}</div><div class="size">${fmt(m.size)}</div></label>`).join("");
  const upd = () => {
    const n = $$("[data-orgsel]:checked").length;
    $$("[data-orgsel]").forEach((c) => c.closest(".row").classList.toggle("checked", c.checked));
    $("#orgSel").innerHTML = n ? `Đã chọn <b>${num(n)} file</b>` : `<span class="muted">Chưa chọn file nào</span>`;
    $("#orgApply").disabled = !n; $("#orgApply").textContent = n ? `📦 Sắp xếp ${num(n)} file` : "📦 Sắp xếp";
    $("#orgAll").checked = n === o.moves.length; $("#orgAll").indeterminate = n > 0 && n < o.moves.length;
  };
  $$("[data-orgsel]").forEach((c) => c.onchange = upd);
  $("#orgAll").onchange = (e) => { $$("[data-orgsel]").forEach((c) => c.checked = e.target.checked); upd(); };
  $("#orgBar").classList.remove("hidden"); upd();
}
$("#orgApply").onclick = async () => {
  const chosen = $$("[data-orgsel]:checked").map((c) => c.value);
  if (!chosen.length) return;
  try {
    const r = await api("organize-apply", { folder: state.org.folder, chosen, by_year: $("#orgByYear").checked });
    toast(`Đã sắp xếp ${num(r.moved)} file.` + (r.failed.length ? ` ${num(r.failed.length)} file giữ nguyên.` : ""),
      { err: r.failed.length > 0, action: "↩ Hoàn tác", onAction: () => undo(r.batch_id).then(previewOrganize) });
    previewOrganize();
  } catch (e) { toast(e.message, { err: true }); }
};

// ---------- schedule ----------
$("#schHour").innerHTML = Array.from({ length: 24 }, (_, h) => `<option value="${h}">${String(h).padStart(2, "0")}:00</option>`).join("");
async function renderSchedule() {
  const c = await api("schedule");
  $("#schEnabled").checked = c.enabled; $("#schFreq").value = c.frequency; $("#schHour").value = c.hour;
  $("#schJunk").checked = c.junk; $("#schPurge").value = String(c.purge_days);
  const last = c.last_run;
  $("#schStatus").innerHTML = (!c.supported ? `<div class="info">Dọn dẹp theo lịch dành cho Windows và macOS.</div>` : "") +
    `<p>${c.enabled ? (c.registered ? "✅ Lịch đang bật và đã được đăng ký với hệ điều hành." : "⚠️ Lịch đang bật nhưng chưa đăng ký được với hệ điều hành. Hãy bấm Lưu lịch lần nữa.") : "Lịch đang tắt."}</p>` +
    (last ? `<p class="muted">Lần chạy gần nhất: ${fmtDate(last.ts)} · dọn ${num(last.junk_moved)} file rác (${fmt(last.junk_bytes)})${last.purged_bytes ? ` · xóa hẳn ${fmt(last.purged_bytes)} trong khu cách ly` : ""}.</p>` : `<p class="muted">Chưa chạy lần nào.</p>`) +
    `<p class="muted">Khu cách ly đang giữ ${fmt(c.pending_bytes)}.</p>`;
}
$("#schSave").onclick = async () => {
  try {
    await api("schedule", { enabled: $("#schEnabled").checked, frequency: $("#schFreq").value, hour: +$("#schHour").value, junk: $("#schJunk").checked, purge_days: +$("#schPurge").value });
    toast($("#schEnabled").checked ? "Đã lưu và bật lịch dọn dẹp." : "Đã tắt lịch dọn dẹp."); renderSchedule();
  } catch (e) { toast(e.message, { err: true }); }
};
$("#schRunNow").onclick = async () => {
  if (!(await dialog("Chạy dọn dẹp tự động ngay?", "<p>Ứng dụng sẽ làm đúng những gì lịch sẽ làm: dọn các mục rác hệ thống <b>an toàn</b> vào khu cách ly" + (+$("#schPurge").value ? ", và xóa hẳn file đã nằm trong khu cách ly quá số ngày đã chọn" : "") + ".</p>", "Chạy ngay"))) return;
  try { const r = await api("schedule-run", {}); toast(`Đã dọn ${num(r.junk_moved)} file rác (${fmt(r.junk_bytes)}).`); refreshBadge(); renderSchedule(); } catch (e) { toast(e.message, { err: true }); }
};

window.addEventListener("resize", () => { if (state.view === "usage") renderUsage(); });
(async () => { await loadScans().catch((e) => toast(e.message, { err: true })); refreshBadge(); render("home"); pollJob(); })();
