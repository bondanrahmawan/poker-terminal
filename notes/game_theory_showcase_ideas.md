# Game Theory Showcase — Four Directions (Detailed)

**Context:** The goal of poker-terminal has shifted. It's not about building the strongest poker engine — it's about **using poker to simulate and demonstrate game theory**, as a presentable side project with solid fundamentals (LinkedIn showcase, not academic research).

Poker is the canonical vehicle for several game-theory ideas at once:

- **Imperfect information** — deciding under uncertainty about hidden state (opponents' cards). Chess and Go are perfect-information; poker is the standard example of the other kind.
- **Mixed strategies** — optimal play is often "do X with probability p," not a deterministic move. In perfect-information games a pure strategy always suffices; in poker, any deterministic bluffing rule can be read and exploited, so the *optimum itself* is randomized. This is the concept chess/Go never teach.
- **Nash equilibrium** — a strategy profile where no player can improve by unilaterally deviating. In two-player zero-sum games, playing equilibrium guarantees you can't lose in expectation, no matter what the opponent does.
- **GTO vs. exploitative play** — the tension between being unexploitable (equilibrium) and maximally punishing a specific opponent's leaks (best response). Real skill in poker is knowing when to deviate.
- **Expected value (EV)** — evaluating decisions against a probability distribution over hidden states and future cards, not against a single outcome. "I lost the hand" ≠ "the decision was wrong."

The design question is **which concept to make visible**, because that decides what to build. Four candidate directions follow. They are ordered so that #1 is the foundation, #2 and #4 build on it, and #3 is independent.

---

## 1. Toy Solver — "Watch Equilibrium Emerge from Self-Play"

### Concept taught
Nash equilibrium, mixed strategies, and self-play learning. This is the headline idea behind the landmark poker AIs (Cepheus, Libratus, Pluribus), shrunk to a game small enough to solve completely, verify against a textbook answer, and explain end-to-end in a post.

### Background: how the landmark systems relate

| System | Year | Achievement | Relevance here |
|---|---|---|---|
| **Cepheus** (U. Alberta) | 2015 | Essentially *solved* heads-up limit hold'em via CFR+ | Proof that CFR converges to equilibrium at scale |
| **Libratus** (CMU) | 2017 | Beat pros at heads-up no-limit | Blueprint strategy + real-time subgame re-solving + overnight self-patching |
| **Pluribus** (CMU/FAIR) | 2019 | Beat pros at **6-player** no-limit for ~$144 of compute | Monte Carlo CFR (sampling instead of full tree walks) makes it cheap |

All three run on the same core algorithm. We implement that core algorithm on a toy game.

### Background: CFR (Counterfactual Regret Minimization)

The algorithm plays the game against itself repeatedly and learns from hindsight:

1. **Information sets.** A decision point is not a game state but an *information set*: everything the acting player knows — own card(s) + the betting history — and nothing they don't (opponents' cards). Two states that look identical to the player are the same info set. Strategy and regret are stored **per info set**, which is why memory stays tiny even when the underlying state space is larger.
2. **Regret.** After each self-play iteration, for every info set visited, compute per-action *counterfactual regret*: "how much better would my expected value have been had I played action X here, holding everyone else's strategy fixed?" Positive regret = "I should have done more of this."
3. **Regret matching.** Next iteration's strategy at each info set picks actions with probability proportional to accumulated *positive* regret. Actions that keep looking good in hindsight get played more; actions with no positive regret get probability 0 (until regrets shift).
4. **Average strategy.** The current strategy oscillates forever. The **time-average** of all strategies played is what provably converges to Nash equilibrium. This is the single most common implementation bug: people output the final strategy instead of the average and wonder why it doesn't match theory.

Theoretical guarantee (two-player zero-sum): if both players' average regret → 0, the average strategy profile → equilibrium, with exploitability shrinking as O(1/√T) in iterations T. For Kuhn poker, convergence to ~1% of optimal takes well under a second.

