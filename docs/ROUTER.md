# Model router — Luna for routine work, Sol for hard work (2026-09-23)

Founder policy: DeepSeek is retired. Two tiers, and **Jev decides which one runs**:

| Tier | Model | Price (per M) | Measured per judgment | For |
| --- | --- | --- | --- | --- |
| `routine` | `openai/gpt-6-luna` | $0.10 / $0.50 | ~1.1k tokens → **$0.00012** | mail/invoice extraction, simple fills, short script-driven repeats |
| `hard` | `openai/gpt-6-sol` | $2 / $10 | ~1.1k tokens → **$0.00230** | multi-window GUI workflows, goal planning/replanning, authoring strict video/3D specs |

`src/eeze_agent/brains/router.py` · wiring in `brains/registry.py` (`make_brain(task=...)`) ·
escalation + `model_route` journaling in `core/loop.py` · per-model cost in `core/pricing.py`.

## Decision order (first match wins)

1. **Pin** — `make_brain(model=...)` or `EEZE_BRAIN_MODEL` — the router never overrides a pin.
2. **`agents.yaml`** → `model.tier` (force a tier per agent; `model.tiers` overrides the models).
3. **Escalation** — the previous run of this run-set FAILED → one tier up (deterministic, capped).
4. **Jev** — a typed `Choice` over the tier set (`EEZE_ROUTER=jev`, the default).
5. **Rules floor** — deterministic signals; also the fallback whenever Jev errors, refuses,
   or answers below `JEVI_CONFIDENCE_FLOOR` (0.6). Source is journaled as `rules-fallback`
   with the reason — never silent.

`EEZE_ROUTER=off` disables routing (the `llm` brain then uses its env model);
`EEZE_ROUTER=rules` never calls Jev.

## What was measured (2026-09-23, all live)

**Jev can route** — typed Choice over the tiers, 4/4 correct on the first probe:
mail/invoices → `luna` (0.97), Notepad fill → `luna` (0.94), "spec 3D + MP4/GLB" → `sol` (0.99),
stuck GUI run → `sol` (0.99); 137–349 ms and ~550 tokens → **~$0.000023 per decision**.

**Judgment quality/cost** (same real Notepad capture, same payload, code path `LlmBrain`):

| Model | select | verify | per cycle (select+verify) | select confidence |
| --- | --- | --- | --- | --- |
| `deepseek/deepseek-chat` (retired) | 1.2–7.1 s | 2.2–6.7 s | ~$0.00070 | 0.95 |
| `openai/gpt-6-luna` | 1.7–1.9 s | 1.3–2.7 s | ~$0.00025 | 1.0 |
| `openai/gpt-6-sol` | 1.3 s | 1.8 s | ~$0.00466 | 0.99 |

Sol at its DEFAULT reasoning effort is fast (1.3 s; 0 reasoning tokens) — the ~102 s
time-to-first-token figure only applies at max effort, which the `llm` brain never requests.

**Same task, both tiers, real runs** (`tasks/notepad_save_as.yaml`, 5 GUI steps incl. a Save
dialog; Sol by rules-fallback, Luna by rules):

| | `sol` run | `luna` run |
| --- | --- | --- |
| status | done | done |
| judgments | 6 | 6 |
| select confidence min | 0.99 | 1.0 |
| est. cost | $0.023178 | **$0.0011988** |

19.3× cheaper, same outcome → the policy is: **cheap tier first, escalate on real failure**.

**Escalation, proven live** (a task whose check can never pass, `--runs 2`):

```
model_route    run 1  routine  luna  source=rules-fallback  (jev confidence 0.18 < 0.6)
run 1 FAIL → model_escalated  routine -> hard (luna -> sol)
model_route    run 2  hard     sol   source=escalated
```

summary: `success_rate 0/2`, `models`: luna 1 call $0.0001201 · sol 1 call $0.0022917.

**What Jev actually reads matters.** With the raw concatenated task text, a *script-only*
task (video-edit) looked "hard" (0.63–0.75 confidence). With the step counts in prose
("Task 'video-edit-agent' — 0 GUI steps, 1 script steps: …") Jev answered `routine` at
0.77–0.86 — the counts are the fact it needs. Prose summaries are what the router sends.

## Tuning knobs (policy guesses, each with a safety net)

- `SMALL_GUI_STEPS = 5` — GUI tasks up to this size default to the cheap tier; bigger flows go
  hard. The escalation ladder is the net when a cheap-tier run fails.
- `JEVI_CONFIDENCE_FLOOR = 0.6` — below it, the rules floor decides. On genuinely borderline
  tasks (a 5-step Save-As flow) Jev abstains at 0.18–0.31 rather than guessing — the floor
  then says "large GUI workflow" or "small GUI task" deterministically. This is honest
  calibration, not a failure.
- `HARD_MARKERS` / `ROUTINE_MARKERS` — word-boundary marker lists over task name + app +
  step ids/intents (`blender`, `3d`, `video`, `spec`, … / `invoice`, `mailbox`, `csv`, …).
- Markers are checked after: script-only (no judgments → tier unused) → hard markers →
  routine markers → GUI size.

## Honest limits

- Routing is **per run**, not per cycle; a mid-run model change only happens through
  escalation between runs of a run-set.
- Jev's routing sample is small (4 probe tasks + 2 real runs); the rules floor exists
  precisely because that record is thin.
- Thresholds above are policy, not measurement; the first real luna failures should tune
  them (the journal carries everything needed).
- OpenRouter's 90%-off cached-input discount is not exploited yet — it would mostly help sol
  (shared prompt prefix), worth revisiting if hard-tier usage grows.
- The extractor brain (`EEZE_EXTRACT_*`, the local Hermes gateway) is deliberately NOT routed:
  it is high-volume (≈300k tokens/run) and rides the user's own quota.
