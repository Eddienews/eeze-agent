"""The observe → decide → act → verify loop (F1 walking skeleton).

One step = one cycle: fresh capture → Jev judgment (closed sets) → driver action
(background-first, escalation only on a returned signal) → verification
(deterministic code checks and/or a Jev Noul over a fresh capture).

The loop is code-owned; Jev only answers typed questions (see docs/ARCHITECTURE.md).
Every event is journaled with the run's ``agent_id`` (ADR-0002).
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from eeze_agent.agents.models import AgentContext
from eeze_agent.core import checks as checks_mod
from eeze_agent.core import risk as risk_mod
from eeze_agent.core.approvals import approval_digest
from eeze_agent.core.journal import RunJournal
from eeze_agent.core.spend import BudgetExceeded
from eeze_agent.core.models import (
    Candidate,
    Observation,
    RunResult,
    StepResult,
    StepSpec,
    TaskSpec,
)

SET_TEXT_ROLES = {"edit", "combobox", "document"}
CLICK_ROLES = {
    "button", "menuitem", "listitem", "tabitem", "splitbutton",
    "checkbox", "radiobutton", "treeitem",
}
MAX_CANDIDATES = 20
NOUL_THRESHOLD = 0.5
STATE_ROWS_CAP = 140


class StepError(RuntimeError):
    """Recoverable step failure (retryable). May carry evidence in ``detail``."""

    def __init__(self, message: str, detail: dict | None = None) -> None:
        super().__init__(message)
        self.detail: dict = detail or {}


class InterferenceError(RuntimeError):
    """State changed in a way our action cannot explain — external input.

    On this signal the run stops immediately and is excluded from the success
    metric (reported separately): we never retry blindly over foreign input.
    Incident: the "v-storm", 2026-09-18 — see docs/SPIKES.md.
    """


class NeedsApproval(RuntimeError):
    """F2 gate: the step's risk class is not allowed and has no active grant.

    The run-set pauses here (state persisted by ``run_set``); approval + resume are
    explicit user actions — the gate never auto-approves and never auto-corrects.
    """

    def __init__(
        self,
        *,
        run_index: int,
        step_index: int,
        step_id: str,
        risk_class: str,
        reason: str,
        action: str = "",
        approval_id: str | None = None,
        partial_steps: list[dict] | None = None,
        vars: dict | None = None,
    ) -> None:
        super().__init__(f"approval required: {step_id} ({risk_class}) — {reason}")
        self.run_index = run_index
        self.step_index = step_index
        self.step_id = step_id
        self.risk_class = risk_class
        self.reason = reason
        self.action = action
        self.approval_id = approval_id
        self.partial_steps = partial_steps or []
        self.vars = vars or {}


@dataclass
class RunState:
    pid: int | None = None
    wid: int | None = None


class _KeepMissing(dict):
    """``format_map`` helper: an unknown ``{name}`` stays literally in the text."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def render(template: str, vars: dict) -> str:
    """Fill ``{name}`` placeholders from ``vars``.

    Previously ANY unknown placeholder (common in ffmpeg filters and PowerShell blocks) made
    the whole template come back unrendered — ``{run_dir}`` included — and a stray ``{``
    raised. Now known names are always substituted and everything else is left as written.
    """
    try:
        return template.format_map(_KeepMissing(vars))
    except (ValueError, IndexError, KeyError, AttributeError, TypeError):
        return _PLACEHOLDER.sub(
            lambda m: str(vars[m.group(1)]) if m.group(1) in vars else m.group(0), template)


def _rendered_for_gate(step: StepSpec, vars: dict) -> StepSpec:
    """The step as it will execute (templates filled) — what the risk gate must judge."""
    update = {}
    for field in ("command", "cwd", "text", "intent"):
        value = getattr(step, field)
        if isinstance(value, str) and value:
            update[field] = render(value, vars)
    if step.menu:
        update["menu"] = [render(x, vars) for x in step.menu]
    return step.model_copy(update=update) if update else step


def retry_backoff_s(attempt_no: int) -> float:
    """Pause before attempt ``attempt_no + 1``: 1 s, 2 s, 4 s … capped at 8 s.

    Back-to-back retries hammered rate-limited providers and re-clicked UIs that had not
    settled. ``EEZE_RETRY_BACKOFF_S`` scales the base (``0`` disables, e.g. in tests).
    """
    try:
        base = float(os.environ.get("EEZE_RETRY_BACKOFF_S", "1") or 0)
    except ValueError:
        base = 1.0
    return min(8.0, max(0.0, base) * (2 ** max(0, attempt_no - 1)))


def build_candidates(
    obs: Observation, roles: set[str], label_contains: str | None = None
) -> list[Candidate]:
    out: list[Candidate] = []
    needle = (label_contains or "").lower()
    for e in obs.elements or []:
        role = str(e.get("role", "")).lower()
        if role not in roles or not e.get("enabled"):
            continue
        if needle and needle not in str(e.get("label") or "").lower():
            continue
        tok = e.get("element_token")
        if not tok:
            continue
        label = str(e.get("label") or "").strip() or "(unlabeled)"
        out.append(
            Candidate(
                id=f"c{e.get('element_index')}",
                role=str(e.get("role")),
                label=label,
                element_index=int(e.get("element_index") or 0),
                token=str(tok),
                frame=e.get("frame"),
            )
        )
        if len(out) >= MAX_CANDIDATES:
            break
    return out


STATE_VALUE_CAP = 1000  # chars kept per element value in the Jev state
# A restored Notepad session can put a whole document into one element's value;
# unbounded values blow the Jev request (live: `max_tokens_exceeded`, 400) — the
# state must stay bounded no matter what the window contains.


def _cap_value(value: object, cap: int = STATE_VALUE_CAP) -> object:
    if not isinstance(value, str) or len(value) <= cap:
        return value
    return f"{value[:cap]}…[+{len(value) - cap} more chars]"


def build_state(obs: Observation, *, goal: str) -> dict:
    rows = [
        {
            "i": e.get("element_index"),
            "role": e.get("role"),
            "label": e.get("label"),
            "value": _cap_value(e.get("value")),
        }
        for e in (obs.elements or [])[:STATE_ROWS_CAP]
    ]
    return {"goal": goal, "window": obs.window_title or obs.app_name, "elements": rows}