**Variants worth knowing** (mention-worthy in a post, optional in code):
- **CFR+** — clip regrets at zero instead of letting them go negative; converges dramatically faster. Trivial code change, good "look, 10× faster convergence" chart.
- **Monte Carlo CFR (MCCFR)** — sample chance outcomes / actions instead of walking the full tree each iteration. Unnecessary for Kuhn (tree is tiny) but it's the Pluribus trick; worth a sentence.

### The game: Kuhn poker — full rules

- Deck of **3 cards**: J, Q, K. Two players, each antes 1 chip, each dealt 1 card (one card remains unseen).
- **One betting round**, fixed bet size of 1 chip:
  - Player 1 acts first: **check** or **bet**.
  - If P1 checks: P2 may **check** (→ showdown for the 2-chip pot) or **bet**; if P2 bets, P1 may **fold** or **call**.
  - If P1 bets: P2 may **fold** or **call**.
- Showdown: higher card wins the pot.

The full game has exactly **12 information sets** (6 per player: 3 cards × 2 possible histories each) and about 30 tree nodes. You can draw the entire tree on one slide.

The 12 info sets, in the standard notation `card + history`:

| Player 1 | Player 2 |
|---|---|
| `J` (first to act) | `J b` (facing a bet) |
| `Q` (first to act) | `Q b` |
| `K` (first to act) | `K b` |
| `J cb` (checked, now facing bet) | `J c` (facing a check) |
| `Q cb` | `Q c` |
| `K cb` | `K c` |

### The known answer (why this game and not another)

Kuhn poker has an **analytically derived Nash equilibrium** — a one-parameter family, parameterized by α ∈ [0, 1/3] = P1's betting frequency with the Jack:

**Player 1:**
- **J**: bet (bluff) with probability α; if checked-raised after checking, always fold.
- **Q**: always check; if facing a bet after checking, call with probability α + 1/3.
- **K**: bet with probability **3α** (value-bet the nuts more often than you bluff — a 3:1 ratio falls out of the math).

**Player 2 (unique, no free parameter):**
- **J**: facing a bet, always fold. Facing a check, bet (bluff) with probability **1/3**.
- **Q**: facing a bet, call with probability **1/3**. Facing a check, always check.
- **K**: always bet / always call.

**Game value:** Player 1 loses **1/18 chip per hand** (≈ −0.0556) at equilibrium — the game is provably a second-mover advantage.

Three headline numbers your solver should reproduce, each a talking point:
1. **P2 bluffs the Jack exactly 1/3 of the time** — bluffing is not psychology, it's an equilibrium frequency.
2. **P2 calls with the Queen exactly 1/3 of the time** — the "bluff-catching" frequency that makes the opponent's bluffs exactly break-even (indifference principle).
3. **Game value −1/18** — your empirical average payoff over the self-play iterations should converge to it, a second independent check.

Note on the α-family: because P1's equilibrium is a *set* of strategies, the solver may land anywhere in α ∈ [0, 1/3] for P1's Jack-bluff. That itself is a teachable point ("equilibria need not be unique — but P2's response is pinned"). P2's 1/3 numbers are unique and are the ones to headline.

### Why 1/3? The indifference-principle derivations

The equilibrium frequencies aren't arbitrary — they fall out of a single principle: **at equilibrium, your mixing frequencies make the opponent indifferent between their options** (if they weren't indifferent, they'd have a pure best response, and you'd be exploitable). The two headline numbers, derived in a few lines each. Convention: each player antes 1, so folding always nets −1; bet size is 1.

**Derivation A — why P2 calls with Q exactly 1/3 of the time.**
P2's call frequency must make P1's *Jack bluff* exactly break even (indifferent vs. checking).

