"use strict";
/* Tracker de continut social - interfata. Fara framework, fetch + DOM direct. */

const state = {
  boot: null,           // raspunsul /api/bootstrap
  week: null,           // saptamana curent afisata (ex. '2026-W38')
  tab: "dashboard",
  clientId: "",         // filtru activ ('' = toti)
  postStatus: "",
  allWeeks: false,
  importCsvText: "",    // continutul fisierului urcat pentru mapare, pastrat intre pasi
  importAccount: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// --------------------------------------------------------------------- api

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    // text (CSV brut) si binare (upload de fisier) merg ca atare; restul e JSON.
    const isRaw = typeof body === "string" || body instanceof ArrayBuffer ||
      body instanceof Blob || ArrayBuffer.isView(body);
    if (isRaw) {
      opts.body = body;
    } else {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
  }
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* raspuns fara body (rar) */ }
  if (!res.ok) throw new Error((data && data.error) || `Eroare ${res.status}`);
  return data;
}

function toast(message, kind = "") {
  const el = $("#toast");
  el.textContent = message;
  el.className = `toast ${kind}`;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 4200);
}

async function guarded(fn) {
  try { return await fn(); } catch (err) { toast(err.message, "err"); throw err; }
}

// --------------------------------------------------------------------- init

async function init() {
  state.boot = await api("GET", "/api/bootstrap");
  state.week = state.boot.week;
  fillSelect($("#clientFilter"), state.boot.clients, { keepFirst: true, value: "id", text: "name" });
  wireNav();
  wirePostDialog();
  wireSettings();
  wireImport();
  wireAddFromLink();
  await refreshAll();
}

function fillSelect(select, items, { keepFirst = false, value = "id", text = "name", placeholder } = {}) {
  const first = keepFirst ? select.firstElementChild : null;
  select.innerHTML = "";
  if (placeholder) {
    const opt = document.createElement("option");
    opt.value = ""; opt.textContent = placeholder;
    select.appendChild(opt);
  }
  if (first) select.appendChild(first);
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item[value];
    opt.textContent = item[text];
    select.appendChild(opt);
  }
}

async function refreshAll() {
  renderWeekLabel();
  if (state.tab === "dashboard") await renderDashboard();
  if (state.tab === "posts") await renderPosts();
  if (state.tab === "settings") await renderSettings();
}

function renderWeekLabel() {
  $("#weekLabel").textContent = state.week;
  $("#thisWeek").classList.toggle("active", state.week === state.boot.week);
}

// --------------------------------------------------------------------- navigatie

