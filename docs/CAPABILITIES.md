# Eeze — what the agent can do today

Honest capability map, refreshed 2026-09-26 using a read-only local snapshot from
2026-09-25 23:07 EDT (F0–F6/M0, v2, script/tool layer, creative verticals and
Codex-subscription brain). ✅ means the *named slice* has a live proof, not that
the entire product is deployed or autonomous. 🟡 is built without complete
end-to-end proof; ❌ is not a usable capability. Runtime status can change; see
§5 and `docs/PROJECT-REPORT.md` §0a for the measured snapshot.

## 1. Execution core — what it can operate

| Capability | State | Evidence / notes |
|---|---|---|
| Windows desktop apps via UI Automation | ✅ | Notepad live: open, type, Save-as through menus, background, no focus steal (`artifacts/runs/*-notepad-save-as`) |
| Task step actions | ✅ | `set_text`, `click`, `invoke_menu`, `hotkey`, `check`, `run_script` (`core/models.py: StepSpec`) |
| Script/tool steps (`run_script`) | ✅ | Runs one shell command per step (cmd.exe), cwd default = the run's own dir; full stdout/stderr logged to `run-NN/step-<id>.log`; exit code + duration + artifacts in the journal; hard `timeout_s` kills the WHOLE process tree; auto-classified `install_exec` (gated) and heuristics can only raise it; tasks with `app: ""` need no window. Live: `tasks/video-card.yaml` gated → approve → resume `1/1` (2/2 steps) + grant path `1/1`; timeout/exit-code/artifact paths covered by `tests/test_script_steps.py` |
| Driver actions beyond steps | 🟡 | `drag` exists in `drivers/cua.py` but is NOT exposed in the task format; no explicit `scroll` action (PageDown via `hotkey`) |
| Per-step verification | ✅ | deterministic `verify_code` (`doc_equals`, `field_equals`, `file_exists`, `file_size_gt`, `window_present/absent`) + `verify_jev` (Noul over a fresh capture; skipped with a journal note on windowless script steps) |
| Retry / replan | ✅ | per-step retries (default 2); bounded replan in `eeze goal` (default 2) |
| Zero focus-steal | ✅ | audit PASS: 107 samples, 0 focus changes, 0 cursor moves |
| Resume a paused run | ✅ | `eeze run --resume` / UI approve; routine resume proven |
| Multi-app runs | 🟡 | per-step `window` targeting exists; only single-app runs proven |
| macOS / Linux | ❌ | cua-driver supports them; orchestration + installers here are Windows-only |
| UIs without accessibility (games, canvas, remote desktop) | ❌ | no OCR/vision-only fallback — element enumeration (UIA) is required |
| Concurrent agents on one desktop | ❌ | one desktop per machine: concurrent runs collide (per-routine `has_open_run` only prevents stacking) |

## 2. Perception & judgment — the brains

- ✅ Per step: element enumeration → candidate Choice → brain decision → one action → fresh
  capture (tokens die per snapshot).
- ✅ Two brains behind the same interface (`select_element`, `verify`): **Jev (TypeSafe)**
  default; **LlmBrain** (OpenAI-compatible; `openai/gpt-6-luna` + `gpt-6-sol` proven live on
  real runs — `deepseek-chat` served until 2026-09-23, now retired).
