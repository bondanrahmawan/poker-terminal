"use strict";

const S = {
  gameId: null,
  view: null,
  ws: null,
  phase: "menu", // "menu" | "settings" | "table" | "stats_view" | "sim_stats" | "sim"
  lastSeq: -1,        // highest event seq seen (dedupe + backfill cursor)
  queue: [],          // events awaiting animation
  animating: false,
  pendingView: null,  // snapshot held back until the queue drains
  skip: false,        // fast-forward flag
  closing: false,     // deliberate WS close (newGame) — suppresses reconnect
};

let wsRetryDelay = 1000; // reconnect backoff: 1s, 2s, 4s … cap 10s
let handWinnings = {};   // pid → {pid, name, amount}; reset each hand (V2 summary)
let statsThenQuit = false; // stats modal opened via Quit → closing it leaves the table

const esc = (s) => String(s).replace(/[&<>"']/g,
  (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));

const el = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Per-event dwell times (ms), from browser_play_assessment.md §6.3. Variable
// cases (fold, per-card streets) are handled in dwellFor().
const DWELL = {
  hand_started: 800,
  seating: 0,
  hole_cards_dealt: 400,
  blind_posted: 250,
  action_taken: 650,
  showdown_started: 500,
  hole_cards_shown: 700,
  pot_structure: 800,
  pot_awarded: 900,
  hand_ended: 0,
  blinds_raised: 600,
};

function dwellFor(ev) {
  if (ev.type === "action_taken" && ev.data.action === "fold") return 350;
  if (ev.type === "street_started") {
    const n = (ev.data.cards_dealt || []).length;
    return n * 400; // preflop deals no cards → 0
  }
  return DWELL[ev.type] ?? 0;
}

// ── Networking ───────────────────────────────────────────────────────────────

async function postJSON(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return res;
}

function openWs() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/games/${S.gameId}/ws`);
  S.ws = ws;

  ws.onopen = async () => {
    setStatus("");
    wsRetryDelay = 1000; // successful connect resets the backoff
    if (S.view && S.view.hand_number === 0) {
      // Brand-new game: start the first hand once the socket is up so its
      // broadcast reaches us. On reconnect this must NOT run (a mid-hand
      // reconnect would 409; a between-hands one would silently deal).
      await nextHand();
    } else {
      // Reconnect: events pushed while we were down are never re-sent on the
      // WS (shared broadcast cursor) — backfill via REST.
      await resyncEvents();
    }
  };

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    if (msg.type === "events") {
      let added = false;
      for (const ev of msg.events) {
        if (ev.seq <= S.lastSeq) continue;                                // dedupe
        if (S.queue.length && ev.seq <= S.queue[S.queue.length - 1].seq) continue;
        S.queue.push(ev);
        added = true;
      }
      if (added && !S.animating) pump();
    } else if (msg.type === "view") {
      if (S.animating || S.queue.length) {
        S.pendingView = msg.view; // held back; newer replaces older
      } else {
        applyView(msg.view);
      }
    } else if (msg.type === "error") {
      setStatus(`Rejected: ${msg.reason}${msg.detail ? " — " + msg.detail : ""}`);
    }
  };

  ws.onclose = () => {
    if (S.ws !== ws) return; // stale socket (replaced by a newer connect)
    if (S.closing || S.phase !== "table") return;
    setStatus("Reconnecting…");
    disableActionBar();
    scheduleReconnect();
  };
  ws.onerror = () => setStatus("Connection error.");
}

function scheduleReconnect() {
  const delay = wsRetryDelay;
  wsRetryDelay = Math.min(wsRetryDelay * 2, 10000);
  setTimeout(attemptReconnect, delay);
}

async function attemptReconnect() {
  if (S.closing || S.phase !== "table") return;
  try {
    const res = await fetch(`/games/${S.gameId}/state`);
    if (res.status === 404) {
      // Session expired or server restarted with fresh state: fall back cleanly.
      newGame();
      setStatus("Previous game expired.");
      return;
    }
    if (!res.ok) throw new Error(`state ${res.status}`);
    openWs(); // onopen resyncs events + resets backoff
  } catch (e) {
    scheduleReconnect(); // network still down — keep backing off
  }
}

// REST catch-up after a (re)connect: replay missed events through the normal
// queue (dedupe makes overlap harmless), then apply a fresh snapshot.
async function resyncEvents() {
  try {
    const res = await fetch(`/games/${S.gameId}/events?since=${S.lastSeq}`);
    if (res.ok) {
      const data = await res.json().catch(() => ({ events: [] }));
      const evs = (data.events || []).filter((ev) => ev.seq > S.lastSeq);
      if (evs.length) {
        S.queue.push(...evs);
        if (!S.animating) pump();
      }
    }
    const vres = await fetch(`/games/${S.gameId}/state`);
    if (vres.ok) {
      const view = await vres.json();
      if (S.animating || S.queue.length) S.pendingView = view;
      else applyView(view);
    }
  } catch (e) { /* WS is up; the next broadcast will still reach us */ }
}

// Restore a live session on page load (tab refresh / mobile tab kill).
async function restoreSession() {
  const gid = localStorage.getItem("poker.gameId");
  if (!gid) return;
  try {
    const res = await fetch(`/games/${gid}/state`);
    if (!res.ok) {
      localStorage.removeItem("poker.gameId");
      return;
    }
    const view = await res.json();
    S.gameId = gid;
    S.phase = "table";
    applyView(view);            // no animation on restore; also snaps lastSeq
    await backfillHistory();    // repopulate the log panel
    openWs();
  } catch (e) {
    // Server unreachable at load: leave the key for next time, show settings.
  }
}

function sendAction(action, amount = 0) {
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) return;
  S.ws.send(JSON.stringify({ action, amount }));
}

async function nextHand(rebuy = false) {
  const res = await postJSON(`/games/${S.gameId}/hands`, rebuy ? { rebuy: true } : {});
  if (res.ok) {
    setStatus(""); // clear any lingering status (e.g. "You're out of chips." after a rebuy)
    return;        // the WS broadcast drives the next hand's render
  }
  const info = await res.json().catch(() => ({}));
  if (info.reason === "busted") {
    showRebuyPrompt();
  } else if (info.reason === "game_over") {
    showGameOver(info.winner);
  } else {
    setStatus(`Next hand: ${info.reason || res.status}`);
  }
}

async function addChips() {
  const res = await postJSON(`/games/${S.gameId}/topup`, {});
  if (res.ok) return; // broadcast updates the stack
  const info = await res.json().catch(() => ({}));
  setStatus(`Add chips: ${info.reason || res.status}`);
}

// Busted (409): the 0-chip player must rebuy before the next hand can start.
function showRebuyPrompt() {
  const bar = el("action-bar");
  bar.innerHTML = "";
  setStatus("You're out of chips.");
  const btn = document.createElement("button");
  btn.textContent = "Rebuy & continue";
  btn.onclick = () => nextHand(true);
  bar.appendChild(btn);
}

// Game over (409): only one funded player remains.
function showGameOver(winner) {
  const bar = el("action-bar");
  bar.innerHTML = "";
  const banner = document.createElement("div");
  banner.className = "game-over";
  banner.textContent = winner ? `Game over — ${winner} wins` : "Game over";
  bar.appendChild(banner);
  const btn = document.createElement("button");
  btn.textContent = "New game";
  btn.onclick = newGame;
  bar.appendChild(btn);
}

function newGame() {
  localStorage.removeItem("poker.gameId");
  S.closing = true; // deliberate close — onclose must not schedule a reconnect
  if (S.ws) { try { S.ws.close(); } catch (e) { /* already closed */ } }
  Object.assign(S, {
    gameId: null, view: null, ws: null, phase: "menu",
    lastSeq: -1, queue: [], animating: false, pendingView: null, skip: false,
    closing: false,
  });
  wsRetryDelay = 1000;
  handWinnings = {};
  el("history").innerHTML = "";
  el("caption").textContent = "";
  document.title = "Poker Terminal";
  render();
}

// ── Event animation ──────────────────────────────────────────────────────────

// Drain the queue one event at a time: caption + seat highlight + history, then
// dwell. The held-back view is applied once the queue empties (§6.3).
async function pump() {
  if (S.animating) return;
  S.animating = true;
  disableActionBar();
  while (S.queue.length) {
    const ev = S.queue.shift();
    S.lastSeq = ev.seq;
    // The full fresh view is held back until the queue drains, so wipe the
    // previous hand's board here — otherwise its community cards linger on the
    // felt while the new hand's blinds/antes animate.
    if (ev.type === "hand_started") clearCommunity();
    const line = appendHistory(ev);           // every event (tracks winnings, returns caption line)
    if (line) showCaption(ev, line);          // banner + seat highlight
    // No caption → nothing to read → no dwell (kills hand-start dead air).
    await sleep(S.skip || !line ? 0 : dwellFor(ev));
  }
  S.skip = false;
  S.animating = false;
  if (S.pendingView) {
    const v = S.pendingView;
    S.pendingView = null;
    applyView(v);
  }
}

function applyView(view) {
  S.view = view;
  if (S.lastSeq < view.last_event_seq) S.lastSeq = view.last_event_seq; // snap (e.g. connect-time view)
  render();
}

// A pure event → string (null = history-skipped / no caption). Player names live
// inside the payloads, so no id→name lookup is needed.
function eventText(ev) {
  const d = ev.data;
  switch (ev.type) {
    case "hand_started":
      return `— Hand #${d.hand_number} · blinds ${d.small_blind}/${d.big_blind} —`;
    case "blind_posted": {
      const kind = d.kind === "small" ? "SB" : d.kind === "big" ? "BB" : "ante";
      return `${d.name} posts ${kind} ${d.amount}`;
    }
    case "street_started": {
      if (!d.cards_dealt || !d.cards_dealt.length) return null; // preflop
      const cards = d.cards_dealt.map((c) => c.display).join(" ");
      return `${d.street.toUpperCase()} · ${cards}`;
    }
    case "action_taken": {
      if (d.action === "fold") return `${d.name} folds`;
      if (d.action === "check") return `${d.name} checks · pot ${d.pot}`;
      if (d.action === "call") return `${d.name} calls ${d.amount} · pot ${d.pot}`;
      if (d.action === "raise") return `${d.name} raises ${d.amount} · pot ${d.pot}`;
      if (d.action === "all-in") return `${d.name} all-in ${d.amount} · pot ${d.pot}`;
      return `${d.name} ${d.action} · pot ${d.pot}`;
    }
    case "showdown_started":
      return "— Showdown —";
    case "hole_cards_shown": {
      const cards = d.cards.map((c) => c.display).join(" ");
      return `${d.name} shows ${cards} — ${d.hand_name}`;
    }
    case "pot_structure":
      return d.pots.map((p, i) =>
        i === 0
          ? `${p.label} ${p.amount}`
          : `${p.label}: ${p.amount} (${p.eligible_names.join(", ")})`
      ).join(" · ");
    case "pot_awarded":
      return `${d.name} wins ${d.amount}`;
    case "hand_ended":
      return handEndSummary();
    case "blinds_raised":
      return `Blinds up: ${d.small_blind}/${d.big_blind}`;
    default:
      return null; // seating, hole_cards_dealt
  }
}