function wireNav() {
  $$(".tab").forEach((btn) => btn.addEventListener("click", () => {
    $$(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    state.tab = btn.dataset.tab;
    $$(".view").forEach((v) => { v.hidden = v.id !== `view-${state.tab}`; });
    refreshAll();
  }));

  $("#prevWeek").addEventListener("click", () => shiftWeek(-1));
  $("#nextWeek").addEventListener("click", () => shiftWeek(1));
  $("#thisWeek").addEventListener("click", () => { state.week = state.boot.week; refreshAll(); });
  $("#clientFilter").addEventListener("change", (e) => {
    state.clientId = e.target.value; refreshAll();
  });
}

function shiftWeek(delta) {
  // saptamana ISO urmatoare/anterioara, calculata local (fara alt request la server)
  const [y, w] = state.week.split("-W").map(Number);
  const jan4 = new Date(Date.UTC(y, 0, 4));
  const monday = new Date(jan4);
  monday.setUTCDate(jan4.getUTCDate() - ((jan4.getUTCDay() + 6) % 7) + (w - 1) * 7 + delta * 7);
  const target = new Date(Date.UTC(monday.getUTCFullYear(), monday.getUTCMonth(), monday.getUTCDate() + 3));
  const firstThu = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const weekNo = 1 + Math.round(((target - firstThu) / 86400000 - 3 + ((firstThu.getUTCDay() + 6) % 7)) / 7);
  state.week = `${target.getUTCFullYear()}-W${String(weekNo).padStart(2, "0")}`;
  refreshAll();
}

// --------------------------------------------------------------------- dashboard

async function renderDashboard() {
  const data = await guarded(() => api(
    "GET", `/api/dashboard?week=${state.week}${state.clientId ? `&client_id=${state.clientId}` : ""}`));
  state.week = data.week;
  renderWeekLabel();
  $("#weekLabel").textContent = `${data.label} · ${data.is_current ? `${data.days_left} zile ramase` : "saptamana trecuta/viitoare"}`;

  const t = data.totals;
  $("#summary").innerHTML = `
    <div class="stat"><div class="k">Tinta saptamana</div><div class="v">${t.target}</div></div>
    <div class="stat good"><div class="k">Postate</div><div class="v">${t.posted}</div></div>
    <div class="stat warn"><div class="k">In lucru</div><div class="v">${t.planned}</div></div>
    <div class="stat ${t.remaining ? "bad" : "good"}"><div class="k">Mai raman</div><div class="v">${t.remaining}</div></div>
    ${data.overdue ? `<div class="stat bad"><div class="k">Restante (saptamani trecute)</div><div class="v">${data.overdue}</div></div>` : ""}
  `;

  if (!data.clients.length) {
    $("#dashboardBody").innerHTML = `<div class="empty">Niciun cont cu plan pentru saptamana asta.
      Adauga un client si un cont din tab-ul Setari.</div>`;
    return;
  }

  $("#dashboardBody").innerHTML = data.clients.map((client) => {
    const accountCards = client.accounts.map(renderAccountCard).join("");
    return `
    <div class="client-block">
      <div class="client-head">
        <h2>${esc(client.name)}</h2>
        <span class="count">${client.totals.posted}/${client.totals.target} realizate</span>
      </div>
      ${client.rows.length ? `
        <div class="account" style="margin-bottom:12px">
          <div class="account-head">
            <span class="pill">Plan pe client</span>
            <span class="handle">acelasi material pe toate retelele se numara o data</span>
          </div>
          ${client.rows.map(renderGoalRow).join("")}
        </div>` : ""}
      ${accountCards ? `<div class="accounts">${accountCards}</div>` : ""}
    </div>`;
  }).join("");
}

function renderGoalRow(row) {
  const target = row.is_range ? `${row.target_min}-${row.target_max}` : `${row.target_min}`;
  const pct = row.target_min ? Math.min(100, Math.round((row.posted / row.target_min) * 100)) : 0;
  const planPct = row.target_min
    ? Math.min(100 - pct, Math.round((row.planned / row.target_min) * 100)) : 0;
  return `
    <div class="goal">
      <div class="goal-top">
        <span>${esc(row.label)} <span class="left">/ ${esc(row.period_label)}</span></span>
        <span class="num"><b>${row.posted}</b> / ${target}
          ${row.planned ? `<span class="left"> · ${row.planned} in lucru</span>` : ""}</span>
      </div>
      <div class="bar ${row.done ? "full" : ""}">
        <i class="done" style="width:${pct}%"></i>
        <i class="plan" style="width:${planPct}%"></i>
      </div>
    </div>`;
}

function renderAccountCard(account) {
  if (!account.rows.length) return "";
  return `
    <div class="account">
      <div class="account-head">
        <span class="pill ${account.platform}">${esc(account.platform_label)}</span>
        <span class="handle">${esc(account.handle)}</span>
      </div>
      ${account.rows.map(renderGoalRow).join("")}
    </div>`;
}

// --------------------------------------------------------------------- postari

async function renderPosts() {
  fillSelect($("#postStatusFilter"), state.boot.statuses,
    { keepFirst: true, value: "value", text: "label" });
  $("#postStatusFilter").value = state.postStatus;

  const qs = new URLSearchParams();
  if (!state.allWeeks) qs.set("week", state.week);
  if (state.clientId) qs.set("client_id", state.clientId);
  if (state.postStatus) qs.set("status", state.postStatus);
  const { posts } = await guarded(() => api("GET", `/api/posts?${qs}`));

  $("#exportCsv").href = `/api/export.csv?${state.clientId ? `client_id=${state.clientId}` : ""}`;

  if (!posts.length) {
    $("#postsBody").innerHTML = `<div class="empty">Nicio postare ${state.allWeeks ? "" : "in saptamana asta"}.
      Apasa „+ Postare noua” ca sa adaugi una.</div>`;
    return;
  }
  $("#postsBody").innerHTML = posts.map(renderPostRow).join("");
  $$(".post", $("#postsBody")).forEach((el) => el.addEventListener("click", () => {
    openPostDialog(posts.find((p) => String(p.id) === el.dataset.id));
  }));
}

function renderPostRow(post) {
  const when = post.status === "posted" ? post.posted_at : (post.planned_for || post.posted_at);
  const late = post.status !== "posted" && post.week < state.boot.week;
  const thumb = post.thumb_url || (post.media_path ? `/${post.media_path}` : "");
  return `
    <div class="post" data-id="${post.id}">
      ${thumb ? `<img class="thumb" src="${esc(thumb)}" loading="lazy" alt="">`
              : `<div class="thumb ph">${post.content_type === "video" ? "🎬" : "🖼️"}</div>`}
      <div class="main">
        <div class="title">${esc(post.title || post.caption.slice(0, 60) || "(fara titlu)")}</div>
        <div class="meta">
          <span>${esc(post.client_name)}</span>
          <span>${esc(post.platform)} · ${esc(post.handle)}</span>
          <span>${esc(post.content_label)}</span>
          ${post.author ? `<span>${esc(post.author)}</span>` : ""}
          ${when ? `<span class="${late ? "late" : ""}">${late ? "restant · " : ""}${esc(when.slice(0, 10))}</span>` : ""}
        </div>
      </div>
      <span class="state ${post.status}">${esc(state.boot.statuses.find((s) => s.value === post.status)?.label || post.status)}</span>
    </div>`;
}

// app.js e incarcat la finalul <body>, DOM-ul e deja gata - fara nevoie de DOMContentLoaded.
$("#newPost").addEventListener("click", () => openPostDialog(null));
$("#postStatusFilter").addEventListener("change", (e) => { state.postStatus = e.target.value; renderPosts(); });
$("#allWeeks").addEventListener("change", (e) => { state.allWeeks = e.target.checked; renderPosts(); });

// --------------------------------------------------------------------- dialog postare

function wirePostDialog() {
  const dialog = $("#postDialog");
  const form = $("#postForm");
  fillSelect(form.content_type, state.boot.post_content_types, { value: "value", text: "label" });
  fillSelect(form.status, state.boot.statuses, { value: "value", text: "label" });

  $("#cancelPost").addEventListener("click", () => dialog.close());
  $("#deletePost").addEventListener("click", async () => {
    if (!form.id.value) return;
    if (!confirm("Stergi aceasta postare?")) return;
    await guarded(() => api("DELETE", `/api/posts/${form.id.value}`));
    dialog.close();
    toast("Postare stearsa.", "ok");
    refreshAll();
  });

  $("#mediaFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    $("#mediaHint").hidden = false;
    $("#mediaHint").textContent = "Se incarca...";
    try {
      const buf = await file.arrayBuffer();
      const res = await api("POST", `/api/upload?filename=${encodeURIComponent(file.name)}`, buf);
      form.media_path.value = res.media_path;
      $("#mediaHint").textContent = `Incarcat: ${res.name}`;
    } catch (err) {
      $("#mediaHint").textContent = `Eroare la incarcare: ${err.message}`;
    }
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    const id = payload.id;
    delete payload.id;
    try {
      if (id) await api("PUT", `/api/posts/${id}`, payload);
      else await api("POST", "/api/posts", payload);
    } catch (err) {
      toast(err.message, "err");
      return;
    }
    dialog.close();
    toast("Salvat.", "ok");
    refreshAll();
  });
}

