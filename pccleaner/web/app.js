"use strict";
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("token") || (() => { try { return sessionStorage.getItem("pcc_token"); } catch (e) { return ""; } })() || "";
try { sessionStorage.setItem("pcc_token", TOKEN); } catch (e) {}
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const COLORS = ["--c1", "--c2", "--c3", "--c5", "--c6", "--c7", "--c4", "--c8"].map((v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim());
const SELECTABLE = { large: "File lớn", old: "File cũ", dups: "File trùng lặp", similar: "Ảnh giống nhau" }; // log reasons; shown through t()

const state = {
  scanId: null, dirId: 0, view: "home", info: null,
  sel: { large: new Map(), old: new Map(), dups: new Map(), similar: new Map() }, // path -> size
  shown: { large: [], old: [], dups: [], similar: [] },                            // selectable paths on screen
  junk: null, startup: null, startupFilter: "all", restorePointDone: false, org: null,
  polling: null, lastJob: null,
  cloud: new Map(), // path -> sync service (OneDrive, Dropbox…) for files shown in lists
};

async function api(path, body) {
  const opt = { headers: { "X-Token": TOKEN, "X-Lang": I18N.lang } };
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
  return (i ? n.toLocaleString(I18N.locale, { maximumFractionDigits: n < 10 ? 1 : 0 }) : n) + " " + u[i];
}
const num = (n) => Number(n || 0).toLocaleString(I18N.locale);
const fmtDate = (ts) => new Date(ts * 1000).toLocaleString(I18N.locale, { dateStyle: "short", timeStyle: "short" });
const fmtDay = (ts) => new Date(ts * 1000).toLocaleDateString(I18N.locale);
function ago(ts) {
  const d = (Date.now() / 1000 - ts) / 86400;
  if (d < 1) return t("hôm nay"); if (d < 30) return t("{0} ngày trước", Math.floor(d));
  if (d < 365) return t("{0} tháng trước", Math.floor(d / 30)); return t("{0} năm trước", Math.floor(d / 365));
}
function dur(s) { s = Math.round(s); return s < 60 ? t("{0} giây", s) : t("{0} phút {1} giây", Math.floor(s / 60), s % 60); }
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg, opts = {}) {
  const box = $("#toast"); $("#toastMsg").textContent = msg;
  box.className = "toast" + (opts.err ? " err" : "");
  const b = $("#toastAct");
  if (opts.action) { b.textContent = opts.action; b.classList.remove("hidden"); b.onclick = () => { box.classList.add("hidden"); opts.onAction(); }; }
  else b.classList.add("hidden");
  clearTimeout(box._h); box._h = setTimeout(() => box.classList.add("hidden"), opts.action ? 10000 : 5000);
}
function dialog(title, html, ok = t("Đồng ý"), cancel = t("Hủy"), alt = null) {
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
    if (view === "settings") return renderSettings();
    if (!state.scanId) return show("home");
    if (view === "usage") return await renderUsage();
    if (view === "large") return await renderLarge();
    if (view === "old") return await renderOld();
    if (view === "types") return await renderTypes();
    if (view === "dups") return await renderDups();
    if (view === "similar") return await renderSimilar();
  } catch (e) { toast(e.message, { err: true }); }
}

// ---------- home: Dashboard ----------
const GROUPS = { junk: ["--v1", "Rác hệ thống", "junk"], dups: ["--v2", "Bản thừa của file trùng", "dups"], quarantine: ["--v3", "Khu cách ly (xóa hẳn để lấy lại chỗ)", "quarantine"] };
const cssVar = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
async function renderHome() {
  const info = state.info = await api("info");
  const dash = state.dash = await api("dashboard");
  renderDashboard(dash);
  $("#pickFolderBtn").classList.toggle("hidden", !info.can_pick_folder);
  $("#locations").innerHTML = info.locations.map((l, i) => {
    const pct = l.total ? (l.used / l.total) * 100 : 0;
    const isHome = l.path === info.home;
    return `<div class="card ${isHome ? "recommended" : ""}">
      ${isHome ? `<span class="ribbon">${t("Nên bắt đầu ở đây")}</span>` : ""}
      <h3>${isHome ? "👤" : "💽"} ${esc(l.label)}</h3><div class="path">${esc(l.path)}</div>
      <div class="meter ${pct > 90 ? "high" : pct > 75 ? "mid" : ""}"><div style="width:${pct.toFixed(1)}%"></div></div>
      <div class="free">${t("Còn trống <b>{0}</b>", fmt(l.free))} <span class="muted">/ ${fmt(l.total)}</span></div>
      ${pct > 90 ? `<div class="warn-text">⚠️ ${t("Ổ đĩa sắp đầy")}</div>` : ""}
      <button class="btn ${isHome ? "primary" : ""}" data-scan="${esc(l.path)}">${isHome ? t("Quét thư mục này") : t("Quét ổ này")}</button>
      ${isHome ? "" : `<div class="hint">${t("Quét cả ổ có thể mất vài phút.")}</div>`}</div>`;
  }).join("");
  $$("[data-scan]").forEach((b) => b.onclick = () => startScan(b.dataset.scan));
  await loadScans();
  const scans = await api("scans");
  $("#recentScans").innerHTML = scans.length ? `<div class="list">${scans.map((s) => `
    <div class="row"><span class="ico">🗂️</span><div class="name"><div class="t">${esc(s.root)}</div><div class="p">${t("Quét lúc {0} · {1} {1|file|files}", fmtDate(s.finished), num(s.file_count))}${s.error_count ? " · " + t("bỏ qua {0} mục không có quyền đọc", num(s.error_count)) : ""}</div></div>
    <div class="size">${fmt(s.total_size)}</div><button class="btn small" data-open="${s.id}">${t("Xem báo cáo")}</button></div>`).join("")}</div>`
    : `<div class="list"><div class="empty">${t("Chưa quét lần nào. Hãy bấm “Quét” ở một ô phía trên.")}</div></div>`;
  $$("[data-open]").forEach((b) => b.onclick = () => { selectScan(+b.dataset.open); show("usage"); });
}

