"use strict";

const S = {
  gameId: null,
  view: null,
  ws: null,
  phase: "settings", // "settings" | "table"
  lastSeq: -1,        // highest event seq seen (dedupe + backfill cursor)
  queue: [],          // events awaiting animation
  animating: false,
  pendingView: null,  // snapshot held back until the queue drains
  skip: false,        // fast-forward flag
  closing: false,     // deliberate WS close (newGame) — suppresses reconnect
};

let wsRetryDelay = 1000; // reconnect backoff: 1s, 2s, 4s … cap 10s
let handWinnings = {};   // pid → {pid, name, amount}; reset each hand (V2 summary)

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
    gameId: null, view: null, ws: null, phase: "settings",
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
    const p = byId[pid] || { name: pid, chips: 0 };
    return {
      name: p.name,
      played: s.hands_played || 0,
      won: s.hands_won || 0,
      net: p.chips - (s.total_invested || 0),
      best: s.best_hand_name && s.best_hand_name !== "-" ? s.best_hand_name : "—",
      rebuys: s.rebuys || 0,
      topups: s.topups || 0,
    };
  }).sort((a, b) => b.net - a.net);

  el("stats-title").textContent =
    `Session stats · ${data.hand_count} hand${data.hand_count === 1 ? "" : "s"}`;
  el("stats-body").innerHTML =
    `<table><thead><tr><th>Player</th><th>Hands</th><th>Won</th><th>Win%</th>` +
    `<th>Net</th><th>Best hand</th><th>Rebuys</th><th>Top-ups</th></tr></thead><tbody>` +
    rows.map((r) => {
      const wr = r.played ? ((r.won / r.played) * 100).toFixed(1) : "0.0";
      const net = (r.net >= 0 ? "+" : "") + r.net;
      return `<tr><td>${esc(r.name)}</td><td>${r.played}</td><td>${r.won}</td>` +
        `<td>${wr}%</td><td class="${r.net >= 0 ? "pos" : "neg"}">${net}</td>` +
        `<td>${esc(r.best)}</td><td>${r.rebuys}</td><td>${r.topups}</td></tr>`;
    }).join("") +
    `</tbody></table>`;
  el("stats-modal").classList.remove("hidden");
}

function closeStats() {
  el("stats-modal").classList.add("hidden");
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
  el("settings").classList.toggle("hidden", S.phase !== "settings");
  el("table").classList.toggle("hidden", S.phase !== "table");
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
  const x = 50 + 44 * Math.cos(theta);
  const y = 50 + 42 * Math.sin(theta);
  return { x, y };
}

function renderSeats(v) {
  const seats = el("seats");
  seats.innerHTML = "";
  const players = v.players;
  const youIdx = players.findIndex((p) => p.is_you);
  const anchor = youIdx >= 0 ? youIdx : 0;

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
  }
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
  // Shortcut totals mirror players/terminal.py (amounts are deltas pushed now).
  const clamp = (x) => Math.min(max, Math.max(min, x));
  const half = clamp(Math.floor(pot / 2) + minCall);
  const full = clamp(pot + minCall);

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
restoreSession();