def _find_token(obs: Observation, cand: Candidate) -> str | None:
    for e in obs.elements or []:
        if (
            str(e.get("role")) == cand.role
            and str(e.get("label") or "").strip() == cand.label
        ):
            return e.get("element_token")
    return None


def _readback(obs: Observation, cand: Candidate) -> str | None:
    for e in obs.elements or []:
        if (
            str(e.get("role")) == cand.role
            and str(e.get("label") or "").strip() == cand.label
        ):
            return e.get("value")
    return None


def _write_text_ladder(
    *,
    driver,
    ctx: AgentContext,
    pid: int,
    wid: int,
    cand: Candidate,
    text: str,
    journal: RunJournal,
    run_ix: int,
    step_id: str,
    allow_foreground: bool,
) -> tuple[bool, str, bool]:
    """Robustly set an element's text; returns (ok, method, interference).

    Rungs (each followed by a fresh-capture readback against label+role identity):
      1. set_value on a fresh token        (canonical UIA ValuePattern write)
      2. pixel double-click + type_text    (word-select then replace — shell dialog edits)
      3. click + type_text                 (append semantics; correct for empty fields)
      4. pixel drag right-to-left + type   (select-all fallback)
      5. backspaces + type_text            (slow last resort)
      6. optional foreground variant       (only when the task allows it)

    State-consistency gate: every readback is classified — ``ok`` (target text),
    ``noop`` (previous value), ``append`` (previous + text), or a mutation our
    action cannot explain (``foreign_mutation`` / ``unexpected_change``). The last
    two are external input noise: journaled as ``external_input_detected`` and
    surfaced as the third return value so the run stops without blind retries.
    """

    def attempt(rung: str, act) -> tuple[bool, bool]:
        """Returns (ok, interference)."""
        obs = driver.capture(ctx, pid, wid)
        tok = _find_token(obs, cand)
        pre = _readback(obs, cand)
        pre_s = None if pre is None else str(pre)
        if tok is None:
            journal.event("write_rung", run_index=run_ix, step_id=step_id, rung=rung,
                          result="element_gone")
            return False, False
        try:
            result = act(tok)
        except Exception as exc:  # noqa: BLE001 — this rung failed; try the next one
            journal.event("write_rung", run_index=run_ix, step_id=step_id, rung=rung,
                          result="exception", error=str(exc)[:200])
            return False, False
        journal.event(
            "write_rung",
            run_index=run_ix,
            step_id=step_id,
            rung=rung,
            tool=result.tool,
            status=result.status,
            effect=result.effect,
            route=result.route,
            refusal=result.code,
            ms=result.ms,
        )
        obs2 = driver.capture(ctx, pid, wid)
        value = _readback(obs2, cand)
        value_s = None if value is None else str(value)

        if value == text:
            verdict = "ok"
        elif value == pre:
            verdict = "noop"
        elif value_s is not None and value_s == (pre_s or "") + text:
            verdict = "append"
        elif value_s is not None and text and text in value_s:
            verdict = "foreign_mutation"
        else:
            verdict = "unexpected_change"

        if verdict in {"foreign_mutation", "unexpected_change"}:
            journal.event(
                "external_input_detected",
                run_index=run_ix, step_id=step_id, rung=rung,
                element=f"{cand.role} {cand.label!r}",
                before=(pre_s or "")[:120], after=(value_s or "")[:160],
                expected=text[:120],
            )
            return False, True

        journal.event("write_rung", run_index=run_ix, step_id=step_id, rung=rung,
                      result=verdict, value=(value_s or "")[:80])
        return verdict == "ok", False

    # rung 1: set_value
    ok1, if1 = attempt("set_value", lambda tok: driver.set_text(ctx, pid, wid, tok, text))
    if ok1 or if1:
        return ok1, "set_value", if1

    fr = cand.frame or {}
    cx = int(fr.get("x", 0)) + int(fr.get("w", 0)) // 2
    cy = int(fr.get("y", 0)) + int(fr.get("h", 0)) // 2

    # rung 2: pixel double-click (word select) + type_text
    if fr.get("w"):
        def rung2(_tok: str):
            driver.click(ctx, pid, wid, x=cx, y=cy, count=2)
            return driver.type_text(ctx, pid, wid, text)

        ok2, if2 = attempt("wselect+type_text", rung2)
        if ok2 or if2:
            return ok2, "wselect+type_text", if2

    # rung 3: click + type_text (append; correct when the field is empty)
    def rung3(tok: str):
        driver.click(ctx, pid, wid, tok)
        return driver.type_text(ctx, pid, wid, text)

    ok3, if3 = attempt("click+type_text", rung3)
    if ok3 or if3:
        return ok3, "click+type_text", if3

    # rung 4: pixel drag right-to-left (select all) + type_text
    if fr.get("w"):
        def rung4(_tok: str):
            driver.click(ctx, pid, wid, x=cx, y=cy)
            driver.drag(
                ctx, pid, wid,
                from_x=int(fr.get("x", 0)) + int(fr.get("w", 0)) - 6, from_y=cy,
                to_x=int(fr.get("x", 0)) + 3, to_y=cy,
            )
            return driver.type_text(ctx, pid, wid, text)

        ok4, if4 = attempt("dragsel+type_text", rung4)
        if ok4 or if4:
            return ok4, "dragsel+type_text", if4

    # rung 5: backspaces + type_text (slow last resort)
    def rung5(_tok: str):
        obs_now = driver.capture(ctx, pid, wid)
        current = str(_readback(obs_now, cand) or "")
        for _ in range(min(len(current) + 2, 80)):
            driver.press_key(ctx, pid, wid, "backspace")
        return driver.type_text(ctx, pid, wid, text)

    ok5, if5 = attempt("backspace+type_text", rung5)
    if ok5 or if5:
        return ok5, "backspace+type_text", if5

    if allow_foreground and fr.get("w"):
        def rung6(_tok: str):
            driver.click(ctx, pid, wid, x=cx, y=cy, count=2, delivery_mode="foreground")
            return driver.type_text(ctx, pid, wid, text)

        ok6, if6 = attempt("fg_wselect+type_text", rung6)
        if ok6 or if6:
            return ok6, "fg_wselect+type_text", if6

    return False, "none", False


def _resolve_window(driver, ctx: AgentContext, step: StepSpec, state: RunState) -> tuple[int, int]:
    if step.window:
        w = driver.main_window(ctx, step.window)
        if not w:
            raise StepError(f"window not found: {step.window!r}")
        return int(w["pid"]), int(w["window_id"])
    if state.pid and state.wid:
        return state.pid, state.wid
    raise StepError("no main window for task step")