function showCaption(ev, line) {
  el("caption").textContent = line;
  setActing(ev.data && ev.data.player_id);
}

function setActing(pid) {
  el("seats").querySelectorAll(".seat.acting").forEach((s) => s.classList.remove("acting"));
  if (!pid) return;
  const seat = el("seats").querySelector(`.seat[data-pid="${pid}"]`);
  if (seat) seat.classList.add("acting");
}

// ── History panel ────────────────────────────────────────────────────────────

// Winnings accumulator for the V2 hand-end summary. Runs for every event in
// both the live (pump) and backfill paths, always before eventText(hand_ended).
function trackEvent(ev) {
  if (ev.type === "hand_started") {
    handWinnings = {};
  } else if (ev.type === "pot_awarded") {
    const d = ev.data;
    const w = handWinnings[d.player_id] || { pid: d.player_id, name: d.name, amount: 0 };
    w.amount += d.amount;
    handWinnings[d.player_id] = w;
  }
}

function handEndSummary() {
  const youId = S.view && S.view.you ? S.view.you.player_id : null;
  const parts = Object.values(handWinnings)
    .sort((a, b) => b.amount - a.amount)
    .map((w) => (w.pid === youId ? `You win ${w.amount}` : `${w.name} wins ${w.amount}`));
  return parts.length ? `Hand over — ${parts.join(" · ")}` : "Hand over";
}

function appendHistory(ev) {
  trackEvent(ev);
  const line = eventText(ev);
  if (line === null) return null; // skip nulls (seating, own hole cards, preflop)
  const box = el("history");
  const div = document.createElement("div");
  div.className = ev.type === "hand_started" ? "h-line h-hand" : "h-line";
  // best_five is appended to the history line only; the caption stays terse.
  div.textContent = (ev.type === "hole_cards_shown" && ev.data.best_five)
    ? `${line} · best: ${ev.data.best_five}`
    : line;
  box.appendChild(div);
  while (box.childElementCount > 300) box.removeChild(box.firstChild); // cap
  box.scrollTop = box.scrollHeight;
  return line; // reused by pump() for the caption (avoids a second eventText call)
}

// Populate the log without animating (table entry / reconnect) and advance the
// dedupe cursor past what we replayed.
async function backfillHistory() {
  const res = await fetch(`/games/${S.gameId}/events?since=-1`);
  if (!res.ok) return;
  const data = await res.json().catch(() => ({ events: [] }));
  for (const ev of data.events || []) {
    appendHistory(ev);
    if (ev.seq > S.lastSeq) S.lastSeq = ev.seq;
  }
}

function disableActionBar() {
  el("action-bar").querySelectorAll("button, input").forEach((n) => (n.disabled = true));
}

// ── Stats modal ──────────────────────────────────────────────────────────────

async function showStats() {
  if (!S.gameId) return;
  const res = await fetch(`/games/${S.gameId}/stats`);
  if (!res.ok) return;
  const data = await res.json().catch(() => null);
  if (!data) return;

  const byId = {};
  ((S.view && S.view.players) || []).forEach((p) => { byId[p.player_id] = p; });

  const rows = Object.entries(data.stats).map(([pid, s]) => {
    const p = byId[pid] || { name: pid, chips: 0, style: null };
    return {
      name: p.name,
      style: p.style || "human",          // bot archetype or human
      chips: p.chips,
      played: s.hands_played || 0,
      won: s.hands_won || 0,
      net: p.chips - (s.total_invested || 0),
      best: s.best_hand_name && s.best_hand_name !== "-" ? s.best_hand_name : "—",
      bigPot: s.biggest_pot || 0,
      wonTotal: s.chips_won || 0,
      rebuys: s.rebuys || 0,
      topups: s.topups || 0,
      bustHand: s.bust_hand,               // hand number they busted, or null
    };
  }).sort((a, b) => b.net - a.net);

  el("stats-title").textContent =
    `Session stats · ${data.hand_count} hand${data.hand_count === 1 ? "" : "s"}`;

  const statusHTML = (r) =>
    r.chips > 0 ? `<span class="pos">Active</span>`
    : r.bustHand ? `<span class="neg">Bust #${r.bustHand}</span>`
    : `<span class="dim">Out</span>`;

  const table =
    `<table><thead><tr><th>Player</th><th>Hands</th><th>Won</th><th>Win%</th>` +
    `<th>Net</th><th>Big pot</th><th>Won total</th><th>Best hand</th>` +
    `<th>Rebuys</th><th>Top-ups</th><th>Status</th></tr></thead><tbody>` +
    rows.map((r) => {
      const wr = r.played ? ((r.won / r.played) * 100).toFixed(1) : "0.0";
      const net = (r.net >= 0 ? "+" : "") + r.net;
      return `<tr><td><div>${esc(r.name)}</div>` +
        `<div class="stat-style">${esc(r.style)}</div></td>` +
        `<td>${r.played}</td><td>${r.won}</td>` +
        `<td>${wr}%</td><td class="${r.net >= 0 ? "pos" : "neg"}">${net}</td>` +
        `<td>${r.bigPot}</td><td>${r.wonTotal}</td>` +
        `<td>${esc(r.best)}</td><td>${r.rebuys}</td><td>${r.topups}</td>` +
        `<td>${statusHTML(r)}</td></tr>`;
    }).join("") +
    `</tbody></table>`;

  el("stats-body").innerHTML = table + statsInsights(rows);
  el("stats-modal").classList.remove("hidden");
}

