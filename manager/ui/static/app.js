"use strict";

const app = document.getElementById("app");

function inviteToast(message) {
  const existing = document.querySelector(".invite-toast");
  if (existing) existing.remove();
  const el = document.createElement("div");
  el.className = "invite-toast";
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

let DEVICE_ID = null;

function getDeviceId() {
  if (DEVICE_ID == null) {
    try { DEVICE_ID = localStorage.getItem("tm_device_id"); } catch (e) { DEVICE_ID = ""; }
    if (!DEVICE_ID) {
      DEVICE_ID = "d-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 10);
      try { localStorage.setItem("tm_device_id", DEVICE_ID); } catch (e) {}
    }
  }
  return DEVICE_ID;
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", "X-Device-Id": getDeviceId() },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.error || `request failed (${res.status})`);
  }
  return data;
}

const query = (name, params = {}) => {
  const qs = new URLSearchParams(params).toString();
  return api(`/api/query?name=${name}&${qs}`);
};
const action = (command, body = {}) =>
  api("/api/action?command=" + command, { method: "POST", body: JSON.stringify(body) });

function fmtMoney(value) {
  if (value == null) return "n/a";
  if (value >= 1000000) return (value / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
  if (value >= 1000) return Math.round(value / 1000) + "k";
  return String(value);
}

/* -------------------------------------------------------------- crests */

let CREST_BY_NAME = null;

async function ensureCrests() {
  if (CREST_BY_NAME) return;
  CREST_BY_NAME = {};
  try {
    const res = await query("clubs");
    res.clubs.forEach((c) => {
      CREST_BY_NAME[c.id] = c.logo;
      CREST_BY_NAME[c.name] = c.logo;
    });
  } catch {
    CREST_BY_NAME = {};
  }
}

function crest(nameOrId) {
  const src = (CREST_BY_NAME && CREST_BY_NAME[nameOrId]) || "";
  return src
    ? `<img class="crest" src="${esc(src)}" alt="" width="16" height="16" loading="lazy" onerror="this.remove()">`
    : "";
}

function playerPhoto(player) {
  const full = player.first_name && player.last_name
    ? `${player.first_name} ${player.last_name}`
    : (player.name || player.full_name || "");
  const parts = full.split(/\s+/).filter(Boolean);
  const initials = ((parts[0] || "")[0] + (parts[1] || "")[0]).toUpperCase() || "?";
  return `
    <img class="p-photo" src="/photos/${esc(player.id)}.png" alt=""
      data-init="${esc(initials)}" loading="lazy" onerror="photoFallback(this)">`;
}

function photoFallback(img) {
  const el = document.createElement("span");
  el.className = "p-photo p-photo-fallback";
  el.textContent = img.dataset.init || "?";
  el.style.setProperty("--c1", "#1f2937");
  el.style.setProperty("--c2", "#0f172a");
  img.replaceWith(el);
}

function moneyLabel(label, value) {
  return `<div class="stat"><div class="label">${esc(label)}</div><div class="value">${fmtMoney(value)}</div></div>`;
}

function banner(text, kind = "error") {
  return text
    ? `<div class="${kind === "ok" ? "ok-banner" : "error-banner"}">${esc(text)}</div>`
    : "";
}

function boardBars(board) {
  return ["overall", "results", "finances", "transfers"]
    .map((key) => `
      <div class="stat">
        <div class="label">${key}</div>
        <div class="bar-cell"><div class="progress"><span style="width:${board[key]}%"></span></div></div>
      </div>`)
    .join("");
}

/* ---------------------------------------------------------------- setup */

function renderSplash() {
  app.innerHTML = `
    <div class="splash">
      <div class="splash-card">
        <div class="brand splash-brand">Touchline <em>Manager</em></div>
        <p class="splash-sub">Initialising fictional world&hellip;</p>
      </div>
    </div>`;
}

async function renderSetup() {
  const manifest = (await query("clubs").catch(() => ({ clubs: [] }))).clubs || [];
  app.innerHTML = `
    <div class="splash">
      <input type="hidden" id="crestSource" value="${esc(JSON.stringify(manifest.reduce((m, c) => {
        m[c.id] = c.logo; m[c.name] = c.logo; return m;
      }, {})))}">
      <div class="splash-card" style="max-width:1180px; width:100%; text-align:left; padding:18px;">
        <div class="brand" style="font-size:28px; margin-bottom:20px;">Touchline <em>Manager</em></div>
        <div class="setup-grid">
          <div>
            <div class="card">
              <h2>New career</h2>
              <label class="field"><span>Manager first name</span><input id="first" type="text" value="Avery"></label>
              <label class="field"><span>Manager last name</span><input id="last" type="text" value="Cole"></label>
              <label class="field"><span>Nationality</span><select id="nation"></select></label>
              <label class="field"><span>Favourite coach</span><select id="coach"></select></label>
              <div id="coachTip" class="muted"></div>
              <label class="field"><span>Difficulty</span><select id="difficulty"></select></label>
              <div id="objectives"></div>
              <button id="createBtn" class="btn" disabled>Create career</button>
            </div>
            <div class="card">
              <h2>Continue / load</h2>
              <div id="saveList"><p class="muted">No saved careers yet.</p></div>
            </div>
          </div>
          <div>
            <div class="card" style="max-height:76vh; overflow-y:auto;">
              <h2>Choose your club</h2>
              <div id="clubList"><p class="muted">Loading clubs&hellip;</p></div>
            </div>
          </div>
        </div>
      </div>
    </div>`;

  let setup;
  try {
    setup = await query("setup");
    await initCrests();
  } catch (err) {
    app.innerHTML = `<div class="splash"><div class="splash-card"><div class="error-banner">${esc(err.message)}</div></div></div>`;
    return;
  }

  const nationSel = document.getElementById("nation");
  setup.nationalities.forEach((n) => nationSel.add(new Option(n, n)));
  nationSel.value = "Valland";

  const diffSel = document.getElementById("difficulty");
  setup.difficulties.forEach((d) => diffSel.add(new Option(d.toUpperCase(), d)));
  diffSel.value = "manager";

  const coachSel = document.getElementById("coach");
  const coachTip = document.getElementById("coachTip");
  (setup.coaches || []).forEach((c) => coachSel.add(new Option(c.name, c.key)));
  if (coachSel.options.length) coachSel.selectedIndex = 0;
  let favouriteCoach = coachSel.value || "";
  const paintCoachTip = () => {
    if (coachTip) {
      const c = (setup.coaches || []).find((x) => x.key === coachSel.value);
      coachTip.textContent = c ? c.tagline : "";
    }
  };
  coachSel.addEventListener("change", () => {
    favouriteCoach = coachSel.value;
    paintCoachTip();
  });
  paintCoachTip();

  const objBox = document.getElementById("objectives");
  objBox.innerHTML = setup.objectives.map((o, i) => `
    <div class="option-card ${i === 0 ? "selected" : ""}" data-key="${esc(o.key)}">
      <div class="t">${esc(o.label)}</div>
      <div class="d">${esc(o.description)}</div>
    </div>`).join("");
  let objective = setup.objectives[0].key;
  objBox.querySelectorAll(".option-card").forEach((card) => {
    card.addEventListener("click", () => {
      objBox.querySelectorAll(".option-card").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      objective = card.dataset.key;
    });
  });

  const clubList = document.getElementById("clubList");
  let selectedClub = null;
  clubList.innerHTML = setup.clubs.map((c) => `
    <div class="club-pick" data-id="${esc(c.id)}">
      <div class="row1">
        ${crest(c.id)}<span class="name">${esc(c.name)}</span>
        <span class="badge pos">${c.reputation}</span>
      </div>
      <div class="city">${esc(c.city)} &middot; ${esc(c.stadium)} (${c.capacity.toLocaleString()})</div>
      <div class="meta">Best five &Oslash; ${c.avg_best5} &middot; Transfer budget ${fmtMoney(c.transfer_budget)}</div>
    </div>`).join("");
  clubList.querySelectorAll(".club-pick").forEach((card) => {
    card.addEventListener("click", () => {
      clubList.querySelectorAll(".club-pick").forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
      selectedClub = card.dataset.id;
      document.getElementById("createBtn").disabled = false;
    });
  });

  document.getElementById("createBtn").addEventListener("click", async () => {
    const first = document.getElementById("first").value.trim();
    const last = document.getElementById("last").value.trim();
    if (!first || !last || !selectedClub) return;
    const data = await api("/api/careers", {
      method: "POST",
      body: JSON.stringify({
        first_name: first,
        last_name: last,
        nationality: nationSel.value,
        difficulty: diffSel.value,
        objective: objective,
        favourite_coach: favouriteCoach,
        club_id: selectedClub,
        seed: 42,
      }),
    });
    app.innerHTML = "";
    renderShell(data);
  });

  await renderSaves();
  initCrests();
}

async function initCrests() {
  const srcEl = document.getElementById("crestSource");
  if (srcEl) {
    CREST_BY_NAME = JSON.parse(srcEl.value || "{}");
    return;
  }
  await ensureCrests();
}

async function renderSaves() {
  const box = document.getElementById("saveList");
  if (!box) return;
  try {
    const { careers } = await query("careers");
    if (!careers.length) {
      box.innerHTML = `<p class="muted">No saved careers yet.</p>`;
      return;
    }
    box.innerHTML = careers.map((c) => `
      <div class="save-card">
        <div>
          <strong>${esc(c.title)}</strong>
          <div class="muted" style="font-size:12.5px">${esc(c.club)} &middot; ${esc(c.difficulty)} &middot; ${esc(c.season)} wk ${c.week} &middot; saved ${esc(c.saved_at)}</div>
        </div>
        <div style="display:flex; gap:6px">
          <button class="btn" data-load="${esc(c.career_id)}">Continue</button>
          <button class="btn ghost" data-del="${esc(c.career_id)}">Delete</button>
        </div>
      </div>`).join("");
    box.querySelectorAll("[data-load]").forEach((b) => {
      b.addEventListener("click", async () => {
        const data = await api("/api/career/load", {
          method: "POST",
          body: JSON.stringify({ career_id: b.dataset.load }),
        });
        app.innerHTML = "";
        renderShell(data);
      });
    });
    box.querySelectorAll("[data-del]").forEach((b) => {
      b.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm("Delete this save?")) return;
        const response = await api("/api/career/delete", {
          method: "POST",
          body: JSON.stringify({ career_id: b.dataset.del }),
        });
        if (response.role === "new_game") return renderSetup();
        await renderSaves();
      });
    });
  } catch (err) {
    box.innerHTML = `<p class="muted">Could not load saves: ${esc(err.message)}</p>`;
  }
}