def _verify_step(
    *,
    step: StepSpec,
    vars: dict,
    driver,
    brain,
    journal: RunJournal,
    run_ix: int,
    ctx: AgentContext,
    pid: int,
    wid: int,
) -> tuple[bool, str]:
    reasons: list[str] = []
    ok = True
    has_window = bool(pid) and bool(wid)

    if step.verify_code:
        for expr in step.verify_code.split(";"):
            expr = expr.strip()
            if not expr:
                continue
            obs = None
            kind = expr.split("|")[0]
            if kind in {"doc_equals", "field_equals"}:
                if not has_window:
                    reasons.append(f"code:{expr} -> False (needs a window; script step)")
                    ok = False
                    continue
                obs = driver.capture(ctx, pid, wid)
            rendered = render(expr, vars)
            passed, why = checks_mod.run_check(rendered, obs=obs, driver=driver, ctx=ctx)
            reasons.append(f"code:{rendered} -> {passed} ({why})")
            ok = ok and passed

    if step.verify_jev:
        if not has_window:
            journal.event(
                "verify_jev_skipped", run_index=run_ix, step_id=step.id,
                reason="no window (script step) — jev verification needs a capture",
            )
            reasons.append("jev:skipped(no window)")
        else:
            obs = driver.capture(ctx, pid, wid)
            statement = render(step.verify_jev, vars)
            j = brain.verify(ctx, statement=statement, state=build_state(obs, goal=statement))
            journal.event(
                "judgment",
                run_index=run_ix,
                step_id=step.id,
                judgment_kind=j.kind,
                question=j.question,
                noul=j.noul,
                ms=j.ms,
                tokens=j.tokens,
                model=j.model,
                request_id=j.request_id,
            )
            passed = (j.noul or 0.0) >= NOUL_THRESHOLD
            reasons.append(f"jev:{j.noul} -> {passed}")
            ok = ok and passed

    return ok, "; ".join(reasons) if reasons else "no verification configured"


def _run_script_step(
    *,
    step: StepSpec,
    journal: RunJournal,
    run_ix: int,
    vars: dict,
    state: RunState,
) -> dict:
    """Execute one ``run_script`` step (no window). Raises StepError on failure."""
    from eeze_agent.core.script import run_command

    if not (step.command or "").strip():
        raise StepError(f"run_script step {step.id!r} has no command")
    command = render(step.command or "", vars)
    run_dir = journal.run_dir(run_ix).resolve()
    cwd = Path(render(step.cwd, vars)).resolve() if step.cwd else run_dir
    if not cwd.is_relative_to(run_dir):
        raise StepError(f"run_script cwd is outside the run directory: {cwd}")
    cwd.mkdir(parents=True, exist_ok=True)
    if not cwd.is_dir():
        raise StepError(f"run_script cwd is not a directory: {cwd}")
    log_path = journal.run_dir(run_ix) / f"step-{step.id}.log"
    result = run_command(command, cwd=cwd, timeout_s=step.timeout_s, log_path=log_path)
    journal.event(
        "action", run_index=run_ix, step_id=step.id, tool="run_script",
        status="ok" if result.ok else "failed",
        effect=f"exit={result.exit_code}" + (" timeout" if result.timed_out else ""),
        ms=result.duration_ms, command=command[:400], cwd=str(cwd),
        log=str(result.log_path.relative_to(journal.dir)) if result.log_path else "",
    )
    if result.artifacts:
        journal.event(
            "script_artifacts", run_index=run_ix, step_id=step.id,
            count=len(result.artifacts),
            files=[a["path"] for a in result.artifacts],
        )
    detail = {
        "exit_code": result.exit_code,
        "timed_out": result.timed_out,
        "log": str(result.log_path.relative_to(journal.dir)) if result.log_path else "",
        "artifacts": len(result.artifacts),
    }
    if result.timed_out:
        raise StepError(
            f"command timed out after {step.timeout_s}s — {command[:160]}", detail=detail
        )
    if result.exit_code != 0:
        tail = (result.stderr_tail or result.stdout_tail).strip()
        lines = tail.splitlines()
        last = lines[-1] if lines else ""
        raise StepError(
            f"command exited with code {result.exit_code}"
            + (f": {last[:200]}" if last else ""),
            detail=detail,
        )
    return detail