function openPostDialog(post) {
  const dialog = $("#postDialog");
  const form = $("#postForm");
  form.reset();
  fillSelect(form.account_id,
    state.boot.accounts.map((a) => ({ id: a.id, name: `${a.client_name} · ${a.platform_label} ${a.handle}` })),
    { value: "id", text: "name" });

  $("#postDialogTitle").textContent = post ? "Editeaza postarea" : "Postare noua";
  $("#deletePost").hidden = !post;
  $("#mediaHint").hidden = true;
  form.media_path.value = post?.media_path || "";
  form.id.value = post?.id || "";

  if (post) {
    form.account_id.value = post.account_id;
    form.content_type.value = post.content_type;
    form.status.value = post.status;
    form.author.value = post.author || "";
    form.planned_for.value = (post.planned_for || "").slice(0, 10);
    form.posted_at.value = (post.posted_at || "").slice(0, 10);
    form.title.value = post.title || "";
    form.url.value = post.url || "";
    form.caption.value = post.caption || "";
    if (post.media_path) $("#mediaHint").hidden = false, $("#mediaHint").textContent = `Fisier: ${post.media_path.split("/").pop()}`;
  } else if (state.boot.accounts.length) {
    form.account_id.value = state.boot.accounts[0].id;
  }
  dialog.showModal();
}