/* ---------------------------------------------------------------- shell */

const NAV = [
  { key: "dashboard", label: "Dashboard" },
  { key: "squad", label: "Squad" },
  { key: "tactics", label: "Tactics" },
  { key: "fixtures", label: "Fixtures" },
  { key: "results", label: "Results" },
  { key: "standings", label: "League table" },
  { key: "cup", label: "Continental Cup" },
  { key: "transfers", label: "Transfers" },
  { key: "training", label: "Training" },
  { key: "news", label: "News" },
  { key: "club", label: "Club finances", soon: true },
  { key: "history", label: "Career history", soon: true },
];

let currentNav = "dashboard";
let session = null;

const labels = {
  fixtures: "Fixtures",
  results: "Results",
  standings: "League table",
  cup: "Continental Cup",
  transfers: "Transfers",
  training: "Training",
  news: "News",
  club: "Club finances",
  history: "Career history",
};

async function renderShell(dashboardData, targetView = "dashboard") {
  currentNav = targetView;
  await ensureCrests();
  app.innerHTML = `
    <div class="shell">
      <aside>
        <div class="brand">Touchline <em>Manager</em></div>
        <div class="club-name">${crest(dashboardData.club.name)}${esc(dashboardData.club.name)}<br>${esc(dashboardData.season.id)} &middot; week ${dashboardData.season.week}</div>
        ${NAV.map((n) => `
          <button class="nav-item ${n.soon ? "disabled" : ""} ${n.key === targetView ? "active" : ""}"
            data-nav="${esc(n.key)}" ${n.soon ? "disabled" : ""}>
            ${esc(n.label)}${n.soon ? " <span style='opacity:.6'>soon</span>" : ""}
          </button>`).join("")}
        <div class="nav-spacer"></div>
        <button class="nav-item" id="saveNow">Save career</button>
        <button class="nav-item" id="newCareer">New career</button>
      </aside>
      <main class="app-main">
        <div class="topbar">
          <h1>${crest(dashboardData.club.name)}${esc(dashboardData.club.name)}</h1>
          <span class="pill primary">${esc(dashboardData.season.difficulty)}</span>
          <span class="pill">${esc(dashboardData.season.id)} &middot; week ${dashboardData.season.week}</span>
          <button class="btn ghost" id="inviteFriend">Invite a friend</button>
          <button class="btn" id="globalSave">Save</button>
        </div>
        <input type="hidden">
        <div id="content"></div>
      </main>
    </div>`;

  document.querySelectorAll(".nav-item[data-nav]").forEach((n) => {
    n.addEventListener("click", () => {
      const target = n.dataset.nav;
      if (n.classList.contains("disabled")) return;
      loadView(target);
    });
  });
  const globalSave = document.getElementById("globalSave");
  if (globalSave) globalSave.addEventListener("click", doSave);
  const inviteBtn = document.getElementById("inviteFriend");
  if (inviteBtn) {
    inviteBtn.addEventListener("click", async () => {
      const url = location.href.split("#")[0].split("?")[0];
      const text = "Try Touchline Manager — run your own football club! " + url;
      if (navigator.share) {
        try { await navigator.share({ title: "Touchline Manager", text, url }); return; } catch (err) { return; }
      }
      try {
        await navigator.clipboard.writeText(text);
        inviteToast("Link copied — send it to your friend!");
      } catch (err) {
        window.prompt("Copy this link to invite a friend:", url);
      }
    });
  }
  document.getElementById("saveNow").addEventListener("click", doSave);
  document.getElementById("newCareer").addEventListener("click", async () => {
    await api("/api/session", { method: "POST", body: JSON.stringify({ action: "reset" }) });
    document.location.reload();
  });

  await loadView(targetView);
}

async function loadView(name) {
  currentNav = name;
  document.querySelectorAll(".nav-item[data-nav]").forEach((n) => {
    n.classList.toggle("active", n.dataset.nav === name);
  });
  const content = document.getElementById("content");
  try {
    if (name === "dashboard") {
      renderDashboard(await query("dashboard"));
    } else if (name === "squad") {
      renderSquad(await query("squad"));
    } else if (name === "tactics") {
      renderTactics(await query("tactics"));
    } else if (name === "fixtures") {
      renderFixtures(await query("fixtures"));
    } else if (name === "results") {
      renderResults(await query("results"));
    } else if (name === "standings") {
      renderStandings(await query("standings"));
    } else if (name === "cup") {
      renderCup(await query("cup"));
    } else if (name === "transfers") {
      renderTransfers(await query("market"));
    } else if (name === "training") {
      renderTraining(await query("training"));
    } else if (name === "news") {
      renderNews(await query("news"));
    } else {
      content.innerHTML = `
        <div class="card">
          <h2>${esc(labels[name] || name)}</h2>
          <p class="muted">This area arrives in a later phase. Fixtures, results, the league table, squad, tactics and career setup are playable now.</p>
        </div>`;
    }
  } catch (err) {
    content.innerHTML = banner(err.message);
  }
}

/* ------------------------------------------------------------- dashboard */

function renderDashboard(data) {
  const content = document.getElementById("content");
  content.innerHTML = `
    ${banner(sessionNote(data))}
    ${nextMatchCard(data)}
    ${simulateCard(data)}
    <div class="grid cols-2">
      <div class="card">
        <h2>Board confidence</h2>
        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(120px,1fr))">${boardBars(data.board)}</div>
      </div>
      <div class="card">
        <h2>Finances</h2>
        <div class="grid cols-4">
          ${moneyLabel("Balance", data.finances.balance)}
          <div class="stat"><div class="label">Transfer budget</div><div class="value">${fmtMoney(data.finances.transfer_budget)}</div></div>
          <div class="stat"><div class="label">Wage budget /wk</div><div class="value">${fmtMoney(data.finances.weekly_wage_budget)}</div></div>
          <div class="stat"><div class="label">Wages spent /wk</div><div class="value">${fmtMoney(data.finances.weekly_wage_spend)}</div></div>
        </div>
      </div>
    </div>
    <div class="card">
      <h2>Objectives ${data.objectives.length ? `&middot; ${data.objectives[0].season}` : ""}</h2>
      ${data.objectives.map((o) => `
        <div style="display:flex; justify-content:space-between; padding:7px 0; border-bottom:1px solid var(--line)">
          <span>${esc(o.label)}</span>
          <span><span class="pill ${o.achieved ? "good" : ""}">${o.achieved ? "achieved" : "in progress"}</span></span>
        </div>`).join("") || `<p class="muted">None.</p>`}
    </div>
    ${newsCard(data.news)}
    <div class="card">
      <h2>Club</h2>
      <p style="margin:0 0 6px"><strong>${esc(data.club.name)}</strong> &middot; ${esc(data.club.city)}, ${esc(data.club.stadium)} (${data.club.capacity.toLocaleString()})</p>
      <p class="muted" style="margin:0">Manager <strong>${esc(data.manager.name)}</strong> (${esc(data.manager.nationality)}) &middot; likes <strong>${esc(data.manager.favourite_coach_name || "n/a")}</strong> &middot; reputation ${data.manager.reputation}</p>
    </div>`;

  const playBtn = document.getElementById("playMatchBtn");
  if (playBtn) playBtn.addEventListener("click", () => runMatchCommand("play_week"));
  const hlBtn = document.getElementById("matchHighlightsBtn");
  if (hlBtn) hlBtn.addEventListener("click", async () => {
    try {
      await playMatchHighlights();
    } catch (err) {
      document.getElementById("content").innerHTML = banner(err.message);
    }
  });
  const openNewsBtn = document.getElementById("openNewsBtn");
  if (openNewsBtn) openNewsBtn.addEventListener("click", () => loadView("news"));
  const skipBtn = document.getElementById("skipWeekBtn");
  if (skipBtn) skipBtn.addEventListener("click", () => {
    const input = document.getElementById("skipWeekInput");
    const target = parseInt(input.value, 10);
    if (Number.isFinite(target) && target >= 1) runMatchCommand("play_to", { week: target });
  });
  const nextSeasonBtn = document.getElementById("nextSeasonBtn");
  if (nextSeasonBtn) nextSeasonBtn.addEventListener("click", async () => {
    if (!confirm("Start the new season? Lineups, squads and the calendar will be set up for the year ahead.")) return;
    try {
      const data = await action("start_next_season", {});
      session = await query("session");
      renderShell(data, "dashboard");
    } catch (err) {
      document.getElementById("content").innerHTML = banner(err.message);
    }
  });
  const simBtn = document.getElementById("simSeasonBtn");
  if (simBtn) simBtn.addEventListener("click", async () => {
    if (!confirm("Simulate every remaining week of the season at once?")) return;
    runMatchCommand("play_season");
  });
}