def execute_step(
    *,
    task: TaskSpec,
    step: StepSpec,
    ctx: AgentContext,
    driver,
    brain,
    journal: RunJournal,
    state: RunState,
    run_ix: int,
    vars: dict,
    demo: bool,
) -> StepResult:
    t0 = time.perf_counter()
    detail: dict = {}
    attempts_allowed = max(1, step.retries + 1)

    for attempt_no in range(1, attempts_allowed + 1):
        journal.event("step_attempt", run_index=run_ix, step_id=step.id, attempt=attempt_no)
        obs: Observation | None = None
        try:
            if step.action == "run_script":
                pid, wid = 0, 0
                detail.update(
                    _run_script_step(
                        step=step, journal=journal, run_ix=run_ix, vars=vars, state=state
                    )
                )
            else:
                pid, wid = _resolve_window(driver, ctx, step, state)

            if step.action in {"set_text", "click"}:
                obs = driver.capture(ctx, pid, wid)
                journal.event(
                    "observation", run_index=run_ix, step_id=step.id,
                    window=obs.window_title, elements=len(obs.elements),
                    degraded=obs.degraded, ms=obs.ms,
                )
                roles = SET_TEXT_ROLES if step.action == "set_text" else CLICK_ROLES
                label_contains = None
                if step.candidate_filter:
                    if step.candidate_filter.get("roles"):
                        roles = {str(r).lower() for r in step.candidate_filter["roles"]}
                    label_contains = step.candidate_filter.get("label_contains")
                cands = build_candidates(obs, roles, label_contains)
                intent = render(step.intent, vars)
                sel = brain.select_element(
                    ctx,
                    intent=intent,
                    state=build_state(obs, goal=intent),
                    candidates=cands,
                )
                journal.event(
                    "judgment", run_index=run_ix, step_id=step.id, judgment_kind=sel.kind,
                    question=sel.question, answer=sel.answer, confidence=sel.confidence,
                    probabilities=sel.probabilities, ms=sel.ms, tokens=sel.tokens,
                    model=sel.model, request_id=sel.request_id,
                    options=[c.describe() for c in cands],
                )
                chosen = next((c for c in cands if c.id == sel.answer), None)
                if chosen is None:
                    raise StepError(f"selection {sel.answer!r} is not a candidate")
                detail["selected"] = f"{chosen.role} {chosen.label!r}"

                if step.action == "set_text":
                    ok, method, interference = _write_text_ladder(
                        driver=driver, ctx=ctx, pid=pid, wid=wid, cand=chosen,
                        text=render(step.text or "", vars), journal=journal,
                        run_ix=run_ix, step_id=step.id,
                        allow_foreground=task.allow_foreground,
                    )
                    detail["write_method"] = method
                    if interference:
                        raise InterferenceError(
                            f"external interference during {method} on {chosen.role} {chosen.label!r}"
                        )
                    if not ok:
                        raise StepError("write failed in all rungs")
                else:
                    result = driver.click(ctx, pid, wid, chosen.token)
                    journal.event(
                        "action", run_index=run_ix, step_id=step.id, tool=result.tool,
                        status=result.status, effect=result.effect, route=result.route,
                        refusal=result.code, ms=result.ms,
                    )
                    if result.code == "window_minimized":
                        restore = driver.restore_window(ctx, pid, wid)
                        journal.event(
                            "action", run_index=run_ix, step_id=step.id, tool=restore.tool,
                            status=restore.status, effect=restore.effect, route=restore.route,
                            refusal=restore.code, ms=restore.ms, note="window_minimized recovery",
                        )
                        if restore.refused:
                            raise StepError(f"window still minimized: {restore.code}")
                        pid, wid = _resolve_window(driver, ctx, step, state)
                        obs_retry = driver.capture(ctx, pid, wid)
                        tok_retry = _find_token(obs_retry, chosen)
                        if tok_retry is None:
                            raise StepError("element not found after window restore")
                        result = driver.click(ctx, pid, wid, tok_retry)
                        journal.event(
                            "action", run_index=run_ix, step_id=step.id, tool=result.tool,
                            status=result.status, effect=result.effect, route=result.route,
                            refusal=result.code, ms=result.ms, retried=True,
                        )
                    if result.needs_escalation and task.allow_foreground:
                        result = driver.click(ctx, pid, wid, chosen.token, delivery_mode="foreground")
                        journal.event(
                            "action", run_index=run_ix, step_id=step.id, tool=result.tool,
                            status=result.status, effect=result.effect, route=result.route,
                            refusal=result.code, ms=result.ms, escalated=True,
                        )
                    if result.refused and not task.allow_foreground:
                        raise StepError(f"click refused: {result.code}")

            elif step.action == "invoke_menu":
                result = driver.invoke_menu(ctx, pid, wid, [render(x, vars) for x in (step.menu or [])])
                journal.event(
                    "action", run_index=run_ix, step_id=step.id, tool=result.tool,
                    status=result.status, effect=result.effect, route=result.route,
                    refusal=result.code, ms=result.ms,
                )
                if result.refused:
                    raise StepError(f"invoke_menu refused: {result.code}: {result.refusal_message}")

            elif step.action == "hotkey":
                result = driver.hotkey(ctx, pid, wid, step.keys or [])
                journal.event(
                    "action", run_index=run_ix, step_id=step.id, tool=result.tool,
                    status=result.status, effect=result.effect, route=result.route,
                    refusal=result.code, ms=result.ms,
                )
                if result.refused:
                    raise StepError(f"hotkey refused: {result.code}")

            elif step.action not in {"check", "run_script"}:
                raise StepError(f"unknown action {step.action!r}")

            if obs is not None and step.action != "set_text":
                # state fingerprint around non-text actions (evidence-only;
                # see "Coexistence with Human and System Activity" in ARCHITECTURE)
                try:
                    post = driver.capture(ctx, pid, wid)
                    journal.event(
                        "state_sig", run_index=run_ix, step_id=step.id,
                        pre=_state_sig(obs), post=_state_sig(post),
                        pre_elements=len(obs.elements), post_elements=len(post.elements),
                    )
                except Exception as exc:  # noqa: BLE001 — evidence-only, never fatal
                    journal.event("state_sig_failed", run_index=run_ix, step_id=step.id,
                                  error=str(exc)[:160])

            ok, why = _verify_step(
                step=step, vars=vars, driver=driver, brain=brain, journal=journal,
                run_ix=run_ix, ctx=ctx, pid=pid, wid=wid,
            )
            detail["verify"] = why
            if ok:
                if demo and step.action != "run_script":
                    try:
                        shot = driver.capture(ctx, pid, wid, screenshot=True)
                        if shot.screenshot_png_b64:
                            journal.save_png(run_ix, f"step-{step.id}.png", shot.screenshot_png_b64)
                    except Exception as exc:  # noqa: BLE001 — best-effort artifact
                        journal.event("demo_capture_failed", run_index=run_ix,
                                      step_id=step.id, error=str(exc)[:160])
                ms = round((time.perf_counter() - t0) * 1000, 1)
                journal.event("step_end", run_index=run_ix, step_id=step.id, ok=True,
                              attempts=attempt_no, ms=ms, **{k: str(v) for k, v in detail.items()})
                return StepResult(step_id=step.id, attempts=attempt_no, ok=True, detail=detail, ms=ms)

        except InterferenceError as exc:
            # state-consistency gate: stop this run; never retry over foreign input
            detail["interference"] = str(exc)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            journal.event("step_end", run_index=run_ix, step_id=step.id, ok=False,
                          interference=True, attempts=attempt_no, ms=ms,
                          **{k: str(v) for k, v in detail.items()})
            return StepResult(step_id=step.id, attempts=attempt_no, ok=False,
                              interference=True, detail=detail, ms=ms)
        except Exception as exc:  # noqa: BLE001 — retryable by design
            detail["error"] = f"{type(exc).__name__}: {exc}"
            for key, value in getattr(exc, "detail", {} or {}).items():
                detail.setdefault(key, value)
            journal.event("step_error", run_index=run_ix, step_id=step.id,
                          attempt=attempt_no, error=detail["error"])
            if step.action == "run_script" and getattr(exc, "detail", {}).get("timed_out"):
                # A script that hit its hard timeout will hit it again: retrying only turned
                # a 2-minute failure into a 6-minute one.
                attempts_allowed = attempt_no
                break
            if attempt_no < attempts_allowed:
                time.sleep(retry_backoff_s(attempt_no))

    ms = round((time.perf_counter() - t0) * 1000, 1)
    journal.event("step_end", run_index=run_ix, step_id=step.id, ok=False,
                  attempts=attempts_allowed, ms=ms, **{k: str(v) for k, v in detail.items()})
    return StepResult(step_id=step.id, attempts=attempts_allowed, ok=False, detail=detail, ms=ms)


