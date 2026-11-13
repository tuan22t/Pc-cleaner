"use strict";
const TOKEN = new URLSearchParams(location.hash.slice(1)).get("token") || sessionStorage.getItem("pcc_token") || "";
try { sessionStorage.setItem("pcc_token", TOKEN); } catch (e) {}
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const COLORS = ["--c1", "--c2", "--c3", "--c5", "--c6", "--c7", "--c4", "--c8"].map((v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim());

const state = { scanId: null, dirId: 0, view: "home", sel: { large: new Set(), old: new Set(), dups: new Set() }, polling: null, lastJob: null };

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
  return (i ? n.toFixed(n < 10 ? 2 : n < 100 ? 1 : 0) : n) + " " + u[i];
}
const fmtDate = (t) => new Date(t * 1000).toLocaleString("vi-VN");
const fmtDay = (t) => new Date(t * 1000).toLocaleDateString("vi-VN");
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function toast(msg, err) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (err ? " err" : "");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), 4500);
}
function confirmBox(title, html) {
  return new Promise((res) => {
    $("#modalTitle").textContent = title; $("#modalBody").innerHTML = html; $("#modal").classList.remove("hidden");
    const done = (v) => { $("#modal").classList.add("hidden"); $("#modalOk").onclick = $("#modalCancel").onclick = null; res(v); };
    $("#modalOk").onclick = () => done(true); $("#modalCancel").onclick = () => done(false);
  });
}

