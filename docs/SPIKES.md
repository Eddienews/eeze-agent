# F0 — Spike results (M0 gate)

Date: 2026-09-18 · Machine: Windows 11 (user session) · cua-driver 0.28.1 · typesafe-sdk 0.6.0 · model `jev-1.13.0`

## Verdict: **GO** on the loop thesis

The mechanism-level claims all held in live runs: Jev makes clean, calibrated
closed-set decisions; the driver performs launch → capture → input in the background
**without ever taking focus**; the integrated loop succeeded 10/10 with negligible cost.
Latency is dominated by UIA captures (driver), not by Jev.

| Metric | Measured |
| --- | --- |
| Jev call latency (batched questions) | median **133–165 ms** (p50 across runs) |
| Jev cost | ~$0.00004 per call / **~$0.00007 per loop cycle** (2 calls, ~1.7k tokens) |
| Loop cycle (full O→D→A→V) | **p50 3 994 ms · p95 4 133 ms** (N=10) |
| Loop success rate | **10/10** (Python exact-match + Jev `noul` ≥ 0.5) |
| Focus steals during the entire run | **0** (active app stayed "Hermes" throughout) |
| Driver: capture | ~1.4 s (32 elements, Notepad) |
| Driver: input action | ~0.5–0.6 s |
| Driver: app launch (cold, packaged app) | 10–13 s → avoid; assume-running/launch-once |

## S1 — Jev live (`spikes/spike_jev.py`)

3 batched calls (3 typed questions each) over a canned Notepad Save-as state:

- Latencies: 175.2 / 130.2 / 132.7 ms → **median 132.7 ms**
- Usage: 777 input tokens, 126 output (free) → **$0.0000326/call**
- Answers behaved as designed: `select_element` → `none_match` (0.71, ambiguous fixture by
  design), `step_done` 0.21, `blocker` → none. No schema errors, no refusals.
- Quirk: `client.models.list()` returns a `ListModelsResponse` that is not directly
  iterable — handle `.data` or print `str()` (fixed in the spike).

## S2 — Driver round trip (`spikes/spike_driver.py`)

Notepad (Win11 packaged app, `Microsoft.WindowsNotepad_8wekyb3d8bbwe!App`):

- `launch_app` with `active: false` — the launched window never takes focus.
- `get_window_state`: 32 elements, not degraded; includes `snapshot_id`,
  `screenshot_png_b64`, `window_bounds`. Window was even positioned **off-screen**
  (negative desktop coords) and capture/input still worked.
- `click` by `element_token` (background): ~0.52–0.62 s, `effect: unverifiable`,
  `route: synthetic_events` — fine.
- `type_text` by `element_token`: `effect: confirmed`, `route: accessibility`,
  evidence `value_readback` — text landed, status bar read "24 characters".
- Focus check: `active_before` = `active_after` = **Hermes**. The real cursor was
  never moved by the driver (observed cursor deltas were user activity; element and
  background actions do not move the pointer).

## S3 — Mini loop (`spikes/mini_loop.py`)

10 iterations of: fresh capture → Jev `Choice` (which element receives the input?) →
`set_value`/`type_text` on the chosen `element_token` → fresh capture → Jev `Noul`
("content is exactly the token?").

- Element selection: **c0/Document, confidence 1.0, 10/10**
- Writes: exact-content replace confirmed by fresh capture every time; status bar "16 characters"
- Verify `noul`: 0.94–0.97 (confident yes)
- Summary: **success 10/10 · cycle p50 3 994 ms · p95 4 133 ms · Jev p50 165 ms
  (20 calls) · 17 343 input tokens total · $0.0007284 total (~$0.00007/cycle)**
- A variant run with `type_text` (insert semantics) plus an "exactly equals" verify
  question showed the loop mechanics work but the verify *wording* must match the
  action's real semantics (insert ⇒ ask "contains", replace ⇒ ask "exactly").
  Jev answered each variant *correctly* for its input.

## Driver contract findings (for the F1 adapter)

1. **Element addressing**: pass `element_token` (or `snapshot_id` + `element_index`);
   a bare `element_index` is refused (`snapshot_id_required`).
2. **Token lifetime**: any new `get_window_state` of the same `(pid, window_id)`
   invalidates previous tokens (`stale_element_token`). Rule: capture → act immediately.