def _state_sig(obs: Observation) -> str:
    """Short fingerprint of the interactive state (role/label/value rows)."""
    rows = []
    for e in obs.elements or []:
        role = str(e.get("role", "")).lower()
        if role in {"button", "edit", "combobox", "document", "menuitem", "listitem", "tabitem"}:
            rows.append(f"{role}|{e.get('label') or ''}|{str(e.get('value'))[:40]}")
    return hashlib.sha1("\n".join(sorted(rows)).encode("utf-8", "replace")).hexdigest()[:12]


def _ensure_isolated(
    *,
    driver,
    ctx: AgentContext,
    journal: RunJournal,
    task: TaskSpec,
    state: RunState,
) -> None:
    """Pre-run isolation for a dedicated window (incident hardening, --isolated).

    - kills leftover target-app instances that are OURS (title markers only),
    - launches fresh; if the app restored old tabs (title not "Untitled"), stops the
      app FIRST (a running app keeps locking/rewriting its session store), then moves
      the store aside (never deleted) and relaunches — retried once,
    - verifies: exactly one target-app window, untitled, empty document.
    Raises StepError when the environment cannot be isolated.
    """
    import subprocess as _sp

    def app_wins() -> list[dict]:
        return [
            w for w in driver.list_windows(ctx)
            if task.app.lower() in str(w.get("title", "")).lower()
        ]

    def kill_pid(pid: int | None) -> None:
        if not pid:
            return
        _sp.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)
        for _ in range(10):
            r = _sp.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, check=False,
            )
            if str(pid) not in r.stdout:
                return
            time.sleep(0.3)

    def launch_fresh() -> None:
        l = driver.launch(ctx, name=task.app if not task.aumid else None, aumid=task.aumid)
        state.pid = l.get("pid")
        time.sleep(1.4)
        w = driver.main_window(ctx, task.app)
        if w:
            state.pid, state.wid = int(w["pid"]), int(w["window_id"])

    def reset_store() -> bool:
        """Move the app's session store aside (never deleted). True if anything moved."""
        local = (
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Packages"
            / "Microsoft.WindowsNotepad_8wekyb3d8bbwe"
            / "LocalState"
        )
        if not local.exists():
            return False
        moved = False
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for name in ("TabState", "WindowState"):
            src = local / name
            if src.exists():
                dst = local / f"{name}.bak-eeze-{stamp}"
                try:
                    src.rename(dst)
                    moved = True
                    journal.event("isolation_store_reset", item=name, moved_to=dst.name)
                except OSError as exc:
                    journal.event("isolation_store_reset_failed", item=name,
                                  error=str(exc)[:120])
        return moved

    # 1) clear our leftovers (title markers only — never the user's own windows)
    for w in app_wins():
        title = str(w.get("title", ""))
        if any(m in title for m in ("eeze-", "notes-", "f1-")):
            journal.event("isolation_kill", pid=w.get("pid"), title=title)
            kill_pid(w.get("pid"))

    # 2) ensure a running instance
    if not app_wins():
        launch_fresh()

    w = driver.main_window(ctx, task.app)
    if w is None:
        raise StepError("isolation: target app did not launch")
    state.pid, state.wid = int(w["pid"]), int(w["window_id"])

    # 3) restored session? stop the app -> reset the store -> relaunch (retry once)
    title = str(w.get("title", ""))
    if "untitled" not in title.lower():
        for attempt in (1, 2):
            journal.event("isolation_reset_attempt", attempt=attempt, title=title)
            for k in app_wins():
                journal.event("isolation_kill", pid=k.get("pid"), title=k.get("title"))
                kill_pid(k.get("pid"))
            state.pid = state.wid = None
            reset_store()
            launch_fresh()
            w = driver.main_window(ctx, task.app)
            if w is None:
                raise StepError("isolation: relaunch failed after session-store reset")
            state.pid, state.wid = int(w["pid"]), int(w["window_id"])
            title = str(w.get("title", ""))
            if "untitled" in title.lower():
                break

    wins = app_wins()
    obs = driver.capture(ctx, state.pid, state.wid)
    doc = next(
        (e for e in (obs.elements or []) if str(e.get("role", "")).lower() == "document"),
        None,
    )
    doc_value = str(doc.get("value") or "") if doc else ""
    ok = len(wins) == 1 and "untitled" in title.lower() and doc_value == ""
    journal.event("isolation_check", instances=len(wins), title=title,
                  doc_chars=len(doc_value), ok=ok)
    if not ok:
        raise StepError(
            f"isolation failed: instances={len(wins)} title={title!r} doc_chars={len(doc_value)}"
        )


