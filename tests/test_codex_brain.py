"""P1 — Codex-subscription brain: argv, stdin delivery, JSONL parsing, tiers, no-paid-spend.

The JSONL replay in ``test_parse_exec_jsonl_real_stream`` is a VERBATIM capture from this
machine's CLI (``codex exec --json``, 2026-09-24) — error items and non-JSON log lines
included, because that is what the real stream looks like.

``test_prompt_travels_on_stdin_not_argv`` locks a live bug: on Windows the argv is launched
through ``cmd /c``, which mangles an argument full of JSON quotes — the model received a
prompt with the payload missing and answered the role-play ("Send the objective") instead
of the question. The prompt MUST travel on stdin.

``test_failure_without_optin_never_calls_the_paid_engine`` locks the owner's testing rule:
no OpenRouter spend — the paid fallback only exists when ``EEZE_CODEX_FALLBACK=openrouter``.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from eeze_agent.agents.models import Agent, AgentContext
from eeze_agent.brains.codex import (
    CodexBrain,
    build_argv,
    codex_client,
    codex_model_for_tier,
    parse_exec_jsonl,
    tier_for_task,
)
from eeze_agent.brains.llm import LlmBrain
from eeze_agent.brains.planner import PlanError, Planner
from eeze_agent.brains.registry import make_brain, resolve_brain_name
from eeze_agent.brains.specwriter import SpecWriteError, SpecWriter
from eeze_agent.core.models import Candidate
from eeze_agent.core.pricing import estimate_cost_usd, price_for

CTX = AgentContext(agent=Agent(id="default", name="Default"))

REAL_STREAM = """\
{"type":"thread.started","thread_id":"01a0d18f-10cb-79f2-bccb-2cbbda8cd20d"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Codex is ignoring 1 unrecognized configuration setting."}}
{"type":"turn.started"}
2026-09-24T03:56:51.847495Z ERROR codex_api::endpoint: failed to connect to websocket
{"type":"item.completed","item":{"id":"item_2","type":"agent_message","text":"{\\"answer\\":\\"cand-3\\",\\"confidence\\":0.88}"}}
{"type":"turn.completed","usage":{"input_tokens":23762,"cached_input_tokens":6912,"cache_write_input_tokens":0,"output_tokens":17,"reasoning_output_tokens":0}}
"""

NO_ENV = (
    "EEZE_CODEX_MODEL",
    "EEZE_CODEX_MODEL_ROUTINE",
    "EEZE_CODEX_MODEL_HARD",
    "EEZE_CODEX_FALLBACK",
    "EEZE_CODEX_ROUTER",
    "EEZE_CODEX_ATTEMPTS",
    "EEZE_CODEX_SCRATCH",
    "EEZE_BRAIN_MODEL",
    "EEZE_PLANNER_ENGINE",
    "EEZE_SPEC_ENGINE",
)


def _cands() -> list[Candidate]:
    return [
        Candidate(id="c0", role="Document", label="Text editor", element_index=0, token="t0"),
        Candidate(id="c1", role="MenuItem", label="File", element_index=1, token="t1"),
    ]


def _stream(text: str) -> str:
    return json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": text}})


def _ok(text: str):
    return lambda argv, prompt: (0, _stream(text))


def _clean(monkeypatch) -> None:
    for key in NO_ENV:
        monkeypatch.delenv(key, raising=False)


def _brain(tmp_path, *, runner, fallback=None, fallback_chat=None, model="test-1", **kw) -> CodexBrain:
    """Subscription-only by default (no paid engine anywhere near a test)."""
    return CodexBrain(
        scratch=tmp_path,
        model=model,
        runner=runner,
        fallback=fallback,
        fallback_chat=fallback_chat,
        **kw,
    )


# -- transport ----------------------------------------------------------------


def test_parse_exec_jsonl_real_stream():
    message, tokens = parse_exec_jsonl(REAL_STREAM)
    assert message == '{"answer":"cand-3","confidence":0.88}'
    assert tokens == 23762 + 17  # input + output; the error items and log lines are skipped


def test_parse_exec_jsonl_without_answer():
    assert parse_exec_jsonl('{"type":"thread.started"}') == (None, 0)
    assert parse_exec_jsonl("") == (None, 0)


def test_build_argv_windows_prefix_and_stdin_marker():
    argv = build_argv("codex", "gpt-6-sol", "C:/scratch", platform="nt")
    assert argv[:4] == ["cmd", "/c", "codex", "exec"]  # the npm shim is a .cmd
    assert {"--json", "--ephemeral", "--skip-git-repo-check", "--color"} <= set(argv)
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[argv.index("-m") + 1] == "gpt-6-sol"
    assert argv[argv.index("-C") + 1] == "C:/scratch"
    assert argv[-1] == "-"  # PROMPT comes on stdin
    posix = build_argv("codex", "", "scratch", platform="linux")
    assert posix[0] == "codex" and "-m" not in posix  # no model pin -> the CLI's own default


# -- judgments ----------------------------------------------------------------


def test_prompt_travels_on_stdin_not_argv(tmp_path):
    seen: dict = {}

    def runner(argv: list[str], prompt: str) -> tuple[int, str]:
        seen["argv"], seen["prompt"] = argv, prompt
        return 0, _stream('{"answer": "c1", "confidence": 0.82}')

    brain = _brain(tmp_path, runner=runner)
    brain.select_element(CTX, intent="open the File menu", state={"elements": 3}, candidates=_cands())
    assert seen["argv"][-1] == "-"
    assert "open the File menu" not in " ".join(seen["argv"])  # no payload in the argv
    assert '"instruction": "open the File menu"' in seen["prompt"]  # the payload IS on stdin
    assert seen["prompt"].startswith("You are the tactical selector of Eeze")


def test_select_element_via_codex_reports_engine(tmp_path):
    brain = _brain(tmp_path, runner=_ok('{"answer": "c1", "confidence": 0.82}'))
    judgment = brain.select_element(
        CTX, intent="open the File menu", state={"elements": 3}, candidates=_cands()
    )
    assert judgment.answer == "c1" and judgment.confidence == 0.82
    assert judgment.model == "codex:test-1"  # the engine is never disguised
    assert judgment.ms >= 0
    assert brain.calls == 1 and brain.fallbacks == 0


def test_verify_via_codex(tmp_path):
    brain = _brain(tmp_path, runner=_ok('{"probability": 0.95, "reason": "x"}'))
    judgment = brain.verify(CTX, statement="the document equals 'x'", state={})
    assert judgment.kind == "verify" and judgment.noul == 0.95
    assert judgment.model == "codex:test-1"


def test_garbage_reply_is_a_retry_not_an_engine_failure(tmp_path):
    # The CLI answered — an unparsable answer is a retry at the LOOP level (same as LlmBrain).
    brain = _brain(tmp_path, runner=_ok("I think maybe the second one?"))
    judgment = brain.select_element(CTX, intent="x", state={}, candidates=_cands())
    assert judgment.answer is None and judgment.confidence is None
    assert brain.calls == 1 and brain.fallbacks == 0 and brain.last_error is None


# -- failure ladder: no money by default --------------------------------------


def test_retry_inside_the_subscription(tmp_path):
    calls: list[int] = []

    def flaky(argv: list[str], prompt: str) -> tuple[int, str]:
        calls.append(1)
        if len(calls) == 1:
            return 1, ""  # transient CLI failure
        return 0, _stream('{"answer": "c1", "confidence": 0.7}')

    brain = _brain(tmp_path, runner=flaky)
    judgment = brain.select_element(CTX, intent="x", state={}, candidates=_cands())
    assert judgment.answer == "c1"
    assert brain.calls == 2 and brain.fallbacks == 0 and judgment.model == "codex:test-1"


def test_failure_without_optin_never_calls_the_paid_engine(tmp_path, monkeypatch):
    """The owner's rule: testing must not spend OpenRouter money."""
    _clean(monkeypatch)
    paid: list[int] = []
    brain = _brain(
        tmp_path,
        runner=lambda argv, prompt: (1, ""),
        fallback_chat=lambda s, u: (paid.append(1) or '{"answer": "c1", "confidence": 0.9}', 10),
    )
    judgment = brain.select_element(CTX, intent="x", state={}, candidates=_cands())
    assert judgment.answer is None  # degrades to a retry, honestly
    assert brain.fallbacks == 0 and paid == []  # the paid engine was never called
    assert brain.calls == 2  # EEZE_CODEX_ATTEMPTS default
    assert judgment.model == "codex:test-1" and judgment.tokens == 0
    assert "codex exec exited 1" in (brain.last_error or "")


def test_attempts_env_is_honored(tmp_path, monkeypatch):
    monkeypatch.setenv("EEZE_CODEX_ATTEMPTS", "3")
    brain = _brain(tmp_path, runner=lambda argv, prompt: (1, ""))
    brain.select_element(CTX, intent="x", state={}, candidates=_cands())
    assert brain.calls == 3


def test_default_brain_has_no_paid_fallback(tmp_path, monkeypatch):
    _clean(monkeypatch)
    assert _brain(tmp_path, runner=_ok('{"probability": 1}')).fallback is None


def test_optin_env_builds_the_paid_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("EEZE_CODEX_FALLBACK", "openrouter")
    brain = _brain(tmp_path, runner=_ok('{"probability": 1}'))
    assert isinstance(brain.fallback, LlmBrain)  # constructed, never called here


def test_optin_fallback_answers_and_is_attributed(tmp_path, monkeypatch):
    monkeypatch.setenv("EEZE_CODEX_FALLBACK", "openrouter")
    brain = _brain(
        tmp_path,
        runner=lambda argv, prompt: (1, ""),
        fallback=LlmBrain(model="fake/fallback"),
        fallback_chat=lambda s, u: ('{"answer": "c1", "confidence": 0.5}', 12),
    )
    judgment = brain.select_element(CTX, intent="x", state={}, candidates=_cands())
    assert judgment.answer == "c1" and judgment.confidence == 0.5
    assert judgment.model == "fake/fallback"  # the journal shows which engine answered
    assert judgment.tokens == 12
    assert brain.fallbacks == 1 and brain.last_error.startswith("RuntimeError")


def test_timeout_degrades_without_the_paid_engine(tmp_path, monkeypatch):
    def boom(argv: list[str], prompt: str) -> tuple[int, str]:
        raise subprocess.TimeoutExpired(cmd="codex", timeout=180)

    _clean(monkeypatch)
    brain = _brain(tmp_path, runner=boom)
    judgment = brain.verify(CTX, statement="x", state={})
    assert judgment.noul is None and judgment.model == "codex:test-1"
    assert brain.fallbacks == 0 and "TimeoutExpired" in (brain.last_error or "")


# -- models: the Luna/Sol policy, flat-priced ---------------------------------


def test_tier_models_default_luna_routine_sol_hard(monkeypatch):
    _clean(monkeypatch)
    assert codex_model_for_tier("routine") == "gpt-6-luna"
    assert codex_model_for_tier("hard") == "gpt-6-sol"
    assert codex_model_for_tier(None) == "gpt-6-luna"
    assert codex_model_for_tier("HARD") == "gpt-6-sol"


def test_tier_models_are_env_overridable(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_CODEX_MODEL_ROUTINE", "gpt-6-sol")
    monkeypatch.setenv("EEZE_CODEX_MODEL_HARD", "gpt-7-max")
    brain = _brain(tmp_path, runner=_ok('{"probability": 1}'), model=None, tier="hard")
    assert brain.model == "gpt-7-max" and brain.engine == "codex:gpt-7-max"


def test_env_pin_beats_the_tier(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_CODEX_MODEL", "gpt-6-sol")
    brain = _brain(tmp_path, runner=_ok('{"probability": 1}'), model=None, tier="routine")
    assert brain.model == "gpt-6-sol" and brain.route.source == "pin"


def test_tier_for_task_uses_the_free_rules_floor(monkeypatch):
    _clean(monkeypatch)
    assert tier_for_task(None) == ("routine", "rules")
    assert tier_for_task("render a 3d video of the logo")[0] == "hard"  # hard marker, no Jev call
    assert tier_for_task("check the invoices inbox")[0] == "routine"
    assert tier_for_task("render a 3d video", escalate_from="routine") == ("hard", "escalated")
    assert tier_for_task("x", escalate_from="hard") == ("hard", "escalated")  # capped


# -- registry + pricing -------------------------------------------------------


def test_registry_resolves_codex_on_the_routine_tier(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.delenv("EEZE_BRAIN", raising=False)
    assert resolve_brain_name(name="codex") == "codex"
    brain = make_brain(name="codex", scratch=tmp_path, model=None)
    assert isinstance(brain, CodexBrain)
    assert brain.route.tier == "routine" and brain.route.model == "codex:gpt-6-luna"
    assert brain.route.source == "rules" and brain.fallback is None


def test_registry_routes_a_hard_task_to_sol(tmp_path, monkeypatch):
    _clean(monkeypatch)
    brain = make_brain(name="codex", task="render a 3d video of the logo", scratch=tmp_path)
    assert isinstance(brain, CodexBrain)
    assert brain.route.tier == "hard" and brain.route.model == "codex:gpt-6-sol"


def test_escalation_stays_inside_the_subscription(tmp_path, monkeypatch):
    """A failed routine run climbs to Sol on the same flat plan — no paid ladder."""
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_ROUTER", "rules")
    brain = make_brain(name="codex", task="a small notepad task", escalate_from="routine", scratch=tmp_path)
    assert isinstance(brain, CodexBrain)  # NOT the LlmBrain: no OpenRouter for a failed run
    assert brain.route.source == "escalated"
    assert brain.route.tier == "hard" and brain.route.model == "codex:gpt-6-sol"
    assert brain.fallback is None


def test_codex_models_price_flat():
    assert price_for("codex:gpt-6-sol") == 0.0
    assert price_for("codex:gpt-6-luna") == 0.0
    assert estimate_cost_usd("codex:gpt-6-sol", 23779) == 0.0  # flat plan: $0 marginal, not "missing"
    assert price_for("openai/gpt-6-sol") > 0  # paid models keep their measured price


# -- the subscription as a text engine for the planner / spec writer -----------


def _plan_reply() -> str:
    return json.dumps({"app": "notepad", "steps": [{"id": "open", "intent": "open notepad"}]})


def test_codex_client_retries_then_raises(tmp_path):
    calls: list[int] = []

    def runner(argv: list[str], prompt: str) -> tuple[int, str]:
        calls.append(1)
        return 1, ""

    client = codex_client(scratch=tmp_path, runner=runner, attempts=2, model="gpt-6-sol")
    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        client("sys", "user")
    assert len(calls) == 2 and client.model == "gpt-6-sol"  # type: ignore[attr-defined]


def test_codex_client_answers_after_one_transient_failure(tmp_path):
    calls: list[int] = []

    def flaky(argv: list[str], prompt: str) -> tuple[int, str]:
        calls.append(1)
        return (1, "") if len(calls) == 1 else (0, _stream(_plan_reply()))

    client = codex_client(scratch=tmp_path, runner=flaky, attempts=2)
    text, _tokens = client("sys", "user")
    assert json.loads(text)["app"] == "notepad" and len(calls) == 2


def test_planner_answers_on_the_subscription(tmp_path):
    planner = Planner(engine="codex", client=codex_client(scratch=tmp_path, runner=_ok(_plan_reply())))
    plan = planner.plan("open notepad and write x")
    assert plan["app"] == "notepad" and planner.engine == "codex" and planner.calls == 1


def test_planner_codex_engine_wiring_is_truthful(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_PLANNER_ENGINE", "codex")
    monkeypatch.setenv("EEZE_CODEX_SCRATCH", str(tmp_path))
    planner = Planner()
    assert planner._client is not None  # built, never called in this test
    assert planner.model == "codex:gpt-6-sol"  # the harness model, never the HTTP name


def test_planner_wraps_a_transport_failure_as_plan_error():
    def boom(system: str, user: str) -> tuple[str, int]:
        raise RuntimeError("codex exec exited 1")

    planner = Planner(engine="codex", client=boom)
    with pytest.raises(PlanError, match="planner engine failed"):
        planner.plan("x")


def test_spec_writer_codex_engine_wiring_is_truthful(tmp_path, monkeypatch):
    _clean(monkeypatch)
    monkeypatch.setenv("EEZE_PLANNER_ENGINE", "codex")  # the spec writer falls back to it
    monkeypatch.setenv("EEZE_CODEX_SCRATCH", str(tmp_path))
    writer = SpecWriter()
    assert writer._client is not None and writer.engine == "codex"
    assert writer.model == "codex:gpt-6-sol"


def test_spec_writer_wraps_a_transport_failure():
    def boom(system: str, user: str) -> tuple[str, int]:
        raise RuntimeError("codex exec exited 1")

    writer = SpecWriter(engine="codex", client=boom)
    with pytest.raises(SpecWriteError, match="spec engine failed"):
        writer._chat("s", "u")