// --------------------------------------------------------------------- setari: clienti/conturi/echipa/tinte

function wireSettings() {
  $("#clientForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    await guarded(() => api("POST", "/api/clients", data));
    e.target.reset();
    toast("Client adaugat.", "ok");
    await reloadBoot();
    renderSettings();
  });

  $("#accountForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    await guarded(() => api("POST", "/api/accounts", data));
    e.target.reset();
    toast("Cont adaugat.", "ok");
    await reloadBoot();
    renderSettings();
  });

  $("#memberForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    await guarded(() => api("POST", "/api/members", data));
    e.target.reset();
    toast("Coleg adaugat.", "ok");
    await reloadBoot();
    renderSettings();
  });
}

async function reloadBoot() {
  state.boot = await api("GET", "/api/bootstrap");
  fillSelect($("#clientFilter"), state.boot.clients, { keepFirst: true, value: "id", text: "name" });
}

async function renderSettings() {
  renderClientList();
  renderAccountList();
  renderMemberList();
  await renderTargets();
  renderSyncList();
  refreshImportPickers();
  fillSelect($("#linkClient"), state.boot.clients,
    { value: "id", text: "name", placeholder: "Client existent..." });
  refreshScraperStatus();
}

function renderClientList() {
  $("#clientList").innerHTML = state.boot.clients.map((c) => `
    <div class="item">
      <div class="grow">${esc(c.name)}${c.active ? "" : " <span class=\"sub2\">(inactiv)</span>"}</div>
      <button class="ghost" data-toggle="${c.id}">${c.active ? "Dezactiveaza" : "Activeaza"}</button>
      <button class="ghost" data-delete-client="${c.id}">Sterge</button>
    </div>`).join("") || `<p class="hint">Niciun client inca.</p>`;

  $$("[data-toggle]", $("#clientList")).forEach((btn) => btn.addEventListener("click", async () => {
    const client = state.boot.clients.find((c) => String(c.id) === btn.dataset.toggle);
    await guarded(() => api("PUT", `/api/clients/${client.id}`, { active: !client.active }));
    await reloadBoot(); renderSettings(); refreshAll();
  }));
  $$("[data-delete-client]", $("#clientList")).forEach((btn) => btn.addEventListener("click", async () => {
    if (!confirm("Stergi clientul si tot ce tine de el (conturi, postari, tinte)?")) return;
    await guarded(() => api("DELETE", `/api/clients/${btn.dataset.deleteClient}`));
    await reloadBoot(); renderSettings(); refreshAll();
  }));
}

function renderAccountList() {
  fillSelect($("#accountForm").client_id, state.boot.clients, { value: "id", text: "name" });
  fillSelect($("#accountForm").platform, state.boot.platforms, { value: "value", text: "label" });

  $("#accountList").innerHTML = state.boot.accounts.map((a) => `
    <div class="item">
      <div class="grow">${esc(a.client_name)} · <span class="pill ${a.platform}">${esc(a.platform_label)}</span>
        ${esc(a.handle)}</div>
      <button class="ghost" data-delete-account="${a.id}">Sterge</button>
    </div>`).join("") || `<p class="hint">Niciun cont inca.</p>`;

  $$("[data-delete-account]", $("#accountList")).forEach((btn) => btn.addEventListener("click", async () => {
    if (!confirm("Stergi contul si postarile lui?")) return;
    await guarded(() => api("DELETE", `/api/accounts/${btn.dataset.deleteAccount}`));
    await reloadBoot(); renderSettings(); refreshAll();
  }));
}