def run_once(
    *,
    task: TaskSpec,
    ctx: AgentContext,
    driver,
    brain,
    journal: RunJournal,
    state: RunState,
    run_ix: int,
    vars: dict,
    demo: bool,
    policy=None,
    approvals=None,
    task_path: Path | None = None,
    start_step_index: int = 0,
    prior_steps: list[StepResult] | None = None,
    gate_exempt: set[tuple[int, int]] | None = None,
) -> RunResult:
    t0 = time.perf_counter()
    result = RunResult(run_index=run_ix, agent_id=ctx.agent_id)
    result.steps = list(prior_steps or [])
    gate_exempt = gate_exempt or set()
    journal.event(
        "run_start", run_index=run_ix, token=vars.get("token"), path=vars.get("path"),
        resumed_from=start_step_index or None,
    )
    try:
        for step_ix, step in enumerate(task.steps):
            if step_ix < start_step_index:
                continue
            if policy is not None and (run_ix, step_ix) not in gate_exempt:
                # Classify what will actually run: ``{tool}`` with vars.tool="del /q ..." used
                # to be judged on the placeholder, not on the command it becomes.
                gated_step = _rendered_for_gate(step, vars)
                cls = risk_mod.classify_step(gated_step, task)
                granted = (
                    approvals.active_grant(ctx.agent_id, cls.risk_class, task.name)
                    if approvals is not None
                    else None
                )
                if not policy.allows(cls.risk_class) and granted is None:
                    payload = {
                        "action": step.action,
                        "intent": step.intent,
                        "text": step.text,
                        "menu": step.menu,
                        "keys": step.keys,
                        "window": step.window,
                    }
                    if step.action == "run_script":
                        payload.update(
                            {
                                "command": gated_step.command,
                                "cwd": gated_step.cwd,
                                "timeout_s": step.timeout_s,
                                "run_dir": vars.get("run_dir"),
                            }
                        )
                    approval_id = None
                    if approvals is not None:
                        approval_id = approvals.request(
                            runset_id=journal.dir.name,
                            task=task.name,
                            task_path=str(task_path) if task_path else "",
                            agent_id=ctx.agent_id,
                            run_index=run_ix,
                            step_id=step.id,
                            step_index=step_ix,
                            action=step.action,
                            risk_class=cls.risk_class,
                            reason=cls.reason,
                            payload=payload,
                            action_digest=approval_digest(
                                task=task, task_path=task_path, agent=ctx.agent,
                                runset_id=journal.dir.name, run_index=run_ix,
                                step_index=step_ix, risk_class=cls.risk_class, vars=vars,
                            ),
                        )
                        journal.event(
                            "approval_requested", run_index=run_ix, step_id=step.id,
                            approval_id=approval_id, risk_class=cls.risk_class,
                            action_digest=approvals.get(approval_id)["action_digest"],
                            reason=cls.reason, action=step.action,
                        )
                    else:
                        journal.event(
                            "approval_required_no_store", run_index=run_ix, step_id=step.id,
                            risk_class=cls.risk_class, reason=cls.reason,
                        )
                    raise NeedsApproval(
                        run_index=run_ix, step_index=step_ix, step_id=step.id,
                        risk_class=cls.risk_class, reason=cls.reason, action=step.action,
                        approval_id=approval_id,
                        partial_steps=[s.model_dump() for s in result.steps],
                        vars=vars,
                    )
                if granted is not None and not policy.allows(cls.risk_class):
                    journal.event(
                        "grant_hit", run_index=run_ix, step_id=step.id,
                        grant_id=granted["id"], risk_class=cls.risk_class,
                    )
            if step.action in {"set_text", "click"} or step.verify_jev:
                # This step asks a model: stop before spending past the agent's daily cap.
                from eeze_agent.core.spend import check_budget

                check_budget(ctx.agent)
            sr = execute_step(
                task=task, step=step, ctx=ctx, driver=driver, brain=brain,
                journal=journal, state=state, run_ix=run_ix, vars=vars, demo=demo,
            )
            result.steps.append(sr)
            if sr.interference:
                result.interference = True
                result.error = "external_input_detected"
                break
            if not sr.ok and step.fatal:
                break
        else:
            result.ok = all(s.ok for s in result.steps)
        if result.steps and result.steps[-1].ok is False and task.steps[
            min(len(result.steps) - 1, len(task.steps) - 1)
        ].fatal:
            result.ok = False
    except NeedsApproval:
        raise
    except Exception as exc:  # noqa: BLE001
        from eeze_agent.core.spend import BudgetExceeded

        if isinstance(exc, BudgetExceeded):
            raise
        result.error = f"{type(exc).__name__}: {exc}"
        journal.event("run_error", run_index=run_ix, error=result.error)

    result.cycle_ms = round((time.perf_counter() - t0) * 1000, 1)
    journal.event("run_end", run_index=run_ix, ok=result.ok, cycle_ms=result.cycle_ms)
    if demo:
        # keep the last successful capture as visual evidence
        pass
    return result


