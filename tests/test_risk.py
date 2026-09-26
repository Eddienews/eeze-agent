"""F2/M0 — risk classification + policy tests."""

from __future__ import annotations

import pytest

from eeze_agent.core.models import StepSpec, TaskSpec
from eeze_agent.core.risk import (
    DEFAULT_ALLOWED,
    Policy,
    classify_step,
    max_class,
    policy_for_agent,
    rank,
)


def _task(**kw) -> TaskSpec:
    return TaskSpec(name="t", app=kw.pop("app", "Fake"), steps=[], **kw)


def _step(**kw) -> StepSpec:
    kw.setdefault("id", "s")
    kw.setdefault("action", "click")
    return StepSpec(**kw)


def test_default_action_classes():
    assert classify_step(_step(action="check"), _task()).risk_class == "read"
    assert classify_step(_step(action="click"), _task()).risk_class == "write_local"
    assert classify_step(_step(action="set_text", text="hi"), _task()).risk_class == "write_local"


def test_heuristics_raise_install_exec():
    step = _step(action="invoke_menu", menu=["Tools", "Install sample addon"])
    assert classify_step(step, _task()).risk_class == "install_exec"


def test_destructive_beats_install():
    step = _step(intent="click the Uninstall button")
    assert classify_step(step, _task()).risk_class == "destructive"


def test_external_send_from_menu():
    step = _step(action="invoke_menu", menu=["Message", "Send now"])
    assert classify_step(step, _task()).risk_class == "external_send"


def test_system_class():
    step = _step(intent="open regedit and change a key")
    assert classify_step(step, _task()).risk_class == "system"


def test_declared_risk_can_raise_but_not_lower():
    raised = _step(action="click", risk="destructive")
    assert classify_step(raised, _task()).risk_class == "destructive"
    lowered = _step(action="click", intent="Install things", risk="read")
    assert classify_step(lowered, _task()).risk_class == "install_exec"  # floor wins
    task_floor = _task(risk="system")
    assert classify_step(_step(action="check"), task_floor).risk_class == "system"


def test_unknown_declared_class_raises():
    with pytest.raises(ValueError):
        rank("nonsense")


def test_max_class_orders():
    assert max_class("read", "destructive") == "destructive"
    assert max_class("write_local", "external_send") == "external_send"
    assert max_class("", None, "read") == "read"


def test_policy_and_agent_permissions():
    policy = Policy()
    assert policy.allows("read") and policy.allows("write_local")
    assert not policy.allows("install_exec") and not policy.allows("external_send")
    agent_policy = policy_for_agent({"risk_classes": ["read", "write_local", "external_send"]})
    assert agent_policy.allows("external_send")
    assert policy_for_agent(None).allowed == DEFAULT_ALLOWED
    with pytest.raises(ValueError):
        policy_for_agent({"risk_classes": ["bogus"]})