// ---------- navigation ----------
function show(view) {
  state.view = view;
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + view));
  $$("nav a[data-view]").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  render(view);
}
$$("nav a[data-view]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); show(a.dataset.view); }));
function updateNav() { $$("nav a[data-needs-scan]").forEach((a) => a.classList.toggle("disabled", !state.scanId)); }

async function render(view) {
  try {
    if (view === "home") return renderHome();
    if (view === "quarantine") return renderQuarantine();
    if (!state.scanId) return;
    if (view === "usage") return renderUsage();
    if (view === "large") return renderLarge();
    if (view === "old") return renderOld();
    if (view === "types") return renderTypes();
    if (view === "dups") return renderDups();
  } catch (e) { toast(e.message, true); }
}

// ---------- home ----------
async function renderHome() {
  const info = await api("info");
  $("#locations").innerHTML = info.locations.map((l) => {
    const pct = l.total ? (l.used / l.total) * 100 : 0;
    return `<div class="card"><h3>${esc(l.label)}</h3><div class="path">${esc(l.path)}</div>
      <div class="meter ${pct > 90 ? "high" : ""}"><div style="width:${pct.toFixed(1)}%"></div></div>
      <div class="muted">Đã dùng ${fmt(l.used)} / ${fmt(l.total)} · còn trống <b>${fmt(l.free)}</b></div>
      <button class="btn primary" data-scan="${esc(l.path)}">Quét</button></div>`;
  }).join("");
  $$("[data-scan]").forEach((b) => b.onclick = () => startScan(b.dataset.scan));
  await loadScans();
  const scans = await api("scans");
  $("#recentScans").innerHTML = scans.length ? `<div class="list">${scans.map((s) => `
    <div class="row"><div class="name"><div class="t">${esc(s.root)}</div><div class="p">${fmtDate(s.finished)} · ${s.file_count.toLocaleString("vi-VN")} file · ${Math.round(s.finished - s.started)} giây${s.error_count ? ` · ${s.error_count} mục không đọc được` : ""}</div></div>
    <div class="size">${fmt(s.total_size)}</div><button class="btn small" data-open="${s.id}">Xem</button></div>`).join("")}</div>`
    : `<div class="list"><div class="empty">Chưa quét lần nào.</div></div>`;
  $$("[data-open]").forEach((b) => b.onclick = () => { selectScan(+b.dataset.open); show("usage"); });
}
$("#customScanBtn").onclick = () => { const p = $("#customPath").value.trim(); if (p) startScan(p); };

async function loadScans() {
  const scans = await api("scans");
  $("#scanSelect").innerHTML = scans.length ? scans.map((s) => `<option value="${s.id}">${esc(s.root)} · ${fmtDay(s.finished)}</option>`).join("") : `<option value="">(chưa có)</option>`;
  if (scans.length && !scans.find((s) => s.id === state.scanId)) state.scanId = scans[0].id;
  if (state.scanId) $("#scanSelect").value = state.scanId;
  updateNav();
}
$("#scanSelect").onchange = (e) => { selectScan(+e.target.value); render(state.view); };
function selectScan(id) { state.scanId = id; state.dirId = 0; Object.values(state.sel).forEach((s) => s.clear()); $("#scanSelect").value = id; updateNav(); }

// ---------- jobs ----------
async function startScan(path) {
  try { await api("scan", { path }); pollJob(); } catch (e) { toast(e.message, true); }
}
$("#jobCancel").onclick = () => api("cancel", {});
function pollJob() {
  clearInterval(state.polling);
  const tick = async () => {
    const j = await api("job").catch(() => null);
    if (!j) return;
    const bar = $("#jobBar");
    if (j.state === "running") {
      bar.classList.remove("hidden");
      const p = j.progress || {};
      if (j.kind === "scan") {
        $("#jobTitle").textContent = "Đang quét " + j.root;
        $("#jobDetail").textContent = `${(p.files || 0).toLocaleString("vi-VN")} file · ${fmt(p.bytes || 0)} · ${p.current || ""}`;
        $(".progress").classList.add("indeterminate"); $("#jobProgress").style.width = "30%";
      } else {
        $("#jobTitle").textContent = p.stage || "Đang tìm file trùng";
        $("#jobDetail").textContent = p.total ? `${p.done}/${p.total} · ${p.current || ""}` : "";
        $(".progress").classList.toggle("indeterminate", !p.total);
        $("#jobProgress").style.width = p.total ? (100 * p.done / p.total).toFixed(1) + "%" : "30%";
      }
      $$("[data-scan], #customScanBtn, #dupRun").forEach((b) => b.disabled = true);
      return;
    }
    clearInterval(state.polling); bar.classList.add("hidden");
    $$("[data-scan], #customScanBtn, #dupRun").forEach((b) => b.disabled = false);
    if (state.lastJob === j.started) return;
    state.lastJob = j.started;
    if (j.state === "done" && j.kind === "scan") { await loadScans(); selectScan(j.result); toast("Quét xong."); show("usage"); }
    else if (j.state === "done" && j.kind === "duplicates") { toast(`Tìm thấy ${j.result} nhóm file trùng.`); if (state.view === "dups") renderDups(); }
    else if (j.state === "cancelled") toast("Đã dừng.");
    else if (j.state === "error") toast("Lỗi: " + j.error, true);
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

async function renderUsage() {
  const d = await api(`scan/${state.scanId}/children?dir=${state.dirId}`);
  $("#crumbs").innerHTML = d.crumbs.map((c, i) => (i ? '<span class="sep">›</span>' : "") + `<a data-dir="${c.id}">${esc(c.name)}</a>`).join("") + ` <span class="muted">· ${fmt(d.dir.size)} · ${d.dir.count.toLocaleString("vi-VN")} file</span>`;
  const max = d.items.length ? d.items[0].size : 1;
  $("#usageList").innerHTML = d.items.length ? d.items.map((it) => `
    <div class="row ${it.type}" ${it.type === "dir" ? `data-dir="${it.id}"` : ""}>
      <span class="ico">${it.type === "dir" ? "📁" : "📄"}</span>
      <div class="name"><div class="t">${esc(it.name)}</div>${it.type === "dir" ? `<div class="p">${it.count.toLocaleString("vi-VN")} file</div>` : `<div class="p">sửa ${fmtDay(it.mtime)}</div>`}</div>
      <div class="bar"><div style="width:${max ? (100 * it.size / max).toFixed(1) : 0}%"></div></div>
      <div class="size">${fmt(it.size)}</div>
      <div class="acts"><button class="btn small ghost" data-reveal="${esc(it.path)}" title="Mở trong Explorer/Finder">Mở</button></div>
    </div>`).join("") : `<div class="empty">Thư mục trống.</div>`;
  const tm = $("#treemap"); const W = tm.clientWidth, H = tm.clientHeight;
  const tiles = squarify(d.items.filter((i) => i.size > 0).slice(0, 40), 0, 0, W, H);
  tm.innerHTML = tiles.map((t, i) => `<div class="tile" ${t.it.type === "dir" ? `data-dir="${t.it.id}"` : ""} title="${esc(t.it.path)} · ${fmt(t.it.size)}"
     style="left:${t.x}px;top:${t.y}px;width:${t.w}px;height:${t.h}px;background:${COLORS[i % COLORS.length]}">${t.w > 60 && t.h > 30 ? `${esc(t.it.name)}<small>${fmt(t.it.size)}</small>` : ""}</div>`).join("");
  $$("#view-usage [data-dir]").forEach((el) => el.addEventListener("click", (e) => { if (e.target.closest("button")) return; state.dirId = +el.dataset.dir; renderUsage(); }));
  bindReveal("#view-usage");
}
function bindReveal(scope) {
  $$(scope + " [data-reveal]").forEach((b) => b.onclick = (e) => { e.stopPropagation(); api("reveal", { path: b.dataset.reveal }).catch((er) => toast(er.message, true)); });
}

// ---------- file lists with selection ----------
function fileRows(list, key) {
  const sel = state.sel[key];
  if (!list.length) return `<div class="empty">Không có file nào phù hợp.</div>`;
  return list.map((f) => `
    <div class="row">
      <input type="checkbox" data-sel="${key}" value="${esc(f.path)}" ${sel.has(f.path) ? "checked" : ""} ${f.protected ? "disabled" : ""}>
      <div class="name"><div class="t">${esc(f.name)}</div><div class="p">${esc(f.path)}</div></div>
      ${f.protected ? '<span class="tag keep">hệ thống – giữ</span>' : `<span class="tag">${esc(f.category)}</span>`}
      <span class="muted" style="width:90px">${fmtDay(f.mtime)}</span>
      <div class="size">${fmt(f.size)}</div>
      <button class="btn small ghost" data-reveal="${esc(f.path)}">Mở</button>
    </div>`).join("");
}
function bindSelection(scope, key, sizes) {
  const upd = () => {
    let total = 0; state.sel[key].forEach((p) => total += sizes.get(p) || 0);
    $(`#${key}Sel`).textContent = state.sel[key].size ? `Đã chọn ${state.sel[key].size} file · ${fmt(total)}` : "";
  };
  $$(scope + ` [data-sel="${key}"]`).forEach((c) => c.onchange = () => { c.checked ? state.sel[key].add(c.value) : state.sel[key].delete(c.value); upd(); });
  upd(); bindReveal(scope);
}
async function renderLarge() {
  const list = await api(`scan/${state.scanId}/large?min=${$("#largeMin").value}`);
  state.cache_large = list;
  $("#largeList").innerHTML = fileRows(list, "large");
  bindSelection("#view-large", "large", new Map(list.map((f) => [f.path, f.size])));
}
$("#largeMin").onchange = renderLarge;
async function renderOld() {
  const list = await api(`scan/${state.scanId}/old?days=${$("#oldDays").value}&min=${$("#oldMin").value}`);
  $("#oldList").innerHTML = fileRows(list, "old");
  bindSelection("#view-old", "old", new Map(list.map((f) => [f.path, f.size])));
}
$("#oldDays").onchange = $("#oldMin").onchange = renderOld;

async function renderTypes() {
  const d = await api(`scan/${state.scanId}/summary`);
  const bars = (rows, label) => { const m = rows.length ? rows[0].size : 1; return rows.map((r, i) => `
    <div class="b"><div>${esc(label(r))} <span class="muted">(${r.count.toLocaleString("vi-VN")})</span></div>
    <div class="track"><div style="width:${(100 * r.size / m).toFixed(1)}%;background:${COLORS[i % COLORS.length]}"></div></div><div class="v">${fmt(r.size)}</div></div>`).join(""); };
  $("#catList").innerHTML = bars(d.categories, (r) => r.category);
  $("#extList").innerHTML = bars(d.extensions, (r) => "." + r.ext);
}

// ---------- duplicates ----------
$("#dupRun").onclick = async () => {
  try { await api("duplicates", { scan_id: state.scanId, min_size: +$("#dupMin").value }); pollJob(); } catch (e) { toast(e.message, true); }
};
async function renderDups() {
  const d = await api(`scan/${state.scanId}/duplicates`);
  const sel = state.sel.dups; sel.clear(); const sizes = new Map();
  $("#dupSummary").innerHTML = d.group_count ? `<b>${d.group_count}</b> nhóm file trùng, có thể giải phóng <b>${fmt(d.wasted)}</b>. Mặc định giữ bản cũ nhất của mỗi nhóm.` : `<span class="muted">Chưa có kết quả. Bấm “Tìm file trùng”.</span>`;
  $("#dupList").innerHTML = d.groups.map((g) => {
    let kept = false;
    const rows = g.files.map((f) => {
      sizes.set(f.path, g.size);
      let keep = false;
      if (!kept && f.exists) { keep = true; kept = true; }
      if (!keep && !f.protected && f.exists) sel.add(f.path);
      return `<div class="row"><input type="checkbox" data-sel="dups" value="${esc(f.path)}" ${sel.has(f.path) ? "checked" : ""} ${f.protected || !f.exists ? "disabled" : ""}>
        <div class="name"><div class="t">${esc(f.path)}</div><div class="p">sửa ${fmtDate(f.mtime)}</div></div>
        ${keep ? '<span class="tag ok">giữ lại</span>' : f.protected ? '<span class="tag keep">hệ thống – giữ</span>' : !f.exists ? '<span class="tag">đã mất</span>' : ""}
        <button class="btn small ghost" data-reveal="${esc(f.path)}">Mở</button></div>`;
    }).join("");
    return `<div class="group"><div class="group-head"><b>${g.files.length} bản</b><span>${fmt(g.size)} mỗi bản</span><span class="muted">thừa ${fmt(g.wasted)}</span></div>${rows}</div>`;
  }).join("");
  bindSelection("#view-dups", "dups", sizes);
}

// ---------- quarantine ----------
$$("[data-quarantine]").forEach((b) => b.onclick = async () => {
  const key = b.dataset.quarantine; const files = [...state.sel[key]];
  if (!files.length) return toast("Chưa chọn file nào.");
  const ok = await confirmBox(`Chuyển ${files.length} file vào khu cách ly?`,
    `<p>File sẽ được chuyển vào khu cách ly của ứng dụng, <b>chưa bị xóa hẳn</b>. Bạn có thể hoàn tác bất cứ lúc nào trong mục “Khu cách ly &amp; nhật ký”.</p>
     <div class="list small" style="max-height:200px;overflow:auto">${files.slice(0, 50).map((f) => `<div class="row">${esc(f)}</div>`).join("")}${files.length > 50 ? `<div class="row muted">… và ${files.length - 50} file khác</div>` : ""}</div>`);
  if (!ok) return;
  try {
    const r = await api("quarantine", { paths: files, reason: { large: "File lớn", old: "File cũ", dups: "File trùng lặp" }[key] });
    state.sel[key].clear();
    toast(`Đã cách ly ${r.moved} file (${fmt(r.bytes)}).` + (r.failed.length ? ` ${r.failed.length} file không chuyển được.` : ""), r.failed.length > 0);
    render(state.view);
  } catch (e) { toast(e.message, true); }
});

async function renderQuarantine() {
  const [batches, log] = await Promise.all([api("batches"), api("log")]);
  const visible = batches.filter((b) => b.files > 0);
  $("#batchList").innerHTML = visible.length ? visible.map((b) => `
    <div class="row"><div class="name"><div class="t">${esc(b.reason || "Dọn dẹp")} · ${b.files} file</div><div class="p">${fmtDate(b.ts)} · ${b.batch_id}</div></div>
    <span class="tag ${b.pending ? "" : "ok"}">${b.pending ? `${b.pending} đang cách ly` : b.purged ? "đã xóa hẳn" : "đã hoàn tác"}</span>
    <div class="size">${fmt(b.bytes)}</div>
    <button class="btn small" data-restore="${b.batch_id}" ${b.pending ? "" : "disabled"}>Hoàn tác</button>
    <button class="btn small ghost" data-purge="${b.batch_id}" ${b.pending ? "" : "disabled"}>Xóa hẳn</button></div>`).join("")
    : `<div class="empty">Khu cách ly trống.</div>`;
  const kinds = { quarantine: "Cách ly", restore: "Hoàn tác", purge: "Xóa hẳn", error: "Lỗi" };
  $("#logList").innerHTML = log.length ? log.map((a) => `<div class="row"><span style="width:140px" class="muted">${fmtDate(a.ts)}</span>
    <span class="tag ${a.kind === "error" ? "keep" : ""}">${kinds[a.kind] || a.kind}</span><div class="name"><div class="t">${esc(a.path)}</div>${a.kind === "error" ? `<div class="p">${esc(a.reason || "")}</div>` : ""}</div><div class="size">${a.size ? fmt(a.size) : ""}</div></div>`).join("")
    : `<div class="empty">Chưa có thao tác nào.</div>`;
  $$("[data-restore]").forEach((b) => b.onclick = async () => {
    const r = await api("restore", { batch_id: b.dataset.restore }).catch((e) => toast(e.message, true));
    if (r) toast(`Đã trả ${r.restored} file về chỗ cũ.` + (r.failed.length ? ` ${r.failed.length} file lỗi.` : ""), r.failed.length > 0);
    renderQuarantine();
  });
  $$("[data-purge]").forEach((b) => b.onclick = async () => {
    if (!(await confirmBox("Xóa hẳn đợt này?", "<p>Các file trong đợt này sẽ bị <b>xóa vĩnh viễn</b> và không thể hoàn tác.</p>"))) return;
    const r = await api("purge", { batch_id: b.dataset.purge }).catch((e) => toast(e.message, true));
    if (r) toast(`Đã giải phóng ${fmt(r.freed)}.`);
    renderQuarantine();
  });
}

window.addEventListener("resize", () => { if (state.view === "usage") renderUsage(); });
(async () => { await loadScans().catch((e) => toast(e.message, true)); render("home"); pollJob(); })();