function renderDashboard(d) {
  const clean = d.cleanable.filter((c) => c.group !== "quarantine");
  const cleanBytes = clean.reduce((a, c) => a + (c.bytes || 0), 0);
  const q = d.cleanable.find((c) => c.group === "quarantine") || { bytes: 0 };
  const st = d.startup, last = d.last_cleanup;
  const tile = (lbl, big, sub, link, view) => `<div class="tile-stat"><span class="lbl">${lbl}</span><span class="big">${big}</span><span class="sub">${sub}</span>${link ? `<a data-goto="${view}">${link} →</a>` : ""}</div>`;
  $("#dashTiles").innerHTML =
    tile(t("Có thể dọn"), clean.length ? fmt(cleanBytes) : "—", clean.length ? t("rác hệ thống và file trùng đã tìm thấy") : t("Chưa kiểm tra"), t("Kiểm tra rác hệ thống"), "junk") +
    tile(t("Khởi động cùng máy"), st ? num(st.enabled) : "—", st ? t("{0} chương trình đang bật, {1} có thể tắt", num(st.enabled), num(st.can_disable)) : t("Chưa kiểm tra"), t("Xem danh sách"), "startup") +
    tile(t("Lần dọn gần nhất"), last ? fmt(last.bytes) : "—", last ? `${fmtDate(last.ts)} · ${esc(tReason(last.reason || ""))}` : t("Chưa dọn lần nào"), t("Khu cách ly & hoàn tác"), "quarantine") +
    tile(t("Khu cách ly đang giữ"), fmt(q.bytes), t("lấy lại được bất cứ lúc nào"), "", "");
  $$("[data-goto]").forEach((a) => a.onclick = () => show(a.dataset.goto));
  // Cleanable space by group: bars on one scale, value always printed beside each bar.
  const rows = d.cleanable;
  const max = Math.max(1, ...rows.map((r) => r.bytes || 0));
  const notes = { junk: (r) => t("theo lần kiểm tra lúc {0}", fmtDate(r.ts)), dups: (r) => t("theo lần tìm trong {0}", esc(r.root)), quarantine: () => t("đã dọn, chưa xóa hẳn") };
  const missing = ["junk", "dups"].filter((g) => !rows.some((r) => r.group === g));
  $("#dashClean").innerHTML = `<div class="hbar">${rows.map((r) => `
      <span>${t(GROUPS[r.group][1])}</span>
      <div class="track" title="${t(GROUPS[r.group][1])}: ${fmt(r.bytes)}"><div style="width:${(100 * (r.bytes || 0) / max).toFixed(1)}%;background:var(${GROUPS[r.group][0]})"></div></div>
      <span class="v">${fmt(r.bytes || 0)}</span><span class="note">${notes[r.group](r)}</span>`).join("")}</div>` +
    (missing.length ? `<p class="muted small-note">${missing.map((g) => g === "junk" ? t("Rác hệ thống: chưa kiểm tra.") : t("File trùng: chưa tìm.")).join(" ")}</p>` : "");
  renderHistory(d);
}

// Used space per drive over time: one line per drive, one shared byte axis, hover crosshair.
function renderHistory(d) {
  const box = $("#dashHistory");
  const labels = Object.fromEntries(d.locations.map((l) => [l.path, l.label]));
  const series = Object.entries(d.history).filter(([p]) => labels[p]).slice(0, 4);
  const days = [...new Set(series.flatMap(([, pts]) => pts.map((x) => x.day)))].sort();
  if (days.length < 2) { box.innerHTML = `<div class="chart-empty">${t("Ứng dụng ghi lại dung lượng mỗi ngày anh/chị mở nó. Biểu đồ sẽ hiện từ ngày thứ hai.")}</div>`; return; }
  const W = Math.max(280, box.clientWidth), H = 200, L = 52, R = 10, T = 10, B = 24;
  const maxV = Math.max(...series.flatMap(([, pts]) => pts.map((x) => x.used))) * 1.08;
  const x = (day) => L + (W - L - R) * days.indexOf(day) / (days.length - 1);
  const y = (v) => T + (H - T - B) * (1 - v / maxV);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => maxV * f);
  const colors = ["--v1", "--v2", "--v3", "--v4"];
  const dayLabel = (day) => new Date(day + "T12:00:00").toLocaleDateString(I18N.locale, { day: "numeric", month: "short" });
  box.innerHTML = `<div class="line-chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${t("Dung lượng đã dùng theo thời gian")}">
    ${ticks.map((v) => `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`).join("")}
    <text class="axis" x="${L}" y="${H - 6}">${dayLabel(days[0])}</text><text class="axis" x="${W - R}" y="${H - 6}" text-anchor="end">${dayLabel(days[days.length - 1])}</text>
    ${series.map(([, pts], i) => `<polyline class="ln" style="stroke:var(${colors[i]})" points="${pts.map((p) => `${x(p.day).toFixed(1)},${y(p.used).toFixed(1)}`).join(" ")}"/>`).join("")}
    <line class="cross hidden" x1="0" x2="0" y1="${T}" y2="${H - B}"/>
    <rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/>
  </svg><div class="tip hidden"></div></div>
  <div class="legend">${series.map(([p], i) => `<span><i style="background:var(${colors[i]})"></i>${esc(labels[p])}</span>`).join("")}</div>`;
  const svg = box.querySelector("svg"), cross = box.querySelector(".cross"), tip = box.querySelector(".tip");
  svg.addEventListener("mousemove", (e) => {
    const r = svg.getBoundingClientRect(); const px = (e.clientX - r.left) * W / r.width;
    const i = Math.max(0, Math.min(days.length - 1, Math.round((px - L) / (W - L - R) * (days.length - 1))));
    const day = days[i]; cross.setAttribute("x1", x(day)); cross.setAttribute("x2", x(day)); cross.classList.remove("hidden");
    tip.innerHTML = `<b>${dayLabel(day)}</b>` + series.map(([p, pts], k) => { const v = pts.find((q) => q.day === day); return v ? `<div><i style="display:inline-block;width:8px;height:8px;border-radius:2px;background:var(${colors[k]})"></i> ${esc(labels[p])}: ${t("đã dùng {0} / {1}", fmt(v.used), fmt(v.total))}</div>` : ""; }).join("");
    tip.classList.remove("hidden");
    const left = (x(day) / W) * r.width; tip.style.left = Math.min(left + 12, r.width - tip.offsetWidth) + "px"; tip.style.top = "8px";
  });
  svg.addEventListener("mouseleave", () => { cross.classList.add("hidden"); tip.classList.add("hidden"); });
}

// Log reasons are stored in Vietnamese as "<what>: <detail>"; each part is translated.
function tReason(r) { const i = r.indexOf(": "); return i > 0 ? t(r.slice(0, i)) + ": " + t(r.slice(i + 2)) : t(r); }

// ---------- settings, theme, language, first-run guide ----------
function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}
function applyAppName() {
  const name = (state.info && state.info.app_name) || "PC Cleaner";
  $("#brandName").textContent = name; $$(".appName").forEach((e) => e.textContent = name);
  document.title = name;
}
async function setLanguage(lang) {
  const s = await api("settings", { lang });
  state.info.settings = s;
  await loadLang(s.lang); applyAppName();
  $("#toast").classList.add("hidden"); // a message still showing is in the old language
  $("#setLang").value = s.lang;
  render(state.view); refreshBadge();
}
function renderSettings() {
  const s = state.info.settings;
  $("#setLang").value = s.lang; $("#setTheme").value = s.theme;
  $("#aboutInfo").innerHTML = t("Phiên bản {0} · Thư mục dữ liệu: {1}", esc(state.info.version), esc(state.info.data_dir));
  $("#macUninstall").classList.toggle("hidden", state.info.platform !== "mac");
  renderUpdate();
}

