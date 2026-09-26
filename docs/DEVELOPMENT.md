# Development — Eeze Agent

## Layout

| Path | What |
| --- | --- |
| `src/eeze_agent/` | Python backend (loop, brains, drivers, API, CLI) |
| `ui/` | Self-hosted frontend (TanStack Start · React 19 · Tailwind v4; built as a SPA) |
| `artifacts/runs/` | Run journals + screenshots (gitignored evidence) |

## Everyday workflow

### Backend (API, and the UI once built)

```bash
uv run eeze api start     # detached daemon on 0.0.0.0:8765 — survives closing the GUI
uv run eeze api status    # running? responding? pid?
uv run eeze api stop      # kills the daemon tree
```

### Frontend in dev mode (hot reload)

```bash
cd ui && npm install      # once
npm run dev               # http://localhost:5173 (proxies /api -> 127.0.0.1:8765)
# or from the repo root:
uv run eeze ui dev
```

### Production build (served by the backend)

```bash
uv run eeze ui build      # npm run build -> ui/dist
uv run eeze api start     # serves  /  -> ui/dist (SPA)  and  /api/* -> JSON
# open http://127.0.0.1:8765
```

All-in-one, foreground:

```bash
uv run eeze api --serve-ui       # force serving the UI
uv run eeze api --no-serve-ui    # API only
# default is auto: the UI is served when ui/dist/index.html exists
```

## API surface

- JSON API prefix: **`/api/*`** (the only prefix — the root belongs to the SPA, so
  client-side routes are never shadowed by API aliases).
- Contract: `docs/API.md` · interactive schema at `/docs`.
- CORS (dev): `localhost:5173`, `localhost:3000`, any `*.lovable.(app|dev|project.com)`,
  any `*.trycloudflare.com`.
- Optional public tunnel (dev/demos): `uv run eeze tunnel start | url | stop`.
- Public deploy builds with `VITE_DEMO_MODE=true`: the UI short-circuits to
  bundled sample data (no network calls, no polling) — see `ui/src/lib/api.ts`.

## Verticals

### Invoices (E1)

```bash
uv run python scripts/make_synthetic_invoices.py          # regenerate the test corpus
uv run eeze invoices --input artifacts/e1-invoices/corpus --out artifacts/e1-invoices/out
```

Folder of PDFs -> `ledger.csv` + `anomalies.md` + `summary.json`. Every value is
accepted only if it sits inside a verbatim quote found in the source PDF
(`src/eeze_agent/verticals/invoices/verify.py`); missing fields stay empty and
are flagged — never a fabricated zero. The extraction brain is OpenAI-compatible
and defaults to the local Hermes gateway:
`EEZE_EXTRACT_BASE_URL` / `EEZE_EXTRACT_API_KEY` / `EEZE_EXTRACT_MODEL`.

### Inbox (E2, read-only)

```bash
uv run eeze inbox pull [--out dir] [--search UNSEEN] [--limit N]
```

Pulls PDF attachments from the mailbox into a local folder — the mailbox is opened
`readonly=True` and bodies are fetched with `BODY.PEEK[]`, so nothing is ever marked as
seen, moved, or deleted. Attachments are named `<message-id>-<filename>`: re-pulls are
idempotent and a same-named attachment arriving in another email never clashes (the
duplicate still reaches the ledger, where it belongs). Credentials: `EEZE_IMAP_HOST`
(default `imap.gmail.com`) / `EEZE_IMAP_USER` / `EEZE_IMAP_APP_PASSWORD` in `.env`
(Gmail app password — spaces are tolerated). Then feed the folder to the ledger:

```bash
uv run eeze invoices --input artifacts/e1-invoices/inbox
```

### Video editing (C1)

```bash
uv run eeze video specs/teaser-edit.yaml --out artifacts/video/c1-demo
```

