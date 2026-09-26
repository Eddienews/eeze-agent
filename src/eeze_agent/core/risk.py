"""Risk classes and the deterministic gate (F2 / M0).

The product rule this implements: **reads are free; anything risky waits for the
user's click**. Classification is deterministic — no LLM in the critical path — and
can only be RAISED by heuristics, never lowered below the heuristic floor by a
declared value. The gate itself lives in ``core.loop`` (single choke point).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from eeze_agent.core.models import StepSpec, TaskSpec

RISK_ORDER: tuple[str, ...] = (
    "read",
    "write_local",
    "external_send",
    "install_exec",
    "destructive",
    "system",
)
DEFAULT_ALLOWED: frozenset[str] = frozenset({"read", "write_local"})

# Heuristic floor: scanned over step id/intent/text/menu/keys/command + the target app.
# ALL matching classes are collected and the STRONGEST wins (a text mentioning both
# "regedit" and "install" is a `system` step, not merely `install_exec`).
# Over-matching gates MORE, which is the safe direction — the lists are expected to
# be tuned with experience. The command patterns also scan `run_script` commands.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "destructive",
        re.compile(
            r"uninstall|delete|erase|wipe|shred|\bformat\b|empty trash|recycle bin|"
            r"drop table|taskkill|terminate process|kill process|overwrite file|"
            r"remove (file|folder|app|account)|"
            r"\brm\s+-rf\b|rmdir\s+/s|del\s+/[fq]|remove-item|diskpart|\bshutdown\b|"
            r"bcdedit|vssadmin|cipher\s+/w|schtasks\s+/delete|reg\s+delete|takeown|"
            r"git\s+reset\s+--hard|git\s+clean\s+-[fdx]",
            re.IGNORECASE,
        ),
    ),
    (
        "install_exec",
        re.compile(
            r"install|setup\.exe|winget|choco|scoop|pip install|npm install|\bnpx\b|"
            r"npm i\b|uv pip|git clone|powershell|cmd\.exe|command prompt|terminal|"
            r"execute|run script|run command|\bcurl\b|\bwget\b|invoke-webrequest|"
            r"invoke-expression|\biex\b|\.exe\b|\.msi\b|\.bat\b|\.ps1\b|\.sh\b|"
            r"\.py\b|\bpython\b|\bnode\b|\bffmpeg\b|\bblender\b|magick",
            re.IGNORECASE,
        ),
    ),
    (
        "system",
        re.compile(
            r"regedit|registry|gpedit|services\.msc|firewall|windows update|defender|antivirus|"
            r"control panel|computer management|user accounts|"
            r"reg\s+add|sc\s+config|sc\s+create|net\s+user|net\s+localgroup|setx\b|"
            r"start-process.*-verb\s+runas|schtasks\s+/create",
            re.IGNORECASE,
        ),
    ),
    (
        "external_send",
        re.compile(
            r"\bsend|email|e-mail|\bsubmit\b|publish|upload|post message|\btweet\b|share file",
            re.IGNORECASE,
        ),
    ),
)


def rank(risk_class: str) -> int:
    try:
        return RISK_ORDER.index(risk_class)
    except ValueError as exc:
        raise ValueError(
            f"unknown risk class: {risk_class!r} (known: {', '.join(RISK_ORDER)})"
        ) from exc


def max_class(*classes: str) -> str:
    """The strongest (highest-ranked) class among the non-empty arguments."""
    non_empty = [c for c in classes if c]
    if not non_empty:
        return "read"
    return max(non_empty, key=rank)


@dataclass(frozen=True)
class Classification:
    risk_class: str
    reason: str


def _haystack(step: StepSpec, task: TaskSpec) -> str:
    parts = [
        step.id or "",
        step.intent or "",
        step.text or "",
        step.command or "",
        " ".join(step.keys or []),
        " ".join(step.menu or []),
        task.app or "",
        task.aumid or "",
    ]
    return " \n ".join(p for p in parts if p)


def classify_step(step: StepSpec, task: TaskSpec) -> Classification:
    """Effective class = strongest of (action default, task/step declarations, heuristics).

    - action default: ``check`` is read-only; ``run_script`` executes code, so it
      defaults to ``install_exec`` (gated unless the policy or a grant allows it);
      every other interacting action is ``write_local``.
    - declarations (``task.risk`` / ``step.risk``) can RAISE the class.
    - the heuristic floor can override a too-low declaration; it is never lowered.
    """
    if step.action == "check":
        default = "read"
    elif step.action == "run_script":
        default = "install_exec"
    else:
        default = "write_local"
    declared_task = task.risk or ""
    declared_step = step.risk or ""
    hits: list[str] = []
    reason_bits: list[str] = []
    haystack = _haystack(step, task)
    for risk_class, pattern in PATTERNS:
        match = pattern.search(haystack)
        if match:
            hits.append(risk_class)
            reason_bits.append(f"heuristic {risk_class} (~{match.group(0)!r})")
    heuristic = max_class(*hits) if hits else ""
    effective = max_class(default, declared_task, declared_step, heuristic)
    if not reason_bits:
        if declared_task or declared_step:
            reason_bits.append(f"declared {max_class(declared_task, declared_step)}")
        else:
            reason_bits.append(f"default for action {step.action!r}")
    return Classification(risk_class=effective, reason="; ".join(reason_bits))


@dataclass(frozen=True)
class Policy:
    """Which risk classes may execute without a fresh approval."""

    allowed: frozenset[str] = DEFAULT_ALLOWED

    def allows(self, risk_class: str) -> bool:
        return risk_class in self.allowed


def policy_for_agent(agent_permissions: dict | None) -> Policy:
    """Policy from an agent's declared ``risk_classes`` (defaults when absent)."""
    perms = agent_permissions or {}
    classes = perms.get("risk_classes")
    if not classes:
        return Policy()
    for name in classes:
        rank(str(name))  # validates
    return Policy(frozenset(str(c) for c in classes))