// ---------- updates: nothing is downloaded or installed without the user's click ----------
async function renderUpdate() {
  let u; try { u = state.update = await api("update"); } catch (e) { return; }
  $("#updChannel").value = u.channel; $("#updAuto").checked = u.auto_check;
  ["#updChannel", "#updAuto", "#updCheck"].forEach((s) => $(s).disabled = !u.configured);
  $("#updGet").classList.toggle("hidden", !u.available);
  $("#updStatus").textContent = !u.configured ? t("Chưa bật trong bản này")
    : u.available ? t("Đã có phiên bản {0} ({1})", u.available.version, fmt(u.available.size))
    : u.last_check ? t("Đang dùng bản mới nhất (kiểm tra lúc {0})", fmtDate(u.last_check)) : t("Chưa kiểm tra");
}
const saveUpdate = async (body) => { try { await api("update-settings", body); renderUpdate(); } catch (e) { toast(e.message, { err: true }); } };
$("#updChannel").onchange = (e) => saveUpdate({ channel: e.target.value });
$("#updAuto").onchange = (e) => saveUpdate({ auto_check: e.target.checked });
$("#updCheck").onclick = async () => {
  try { await api("update-check", {}); await renderUpdate(); if (!state.update.available) toast(t("Đang dùng bản mới nhất.")); }
  catch (e) { toast(t("Không kiểm tra được bản cập nhật: {0}", e.message), { err: true }); }
};
$("#updGet").onclick = async () => {
  const a = state.update.available; const notes = a.notes[I18N.lang] || a.notes.vi || "";
  const ok = await dialog(t("Cập nhật lên phiên bản {0}", a.version),
    (notes ? `<p>${esc(notes)}</p>` : "") + `<p>${esc(t("Ứng dụng sẽ tải bản mới ({0}), kiểm tra chữ ký rồi mới cài. Dữ liệu, nhật ký và khu cách ly được giữ nguyên.", fmt(a.size)))}</p>`,
    t("Tải và cài"));
  if (!ok) return;
  try { await api("update-download", {}); pollJob(); } catch (e) { toast(e.message, { err: true }); }
};
async function finishUpdate(r) {
  try {
    const x = await api("update-install", { path: r.path });
    if (x.drag) dialog(t("Cài bản mới"), `<p>${esc(t("Kéo {0} vào thư mục Applications để thay bản cũ, rồi mở lại ứng dụng.", state.info.app_name))}</p>`, t("Đã hiểu"), null);
    else toast(t("Đang cài bản mới. Ứng dụng sẽ tự mở lại."));
  } catch (e) { toast(e.message, { err: true }); }
}
$("#beforeUninstall").onclick = async () => {
  try { const r = await api("before-uninstall", {}); toast(r.message); } catch (e) { toast(e.message, { err: true }); }
};
$("#setLang").onchange = (e) => setLanguage(e.target.value).catch((er) => toast(er.message, { err: true }));
$("#setTheme").onchange = async (e) => {
  try { state.info.settings = await api("settings", { theme: e.target.value }); applyTheme(state.info.settings.theme); if (state.view === "home") renderHome(); }
  catch (er) { toast(er.message, { err: true }); }
};
$("#setGuide").onclick = () => openGuide();
function openGuide() {
  const steps = $$(".guide-step"); let i = 0;
  const draw = () => {
    steps.forEach((s, k) => s.classList.toggle("on", k === i));
    $("#guideDots").innerHTML = steps.map((_s, k) => `<span class="${k === i ? "on" : ""}"></span>`).join("");
    $("#guideBack").classList.toggle("hidden", i === 0);
    $("#guideNext").textContent = i === steps.length - 1 ? t("Bắt đầu sử dụng") : t("Tiếp");
    $$("[data-guide-lang]").forEach((b) => b.classList.toggle("active", b.dataset.guideLang === I18N.lang));
  };
  const close = async () => {
    $("#guide").classList.add("hidden");
    try { state.info.settings = await api("settings", { onboarded: true }); } catch (e) { /* asked again next time */ }
  };
  $("#guideNext").onclick = () => { if (i === steps.length - 1) close(); else { i++; draw(); } };
  $("#guideBack").onclick = () => { if (i > 0) { i--; draw(); } };
  $("#guideSkip").onclick = close;
  $$("[data-guide-lang]").forEach((b) => b.onclick = async () => { await setLanguage(b.dataset.guideLang).catch((e) => toast(e.message, { err: true })); draw(); });
  $("#guide").classList.remove("hidden"); draw(); $("#guideNext").focus();
}
$("#customScanBtn").onclick = () => { const p = $("#customPath").value.trim(); if (p) startScan(p); else { toast(t("Hãy nhập đường dẫn thư mục trước.")); $("#customPath").focus(); } };
$("#customPath").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#customScanBtn").click(); });
$("#pickFolderBtn").onclick = async () => {
  try { const r = await api("pick-folder", {}); if (r.path) startScan(r.path); } catch (e) { toast(e.message, { err: true }); }
};

async function loadScans() {
  const scans = await api("scans");
  $("#scanSelect").innerHTML = scans.length ? scans.map((s) => `<option value="${s.id}">${esc(s.root)} (${fmtDay(s.finished)})</option>`).join("") : `<option value="">${t("Chưa có")}</option>`;
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
// File-changing actions (clean, undo, organize…) run in the background with progress
// and a Stop button. Resolves with the action's result when it finishes.
function runAction(endpoint, body) {
  return new Promise(async (resolve, reject) => {
    try { await api(endpoint, body); } catch (e) { reject(e); return; }
    state.actionWaiter = { resolve, reject };
    pollJob();
  });
}
const stopped = (r) => (r && r.cancelled ? " " + t("Đã dừng giữa chừng theo yêu cầu: phần chưa làm vẫn giữ nguyên.") : "");
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
      if (j.kind === "update") {
        const pct = p.total ? Math.floor(100 * p.done / p.total) : 0;
        $("#jobTitle").textContent = `${t("Đang tải bản cập nhật")} (${pct}%)`;
        $("#jobDetail").textContent = `${el} · ${fmt(p.done || 0)} / ${fmt(p.total || 0)}`;
        $(".progress").classList.remove("indeterminate"); $("#jobProgress").style.width = pct + "%";
      } else if (j.kind === "scan") {
        $("#jobTitle").textContent = t("Đang quét {0} — đã tìm thấy {1} {1|file|files} ({2})", j.root, num(p.files), fmt(p.bytes || 0));
        $("#jobDetail").textContent = `${el} · ${p.current || ""}`;
        $(".progress").classList.add("indeterminate"); $("#jobProgress").style.width = "30%";
      } else {
        const pct = p.total ? Math.floor(100 * p.done / p.total) : 0;
        const what = { duplicates: t("Đang tìm file trùng"), similar: t("Đang tìm ảnh giống nhau"), junk: t("Đang kiểm tra rác hệ thống") }[j.kind] || "";
        const stage = j.kind === "action" ? (p.stage || j.label || t("Đang xử lý")) : `${what}: ${p.stage || ""}`;
        $("#jobTitle").textContent = `${stage}${p.total ? ` (${pct}%)` : ""}`;
        $("#jobDetail").textContent = `${el}${p.total ? " · " + t("{0}/{1} {1|file|files}", num(p.done), num(p.total)) : ""}`;
        $(".progress").classList.toggle("indeterminate", !p.total);
        $("#jobProgress").style.width = p.total ? pct + "%" : "30%";
      }
      return;
    }
    clearInterval(state.polling); bar.classList.add("hidden");
    if (state.lastJob === j.started) return;
    state.lastJob = j.started;
    if (j.kind === "action") {
      const w = state.actionWaiter; state.actionWaiter = null;
      if (w) { j.state === "done" ? w.resolve(j.result) : w.reject(new Error(j.state === "error" ? j.error : t("Đã dừng lại."))); }
      else if (j.state === "done") { toast(t("Thao tác chạy nền đã xong.") + stopped(j.result)); refreshBadge(); render(state.view); }
      return;
    }
    if (j.state === "done" && j.kind === "scan") { await loadScans(); selectScan(j.result); toast(t("Quét xong. Đây là các thư mục chiếm nhiều chỗ nhất.")); show("usage"); }
    else if (j.state === "done" && j.kind === "duplicates") { toast(j.result ? t("Tìm thấy {0} {0|nhóm|nhóm} file trùng.", j.result) : t("Không có file trùng nào. Máy anh/chị khá gọn!")); if (state.view === "dups") renderDups(); }
    else if (j.state === "done" && j.kind === "similar") { toast(j.result ? t("Tìm thấy {0} {0|nhóm|nhóm} ảnh giống nhau.", j.result) : t("Không có ảnh nào giống nhau.")); if (state.view === "similar") renderSimilar(); }
    else if (j.state === "done" && j.kind === "junk") { state.junk = j.result; renderJunk(); }
    else if (j.state === "done" && j.kind === "update") finishUpdate(j.result);
    else if (j.state === "cancelled") toast(t("Đã dừng lại."));
    else if (j.state === "error") toast(t("Có lỗi: {0}", j.error), { err: true });
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
      const worst = Math.max(...test.map((q) => Math.max((short * short * q.a) / (s * s), (s * s) / (short * short * q.a))));
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
const revealBtn = (p) => `<button class="btn small ghost" data-reveal="${esc(p)}" title="${t("Mở thư mục chứa file này trong {0}", state.info && state.info.platform === "mac" ? "Finder" : "File Explorer")}">📂 ${t("Xem vị trí")}</button>`;

