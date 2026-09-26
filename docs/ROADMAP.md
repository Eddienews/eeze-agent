# Eeze Agent — Roadmap

Estimates re-baselined after F0. Status: ⏳ in progress · ✅ done · ⬜ not started.
The dated phase entries below are **historical checkpoints**, not the current
runtime status; later phases supersede earlier "not yet" statements. Current
read-only snapshot (2026-09-25 23:07 EDT / 2026-09-26 UTC): local daemon
`running:false`, `responding:false`; three routines enabled with next due
2026-09-26 08:00 local (they will not run while the daemon is stopped);
two old non-resumable pending approvals `ap-e99e021f30` and `ap-ddb6e39e7b`
(September 24 invoice routine remains `needs_approval`). The day-19 invoice
approval `ap-cedbf1f720` was resolved on September 23, email `sent:true`.
Seven-day report: **24/29** run outcomes, five failures, zero interference;
not a lifetime or uninterrupted-pilot figure. SQLite `quick_check=ok`.
No service restart, approval decision or new Mission was part of this refresh.
Current capability inventory and gaps: `docs/CAPABILITIES.md`;
decision-ready summary: `docs/PROJECT-REPORT.md` §0a/§4.

| Phase | Focus | Exit milestone | Status |
| --- | --- | --- | --- |
| F0 (2–3 d) | Foundations + risk spikes | ✅ **done 2026-09-18 — M0: GO**. Loop p50 3 994 ms, success 10/10, ~$0.00007/cycle; numbers + driver contract in `docs/SPIKES.md` | ✅ |
| F1 (~1 w) | Walking skeleton | ✅ **done 2026-09-18**. `eeze run` executes the Notepad save-as task end-to-end — **final gated+isolated set: 20/20 runs** (0 interference events, 2 minimize-recoveries, 1 retry), 5/5 steps, code↔Jev agreement 20/20, ≈$0.00073/run. Write ladder + window recovery + state-consistency gate in code; details in `docs/F1-REPORT.md` | ✅ |
| F1.5 (0.5 d) | Read-only API slice + input tooling | ✅ **done 2026-09-18**. Live: GET `/agents`, `/agents/{id}`, `/runs`, `/runs/{id}`, `/system/status`, `/approvals` (stub) via `uv run eeze api`; `eeze doctor input` (`tools/diagnose_input.py`); coexistence section in `docs/ARCHITECTURE.md`. Contract `docs/API.md`, 6 contract tests green | ✅ |
| E1 (0.5 d) | First vertical: invoices (PDFs → verified ledger + anomalies) | ✅ **done 2026-09-18** (`ddf7467`). `eeze invoices`: 10/10 synthetic files, all 5 planted anomalies caught (duplicate pair, missing due, overdue, no-text-layer), 5 clean rows fully quote-verified, 28/28 tests, ruff clean; literal values + derived `*_iso` columns (`docs/DEVELOPMENT.md`) | ✅ |
| E2 (0.5 d) | Gmail read-only (inbox → PDFs → E1 pipeline) | ✅ **done 2026-09-18** (`adaa69e`). `eeze inbox pull` live-verified on a real account: 40 messages, 3 attachments pulled, extraction 2 ok / 1 flagged, all quote-verified; readonly mailbox + BODY.PEEK (nothing marked seen); folder names with spaces quoted | ✅ |
| F2 (~1 w) | System 2 planner + risk classes + approvals | ✅ **done 2026-09-18**. M0 risk gate (6 classes, heuristic floor, policy) · M1 approvals store/API/resume (`~/.eeze/eeze.db`, token-gated writes, grants with TTL/revoke) · M2 `eeze goal` planner with bounded replan (live: NL goal → file saved; honest verify failure → replan → 1/1) · M3 real `/approvals` UI (live: goal paused → clicked Approve in the browser → resumed → `1/1 done`). 64/64 tests, ruff clean — `docs/F2-REPORT.md` | ✅ |
| F3 (~1 w) | Memory + audit | any run fully reconstructable; replay reproduces actions | ✅ **done 2026-09-18** (`docs/F3-REPORT.md`): runset snapshots (task verbatim + run_meta at start), `eeze audit export` bundles (normalized audit.json + REPORT.md + hashes + copies; old runsets degrade to explicit warnings), and `eeze replay` — archived task re-run with a fresh brain + per-step diff (`replay.json`); live: export of a gated runset + **REPLAY: MATCH** (2/2 steps) |
| F4 (1–2 w) | First vertical routine + scheduler | routine runs unattended on schedule; async approval round-trip | ✅ **done 2026-09-18** (`docs/F4-REPORT.md`): scheduled invoices routine (Gmail → verified ledger → **gated** email summary) ran end-to-end; scheduler fired unattended and paused at the gate, approved via UI, resumed `1/1`; routines CLI + run records (`routines`, `routine_runs`); skip-if-open guard |
| F5 (1–2 w) | Control plane UX + installer | a non-technical person installs and runs it; zero focus-steal audit | ✅ **done 2026-09-18** (`docs/F5-REPORT.md`): `/routines` page (create/toggle/run/history/remove, token-gated API), first-run wizard `/setup` (system check → Gmail connect with live probe → first routine; `.env` written server-side, never echoed), one-click installer `install.cmd`/`scripts/install.ps1` (uv bootstrap, shortcuts, autostart, idempotent), and the **zero focus-steal audit PASSED live** (107 samples, 0 focus changes, 0 cursor moves) |
| F6 (2+ w) | Hardening + pilot | pilot user running daily ≥ 1 week; security checklist signed; metrics report | 🔄 **in progress** — M0 done 2026-09-18: loopback bind, `eeze report` and checklist. PyMuPDF licensing and frontend lint gaps were closed by September 23; checklist item 12 (continuous pilot week) and final sign-off remain open. September 19 approval was later resolved; a different September 24 invoice run is blocked on a non-resumable legacy approval. At this refresh the daemon was down. See `docs/F6-SECURITY-CHECKLIST.md` and current snapshot above. |