Spec-driven editing chain run with ffmpeg and verified step by step with ffprobe
(`src/eeze_agent/verticals/video/`). The spec (YAML) declares `sources` (paths), an ordered
list of `steps`, and `output` (a file name, or the id of the step whose result is the
deliverable). Ops: `still_to_video`, `trim`, `scale`, `fps`, `concat` (normalizes its
inputs to one size/fps/sar and adds a silent track to silent sources), `thumbnail`. Each
step's expectation is checked on the produced file — duration within max(0.15 s, 5%),
exact size/fps, stream presence, non-empty — so a step that does not match is reported
FAILED (later steps `skipped`) instead of silently passing; `report.md` shows expected vs
observed per step and `work/` keeps every intermediate. ffmpeg discovery: `--ffmpeg-dir` →
`EEZE_FFMPEG` (full path) / `EEZE_FFMPEG_DIR` → `~/tools/ffmpeg` → PATH. The agent can run
the same CLI through `run_script` (gated `install_exec`); demo task
`tasks/video-edit-agent.yaml`.

### 3D scene render (C2)

```bash
uv run eeze 3d specs/brand-3d.yaml --out artifacts/3d/c2-demo
```

Declarative 3D: the spec describes the scene (`objects` — cube/sphere/torus/cylinder/cone/
plane/text with location/rotation/scale/color/metallic/roughness and per-kind `params`;
`camera` with optional `orbit`; `lights`; `world` background) and the render settings
(engine, resolution, fps, frames, samples), then the steps: `render_still` (frame → PNG),
`render_animation` (frames → MP4 h264), `save_blend`, `export_glb`. Blender runs headless
via one generated script (`work/run_blender.py` + `work/scene.json` + `work/blender.log`
are kept as evidence); the runner verifies every artifact for real (existence/size,
`.blend` header plain or zstd, GLB magic `glTF`, PNG/ MP4 facts via ffprobe) so a bad
artifact FAILS its step with the measured reason. Blender discovery: `--blender` →
`EEZE_BLENDER` → PATH → newest `C:/Program Files/Blender Foundation/Blender */blender.exe`.
The agent runs the same CLI through `run_script` (gated `install_exec`); demo task
`tasks/render3d-agent.yaml`.

### Creative writer (C3) — a goal in plain language

```bash
uv run eeze spec video "<goal>" --sources artifacts/creative/sources --out artifacts/creative/c3-video --run
uv run eeze spec 3d    "<goal>" --out artifacts/creative/c3-3d --run
```

`brains/specwriter.py` asks a model (default: the hard tier — `EEZE_SPEC_MODEL` →
`EEZE_PLANNER_MODEL`, i.e. Sol) for ONE JSON spec and refuses to trust it blindly: the
vocabulary in the prompt is generated from the verticals' code (`verticals/video/vocab.py`,
`verticals/render3d/vocab.py`) and a test locks every listed op/required field against the
pydantic validators; the reply is validated by the vertical's own spec model; feasibility is
checked against ffprobe facts of the real sources (exact paths, kinds, trims past the end); a
rejection is fed back to the model (≤3 attempts) and every attempt lands in
`write-report.json`. The writer never executes: `--run` hands the spec to the vertical, whose
steps are verified again. The agent path is `tasks/creative-goal-agent.yaml` (script-only,
gated `install_exec` — the whole creative chain behind one user click).

## Routines (F4)

Scheduled runs live in `~/.eeze/eeze.db` (`routines`, `routine_runs`) and are executed by
the API daemon's scheduler (30 s tick) as detached `eeze routines run <id>` processes —
the daemon must be running for schedules to fire.

```bash
uv run eeze routines add invoices --kind invoices --schedule daily:08:00 \
    --email-summary --email-to you@example.com     # daily invoice scan + GATED email
uv run eeze routines add demo --kind task --schedule every:2 --task tasks/notepad-gated-demo.yaml
uv run eeze routines run invoices        # run now (foreground)
uv run eeze routines history invoices    # run records (status, approval_id, detail)
uv run eeze routines resume <approval_id>  # continue a gated email step (usually auto)
```

- The `email_summary` step is risk class **`external_send`** → it pauses and appears in
  `/approvals`; approving it auto-resumes via the payload's `resume_argv`
  (`routines resume <id>`), sends the ledger + anomalies, and closes the run record.
- Add `"allow": ["external_send"]` to a routine's params (CLI: `--allow external_send`)
  to skip the gate for that routine.
