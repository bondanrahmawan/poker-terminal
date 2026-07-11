"use strict";

// Client state (trimmed to what snapshot rendering needs; the event queue and
// animation fields from the spec arrive in a later step).
const S = {
  gameId: null,
  view: null,
  ws: null,
  phase: "settings", // "settings" | "table"
};

const el = (id) => document.getElementById(id);

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
    if (msg.type === "view") {
      S.view = msg.view;
      render();
    } else if (msg.type === "error") {
      setStatus(`Rejected: ${msg.reason}${msg.detail ? " — " + msg.detail : ""}`);
    }
    // "events" are ignored here — animation/pacing is a later step.
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
  openWs();
  render();
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