## v2 — office of bots (2026-09-18, between F6/M0 and the pilot)

Same-day block: pluggable brains (`LlmBrain` + `make_brain`), named agents with per-agent
policy and brain (`agents.yaml` → default/finance/ops), full agents CRUD from the UI
(wizard create with brain picker, edit dialog incl. overrides of built-ins, remove; user
file `~/.eeze/agents.yaml` merged over the repo file), approval notifications (daemon
watcher → Windows toast via PowerShell/WinRT, deduped, toggle in UI), honest live UI on
every route (agent detail, run viewer showing the REAL per-step captures, Settings page
with runtime/keys/paths — no mock numbers anywhere in live mode). Commits: `fcda9af`,
`6f1790d`, `c170c72`, `666858a`, `fdd059b`, `1a7c262`.

## Script/tool layer — creative verticals (2026-09-23)

`run_script` step action: one shell command per step (cmd.exe on Windows), cwd default =
the run's own dir (`{run_dir}` var), hard `timeout_s` that kills the whole process tree,
full stdout/stderr to `run-NN/step-<id>.log`, exit code + duration + artifacts in the
journal. Auto-classified `install_exec` (gated unless policy/grant/`--allow install_exec`);
command-text heuristics can only raise the class. Tasks with `app: ""` need no window, and
`verify_jev` is skipped with a journal note there (`verify_code` stays fully supported —
`file_exists` + new `file_size_gt`). Proven live with a real ffmpeg 9.0.2 build:
`tasks/video-card.yaml` → gated pause → API approve (`grant scope=task`) → auto-resume
`1/1` with real artifacts (`card.mp4` h264 720×720×75f = 3.0 s; `poster.png`); grant path
re-run `1/1`. 135/135 tests, ruff clean. Commit: `run_script` block.

Also fixed live during this block (found by a GUI regression run): the Jev state sent
unbounded element values — a session-restored Notepad tab with a big document produced
`max_tokens_exceeded` (HTTP 400). `build_state` now caps each value (1000 chars + explicit
marker); deterministic checks still read the raw capture.

## C1 — Video editing vertical (2026-09-23)

Spec-driven EDITING on top of the script layer: `uv run eeze video <spec.yaml> [--out DIR]`
(`src/eeze_agent/verticals/video/`: probe · spec · ops · runner). Ops: `still_to_video`,
`trim`, `scale`, `fps`, `concat` (inputs normalized to one size/fps/sar + h264/aac; silent
sources get an anullsrc track) and `thumbnail`. Every step's output is probed and compared
against the op's declared expectations — duration within max(0.15 s, 5%), exact size/fps,
stream presence, non-empty file; a mismatch FAILS the step and the rest are marked
`skipped` (no silent passes). Artifacts: final file (+ `output` may name the step whose
result is the deliverable), `work/NN-<id>.*` intermediates, `report.md` (expected vs
observed per step), `edit-report.json`, `summary.json`; CLI exit ≠ 0 when any step failed.

Live: `specs/teaser-edit.yaml` (mascot still 2 s + a 2 s cut of raw footage → scale →
concat → cover frame) — 5/5 steps, `mascot-teaser.mp4` (h264+aac, 480×480, 25 fps,
4.063 s, 141 411 B, sha256 `e209c136…`) + cover 480×480 PNG (verified visually). Agent
path: `tasks/video-edit-agent.yaml` (gated `install_exec` → API approve `grant scope=task`
→ auto-resume) → `done 1/1`, `$0.0` (script steps make zero brain calls), byte-identical
output to the CLI run. 142/142 tests, ruff clean. Commit: C1 block.