// Gini of chip counts — mirrors StatsTracker.calculate_gini (chips sorted
// ascending, 1-indexed weights): G = 2·Σ(i·x_i)/(n·Σx) − (n+1)/n.
function chipGini(chips) {
  const xs = chips.map((c) => Math.max(0, c)).sort((a, b) => a - b);
  const n = xs.length;
  const sum = xs.reduce((a, b) => a + b, 0);
  if (n === 0 || sum === 0) return 0;
  const weighted = xs.reduce((acc, x, i) => acc + (i + 1) * x, 0);
  return (2 * weighted) / (n * sum) - (n + 1) / n;
}

// Client-side insights panel: wealth concentration, per-archetype performance,
// and top performers. Field semantics mirror core/stats_tracker.py.
function statsInsights(rows) {
  const g = chipGini(rows.map((r) => r.chips));
  const gLabel = g > 0.7 ? "extreme" : g > 0.4 ? "high" : g > 0.2 ? "moderate" : "low";

  // Per-archetype: avg net + survival % (share still holding chips).
  const arch = {};
  rows.forEach((r) => {
    const a = arch[r.style] || (arch[r.style] = { net: 0, count: 0, alive: 0 });
    a.net += r.net;
    a.count += 1;
    if (r.chips > 0) a.alive += 1;
  });
  const archRows = Object.entries(arch)
    .map(([label, a]) => ({
      label,
      avgNet: Math.round(a.net / a.count),
      survival: Math.round((a.alive / a.count) * 100),
    }))
    .sort((x, y) => y.avgNet - x.avgNet);

  const archTable =
    `<table><thead><tr><th>Archetype</th><th>Avg net</th><th>Survival</th></tr></thead><tbody>` +
    archRows.map((a) => {
      const net = (a.avgNet >= 0 ? "+" : "") + a.avgNet;
      return `<tr><td>${esc(a.label)}</td>` +
        `<td class="${a.avgNet >= 0 ? "pos" : "neg"}">${net}</td>` +
        `<td>${a.survival}%</td></tr>`;
    }).join("") +
    `</tbody></table>`;

  // Top performers: best win rate (min 5 hands), biggest single pot won.
  const eligible = rows.filter((r) => r.played >= 5);
  const bestWr = eligible.length
    ? eligible.reduce((b, r) => (r.won / r.played > b.won / b.played ? r : b))
    : null;
  const bigWinner = rows.length
    ? rows.reduce((b, r) => (r.bigPot > b.bigPot ? r : b))
    : null;

  const perf = [];
  if (bestWr) {
    perf.push(`<div class="ins-line">Best win rate: <b>${esc(bestWr.name)}</b> ` +
      `(${((bestWr.won / bestWr.played) * 100).toFixed(1)}%)</div>`);
  }
  if (bigWinner) {
    perf.push(`<div class="ins-line">Biggest pot: <b>${esc(bigWinner.name)}</b> ` +
      `(${bigWinner.bigPot})</div>`);
  }

  return `<div class="insights"><h4>Insights</h4>` +
    `<div class="ins-line">Wealth concentration (Gini): <b>${g.toFixed(3)}</b> — ${gLabel} inequality</div>` +
    `<div class="ins-sub">By archetype</div>${archTable}` +
    `<div class="ins-sub">Top performers</div>${perf.join("")}` +
    `</div>`;
}

function closeStats() {
  el("stats-modal").classList.add("hidden");
  if (statsThenQuit) {
    statsThenQuit = false;
    finalizeQuit();
  }
}

// Persist the session server-side (DELETE), then reset to the menu.
async function finalizeQuit() {
  try { await fetch(`/games/${S.gameId}`, { method: "DELETE" }); } catch (e) { /* best effort */ }
  newGame();
}

// ── Landing menu + tournament-stats viewer ────────────────────────────────────

function showMenu() {
  S.phase = "menu";
  render();
}

function showSettings() {
  S.phase = "settings";
  render();
}

// Viewer state: which tab and difficulty filter are active.
const SV = { tab: "players", difficulty: "" };

function showStatsView() {
  S.phase = "stats_view";
  render();
  loadStatsView();
}