function sessionNote(data) {
  if (data.next_match) {
    return `Next up: <strong>${esc(data.next_match.opponent)}</strong> (${esc(data.next_match.venue)}) in week ${data.next_match.week}.`;
  }
  return "The season is complete.";
}

function nextMatchCard(data) {
  if (!data.next_match) {
    return `
      <div class="card match-card">
        <h2>Season complete</h2>
        <p class="muted">All league fixtures have been played.</p>
        ${data.season.final_position ? `<p style="margin:10px 0 4px"><strong>Final position: ${data.season.final_position}${ordinal(data.season.final_position)}</strong> &middot; ${esc(data.season.id)}</p>` : ""}
        ${data.objectives.map((o) => `
          <div style="display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--line)">
            <span>${esc(o.label)}</span>
            <span><span class="pill ${o.achieved ? "good" : "bad"}">${o.achieved ? "achieved" : "not met"}</span></span>
          </div>`).join("") || ""}
      </div>`;
  }
  const m = data.next_match;
  const at = m.venue === "Home" ? `at ${esc(m.stadium)}` : "away from home";
  return `
    <div class="card match-card">
      <div class="big-line">
        <span class="muted">${m.date_label ? `${esc(m.date_label)} &middot; ` : `${"Week " + m.week} &middot; `}${esc(m.competition)} &middot; ${esc(m.venue)}</span>
        <span style="display:flex; gap:8px">
          <button class="btn ghost" id="matchHighlightsBtn" title="Simulate the match and show the key moments as a live highlights reel">Match highlights</button>
          <button class="btn" id="playMatchBtn">Play match</button>
        </span>
      </div>
      <div class="big-line">
        <span class="vs"><span>${crest(data.club.name)}${esc(data.club.name)}</span><span class="vs-sep">vs</span><span>${crest(m.opponent)}${esc(m.opponent)}</span></span>
      </div>
      <p class="muted" style="margin:2px 0 0">${at}</p>
    </div>`;
}

function simulateCard(data) {
  if (data.season.finished) {
    const pos = data.season.final_position ?? "?";
    return `
      <div class="card result-w" style="display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap">
        <div>
          <h2>Season complete</h2>
          <p class="muted" style="margin:0">You finished <strong>${ordinal(pos)}</strong> in the ${esc(data.club.name)}'s division.</p>
        </div>
        <button class="btn" id="nextSeasonBtn">Start next season &rarr;</button>
      </div>`;
  }
  if (!data.next_match) return "";
  const week = data.season.week + 1;
  const weeksLeft = 34 - data.season.week;
  return `
    <div class="card" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
      <span class="muted" style="font-size:13px">Skip ahead:</span>
      <input type="number" id="skipWeekInput" min="${week}" max="34" value="${week}" style="width:86px" />
      <button class="btn ghost" id="skipWeekBtn">To week</button>
      <span class="muted" style="font-size:13px">or</span>
      <button class="btn ghost" id="simSeasonBtn">Simulate rest of season (${weeksLeft} weeks)</button>
    </div>`;
}

function newsCard(headlines) {
  if (!headlines.length) return "";
  return `
    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center">
        <h2>Latest news</h2>
        <button class="btn ghost" id="openNewsBtn">Open newsroom</button>
      </div>
      ${headlines.slice().reverse().map((h) => `<div class="news-row">${esc(h)}</div>`).join("")}
    </div>`;
}

async function runMatchCommand(cmd, payload = {}) {
  const content = document.getElementById("content");
  try {
    const report = await action(cmd, payload);
    session = await query("session");
    updateWeekPill(report.week);
    renderMatchday(report);
  } catch (err) {
    content.innerHTML = banner(err.message);
  }
}

/* ------------------------------------------------------ match highlights */

let HL_AUDIO_CTX = null;

function hlEnsureAudio() {
  if (!HL_AUDIO_CTX) {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC) HL_AUDIO_CTX = new AC();
  }
  return HL_AUDIO_CTX;
}

// Crowd cheer burst for a goal.
function hlCrowdCheer() {
  const ctx = hlEnsureAudio();
  if (!ctx) return;
  if (ctx.state === "suspended") ctx.resume();
  const now = ctx.currentTime;
  for (let i = 0; i < 220; i++) {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    const f = 380 + Math.random() * 1200;
    osc.type = Math.random() < 0.4 ? "square" : "sawtooth";
    osc.frequency.value = f;
    const t0 = now + Math.random() * 1.6;
    gain.gain.setValueAtTime(0.0001, t0);
    gain.gain.exponentialRampToValueAtTime(0.05 + Math.random() * 0.05, t0 + 0.05);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.12 + Math.random() * 0.3);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + 0.5);
  }
  // low "boom"
  const boom = ctx.createOscillator();
  const bg = ctx.createGain();
  boom.type = "sine";
  boom.frequency.setValueAtTime(90, now);
  boom.frequency.exponentialRampToValueAtTime(45, now + 0.8);
  bg.gain.setValueAtTime(0.4, now);
  bg.gain.exponentialRampToValueAtTime(0.0001, now + 0.9);
  boom.connect(bg).connect(ctx.destination);
  boom.start(now);
  boom.stop(now + 1);
}

// Announcer-style "GOOOOOL!" shout: rising "ooo" vowel with vocal vibrato.
function hlGooooool() {
  const ctx = hlEnsureAudio();
  if (!ctx) return;
  if (ctx.state === "suspended") ctx.resume();
  const now = ctx.currentTime + 0.04;
  const t0 = now;
  const t1 = now + 0.75;

  const osc = ctx.createOscillator();
  const bp = ctx.createBiquadFilter();
  const gain = ctx.createGain();
  osc.type = "sawtooth";
  // rising excited pitch: "ooo" of "goooool"
  osc.frequency.setValueAtTime(135, t0);
  osc.frequency.linearRampToValueAtTime(230, t1);
  // open-o vowel formant
  bp.type = "bandpass";
  bp.Q.value = 1.7;
  bp.frequency.setValueAtTime(580, t0);
  bp.frequency.linearRampToValueAtTime(760, t1);
  // envelope: fast attack, held shout, decay
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(0.42, t0 + 0.07);
  gain.gain.setValueAtTime(0.42, t1 - 0.18);
  gain.gain.exponentialRampToValueAtTime(0.0001, t1 + 0.12);
  // vocal vibrato
  const vib = ctx.createOscillator();
  const vg = ctx.createGain();
  vib.frequency.value = 5.2;
  vg.gain.value = 6;
  vib.connect(vg).connect(osc.frequency);

  osc.connect(bp).connect(gain).connect(ctx.destination);
  osc.start(t0);
  osc.stop(t1 + 0.15);
  vib.start(t0);
  vib.stop(t1 + 0.15);
}