Two live-found pitfalls (each now locked by a test): (1) `-t` must be an OUTPUT option
whenever an anullsrc input is in play — `-shortest` overshoots and a 0.6 s silent clip
came out 0.998 s at container level; (2) concat list entries must be ABSOLUTE — the
demuxer resolves relative entries against the LIST FILE's directory, so a relative
`--out` produced `work/artifacts/.../work/…-norm1.mp4` and failed honestly. Limits: the
op set is fixed (no overlays/transitions/text/audio mixing), no GPU encoders, and the
brain does not write specs yet (C2 knowledge pack).

## C2 — 3D vertical on Blender headless (2026-09-23)

`uv run eeze 3d <spec.yaml> [--out DIR] [--blender PATH] [--timeout S]` — a declarative
scene (primitives/text + transforms/materials, one camera with optional orbit, lights,
world, render settings) and the artifact steps: `render_still`, `render_animation`,
`save_blend`, `export_glb`. ONE Blender process per run (a cold headless EEVEE start
measured ~36 s): the generated `work/run_blender.py` (+ `work/scene.json`) builds the scene
once, runs every step and prints machine-readable per-step lines; the runner verifies each
artifact for real — existence/size, `.blend` header (plain or zstd), GLB magic `glTF`, PNG
facts and MP4 duration/fps/size via ffprobe — and reports FAILED with the measured reason
otherwise. Differences from C1: steps are independent outputs of one scene, so there is no
`skipped` cascade; `blender.log` (stdout+stderr of the whole run) is kept beside the script.

Live: `specs/brand-3d.yaml` (wordmark + ring + floor, orbiting camera, Blender 5.2.2 LTS) —
**4/4 steps in 16.3 s** → still PNG 480×480 (259 239 B), turntable MP4 h264 480×480 2.0 s
12 fps (92 179 B), `.blend` zstd (186 855 B), `.glb` (481 364 B); deliverable sha256
`3a6d8eb9…`, verified visually (wordmark readable facing the camera across the orbit).
Agent path: `tasks/render3d-agent.yaml` (script-only, gated `install_exec`) → approve
`grant scope=task` → `done 1/1`, `$0.0`; the render is pixel-identical to the CLI run
(decoded-stream md5 `e3d00103…` on both — the file hash differs only by the container's
`date` tag, so prefer the decoded md5 for MP4 identity). Limits: declarative vocabulary only
(no mesh import/modeling), one process per run, engine set depends on the build.

Blender 5.x API facts paid for live (each encoded in the generated script): engines list is
`BLENDER_EEVEE` (+ WORKBENCH/CYCLES assignable); `file_format = "FFMPEG"` only exists after
`image_settings.media_type = "VIDEO"`; `.blend` saves are zstd by default; `Action.fcurves`
is gone in 4.4+ slotted actions (keyframe interpolation now set via
`preferences.edit.keyframe_new_interpolation_type`); an FFMPEG render ignores a `.mp4`
filepath unless `use_file_extension = False`; the orbit starts at the spec camera's own
azimuth (a hard-coded start angle shot the back of the wordmark in the first demo run).

## Model router (2026-09-23)

Founder policy: DeepSeek retired; `routine` → `openai/gpt-6-luna`, `hard` → `openai/gpt-6-sol`.
`brains/router.py` decides per run — pin > `agents.yaml model.tier` > escalation (a failed run
moves one tier up, capped) > Jev's typed Choice > the deterministic rules floor (also the
logged fallback for every refusal/error). Every run journals `model_route`; `summary.models`
carries per-model calls/tokens/cost (`core/pricing.py`). Live: Jev 4/4 correct in the probe
(~$0.000023/decision); same 5-step Notepad task — Sol $0.023178 vs **Luna $0.0011988**, both
`done`; escalation proven with a deliberately failing task (`model_escalated` in the journal).
Design + numbers: `docs/ROUTER.md`. Not yet: per-cycle routing, an extractor/image tier (the
invoice extractor deliberately keeps riding the local Hermes gateway), and the OpenRouter
cached-input discount.

## C3 — The brain writes the specs (2026-09-23)

`brains/specwriter.py` + `uv run eeze spec <video|3d> "<goal>" [--sources DIR] [--out DIR] [--run]`:
the vocabulary comes from the verticals' code (`verticals/*/vocab.py`, test-locked against the
validators), the reply is validated by the vertical's own pydantic model, feasibility is checked
against real ffprobe facts (exact paths, kinds, trims past the end), every rejection goes back to
the model (≤3 attempts, recorded in `write-report.json`) and the run is the vertical's, with its
per-step verification. Writer model: `EEZE_SPEC_MODEL` → `EEZE_PLANNER_MODEL` (hard tier by
policy). Live: video goal 6/6 → 4.083 s MP4 at 24 fps (Sol, 1 attempt, $0.003193); 3D goal 3/3 →
2.52 s MP4 + PNG + GLB (Sol, 1 attempt, $0.003364); agent task `tasks/creative-goal-agent.yaml`
gated → `done 1/1`. Numbers + the live-caught sources-path bug: `docs/C3-REPORT.md`.
Not yet: photo/image verticals, mesh import, a router decision for the write itself, and the
loop's cost rollup seeing the child process's LLM spend.