async function loadStatsView() {
  el("sv-tabs").querySelectorAll("button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === SV.tab));
  const body = el("sv-body");
  body.textContent = "Loading…";
  const q = SV.difficulty ? `?difficulty=${encodeURIComponent(SV.difficulty)}` : "";
  const path = SV.tab === "players" ? "/stats/tournament/players" : "/stats/tournament/sessions";
  try {
    const res = await fetch(path + q);
    const data = await res.json();
    body.innerHTML = SV.tab === "players" ? renderStatsPlayers(data) : renderStatsSessions(data);
    if (SV.tab === "players") wirePlayerRows();
  } catch (e) {
    body.textContent = "Could not load stats.";
  }
}

// dict {difficulty_label: [player aggregate, …]} → one table per difficulty group.
function renderStatsPlayers(byDiff) {
  const groups = Object.entries(byDiff);
  if (!groups.length) return `<p class="sv-empty">No tournament stats yet.</p>`;
  return groups.sort().map(([diff, players]) => {
    const rows = players.map((p, i) => {
      const net = (p.total_net >= 0 ? "+" : "") + p.total_net.toLocaleString();
      return `<tr class="sv-player" data-pid="${esc(p.player_id)}">` +
        `<td>${i + 1}</td>` +
        `<td><div>${esc(p.name)}</div><div class="stat-style">${p.is_human ? "Human" : "Bot"}</div></td>` +
        `<td>${p.total_sessions}</td><td>${p.total_hands_played}</td>` +
        `<td>${p.total_hands_won}</td><td>${p.win_rate.toFixed(1)}%</td>` +
        `<td class="${p.total_net >= 0 ? "pos" : "neg"}">${net}</td></tr>`;
    }).join("");
    return `<h3 class="sv-group">${esc(diff)} <span class="dim">(${players.length})</span></h3>` +
      `<table><thead><tr><th>#</th><th>Player</th><th>Sessions</th><th>Hands</th>` +
      `<th>Won</th><th>Win%</th><th>Net</th></tr></thead><tbody>${rows}</tbody></table>`;
  }).join("");
}

// list of session summaries → one table.
function renderStatsSessions(sessions) {
  if (!sessions.length) return `<p class="sv-empty">No sessions yet.</p>`;
  const rows = sessions.map((s) =>
    `<tr><td>#${s.session_id}</td><td>${esc(s.difficulty)}</td><td>${esc(s.date)}</td>` +
    `<td>${s.hands_played}</td><td>${esc(s.game_mode)}</td><td>${s.players.length}</td></tr>`
  ).join("");
  return `<table><thead><tr><th>ID</th><th>Difficulty</th><th>Date</th>` +
    `<th>Hands</th><th>Mode</th><th>Players</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function wirePlayerRows() {
  el("sv-body").querySelectorAll("tr.sv-player").forEach((tr) => {
    tr.onclick = () => loadPlayerHistory(tr.dataset.pid);
  });
}

async function loadPlayerHistory(playerId) {
  const body = el("sv-body");
  body.textContent = "Loading…";
  const q = SV.difficulty ? `?difficulty=${encodeURIComponent(SV.difficulty)}` : "";
  try {
    const res = await fetch(`/stats/tournament/players/${encodeURIComponent(playerId)}${q}`);
    const h = await res.json();
    body.innerHTML = renderPlayerHistory(h);
    el("sv-back-list").onclick = loadStatsView;
  } catch (e) {
    body.textContent = "Could not load player history.";
  }
}

function renderPlayerHistory(h) {
  if (!h || !h.player_id) return `<button id="sv-back-list" class="chip-btn">← Back</button>` +
    `<p class="sv-empty">No history for this player.</p>`;
  const at = h.all_time || {};
  const net = at.total_net != null ? (at.total_net >= 0 ? "+" : "") + at.total_net.toLocaleString() : "—";
  const avg = at.avg_net_per_session != null
    ? (at.avg_net_per_session >= 0 ? "+" : "") + Math.round(at.avg_net_per_session).toLocaleString() : "—";

  let allTime = "";
  if (at.total_sessions) {
    allTime =
      `<div class="ins-line">Sessions: <b>${at.total_sessions}</b> · Hands: <b>${at.total_hands_played}</b> · ` +
      `Won: <b>${at.total_hands_won}</b> · Win rate: <b>${at.win_rate.toFixed(1)}%</b></div>` +
      `<div class="ins-line">Net: <b class="${at.total_net >= 0 ? "pos" : "neg"}">${net}</b> · ` +
      `Avg/session: <b>${avg}</b> · Rebuys: <b>${at.total_rebuys}</b> · Biggest pot: <b>${at.biggest_pot.toLocaleString()}</b></div>` +
      `<div class="ins-line">Best hand: <b>${esc(at.best_hand)}</b></div>`;
  }

  const diffs = Object.entries(h.by_difficulty || {});
  let byDiff = "";
  if (diffs.length) {
    const rows = diffs.sort().map(([diff, d]) => {
      const s = d.stats;
      const dn = (s.total_net >= 0 ? "+" : "") + s.total_net.toLocaleString();
      const da = (s.avg_net_per_session >= 0 ? "+" : "") + Math.round(s.avg_net_per_session).toLocaleString();
      return `<tr><td>${esc(diff)}</td><td>${s.total_sessions}</td><td>${s.total_hands_played}</td>` +
        `<td>${s.win_rate.toFixed(1)}%</td><td class="${s.total_net >= 0 ? "pos" : "neg"}">${dn}</td><td>${da}</td></tr>`;
    }).join("");
    byDiff = `<div class="ins-sub">By difficulty</div>` +
      `<table><thead><tr><th>Difficulty</th><th>Sessions</th><th>Hands</th><th>Win%</th>` +
      `<th>Net</th><th>Avg Net</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  return `<button id="sv-back-list" class="chip-btn">← Back</button>` +
    `<h3 class="sv-group">${esc(h.name)} <span class="dim">${h.is_human ? "Human" : "Bot"}</span></h3>` +
    `<div class="insights">${allTime}${byDiff}</div>`;
}

// ── Simulation-stats viewer ───────────────────────────────────────────────────
// Mirrors core/simulation_stats.py print_* methods. Three tabs match print_stats:
// session history, all-time all-vs-all rankings, all-time head-to-head matrix.

const SS = { tab: "sessions", data: null };

// Signed percentage, e.g. +1.2 / -3.4 — mirrors Python's "{v:+.Nf}".
const signedPct = (v, d = 1) => (v >= 0 ? "+" : "") + (v * 100).toFixed(d);

async function showSimStats() {
  S.phase = "sim_stats";
  render();
  el("ssv-body").textContent = "Loading…";
  try {
    const res = await fetch("/stats/simulation");
    SS.data = await res.json();
  } catch (e) {
    el("ssv-body").textContent = "Could not load simulation stats.";
    return;
  }
  renderSimStats();
}

function renderSimStats() {
  el("ssv-tabs").querySelectorAll("button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === SS.tab));
  const body = el("ssv-body");
  const d = SS.data || {};
  if (SS.tab === "sessions") body.innerHTML = renderSimSessions(d.sessions || []);
  else if (SS.tab === "ava") body.innerHTML = renderSimAllTime((d.alltime || {}).all_vs_all || {});
  else body.innerHTML = renderSimH2H((d.alltime || {}).h2h || {});
}

function simConfigStr(cfg) {
  const tags = [`${esc(cfg.stack_depth)} stack`];
  if (cfg.ante) tags.push("ante");
  if (cfg.short_deck) tags.push("short");
  return tags.join(", ");
}

// Top-result string per session type — mirrors _print_session_history.
function simTopResult(s) {
  try {
    if (s.type === "all_vs_all") {
      const top = Object.entries(s.results).reduce((a, b) => (b[1].rank < a[1].rank ? b : a));
      return `${esc(top[0])} (${signedPct(top[1].avg_net_roi)}% ROI)`;
    }
    if (s.type === "h2h") {
      const best = Object.entries(s.results.overall_win_rates).reduce((a, b) => (b[1] > a[1] ? b : a));
      return `${esc(best[0])} (${best[1].toFixed(1)}% overall)`;
    }
    if (s.type === "param_sweep") {
      const r = s.results;
      return `${esc(r.param_name)}=${esc(String(r.optimal_value))} (${signedPct(r.optimal_net_roi)}% ROI)`;
    }
  } catch (e) { /* fall through to raw */ }
  return `<span class="dim">${esc(JSON.stringify(s.results))}</span>`;
}

function renderSimSessions(sessions) {
  if (!sessions.length) return `<p class="sv-empty">No simulations yet.</p>`;
  const rows = sessions.map((s) => {
    const cfg = s.config || {};
    return `<tr><td>${s.session_id}</td><td>${esc(s.type)}</td><td>${esc(s.date)}</td>` +
      `<td>${esc(cfg.difficulty || "—")}</td><td>${simConfigStr(cfg)}</td>` +
      `<td>${simTopResult(s)}</td></tr>`;
  }).join("");
  return `<table><thead><tr><th>#</th><th>Type</th><th>Date</th><th>Difficulty</th>` +
    `<th>Config</th><th>Top Result</th></tr></thead><tbody>${rows}</tbody></table>`;
}

// Bucket key: "difficulty|short_deck|ante|depth". Returns a readable header.
function bucketLabel(key) {
  const [diff, short, ante, depth] = key.split("|");
  const tags = [`${esc(depth)} stack`];
  if (ante === "True") tags.push("ante");
  if (short === "True") tags.push("short deck");
  return `${esc(diff)} · ${tags.join(", ")}`;
}

function renderSimAllTime(buckets) {
  const keys = Object.keys(buckets);
  if (!keys.length) return `<p class="sv-empty">No simulations yet.</p>`;
  return keys.map((key) => {
    const data = buckets[key];
    const totalTables = data.total_tables || 0;
    const sessions = data.sessions_count || 0;
    // Strategy entries are the dict values carrying total_roi; others are meta.
    const rows = Object.entries(data)
      .filter(([, s]) => s && typeof s === "object" && "total_roi" in s)
      .map(([sname, s]) => {
        const avgRoi = totalTables > 0 ? s.total_roi / totalTables : 0;
        const winRate = s.total_hands_played > 0
          ? (s.total_hands_won / s.total_hands_played * 100) : 0;
        const firsts = (s.rank_histogram || {})["1"] || 0;
        return { sname, avgRoi, winRate, tablesWon: s.tables_won || 0, rebuys: s.total_rebuys || 0, firsts };
      })
      .sort((a, b) => b.avgRoi - a.avgRoi);

    if (!rows.length) return `<h3 class="sv-group">${bucketLabel(key)}</h3><p class="sv-empty">No data in this bucket.</p>`;

    const body = rows.map((r, i) =>
      `<tr><td>${i + 1}</td><td>${esc(r.sname)}</td>` +
      `<td class="${r.avgRoi >= 0 ? "pos" : "neg"}">${signedPct(r.avgRoi, 2)}%</td>` +
      `<td>${r.winRate.toFixed(1)}%</td><td>${r.tablesWon.toLocaleString()}</td>` +
      `<td>${r.firsts}</td><td>${r.rebuys.toLocaleString()}</td></tr>`).join("");

    return `<h3 class="sv-group">${bucketLabel(key)} ` +
      `<span class="dim">(${sessions} sessions, ${totalTables.toLocaleString()} tables)</span></h3>` +
      `<table><thead><tr><th>Rank</th><th>Strategy</th><th>Avg ROI</th><th>Win%</th>` +
      `<th>Tbl Won</th><th>1st</th><th>Rebuys</th></tr></thead><tbody>${body}</tbody></table>`;
  }).join("");
}

function renderSimH2H(buckets) {
  const keys = Object.keys(buckets);
  if (!keys.length) return `<p class="sv-empty">No simulations yet.</p>`;
  return keys.map((key) => {
    const data = buckets[key];
    const sessions = data.sessions_count || 0;
    const names = Object.keys(data).filter((k) => data[k] && typeof data[k] === "object" && "vs" in data[k]);
    if (!names.length) return `<h3 class="sv-group">${bucketLabel(key)}</h3><p class="sv-empty">No H2H data in this bucket.</p>`;

    const head = `<tr><th></th>${names.map((n) => `<th>${esc(n)}</th>`).join("")}<th>Overall</th></tr>`;
    const rows = names.map((si) => {
      const entry = data[si];
      const cells = names.map((sj) => {
        if (si === sj) return `<td class="dim">—</td>`;
        const vs = (entry.vs || {})[sj] || {};
        if (!vs.total) return `<td class="dim">N/A</td>`;
        const pct = vs.wins / vs.total * 100;
        const cls = pct >= 60 ? "pos" : pct <= 40 ? "neg" : "";
        return `<td class="${cls}">${pct.toFixed(1)}%</td>`;
      }).join("");
      let overall = `<td class="dim">N/A</td>`;
      if (entry.overall_total > 0) {
        const ov = entry.overall_wins / entry.overall_total * 100;
        const cls = ov >= 55 ? "pos" : ov < 45 ? "neg" : "";
        overall = `<td class="${cls}">${ov.toFixed(1)}%</td>`;
      }
      return `<tr><th>${esc(si)}</th>${cells}${overall}</tr>`;
    }).join("");

    return `<h3 class="sv-group">${bucketLabel(key)} <span class="dim">(${sessions} sessions)</span></h3>` +
      `<p class="ssv-note">row beats column</p>` +
      `<table class="ssv-matrix"><thead>${head}</thead><tbody>${rows}</tbody></table>`;
  }).join("");
}

// ── Simulation runner (benchmark jobs) ────────────────────────────────────────
// Derived stats (CI, z-score, verdicts) are computed here from the raw job
// result, copying the formulas in main.py's _print_* printers verbatim.

const SIM = { type: "all_vs_all", polling: null };
const SIM_DEFAULTS = {
  all_vs_all:  { num_tables: 50, hands_per_table: 500 },
  h2h:         { num_tables: 50, hands_per_table: 200 },
  param_sweep: { num_tables: 30, hands_per_table: 300 },
};
const fmtNet = (v) => (v >= 0 ? "+" : "") + Math.round(v).toLocaleString();
// Sample std dev about a given mean (matches the printers' (n-1) formula).
const sampleSd = (xs, mean) =>
  xs.length > 1 ? Math.sqrt(xs.reduce((a, x) => a + (x - mean) ** 2, 0) / (xs.length - 1)) : 0;

function setSimType(type) {
  SIM.type = type;
  el("sim-type-picker").querySelectorAll("button").forEach((b) =>
    b.classList.toggle("active", b.dataset.sim === type));
  el("sim-f-param").classList.toggle("hidden", type !== "param_sweep");
  el("sim-f-ante").classList.toggle("hidden", type !== "all_vs_all");
  el("sim-f-short").classList.toggle("hidden", type !== "all_vs_all");
  const f = el("sim-form");
  f.num_tables.value = SIM_DEFAULTS[type].num_tables;
  f.hands_per_table.value = SIM_DEFAULTS[type].hands_per_table;
}

async function showSim() {
  S.phase = "sim";
  render();
  setSimType(SIM.type);
  el("sim-results").innerHTML = "";
  // Recover a running job on entry (refresh mid-run lands here).
  try {
    const r = await fetch("/simulations/current");
    if (r.ok) {
      const job = await r.json();
      if (job.status === "running") {
        setSimType(job.type);
        enterSimRunning(job);
        startSimPolling();
        return;
      }
    }
  } catch (e) { /* no prior job / server down — just show the setup form */ }
  showSimSetup();
}

function showSimSetup() {
  el("sim-run").classList.add("hidden");
  el("sim-setup").classList.remove("hidden");
}

function enterSimRunning(job) {
  el("sim-setup").classList.add("hidden");
  el("sim-run").classList.remove("hidden");
  el("sim-results").innerHTML = "";
  updateSimProgress(job);
}

function updateSimProgress(job) {
  const unit = { all_vs_all: "tables", h2h: "matchups", param_sweep: "steps" }[job.type] || "";
  const pct = job.total ? Math.round(job.done / job.total * 100) : 0;
  el("sim-progress-line").textContent = `${job.done}/${job.total} ${unit} (${pct}%) · ${job.elapsed}s`;
  el("sim-bar-fill").style.width = pct + "%";
}

function stopSimPolling() {
  if (SIM.polling) { clearInterval(SIM.polling); SIM.polling = null; }
}

function startSimPolling() {
  stopSimPolling();
  SIM.polling = setInterval(async () => {
    if (S.phase !== "sim") { stopSimPolling(); return; }  // left the screen
    let job;
    try {
      const r = await fetch("/simulations/current");
      if (!r.ok) { stopSimPolling(); return; }
      job = await r.json();
    } catch (e) { return; } // transient — try again next tick
    if (job.status === "running") { updateSimProgress(job); return; }
    stopSimPolling();
    updateSimProgress(job);
    showSimSetup();
    if (job.status === "error") {
      el("sim-results").innerHTML = `<p class="neg">Simulation error: ${esc(job.error || "unknown")}</p>`;
      return;
    }
    loadSimResult();
  }, 1000);
}

async function loadSimResult() {
  try {
    const r = await fetch("/simulations/current/result");
    if (!r.ok) return;
    renderSimResult(await r.json());
  } catch (e) { /* leave results empty */ }
}

function renderSimResult(data) {
  const banner = data.status === "cancelled"
    ? `<div class="sim-cancelled">Cancelled — partial result below.</div>` : "";
  let html;
  if (data.type === "all_vs_all") html = renderSimAvA(data.result, data.params);
  else if (data.type === "h2h") html = renderSimH2HRun(data.result, data.params);
  else html = renderSimSweep(data.result, data.params);
  el("sim-results").innerHTML = banner + html;
}

// A horizontal CSS bar chart of signed values (green/red, width ∝ |value|).
function simBarChart(title, rows) {
  const maxAbs = Math.max(...rows.map((r) => Math.abs(r.value)), 1);
  const bars = rows.map((r) => {
    const w = Math.abs(r.value) / maxAbs * 100;
    return `<div class="sim-bar-row"><span class="sim-bar-label">${esc(r.label)}</span>` +
      `<span class="sim-bar-track"><span class="sim-bar-val ${r.value >= 0 ? "pos-bg" : "neg-bg"}" ` +
      `style="width:${w}%"></span></span>` +
      `<span class="sim-bar-num ${r.value >= 0 ? "pos" : "neg"}">${fmtNet(r.value)}</span></div>`;
  }).join("");
  return `<h3 class="sv-group">${esc(title)}</h3><div class="sim-chart">${bars}</div>`;
}

function renderSimAvA(result, params) {
  const nt = params.num_tables;
  const ranked = result.ranked, ptn = result.per_table_nets;

  const rows = ranked.map(([name, data], i) => {
    const nets = ptn[name] || [];
    const avg = data.total_net / nt;
    const sd = sampleSd(nets, avg);
    const ci = nets.length > 1 ? 1.96 * sd / Math.sqrt(nets.length) : 0;
    const win = data.hands_played > 0 ? data.hands_won / data.hands_played * 100 : 0;
    return `<tr><td>${i + 1}</td><td>${esc(name)}</td>` +
      `<td class="${avg >= 0 ? "pos" : "neg"}">${fmtNet(avg)}</td>` +
      `<td class="dim">±${Math.round(ci).toLocaleString()}</td>` +
      `<td class="dim">${Math.round(sd).toLocaleString()}</td>` +
      `<td>${win.toFixed(1)}%</td><td>${(data.total_rebuys / nt).toFixed(1)}</td>` +
      `<td>${data.tables_won}/${nt}</td></tr>`;
  }).join("");
  const table = `<table><thead><tr><th>#</th><th>Strategy</th><th>Avg Net</th>` +
    `<th>±95%CI</th><th>Std Dev</th><th>Win%</th><th>Rebuys</th><th>Tbl Won</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>`;

  // Significance (1st vs 2nd) — pooled two-sample z, verbatim from the printer.
  let sig = "";
  if (ranked.length >= 2) {
    const [tName, tData] = ranked[0], [sName, sData] = ranked[1];
    const tNets = ptn[tName] || [], sNets = ptn[sName] || [];
    const tAvg = tData.total_net / nt, sAvg = sData.total_net / nt;
    const tSd = sampleSd(tNets, tAvg), sSd = sampleSd(sNets, sAvg);
    const pooledSe = tNets.length > 1
      ? Math.sqrt(tSd ** 2 / tNets.length + sSd ** 2 / sNets.length) : 1;
    const z = pooledSe > 0 ? (tAvg - sAvg) / pooledSe : 0;
    let verdict, cls;
    if (z >= 2.576) { verdict = "HIGHLY SIGNIFICANT (p < 0.01)"; cls = "pos"; }
    else if (z >= 1.96) { verdict = "SIGNIFICANT (p < 0.05)"; cls = "pos"; }
    else if (z >= 1.645) { verdict = "MARGINALLY SIGNIFICANT (p < 0.10)"; cls = "warn"; }
    else { verdict = "NOT SIGNIFICANT — increase tables for confidence"; cls = "neg"; }
    sig = `<p class="sim-sig">Significance (1st vs 2nd): z = ${z.toFixed(2)} — ` +
      `<span class="${cls}">${verdict}</span></p>`;
  }

  const chart = simBarChart("Net profit (avg chips/table)",
    ranked.map(([name, data]) => ({ label: name, value: data.total_net / nt })));

  // Convergence check (present only when num_tables ≥ 8).
  let conv = "";
  const snaps = result.convergence_snapshots || [];
  if (snaps.length) {
    const finalTop3 = ranked.slice(0, 3).map(([n]) => n);
    const lines = snaps.map(([tablesDone, top3]) => {
      const match = top3.filter((s) => finalTop3.includes(s)).length;
      const cls = match === 3 ? "pos" : match >= 2 ? "warn" : "neg";
      return `<div class="ins-line"><span class="${cls}">[${match}/3]</span> at ` +
        `${(tablesDone / nt * 100).toFixed(0)}% (${tablesDone} tables): ${top3.map(esc).join(", ")}</div>`;
    }).join("");
    const last = snaps[snaps.length - 1][1];
    const converged = finalTop3.every((s) => last.includes(s)) && last.every((s) => finalTop3.includes(s));
    const verdict = converged
      ? `<div class="ins-line pos">Ranking converged by 75% — results are stable</div>`
      : `<div class="ins-line warn">Ranking shifted after 75% — consider more tables</div>`;
    conv = `<h3 class="sv-group">Convergence check</h3>${lines}${verdict}`;
  }

  return table + sig + chart + conv;
}

function renderSimH2HRun(result, params) {
  const nt = params.num_tables;
  const names = result.strat_names, wins = result.wins, n = names.length;
  const overall = names.map((_, i) =>
    wins[i].reduce((s, w, j) => (j !== i ? s + w : s), 0) / ((n - 1) * nt) * 100);

  const head = `<tr><th></th>${names.map((x) => `<th>${esc(x)}</th>`).join("")}<th>Overall</th></tr>`;
  const rows = names.map((ri, i) => {
    const cells = names.map((_, j) => {
      if (i === j) return `<td class="dim">—</td>`;
      const pct = wins[i][j] / nt * 100;
      const cls = pct >= 60 ? "pos" : pct <= 40 ? "neg" : "";
      return `<td class="${cls}">${pct.toFixed(0)}%</td>`;
    }).join("");
    const ov = overall[i], ocls = ov >= 55 ? "pos" : ov < 45 ? "neg" : "";
    return `<tr><th>${esc(ri)}</th>${cells}<td class="${ocls}">${ov.toFixed(1)}%</td></tr>`;
  }).join("");
  const matrix = `<p class="ssv-note">row beats column</p>` +
    `<table class="ssv-matrix"><thead>${head}</thead><tbody>${rows}</tbody></table>`;

  const ranking = names.map((nm, i) => ({ nm, ov: overall[i] })).sort((a, b) => b.ov - a.ov);
  const medals = ["1st", "2nd", "3rd"];
  const domRows = ranking.map((r, i) => {
    const cls = r.ov >= 55 ? "pos" : r.ov < 45 ? "neg" : "";
    return `<div class="ins-line">${medals[i] || (i + 1) + "th"}  <b>${esc(r.nm)}</b>  ` +
      `<span class="${cls}">${r.ov.toFixed(1)}% win rate</span></div>`;
  }).join("");

  return matrix + `<h3 class="sv-group">Dominance ranking</h3>${domRows}`;
}

function renderSimSweep(result, params) {
  const nt = params.num_tables, sc = params.starting_chips;
  const pts = result.results;  // [[value, avg_net, sd], …]
  if (!pts.length) return `<p class="sim-cancelled">No data points completed.</p>`;

  let best = pts[0];
  pts.forEach((p) => { if (p[1] > best[1]) best = p; });

  const rows = pts.map(([v, avg, sd]) => {
    const ci = nt > 1 ? 1.96 * sd / Math.sqrt(nt) : 0;
    const isBest = v === best[0];
    return `<tr class="${isBest ? "sim-best" : ""}"><td>${v.toFixed(1)}${isBest ? " ★" : ""}</td>` +
      `<td class="${avg >= 0 ? "pos" : "neg"}">${fmtNet(avg)}</td>` +
      `<td class="dim">±${Math.round(ci).toLocaleString()}</td>` +
      `<td class="dim">${Math.round(sd).toLocaleString()}</td></tr>`;
  }).join("");
  const table = `<table><thead><tr><th>${esc(params.param_name)}</th><th>Avg Net</th>` +
    `<th>±95%CI</th><th>Std Dev</th></tr></thead><tbody>${rows}</tbody></table>`;

  const nets = pts.map((p) => p[1]);
  const spread = Math.max(...nets) - Math.min(...nets);
  const [sens, scls] = spread > sc * 2 ? ["HIGH", "neg"] : spread > sc ? ["MODERATE", "warn"] : ["LOW", "dim"];
  const summary = `<p class="sim-sig">Optimal: <b>${esc(params.param_name)} = ${best[0].toFixed(1)}</b> ` +
    `(avg ${fmtNet(best[1])} chips/table)</p>` +
    `<p class="sim-sig">Sensitivity: <span class="${scls}">${sens}</span></p>`;

  const chart = simBarChart(`${params.param_name} vs net profit (chips/table)`,
    pts.map(([v, avg]) => ({ label: v.toFixed(1), value: avg })));

  return summary + table + chart;
}

function initHistoryToggle() {
  const panel = el("history-panel");
  panel.classList.toggle("collapsed", localStorage.getItem("poker.history") === "1");
  el("history-toggle").onclick = () => {
    const collapsed = panel.classList.toggle("collapsed");
    localStorage.setItem("poker.history", collapsed ? "1" : "0");
  };
}

// Simple/mobile display mode: a pure CSS switch via body.simple. Default ON on
// narrow viewports when the user hasn't chosen yet.
function initSimpleMode() {
  const stored = localStorage.getItem("poker.simple");
  const simple = stored === null
    ? matchMedia("(max-width: 640px)").matches
    : stored === "1";
  const box = el("simple-toggle").querySelector("input");
  box.checked = simple;
  document.body.classList.toggle("simple", simple);
  box.addEventListener("change", () => {
    document.body.classList.toggle("simple", box.checked);
    localStorage.setItem("poker.simple", box.checked ? "1" : "0");
  });
  // Auto-follow the breakpoint until the user makes an explicit choice, so
  // rotating/resizing onto a narrow screen switches to the stacked view.
  matchMedia("(max-width: 640px)").addEventListener("change", (e) => {
    if (localStorage.getItem("poker.simple") !== null) return;
    box.checked = e.matches;
    document.body.classList.toggle("simple", e.matches);
  });
}

// Light/dark theme: persisted, defaults to dark. Applied on <html> so the CSS
// variable overrides cascade to everything.
function initTheme() {
  const stored = localStorage.getItem("poker.theme");
  applyTheme(stored === "light" ? "light" : "dark");
  el("theme-toggle").addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    applyTheme(next);
    localStorage.setItem("poker.theme", next);
  });
}
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  el("theme-toggle").textContent = theme === "light" ? "☀️" : "🌙";
}