def run_set(
    *,
    task: TaskSpec,
    agent_ctx: AgentContext,
    driver,
    brain,
    journal: RunJournal,
    runs: int,
    out_dir: Path,
    demo: bool = False,
    keep_app: bool = False,
    isolated: bool = False,
    policy=None,
    approvals=None,
    task_path: Path | None = None,
    resume_state: dict | None = None,
    extra_state: dict | None = None,
    brain_factory=None,
) -> dict:
    """Run the task ``runs`` times; returns the aggregate summary dict.

    With ``policy`` provided (F2), each step is classified before execution: a class
    outside the policy (and without an active grant) PAUSES the run-set — the state is
    persisted through ``approvals`` and the summary carries ``status: needs_approval``.
    ``resume_state`` continues a paused run-set from the exact step.

    When the brain carries a router decision (``brain.route``), each run journals
    ``model_route`` — and a FAILED run escalates one tier up through ``brain_factory``
    (see `brains/router.py`); the escalation sticks for the rest of the run-set.
    """
    if resume_state is not None:
        if approvals is None or policy is None:
            raise ValueError("approval identity mismatch: resume requires the approval gate")
        partial_state = resume_state.get("partial") or {}
        try:
            step_ix = int(partial_state["step_index"])
            run_ix = int(partial_state["run_index"])
            step = task.steps[step_ix]
            if step_ix < 0 or run_ix < 1 or partial_state.get("step_id") != step.id:
                raise ValueError("invalid step")
            risk_class = risk_mod.classify_step(step, task).risk_class
            digest = approval_digest(
                task=task, task_path=task_path, agent=agent_ctx.agent,
                runset_id=journal.dir.name, run_index=run_ix, step_index=step_ix,
                risk_class=risk_class, vars=partial_state["vars"],
            )
            if resume_state.get("runset_id") != journal.dir.name:
                raise ValueError("invalid runset")
            expected_context = {
                "task_path": str(task_path) if task_path else "",
                "agent_id": agent_ctx.agent_id,
                "runs_root": str(journal.dir.parent),
                "out_dir": str(out_dir),
                "runs": runs,
                "demo": demo,
                "isolated": isolated,
                "keep_app": keep_app,
            }
            if any(resume_state.get(key) != value for key, value in expected_context.items()):
                raise ValueError("invalid execution context")
            approval_id = str(resume_state["approval_id"])
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("approval identity mismatch: incomplete resume state") from exc
        approvals.claim_resume(approval_id, resume_state, digest)
        journal.event("approval_identity_verified", approval_id=approval_id,
                      approved_digest=digest, executed_digest=digest)

    journal.event("runset_start", task=task.name, agent_id=agent_ctx.agent_id, runs=runs)
    # F3/M1: make the runset self-sufficient (task verbatim + run context).
    try:
        from eeze_agent.core.audit import snapshot_runset

        snapshot_runset(
            journal.dir,
            task=task,
            task_path=task_path,
            agent_id=agent_ctx.agent_id,
            runs=runs,
            demo=demo,
            isolated=isolated,
            keep_app=keep_app,
            policy=policy,
        )
    except OSError:
        pass  # snapshot is best-effort; the journal remains the source of truth
    files_dir = out_dir / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    state = RunState()
    needs_app = bool(task.app or task.aumid)

    if not needs_app:
        # script-only task: nothing to launch and nothing to isolate
        journal.event("no_app_task", task=task.name)
    elif isolated:
        _ensure_isolated(driver=driver, ctx=agent_ctx, journal=journal, task=task, state=state)
    else:
        # launch once per run-set (packaged-app cold launches cost ~10s)
        launch = driver.launch(
            agent_ctx, name=task.app if not task.aumid else None, aumid=task.aumid
        )
        state.pid = launch.get("pid")
        time.sleep(1.2)
        w = driver.main_window(agent_ctx, task.app)
        if w:
            state.pid, state.wid = int(w["pid"]), int(w["window_id"])
        else:
            wins = launch.get("windows") or []
            state.wid = wins[0].get("window_id") if wins else None
        journal.event("launch", pid=state.pid, window_id=state.wid)

    results: list[RunResult] = []
    partial: dict | None = None
    paused: NeedsApproval | None = None
    gate_exempt: set[tuple[int, int]] = set()
    if resume_state:
        runs = int(resume_state.get("runs") or runs)
        results = [RunResult(**r) for r in (resume_state.get("completed") or [])]
        partial = resume_state.get("partial") or None
        if partial and approvals is not None and resume_state.get("approval_id"):
            ap = approvals.get(str(resume_state["approval_id"]))
            if ap and ap.get("status") == "approved":
                try:
                    gate_exempt.add(
                        (int(partial.get("run_index") or 0), int(partial.get("step_index") or 0))
                    )
                except (TypeError, ValueError):
                    pass
        journal.event(
            "runset_resume",
            run_index=(partial or {}).get("run_index"),
            approval_id=resume_state.get("approval_id"),
            completed_runs=len(results),
            gate_exempt=sorted(gate_exempt),
        )
    start_run = int((partial or {}).get("run_index") or 1)
    consecutive_interference = 0
    budget_stop: BudgetExceeded | None = None
    run_brain = brain
    route = getattr(brain, "route", None)
    for run_ix in range(start_run, runs + 1):
        if route is not None:
            journal.event("model_route", run_index=run_ix, **route.as_event())
        if needs_app:
            w = driver.main_window(agent_ctx, task.app)
            if w is None:
                l2 = driver.launch(agent_ctx, name=task.app if not task.aumid else None, aumid=task.aumid)
                state.pid = l2.get("pid")
                time.sleep(1.2)
                w = driver.main_window(agent_ctx, task.app)
                journal.event("relaunch", run_index=run_ix, pid=state.pid)
            if w:
                state.pid, state.wid = int(w["pid"]), int(w["window_id"])
                if w.get("minimized"):
                    r = driver.restore_window(agent_ctx, state.pid, state.wid)
                    journal.event("action", run_index=run_ix, step_id="<run-start>", tool=r.tool,
                                  status=r.status, effect=r.effect, refusal=r.code, ms=r.ms)
        if partial and run_ix == int(partial.get("run_index") or 0):
            vars = dict(partial.get("vars") or {})
            prior_steps = [StepResult(**s) for s in (partial.get("steps") or [])]
            start_step = len(prior_steps)
            partial = None
        else:
            uid = uuid.uuid4().hex[:4]
            vars = {
                "token": f"eeze-f1-{run_ix}-{uid}",
                "path": str(files_dir / f"notes-{run_ix:02d}-{uid}.txt"),
                "run_dir": str(journal.run_dir(run_ix)),
                "runset_dir": str(journal.dir),
                **{str(k): str(v) for k, v in (task.vars or {}).items()},
            }
            prior_steps = []
            start_step = 0
        try:
            rr = run_once(
                task=task, ctx=agent_ctx, driver=driver, brain=run_brain, journal=journal,
                state=state, run_ix=run_ix, vars=vars, demo=demo,
                policy=policy, approvals=approvals, task_path=task_path,
                start_step_index=start_step, prior_steps=prior_steps, gate_exempt=gate_exempt,
            )
        except BudgetExceeded as be:
            budget_stop = be
            journal.event("budget_exceeded", run_index=run_ix, spent_usd=round(be.spent, 6),
                          budget_usd=be.budget, message=str(be))
            print(f"STOPPED: {be}")
            break
        except NeedsApproval as na:
            paused = na
            journal.event(
                "runset_paused", run_index=na.run_index, step_id=na.step_id,
                step_index=na.step_index, risk_class=na.risk_class,
                approval_id=na.approval_id, reason=na.reason,
            )
            if approvals is not None and na.approval_id:
                pause_payload = {
                    "approval_id": na.approval_id,
                    "task_path": str(task_path) if task_path else "",
                    "runset_id": journal.dir.name,
                    "runs_root": str(journal.dir.parent),
                    "out_dir": str(out_dir),
                    "runs": runs,
                    "agent_id": agent_ctx.agent_id,
                    "demo": demo,
                    "isolated": isolated,
                    "keep_app": keep_app,
                    "resume_argv": ["run", "--resume", na.approval_id],
                    "completed": [r.model_dump() for r in results],
                    "partial": {
                        "run_index": na.run_index,
                        "step_id": na.step_id,
                        "step_index": na.step_index,
                        "steps": na.partial_steps,
                        "vars": na.vars,
                    },
                }
                if extra_state:
                    pause_payload.update(extra_state)
                approvals.save_run_state(na.approval_id, pause_payload)
            print(
                f"PAUSED: approval required — {na.step_id} ({na.risk_class}) · "
                f"id={na.approval_id or 'n/a'}"
            )
            break
        results.append(rr)
        if rr.interference:
            consecutive_interference += 1
        else:
            consecutive_interference = 0
        # Router escalation: a real failure (not interference, not a pause) buys the next
        # tier up for the remaining runs — cheap first, escalate when it was not enough.
        if (
            not rr.ok
            and not rr.interference
            and route is not None
            and brain_factory is not None
        ):
            upgraded = brain_factory(escalate_from=route.tier)
            upgraded_route = getattr(upgraded, "route", None) if upgraded is not None else None
            if upgraded_route is not None and upgraded_route.tier != route.tier:
                journal.event(
                    "model_escalated",
                    run_index=run_ix,
                    from_tier=route.tier,
                    from_model=route.model,
                    to_tier=upgraded_route.tier,
                    to_model=upgraded_route.model,
                    reason=upgraded_route.reason,
                )
                print(f"ESCALATED model: {route.tier} -> {upgraded_route.tier} ({upgraded_route.model})")
                run_brain, route = upgraded, upgraded_route
        mark = "INTR" if rr.interference else ("OK  " if rr.ok else "FAIL")
        print(
            f"run {run_ix:02d}/{runs}: {mark} "
            f"{rr.cycle_ms:8.1f} ms  steps={sum(1 for s in rr.steps if s.ok)}/{len(task.steps)}"
        )
        if consecutive_interference >= 3:
            journal.event("runset_abort", run_index=run_ix,
                          reason="3 consecutive interference runs — environment is hostile")
            print(f"ABORT: 3 consecutive interference runs at run {run_ix:02d}")
            break

    if not keep_app and state.pid and paused is None:
        driver.kill(agent_ctx, state.pid)

    summary = summarize(journal, results, runs)
    if paused is not None:
        summary.update(
            {
                "status": "needs_approval",
                "approval_id": paused.approval_id,
                "paused_at": {
                    "run_index": paused.run_index,
                    "step_id": paused.step_id,
                    "risk_class": paused.risk_class,
                    "reason": paused.reason,
                },
            }
        )
    elif budget_stop is not None:
        summary["status"] = "budget_exceeded"
        summary["error"] = str(budget_stop)
    else:
        summary["status"] = "done"
    journal.event("runset_end", **summary)
    routine_run_id = str((resume_state or {}).get("routine_run_id") or "")
    if routine_run_id:
        # Close the routine run record opened by the scheduler's child process.
        try:
            from eeze_agent.core.routines import RoutineStore, task_routine_status

            RoutineStore().end_run(
                routine_run_id,
                str((resume_state or {}).get("routine_id") or ""),
                status=task_routine_status(summary),
                detail={
                    "resumed": True,
                    "runset_id": journal.dir.name,
                    "success_rate": summary.get("success_rate"),
                },
                approval_id=(resume_state or {}).get("approval_id"),
            )
        except Exception:  # noqa: BLE001, S110 — bookkeeping must not fail a finished run
            pass
    if resume_state is not None and task_path is not None:
        from eeze_agent.core.missions import MissionStore, missions_home

        if Path(task_path).resolve().parent.parent == missions_home().resolve():
            try:
                updated = MissionStore().record_resume(
                    task_path=Path(task_path), runset_id=journal.dir.name,
                    approval_id=str(resume_state["approval_id"]), summary=summary,
                )
                if not updated:
                    journal.event("mission_status_update_refused", reason="stale_or_mismatched")
            except Exception as exc:  # noqa: BLE001 — execution result is independent of bookkeeping
                journal.event("mission_status_update_failed", reason=type(exc).__name__)
    return summary