function renderMemberList() {
  $("#memberList").innerHTML = state.boot.members.map((m) => `
    <span class="who">${esc(m.name)} <button data-delete-member="${m.id}" title="Sterge">×</button></span>
  `).join("") || `<p class="hint">Niciun coleg inca.</p>`;
  $("#memberOptions").innerHTML = state.boot.members.map((m) => `<option value="${esc(m.name)}">`).join("");

  $$("[data-delete-member]", $("#memberList")).forEach((btn) => btn.addEventListener("click", async () => {
    await guarded(() => api("DELETE", `/api/members/${btn.dataset.deleteMember}`));
    await reloadBoot(); renderSettings();
  }));
}

async function renderTargets() {
  if (!state.boot.clients.length) {
    $("#targetsBody").innerHTML = `<p class="hint">Adauga un client ca sa-i setezi planul.</p>`;
    return;
  }
  const { targets } = await api("GET", "/api/targets");
  const key = (t) => `${t.period}:${t.period_key}:${t.content_type}`;
  const byClient = {}, byAccount = {};
  for (const t of targets) {
    const bucket = t.client_id ? (byClient[t.client_id] ??= {}) : (byAccount[t.account_id] ??= {});
    bucket[key(t)] = t;
  }

  const cell = (owner, ownerId, contentType, period) => {
    const store = owner === "client" ? byClient : byAccount;
    const t = (store[ownerId] || {})[`${period}:*:${contentType}`] || {};
    return `
      <td class="target-cell">
        <input type="number" min="0" placeholder="-" value="${t.target_min ?? ""}"
          data-owner="${owner}" data-id="${ownerId}" data-type="${contentType}"
          data-period="${period}" data-bound="min">
        <span class="dash">-</span>
        <input type="number" min="0" placeholder="=" value="${
          t.target_max && t.target_max !== t.target_min ? t.target_max : ""}"
          data-owner="${owner}" data-id="${ownerId}" data-type="${contentType}"
          data-period="${period}" data-bound="max">
      </td>`;
  };

  const table = (owner, ownerId, types) => `
    <table class="targets">
      <thead><tr><th></th><th>Pe saptamana</th><th>Pe luna</th></tr></thead>
      <tbody>${types.map((c) => `
        <tr>
          <td>${esc(c.label)}</td>
          ${cell(owner, ownerId, c.value, "week")}
          ${cell(owner, ownerId, c.value, "month")}
        </tr>`).join("")}</tbody>
    </table>`;

  $("#targetsBody").innerHTML = state.boot.clients.map((client) => {
    const accounts = state.boot.accounts.filter((a) => a.client_id === client.id);
    return `
    <div style="margin-bottom:20px">
      <div style="font-weight:600;margin-bottom:6px">${esc(client.name)}</div>
      ${table("client", client.id, state.boot.content_types)}
      ${accounts.length ? `
        <details style="margin-top:8px">
          <summary class="hint" style="cursor:pointer">
            Tinte separate pe o singura platforma (optional)
          </summary>
          ${accounts.map((a) => `
            <div style="margin-top:10px">
              <div class="sub2"><span class="pill ${a.platform}">${esc(a.platform_label)}</span>
                ${esc(a.handle)}</div>
              ${table("account", a.id, state.boot.post_content_types)}
            </div>`).join("")}
        </details>` : ""}
    </div>`;
  }).join("");

  $$("#targetsBody input").forEach((input) => input.addEventListener("change", async () => {
    const row = $$(`#targetsBody input[data-owner="${input.dataset.owner}"]` +
      `[data-id="${input.dataset.id}"][data-type="${input.dataset.type}"]` +
      `[data-period="${input.dataset.period}"]`);
    const min = Number(row.find((i) => i.dataset.bound === "min")?.value || 0);
    const max = Number(row.find((i) => i.dataset.bound === "max")?.value || 0);
    const payload = {
      period: input.dataset.period, content_type: input.dataset.type,
      target_min: min, target_max: max || min,
    };
    payload[input.dataset.owner === "client" ? "client_id" : "account_id"] =
      Number(input.dataset.id);
    await guarded(() => api("POST", "/api/targets", payload));
    toast("Plan actualizat.", "ok");
  }));
}