// ── Settings → create game ───────────────────────────────────────────────────

el("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const settings = {
    player_name: f.player_name.value || "Player",
    num_bots: Number(f.num_bots.value),
    difficulty: f.difficulty.value,
    game_mode: f.game_mode.value,
    starting_chips: Number(f.starting_chips.value),
    big_blind: Number(f.big_blind.value),
    hands_per_level: Number(f.hands_per_level.value),
    enable_ante: f.enable_ante.checked,
    short_deck: f.short_deck.checked,
    shuffle_bots: f.shuffle_bots.checked,
  };
  const res = await postJSON("/games", settings);
  if (!res.ok) {
    // #ws-status lives in the (hidden) table screen, so alert here instead.
    alert(res.status === 503
      ? "The server is at capacity right now — try again shortly."
      : `Could not create game (error ${res.status}).`);
    return;
  }
  const data = await res.json();
  S.gameId = data.game_id;
  S.view = data.view;
  localStorage.setItem("poker.gameId", S.gameId);
  S.phase = "table";
  render();
  await backfillHistory(); // empty for a fresh game; sets lastSeq before WS events arrive
  openWs();
});

// ── Rendering ────────────────────────────────────────────────────────────────

function render() {
  el("menu").classList.toggle("hidden", S.phase !== "menu");
  el("settings").classList.toggle("hidden", S.phase !== "settings");
  el("table").classList.toggle("hidden", S.phase !== "table");
  el("stats-view").classList.toggle("hidden", S.phase !== "stats_view");
  el("sim-stats-view").classList.toggle("hidden", S.phase !== "sim_stats");
  el("sim-view").classList.toggle("hidden", S.phase !== "sim");
  if (S.phase === "table") renderTable();
}