3. **`type_text` = insert** (typing at caret; empty→"AAA", then "BBB" → "AAABBB").
   **`set_value` = replace** (full content; "AAABBB" → "CCC"). `set_value` reports
   `effect: "unverifiable"` on Win11 Notepad even when it works — confirm with a fresh
   capture (the value is readable from the Document element's `value` field).
4. **Packaged apps (Win11)**: launch by `name` resolves via `shell:AppsFolder`; the
   `aumid` fallback (`..._8wekyb3d8bbwe!App`) also works. Cold launch is slow
   (10–13 s) — do not relaunch per cycle.
5. **Captures work for off-screen windows** — background automation does not require
   windows to be visible on the current desktop.
6. Quirk: `get_window_state` with a tiny `max_elements` (e.g. 5) returned `degraded:
   true` with `ax_tree_empty` on an Electron app (Hermes, 736 elements uncapped).
   Investigate before relying on aggressive caps; F1 will use `query`/`max_depth`
   projections instead.
7. `hotkey` with `{pid, keys}` was refused — payload shape TBD (not needed for M0;
   `set_value` covers exact-content needs for now).
8. cua-driver 0.28.2 is available (we run 0.28.1) — update in the F1 kickoff.

## Open items carried into F1

- Generalize beyond a single app & single action type: clicks, menus, dialogs,
  save-file flows, degraded-capture escalation (px → foreground → vision LLM).
- Cut cycle latency: the two UIA captures (~2.8 s) are 70% of the cycle. Try
  `query` projections, `max_depth`, and skipping the second full capture when the
  action effect is already `confirmed` with read-back evidence.
- Judgment eval set (labeled states) + threshold tuning per question; pin `jev-1.13`.
- Cosmetic: `uv` prints "Failed to set cwd to temp dir" on this shell — harmless.

## Evidence (local, gitignored)

- `spikes/out/mini_loop_report.json` · `spikes/out/driver_report.json`
- `spikes/out/notepad_loop.png` (last iteration, token visible) · `notepad_1/2.png`, `notepad_probe.png`

---

# Incident log — 2026-09-18 · the "v-storm" (external input during F1 runs)

Append-only record per directive. Full evidence: `artifacts/incidents/20260918-v-storm.md`
+ `artifacts/incidents/vstorm_probe.json`.

## Timeline (batch 1, runset `20260918-023044`, times UTC)

| Time | Evidence | Readback value |
| --- | --- | --- |
| 06:33:47 | run 6 · `set_value` readback | `vvvv…(25) + eeze-f1-6-f6f3` |
| 06:33:53–06:34:06 | rungs 2–4 readbacks | `vvvv…` (no token) |
| 06:35:01 | attempt 2 · `set_value` readback | `vvvv…(40) + token` |
| 06:36:05 | attempt 3 · `set_value` readback | **clean (`eeze-f1-6-f6f3`)** |
| 06:36:24 | rung readback | `vvvv…` again (storm resumed) |
| 06:37:17 | run 6 ended | fail after 217 s |
| 06:37:47+ | runs 7–9 | clean, pass |

Synthetic input (landed while the window was **not** focused — a physical keyboard
cannot do that). Live watcher probe at ~07:12 UTC: **zero growth over 40 s** (not
flowing). Source not identified with certainty (resident synthetic-input candidates:
OpenAI Codex `codex-computer-use-swift.exe`, an "AlessandraBeta" app-host); bounded
and closed per directive — the gate makes the source non-blocking.

## The fix: state-consistency gate (implemented, `--isolated` support)

1. Text ladder readbacks classified `ok | noop | append | foreign_mutation |
   unexpected_change`; unexplained mutations emit `external_input_detected`
   (new journal event kind) and abort the run — no blind retries.
2. Interference runs stop immediately, are excluded from the success metric, and are
   reported separately (`interference_runs`, `success_rate_all_runs`); 3 consecutive
   interference runs abort the set.
3. `state_sig` fingerprints around non-text actions (evidence-only; click attribution
   deliberately deferred to F2's expectations work).
4. Isolation (`eeze run --isolated`): single fresh window, empty untitled doc,
   session-store reset if Win11 Notepad restored tabs; `isolation_check` pre-run event.

## Clean 20-run with the gate

[filled after the gated isolated run]

## Contract additions discovered along the way

- `window_minimized`: clicks refused (even on the Maximize button); `set_window_frame`
  refuses → sanctioned recovery `bring_to_front` (recovery-only activation).
- Win11 Notepad session restore resurrects prior tabs as window stubs → deterministic
  window pick (on-screen · not-minimized · largest area); store reset = move
  `TabState`/`WindowState` aside (never delete).
