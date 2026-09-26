"""System 2 planner (F2 / M2): natural-language goal → structured, executable plan.

The planner asks a general-purpose model for a JSON plan in the runtime's action
vocabulary; the plan is then executed by the *gated* loop — the planner can declare a
risk class but can never lower what the heuristic floor enforces. Replanning is bounded.

Brain: any OpenAI-compatible endpoint. Defaults (env-overridable):
    EEZE_PLANNER_BASE_URL  (default: https://openrouter.ai/api/v1)
    EEZE_PLANNER_API_KEY
    EEZE_PLANNER_MODEL     (default: openai/gpt-6-sol)

``EEZE_PLANNER_ENGINE=codex`` swaps the HTTP endpoint for the owner's **Codex subscription**
(``brains/codex.py: codex_client``, tier ``hard`` = ``gpt-6-sol``): local-only, no paid spend,
and a CLI failure is retried then raised as ``PlanError`` — never a silent paid call.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

import httpx

from eeze_agent.core.jsonx import parse_json_object

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
# Planning/spec-writing is the "hard" tier by policy (2026-09-23): Sol.
DEFAULT_MODEL = "openai/gpt-6-sol"

ACTION_VOCABULARY = """
- set_text: type/replace the text of an element. fields: intent, text, window?, candidate_filter{roles,label_contains}
- click: click an element. fields: intent, window?, candidate_filter{roles,label_contains}
- invoke_menu: open a menu path, e.g. menu=["File","Save as"]. fields: menu, window?
- hotkey: press a key combination. fields: keys=["ctrl","s"], window?
- check: verification-only step (no input). fields: verify_code and/or verify_jev
All steps may carry: id (short slug), intent (one sentence used to select the element),
verify_code, verify_jev, risk, fatal (default true), retries (default 2), window (title
substring when the step targets a dialog).
"""

SYSTEM_PROMPT = f"""You are the System 2 planner of Eeze, a computer-use agent that drives
Windows GUI apps in the background. Turn the user's goal into a JSON plan the runtime can
execute. Output ONLY a JSON object: {{"app": "<process name>", "steps": [...]}}.

The runtime action vocabulary (ONLY these actions; EVERY step needs BOTH "id" AND "action"):
{ACTION_VOCABULARY}

Verification codes (use the "|" separator; Windows paths stay intact):
doc_equals|<text> · field_equals|<label>|<text> · window_present|<title substring> ·
window_absent|<title substring> · file_exists|<absolute path>

Verified example (this EXACT shape — click route, action field, full path):
{{"app": "Notepad", "steps": [
  {{"id": "set-content", "action": "set_text", "intent": "the document input that receives the document text", "text": "hello world", "verify_code": "doc_equals|hello world"}},
  {{"id": "open-file-menu", "action": "click", "candidate_filter": {{"roles": ["menuitem", "button"], "label_contains": "File"}}, "intent": "open the File menu of Notepad (the 'File' menu item in the menu bar)"}},
  {{"id": "click-save-as", "action": "click", "candidate_filter": {{"roles": ["menuitem", "button"], "label_contains": "Save as"}}, "intent": "click the 'Save as' item in the open File menu"}},
  {{"id": "set-filename", "action": "set_text", "window": "Save as", "candidate_filter": {{"roles": ["edit"], "label_contains": "File name"}}, "text": "C:/Users/me/out.txt", "intent": "set the 'File name' field to the FULL absolute path"}},
  {{"id": "confirm-save", "action": "click", "window": "Save as", "candidate_filter": {{"roles": ["button"], "label_contains": "Save"}}, "intent": "click the Save button to confirm"}},
  {{"id": "verify", "action": "check", "verify_code": "window_absent|Save as;file_exists|C:/Users/me/out.txt"}}]}}

Rules:
- Currently verified target: Notepad (Win11). Launching is implicit in "app".
- For Notepad NEVER use invoke_menu (the driver refuses it there) and NEVER use hotkeys —
  always the CLICK route shown in the example above.
- The "File name" field must receive the FULL absolute path from the goal (never a bare
  file name); the goal's path separators may be "/" or "\\" — reproduce the path exactly.
- Declare "risk" ONLY when a step genuinely installs/executes software ("install_exec"),
  deletes data ("destructive"), sends something externally ("external_send") or changes
  system settings ("system"). Do not declare risk otherwise.