function renderSyncList() {
  $("#syncList").innerHTML = state.boot.accounts.map((a) => `
    <div class="item">
      <div class="grow">${esc(a.client_name)} · <span class="pill ${a.platform}">${esc(a.platform_label)}</span>
        ${esc(a.handle)}</div>
      <button class="ghost" data-sync="${a.id}">Sincronizeaza</button>
    </div>`).join("") || `<p class="hint">Niciun cont inca - adauga unul din link, mai sus.</p>`;

  $$("[data-sync]", $("#syncList")).forEach((btn) => btn.addEventListener("click", async () => {
    btn.disabled = true; btn.textContent = "...";
    try {
      const r = await api("POST", `/api/sync/${btn.dataset.sync}`);
      toast(r.ok ? `${r.account}: ${r.created} noi, ${r.updated} actualizate, ${r.linked_planned} legate de plan.`
                 : `${r.account}: ${r.error}`, r.ok ? "ok" : "err");
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false; btn.textContent = "Sincronizeaza";
    }
  }));
}

// --------------------------------------------------------------------- import: format propriu

$("#csvFile")?.addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const text = await file.text();
  try {
    const report = await api("POST", "/api/import", text);
    toast(`Import: ${report.imported} adaugate, ${report.skipped} ignorate.` +
      (report.errors.length ? ` Prima eroare: ${report.errors[0]}` : ""), "ok");
    await reloadBoot();
    refreshAll();
  } catch (err) {
    toast(err.message, "err");
  }
  e.target.value = "";
});

// --------------------------------------------------------------------- import: export de platforma (mapare)

async function refreshScraperStatus() {
  try {
    const status = await api("GET", "/api/scraper/status");
    $("#scraperStatus").textContent = status.available
      ? (status.logged_in
          ? "Sincronizare automata: gata de folosit."
          : "Ruleaza `python3 run.py --login` o data, ca sa te loghezi in conturi.")
      : status.hint.replace(/\n/g, " ");
  } catch {
    $("#scraperStatus").textContent = "";
  }
}

function wireAddFromLink() {
  $("#addFromLinks").addEventListener("click", async () => {
    const links = $("#linkUrls").value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!links.length) { toast("Lipeste cel putin un link.", "err"); return; }
    const clientId = $("#linkClient").value;
    const clientName = $("#linkClientNew").value.trim();
    if (!clientId && !clientName) { toast("Alege un client sau scrie un nume nou.", "err"); return; }

    const btn = $("#addFromLinks");
    btn.disabled = true; btn.textContent = "Se adauga...";
    let added = 0, existed = 0;
    const problems = [];
    for (const url of links) {
      try {
        const res = await api("POST", "/api/accounts/from-link",
          clientId ? { url, client_id: Number(clientId) } : { url, client_name: clientName });
        res.created ? added++ : existed++;
      } catch (err) {
        problems.push(`${url.slice(0, 40)}: ${err.message}`);
      }
    }
    btn.disabled = false; btn.textContent = "Adauga conturile";
    $("#linkUrls").value = "";
    $("#linkClientNew").value = "";
    toast(`${added} conturi adaugate` + (existed ? `, ${existed} existau deja` : "") +
      (problems.length ? `. Probleme: ${problems[0]}` : "."), problems.length ? "err" : "ok");
    await reloadBoot();
    renderSettings();
    refreshAll();
  });
}

function wireImport() {
  refreshImportPickers();

  $("#importClient").addEventListener("change", () => {
    refreshImportAccounts();
    updateImportFileState();
  });
  $("#importAccount").addEventListener("change", updateImportFileState);

  $("#importFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const accountId = $("#importAccount").value;
    const account = state.boot.accounts.find((a) => String(a.id) === accountId);
    if (!account) { toast("Alege mai intai contul.", "err"); e.target.value = ""; return; }
    state.importCsvText = await file.text();
    state.importAccount = account;
    try {
      const preview = await api("POST", `/api/import/preview?platform=${account.platform}`, state.importCsvText);
      if (preview.error) { toast(preview.error, "err"); return; }
      openImportDialog(preview, account);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      e.target.value = "";
    }
  });

  $("#cancelImport").addEventListener("click", () => $("#importDialog").close());
  $("#closeImportReport").addEventListener("click", async () => {
    $("#importDialog").close();
    await reloadBoot();
    refreshAll();
  });
  $("#commitImport").addEventListener("click", commitImport);
}