// Referee whistle (brief shrill) for a card.
function hlWhistle(long = false) {
  const ctx = hlEnsureAudio();
  if (!ctx) return;
  if (ctx.state === "suspended") ctx.resume();
  const now = ctx.currentTime;
  const pulses = long ? 2 : 1;
  for (let p = 0; p < pulses; p++) {
    const t0 = now + p * (long ? 0.55 : 0);
    const dur = long ? 0.42 : 0.32;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(2600, t0);
    osc.frequency.linearRampToValueAtTime(3200, t0 + dur * 0.5);
    osc.frequency.linearRampToValueAtTime(2400, t0 + dur);
    gain.gain.setValueAtTime(0.001, t0);
    gain.gain.linearRampToValueAtTime(0.22, t0 + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(gain).connect(ctx.destination);
    osc.start(t0);
    osc.stop(t0 + dur + 0.1);
  }
}

function hlClockIcon(minute) {
  return `<span class="hl-time" style="font-weight:700; color:var(--accent,#0a7); font-variant-numeric:tabular-nums">&nbsp;${minute}'</span>`;
}

function hlEventText(ev) {
  if (ev.type === "goal") {
    return `${hlClockIcon(ev.minute)} <strong>GOAL!</strong> ${esc(ev.player)} &middot; <span class="hl-score"><strong>${esc(ev.score)}</strong></span>`;
  }
  if (ev.type === "red_card") {
    return `${hlClockIcon(ev.minute)} <span class="hl-card red">&#9632;</span> Red card &middot; ${esc(ev.player)}`;
  }
  return `${hlClockIcon(ev.minute)} <span class="hl-card yellow">&#9632;</span> Yellow card &middot; ${esc(ev.player)}`;
}

async function playMatchHighlights() {
  const content = document.getElementById("content");
  content.innerHTML = `<div class="card match-card" style="text-align:center; min-height:260px; display:flex; flex-direction:column; justify-content:center; align-items:center; gap:14px">
    <span class="pill">Match highlights</span>
    <p class="muted" style="margin:0">Simulating the match…</p>
  </div>`;
  const report = await action("play_week", {});
  session = await query("session");
  updateWeekPill(report.week);
  renderMatchHighlights(report);
}

function renderMatchHighlights(report) {
  const content = document.getElementById("content");
  const events = (report.highlights || []).slice();
  content.innerHTML = `
    <div class="card match-card" style="text-align:center; min-height:320px; display:flex; flex-direction:column; justify-content:center; align-items:center; gap:10px">
      <span class="pill">Match highlights</span>
      <div class="big-line" id="hlMatchup"></div>
      <div class="hl-stage" id="hlStage" style="min-height:120px; font-size:17px"></div>
      <div class="hl-scorebox" id="hlScore" style="font-size:34px; font-weight:800; letter-spacing:2px">&#8211; : &#8211;</div>
      <div class="muted" id="hlHint" style="font-size:13px"></div>
    </div>`;
  const stage = content.querySelector("#hlStage");
  const scoreEl = content.querySelector("#hlScore");
  const matchEl = content.querySelector("#hlMatchup");
  const hint = content.querySelector("#hlHint");

  hlEnsureAudio();

  // Build matchup line from the user's fixture result
  const ur = (report.results || []).find(r => r.is_user) || {};
  matchEl.innerHTML = `<span class="vs"><span>${esc(ur.home || "")}</span><span class="vs-sep">vs</span><span>${esc(ur.away || "")}</span></span>`;

  let idx = 0;
  stage.textContent = "";
  scoreEl.textContent = "\u2013 : \u2013";

  function showEvent(ev, done) {
    stage.classList.remove("hl-pop");
    // reset
    stage.innerHTML = hlEventText(ev);
    // cause reflow to retrigger animation
    void stage.offsetWidth;
    stage.classList.add("hl-pop");
    if (ev.type === "goal") {
      scoreEl.textContent = ev.score;   // reveal running score
      hlCrowdCheer();
      hlGooooool();
    } else if (ev.type === "red_card") {
      hlWhistle(true);
    } else {
      hlWhistle();
    }
    setTimeout(done, PER_EVENT);
  }

  // total duration ~10s: time per event scales to fit
  if (events.length === 0) {
    stage.innerHTML = "No notable moments.";
    hint.textContent = "A quiet match \u2013 no goals or cards.";
    setTimeout(() => showFinal(report, scoreEl, stage, hint), 700);
    return;
  }

  const DURATION = 10000;
  const PER_EVENT = Math.max(650, Math.min(1600, DURATION / events.length));
  const step = () => {
    if (idx >= events.length) {
      showFinal(report, scoreEl, stage, hint);
      return;
    }
    showEvent(events[idx], () => {
      idx++;
      step();
    });
  };
  step();
}

function showFinal(report, scoreEl, stage, hint) {
  scoreEl.textContent = report.scoreline || "\u2013 : \u2013";
  stage.innerHTML = `<span style="font-size:18px; font-weight:700">Full time &middot; ${esc(report.summary || "")}</span>`;
  hlWhistle();
  hint.innerHTML = `<button class="btn" id="hlDoneBtn">Continue</button>`;
  const btn = document.getElementById("hlDoneBtn");
  if (btn) btn.addEventListener("click", () => loadView("dashboard"));
}

function ordinal(n) {
  if (n % 100 >= 11 && n % 100 <= 13) return "th";
  return { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th";
}

function updateWeekPill(week) {
  document.querySelectorAll(".pill").forEach((p) => {
    if (/week \d+/.test(p.textContent)) p.textContent = `${session.season} &middot; week ${week}`;
  });
  const clubWeek = document.querySelector(".club-name");
  if (clubWeek) clubWeek.innerHTML = `${esc(session.club)}<br>${esc(session.season)} &middot; week ${week}`;
}

/* ---------------------------------------------------------------- squad */

let draft = null;

async function renderSquad(data) {
  draft = {
    formation: data.formation,
    starters: [...data.starter_ids],
    subs: [...data.substitute_ids],
  };
  const content = document.getElementById("content");
  content.innerHTML = `
    <div class="card">
      <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap">
        <label class="field" style="margin:0"><span>Formation</span>
          <select id="formation">
            ${["4-3-3", "4-4-2", "4-2-3-1", "3-5-2", "5-3-2", "4-3-2-1", "3-4-3", "4-1-4-1"].map((f) => `<option ${f === data.formation ? "selected" : ""}>${f}</option>`).join("")}
          </select>
        </label>
        <button class="btn ghost" id="autoBtn">Auto-select best XI</button>
        <button class="btn" id="saveSelBtn">Save selection</button>
        <span class="pill">${data.counts.injured} injured &middot; ${data.counts.suspended} suspended</span>
      </div>
    </div>
    <div id="selMessage"></div>
    <div class="card">
      <table>
        <thead><tr><th>Status</th><th>Player</th><th>Pos</th><th>Rating</th><th>Pot</th><th>Age</th><th>Wage/wk</th><th>Contract</th><th>Form</th><th>Morale</th><th></th></tr></thead>
        <tbody id="squadRows"></tbody>
      </table>
    </div>`;

  document.getElementById("formation").addEventListener("change", (e) => {
    draft.formation = e.target.value;
  });
  document.getElementById("autoBtn").addEventListener("click", async () => {
    try {
      const fresh = await action("autoselect");
      renderSquad(fresh);
    } catch (err) {
      document.getElementById("selMessage").innerHTML = banner(err.message);
    }
  });
  document.getElementById("saveSelBtn").addEventListener("click", async () => {
    if (draft.starters.length !== 11) {
      document.getElementById("selMessage").innerHTML = banner(`Starting XI has ${draft.starters.length} players - needs exactly 11.`);
      return;
    }
    if (draft.subs.length > 5) {
      document.getElementById("selMessage").innerHTML = banner("At most 5 substitutes.");
      return;
    }
    try {
      const fresh = await action("set_selection", {
        formation: draft.formation,
        starter_ids: draft.starters,
        substitute_ids: draft.subs,
      });
      renderSquad(fresh);
      document.getElementById("selMessage").innerHTML = banner("Selection saved.", "ok");
    } catch (err) {
      document.getElementById("selMessage").innerHTML = banner(err.message);
    }
  });

  const rows = document.getElementById("squadRows");
  rows.innerHTML = data.players.map((p) => {
    const status = p.in_xi ? "XI" : p.on_bench ? "Bench" : "Out";
    const rowClass = p.in_xi ? "in-xi" : p.on_bench ? "on-bench" : "";
    const inj = p.injury ? `<span class="badge bad">inj ${p.injury.weeks}w</span>` : "";
    const susp = p.suspension ? `<span class="badge warn">susp ${p.suspension}</span>` : "";
    return `
      <tr class="clickable ${rowClass} ${p.injury ? "injured" : ""}" data-id="${esc(p.id)}">
        <td><span class="badge pos">${status}</span></td>
        <td><div class="name-cell">${playerPhoto(p)}<div><strong>${esc(p.full_name)}</strong> <span class="muted">${esc(p.nationality)}</span>
          ${p.loan_from ? ` <span class="badge warn">loan · ${esc(p.loan_from)}</span>` : ""}</div></div></td>
        <td>${esc(p.preferred_position)}</td>
        <td><strong>${p.overall}</strong></td>
        <td class="muted">${p.potential}</td>
        <td>${p.age}</td>
        <td>${p.wage ? fmtMoney(p.wage) : "n/a"}</td>
        <td class="muted">${esc(p.contract_end)}</td>
        <td>${p.form}</td>
        <td>${p.morale}</td>
        <td>${inj}${susp}${p.loanable ? `<button class="btn ghost" data-loan-out="${esc(p.id)}">Loan out</button>` : ""}</td>
      </tr>`;
  }).join("");

  rows.querySelectorAll("tr").forEach((tr) => {
    tr.addEventListener("click", () => cyclePlayerStatus(tr.dataset.id));
  });
  rows.querySelectorAll("[data-loan-out]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      const pid = btn.dataset.loanOut;
      try {
        const fresh = await action("loan_out", { player_id: pid });
        renderSquad(fresh);
        document.getElementById("selMessage").innerHTML = banner(fresh.message, "ok");
      } catch (err) {
        document.getElementById("selMessage").innerHTML = banner(err.message);
      }
    });
  });
}

