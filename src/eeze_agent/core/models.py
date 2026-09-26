"""Core models: task specs, observations, action outcomes, judgments, run results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StepSpec(BaseModel):
    """One declarative step of a task."""

    # Step ids become file names (step-<id>.log / .png): no separators, no "..", no spaces.
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
    action: Literal["set_text", "click", "invoke_menu", "hotkey", "check", "run_script"]
    intent: str = ""  # rendered and given to Jev when the action needs an element
    text: str | None = None  # set_text: value (template)
    keys: list[str] | None = None  # hotkey: e.g. ["ctrl", "shift", "s"]
    menu: list[str] | None = None  # invoke_menu: e.g. ["File", "Save as"]
    window: str | None = None  # target window: title substring; default = task window
    candidate_filter: dict | None = None  # {"roles": [...], "label_contains": str} narrows candidates
    command: str | None = None  # run_script: shell command (template), gated as install_exec by default
    cwd: str | None = None  # run_script: working dir (template; default = this run's dir)
    timeout_s: float = Field(default=120.0, gt=0, le=4 * 3600)  # run_script: hard timeout; killed on expiry
    verify_jev: str | None = None  # Noul statement over a fresh capture (template)
    verify_code: str | None = None  # deterministic check (template), see core.checks
    fatal: bool = True
    retries: int = Field(default=2, ge=0, le=5)
    risk: str | None = None  # declared risk class floor (F2): read|write_local|external_send|install_exec|destructive|system


class TaskSpec(BaseModel):
    name: str
    app: str = ""  # empty = script-only task (no window is launched or required)
    aumid: str | None = None
    allow_foreground: bool = False
    risk: str | None = None  # declared risk class floor for every step (F2)
    vars: dict[str, str] = Field(default_factory=dict)  # static template vars (e.g. tool paths)
    steps: list[StepSpec]


class Candidate(BaseModel):
    """A code-enumerated element candidate offered to Jev for selection."""

    id: str  # "c<element_index>"
    role: str
    label: str
    element_index: int
    token: str
    frame: dict | None = None  # window-local {x,y,w,h} — needed for pixel-mode actions

    def describe(self) -> str:
        return f"{self.role} {self.label!r}"


class Observation(BaseModel):
    pid: int
    window_id: int
    window_title: str | None = None
    app_name: str | None = None
    snapshot_id: str | None = None
    degraded: bool | None = None
    degraded_reason: str | None = None
    escalation: dict | None = None
    elements: list[dict] = Field(default_factory=list)
    screenshot_png_b64: str | None = None
    ms: float = 0.0


class ActionOutcome(BaseModel):
    tool: str
    status: str | None = None
    effect: str | None = None
    route: str | None = None
    code: str | None = None  # structured refusal code
    refusal_message: str | None = None
    ms: float = 0.0
    raw: dict = Field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return self.status == "refused" or self.code is not None

    @property
    def needs_escalation(self) -> bool:
        """Ladder rule: only a returned signal — never a prediction — escalates."""
        if self.code in {"background_unavailable", "foreground_unsupported"}:
            return True
        return self.effect == "suspected_noop"


class Judgment(BaseModel):
    kind: str  # "select_element" | "verify"
    question: str
    answer: str | float | None = None
    confidence: float | None = None
    probabilities: dict | None = None
    noul: float | None = None
    ms: float = 0.0
    tokens: int = 0
    model: str | None = None
    request_id: str | None = None


class StepResult(BaseModel):
    step_id: str
    attempts: int = 0
    ok: bool = False
    interference: bool = False  # external_input_detected gate tripped this step
    detail: dict = Field(default_factory=dict)
    ms: float = 0.0


class RunResult(BaseModel):
    run_index: int
    agent_id: str | None = None
    ok: bool = False
    interference: bool = False  # run stopped by the state-consistency gate
    steps: list[StepResult] = Field(default_factory=list)
    cycle_ms: float = 0.0
    error: str | None = None