## OSS engine named Baton (2026-09-23)

The naming round that blocked the OSS split is **decided**: the engine ships as **Baton** —
distribution `baton-engine` (free on PyPI and npm), GitHub org `baton` (free), docs at
`baton.eeze.app` (owned zone). Evidence and caveats: `docs/ENGINE-NAMING.md`; decision:
`docs/DECISIONS/ADR-0003-oss-engine-name-baton.md`. In the same pass F6 item 10 was closed:
**PyMuPDF (AGPL) replaced by `pypdf` (BSD)**, A/B-proven on the real invoices — ledger identical in
all 11 columns × 5 rows (`ADR-0004`). Next: the extraction/publishing checklist in the naming doc.

## Providers (2026-09-24)

Owner directive: while testing, the brains run on the owner's **Codex subscription** with **no
paid spend at all** (OpenRouter only as an opt-in fallback); the shipped product must let every
user **add their own API key** per provider. Design, phases (P1 subscription brain → P2 registry
+ secrets + API → P3 UI → P4 product policy) and non-goals: `docs/PROVIDERS-PLAN.md`.

**P1 DELIVERED (2026-09-24, corrected the same day after the owner's review)** — `brains/codex.py`
(`EEZE_BRAIN=codex`), local-only, **subscription-only**: tier models `gpt-6-luna` (routine) /
`gpt-6-sol` (hard) from the free rules floor, failed runs climb luna → sol inside the subscription,
the paid fallback is opt-in (`EEZE_CODEX_FALLBACK=openrouter`). Live proof: a real 5-step Notepad
run `done 1/1` with **6 judgments on `codex:gpt-6-luna`** (confidence min 1.0, 483 678 tokens,
**$0.0**, zero OpenRouter mentions in the journal) and the money rule proven live (bogus binary →
2 attempts, `fallbacks=0`). The planner and the spec writer ride the same subscription
(`EEZE_PLANNER_ENGINE`/`EEZE_SPEC_ENGINE=codex`; live: plan 79 783 tok, 3D spec 80 267 tok,
both $0.0, render `p1e-cup.mp4`), and the local `.env` defaults to `EEZE_BRAIN=codex` +
`EEZE_PLANNER_ENGINE=codex` (applied by the assistant on the owner's behalf). Report: `docs/P1-REPORT.md`.

**P2 DELIVERED (2026-09-24)** — `core/providers.py` (8-provider catalog + per-field precedence
run → agent → store → env → default) and `core/secrets_local.py` (write-only `~/.eeze/secrets.json`,
0600, corrupt file quarantined), wired into `llm`/`planner`/`specwriter` and exposed as
`/api/providers` (list, key, delete, overrides, live test). **No endpoint ever returns a key value**
(presence + `last4` only). Live proof with a fake key: honest `401` from OpenRouter in 188 ms, a real
Codex-subscription judgment (`gpt-6-luna`, 78 631 tok, 7 051 ms, $0), and every refusal path
(401/403/404/409/422). The live pass found a real bug — the generic `EEZE_<ROLE>_*` env leaked
`openai/gpt-6-sol` into the Codex CLI and a base_url into every row — now a rule:
**only `api_key` providers read the role env; the CLI reads `EEZE_CODEX_*`; `local` reads neither.**
Report: `docs/P2-REPORT.md`. Tests 232/232.

**P3 DELIVERED (2026-09-24)** — the Settings screen ships **Providers & models**
(`ui/src/components/providers-card.tsx`): per-provider status, where the key comes from, tier
models, Paste/Replace key, Remove, **Test connection** (live) and "Use this one"; the tier mapping
is now CONSUMED by the router (defaults → active provider's models → `agents.yaml`) and the pick
selects the brain (`llm` for an API provider, `codex` for the local subscription). Live proof on
the real page: a fake key pasted through the UI (`stored on this machine ···9999`, the value never
rendered), an honest `Failed (HTTP 401)` from the OpenRouter probe, removal back to the `.env`
source, and codex answering for real (`7.6 s · gpt-6-luna · 78,631 tokens`, $0). Two live bugs
found and fixed: every API provider claimed OpenRouter's `.env` key (now only the owner claims it),
and "Use this one" could have shown a badge that did not match what runs.
Report: `docs/P3-REPORT.md`. Tests 239/239.

**F7 — Missions (Mission Composer) — ✅ DELIVERED 2026-09-24.** The front door the app never had: a
mission is now an object you write, draft, edit, save and run from one screen (`/missions`); the
plan YAML is an editor (with an `edited` chip and a confirmation before regenerating); Run exists
only once a plan does, and the reason is written next to the disabled button; a mission owns its
schedule as one derived routine (`mission:<id>`) — no new engine, no new scheduler. Live-proven on
the real app: draft `codex:gpt-6-sol` 77,636 tokens / 17.7 s / $0 → edited in the UI → validated →
saved → the run paused at the gate (`ap-e99e021f30`, waiting for the owner); switching the schedule
Daily → On demand created and removed the routine. Two bugs found by the proof and fixed (the editor
saved `id: ""`; a test leaked the real `.env` into every test after it). Report:
`docs/F7-REPORT.md`. Tests 260/260.

**A1 — provider credential isolation — implemented 2026-09-24.** The HTTP brain, planner,
and spec writer now honor the selected provider's resolved key (including an empty key),
without rereading a foreign role key. Environment credentials remain bound to their
endpoint; explicit endpoint overrides require their own key; a mismatched provider probe
is refused. Synthetic-key transport regression + full suite: 265/265 passed, ruff clean.
No real provider request, daemon restart, approval decision or mission run was part of A1.
Report: `docs/A1-REPORT.md`. Changes are uncommitted pending review.

**A2 — approval/action binding — implemented 2026-09-24.** New approvals capture
an immutable task/agent/runtime digest. Resume verifies the approved identity and the
stored pause context before device actions, then atomically claims the approval once;
changed tasks/context, replay and pre-A2 approvals fail closed. Local fake-driver suite:
277/277 passed, ruff clean. No live mission, approval decision, daemon restart or commit.
Report: `docs/A2-REPORT.md`.

**A3 — local operator and artifact boundary — implemented 2026-09-24, not deployed.**
`/api` and `/artifacts` now require a loopback operator credential: an out-of-band
local token for CLI or a signed browser cookie obtained at `/pair`; the old HTTP
read-token endpoint no longer discloses the secret. Browser 401s reach pairing,
and the Vite proxy keeps the `/api` prefix. Script subprocesses receive a minimal
environment and cannot set cwd outside their run directory, **but are not sandboxed**:
filesystem and network access remain possible. Isolated verification: 285 Python
tests, Ruff, TypeScript, UI build, pairing-path tests and lint (11 existing warnings).
A disposable HTTP/browser check verified anonymous denial, synthetic-cookie read and
401-to-pair navigation; browser form submission was not exercised. No commit, live
mission or daemon restart. See `docs/A3-REPORT.md` for limits and rollout hold.

**P4** (BYO-key onboarding docs, per-provider guide, ToS note on subscriptions)
remains gated. Photo editing was subsequently delivered in A18–A22; image
generation remains unbuilt and requires separate provider/spend authorization.

**A4 — local activation — 2026-09-24 (`docs/A4-REPORT.md`).** The daemon was
restarted on the A1–A3 code and the tested UI bundle. Its API now returns 410
instead of disclosing the token, denies anonymous reads with 401 (including
artifacts), and reports healthy on loopback; the browser reaches `/pair`. The
local operator token was rotated without disclosing either value. The backup
passed integrity and the six business-table counts and both old pending
approvals remained unchanged. **Do not click either old approval**: both lack
the A2 digest. The live authenticated browser flow needs the owner's manual
pairing; no real mission or public ingress was tested. At A4 the recorded
tunnel PID belonged to Edge, not cloudflared. `run_script` remains unsandboxed.
P4 remains gated.

**A5 — tunnel PID ownership — code-only 2026-09-24 (`docs/A5-REPORT.md`).**
New quick tunnels record a process-creation fingerprint; start/status/stop
verify the executable, local command and persisted identity before claiming
or terminating a PID. Legacy/unverified PIDs fail closed. On the actual stale
Edge PID, the read-only CLI now reports `running:false` and no URL; Edge and
the Eeze daemon stayed running. Simulated-process tests 11/11, full Python
suite 296/296, Ruff clean. No real tunnel start/stop or daemon restart; nothing
committed. Residual check-to-kill race and CLI failure exit-code semantics are
documented in the report. Await separate GO for further work.

**A6 — legacy approvals non-resumable — code-only 2026-09-24 (`docs/A6-REPORT.md`).**
The API marks records without an A2 digest or waiting run state as non-resumable
and refuses either decision before any grant/status change. The local Approvals
page shows their warning without action controls. Isolated browser fixture: two
legacy cards with zero decision/grant controls; one bound card with both actions.
Full suite 299/299, Ruff, TypeScript, lint (0 errors, 11 existing warnings), and
scratch UI build passed. The two real pending records remain unchanged (NULL
digests). **Not activated on the running daemon or served UI; no commit or restart.**
Await separate GO for activation and real browser pairing.

**A7 — activate A6 locally — 2026-09-24 (`docs/A7-REPORT.md`).**
The owner authorized unattended work. A6's API guard and current local UI bundle
were activated on the loopback daemon after a consistent DB backup and old-client
snapshot; no routine was running. Read-back: health 200, anonymous approvals 401,
authenticated read-only list 200 with both historical approvals still `pending` and
`resumable:false`; all six business-table counts unchanged (19/4/19/4/13/3), DB
quick-check `ok`. No approval was decided, no pairing performed, and no live mission
was run. The owner's local browser pairing remains the next human-only check.

**A8–A13 — offline routine/approval hardening (`docs/A8-A11-REPORT.md`,
`docs/A12-REPORT.md`, `docs/A13-REPORT.md`).** New invoice approvals bind to a
resumable action; task-routine failures report honestly; optional failure alerts
baseline old failures; visual fallback validates proposals offline only; scheduler
spawn and tick failures become visible. The tests are isolated; no live mission or
VLM-driven click has yet validated these paths end-to-end.

**A14 — controlled local activation (2026-09-24 EDT; `docs/A14-REPORT.md`).**
With the owner present, backed up the live DB and client, built and swapped the
operator UI, and restarted the verified Eeze daemon. Read-back: new PID 52984,
loopback health and HTML/assets OK, anonymous operator API 401, approvals/runs/
schedules unchanged (19/13/three due 2026-09-25 08:00 local), no routine running.
One new settings key is the expected old-failure baseline; failure toasts remain
off pending opt-in. Full suite 338 passed, one dependency warning; Ruff, UI lint,
TypeScript and production build passed. Neither an approval nor a mission was
executed. A supervised live pilot is still outstanding.

**A15 — supervised new approval/resume (2026-09-24 EDT; `docs/A15-REPORT.md`).**
The owner paired the browser and approved two fresh, step-scoped `install_exec`
requests for a new local video-card task, both without a grant. The assistant
created the pause but did not decide or resume either approval. The task finished
`done 1/1` with two successful steps, a verified 3.000 s H.264 MP4 (720×720) and
PNG poster; 0 Jev calls and $0 estimated model cost. Four grants unchanged,
both legacy approvals still pending. Full suite 338 passed; Ruff clean. This
proves a local creative script's human approval loop, not remote approvals or
VLM GUI work.

**A16 — dashboard video mission pilot (2026-09-24 EDT; `docs/A16-REPORT.md`): partial.**
The owner generated and validated a Codex video spec in `/missions`, saved an
on-demand mission and approved its one fresh `install_exec` step without a grant.
The resumed run reported 1/1 and produced a genuine 4.063203 s H.264/AAC video
as `work/04-teaser.mp4` plus a PNG cover. However the advertised final `.mp4`
contains PNG bytes (last-step output selection bug), and the saved mission still
shows `needs_approval` after completion (resume metadata bug). The saved sources
are temporary scratch files. Do not call the final deliverable or mission status
verified until these defects are corrected and rerun on a fresh mission copy.

**A17 — local video mission correction (2026-09-25 EDT; `docs/A17-REPORT.md`): done.**
The video runner now selects the latest artifact compatible with a named output file
and verifies the final media kind; a PNG cannot silently ship under an `.mp4` name.
A signed approval resume updates only the matching mission's run status, with stale
and failed runs handled explicitly. RED regressions were observed, then 343 tests and
Ruff passed. After a backed-up local daemon cutover, the owner saved a **new**
on-demand mission with durable local sources and approved its fresh gate without
a grant. The final deliverable is a real H.264/AAC MP4 (4.063203 s, 480×480, 25 fps),
plus a PNG cover; 5/5 edit steps and runset 1/1. Persisted/API mission status and
the owner's dashboard view all say `done`. Grants remain at four; A16 and old
non-resumable approvals were not changed. Later reruns and backups of source media
remain unproven.

**A18 — local photo-editing vertical, first slice (2026-09-25 EDT; `docs/A18-REPORT.md`): code + real artifact done.**
New `eeze photo <spec.yaml>` uses the installed ffmpeg for bounded crop, resize
and color adjustments, probes each intermediate and the independently copied final
PNG, and refuses wrong source types, bad geometry, unsafe paths and overwrites.
`specs/a18-avatar-photo.yaml` edited the real Eeze mascot into a 600×600 PNG
(`artifacts/photo/a18/refined/eeze-avatar.png`, 269,004 B; 3/3 steps; inspected
visually). RED success/race/CLI tests preceded the fixes; full suite **351 passed**,
Ruff clean. No new dependency or paid provider; daemon/UI/schedules unchanged.
At the A18 checkpoint this was **CLI-only**: no brain-authored photo spec, Missions
kind or approval-flow pilot. A19 below closes those three gaps; user-photograph
proof and image-generation APIs remain outstanding.

**A19 — goal-authored dashboard photo mission (2026-09-25 EDT; `docs/A19-REPORT.md`): done.**
The owner created `a19-robot-avatar` in `/missions`, generated a validated photo
spec with the local Codex subscription, ran it on demand and personally approved
the fresh `install_exec` gate without a grant. Runset
`20260925-020101-mission-a19-robot-avatar` finished **1/1**; photo edit **3/3**;
the final `run-01/a19-robot-avatar.png` is a visually inspected, genuine
600×600 PNG (269,004 B), with SHA-256 matching the edit report. Persisted mission
and authenticated API both say `done` for the matching runset; refreshed owner
dashboard display was not independently observed. The draft writer recorded one
attempt, 79,336 tokens and estimated US$0; actual subscription billing is
unavailable. Full suite **360 passed**, one warning; Ruff, UI lint (0 errors,
11 existing warnings), TypeScript and isolated build passed. An accidental live
UI build briefly made `/` return 500; the shell was restored and post-cutover
`/`, `/missions` and health returned 200. Backup and controlled daemon restarts
are detailed in the report. Grants remain four, old approvals untouched, and
the mission adds no routine. This edits the Eeze brand image, not the owner's
photo; it neither generates an image nor uses a VLM. No commit or A20 work.

**A20 — user-supplied dusk grade (2026-09-25 EDT; `docs/A20-REPORT.md`): done, with a visual limit.**
The owner supplied a 2048×2048 illustrated snowy scene, requested "Faça
anoitecendo", then ran and personally approved a fresh on-demand photo mission
without a grant. `a20-snow-dusk` completed **1/1** with **1/1** local adjustment;
the advertised final PNG was independently probed at 2048×2048, 3,477,450 B,
its hash matched the edit report, and the image was visually inspected. It is
noticeably darker with preserved subject and landscape, **but the sun/left sky
remain bright**: the current editor applies only a global grade, not selective
sky/lighting reconstruction. Mission YAML and authenticated API say `done` for
the matching runset/approval; refreshed browser display was not observed.
The draft used `codex:gpt-6-sol` via the subscription (one attempt, 79,380
reported tokens, estimated US$0; actual billing unavailable). No code changed,
so tests were not rerun. Grants remain four; accepted runs untouched, no commit.

**A21 — local positional twilight grade (2026-09-25 EDT; `docs/A21-REPORT.md`): offline preview, NOT live Missions.**
Added a bounded `twilight` photo op: a cool upper-frame tint that fades smoothly
toward the foreground (not semantic sky selection). From the same preserved source,
the chosen softer preview `artifacts/photo/a21/preview-soft/a21-snow-twilight-soft.png`
completed **2/2** ffmpeg steps; final genuine PNG 2048×2048, 3,927,831 B, SHA-256
matching the edit report and inspected visually. The bright left glow is subdued,
but peaks and trees are tinted too. RED→GREEN pixel/validation tests; targeted
**40 passed**, full suite **368 passed** (one third-party warning), Ruff clean.
The running daemon was not restarted: its authenticated `twilight` validation
still returns `ok:false`. **No A21 mission, approval or live dashboard proof**;
activation and an owner-decided gate require a separate safe cutover. No model
call, paid provider, new dependency, UI rebuild or commit in A21.

**A22 — local activation and new Mission (2026-09-25 EDT; `docs/A22-REPORT.md`): done.**
After verified daemon ownership, no running routine and a consistent DB/UI
backup, the loopback daemon was restarted on the A21 code. Health and UI returned
200, anonymous mission API 401, and authenticated `twilight` validation changed
from `ok:false` to `ok:true`; counts **25/25/4/4/13**, three 08:00 schedules,
four grants and the A20 `done` status stayed intact. A fresh on-demand
`a22-snow-twilight` was validated, saved and read back. The owner clicked Run now
and then personally approved/resumed only `ap-72097b4b0e` (`install_exec`), **without
a grant**. Runset `20260925-034439-mission-a22-snow-twilight` finished **done,
1/1**, with **2/2** local photo steps. The advertised final PNG was independently
verified at **2048×2048**, **3,927,831 B**, report-matching SHA-256
`a4f2587c807a3f31a4994903b7cd8e9e233d04365f08097362628ee73e7d1a4e`,
and inspected visually. Its positional tint subdues the left glow but also colors
upper mountains/trees; it is not a semantic sky mask. Persisted/API mission status
is `done` for the same runset/approval. Database `quick_check=ok`, counts
**26/26/4/4/13**, three 08:00 schedules and the accepted A20 image remained
unchanged; the two old non-resumable approvals are still pending. A21's full suite
was **368 passed**, Ruff green; A22 made no code changes or new test run. No UI build,
paid call, email, public deploy, commit or A23 work.

**A23 — offline selective dusk-mask feasibility (2026-09-25 EDT; `docs/A23-REPORT.md`): rejected prototype, no new capability.**
A local warm/bright left-sky heuristic was tested on the A22 final and its preserved
global-grade intermediate. The A22-based mask changed only **20,117 / 4,194,304**
pixels, mostly a small tree patch, and looked nearly identical to A22. The
intermediate-based candidate changed **531,717 / 4,194,304** pixels and yielded a
genuine 2048×2048 PNG, but visibly darkened the left trees while leaving the bright
glow; sampled glow was unchanged, while a tree pixel changed from `[195,170,154]`
to `[83,80,99]`. Both candidates were rejected after visual inspection. The
heuristic is not semantic sky segmentation and was not added to the product.
Disposable artifacts/masks live in gitignored `spikes/out/a23/`; **3/3** prototype
tests, full **368 passed, 1 third-party warning**, Ruff green. No live activation,
provider call, accepted-run rewrite, UI build or commit. A reliable matte/segmentation
would need a separate plan and proof.

**A24 — local semantic sky-label proof (2026-09-25 EDT; `docs/A24-REPORT.md`): rejected offline.**
A pinned CPU ONNX SegFormer ADE20K checkpoint ran locally on the owner's original
artwork, but its `sky` mask covered only **37,506 / 4,194,304** pixels (~0.9%)
and missed the bright left glow (sample mask 0). On A22's graded intermediate it
predicted **no sky** at all, so the prototype refused to make up a mask. The
source-derived mask produced a genuine 2048×2048 PNG, but the glow remained bright
and the candidate was rejected after mask/image inspection. Checkpoint license is
non-commercial research/evaluation only, so it cannot be shipped with Eeze even
if its quality were acceptable. Isolated code, model and image stay gitignored
under `spikes/out/a24/`; RED→GREEN prototype tests **2/2**, repo **368 passed,
1 third-party warning**, Ruff green. No production code, live activation, paid
provider, API write, accepted-run rewrite or commit. A verified human-guided matte
or a better-licensed/better-performing model remains a separate decision.

**A25 — human-guided local glow matte (2026-09-25 EDT; `docs/A25-REPORT.md`): two rejected offline previews.**
A scene-specific OpenCV GrabCut draft masked **337,554 / 4,194,304** pixels
but left a flat blue sky patch, circular holes and a darkened snowy tree. A
second draft protected both pines with manually traced envelopes, broadened
feathering and reduced opacity: **229,998** raw mask pixels, genuine
2048×2048 PNG, but visible triangular/light silhouettes remained, while the
tree-adjacent glow sample was unchanged. Both were visually rejected, not
promoted to the photo editor or a Mission. Isolated tests **4 passed**; full
suite **368 passed, 1 third-party warning**, Ruff green. A22 accepted file
and source hashes intact; no daemon/API/product write, model call, paid
provider or commit. A pixel-accurate matte reviewed by the owner (or another
licensed, verified method) remains an unresolved separate phase.

**A26 — offline pixel-matte editor (`docs/A26-REPORT.md`): closed by owner; selective edit not accepted.**
Delivered a standalone local HTML editor with the accepted A22 image embedded,
empty matte by default, paint/erase/zoom/pan/undo/clear, binary matte export and
bounded dusk draft export. Real browser pointer and export checks: genuine
2048×2048 PNGs, **1,808 test pixels selected and changed, zero pixels changed
outside the matte**; this was only a synthetic brush stroke, not an artist-complete
matte. Node tests **3 passed**; full repo **368 passed, 1 third-party warning**,
Ruff green. Browser screenshot capture was unavailable, but DOM actions and
pixel/ffprobe readback passed; automatic browser download was not independently
observed, so a visible fallback link is provided. The owner exported a real
trial matte/draft: 330,996 pixels changed, none outside the binary matte.
Visual review found a hard sky boundary and missed left glow; the owner then
ended this attempt without accepting the draft. Nothing was activated in
Missions; the editor and exports remain offline evidence. No commit, model,
paid call, deploy or product dependency.

Measured on this machine (subscription side, 2026-09-24): `gpt-6-luna` ✓ and `gpt-6-sol` ✓ answer
through the CLI and through Hermes' `openai-codex` provider (78 622 tokens for a one-word answer);
`gpt-6-terra` ✗ refused; `gpt-5.6-luna` / `gpt-5.6-sol` still answer (previous generation);
`gpt-5.3-codex-spark` is **not entitled** ("model entitlement", live-proven) and the OpenRouter
fallback answered in its place — the chain works end-to-end. Hermes itself now runs `gpt-6-sol`
via `openai-codex`, OpenRouter (`google/gemini-2.5-flash`) as fallback.

## Gates

- **Capability map**: `docs/CAPABILITIES.md` — ✅ proven slices, 🟡 built-but-unproven
  paths, ❌ absent capabilities, current operational snapshot and prioritized gaps.
- **Project report**: `docs/PROJECT-REPORT.md` — original founder intent, historical
  2026-09-23 pilot incident, **current §0a snapshot** and §4 open work. The day-19
  gate was later resolved; a separate day-24 invoice run is legacy-blocked.
- **A26**: editor delivered offline, trial draft visually rejected, owner ended
  the attempt. Preserve A22; no silent next sky-matte phase.

- **M0 (F0→F1):** go/no-go on the loop thesis — real numbers in `docs/SPIKES.md`.
- **M3 (F3→F4):** first vertical chosen, with a pilot user in hand.
- **M5 (F5→F6):** security checklist drafted (injection, secrets, permissions).