function cyclePlayerStatus(id) {
  if (draft.starters.includes(id)) {
    draft.starters = draft.starters.filter((x) => x !== id);
    draft.subs.push(id);
  } else if (draft.subs.includes(id)) {
    draft.subs = draft.subs.filter((x) => x !== id);
  } else {
    if (draft.starters.length < 11) draft.starters.push(id);
    else if (draft.subs.length < 5) draft.subs.push(id);
  }
  for (const tr of document.querySelectorAll("#squadRows tr")) {
    if (tr.dataset.id !== id) continue;
    const isXI = draft.starters.includes(id);
    const isBench = draft.subs.includes(id);
    tr.className = `clickable ${isXI ? "in-xi" : isBench ? "on-bench" : ""}`;
    tr.querySelector(".badge.pos").textContent = isXI ? "XI" : isBench ? "Bench" : "Out";
  }
}

/* --------------------------------------------------------------- tactics */

async function renderTactics(data) {
  const content = document.getElementById("content");
  const t = data.tactics;
  const gp = data.game_plan;
  const field = (key, label) => `
    <label class="field"><span>${esc(label)}</span>
      <select data-k="${esc(key)}">
        ${data.options[key].map((o) => `<option ${t[key] === o ? "selected" : ""}>${esc(o)}</option>`).join("")}
      </select>
    </label>`;
  const mentalities = data.options.mentality;
  const mindLabels = {
    ultra_defensive: "Ultra defensive", defensive: "Defensive", balanced: "Balanced",
    attacking: "Attacking", ultra_attacking: "Ultra attacking",
  };
  const chip = (p, cls, badge) => `
    <div class="gp-chip ${cls}" title="${esc(p.name)} · ${p.overall} · ${esc(p.fitness)}% fitness">
      <div class="gp-chip-top">
        ${badge || ""}
        <span class="gp-pos">${esc(p.position)}</span>
        <span class="gp-ovr">${p.overall}</span>
      </div>
      <div class="gp-name">${esc(shortName(p.name))}</div>
      <div class="gp-fit"><i style="width:${Math.max(4, p.fitness)}%"></i></div>
      ${p.injury ? `<div class="gp-inj">INJ</div>` : ""}
    </div>`;
  const rowOrder = [...gp.rows].reverse().map((r) => r);
  const pitchRows = rowOrder.map((r) => `
    <div class="gp-row" data-line="${esc(r.line)}">
      ${r.players.length ? r.players.map((p) => chip(p, "gp-chip-pos", p.captain ? `<span class="gp-cap">C</span>` : "")).join("") : `<span class="gp-empty">—</span>`}
    </div>`).join("");

  content.innerHTML = `
    <div id="tacticsMessage"></div>
    <div class="card">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px">
        <h2 style="margin:0">Game plan</h2>
        <button class="btn ghost" id="lineupBtn">Adjust lineup <span class="muted">→</span></button>
      </div>
      <label class="field"><span>Formation</span>
        <select id="formationSelect">
          ${data.options.formations.map((f) => `<option ${t.formation === f ? "selected" : ""}>${f}</option>`).join("")}
        </select>
      </label>
      <div class="pitch">
        ${pitchRows}
        <div class="pitch-center"></div>
      </div>
      ${gp.substitutes.length ? `
        <div class="gp-bench">
          <span class="muted" style="font-size:12px; text-transform:uppercase; letter-spacing:1px">Bench (${gp.substitutes.length})</span>
          <div style="display:flex; gap:6px; flex-wrap:wrap; margin-top:6px">
            ${gp.substitutes.map((p) => chip(p, "gp-chip-bench")).join("")}
          </div>
        </div>` : ""}
    </div>
    <div class="card">
      <h2>Team mentality</h2>
      <div class="mentality-row">
        <select id="mentalitySelect" data-k="mentality" style="display:none">
          ${mentalities.map((m) => `<option value="${esc(m)}" ${t.mentality === m ? "selected" : ""}>${esc(m)}</option>`).join("")}
        </select>
        ${mentalities.map((m) => `
          <button class="btn mentality-chip ${t.mentality === m ? "active mind-" + esc(m) : "mind-" + esc(m)}"
                  data-mind="${esc(m)}">${esc(mindLabels[m] || m)}</button>`).join("")}
      </div>
      <p class="muted" style="font-size:12.5px; margin:8px 0 0 2px">
        Mentality changes how your XI plays: attacking sides create and concede more, defensive sides grind results.
      </p>
    </div>
    <div class="card">
      <h2>Playing style</h2>
      <div class="grid cols-2">
        ${field("playing_style", "Style")}
        ${field("pressing", "Pressing")}
        ${field("passing", "Passing style")}
        ${field("tempo", "Tempo")}
        ${field("defensive_line", "Defensive line")}
        ${field("defensive_approach", "Defensive approach")}
        ${field("attacking_approach", "Attacking approach")}
      </div>
      <button class="btn" id="saveTacBtn">Save game plan</button>
    </div>`;

  const mindSelect = document.getElementById("mentalitySelect");
  content.querySelectorAll(".mentality-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      mindSelect.value = btn.dataset.mind;
      content.querySelectorAll(".mentality-chip").forEach((b) => b.classList.toggle("active", b === btn));
    });
  });

  document.getElementById("lineupBtn").addEventListener("click", () => loadView("squad"));
  document.getElementById("saveTacBtn").addEventListener("click", async () => {
    const payload = {};
    document.querySelectorAll("[data-k]").forEach((sel) => {
      payload[sel.dataset.k] = sel.value;
    });
    payload.formation = document.getElementById("formationSelect").value;
    try {
      const fresh = await action("set_tactics", payload);
      renderTactics(fresh);
      document.getElementById("tacticsMessage").innerHTML = banner("Game plan saved.", "ok");
    } catch (err) {
      document.getElementById("tacticsMessage").innerHTML = banner(err.message);
    }
  });
}

function shortName(fullName) {
  const parts = fullName.split(" ");
  return parts.length > 1 ? `${parts[0][0]}. ${parts.slice(1).join(" ")}` : fullName;
}

/* ----------------------------------------------------------- fixtures etc. */