function renderTable() {
  const v = S.view;
  if (!v) return;
  el("raw-json").textContent = JSON.stringify(v, null, 2);

  const b = v.blinds || {};
  const levelStr = v.game_mode === "cash"
    ? "Cash"
    : `Level ${b.level}` +
      (b.hands_to_level != null ? ` · next in ${b.hands_to_level} hand${b.hands_to_level === 1 ? "" : "s"}` : "");
  el("table-info").innerHTML =
    `<span>Hand #${v.hand_number}</span>` +
    `<span>Blinds ${b.small}/${b.big}${b.ante ? " (ante " + b.ante + ")" : ""} · ${levelStr}` +
    `${v.short_deck ? " · Short Deck" : ""}</span>`;

  renderSeats(v);
  renderCommunity(v);
  el("pot").textContent = `Pot: ${v.pot}`;
  renderHole(v);
  el("hand-name").textContent = (v.you && v.you.hand_name) || "";
  renderActionBar(v);
}

function cardHTML(c) {
  const red = c.suit === "H" || c.suit === "D";
  return `<span class="card${red ? " red" : ""}">${c.display}</span>`;
}

function seatPosition(rel, total) {
  // Human (rel 0) sits bottom-centre; others spread clockwise around an ellipse.
  const theta = Math.PI / 2 + (rel / total) * 2 * Math.PI;
  // Radii kept clear of the seat box's half-width/height so side and end seats
  // stay inside the felt oval rather than spilling over its rim.
  const x = 50 + 42 * Math.cos(theta);
  const y = 50 + 40 * Math.sin(theta);
  return { x, y };
}