- P1 checks with J → loses the showdown either way → EV = **−1**.
- P1 bets with J → P2 holds Q or K with equal probability. K always calls (it's the nuts). Say Q calls with probability *c*. Total call probability = ½·1 + ½·c.
  - P2 folds: P1 wins the pot → **+1**.
  - P2 calls: P1 loses ante + bet → **−2**.
  - EV(bet) = (1 − P_call)(+1) + P_call(−2) = 1 − 3·P_call.
- Indifference: 1 − 3·P_call = −1 → **P_call = 2/3** → ½ + c/2 = 2/3 → **c = 1/3**. ∎

Intuition: a 1-chip bluff into a 2-chip pot risks 1 to win 2, so it profits iff it succeeds more than 1/3 of the time. Equilibrium defense makes it succeed *exactly* 1/3 of the time — no more (or bluffs print money), no less (or folds get exploited).

**Derivation B — why P2 bluffs the Jack exactly 1/3 of the time (after P1 checks).**
Mirror image: P2's bluff frequency must make P1's *Queen call* exactly break even.

- P1 checked with Q, P2 bets. P2's betting range: K always (value), J with probability *b* (bluff). P2 checks back Q, so given a bet, P1's Q faces {K, J} with posterior odds 1 : b.
- P1 folds → **−1**. P1 calls → +2 vs. the bluff (wins a 4-chip pot), −2 vs. the K.
- EV(call) = [b/(1+b)]·(+2) + [1/(1+b)]·(−2). Indifference with −1:
  2b − 2 = −(1 + b) → 3b = 1 → **b = 1/3**. ∎

**Bonus — the modern-theory tie-in.** b = 1/3 means P2's *betting range* is {K always, J one-third of the time}, so bluffs make up (1/3)/(1 + 1/3) = **25% of the betting range**. Meanwhile P1's caller gets 3:1 pot odds (call 1 to win 3), i.e. needs exactly 25% equity to call. The bluff fraction *equals* the caller's pot-odds threshold — which is precisely the "bluff-to-value ratio" formula from modern poker theory books, for a half-pot bet. A 1940s toy game and 2020s solver doctrine give the same number; that's a great slide.

(The game value −1/18 follows by summing P1's equilibrium EV over all six equally likely deals — worth verifying empirically rather than deriving by hand.)

### CFR pseudocode (vanilla, chance-sampled)

```
for t in 1..T:
    for each of the 6 deals (or sample one):           # chance sampling
        cfr(root_after_deal, reach_p1=1.0, reach_p2=1.0)

def cfr(node, reach_1, reach_2) -> ev_for_acting_player:
    if node is terminal:
        return payoff(node)

    I = info_set(node)                                  # card + history
    strategy = regret_matching(I.regret_sum)            # normalize positive regrets
    I.strategy_sum += my_reach * strategy               # for the average strategy

    for each action a:
        ev[a] = -cfr(child(node, a), ...update reaches...)   # zero-sum: negate
    node_ev = Σ strategy[a] * ev[a]

    for each action a:                                  # regret update,
        I.regret_sum[a] += opponent_reach * (ev[a] - node_ev)   # weighted by opp reach

    return node_ev

def average_strategy(I):
    return normalize(I.strategy_sum)                    # ← THE output. Not current strategy.
```

Data structure: a dict `info_set_key -> (regret_sum[n_actions], strategy_sum[n_actions])`. For Kuhn that's 12 keys × 2 actions. The whole solver state is ~48 floats.

### One CFR iteration by hand

To make the pseudocode concrete (and to have a debugging reference when implementing), here is the very first iteration traced on one sampled deal: **P1 = Q, P2 = J**. All regrets start at 0, so regret matching returns uniform — every decision is 50/50.

The tree for this deal, with expected values computed bottom-up from P1's perspective:

```
P1 "Q": check or bet                              EV = ½(0.75) + ½(1.5) = +1.125
├─ check → P2 "J c": check or bet                 EV(P1) = ½(+1) + ½(+0.5) = +0.75
│   ├─ check → showdown, Q > J                    P1 +1
│   └─ bet  → P1 "Q cb": fold or call             EV = ½(−1) + ½(+2) = +0.5
│       ├─ fold                                   P1 −1
│       └─ call → showdown, Q > J                 P1 +2
└─ bet  → P2 "J b": fold or call                  EV(P1) = ½(+1) + ½(+2) = +1.5
    ├─ fold                                       P1 +1
    └─ call → showdown, Q > J                     P1 +2
```

Regret update at each info set visited — `regret(a) = reach_opp × (EV(a) − EV(node))`, each from the acting player's own perspective (P2's payoffs are the negation of P1's):

| Info set | Action EVs (actor's view) | Node EV | Regret update | What the bot just "learned" |
|---|---|---|---|---|
| P1 `Q` | check +0.75, bet +1.5 | +1.125 | bet **+0.375**, check −0.375 | "Betting the Q is great!" — an *overreaction* (true only because P2 held the worse card and played randomly); future deals vs. K will punish it |
| P2 `J b` | fold −1, call −2 | −1.5 | fold **+0.25**, call −0.25 (reach ½) | With J facing a bet, fold — already the correct equilibrium play, learned in one sample |
| P2 `J c` | check −1, bet −0.5 | −0.75 | bet **+0.125**, check −0.125 (reach ½) | Bluffing the J after a check looks good (P1 folds half the time with a better hand) — the *birth of the bluff*; later, P1's calls adapt and drive this to exactly 1/3 |
| P1 `Q cb` | fold −1, call +2 | +0.5 | call **+0.375**, fold −0.375 (reach ¼) | Bluff-catch with the Q — correct direction, frequency to be calibrated over time |

Two things worth noticing, because they preview the whole dynamic:

- **Sensible poker emerges after literally one iteration** — fold J to a bet, bluff-catch with Q, try bluffing the J. Nobody told it anything; the regrets did.
- **The overreaction at P1 `Q` is the system working as intended.** Next iteration, regret matching plays "bet Q" at 100%. On deals where P2 holds the K, that gets punished, negative regret accumulates, the strategy swings back. The *current* strategy lurches like this forever; the *average* strategy glides to equilibrium. This is exactly the current-vs-average contrast that direction #4 puts on screen.

### What to build

- `solver/` package (or single module) — **separate from the NLHE engine; don't entangle them.** The toy game defines its own minimal tree; it should not import the engine's deck/betting code.
  - `kuhn.py` — game rules: legal actions, terminal detection, payoffs. (~50 lines)
  - `cfr.py` — the trainer above. (~80 lines)
  - `report.py` — pretty-print the averaged strategy per info set, distance from analytic equilibrium, empirical game value.
- **Convergence tracking:** every N iterations, record (a) max |strategy − analytic| across P2's pinned info sets, (b) running average game value vs. −1/18. Dump as a table or CSV for a convergence chart.
- **Tests as the success criteria** (per the project's goal-driven style):
  - After 100k iterations: P2's `J c` bet-frequency within ±0.02 of 1/3.
  - P2's `Q b` call-frequency within ±0.02 of 1/3.
  - Empirical game value within ±0.005 of −1/18.
  - P1's `K` bet-freq ≈ 3 × P1's `J` bet-freq (the 3:1 value/bluff ratio).

### Showcase moment

```
iter        10 │ P2 with J facing check: bluff 41.2%
iter     1,000 │ P2 with J facing check: bluff 35.8%
iter   100,000 │ P2 with J facing check: bluff 33.4%   → analytic optimum: 33.33%
game value: -0.0553   → analytic: -0.0556 (P1 loses 1/18/hand)
```

The LinkedIn punchline: *"I never told the AI to bluff. It taught itself by playing millions of hands against itself — and independently discovered that bluffing exactly 1/3 of the time is mathematically optimal."* Surprising, provably true, and it demystifies the one thing everyone finds mysterious about poker. Follow-up hook: *"It also discovered you should value-bet 3× as often as you bluff — a ratio pros learn from theory books."*

### Stretch: Leduc poker
6 cards (2 suits × J/Q/K), 2 rounds, a community card, raises allowed — ~288 info sets. Still solves in seconds, looks more like real poker, and pairs (hitting the board) introduce *semi-bluffs*. Good "part 2" material; not needed for the first post.

### Effort
**Low–medium.** ~200–300 lines total, fully self-contained, verifiable against a known answer. The known answer is the whole point: it converts "I wrote a thing" into "I wrote a thing that provably works."

---

## 2. Exploitability Meter — "How Much Is Your Leak Worth?"

### Concept taught
GTO vs. exploitative play, and **exploitability as a measurable number**: how much a perfect opponent (a *best response*) would win against your strategy, in chips per hand. The deep idea: an equilibrium strategy is exactly the strategy whose exploitability is zero — "GTO" is not a style, it's a fixed point.

### The math, concretely

- Fix a strategy σ for one player. The opponent's **best response** BR(σ) is computed by a single recursive walk of the game tree: at opponent decision nodes take the max-EV action; at σ's nodes weight children by σ's action probabilities; at chance nodes weight by card probabilities. No learning loop — it's exact and instant on a toy tree.
- **Exploitability of σ** = (value BR extracts against σ) − (game value at equilibrium). For a two-player zero-sum game the standard symmetric measure is:
  `exploitability(σ) = ½ [ u₂(σ₁, BR(σ₁)) + u₁(BR(σ₂), σ₂) ] − game value`
  For Kuhn, report it simply as **chips per hand above the −1/18 baseline**; scale ×100 for the poker-familiar "per 100 hands" framing.
- Worked example (classic): if P2 *never* calls a bet with the Queen (instead of calling 1/3), P1's best response bluffs every Jack — and P2's guaranteed loss grows measurably beyond 1/18. The meter turns "you fold too much" into a number.

### Measuring a *human's* strategy
A human doesn't hand you σ — you estimate it from observed frequencies:
- Track, per info set, the empirical action frequencies over the session (e.g. "with Q facing a bet: called 2 of 9 times → call freq 22%").
- Feed the empirical σ̂ into the best-response calculator → live exploitability estimate.
- **Honest caveat to display:** small samples are noisy. Show hands-observed per info set and widen/flag the estimate until each key info set has, say, 15–20 observations. (In Kuhn only 12 info sets exist, so sessions of 100–200 hands are already meaningful — this is another reason toy games are the right vehicle.)

### What to build
- `best_response.py` — the recursive max-EV walk against a fixed strategy (~60 lines). Also reusable as an *internal check on #1*: exploitability of the solver's average strategy should trend → 0, which is the rigorous convergence metric.
- A **play mode**: human vs. the equilibrium bot from #1, in the existing terminal UI. After each hand (or every 10), refresh a panel:

```
┌─ LEAK REPORT ──────────────────────────────────────┐
│ hands: 120                                          │
│ your exploitability:  +0.14 chips/hand  (GTO: 0.00) │
│                                                     │
│ biggest leak: with Q facing bet you call 11%        │
│   (optimal 33%) → a perfect opponent bluffs you     │
│   relentlessly: worth 9 chips per 100 hands         │
└─────────────────────────────────────────────────────┘
```

- The "biggest leak" line falls out naturally: compute exploitability with each info set individually corrected to optimal; the info set whose correction recovers the most EV is the biggest leak. (12 info sets → 12 recomputes → instant.)

### Showcase moment
A player thinks they're playing fine; the meter quantifies the cost of their predictability in real time — and names the leak. The visceral lesson: **being predictable has a price, and the price is computable.** This is the most *interactive* of the four — the only one where the viewer imagines themselves playing it. Good demo-video material: play 50 hands on camera, watch your own leak report.

### Effort
**Medium**, and it depends on #1 (same tree, same info-set infrastructure). The best-response walk itself is easy; the polish is in the frequency tracking + presentation. Natural phase two.

---

## 3. Strategy Tournament — "Which Personality Wins?"

### Concept taught
Dominance and intransitivity of strategies, evolutionary stability, and the core game-theoretic insight that **no strategy is best in isolation — it depends on the field**. Poker styles form a rock-paper-scissors structure; equilibrium play is the strategy that refuses to be anyone's food.

### How it works
Define a roster of pure archetypes and run round-robin matches over many hands, tracking chip flow per matchup pair. **This is the direction that reuses the most existing work** — the engine's bot archetypes, difficulty system, and push/fold logic become the tournament roster. Little new game-theory math; mostly orchestration and presentation.

Suggested roster (each one sentence to explain, which matters for the post):
- **Maniac** — bets/raises with everything.
- **Rock** — only plays premium hands, never bluffs.
- **Calling station** — rarely folds, rarely raises.
- **TAG** (tight-aggressive) — the "textbook human" baseline.
- **GTO-approx** — the closest thing the engine has to balanced play (or, if #1 is built and matches are run on Kuhn, the actual equilibrium bot — see design choice below).

**Design choice to make up front:** run the tournament on (a) the full NLHE engine with existing archetypes — richer, more impressive, but results are noisy and nothing is provable; or (b) Kuhn/Leduc with scripted styles + the #1 equilibrium bot — cleaner story ("the equilibrium strategy is the only one with no losing matchup, *as theory predicts*"). Option (a) is the fastest standalone build; option (b) makes #3 a corollary of #1. Could do (a) first, (b) as the kicker.

### Variance control (what makes results credible)
Poker is high-variance; a naive 1,000-hand match can crown the wrong winner. Two cheap standard tricks:
- **Lots of hands**: 50k–100k per matchup — trivial for bots, seconds of runtime.
- **Duplicate/mirrored deals**: play each deal twice with hole cards swapped between the bots, then sum. Kills most card-luck variance; one paragraph of code, and mentioning it signals rigor.
- Report **mbb/hand or chips/100 with a confidence band**, not raw chip totals.

### The evolutionary stretch: replicator dynamics
Give each archetype a population share pᵢ (start uniform). Each generation:
1. Expected payoff of archetype i against the field: `fᵢ = Σⱼ pⱼ · payoff(i vs j)` (from the matchup matrix — no re-simulation needed).
2. Update shares: `pᵢ ← pᵢ · (fᵢ − f_min + ε) / normalizer` (or the standard replicator form `ṗᵢ ∝ pᵢ(fᵢ − f̄)`).
3. Print the population bar chart per generation.

Expected story arc, which is genuinely fun to watch: maniacs feast on rocks early → calling stations rise to eat the maniacs → the field tightens → balanced/TAG/GTO strategies quietly take over. **Ecosystem dynamics from a payoff matrix** — this is textbook evolutionary game theory, driven entirely by data your tournament already produced.

### What to build
- `tournament.py` — seat pairings, N hands per matchup with mirrored deals, chip-flow accounting.
- Terminal **heatmap matrix**: rows = hero, cols = villain, cell = chips/100 (green positive, red negative). ANSI 256-color blocks are enough.
- `evolve.py` — the ~30-line replicator loop over the saved matrix + a per-generation stacked population bar.

```
chips/100 (row vs col)   MAN    ROCK    STN    TAG    GTO
MANIAC                    —    +42.1  -18.3   -9.6   -7.2
ROCK                   -42.1     —     +6.4   -3.1   -2.8
STATION                +18.3   -6.4     —    -11.9   -8.5
TAG                     +9.6   +3.1  +11.9     —     -1.4
GTO-approx              +7.2   +2.8   +8.5   +1.4     —
```

(Illustrative numbers — the real matrix is the deliverable.) The GTO row being all-positive-but-small vs. the maniac/rock rows being huge-swing is the visual argument.

### Showcase moment
Two artifacts: the **heatmap screenshot** (rock-paper-scissors made visible in one image) and the **evolution gif** (population shares shifting generation by generation until balance wins). The evolution gif is arguably the second-best animation of the whole project after #4.

### Effort
**Low–medium.** Best visual payoff per line of code, and the only direction fully standalone from #1. Weakness: the core insight ("styles counter each other") is interesting but not *surprising* — weaker hook than #1's bluff discovery. Strongest as a *follow-up post* once #1 established credibility.

---

## 4. Regret Visualization — "The Machinery of Learning, On Screen"

### Concept taught
The *mechanism* underneath equilibrium-finding — **regret matching** — rather than just the converged answer. Everyone posts results; showing the *learning signal itself* is what makes this distinctive.

### What exactly to show
For 2–3 hand-picked info sets (the stars: P2's `J c` bluff decision and P2's `Q b` bluff-catch decision), render live as the #1 solver runs:

1. **Cumulative regret bars** per action — the raw learning signal. Early: large, jittery, sign-flipping. Late: the relative gap stabilizes.
2. **Current strategy** (regret-matched probabilities) — twitchy forever; instructive *because* it never settles.
3. **Average strategy** — the thing that actually converges; drawn with a target line at the analytic optimum (33.3%).
4. A **sparkline** of average-strategy history, so the convergence curve is visible in one glance.

The pedagogical core is the **contrast between (2) and (3)**: current strategy dances, average strategy glides into the target. That contrast *is* CFR's convergence theorem, rendered.

```
 P2: J, opponent checked            iter 38,400
 ─────────────────────────────────────────────
 regret   BET   ████████████░░░░░░░  +214.6
          CHECK ██░░░░░░░░░░░░░░░░░   +41.2
 current  bet 83.9%                       ▲ twitchy
 average  bet 33.6%  ▁▂▄▆▅▄▄▃▃▃▃▃▃  → target 33.3%
```

### What to build
- `viz.py` — a render layer over #1's solver state. The solver exposes a snapshot callback every N iterations; viz redraws with ANSI cursor moves (or plain full-screen reprint at ~10 fps — fine at terminal sizes). No new theory; strictly a view.
- **Pacing control** — the whole solve takes <1s at full speed, which is *bad* for a demo. Add a throttle (iterations/second) so convergence takes a watchable ~20–30 seconds: chaos → oscillation → lock-on. The narrative arc is the product.
- **Recording:** asciinema or terminalizer → gif/mp4 for the post. Design for a ~15–20 s clip with the target line visibly getting hit at the end.
- Optional: matplotlib convergence chart (avg strategy vs. iterations, log-x) as the "serious" static figure accompanying the fun gif.

### Showcase moment
An animated terminal gif of bars settling onto the 33.3% line — *"this is what an AI teaching itself to bluff looks like."* The most visually distinctive artifact of the four, but it's a **companion to #1, not standalone** — without the solver it has no data, and without #1's provable claim it's just "bars moving."

### Effort
**Low**, given #1 exists. It's a view over ~48 floats of solver state. Most of the work is taste: pacing, layout, recording.

---

## Comparison

| Direction | Concept clarity | Visual payoff | Standalone? | Effort | Hook strength |
|---|---|---|---|---|---|
| 1. Toy solver | ★★★ (provable) | ★★ | Yes | Low–Med | ★★★ — the 1/3-bluff sentence |
| 2. Exploitability | ★★ | ★★ | No (needs #1) | Med | ★★ — "your leak costs X"; most interactive |
| 3. Tournament | ★★ | ★★★ | Yes | Low–Med | ★ — fun, not surprising; great follow-up |
| 4. Regret viz | ★★ | ★★★ | No (needs #1) | Low | (amplifies #1's hook) |

## Recommendation & suggested roadmap

**Build #1 as the foundation, bolt on #4 as its visualization. Ship those together as the first post.**

- The gif (#4) stops the scroll; the provable claim (#1) makes people stay and comment.
- The combo is self-contained and explainable end-to-end — it reads as "this person understands the theory," not "this person wired up a library." That's the real reputational payoff.

Sequenced roadmap, each phase independently shippable:

1. **Phase 1 — Kuhn + CFR core** (#1). Success: tests pass against the analytic equilibrium (1/3 frequencies, −1/18 game value, 3:1 value/bluff ratio).
2. **Phase 2 — Regret viz + recording** (#4). Success: a 15–20 s gif showing convergence onto the 33.3% target line.
3. **Phase 3 — Best response + leak report** (#2). Success: exploitability of the solver's own average strategy trends → 0 (this doubles as the rigorous proof of Phase 1); human play mode with live leak report.
4. **Phase 4 — Tournament + evolution** (#3). Success: matchup heatmap with variance controls; replicator-dynamics gif. Runs on the existing NLHE archetypes and/or the Kuhn bots.

Each later phase also upgrades the earlier ones (Phase 3's best response is the honest convergence metric for Phase 1; Phase 4's GTO row is the payoff of Phase 1's equilibrium bot). Four phases ≈ four LinkedIn posts, escalating from "provable result" → "watch it learn" → "play against it and see your leaks" → "poker ecosystem evolution."

## Presentation surface: terminal vs. web (open decision)

The doc so far assumes terminal + recorded gifs. But the project now has a browser client (`web/`) and a game-theory showcase page already in progress (`showcase/poker_game_theory.html`) — so there is a real choice here, and it affects Phases 2 and 4.

**Option A — terminal gifs (asciinema/terminalizer):**
- Feed-native: autoplays in the LinkedIn feed, zero friction, nobody has to click anything.
- The terminal aesthetic reads as authentic engineering, not a product ad.
- But it's passive — viewers watch one pre-recorded run.

**Option B — interactive web page (extend the showcase page):**
- Regret bars with an **iteration slider** ("scrub through the AI learning to bluff"), play-against-GTO with a live leak meter (#2), evolution animation with a restart button (#4/#3).
- "Try it yourself" is a much deeper engagement than a gif — and Kuhn CFR is small enough (~100 lines) to implement directly in browser JS, so the page can *re-solve live*, no backend needed. Alternatively: keep the solver in Python and precompute a snapshot log to static JSON; the page just plays it back. Either way it can be a static page (GitHub Pages), no `api/server.py` dependency.
- But: LinkedIn's algorithm penalizes external links in the post body, and a link is a click most scrollers won't make.

**Resolution — don't choose; structure for both:**
1. Make the solver emit a **serializable snapshot log** (per-info-set regrets + current + average strategy, every N iterations, as JSON). This costs almost nothing in Phase 1.
2. Terminal viz (Phase 2) and web viz both become thin *consumers of the same snapshot data* — the decision stops being architectural and becomes purely about presentation order.
3. For the post itself, the standard playbook: **gif in the post** (stops the scroll, feed-native) **+ interactive page linked in the first comment** ("play with it yourself"). Best of both, and the algorithm penalty applies only weakly to comment links.

Concrete implication for the roadmap: Phase 1 gains a "snapshot log to JSON" requirement (trivial); Phase 2 stays terminal-first; a "Phase 2b — interactive web version on the showcase page" slots in whenever it's worth the polish.

## Presentation notes (for later)

- Lead with the sentence, not the tech: bluffing-as-math is the hook; CFR is the appendix.
- One gif per post, ≤20 s, terminal aesthetic is a feature — it reads as authentic engineering, not a product ad.
- Always show the target line / analytic answer in visuals: "matches theory" is the differentiator over every other "I trained a bot" post.
- Repo README should mirror this doc's structure: claim → demo gif → how it works → run it yourself.

## Reference pointers

- Pluribus paper: [Superhuman AI for multiplayer poker (Science, 2019)](https://noambrown.com/papers/19-Science-Superhuman.pdf)
- CFR walkthrough with code: [Counterfactual Regret Minimization for Poker AI — Int8](https://int8.io/counterfactual-regret-minimization-for-poker-ai/)
- The standard practical intro: Neller & Lanctot, *An Introduction to Counterfactual Regret Minimization* (2013) — Kuhn poker worked example, the classic starting point.
- Kuhn poker equilibrium: analytic solution summarized above (α-family for P1; unique 1/3 frequencies for P2; game value −1/18).