- ✅ **Third brain: `codex`** (2026-09-24, `brains/codex.py`, P1 of `docs/PROVIDERS-PLAN.md`)
  — judgments through the owner's **Codex/ChatGPT subscription** via the local CLI
  (`codex exec --json --ephemeral`, read-only sandbox, prompt on stdin), **local-only**
  (never the distributed product's provisioning model) and **subscription-only by default**
  (the owner's testing rule: no OpenRouter spend). Models per tier, flat-priced:
  `gpt-6-luna` (routine) / `gpt-6-sol` (hard), tier from the free rules floor. Every failure —
  CLI missing, not logged in, timeout, non-zero exit, no message — retries the CLI and then
  **degrades honestly**; the paid `LlmBrain` fallback exists only with
  `EEZE_CODEX_FALLBACK=openrouter`, and `Judgment.model` then says which engine answered
  (`codex:<model>` vs the OpenRouter model). Live: real 5-step Notepad run `done 1/1` —
  6 judgments, all `codex:gpt-6-luna`, confidence min 1.0, 483 678 tokens, **$0.0**, zero
  OpenRouter mentions in the journal; the money rule proven live (bogus binary → 2 attempts,
  `fallbacks=0`, no paid engine constructed); `eeze doctor pilot` shows tier models + cli.
  **Planner + spec writer ride the same subscription** (`EEZE_PLANNER_ENGINE`/`EEZE_SPEC_ENGINE
  = codex`, `codex.py: codex_client`; a CLI failure is a `PlanError`/`SpecWriteError`, never a
  paid call). Live: a real plan in 79 783 tokens and a real 3D spec written in 80 267 tokens
  (attempt 1, 20.9 s), both **$0.0**, the spec then rendered by Blender 5.2.2 (`p1e-cup.mp4`).
- ✅ Per-agent brain selection (agents.yaml + UI picker); env override; per-agent planner model.
- ✅ **Model router** (2026-09-23, `brains/router.py`): per-run model choice for the `llm`
  brain — `routine` → `openai/gpt-6-luna`, `hard` → `openai/gpt-6-sol` (DeepSeek retired).
  Jev decides with a typed Choice (4/4 correct in the probe, ~140–350 ms, ~$0.000023), a
  deterministic rules floor catches every refusal/error below `JEVI_CONFIDENCE_FLOOR` (and
  is journaled as `rules-fallback`, never silent), and a FAILED run escalates one tier up for
  the next run of the run-set (proven live). Measured on the same 5-step Notepad task:
  Sol $0.023178 vs **Luna $0.0011988** (19.3×), both `done`. Every decision journals
  `model_route`; the summary carries per-model calls/tokens/cost. Detail: `docs/ROUTER.md`.
- ❌ No per-decision routing (a different brain per STEP) — the router picks one model per run.
- 🟡 The codex brain has an **opt-in** paid fallback (`EEZE_CODEX_FALLBACK=openrouter`); by
  default a failed engine retries the CLI and degrades honestly, and a failed run climbs
  luna → sol **inside the subscription**. **Jev still has no fallback** — a Jev failure fails
  the step.
- ❌ No long-term memory per agent (v2 roadmap; the runs/audit trail is the only record).
- 🟡 A **subscription-backed** engine exists (`codex`, local-only) but there is still no
  local/offline (Ollama-style) model option.

## 3. Safety & governance — "you approve what's risky"

- ✅ Six risk classes (`read < write_local < external_send < install_exec < destructive <
  system`); heuristics can only RAISE a step's class; declarations raise, never lower.
- ✅ Per-agent policy + grants with TTL + revoke; approve/deny with resume (UI + token-gated
  API); `external_input_detected` pauses-not-fixes and excludes the run from metrics.
- ✅ Audit trail: every runset self-sufficient (task verbatim, run_meta, journal, per-step
  screenshots); `eeze audit export` bundles with sha256s; `eeze replay` reproduces (MATCH).
- ✅ Desktop toast when a run pauses (deduped, toggleable, no focus steal).
- ❌ No remote approval — approving needs this machine's UI/API (no email/mobile link).
- ❌ Bundles are hashed but not signed (no external trust anchor).
- ❌ `budget_usd_daily` is declared on agents but enforced nowhere — no spend caps or
  mid-run cost alerts.
- ❌ Single-user only: no login/RBAC; the API trusts anything running on localhost.

## 4. Work verticals — what it does for a living

**Intended verticals (founder, 2026-09-23): video editing · photo editing · image
generation · 3D models — an agent that opens applications and, depending on the brain it
uses, carries the domain skill to do that work.** The action surface now reaches scripts
and CLI tools (`run_script`, 2026-09-23 — see §1), which is how creative work actually
happens (`ffmpeg`, Blender's Python API, Photoshop UXP, Resolve's API, generation APIs);
video rendering AND spec-driven editing landed, plus a 3D vertical on Blender headless
(below). A18 added local crop/resize/color adjustment; A19 proved a brain-authored
photo plan and owner-approved `/missions` execution with a verified PNG from the
existing Eeze brand image. This is not image generation or proof with a user's
photograph. A20 then edited a user-supplied illustrated snow scene into a
darker, late-evening grade through the same gated Missions path. The bright
sun/left sky remained because the adjustments are global; selective relighting
and sky replacement remain ❌. A21 added a local **position-based** twilight
gradient with a real preview. A22 activated its validator in the loopback daemon
and proved a fresh, owner-approved on-demand Mission: `done 1/1`, two local steps,
verified final PNG. The effect does not identify a sky. A23 tested a local
warm/bright-pixel mask offline, but it targeted left trees more strongly than the
remaining glow; both previews were rejected and no new photo op was shipped.
A24 tested a local semantic `sky` label on the same owner image: only 37,506
pixels were selected and the glow was missed; the model's upstream license is
non-commercial research/evaluation only, so this checkpoint cannot ship.
A25 tried a locally guided GrabCut matte; two visual previews were rejected
because the first made a blue patch and tree holes, and the softened second
still left unnatural silhouettes around pines without fixing the glow.
A26 delivered an **offline manual pixel-matte editor** over the accepted A22
image (paint/erase/zoom/export). The owner exported a real trial matte/draft;
pixels outside the matte were preserved, but the visual result retained a hard
sky boundary and missed part of the left glow. The owner closed the attempt
without accepting a new image. The editor remains an offline tool, not a proven
selective relighting operation.
Image-generation APIs and VLM interpretation remain ❌.
The office-shaped table below is still the paid-for reality; the video row is the first
creative one.

| Vertical | State | Evidence |
|---|---|---|
| **Video (ffmpeg): render an MP4 card + extract a poster frame from an image** | ✅ | 2026-09-23: `tasks/video-card.yaml` (script-only) — gated run paused (`install_exec`, "'ffmpeg'"), approved via API with `grant scope=task` + auto-resume → `1/1`, 2/2 steps; real artifacts `card.mp4` (h264, 720×720, 25 fps, 75 frames, 3.000 s, 18 237 B) + `poster.png` (83 668 B, verified visually); grant path re-run `1/1`. Covers render + frame extraction only — no editing pipeline, no timeline, no audio |
| **Video (ffmpeg): spec-driven EDITING — still→video, trim, scale, fps, concat, thumbnail; every step ffprobe-verified** | ✅ | `verticals/video` + `uv run eeze video <spec.yaml>`: real 5/5 steps → verified H.264/AAC MP4 + PNG cover (C1). A brain-authored video spec has also run (C3); A16's dashboard mission had a malformed advertised final and stale status, both corrected and proved on a fresh owner-approved A17 mission (5/5 steps, 1/1 run, genuine 480×480 MP4). Limits: fixed op set (no overlays/transitions/text/audio mixing/timeline), no GPU encoders, ffmpeg required. See `docs/C1-REPORT.md`, `docs/C3-REPORT.md`, `docs/A17-REPORT.md`. |
| **Photo edit (ffmpeg): crop, resize, global adjust and positional twilight → PNG** | ✅ bounded editor + owner-approved Missions pilots | A18 proved CLI (3/3); A19 brain-written, owner-approved brand photo Mission (1/1, 3/3); A20 owner-supplied *illustration* (1/1, global adjustment 1/1); A22 owner-approved positional twilight Mission (1/1, 2/2, verified 2048×2048 PNG). The global grade leaves left-sky glow; twilight reduces it but also tints mountain/tree pixels. A23–A25 masks were rejected; A26 manual editor is offline and its owner-exported draft was not accepted. This is not camera-photograph proof, semantic relighting, image generation or VLM. See A19–A26 reports. |
| **Twilight gradient (local photo editor)** | ✅ owner-approved Missions pilot | A21 added a bounded upper-frame navy blend with smooth vertical fade and verified an offline preview. A22 activated the loopback validator and the owner approved/resumed fresh `a22-snow-twilight` without a grant. Runset **done 1/1**, edit **2/2**, final genuine PNG **2048×2048**, **3,927,831 B**, report-matching SHA-256 `a4f2587c807a3f31a4994903b7cd8e9e233d04365f08097362628ee73e7d1a4e`, visually inspected; persisted/API mission status `done`. The bright left glow is subdued, but mountains/trees in the same vertical region are tinted: **not a semantic sky mask**. `docs/A21-REPORT.md`, `docs/A22-REPORT.md`. |
| **3D (Blender headless): declarative scene → still + turntable MP4 + .blend + .glb, every artifact verified** | ✅ | 2026-09-23: `verticals/render3d` + `uv run eeze 3d <spec.yaml>` on Blender 5.2.2 LTS (`Program Files/Blender Foundation/Blender 5.2`; discovery `--blender` → `EEZE_BLENDER` → PATH → newest install). The spec declares primitives/text + transforms/materials, camera (optional orbit), lights, render settings and the steps; ONE Blender process per run (cold start ~36 s measured) builds the scene, runs every step and prints per-step status lines; the runner verifies each artifact for real — existence/size, `.blend` header (plain or zstd), GLB magic `glTF`, PNG facts and MP4 duration/fps/size via ffprobe — and reports FAILED with the measured reason otherwise. Live demo `specs/brand-3d.yaml` (wordmark + ring + floor, orbiting camera): **4/4 steps in 16.3 s** → still 480×480 PNG 259 239 B, turntable MP4 h264 480×480 2.0 s 12 fps 92 179 B, `.blend` 186 855 B, `.glb` 481 364 B (sha256 `3a6d8eb9…`, verified visually); generated `work/run_blender.py` + `work/scene.json` + `work/blender.log` kept as evidence. Agent path: `tasks/render3d-agent.yaml` (gated `install_exec`). Limits: declarative primitives only (no mesh import/modeling), single Blender process per run, engine availability depends on the build (EEVEE/WORKBENCH/CYCLES) |
| **Creative writer (C3 + A19): a plain-language goal → a validated spec → a verified run** | ✅ | C3 proved video/3D; A19 added a photo vocabulary with real source/geometry validation and a live Codex draft (1 attempt, 79,336 tokens, estimated US$0, actual billing unavailable) through `/missions`, followed by a gated 3/3 edit and verified PNG. Historical video/3D figures remain in `docs/C3-REPORT.md`; photo evidence in `docs/A19-REPORT.md`. Limits: no image-generation vocabulary/API, 3D composes primitives (no mesh import), and a runset's cost rollup does not include the separate writer call. |
| Invoices: read-only inbox pull → PDF → verified ledger + anomalies | ✅ | 10/10 synthetic files, 5/5 planted anomalies; real mailbox: 41 msgs / 5 attachments / 4 anomalies, quote-verified rows; daily routine armed |
| Gated summary email | ✅ | external_send gate → UI approve → SMTP send confirmed, record `ok` |
| Demo desktop task (Notepad write/save) | ✅ | gated demo task; full pause → approve → resume loop |
| Spreadsheets (Excel / Sheets) | ❌ | nothing built or proven |
| Browser / web apps | ❌ | nothing built in Eeze; no login/credential flow |
| Documents & forms (fill, merge, sign) | ❌ | only PDF *reading* (invoices) exists |
| Email beyond the summary (triage, replies, folders) | ❌ | read-only pull exists; no sending outside the gated summary |
| Calendar / meetings | ❌ | nothing |
| Chat / Slack / Teams | ❌ | nothing |
| ERP / CRM / internal systems | ❌ | nothing |
| File organization (rename, sort, downloads) | ❌ | no user-facing task templates |
| Credentials for work apps | ❌ | only the IMAP app password (.env); no local credential store |

## 5. Operations

- ✅ Scheduler in the daemon (`daily:HH:MM` / `every:MIN`, 30s tick), skip-if-open, run
  records + history (CLI and UI).
- ✅ First-run wizard (mailbox probe; .env written server-side), one-click installer
  (shortcuts, autostart, idempotent), daemon local-only on 127.0.0.1.
- ✅ Backups (store + .env + logs, git-ignored), weekly report CLI (`eeze report`),
  `eeze doctor input|focus|pilot`.
- ❌ No automatic retry of a failed routine run or proven orphan-worker recovery.
- 🟡 Opt-in **failure notification code** (A10) was activated in the local daemon at
  A14, but the switch was left **off** and no live failure toast was observed.
  Approval-pause notifications are a separate proven path. Scheduler spawn/tick
  failures have offline-tested recording/logging (A12–A13), not an end-to-end
  failure-recovery pilot.
- ❌ Routines: no editing in the UI (no agent picker at creation, no schedule edit), no
  chaining/DAG, no full cron.
- ❌ Weekly report is CLI-only (no UI page); no per-agent split.

At the read-only snapshot (2026-09-25 23:07 EDT), `eeze api status` said
**running:false / responding:false**. The store has three enabled routines
(invoices, render3d-demo, test3d) due next at 2026-09-26 08:00 local; they cannot
fire while the daemon is stopped. The September 19 invoice email was sent after
its September 23 decision; a *different* September 24 invoice run remains
`needs_approval` on old, non-resumable `ap-ddb6e39e7b`. The other old pending
record is `ap-e99e021f30`. Neither should be decided or resumed; use a fresh
run and owner decision for new work. No daemon restart is implied by this document.

## 6. Interfaces

- ✅ Local UI, all live-mode pages real: Team/agents (wizard, edit dialog, brain picker),
  runs + viewer with REAL step captures, approvals, routines, setup wizard, settings
  (runtime/keys/paths), toasts.
- ✅ **Missions (F7)** — `/missions`: write the goal, generate the plan on the subscription
  (~15 s, $0), edit the plan YAML (`edited` chip), validate it, save it, run it. Run is disabled —
  with the reason written next to it — until a plan exists; a refusal from the writer shows its
  attempts. The mission owns its schedule (one derived routine) and its History.
- ✅ Public **concept landing** at eeze.app + contact API; **not** a runnable bot
  demo or the local operator dashboard (`docs/PUBLIC-HERO-REPORT.md`).
- ❌ No packaged desktop app / tray icon (daemon + browser tab today).
- ❌ No mobile / remote dashboard. ❌ No i18n (everything English).

## 7. What to build next — suggested priority

**P0 — pilot-blocking (a choice of next phase, not authorization to run it)**
1. **Restore and verify the local operator safely** — the daemon was down in the
   last measured snapshot. Back up and confirm scheduler/daemon identity before
   an authorized restart; do not touch the two non-resumable old approvals.
2. **Creative verticals, deepened** — script/tool layer ✅ (`run_script`), video EDITING
   ✅ (`eeze video`), 3D ✅ (`eeze 3d`), and photo editing with a brain-written plan
   and gated Missions pilot ✅ (A19 brand image; A20 user-supplied artwork).
   A21 added a position-based twilight preview; A22 activated it and proved
   the owner-gated Missions path ✅. A23's offline warm/bright-pixel mask was
   rejected after it darkened trees but missed the glow. Semantic sky/lighting
   work remains open: A24's local semantic model missed the glow and carries
   non-commercial terms, so neither prototype is a product solution. A reliable
   human-guided matte or a compatible, demonstrably better model is still needed.
   A25's guided GrabCut drafts also failed visual inspection. A26 delivered a
   local manual matte editor; its owner-exported trial preserved pixels outside
   the matte but left a hard sky edge and missed part of the glow. The owner
   closed the attempt without accepting a new image.
   Camera-photograph proof is separate; an image-generation API also requires
   explicit provider/spend approval.
3. **Routine failure handling** — A10 optional alert is built/activated but off
   and not live-proven; add supervised proof, safe retry and clear failure state.
4. **Approve away from the desktop** — signed one-time email/mobile link, not built.

**P1 — product depth**
5. **Per-agent memory** — learnings that persist between runs.
6. **Local credential store** for work apps — unlocks browser/web-app verticals.
   (🟡 provider keys have one since P2: `core/secrets_local.py`, write-only `~/.eeze/secrets.json`
   — app logins still missing, plus the OS keyring is not wired.)
7. **Routines UI**: edit schedule, pick agent, chain; report page in the UI. *Superseded in part by
   F7: a mission owns its schedule and History; the Routines page shows mission routines as
   `Mission · <name>` with an *open mission* link.*
8. **Budget enforcement** — hard daily cap + alert at 80%.
9. **Providers UI (P3)** — ✅ DELIVERED 2026-09-24: Settings → **Providers & models**
   (`providers-card.tsx`): status per provider, paste/replace/remove key, live **Test connection**,
   tier mapping (consumed by the router since P3) and "Use this one", which selects the brain.
   See `docs/P3-REPORT.md`; the API side (`/api/providers`) landed in P2.

**P2 — platform**
10. Multi-user (login/RBAC) + remote-approval infrastructure.
11. Signed audit bundles (verify without trusting the machine).
12. OCR/vision fallback for non-accessible UIs; `drag` + `scroll` in the task format.
13. Desktop packaging (service + tray + updater); macOS/Linux.
14. Isolation for concurrent agents (desktop session per agent).