function refreshImportPickers() {
  // Refacem si selectul de client (poate a aparut unul nou de la ultimul render),
  // pastrand alegerea curenta daca inca e valida.
  const keepClient = $("#importClient").value;
  fillSelect($("#importClient"), state.boot.clients,
    { value: "id", text: "name", placeholder: "Alege clientul..." });
  if (keepClient && state.boot.clients.some((c) => String(c.id) === keepClient)) {
    $("#importClient").value = keepClient;
  }
  refreshImportAccounts();
  updateImportFileState();
}

function refreshImportAccounts() {
  const clientId = $("#importClient").value;
  const keepAccount = $("#importAccount").value;
  const accounts = state.boot.accounts.filter((a) => !clientId || String(a.client_id) === clientId);
  fillSelect($("#importAccount"), accounts.map((a) => ({ id: a.id, name: `${a.platform_label} ${a.handle}` })),
    { value: "id", text: "name", placeholder: "Alege contul..." });
  if (keepAccount && accounts.some((a) => String(a.id) === keepAccount)) {
    $("#importAccount").value = keepAccount;
  }
}

function updateImportFileState() {
  const ready = $("#importClient").value && $("#importAccount").value;
  $("#importFile").disabled = !ready;
  $("#importFileHint").textContent = ready
    ? "Alege fisierul CSV exportat din platforma."
    : "Alege mai intai clientul si contul.";
}

function openImportDialog(preview, account) {
  $("#importMapStep").hidden = false;
  $("#importReportStep").hidden = true;
  $("#importSummary").textContent =
    `${account.client_name} · ${account.platform_label} ${account.handle} — ` +
    `${preview.row_count} randuri gasite` +
    (preview.profile_name ? ", mapare refolosita din import anterior." : ", mapare ghicita automat.");

  $("#mapTable").innerHTML = preview.fields.map((f) => `
    <div class="field">${esc(f.label)}${f.required ? ' <span class="req">*</span>' : ""}</div>
    <select data-field="${f.key}">
      <option value="">— nu exista —</option>
      ${preview.headers.map((h) => `<option value="${esc(h)}" ${preview.mapping[f.key] === h ? "selected" : ""}>${esc(h)}</option>`).join("")}
    </select>
  `).join("");

  const table = $("#importPreviewTable");
  table.innerHTML = `<thead><tr>${preview.headers.map((h) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${preview.sample.map((row) => `<tr>${preview.headers.map((h) => `<td>${esc(row[h] ?? "")}</td>`).join("")}</tr>`).join("")}</tbody>`;

  $("#importDialog").showModal();
}

async function commitImport() {
  const mapping = {};
  $$("[data-field]", $("#mapTable")).forEach((sel) => { mapping[sel.dataset.field] = sel.value || null; });

  const btn = $("#commitImport");
  btn.disabled = true; btn.textContent = "Se importa...";
  try {
    const report = await api("POST", "/api/import/commit", {
      account_id: state.importAccount.id,
      csv: state.importCsvText,
      mapping,
      save_profile: $("#importSaveProfile").checked,
    });
    showImportReport(report);
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false; btn.textContent = "Importa";
  }
}

function showImportReport(report) {
  $("#importMapStep").hidden = true;
  $("#importReportStep").hidden = false;
  $("#importReportBody").innerHTML = `
    <div class="report-grid">
      <div class="stat good"><div class="k">Postari noi</div><div class="v">${report.created}</div></div>
      <div class="stat"><div class="k">Actualizate</div><div class="v">${report.updated}</div></div>
      <div class="stat warn"><div class="k">Legate de plan</div><div class="v">${report.linked_planned}</div></div>
      <div class="stat ${report.skipped ? "bad" : ""}"><div class="k">Ignorate</div><div class="v">${report.skipped}</div></div>
    </div>
    ${report.errors.length ? `<ul class="error-list">${report.errors.map((e) => `<li>${esc(e)}</li>`).join("")}</ul>` : ""}
  `;
}

init().catch((err) => toast(`Nu am putut porni: ${err.message}`, "err"));