function renderSeats(v) {
  const seats = el("seats");
  seats.innerHTML = "";
  const players = v.players;
  const youIdx = players.findIndex((p) => p.is_you);
  const anchor = youIdx >= 0 ? youIdx : 0;

  // Scale seat boxes down as the table fills so they stay clear of each other.
  const n = players.length;
  seats.style.setProperty("--seat-w", (n > 10 ? 104 : n > 7 ? 114 : 124) + "px");
  seats.classList.toggle("crowded", n > 8);

  players.forEach((p, idx) => {
    const rel = (idx - anchor + players.length) % players.length;
    const { x, y } = seatPosition(rel, players.length);

    const cls = ["seat"];
    if (p.is_you) cls.push("you");
    const busted = p.chips === 0 && !p.is_active && !p.is_all_in;
    if (busted) cls.push("busted");
    else if (!p.is_active) cls.push("folded");

    const badges = [];
    if (p.role) badges.push(`<span class="badge">${p.role}</span>`);
    if (p.is_all_in) badges.push(`<span class="badge allin">ALL-IN</span>`);

    const div = document.createElement("div");
    div.className = cls.join(" ");
    div.dataset.pid = p.player_id;
    div.style.left = x + "%";
    div.style.top = y + "%";
    div.innerHTML =
      `<div class="name">${esc(p.name)} ${badges.join(" ")}</div>` +
      (p.style ? `<div class="style">${esc(p.style)}</div>` : "") +
      `<div class="chips">${p.chips}</div>` +
      `<div class="bet">${p.bet_this_round ? "bet " + p.bet_this_round : ""}</div>`;
    seats.appendChild(div);
  });
}

function renderCommunity(v) {
  const slots = [];
  for (let i = 0; i < 5; i++) {
    const c = v.community_cards[i];
    slots.push(c ? cardHTML(c) : `<span class="card empty"></span>`);
  }
  el("community").innerHTML = slots.join("");
}

// Reset the board to five empty slots (called at hand start, before the fresh
// view lands).
function clearCommunity() {
  el("community").innerHTML =
    `<span class="card empty"></span>`.repeat(5);
}

function renderHole(v) {
  const you = v.players.find((p) => p.is_you);
  const cards = (you && you.hole_cards) || [];
  el("hole").innerHTML = cards.length
    ? cards.map(cardHTML).join("")
    : `<span class="card back"></span><span class="card back"></span>`;
}

function renderActionBar(v) {
  const bar = el("action-bar");
  bar.innerHTML = "";
  // While captions are still playing the view is stale; keep the bar empty so it
  // can't unlock before the player has seen why it's their turn.
  if (S.animating) return;
  const you = v.you;

  // "Your turn" attention cue: pulse + tab title (helps backgrounded tabs).
  const toAct = !!(you && you.to_act && you.action_request);
  bar.classList.toggle("your-turn", toAct);
  document.title = toAct ? "● Your turn — Poker Terminal" : "Poker Terminal";

  if (toAct) {
    renderActions(bar, you.action_request);
    return;
  }
  // Not our turn. If the hand is over, offer to start the next one so a full
  // hand is playable end-to-end (the rich between-hands flow comes later).
  if (v.state === "END" || v.state === "WAITING") {
    const btn = document.createElement("button");
    btn.textContent = "Next hand";
    btn.onclick = () => nextHand();
    bar.appendChild(btn);

    const add = document.createElement("button");
    add.textContent = "Add chips";
    add.className = "chip-btn";
    add.onclick = addChips;
    bar.appendChild(add);

    const quit = document.createElement("button");
    quit.textContent = "Quit table";
    quit.className = "chip-btn";
    quit.onclick = quitTable;
    bar.appendChild(quit);
  }
}