async function renderUsage() {
  const d = await api(`scan/${state.scanId}/children?dir=${state.dirId}`);
  $("#crumbs").innerHTML = (d.crumbs.length > 1 ? `<a data-dir="${d.crumbs[d.crumbs.length - 2].id}" class="back">← ${t("Quay lại")}</a>` : "") +
    d.crumbs.map((c, i) => (i ? '<span class="sep">›</span>' : "") + `<a data-dir="${c.id}">${esc(c.name)}</a>`).join("") +
    ` <span class="muted">· ${t("tổng {0} · {1} {1|file|files}", fmt(d.dir.size), num(d.dir.count))}</span>`;
  const total = d.dir.size || 1;
  $("#usageList").innerHTML = `<div class="row head"><span class="ico"></span><div class="name">${t("Tên")}</div><div class="bar-h">${t("Tỉ lệ")}</div><div class="size">${t("Dung lượng")}</div><div class="acts"></div></div>` +
    (d.items.length ? d.items.map((it) => `
    <div class="row ${it.type}" ${it.type === "dir" ? `data-dir="${it.id}" title="${t("Bấm để xem bên trong")}"` : ""}>
      <span class="ico">${it.type === "dir" ? "📁" : "📄"}</span>
      <div class="name"><div class="t">${esc(it.name)}</div>${it.type === "dir" ? `<div class="p">${t("{0} {0|file|files}", num(it.count))}</div>` : `<div class="p">${t("sửa {0}", ago(it.mtime))}</div>`}</div>
      <div class="bar" title="${t("{0}% của thư mục hiện tại", Math.round(100 * it.size / total))}"><div style="width:${(100 * it.size / total).toFixed(1)}%"></div></div>
      <div class="size">${fmt(it.size)}</div>
      <div class="acts">${revealBtn(it.path)}</div>
    </div>`).join("") : `<div class="empty">${t("Thư mục này trống.")}</div>`);
  const tm = $("#treemap"); const W = tm.clientWidth, H = tm.clientHeight;
  const tiles = squarify(d.items.filter((i) => i.size > 0).slice(0, 40), 0, 0, W, H);
  tm.innerHTML = tiles.map((tl, i) => `<div class="tile ${tl.it.type}" ${tl.it.type === "dir" ? `data-dir="${tl.it.id}"` : ""} title="${esc(tl.it.name)} · ${fmt(tl.it.size)}"
     style="left:${tl.x}px;top:${tl.y}px;width:${tl.w}px;height:${tl.h}px;background:${COLORS[i % COLORS.length]}">${tl.w > 60 && tl.h > 30 ? `${tl.it.type === "dir" ? "📁 " : ""}${esc(tl.it.name)}<small>${fmt(tl.it.size)}</small>` : ""}</div>`).join("");
  $$("#view-usage [data-dir]").forEach((el) => el.addEventListener("click", (e) => { if (e.target.closest("button")) return; state.dirId = +el.dataset.dir; renderUsage(); }));
  bindReveal("#view-usage");
}
function bindReveal(scope) {
  $$(scope + " [data-reveal]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); api("reveal", { path: b.dataset.reveal }).catch((er) => toast(er.message, { err: true })); });
}

// ---------- selectable file lists ----------
// Why a file cannot be offered for cleanup, and the cloud service a file syncs with.
const lockAttr = (f) => f.protected ? `title="${esc(f.why || t("Được bảo vệ, ứng dụng không cho phép dọn."))}"` : "";
const lockTag = (f) => `<span class="tag keep" ${lockAttr(f)}>${f.system ? t("Hệ thống") : t("Được bảo vệ")}</span>`;
const cloudTag = (f) => f.cloud ? ` <span class="tag warn-tag" title="${t("Dọn file này sẽ xóa nó khỏi {0} trên mọi thiết bị.", esc(f.cloud))}">☁ ${esc(f.cloud)}</span>` : "";
function noteCloud(f) { if (f.cloud) state.cloud.set(f.path, f.cloud); }
function fileRows(list, key) {
  const sel = state.sel[key];
  const head = `<div class="row head"><span class="cb"></span><div class="name">${t("Tên file")}</div><span class="kind">${t("Loại")}</span><span class="when">${t("Sửa lần cuối")}</span><div class="size">${t("Dung lượng")}</div><span class="acts"></span></div>`;
  if (!list.length) return `<div class="empty">${t("Không có file nào phù hợp. Thử chọn mức nhỏ hơn ở phía trên.")}</div>`;
  return head + list.map((f) => `
    ${noteCloud(f) || ""}<label class="row ${f.protected ? "locked" : "pick"}" ${lockAttr(f)}>
      <span class="cb">${f.protected ? "🔒" : `<input type="checkbox" data-sel="${key}" data-size="${f.size}" value="${esc(f.path)}" ${sel.has(f.path) ? "checked" : ""}>`}</span>
      <div class="name"><div class="t">${esc(f.name)}</div><div class="p">${esc(f.path)}</div></div>
      <span class="kind">${f.protected ? lockTag(f) : `<span class="tag">${esc(t(f.category))}</span>`}${cloudTag(f)}</span>
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
  $("#selInfo").innerHTML = sel.size ? t("Đã chọn <b>{0} {0|file|files}</b> · sẽ giải phóng <b>{1}</b>", num(sel.size), fmt(total)) : `<span class="muted">${t("Chưa chọn file nào")}</span>`;
  $("#selClean").disabled = !sel.size; $("#selClear").disabled = !sel.size;
  $("#selClean").textContent = "🧹 " + (sel.size ? t("Dọn {0} {0|file|files}", num(sel.size)) : t("Dọn các file đã chọn"));
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
  // One measure, one hue: bar length carries the size, the label names the group.
  const bars = (rows, label) => { const m = rows.length ? rows[0].size : 1; return rows.map((r) => `
    <div class="b"><div>${esc(label(r))} <span class="muted">· ${t("{0} {0|file|files}", num(r.count))}</span></div>
    <div class="track" title="${esc(label(r))}: ${fmt(r.size)}"><div style="width:${(100 * r.size / m).toFixed(1)}%;background:var(--v1)"></div></div><div class="v">${fmt(r.size)}</div></div>`).join(""); };
  $("#catList").innerHTML = bars(d.categories, (r) => t(r.category));
  $("#extList").innerHTML = bars(d.extensions, (r) => (r.ext.startsWith("(") ? t(r.ext) : "." + r.ext));
}

// ---------- duplicates ----------
$("#dupRun").onclick = async () => {
  try { await api("duplicates", { scan_id: state.scanId, min_size: +$("#dupMin").value }); pollJob(); } catch (e) { toast(e.message, { err: true }); }
};
async function renderDups() {
  const d = await api(`scan/${state.scanId}/duplicates`);
  const sel = state.sel.dups; sel.clear();
  $("#dupSummary").innerHTML = d.group_count
    ? t("Tìm thấy <b>{0} nhóm</b> file trùng, dọn bản thừa sẽ giải phóng khoảng <b>{1}</b>.", num(d.group_count), fmt(d.wasted)) +
      `<br><span class="muted">${t("Ứng dụng đã tự chọn sẵn các bản thừa và giữ lại một bản, ưu tiên bản nằm ngoài Downloads/Desktop và không có chữ “copy” (có nhãn “Giữ lại”). Anh/chị có thể đổi lựa chọn.")}</span>`
    : `<div class="empty">${t("Chưa có kết quả. Bấm “Tìm file trùng” để bắt đầu.")}</div>`;
  $("#dupList").innerHTML = d.groups.map((g) => {
    let kept = false;
    const rows = g.files.map((f) => {
      let keep = false;
      if (!kept && f.exists) { keep = true; kept = true; }
      noteCloud(f);
      // Copies in OneDrive/Dropbox/iCloud are never pre-selected: removing them removes them on every device.
      if (!keep && !f.protected && f.exists && !f.cloud) sel.set(f.path, g.size);
      const name = f.path.split(/[\\/]/).pop();
      return `<label class="row ${f.protected || !f.exists ? "locked" : "pick"}" ${lockAttr(f)}>
        <span class="cb">${f.protected ? "🔒" : !f.exists ? "" : `<input type="checkbox" data-sel="dups" data-size="${g.size}" value="${esc(f.path)}" ${sel.has(f.path) ? "checked" : ""}>`}</span>
        <div class="name"><div class="t">${esc(name)}</div><div class="p">${esc(f.path)}</div></div>
        <span class="kind">${keep ? `<span class="tag ok">✓ ${t("Giữ lại")}</span>` : f.protected ? lockTag(f) : !f.exists ? `<span class="tag">${t("Đã dọn")}</span>` : `<span class="tag">${t("Bản thừa")}</span>`}${cloudTag(f)}</span>
        <span class="when">${ago(f.mtime)}</span>
        <span class="acts">${f.exists ? revealBtn(f.path) : ""}</span></label>`;
    }).join("");
    return `<div class="group"><div class="group-head"><b>${t("{0} bản giống hệt nhau", g.files.length)}</b><span>${t("{0} mỗi bản", fmt(g.size))}</span><span class="muted">${t("thừa {0}", fmt(g.wasted))}</span></div>${rows}</div>`;
  }).join("");
  bindSelection("#view-dups", "dups");
}

// ---------- cleaning ----------
$("#selClean").onclick = async () => {
  const key = state.view; const sel = state.sel[key]; const files = [...sel.keys()];
  if (!files.length) return;
  let total = 0; sel.forEach((s) => total += s);
  const cloudFiles = files.filter((f) => state.cloud.has(f));
  const cloudNames = [...new Set(cloudFiles.map((f) => state.cloud.get(f)))].join(", ");
  const ok = await dialog(t("Dọn {0} {0|file|files} ({1})?", num(files.length), fmt(total)),
    `<p>${t("Các file này sẽ được chuyển vào <b>Khu cách ly</b>, <b>chưa bị xóa vĩnh viễn</b>. Nếu cần, anh/chị có thể lấy lại bất cứ lúc nào.")}</p>
     ${cloudFiles.length ? `<div class="info warn">☁ ${t("<b>{0} {0|file|files} nằm trong {1}.</b> Dọn chúng sẽ xóa chúng khỏi {1} trên <b>mọi máy và điện thoại</b> đang đồng bộ. Lấy lại từ khu cách ly sẽ đưa chúng trở lại.", num(cloudFiles.length), esc(cloudNames))}</div>` : ""}
     ${key === "dups" ? `<p class="muted">${t("Trước khi dọn, ứng dụng sẽ kiểm tra lại nội dung từng file và luôn giữ lại ít nhất một bản.")}</p>` : ""}
     <div class="list small scroll">${files.slice(0, 50).map((f) => `<div class="row">${esc(f)}</div>`).join("")}${files.length > 50 ? `<div class="row muted">${t("… và {0} file khác", num(files.length - 50))}</div>` : ""}</div>`,
    "🧹 " + t("Dọn ngay"));
  if (!ok) return;
  try {
    const body = { paths: files, reason: SELECTABLE[key], allow_cloud: cloudFiles.length > 0 }; // stored in Vietnamese, shown with t()
    if (key === "dups") body.dup_scan_id = state.scanId;
    if (key === "similar") body.similar_scan_id = state.scanId;
    const r = await runAction("quarantine", body);
    sel.clear(); refreshBadge();
    if (r.failed.length) {
      await dialog(r.moved ? t("Đã dọn {0} {0|file|files}, {1} {1|file|files} được giữ nguyên", num(r.moved), num(r.failed.length)) : t("Không dọn được file nào"),
        `<p>${r.moved ? t("Đã chuyển {0} vào khu cách ly.", fmt(r.bytes)) + " " : ""}${t("Những file dưới đây được giữ nguyên:")}</p>
         <div class="list small scroll">${r.failed.map((f) => `<div class="row"><div class="name"><div class="t">${esc(f.path)}</div><div class="p">${esc(f.error)}</div></div></div>`).join("")}</div>`, t("Đã hiểu"), null);
    }
    if (r.moved) toast(t("Đã dọn {0} {0|file|files} ({1}).", num(r.moved), fmt(r.bytes)) + stopped(r), { action: "↩ " + t("Hoàn tác"), onAction: () => undo(r.batch_id) });
    else if (r.cancelled) toast(stopped(r));
    render(state.view);
  } catch (e) { toast(e.message, { err: true }); }
};
async function undo(batchId) {
  try {
    const r = await runAction("restore", Array.isArray(batchId) ? { batch_ids: batchId } : { batch_id: batchId });
    toast(t("Đã trả {0} {0|file|files} về chỗ cũ.", num(r.restored)) + (r.failed.length ? " " + t("{0} {0|file|files} không trả về được.", num(r.failed.length)) : "") +
      (r.renamed && r.renamed.length ? " " + t("{0} {0|file|files} đã có file mới cùng tên nên được trả về với tên thêm \"(khôi phục)\".", num(r.renamed.length)) : "") +
      (r.cancelled ? " " + t("Đã dừng giữa chừng: bấm Lấy lại lần nữa để trả nốt.") : ""), { err: r.failed.length > 0 });
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
  $("#qSummary").innerHTML = pendingFiles ? t("Đang cất giữ <b>{0} {0|file|files}</b> (khoảng {1}).", num(pendingFiles), fmt(pendingBytes)) : "";
  $("#batchList").innerHTML = visible.length ? `<div class="row head"><div class="name">${t("Lần dọn")}</div><span class="kind">${t("Trạng thái")}</span><div class="size">${t("Dung lượng")}</div><span class="acts2"></span></div>` + visible.map((b) => `
    <div class="row"><div class="name"><div class="t">${esc(b.reason ? tReason(b.reason) : t("Dọn dẹp"))} · ${t("{0} {0|file|files}", num(b.files))}</div><div class="p">${fmtDate(b.ts)}</div></div>
    <span class="kind"><span class="tag ${b.pending ? "" : "ok"}">${b.moves ? (b.pending ? t("Đã sắp xếp") : t("Đã hoàn tác")) : b.pending ? t("Đang cất giữ") : b.purged ? t("Đã xóa vĩnh viễn") : t("Đã lấy lại")}</span></span>
    <div class="size">${fmt(b.bytes)}</div>
    <span class="acts2">${b.pending && b.moves ? `<button class="btn small primary" data-restore="${b.batch_id}">↩ ${t("Hoàn tác")}</button>` : b.pending ? `<button class="btn small primary" data-restore="${b.batch_id}">↩ ${t("Lấy lại")}</button>
    <button class="btn small ghost danger-text" data-purge="${b.batch_id}">${t("Xóa vĩnh viễn")}</button>` : ""}</span></div>`).join("")
    : `<div class="empty">${t("Khu cách ly đang trống. Các file anh/chị dọn sẽ xuất hiện ở đây.")}</div>`;
  const kinds = { quarantine: t("Đã dọn"), restore: t("Lấy lại"), purge: t("Xóa vĩnh viễn"), error: t("Giữ nguyên"), move: t("Sắp xếp") };
  $("#logList").innerHTML = log.length ? log.map((a) => `<div class="row"><span class="when">${fmtDate(a.ts)}</span>
    <span class="tag ${a.kind === "error" ? "keep" : ""}">${kinds[a.kind] || a.kind}</span><div class="name"><div class="t">${esc(a.path)}</div>${a.kind === "error" ? `<div class="p">${esc(a.reason || "")}</div>` : ""}</div><div class="size">${a.size ? fmt(a.size) : ""}</div></div>`).join("")
    : `<div class="empty">${t("Chưa có thao tác nào.")}</div>`;
  $$("[data-restore]").forEach((b) => b.onclick = () => undo(b.dataset.restore));
  $$("[data-purge]").forEach((b) => b.onclick = async () => {
    if (!(await dialog(t("Xóa vĩnh viễn lần dọn này?"), `<p>${t("Các file trong lần dọn này sẽ bị <b>xóa hẳn khỏi máy</b> và <b>không thể lấy lại</b>.")}</p>`, t("Xóa vĩnh viễn")))) return;
    const r = await runAction("purge", { batch_id: b.dataset.purge }).catch((e) => toast(e.message, { err: true }));
    if (r) toast(t("Đã giải phóng {0}.", fmt(r.freed)));
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
    ? t("Tìm thấy <b>{0} nhóm</b> ảnh giống nhau, dọn bớt có thể giải phóng khoảng <b>{1}</b>.", num(d.group_count), fmt(d.saving)) +
      `<br><span class="muted">${t("Ảnh có nhãn “Giữ lại” là ảnh nét nhất (độ phân giải cao nhất) của nhóm. Hãy xem kỹ ảnh trước khi dọn.")}</span>`
    : `<div class="empty">${t("Chưa có kết quả. Bấm “Tìm ảnh giống nhau” để bắt đầu.")}</div>`;
  $("#simList").innerHTML = d.groups.map((g) => `<div class="group"><div class="group-head"><b>${t("{0} ảnh giống nhau", g.files.length)}</b><span class="muted">${t("dọn bớt được {0}", fmt(g.saving))}</span></div>
    <div class="photo-grid">${g.files.map((f, i) => {
      const keep = i === 0 && f.exists;
      noteCloud(f);
      if (!keep && f.exists && !f.protected && !f.cloud) sel.set(f.path, f.size);
      const name = f.path.split(/[\\/]/).pop();
      return `<label class="photo ${keep ? "keep" : ""} ${!f.exists ? "gone" : ""}" title="${esc(f.why ? f.why + " · " + f.path : f.path)}">
        <div class="ph-img">${f.exists ? `<img loading="lazy" src="${thumbUrl(f.path)}" alt="">` : t("Đã dọn")}</div>
        <div class="ph-meta">${f.exists && !f.protected ? `<input type="checkbox" data-sel="similar" data-size="${f.size}" value="${esc(f.path)}" ${sel.has(f.path) ? "checked" : ""}>` : f.protected ? "🔒" : ""}
          <div class="name"><div class="t">${esc(name)}</div><div class="p">${f.width}×${f.height} · ${fmt(f.size)}${f.cloud ? ` · ☁ ${esc(f.cloud)}` : ""}</div></div></div>
        ${keep ? `<span class="tag ok ph-tag">✓ ${t("Giữ lại")}</span>` : ""}
        ${f.exists ? `<button class="btn small ghost ph-open" data-reveal="${esc(f.path)}" title="${t("Xem vị trí")}">📂</button>` : ""}
      </label>`;
    }).join("")}</div></div>`).join("");
  bindSelection("#view-similar", "similar");
}

// ---------- system junk ----------
$("#junkRun").onclick = async () => { try { await api("junk-scan", {}); pollJob(); } catch (e) { toast(e.message, { err: true }); } };
function renderJunk() {
  const list = state.junk;
  if (!list) {
    $("#junkList").innerHTML = `<div class="empty">${t("Bấm “Kiểm tra rác hệ thống” để xem máy đang có bao nhiêu rác. Việc kiểm tra chỉ đọc, chưa xóa gì.")}</div>`;
    $("#junkBar").classList.add("hidden"); $("#junkInfo").textContent = ""; return;
  }
  const total = list.reduce((a, c) => a + c.size, 0);
  $("#junkInfo").innerHTML = t("Tìm thấy tổng cộng <b>{0}</b>", fmt(total));
  $("#junkList").innerHTML = list.map((c) => `
    <label class="row ${c.count ? "pick" : "locked"}">
      <span class="cb">${c.count ? `<input type="checkbox" data-junk="${c.id}" data-size="${c.size}" ${c.selected ? "checked" : ""}>` : ""}</span>
      <div class="name"><div class="t">${esc(t(c.name))} ${c.label === "safe" ? `<span class="tag ok">${t("An toàn")}</span>` : `<span class="tag warn-tag">${t("Cân nhắc")}</span>`}${c.admin ? ` <span class="tag" title="${t("Một số file cần quyền quản trị; file không đủ quyền sẽ được bỏ qua.")}">${t("Cần quyền quản trị")}</span>` : ""}</div>
        <div class="p wrap">${esc(t(c.desc))}</div></div>
      <span class="when">${c.count ? t("{0} {0|file|files}", num(c.count)) : t("Sạch")}</span>
      <div class="size">${c.count ? fmt(c.size) : "—"}</div>
    </label>`).join("") || `<div class="empty">${t("Không tìm thấy rác.")}</div>`;
  const upd = () => {
    let n = 0, sz = 0; $$("[data-junk]:checked").forEach((c) => { n++; sz += +c.dataset.size; c.closest(".row").classList.add("checked"); });
    $$("[data-junk]:not(:checked)").forEach((c) => c.closest(".row").classList.remove("checked"));
    $("#junkSel").innerHTML = n ? t("Đã chọn <b>{0} {0|mục|mục}</b> · khoảng <b>{1}</b>", n, fmt(sz)) : `<span class="muted">${t("Chưa chọn mục nào")}</span>`;
    $("#junkClean").disabled = !n;
  };
  $$("[data-junk]").forEach((c) => c.onchange = upd);
  $("#junkBar").classList.toggle("hidden", !list.some((c) => c.count)); upd();
}
$("#junkClean").onclick = async () => {
  const ids = $$("[data-junk]:checked").map((c) => c.dataset.junk);
  if (!ids.length) return;
  if (!(await dialog(t("Dọn rác hệ thống?"), `<p>${t("Các file sẽ được chuyển vào <b>Khu cách ly</b> (lấy lại được). File đang được chương trình khác sử dụng hoặc cần quyền quản trị sẽ được bỏ qua.")}</p><p class="muted">${t("Nên đóng trình duyệt trước khi dọn bộ nhớ đệm trình duyệt.")}</p>`, "🧹 " + t("Dọn ngay")))) return;
  try {
    const r = await runAction("junk-clean", { ids });
    toast(t("Đã dọn {0} file rác ({1}).", num(r.moved), fmt(r.bytes)) + (r.skipped ? " " + t("Bỏ qua {0} {0|file|files} đang dùng hoặc cần quyền.", num(r.skipped)) : "") + stopped(r),
      r.batch_ids.length ? { action: "↩ " + t("Hoàn tác"), onAction: () => undo(r.batch_ids) } : {});
    refreshBadge(); state.junk = null; await api("junk-scan", {}); pollJob();
  } catch (e) { toast(e.message, { err: true }); }
};

// ---------- startup programs ----------
const LABELS = { safe: ["ok", "Có thể tắt"], unknown: ["", "Chưa rõ"], keep: ["keep", "Nên giữ"] };
$$("#startupFilter .chip").forEach((b) => b.onclick = () => { state.startupFilter = b.dataset.f; $$("#startupFilter .chip").forEach((x) => x.classList.toggle("active", x === b)); drawStartup(); });
$("#startupReload").onclick = () => { state.startup = null; renderStartup(); };
async function renderStartup() {
  if (!state.startup) {
    $("#startupList").innerHTML = `<div class="empty"><div class="spinner inline"></div> ${t("Đang đọc danh sách chương trình…")}</div>`;
    try { state.startup = await api("startup"); } catch (e) { $("#startupList").innerHTML = `<div class="empty">${t("Không đọc được: {0}", esc(e.message))}</div>`; return; }
  }
  const plat = state.info ? state.info.platform : "";
  $("#startupNote").innerHTML = plat === "windows"
    ? `<div class="info">${t("Với mục có nhãn <b>Cần quyền quản trị</b>, Windows sẽ hỏi “Cho phép ứng dụng thay đổi thiết bị?”. Trước lần thay đổi đầu tiên, ứng dụng sẽ đề nghị tạo <b>điểm khôi phục hệ thống</b> để có thể quay lại nếu cần.")}</div>`
    : plat === "mac" ? `<div class="info">${t("macOS có thể hỏi quyền điều khiển “System Events” khi đọc mục đăng nhập. Mục <b>Dịch vụ hệ thống</b> cần nhập mật khẩu máy.")}</div>`
    : `<div class="info">${t("Tính năng này dành cho Windows và macOS.")}</div>`;
  drawStartup();
}
function drawStartup() {
  const items = (state.startup && state.startup.items) || [];
  const f = state.startupFilter;
  const shown = items.filter((i) => f === "all" || (f === "off" ? !i.enabled : i.label === f));
  $("#startupList").innerHTML = shown.length ? shown.map((i) => {
    const [cls, txt] = LABELS[i.label] || ["", i.label];
    return `<div class="row ${i.enabled ? "" : "is-off"}">
      <div class="name"><div class="t">${esc(i.name)} <span class="tag ${cls}" title="${esc(t(i.why))}">${t(txt)}</span>${i.admin ? ` <span class="tag">${t("Cần quyền quản trị")}</span>` : ""}</div>
        <div class="p">${esc(t(i.where))}${i.command ? " · " + esc(i.command) : ""}</div><div class="p why">${esc(t(i.why))}</div></div>
      <label class="switch" title="${i.enabled ? t("Đang bật – bấm để tắt") : t("Đang tắt – bấm để bật lại")}"><input type="checkbox" data-startup="${esc(i.id)}" ${i.enabled ? "checked" : ""}><span></span></label>
      <span class="state">${i.enabled ? t("Đang bật") : t("Đã tắt")}</span>
    </div>`;
  }).join("") : `<div class="empty">${items.length ? t("Không có mục nào trong nhóm này.") : t("Không có chương trình nào tự khởi động.")}</div>`;
  $$("[data-startup]").forEach((c) => c.onchange = () => toggleStartup(c.dataset.startup, c.checked, c));
}
async function toggleStartup(id, enable, el) {
  const item = state.startup.items.find((i) => i.id === id);
  el.disabled = true;
  try {
    if (!enable && item.admin && state.info.platform === "windows" && !state.restorePointDone) {
      const ans = await dialog(t("Tạo điểm khôi phục trước?"),
        `<p>${t("Mục này cần quyền quản trị. Nên tạo <b>điểm khôi phục hệ thống</b> trước để có thể đưa Windows về trạng thái hiện tại nếu có trục trặc.")}</p><p class="muted">${t("Windows sẽ hỏi quyền quản trị. Việc tạo mất khoảng một phút.")}</p>`,
        t("Tạo điểm khôi phục rồi tắt"), t("Hủy"), t("Tắt luôn"));
      if (!ans) { el.checked = !enable; return; }
      if (ans === true) {
        toast(t("Đang tạo điểm khôi phục…"));
        const r = await api("restore-point", {});
        if (!r.ok && !(await dialog(t("Chưa tạo được điểm khôi phục"), `<p>${esc(r.error || "")}</p><p>${t("Vẫn tiếp tục tắt? Anh/chị vẫn có thể bật lại mục này trong ứng dụng.")}</p>`, t("Vẫn tắt")))) { el.checked = !enable; return; }
        if (r.ok) toast(t("Đã tạo điểm khôi phục."));
      }
      state.restorePointDone = true;
    }
    await api("startup-set", { id, enable });
    item.enabled = enable;
    toast(enable ? t("Đã bật lại “{0}”.", item.name) : t("Đã tắt “{0}”. Lần khởi động sau nó sẽ không tự chạy.", item.name),
      enable ? {} : { action: "↩ " + t("Bật lại"), onAction: async () => { await api("startup-set", { id, enable: true }); item.enabled = true; drawStartup(); toast(t("Đã bật lại “{0}”.", item.name)); } });
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
  if (!folder) { toast(t("Hãy chọn thư mục trước.")); return; }
  try { state.org = await api("organize-preview", { folder, by_year: $("#orgByYear").checked }); } catch (e) { toast(e.message, { err: true }); return; }
  const o = state.org;
  if (!o.moves.length) { $("#orgSummary").innerHTML = `<div class="empty">${t("Thư mục này đã gọn gàng: không có file lẻ nào cần sắp xếp.")}</div>`; $("#orgList").classList.add("hidden"); $("#orgBar").classList.add("hidden"); return; }
  $("#orgSummary").innerHTML = t("Sẽ sắp xếp <b>{0} {0|file|files}</b> trong <b>{1}</b> vào các thư mục:", num(o.moves.length), esc(o.folder)) +
    `<div class="chips static">${o.summary.map((x) => `<span class="chip">📁 ${esc(x.target)} <b>${num(x.count)}</b></span>`).join("")}</div><span class="muted">${t("Thư mục con có sẵn được giữ nguyên. Không file nào bị ghi đè; file trùng tên sẽ được thêm số (2), (3)…")}</span>`;
  $("#orgList").classList.remove("hidden");
  $("#orgList").innerHTML = `<div class="row head"><span class="cb"><input type="checkbox" id="orgAll" checked></span><div class="name">${t("File")}</div><span class="arrow"></span><div class="target">${t("Chuyển vào")}</div><div class="size">${t("Dung lượng")}</div></div>` +
    o.moves.map((m) => `<label class="row pick checked"><span class="cb"><input type="checkbox" data-orgsel value="${esc(m.src)}" checked></span>
      <div class="name"><div class="t">${esc(m.name)}</div>${m.renamed ? `<div class="p">${t("sẽ đổi tên thành {0} vì trùng tên", esc(m.dest.split(/[\\/]/).pop()))}</div>` : ""}</div>
      <span class="arrow">→</span><div class="target">📁 ${esc(m.target)}</div><div class="size">${fmt(m.size)}</div></label>`).join("");
  const upd = () => {
    const n = $$("[data-orgsel]:checked").length;
    $$("[data-orgsel]").forEach((c) => c.closest(".row").classList.toggle("checked", c.checked));
    $("#orgSel").innerHTML = n ? t("Đã chọn <b>{0} {0|file|files}</b>", num(n)) : `<span class="muted">${t("Chưa chọn file nào")}</span>`;
    $("#orgApply").disabled = !n; $("#orgApply").textContent = "📦 " + (n ? t("Sắp xếp {0} {0|file|files}", num(n)) : t("Sắp xếp"));
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
    const r = await runAction("organize-apply", { folder: state.org.folder, chosen, by_year: $("#orgByYear").checked });
    toast(t("Đã sắp xếp {0} {0|file|files}.", num(r.moved)) + (r.failed.length ? " " + t("{0} {0|file|files} giữ nguyên.", num(r.failed.length)) : ""),
      { err: r.failed.length > 0, action: "↩ " + t("Hoàn tác"), onAction: () => undo(r.batch_id).then(previewOrganize) });
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
  $("#schStatus").innerHTML = (!c.supported ? `<div class="info">${t("Dọn dẹp theo lịch dành cho Windows và macOS.")}</div>` : "") +
    (c.enabled && c.health && !c.health.ok ? `<div class="info warn">⚠️ ${esc(t(c.health.message))}</div>` :
    `<p>${c.enabled ? (c.registered ? "✅ " + t("Lịch đang bật và đã được đăng ký với hệ điều hành.") : "⚠️ " + t("Lịch đang bật nhưng chưa đăng ký được với hệ điều hành. Hãy bấm Lưu lịch lần nữa.")) : t("Lịch đang tắt.")}</p>`) +
    (last && last.skipped ? `<p class="muted">${t("Lần chạy gần nhất: {0}", fmtDate(last.ts))} · ${esc(t(last.skipped))}.</p>` : last ? `<p class="muted">${t("Lần chạy gần nhất: {0}", fmtDate(last.ts))} · ${t("dọn {0} file rác ({1})", num(last.junk_moved), fmt(last.junk_bytes))}${last.purged_bytes ? " · " + t("xóa hẳn {0} trong khu cách ly", fmt(last.purged_bytes)) : ""}.</p>` : `<p class="muted">${t("Chưa chạy lần nào.")}</p>`) +
    `<p class="muted">${t("Khu cách ly đang giữ {0}.", fmt(c.pending_bytes))}</p>`;
}
$("#schSave").onclick = async () => {
  try {
    await api("schedule", { enabled: $("#schEnabled").checked, frequency: $("#schFreq").value, hour: +$("#schHour").value, junk: $("#schJunk").checked, purge_days: +$("#schPurge").value });
    toast($("#schEnabled").checked ? t("Đã lưu và bật lịch dọn dẹp.") : t("Đã tắt lịch dọn dẹp.")); renderSchedule();
  } catch (e) { toast(e.message, { err: true }); }
};
$("#schRunNow").onclick = async () => {
  const purge = +$("#schPurge").value;
  if (!(await dialog(t("Chạy dọn dẹp tự động ngay?"), `<p>${purge ? t("Ứng dụng sẽ làm đúng những gì lịch sẽ làm: dọn các mục rác hệ thống <b>an toàn</b> vào khu cách ly, và xóa hẳn file đã nằm trong khu cách ly quá số ngày đã chọn.") : t("Ứng dụng sẽ làm đúng những gì lịch sẽ làm: dọn các mục rác hệ thống <b>an toàn</b> vào khu cách ly.")}</p>`, t("Chạy ngay")))) return;
  try { const r = await runAction("schedule-run", {}); toast(t("Đã dọn {0} file rác ({1}).", num(r.junk_moved), fmt(r.junk_bytes))); refreshBadge(); renderSchedule(); } catch (e) { toast(e.message, { err: true }); }
};

window.addEventListener("resize", () => { if (state.view === "usage") renderUsage(); if (state.view === "home" && state.dash) renderHistory(state.dash); });
(async () => {
  try {
    state.info = await api("info");
    applyTheme(state.info.settings.theme);
    await loadLang(state.info.settings.lang);
  } catch (e) { await loadLang("vi"); toast(e.message, { err: true }); }
  applyAppName();
  await loadScans().catch((e) => toast(e.message, { err: true })); refreshBadge(); render("home"); pollJob();
  if (state.info && !state.info.settings.onboarded) openGuide();
  else api("update").then((u) => { if (u.available) toast(t("Đã có phiên bản mới {0}.", u.available.version), { action: t("Xem"), onAction: () => show("settings") }); }).catch(() => {});
})();