function renderFixtures(data) {
  const content = document.getElementById("content");
  const groups = {};
  data.fixtures.forEach((f) => {
    const m = (f.month || `Weeks ${f.week}`) + (f.cup ? " (cup)" : "");
    (groups[m] = groups[m] || []).push(f);
  });
  const nextWeek = data.fixtures.find((f) => !f.played && f.week >= data.week);
  content.innerHTML = `
    <div class="card">
      <div style="display:flex; gap:10px; align-items:center; flex-wrap:wrap">
        <h2 style="margin:0">${esc(data.club.name)} calendar</h2>
        <span class="pill">week ${data.week}</span>
        ${data.finished ? `<span class="pill good">season complete</span>` : ""}
      </div>
    </div>
    ${Object.entries(groups).map(([month, fixtures]) => `
      <div class="card cal-month">
        <h2>${esc(month.replace(" (cup)", ""))}
          ${month.includes("(cup)") ? '<span class="pill">cup month</span>' : ""}</h2>
        <table>
          <thead><tr><th>Date</th><th>Comp</th><th>Match</th><th>Venue</th><th>Score</th></tr></thead>
          <tbody>
            ${fixtures.map((f) => `
              <tr class="${f.played ? (f.result ? "result-" + f.result.toLowerCase() : "played-row") : (nextWeek && f.id === nextWeek.id ? "row-next" : "row-me")} ${f.played ? "played-row" : ""}">
                <td class="cal-date">
                  ${f.date_label ? `<strong>${esc(f.date_label)}</strong><span class="muted">${esc(f.weekday)}</span>` : `<span class="muted">week ${f.week}</span>`}
                </td>
                <td>${f.cup ? `<span class="pill">${esc(f.competition)}</span> <span class="muted">${esc(f.round || "")}</span>` : `<span class="muted">${esc(f.competition)}</span>`}</td>
                <td><strong>${crest(f.home)}${esc(f.home)}</strong> <span class="muted">vs</span> <strong>${crest(f.away)}${esc(f.away)}</strong></td>
                <td>${f.venue === "Home" ? '<span class="pill good">H</span>' : '<span class="pill bad">A</span>'}</td>
                <td>${f.played ? `<strong>${esc(f.score)}</strong>` : '<span class="muted">scheduled</span>'}</td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>`).join("")}
    ${nextWeek ? `
    <div class="card next-match-card">
      <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px">
        <span><span class="pill good">NEXT</span> ${crest(nextWeek.opponent)}<strong>${esc(nextWeek.opponent)}</strong>
          &middot; ${esc(nextWeek.venue.toLowerCase())}
          ${nextWeek.date_label ? `&middot; ${esc(nextWeek.date_label)}` : `&middot; week ${nextWeek.week}`}
          &middot; ${esc(nextWeek.competition)}</span>
        <button class="btn" data-next-gp>Open game plan</button>
      </div>
    </div>` : ""}`;

  const runBtn = content.querySelector("[data-next-gp]");
  if (runBtn) runBtn.addEventListener("click", () => loadView("tactics"));
}

function renderResults(data) {
  const content = document.getElementById("content");
  content.innerHTML = `
    <div class="card">
      <h2>Recent results</h2>
      ${data.results.length ? `
        <table>
          <thead><tr><th>Week</th><th>Result</th><th>Fixture</th><th>Attendance</th></tr></thead>
          <tbody>
            ${data.results.map((r) => `
              <tr class="result-${r.result.toLowerCase()}">
                <td>${r.week}</td>
                <td><strong>${r.result}</strong></td>
                <td>${esc(r.home)} ${esc(r.score)} ${esc(r.away)}</td>
                <td class="muted">${r.attendance.toLocaleString()}</td>
              </tr>`).join("")}
          </tbody>
        </table>`
      : `<p class="muted">No matches played yet.</p>`}
    </div>`;
}

function renderStandings(data) {
  const content = document.getElementById("content");
  const user = {
    pos: data.user_position,
    club: data.rows.find((r) => r.is_user),
  };
  content.innerHTML = `
    ${banner(`You sit in position ${user.pos ?? "?"} after week ${data.week}.`)}
    <div class="card">
      <h2>${esc(data.competition)} ${data.season}</h2>
      <table class="standings">
        <thead><tr><th>#</th><th>Club</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GF</th><th>GA</th><th>GD</th><th>Pts</th></tr></thead>
        <tbody>
          ${data.rows.map((r) => `
            <tr class="${r.is_user ? "row-me" : ""}">
              <td>${r.position}</td>
              <td>${crest(r.club)}${esc(r.club)}${r.is_user ? ' <span class="badge pos">you</span>' : ""}</td>
              <td>${r.played}</td>
              <td>${r.won}</td>
              <td>${r.drawn}</td>
              <td>${r.lost}</td>
              <td>${r.goals_for}</td>
              <td>${r.goals_against}</td>
              <td>${r.goal_difference}</td>
              <td><strong>${r.points}</strong></td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
}

function renderCup(data) {
  const content = document.getElementById("content");
  const trophyBanner = data.champion
    ? `<div class="card result-w"><h2>&#127942; ${esc(data.trophy)} winner: ${esc(data.champion)}</h2></div>`
    : "";
  content.innerHTML = `
    ${banner(`${data.name} &middot; knockout battle for the ${esc(data.trophy)}.`)}
    ${trophyBanner}
    ${data.rounds.map((round) => `
      <div class="card">
        <h3>${esc(round.label)} <span class="muted">${round.week ? `week ${round.week}` : "scheduled"}</span></h3>
        ${round.ties.map((tie) => `
          <div class="cup-tie ${tie.is_user ? "row-me" : ""}">
            <span class="cup-club ${tie.winner === tie.home ? "cup-win" : ""}">${crest(tie.home)}${esc(tie.home)}</span>
            <span class="cup-score">${esc(tie.score)}${tie.pens ? " (pens)" : ""}</span>
            <span class="cup-club ${tie.winner === tie.away ? "cup-win" : ""}">${crest(tie.away)}${esc(tie.away)}</span>
          </div>`).join("")}
      </div>`).join("")}
  `;
}

function renderMatchday(report) {
  const content = document.getElementById("content");
  content.innerHTML = `
    <div class="card match-card" style="text-align:center">
      <span class="pill">Matchday ${report.week}</span>
      <h2 style="margin:10px 0">${report.user_had_match ? esc(report.scoreline) : "No match this week"}</h2>
      ${report.summary ? `<p class="muted" style="margin:0">${esc(report.summary)}</p>` : ""}
      ${report.finished ? `<p class="muted">The season is complete.</p>` : ""}
      <div style="margin-top:12px">
        <button class="btn" id="afterMatchBtn">${report.finished ? "Back to dashboard" : "Continue"}</button>
      </div>
    </div>
    ${report.top_performers.length ? `
      <div class="card">
        <h2>Your best players</h2>
        <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
          ${report.top_performers.map((p) => `
            <div class="stat"><div class="label">${esc(p.name)}</div><div class="value">${p.rating}</div></div>`).join("")}
        </div>
      </div>` : ""}
    <div class="card">
      <h2>This week's results</h2>
      <table>
        <thead><tr><th>Home</th><th>Score</th><th>Away</th><th>Attendance</th></tr></thead>
        <tbody>
          ${report.results.map((r) => `
            <tr class="${r.is_user ? "row-me" : ""}">
              <td>${crest(r.home)}${esc(r.home)}</td>
              <td><strong>${esc(r.score)}</strong></td>
              <td>${crest(r.away)}${esc(r.away)}</td>
              <td class="muted">${r.attendance.toLocaleString()}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <div class="card">
      <h2>League table</h2>
      ${standingsTable(report.standings)}
    </div>`;

  document.getElementById("afterMatchBtn").addEventListener("click", () => {
    loadView("dashboard");
  });
}

function standingsTable(data) {
  return `
    <table class="standings">
      <thead><tr><th>#</th><th>Club</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>Pts</th></tr></thead>
      <tbody>
        ${data.rows.map((r) => `
          <tr class="${r.is_user ? "row-me" : ""}">
            <td>${r.position}</td>
            <td>${crest(r.club)}${esc(r.club)}</td>
            <td>${r.played}</td>
            <td>${r.won}</td>
            <td>${r.drawn}</td>
            <td>${r.lost}</td>
            <td>${r.goal_difference}</td>
            <td><strong>${r.points}</strong></td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

/* -------------------------------------------------------------- transfers */

function canBidOn(target, win) {
  if (!win) return "";
  if (win.open) return "";
  if (target.kind === "free") {
    return `title="Free agents can be signed at any time"`;
  }
  return "disabled title=\"The transfer window is closed\"";
}

function windowBanner(window = null) {
  if (!window) return "";
  if (window.open) {
    const label = window.name === "winter" ? "Winter transfer window is open"
      : window.name === "summer" ? "Summer transfer window is open"
      : "Transfer window open";
    return `<div class="card good-line" style="margin-bottom:10px">
      <strong>${label}</strong>
      <span class="muted" style="margin-left:8px">You can buy, sell, loan and accept offers while it lasts (weeks ${window.weeks.join("&ndash;")}).</span>
    </div>`;
  }
  return `<div class="card bad-line" style="margin-bottom:10px">
    <strong>Transfer window closed</strong>
    <span class="muted" style="margin-left:8px">Club transfers resume at the winter window (mid-season) or next summer. Free agents can still be signed.</span>
  </div>`;
}

function renderTransfers(data, notice = null, noticeKind = "ok") {
  const content = document.getElementById("content");
  content.innerHTML = `
    <div id="transferMsg">${banner(notice, noticeKind)}</div>
    <div class="card" style="display:flex; align-items:flex-end; gap:10px; flex-wrap:wrap">
      <label class="field" style="flex:1; min-width:200px; margin:0"><span>Search</span>
        <input type="text" id="marketQ" value="" placeholder="Name or club..." style="width:100%"></label>
      <label class="field" style="margin:0"><span>Position</span>
        <select id="marketPos">
          <option value="">All</option>
          <option value="GK">Goalkeepers</option>
          <option value="DF">Defenders</option>
          <option value="MF">Midfielders</option>
          <option value="FW">Forwards</option>
        </select></label>
      <label class="field" style="margin:0"><span>Type</span>
        <select id="marketKind">
          <option value="">All</option>
          <option value="free">Free agent</option>
          <option value="first-team">First team</option>
          <option value="academy">Academy</option>
          <option value="loan">Loan</option>
        </select></label>
      <button class="btn ghost" id="applyFilters">Search</button>
    </div>
    <div id="windowBanner">${windowBanner(data.window)}</div>
    ${data.offers.length ? `
    <div class="card">
      <h2>Bids for your players <span class="badge">${data.offers.length}</span></h2>
      <p class="muted" style="margin:0 0 10px">AI clubs want your players. Accept and the deal completes now; refuse and the bid is rejected.</p>
      <table>
        <thead><tr><th>Player</th><th>Buyer</th><th>Fee</th><th>Wage</th><th>Years</th><th></th></tr></thead>
        <tbody>
          ${data.offers.map((o, i) => `
            <tr>
              <td><strong>${esc(o.player)}</strong> <span class="badge pos">yours</span></td>
              <td>${crest(o.from)}${esc(o.from)}</td>
              <td>${fmtMoney(o.fee)}</td>
              <td class="muted">${fmtMoney(o.weekly_wage)}/wk</td>
              <td>${o.years} yrs</td>
              <td style="white-space:nowrap">
                <button class="btn good" data-accept="${esc(o.id)}" ${data.window.open ? "" : "disabled title=\"The transfer window is closed\""}>Accept</button>
                <button class="btn ghost" data-negotiate="${esc(o.id)}" ${data.window.open ? "" : "disabled title=\"The transfer window is closed\""}>Negotiate</button>
                <button class="btn ghost" data-refuse="${esc(o.id)}" ${data.window.open ? "" : "disabled title=\"The transfer window is closed\""}>Refuse</button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>` : ""}
    <div class="card">
      <h2>Transfer market <span class="badge">${data.total} targets</span></h2>
      <p class="muted" style="margin:0 0 10px">
        Transfer budget <strong>${fmtMoney(data.budget)}</strong> &middot;
        wage room <strong>${fmtMoney(data.wage_room)}</strong>/wk &middot;
        <span style="white-space:nowrap"><span class="pill">${data.kinds.free} free</span>
        <span class="pill">${data.kinds["first-team"]} first team</span>
        <span class="pill">${data.kinds.academy} academy</span>
        <span class="pill">${data.loan_available} loanable</span></span><br>
        <span class="muted" style="font-size:12.5px">Loans in: ${data.loans.incoming}/${data.loans.max} &middot; no transfer fee, salary only, back at season end</span>
      </p>
      <table>
        <thead><tr><th>Player</th><th>Pos</th><th>Age</th><th>Club</th><th>Rtg</th><th>Valuation</th><th>Wage</th><th></th></tr></thead>
        <tbody id="marketRows">
          ${data.targets.length ? data.targets.map((t) => `
            <tr>
              <td><div class="name-cell">${playerPhoto(t)}<div><strong>${esc(t.name)}</strong>
                ${t.loan ? ' <span class="badge">loan</span>'
                  : t.kind === "free" ? ' <span class="badge pos">free</span>'
                  : t.kind === "academy" ? ' <span class="badge">academy</span>'
                  : ' <span class="badge">first team</span>'}</div></div></td>
              <td>${esc(t.position)}</td>
              <td>${t.age}</td>
              <td>${crest(t.club)}${esc(t.club)}</td>
              <td>${t.overall}</td>
              <td>${fmtMoney(t.valuation)}</td>
              <td class="muted">${fmtMoney(t.wage)}</td>
              <td><button class="btn ghost" data-bid="${esc(t.id)}" ${canBidOn(t, data.window)}>${t.loan ? "Loan" : "Offer"}</button></td>
            </tr>`).join("")
          : `<tr><td colspan="8" class="muted">No players match — try a wider search.</td></tr>`}
        </tbody>
      </table>
      ${data.targets.length >= 60 ? `<p class="muted" style="font-size:12px;margin:8px 0 0">Showing the top 60 of ${data.total} — refine your search.</p>` : ""}
    </div>
    ${data.renewals.length ? `
    <div class="card">
      <h2>Contract renewals <span class="badge">${data.renewals.length}</span></h2>
      <table>
        <thead><tr><th>Player</th><th>Pos</th><th>Age</th><th>Overall</th><th>Wage</th><th>Ends</th><th></th></tr></thead>
        <tbody>
          ${data.renewals.map((r) => `
            <tr>
              <td><strong>${esc(r.name)}</strong></td>
              <td>${esc(r.position)}</td>
              <td>${r.age}</td>
              <td>${r.overall}</td>
              <td class="muted">${fmtMoney(r.wage)}</td>
              <td>${esc(r.end_season)}</td>
              <td><button class="btn ghost" data-renew="${esc(r.id)}">Renew</button></td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>` : ""}
    ${data.history.length ? `
    <div class="card">
      <h2>Recent transfer activity</h2>
      ${data.history.map((h) => `
        <div class="news-row">
          <strong>${esc(h.player)}</strong>
          <span class="muted">${crest(h.from)}${esc(h.from)} &rarr; ${crest(h.to)}${esc(h.to)} for ${fmtMoney(h.fee)}</span>
          <span class="pill ${h.status === "completed" ? "good" : "bad"}" style="margin-left:8px">${esc(h.status)}</span>
        </div>`).join("")}
    </div>` : ""}`;

  document.getElementById("applyFilters").addEventListener("click", async () => {
    const fresh = await query("market", {
      q: document.getElementById("marketQ").value,
      position: document.getElementById("marketPos").value,
      kind: document.getElementById("marketKind").value,
    });
    renderTransfers(fresh);
  });
  document.querySelectorAll("[data-bid]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = data.targets.find((t) => t.id === btn.dataset.bid);
      if (!target) return;
      if (target.loan) askLoan(target, data);
      else askBid(target, data);
    });
  });
  document.querySelectorAll("[data-renew]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const row = data.renewals.find((r) => r.id === btn.dataset.renew);
      if (row) askRenew(row);
    });
  });
  document.querySelectorAll("[data-accept]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const offer = data.offers.find((o) => o.id === btn.dataset.accept);
      if (!offer) return;
      const overlay = openModal(`Sell ${offer.player}?`, `
        <p class="muted" style="margin:0 0 8px">
          <strong>${esc(offer.from)}</strong> bid <strong>${fmtMoney(offer.fee)}</strong> for
          ${esc(offer.player)} on a ${offer.years}-year deal at ${fmtMoney(offer.weekly_wage)}/wk.
        </p>
        <p class="muted" style="margin:0;font-size:12.5px">The fee goes straight into your transfer budget.</p>`, "Accept");
      overlay.querySelector("#modalConfirm").addEventListener("click", async () => {
        overlay.remove();
        await runTransfer("accept_offer", { offer_id: offer.id });
      });
    });
  });
  document.querySelectorAll("[data-refuse]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const offer = data.offers.find((o) => o.id === btn.dataset.refuse);
      if (!offer) return;
      await runTransfer("refuse_offer", { offer_id: offer.id });
    });
  });
  document.querySelectorAll("[data-negotiate]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const offer = data.offers.find((o) => o.id === btn.dataset.negotiate);
      if (!offer) return;
      const overlay = openModal(`Negotiate ${offer.player} deal`, `
        <p class="muted" style="margin:0 0 12px">
          <strong>${esc(offer.from)}</strong> currently offer <strong>${fmtMoney(offer.fee)}</strong> for
          ${esc(offer.player)} on a ${offer.years}-year deal at ${fmtMoney(offer.weekly_wage)}/wk.
        </p>
        <label class="field"><span>Your counter fee</span>
          <input type="number" id="counterFee" value="${Math.round((offer.fee * 1.1) / 10000) * 10000}" min="0" step="10000"></label>
        <p class="muted" style="margin:0;font-size:12.5px">Push too high and they walk away. The fee goes straight into your transfer budget.</p>`, "Send counter");
      overlay.querySelector("#modalConfirm").addEventListener("click", async () => {
        const input = overlay.querySelector("#counterFee");
        const fee = parseInt(input.value, 10);
        if (Number.isNaN(fee) || fee < 0) { input.style.outline = "2px solid #f87171"; return; }
        overlay.remove();
        await runTransfer("negotiate_offer", { offer_id: offer.id, fee });
      });
    });
  });
}

function openModal(title, bodyHtml, confirmLabel = "Confirm") {
  const overlay = document.createElement("div");
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(5,10,20,.72);display:flex;align-items:center;justify-content:center;z-index:40";
  overlay.innerHTML = `
    <div class="card" style="width:min(460px,92vw);margin:0">
      <h2 style="text-transform:none;letter-spacing:0;color:var(--ink)">${esc(title)}</h2>
      ${bodyHtml}
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px">
        <button class="btn ghost" id="modalCancel">Cancel</button>
        <button class="btn" id="modalConfirm">${esc(confirmLabel)}</button>
      </div>
    </div>`;
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) overlay.remove();
  });
  overlay.querySelector("#modalCancel").addEventListener("click", () => overlay.remove());
  document.body.appendChild(overlay);
  return overlay;
}

function askLoan(target, market) {
  const overlay = openModal(`Loan ${target.name}`, `
    <div class="name-cell" style="margin-bottom:12px">${playerPhoto(target)}<div><strong>${esc(target.name)}</strong></div></div>
    <p class="muted" style="margin:0 0 12px">
      <strong>Season-long loan</strong> &middot; no transfer fee &middot; ${crest(target.club)}${esc(target.club)} &middot;
      ${esc(target.position)} &middot; rating ${target.overall} &middot; age ${target.age}
    </p>
    <label class="field"><span>Weekly wage (paid by us)</span>
      <input type="number" id="loanWage" value="${target.wage}" min="${Math.max(target.wage,0)}" step="100" disabled></label>
    <p class="muted" style="margin:0;font-size:12.5px">
      The player's club covers his contract. Salary ${fmtMoney(target.wage)}/wk comes out of our wage budget until
      the season ends, then he returns to ${esc(target.club)}. Loans in: ${market.loans.incoming}/${market.loans.max}.
      Wage room <strong>${fmtMoney(market.wage_room)}</strong>/wk.
    </p>`);
  overlay.querySelector("#modalConfirm").addEventListener("click", () => {
    runTransfer("propose_loan", { player_id: target.id });
    overlay.remove();
  });
}

function askBid(target, market) {
  const free = target.kind === "free";
  const fee = free ? 0 : target.hint || Math.max(0, Math.round((target.valuation * 1.1) / 1000) * 1000);
  const base = Math.max(target.wage, 1500);
  const wage = Math.round((free ? base * 1.1 : base * 1.05) / 100) * 100;
  const note = free
    ? `<p class="muted" style="margin:0 0 12px"><strong>Free transfer</strong> &middot; no fee, just wages &middot; ${esc(target.position)} &middot; rating ${target.overall} &middot; age ${target.age}</p>`
    : `<div class="name-cell" style="margin-bottom:12px">${playerPhoto(target)}<div><strong>${esc(target.name)}</strong></div></div>
       <p class="muted" style="margin:0 0 12px">${crest(target.club)}${esc(target.club)} &middot; ${esc(target.position)} &middot; rating ${target.overall} &middot; age ${target.age}
       &middot; valued at ${fmtMoney(target.valuation)}
       &middot; clubs will want around <strong>${fmtMoney(target.hint)}</strong>
       ${target.kind === "academy" ? " &middot; <span class='pill'>academy talent</span>" : ""}</p>`;
  const overlay = openModal(`${free ? "Sign" : "Offer for"} ${target.name}`, `
    ${note}
    <label class="field"><span>Transfer fee ${free ? "(free)" : ""}</span>
      <input type="number" id="offerFee" value="${fee}" min="0" step="50000" ${free ? "disabled" : ""}></label>
    <label class="field"><span>Weekly wage</span>
      <input type="number" id="offerWage" value="${wage}" min="100" step="100"></label>
    <label class="field"><span>Contract years</span>
      <input type="number" id="offerYears" value="2" min="1" max="5" step="1"></label>
    <p class="muted" style="margin:0;font-size:12.5px">
      Budget <strong>${fmtMoney(market.budget)}</strong> &middot; wage room <strong>${fmtMoney(market.wage_room)}</strong>/wk
    </p>`);
  overlay.querySelector("#modalConfirm").addEventListener("click", () => {
    runTransfer("propose_transfer", {
      player_id: target.id,
      fee: free ? 0 : parseInt(document.getElementById("offerFee").value, 10) || 0,
      weekly_wage: parseInt(document.getElementById("offerWage").value, 10) || 0,
      contract_years: parseInt(document.getElementById("offerYears").value, 10) || 1,
    });
    overlay.remove();
  });
}

function askRenew(row) {
  const overlay = openModal(`Renew ${row.name}`, `
    <p class="muted" style="margin:0 0 12px">
      ${esc(row.position)} &middot; age ${row.age} &middot; rating ${row.overall} &middot;
      currently ${fmtMoney(row.wage)}/wk until ${esc(row.end_season)}
    </p>
    <label class="field"><span>Weekly wage</span>
      <input type="number" id="renewWage" value="${row.suggested}" min="100" step="100"></label>
    <label class="field"><span>Contract years</span>
      <input type="number" id="renewYears" value="3" min="1" max="5" step="1"></label>`);
  overlay.querySelector("#modalConfirm").addEventListener("click", () => {
    runTransfer("renew_contract", {
      player_id: row.id,
      weekly_wage: parseInt(document.getElementById("renewWage").value, 10) || 0,
      contract_years: parseInt(document.getElementById("renewYears").value, 10) || 1,
    });
    overlay.remove();
  });
}

async function runTransfer(command, payload) {
  const content = document.getElementById("content");
  try {
    const res = await action(command, payload);
    const fresh = await query("market");
    renderTransfers(fresh, res.message, res.accepted === false ? "error" : "ok");
  } catch (err) {
    const fresh = await query("market").catch(() => null);
    if (fresh) {
      renderTransfers(fresh, err.message);
    } else {
      content.innerHTML = banner(err.message);
    }
  }
}

/* ---------------------------------------------------------------- training */

const NEWS_LABELS = {
  match_result: "Results",
  transfer_done: "Transfers",
  transfer_rumor: "Rumours",
  contract: "Contracts",
  injury: "Injuries",
  manager_change: "Managers",
  young_star: "Young stars",
  streak: "Streaks",
  finance: "Finance",
  board: "Board",
  general: "General",
};

function renderNews(data) {
  const content = document.getElementById("content");
  content.innerHTML = `
    <div id="newsMsg"></div>
    <div class="card">
      <h2>Newsroom <span class="badge">${data.total} articles</span></h2>
      <div style="display:flex; gap:6px; flex-wrap:wrap; margin:10px 0 2px">
        <button class="btn ghost chip" data-cat="">All ${data.total}</button>
        ${data.categories.filter((c) => data.counts[c]).map((c) =>
          `<button class="btn ghost chip" data-cat="${esc(c)}">${esc(NEWS_LABELS[c] || c)} ${data.counts[c]}</button>`).join("")}
      </div>
    </div>
    <div id="newsFeed">
      ${data.articles.length ? data.articles.map((a) => `
        <div class="card article">
          <div style="display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap">
            <h2 style="margin:0; text-transform:none; letter-spacing:0; font-size:17px; color:var(--ink)">${esc(a.headline)}</h2>
            <span class="pill">${esc(NEWS_LABELS[a.category] || a.category)}</span>
          </div>
          ${a.body ? `<p style="margin:8px 0 0">${esc(a.body)}</p>` : ""}
          <p class="muted" style="margin:8px 0 0; font-size:12.5px">
            ${esc(a.season)} &middot; week ${a.week}
            ${a.clubs.length ? ` &middot; ${a.clubs.map(esc).join(", ")}` : ""}
          </p>
        </div>`).join("")
      : `<p class="muted">No articles yet — play some weeks first.</p>`}
    </div>`;

  content.querySelectorAll("[data-cat]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        renderNews(await query("news", { category: btn.dataset.cat }));
      } catch (err) {
        document.getElementById("newsMsg").innerHTML = banner(err.message);
      }
    });
  });
}

function renderTraining(data) {
  const content = document.getElementById("content");
  const sel = (value, options, key) => `
    <select data-k="${key}">
      ${options.map((o) => `<option value="${esc(o)}" ${value === o ? "selected" : ""}>${esc(o)}</option>`).join("")}
    </select>`;
  content.innerHTML = `
    <div id="trainingMsg"></div>
    <div class="card">
      <h2>Training &amp; tactical roles <span class="badge">${data.players.length} players</span></h2>
      <p class="muted" style="margin:0 0 10px">
        Choose what each player works on in training and how they play. Focus drives weekly attribute growth;
        high intensity grows players faster but costs energy; roles and duties influence who gets the goals.
      </p>
      <table>
        <thead><tr>
          <th>Player</th><th>Focus</th><th>Intensity</th><th>Role</th><th>Duty</th><th>Energy</th><th>Last week</th>
        </tr></thead>
        <tbody>
          ${data.players.map((p) => `
            <tr data-pid="${esc(p.id)}">
              <td><strong>${esc(p.name)}</strong><br>
                <span class="muted" style="font-size:12px">${esc(p.position)} &middot; ${p.overall} (${p.potential}) &middot; age ${p.age}</span></td>
              <td>${sel(p.focus, data.focuses)}
                <br><span class="muted" style="font-size:12px">${esc(p.focus)}</span></td>
              <td>${sel(p.intensity, data.intensities)}
                <br><span class="muted" style="font-size:12px">${esc(p.intensity)}</span></td>
              <td><select data-k="role">
                ${p.allowed_roles.map((r) => `<option value="${esc(r)}" ${p.role === r ? "selected" : ""}>${esc(r)}</option>`).join("")}
              </select></td>
              <td>${sel(p.duty, data.duties)}
                <br><span class="muted" style="font-size:12px">${esc(p.duty)}</span></td>
              <td><span class="pill ${p.energy < 40 ? "bad" : p.energy < 70 ? "warn" : "good"}">${p.energy}%</span></td>
              <td class="muted" style="font-size:12.5px">${esc(p.last_dev || "—")}</td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;

  document.querySelectorAll("tr[data-pid]").forEach((tr) => {
    tr.addEventListener("change", async () => {
      const pid = tr.dataset.pid;
      const payload = {
        player_id: pid,
        focus: tr.querySelector('[data-k="focus"]').value,
        intensity: tr.querySelector('[data-k="intensity"]').value,
        role: tr.querySelector('[data-k="role"]').value,
        duty: tr.querySelector('[data-k="duty"]').value,
      };
      try {
        const fresh = await action("set_player_plan", payload);
        renderTraining(fresh);
        document.getElementById("trainingMsg").innerHTML = banner("Training plan updated.", "ok");
      } catch (err) {
        document.getElementById("trainingMsg").innerHTML = banner(err.message);
      }
    });
  });
}

/* ------------------------------------------------------------- banner+save */

async function doSave() {
  try {
    await action("save");
    flash("Saved.");
  } catch (err) {
    flash(err.message, true);
  }
}

function flash(text, isError = false) {
  const old = document.querySelector("[data-flash]");
  if (old) old.remove();
  const node = document.createElement("div");
  node.setAttribute("data-flash", "");
  node.textContent = text;
  node.style.cssText = `position:fixed;top:14px;right:14px;padding:10px 16px;border-radius:10px;z-index:50;font-weight:700;background:${isError ? "var(--danger)" : "var(--accent-2)"};color:${isError ? "#1a0505" : "#04251b"}`;
  document.body.appendChild(node);
  setTimeout(() => node.remove(), 2200);
}

/* ----------------------------------------------------------------- boot */

async function boot() {
  renderSplash();
  try {
    const s = await query("session");
    if (s.in_career) {
      session = s;
      const data = await query("dashboard");
      app.innerHTML = "";
      renderShell(data);
    } else {
      renderSetup();
    }
  } catch (err) {
    app.innerHTML = `<div style="padding:40px;color:var(--danger)">${esc(err.message)}</div>`;
  }
}

boot();