// Leave the table for good: show the finished game's stats first, then persist
// and return to the menu once the modal is dismissed (finalizeQuit, via
// closeStats). Stats are fetched while the game still exists — before DELETE.
async function quitTable() {
  if (!confirm("Leave this table? Your session stats will be saved.")) return;
  statsThenQuit = true;
  await showStats();
  // If stats couldn't be shown (e.g. request failed), don't strand the user.
  if (el("stats-modal").classList.contains("hidden")) closeStats();
}

function renderActions(bar, req) {
  const mk = (label, fn, cls) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    if (cls) btn.className = cls;
    btn.onclick = fn;
    bar.appendChild(btn);
    return btn;
  };

  for (const a of req.legal_actions) {
    if (a === "fold") mk("Fold", () => sendAction("fold"));
    else if (a === "check") mk("Check", () => sendAction("check"));
    else if (a === "call") mk(`Call ${req.min_call}`, () => sendAction("call"));
    else if (a === "raise") mk("Raise", () => toggleRaisePanel(bar, req));
    else if (a === "all-in") mk(`All-in ${req.max_raise_total}`, () => confirmAllIn());
  }

  const info = document.createElement("div");
  info.className = "hint";
  const parts = [];
  if (req.min_call > 0) {
    const ratio = (req.pot_size / req.min_call).toFixed(1);
    const pct = Math.round((req.min_call / (req.pot_size + req.min_call)) * 100);
    parts.push(`To call ${req.min_call} · pot odds ${ratio}:1 (${pct}%)`);
  }
  parts.push(`Min raise ${req.min_raise_total}`);
  info.textContent = parts.join(" · ");
  bar.appendChild(info);
}

function confirmAllIn() {
  if (confirm("Go all-in?")) sendAction("all-in");
}

function toggleRaisePanel(bar, req) {
  const existing = bar.querySelector(".raise-panel");
  if (existing) { existing.remove(); return; }

  const min = req.min_raise_total;
  const max = req.max_raise_total;
  const minCall = req.min_call;
  const pot = req.pot_size;
  // Shortcut deltas mirror players/terminal.py (chips pushed in now). A pot-
  // sized raise = call the outstanding bet, then raise by the resulting pot.
  const clamp = (x) => Math.min(max, Math.max(min, x));
  const half = clamp(minCall + Math.floor((pot + minCall) / 2));
  const full = clamp(minCall + (pot + minCall));

  const panel = document.createElement("div");
  panel.className = "raise-panel";
  panel.innerHTML =
    `<input type="range" min="${min}" max="${max}" value="${min}" step="1" />` +
    `<input type="number" min="${min}" max="${max}" value="${min}" />` +
    `<button class="chip-btn" data-v="${min}">Min ${min}</button>` +
    `<button class="chip-btn" data-v="${half}">½ Pot ${half}</button>` +
    `<button class="chip-btn" data-v="${full}">Pot ${full}</button>` +
    `<button class="chip-btn" data-v="${max}">Max ${max}</button>` +
    `<button class="confirm">Confirm</button>` +
    `<div class="hint"></div>`;
  bar.appendChild(panel);

  const range = panel.querySelector('input[type="range"]');
  const number = panel.querySelector('input[type="number"]');
  const hint = panel.querySelector(".hint");
  const sync = (val) => {
    const amt = clamp(Math.round(Number(val) || min));
    range.value = amt;
    number.value = amt;
    hint.textContent = `Putting in ${amt} now (min ${min}, max ${max}).`;
  };
  range.oninput = () => sync(range.value);
  number.oninput = () => sync(number.value);
  panel.querySelectorAll(".chip-btn").forEach((btn) => {
    btn.onclick = () => sync(btn.dataset.v);
  });
  panel.querySelector(".confirm").onclick = () => {
    sendAction("raise", clamp(Math.round(Number(number.value) || min)));
  };
  sync(min);
}

function setStatus(text) {
  el("ws-status").textContent = text;
}

// ── Wiring ───────────────────────────────────────────────────────────────────

// Skip affordance: click the felt (or leave the tab) to fast-forward the queue.
el("felt").addEventListener("click", () => { if (S.animating) S.skip = true; });
document.addEventListener("visibilitychange", () => { if (document.hidden && S.animating) S.skip = true; });

// Quit the table at any point → back to settings (clears the session).
el("quit-btn").addEventListener("click", () => {
  if (confirm("Leave this table and start a new game?")) newGame();
});

// Landing-menu wiring: Play → settings, Tournament stats → viewer; disabled
// entries (Simulation, Simulation stats) do nothing until later phases.
el("menu-list").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-menu]");
  if (!btn || btn.disabled) return;
  if (btn.dataset.menu === "play") showSettings();
  else if (btn.dataset.menu === "tstats") showStatsView();
  else if (btn.dataset.menu === "sstats") showSimStats();
  else if (btn.dataset.menu === "sim") showSim();
});
el("settings-back").addEventListener("click", showMenu);
el("stats-view-back").addEventListener("click", showMenu);
el("sim-stats-back").addEventListener("click", showMenu);
el("sim-back").addEventListener("click", () => { stopSimPolling(); showMenu(); });
el("sim-type-picker").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-sim]");
  if (btn) setSimType(btn.dataset.sim);
});
el("sim-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = {
    type: SIM.type,
    num_tables: Number(f.num_tables.value),
    hands_per_table: Number(f.hands_per_table.value),
    starting_chips: Number(f.starting_chips.value),
    big_blind: Number(f.big_blind.value),
    difficulty: f.difficulty.value,   // label; the server normalizes to a float
  };
  if (SIM.type === "all_vs_all") { body.ante = f.ante.checked; body.short_deck = f.short_deck.checked; }
  if (SIM.type === "param_sweep") { body.param_name = f.param_name.value; }
  const res = await postJSON("/simulations", body);
  if (res.status === 409) { alert("A simulation is already running."); return; }
  if (!res.ok) { alert(`Could not start simulation (error ${res.status}).`); return; }
  enterSimRunning(await res.json());
  startSimPolling();
});
el("sim-cancel").addEventListener("click", async () => {
  el("sim-cancel").disabled = true;
  try { await fetch("/simulations/current/cancel", { method: "POST" }); } catch (e) { /* poll will settle */ }
  el("sim-cancel").disabled = false;
});
el("ssv-tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  SS.tab = btn.dataset.tab;
  renderSimStats();
});
el("sv-difficulty").addEventListener("change", (e) => {
  SV.difficulty = e.target.value;
  loadStatsView();
});
el("sv-tabs").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-tab]");
  if (!btn) return;
  SV.tab = btn.dataset.tab;
  loadStatsView();
});

// Stats modal wiring: button, ✕, backdrop click.
el("stats-btn").addEventListener("click", showStats);
el("stats-close").addEventListener("click", closeStats);
el("stats-modal").addEventListener("click", (e) => {
  if (e.target === el("stats-modal")) closeStats();
});

// Keyboard shortcuts (V4). Driven by clicking the rendered buttons so all
// gating (animating, disabled, legality) stays in renderActionBar.
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, textarea, select")) return;
  if (!el("stats-modal").classList.contains("hidden")) {
    if (e.key === "Escape") closeStats();
    return;
  }
  if (S.phase !== "table") return;

  const bar = el("action-bar");
  const panel = bar.querySelector(".raise-panel");
  if (e.key === "Escape" && panel) { panel.remove(); return; }
  if (e.key === "Enter" && panel) {
    e.preventDefault();
    panel.querySelector(".confirm").click();
    return;
  }

  const byLabel = (pred) =>
    [...bar.querySelectorAll("button")].find((b) => !b.disabled && pred(b.textContent));
  const k = e.key.toLowerCase();
  let btn = null;
  if (k === "f") btn = byLabel((t) => t === "Fold");
  else if (k === "c") btn = byLabel((t) => t === "Check" || t.startsWith("Call"));
  else if (k === "r") btn = byLabel((t) => t === "Raise");
  else if (k === "a") btn = byLabel((t) => t.startsWith("All-in"));
  else if (k === "n") btn = byLabel((t) => t === "Next hand");
  if (btn) { e.preventDefault(); btn.click(); }
});

initHistoryToggle();
initSimpleMode();
initTheme();
restoreSession();