- Keep steps minimal and verifiable."""

REPLAN_PROMPT = """The previous plan failed. A new plan is needed for the same goal.

Goal:
{goal}

Previous plan:
{previous}

Failure evidence (from the runtime):
{failure}

Produce a NEW plan (same JSON shape/vocabulary) that avoids the failure. If the failure is
about an element not being found, prefer a different route to the same outcome (e.g. a
menu path instead of a click, or a different order of steps). Output ONLY the JSON object."""


class PlanError(RuntimeError):
    """The planner could not produce a usable plan."""


class Planner:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
        client: Callable[[str, str], tuple[str, int]] | None = None,
        engine: str | None = None,
        provider: object | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("EEZE_PLANNER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or os.environ.get("EEZE_PLANNER_API_KEY") or ""
        self.model = model or os.environ.get("EEZE_PLANNER_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self.engine = (engine or os.environ.get("EEZE_PLANNER_ENGINE") or "http").strip().lower()
        self.provider_id = ""
        self.provider_source = "default"
        self._client = client
        if self._client is None and self.engine == "codex":
            from eeze_agent.brains.codex import codex_client, codex_model_for_tier

            self._client = codex_client(tier="hard")  # planning is the hard tier by policy
            self.model = f"codex:{codex_model_for_tier('hard')}"
        elif self._client is None and self.engine == "http":
            # Provider layer (P2): a stored key/endpoint wins over env, which wins over the default.
            from eeze_agent.core.providers import (
                require_key_for_endpoint_override,
                resolve_provider,
            )

            cfg = provider if provider is not None else resolve_provider("planner")
            require_key_for_endpoint_override(base_url, api_key, cfg)
            self.provider_id = getattr(cfg, "provider_id", "") or "openrouter"
            self.provider_source = getattr(cfg, "source", "default")
            if not base_url and getattr(cfg, "base_url", ""):
                self.base_url = str(cfg.base_url).rstrip("/")
            # Never fall back to an unscoped role key after provider resolution:
            # it may belong to a different endpoint.
            self.api_key = api_key if api_key is not None else str(getattr(cfg, "api_key", ""))
            if not model and getattr(cfg, "model", ""):
                self.model = str(cfg.model)
        self.calls = 0
        self.last_tokens = 0
        self.budget_agent: object | None = None  # whose daily cap pays (missions set it)

    def _chat(self, system: str, user: str) -> str:
        from eeze_agent.core import spend

        try:
            spend.check_budget(self.budget_agent)
        except spend.BudgetExceeded as exc:
            raise PlanError(str(exc)) from exc
        reply = self._chat_raw(system, user)
        try:
            spend.record(getattr(self.budget_agent, "id", "default"), self.model,
                         self.last_tokens, source="planner")
        except Exception:  # noqa: BLE001, S110 — bookkeeping never blocks planning
            pass
        return reply

    def _chat_raw(self, system: str, user: str) -> str:
        self.calls += 1
        if self._client is not None:
            try:
                reply, self.last_tokens = self._client(system, user)
            except PlanError:
                raise
            except Exception as exc:
                raise PlanError(f"planner engine failed: {exc}") from exc
            return reply
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        response = httpx.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
        )
        if response.status_code != 200:
            raise PlanError(f"planner HTTP {response.status_code}: {response.text[:300]}")
        body = response.json()
        usage = body.get("usage") or {}
        self.last_tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise PlanError(f"planner reply missing choices: {str(body)[:200]}") from exc

    def _parse_plan(self, reply: str) -> dict:
        try:
            parsed = parse_json_object(reply, what="planner reply")
        except (ValueError, TypeError) as exc:
            raise PlanError(str(exc)) from exc
        steps = parsed.get("steps")
        if not isinstance(parsed.get("app"), str) or not isinstance(steps, list) or not steps:
            raise PlanError(f"plan must be {{app, steps[]}} with at least one step: {reply[:200]}")
        return parsed

    def plan(self, goal: str) -> dict:
        reply = self._chat(SYSTEM_PROMPT, f"Goal:\n{goal}")
        return self._parse_plan(reply)

    def replan(self, goal: str, previous_plan: dict, failure: str) -> dict:
        user = REPLAN_PROMPT.format(
            goal=goal,
            previous=json.dumps(previous_plan, ensure_ascii=False)[:4000],
            failure=failure[:2000],
        )
        reply = self._chat(SYSTEM_PROMPT, user)
        return self._parse_plan(reply)
