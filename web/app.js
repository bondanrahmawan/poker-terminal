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
};

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
    // Start the first hand once the socket is up so its broadcast reaches us.
    const res = await postJSON(`/games/${S.gameId}/hands`, {});
    if (!res.ok) {
      const info = await res.json().catch(() => ({}));
      setStatus(`Could not start hand: ${info.reason || res.status}`);
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

  ws.onclose = () => setStatus("Disconnected.");
  ws.onerror = () => setStatus("Connection error.");
}

function sendAction(action, amount = 0) {
  if (!S.ws || S.ws.readyState !== WebSocket.OPEN) return;
  S.ws.send(JSON.stringify({ action, amount }));
}

async function nextHand() {
  const res = await postJSON(`/games/${S.gameId}/hands`, {});
  if (!res.ok) {
    const info = await res.json().catch(() => ({}));
    // Full between-hands / rebuy / game-over flow is a later step; surface plainly.
    setStatus(`Next hand: ${info.reason || res.status}`);
  }
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
    appendHistory(ev);                        // every event, always
    const line = eventText(ev);
    if (line) showCaption(ev, line);          // banner + seat highlight
    await sleep(S.skip ? 0 : dwellFor(ev));
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
    case "pot_awarded":
      return `${d.name} wins ${d.amount}`;
    case "hand_ended":
      return "Hand over";
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

function appendHistory(ev) {
  const line = eventText(ev);
  if (line === null) return; // skip nulls (seating, own hole cards, preflop)
  const box = el("history");
  const div = document.createElement("div");
  div.className = ev.type === "hand_started" ? "h-line h-hand" : "h-line";
  div.textContent = line;
  box.appendChild(div);
  while (box.childElementCount > 300) box.removeChild(box.firstChild); // cap
  box.scrollTop = box.scrollHeight;
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

function initHistoryToggle() {
  const panel = el("history-panel");
  panel.classList.toggle("collapsed", localStorage.getItem("poker.history") === "1");
  el("history-toggle").onclick = () => {
    const collapsed = panel.classList.toggle("collapsed");
    localStorage.setItem("poker.history", collapsed ? "1" : "0");
  };
}

// ── Settings → create game ───────────────────────────────────────────────────

el("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const settings = {
    player_name: f.player_name.value || "Player",
    num_bots: Number(f.num_bots.value),
    difficulty: f.difficulty.value,
    starting_chips: Number(f.starting_chips.value),
    big_blind: Number(f.big_blind.value),
    hands_per_level: Number(f.hands_per_level.value),
    enable_ante: f.enable_ante.checked,
    short_deck: f.short_deck.checked,
    shuffle_bots: f.shuffle_bots.checked,
  };
  const res = await postJSON("/games", settings);
  if (!res.ok) {
    setStatus(`Create failed: ${res.status}`);
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
  el("table-header").innerHTML =
    `<span>Hand #${v.hand_number}</span>` +
    `<span>Blinds ${b.small}/${b.big}${b.ante ? " (ante " + b.ante + ")" : ""} · Level ${b.level}</span>`;

  renderSeats(v);
  renderCommunity(v);
  el("pot").textContent = `Pot: ${v.pot}`;
  renderHole(v);
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
      `<div class="name">${p.name} ${badges.join(" ")}</div>` +
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

  if (you && you.to_act && you.action_request) {
    renderActions(bar, you.action_request);
    return;
  }
  // Not our turn. If the hand is over, offer to start the next one so a full
  // hand is playable end-to-end (the rich between-hands flow comes later).
  if (v.state === "END" || v.state === "WAITING") {
    const btn = document.createElement("button");
    btn.textContent = "Next hand";
    btn.onclick = nextHand;
    bar.appendChild(btn);
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

initHistoryToggle();