- The scheduler never stacks runs: a routine with a run in flight or parked at the gate
  is postponed (`has_open_run`).

## Brains (v2 — pluggable)

The loop's tactical brain is a 2-method port (`select_element`, `verify`). Two
implementations ship:

| Brain | Backend | Notes |
| --- | --- | --- |
| `jev` (default) | TypeSafe System One | typed judgments, calibrated, ~300 ms, `TYPESAFE_API_KEY` |
| `llm` | any OpenAI-compatible endpoint | `EEZE_BRAIN_BASE_URL/API_KEY/MODEL` (falls back to `EEZE_PLANNER_*`); ~1.3–2.7 s/judgment, confidence is self-reported |

Selection order: explicit `name` → `EEZE_BRAIN` env → `agents.yaml` → the agent's
`model.brain` → `jev`. Example (same task, other brain):

```bash
EEZE_BRAIN=llm uv run eeze run tasks/notepad-gated-demo.yaml --allow install_exec --runs 1
```

The gate, risk classes, approvals and thresholds are brain-independent — a weaker brain
retries and pauses more, it never bypasses the policy.

### Model router (v2 — Luna routine / Sol hard)

When the brain is `llm`, the MODEL is decided per run: pin (`model=` / `EEZE_BRAIN_MODEL`) →
`agents.yaml` `model.tier` → escalation (a failed run moves one tier up) → **Jev** (typed
Choice over the tiers) → **rules floor** (deterministic signals; the fallback for every Jev
refusal/error). Tiers default to `openai/gpt-6-luna` (routine) and `openai/gpt-6-sol` (hard);
`agents.yaml` `model.tiers` overrides them, `EEZE_ROUTER=off|rules|jev` sets the mode.
Every run journals `model_route` and `summary.models` carries per-model calls/tokens/cost
(`core/pricing.py`). Full design + live measurements: `docs/ROUTER.md`.

```bash
EEZE_BRAIN=llm uv run eeze run tasks/notepad_save_as.yaml --runs 1   # Jev routes; failures escalate
```

### Named agents (v2)

`agents.yaml` ships three agents demonstrating the office model: `default`
(generalist), `finance` (local writes; sends gated) and `ops` (strictly read-only,
brain `llm`). Same task, different agent ⇒ different policy lane and brain:

```bash
uv run eeze run tasks/notepad-gated-demo.yaml --agent finance --allow install_exec  # runs through
uv run eeze run tasks/notepad-gated-demo.yaml --agent ops                          # pauses per risky step; approve in /approvals
uv run eeze routines add nightly --kind task --agent finance --schedule daily:02:00 --task tasks/x.yaml
```

Per-agent policy = `permissions.risk_classes`; approvals carry the agent id; runs,
journals, costs and metrics are all scoped by `agent_id` (the Team page shows them live).

**Creating agents from the UI (v2).** The Team page's *Create Agent* wizard writes
user-level agents to `~/.eeze/agents.yaml` (repo agents are read-only): the wizard maps
its permission toggles to risk classes, lets you pick the tactical brain (Jev / LLM),
and the new agent appears in the selector and on the Team page with a remove button
(user-level only). Runtime merge: repo `agents.yaml` + user file (user wins per id).
The agent detail page has an Edit dialog (name, role, description, risk classes, brain);
editing a built-in creates a user-level override — removing it restores the built-in.

**Approval notifications.** When a run pauses, the daemon's `ApprovalWatcher`
(`core/notify.py`) shows a Windows toast ("Eeze needs an approval — <agent> paused at
step '<step>' (<risk>)") — deliberately non-focus-stealing. Toasts use PowerShell + WinRT
(zero pip deps); failures are swallowed and retried on the next tick, and toasted ids are
deduped in the settings table (`notified_approvals`) so restarts don't re-notify. Toggle:
`POST /api/setup/notify` (or the Notifications card on the Setup page); state shows in
`GET /api/system/status` as `notifications_enabled`.

## Tests & checks

```bash
uv run pytest           # backend suite
bash scripts/check.sh   # ruff + pytest
cd ui && npm run lint   # frontend eslint
```