def summarize(journal: RunJournal, results: list[RunResult], runs: int) -> dict:
    import json as _json
    import statistics

    judgments = []
    actions = []
    rungs = []
    interference_events = []
    for line in (journal.dir / "journal.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            ev = _json.loads(line)
        except _json.JSONDecodeError:
            continue
        if ev.get("kind") == "judgment":
            judgments.append(ev)
        elif ev.get("kind") == "action":
            actions.append(ev)
        elif ev.get("kind") == "write_rung" and ev.get("result") == "ok":
            rungs.append(ev)
        elif ev.get("kind") == "external_input_detected":
            interference_events.append(ev)

    cycles = [r.cycle_ms for r in results if r.cycle_ms]
    interference_runs = [r.run_index for r in results if r.interference]
    eligible = [r for r in results if not r.interference]
    ok_runs = sum(1 for r in eligible if r.ok)
    ok_all = sum(1 for r in results if r.ok)
    jev_ms = [j["ms"] for j in judgments if j.get("ms")]
    tokens = sum(int(j.get("tokens") or 0) for j in judgments)
    # Per-model rollup (router era: a run-set can mix Luna/Sol/Jev) — cost per model.
    from eeze_agent.core.pricing import estimate_cost_usd

    models: dict[str, dict] = {}
    for j in judgments:
        key = str(j.get("model") or "unknown")
        bucket = models.setdefault(key, {"calls": 0, "tokens": 0, "cost_estimate_usd": 0.0})
        bucket["calls"] += 1
        bucket["tokens"] += int(j.get("tokens") or 0)
    for key, bucket in models.items():
        bucket["cost_estimate_usd"] = estimate_cost_usd(key, int(bucket["tokens"]))
    cost_total = round(sum(float(b["cost_estimate_usd"]) for b in models.values()), 7)
    sel = [j for j in judgments if j.get("judgment_kind") == "select_element"]
    ver = [j for j in judgments if j.get("judgment_kind") == "verify"]

    return {
        "task_runs": runs,
        "runs_completed": len(results),
        "success_rate": f"{ok_runs}/{len(eligible)}",
        "success_rate_all_runs": f"{ok_all}/{len(results)}",
        "interference_runs": interference_runs,
        "external_input_events": len(interference_events),
        "cycle_ms_p50": round(statistics.median(cycles), 1) if cycles else None,
        "cycle_ms_p95": round(sorted(cycles)[int(0.95 * (len(cycles) - 1))], 1) if cycles else None,
        "jev_calls": len(judgments),
        "jev_ms_p50": round(statistics.median(jev_ms), 1) if jev_ms else None,
        "input_tokens_total": tokens,
        "cost_estimate_usd": cost_total,
        "models": models,
        "selections": len(sel),
        "select_confidence_min": min((s.get("confidence") or 0 for s in sel), default=None),
        "verify_noul_min": min((v.get("noul") or 0 for v in ver), default=None),
        "write_methods": sorted({r.get("rung") for r in rungs if r.get("rung")}),
        "actions": len(actions),
        "journal": str(journal.dir / "journal.jsonl"),
    }
