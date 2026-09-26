"""F7: missions — write a goal, edit the plan, run it, keep the evidence.

A mission is the front door the CLI never had: a name, a plain-language ``goal``, the **plan**
(the exact YAML the agent will run — the operator may edit every line), an optional ``schedule``
and the last run. Three kinds:

``3d``    plan = a Blender scene spec      → materialized task runs ``eeze 3d <spec> --out {run_dir}``
``video`` plan = an ffmpeg edit spec       → materialized task runs ``eeze video <spec> --out {run_dir}``
``task``  plan = a task YAML (steps)       → run directly

Drafting uses the same writers the CLI uses (``SpecWriter`` for 3d/video, ``Planner`` + ``plan_to_task``
for GUI missions), so a refusal comes back with the writer's reasons instead of a silent fallback.
Running materializes the plan and executes it as a **task through the gated loop** (``run_set``, the
same call a ``task`` routine makes) — approvals, grants, the run viewer and ``artifacts/runs/`` all
work exactly as they do for routines. A scheduled mission owns a routine ``mission:<id>`` pointing at
the materialized task; "on demand" removes it (one scheduler, no second one).

Storage: ``~/.eeze/missions/<id>.yaml`` (atomic write). ``EEZE_MISSIONS`` overrides the directory so
tests never touch the operator's real missions (same rule as the P2 vault).
"""

from __future__ import annotations

import hashlib

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

KINDS = ("3d", "video", "photo", "task", "files")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,59}$")
RUN_TIMEOUT_S = 900.0


class MissionError(RuntimeError):
    """The mission could not be drafted, saved, validated, materialized or run."""


class MissionDraftError(MissionError):
    """The writer refused to produce a plan — the reasons travel with it, never a silent fallback."""

    def __init__(self, message: str, *, attempts: list[dict] | None = None, model: str = "", draft_dir: str = "") -> None:
        super().__init__(message)
        self.attempts = attempts or []
        self.model = model
        self.draft_dir = draft_dir


def missions_home(home: Path | str | None = None) -> Path:
    if home is not None:
        return Path(home) / "missions"
    env = (os.environ.get("EEZE_MISSIONS") or "").strip()
    return Path(env) if env else Path.home() / ".eeze" / "missions"


def check_id(mid: str) -> str:
    mid = (mid or "").strip().lower()
    if not _ID_RE.match(mid):
        raise MissionError(
            f"invalid mission id {mid!r} — lowercase letters, digits, '-' and '_', max 60 chars"
        )
    return mid


from datetime import UTC, datetime  # noqa: E402 — kept next to the stamp helper it pairs with


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _norm_schedule(value: Any) -> dict:
    """The only schedules v1 understands (mirrors the routines UI)."""
    data = dict(value or {})
    kind = str(data.get("type") or "on_demand").strip().lower()
    if kind == "on_demand":
        return {"type": "on_demand"}
    if kind == "daily":
        at = str(data.get("at") or "08:00").strip()
        if not re.match(r"^\d{2}:\d{2}$", at):
            raise MissionError(f"invalid daily time {at!r} — use HH:MM")
        return {"type": "daily", "at": at}
    if kind == "every":
        try:
            minutes = int(data.get("minutes") or 0)
        except (TypeError, ValueError):
            minutes = 0
        if minutes < 1:
            raise MissionError("'every' needs minutes >= 1")
        return {"type": "every", "minutes": minutes}
    raise MissionError(f"unknown schedule type {kind!r} — on_demand | daily | every")


def effective_last_run(last: dict | None, *, approval_status=None, now: datetime | None = None) -> dict | None:
    """The last run as the owner should see it now (display only; the stored row is untouched).

    - ``needs_approval`` whose approval was denied/abandoned/expired shows that outcome
      (``approval_status`` is ``callable(approval_id) -> status | None``);
    - ``running`` long past the run timeout was interrupted (reboot, killed worker).
    """
    if not last:
        return last
    out = dict(last)
    status = out.get("status")
    if status == "needs_approval" and approval_status and out.get("approval_id"):
        decided = approval_status(str(out["approval_id"]))
        if decided in {"denied", "abandoned", "expired"}:
            out["status"] = decided
    elif status == "running":
        try:
            started = datetime.fromisoformat(str(out.get("at")))
            # Stamps are local wall-clock without an offset (see _now()).
            current = now or (datetime.now() if started.tzinfo is None  # noqa: DTZ005
                              else datetime.now(UTC))
            age = (current - started).total_seconds()
            if age > RUN_TIMEOUT_S + 600:
                out["status"] = "interrupted"
        except (TypeError, ValueError):
            pass
    return out


def to_public(row: dict, *, plan: bool, approval_status=None) -> dict:
    """What the API returns. Lists carry no plan text; a single mission carries it verbatim."""
    out = {k: row.get(k) for k in ("id", "name", "kind", "agent_id", "goal", "schedule", "sources", "created_at", "updated_at", "last_run")}
    out["last_run"] = effective_last_run(row.get("last_run"), approval_status=approval_status)
    out["plan_meta"] = {k: v for k, v in (row.get("plan_meta") or {}).items() if k != "draft_text"}
    out["has_plan"] = bool(str(row.get("plan") or "").strip())
    out["plan_chars"] = len(str(row.get("plan") or ""))
    if plan:
        out["plan"] = str(row.get("plan") or "")
    return out


class MissionStore:
    """One YAML per mission under ``~/.eeze/missions`` — atomic writes, id-safe paths."""

    def __init__(self, home: Path | str | None = None) -> None:
        self.root = missions_home(home)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, mid: str) -> Path:
        return self.root / f"{check_id(mid)}.yaml"

    def _read(self, path: Path) -> dict | None:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — a corrupt mission must not take the list down
            return None
        return data if isinstance(data, dict) else None

    def _write(self, row: dict) -> None:
        target = self.path(str(row["id"]))
        tmp = target.with_suffix(".yaml.tmp")
        tmp.write_text(yaml.safe_dump(row, sort_keys=False, allow_unicode=True), encoding="utf-8")
        os.replace(tmp, target)

    def list(self, approval_status=None) -> list[dict]:
        rows: list[dict] = []
        for path in sorted(self.root.glob("*.yaml")):
            row = self._read(path)
            if row is not None and row.get("id"):
                rows.append(to_public(row, plan=False, approval_status=approval_status))
        rows.sort(key=lambda r: str(r.get("updated_at") or ""), reverse=True)
        return rows

    def get(self, mid: str) -> dict | None:
        path = self.path(mid)
        return self._read(path) if path.exists() else None

    def save(self, data: dict) -> dict:
        """Create or update. Missing fields fall back to the stored mission (partial updates are safe)."""
        mid = check_id(str(data.get("id") or ""))
        previous = self.get(mid) or {}
        kind = str(data.get("kind") or previous.get("kind") or "task").strip().lower()
        if kind not in KINDS:
            raise MissionError(f"unknown kind {kind!r} — 3d | video | photo | task")

        def pick(field: str, default: Any = "") -> Any:
            raw = data.get(field)
            if raw is None:
                return previous.get(field, default)
            return raw

        plan = str(pick("plan", "") or "")
        meta = dict(data.get("plan_meta") or previous.get("plan_meta") or {})
        draft_text = str(meta.get("draft_text") or "")
        if plan.strip():
            meta["edited"] = bool(draft_text.strip()) and plan.strip() != draft_text.strip()
        else:
            meta.pop("edited", None)

        row = {
            "id": mid,
            "name": str(data.get("name") or previous.get("name") or mid).strip()[:80],
            "kind": kind,
            "agent_id": str(pick("agent_id", "default") or "default"),
            "goal": str(pick("goal", "") or ""),
            "plan": plan,
            "plan_meta": meta,
            "schedule": _norm_schedule(data.get("schedule") or previous.get("schedule")),
            "sources": str(pick("sources", "") or ""),
            "created_at": previous.get("created_at") or _now(),
            "updated_at": _now(),
            "last_run": previous.get("last_run"),
        }
        self._write(row)
        return to_public(row, plan=True)

    def remove(self, mid: str) -> bool:
        path = self.path(mid)
        if not path.exists():
            return False
        path.unlink()
        return True

    def record_run(self, mid: str, *, runset_id: str, status: str, approval_id: str | None = None, out_dir: str = "") -> None:
        row = self.get(mid)
        if row is None:
            raise MissionError(f"unknown mission: {mid!r}")
        row["last_run"] = {
            "runset_id": runset_id,
            "status": status,
            "approval_id": approval_id,
            "out_dir": out_dir,
            "at": _now(),
        }
        row["updated_at"] = _now()
        self._write(row)

    def record_resume(self, *, task_path: Path, runset_id: str, approval_id: str, summary: dict) -> bool:
        """Update only the matching mission's run status after an approved resume."""
        task_path = Path(task_path).resolve()
        if task_path.name != "task.yaml" or task_path.parent.parent != self.root.resolve():
            return False
        mid = task_path.parent.name
        row = self.get(mid)
        if row is None:
            return False
        last = row.get("last_run") or {}
        if (last.get("runset_id") != runset_id or last.get("approval_id") != approval_id
                or last.get("status") != "needs_approval"):
            return False
        from eeze_agent.core.routines import task_routine_status

        outcome = task_routine_status(summary)
        last["status"] = "done" if outcome == "ok" else outcome
        if outcome == "needs_approval":
            last["approval_id"] = summary.get("approval_id")
        last["at"] = _now()
        row["updated_at"] = _now()
        self._write(row)
        return True

    def plan_dir(self, mid: str) -> Path:
        path = self.root / check_id(mid)
        path.mkdir(parents=True, exist_ok=True)
        return path


def _spec_for(kind: str, path: Path):
    """Parse/validate a plan with the SAME loaders the runner uses."""
    if kind == "3d":
        from eeze_agent.verticals.render3d.spec import load_spec

        return load_spec(path)
    if kind == "video":
        from eeze_agent.verticals.video.spec import load_spec

        return load_spec(path)
    if kind == "photo":
        from eeze_agent.verticals.photo.spec import load_spec

        return load_spec(path)
    if kind == "task":
        from eeze_agent.core.tasks import load_task

        return load_task(path)
    if kind == "files":
        from eeze_agent.verticals.files.spec import load_spec

        return load_spec(path)
    raise MissionError(f"unknown kind {kind!r} — 3d | video | photo | task")


def validate_plan(*, kind: str, plan_text: str, sources: str = "") -> dict:
    """Schema + vocabulary check on the CURRENT text (unsaved edits included). Honest errors only."""
    kind = (kind or "").strip().lower()
    errors: list[str] = []
    if kind not in KINDS:
        return {"ok": False, "errors": [f"unknown kind {kind!r}"]}
    text = str(plan_text or "")
    if not text.strip():
        return {"ok": False, "errors": ["the plan is empty — generate a draft first"]}
    with tempfile.TemporaryDirectory(prefix="eeze-mission-check-") as tmp:
        path = Path(tmp) / ("task.yaml" if kind == "task" else "spec.yaml")
        path.write_text(text, encoding="utf-8")
        spec = None
        try:
            spec = _spec_for(kind, path)
        except Exception as exc:  # noqa: BLE001 — every loader failure is data here
            errors.append(f"{type(exc).__name__}: {exc}")
    if kind == "video" and spec is not None and not errors:
        try:
            from eeze_agent.brains.specwriter import _feasibility_video

            _names, facts = _sources_facts(sources)
            errors.extend(_feasibility_video(spec, facts))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
    if kind == "photo" and spec is not None and not errors:
        try:
            from eeze_agent.brains.specwriter import _feasibility_photo

            if not str(sources or "").strip():
                raise MissionError("a photo mission needs a sources folder")
            _names, facts = _photo_sources(sources)
            errors.extend(_feasibility_photo(spec, facts))
        except Exception as exc:  # noqa: BLE001 — validation returns reasons, never runs
            errors.append(f"{type(exc).__name__}: {exc}")
    if kind == "files" and spec is not None and not errors:
        from eeze_agent.brains.specwriter import _feasibility_files

        if not str(sources or "").strip():
            errors.append("a files mission needs the folder to work on")
        else:
            errors.extend(_feasibility_files(spec, str(sources)))
    if kind == "3d" and spec is not None and not errors:
        try:
            from eeze_agent.brains.specwriter import _feasibility_3d

            errors.extend(_feasibility_3d(spec))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
    return {"ok": not errors, "errors": errors}


def _sources_facts(sources: str) -> tuple[dict[str, str], dict[str, dict]]:
    from eeze_agent.brains.specwriter import collect_sources

    ffprobe = None
    try:
        from eeze_agent.verticals.video.probe import find_tools

        _ffmpeg, ffprobe = find_tools()
    except Exception:  # noqa: BLE001 — no ffprobe: sources are listed without media facts
        ffprobe = None
    return collect_sources(sources, ffprobe=ffprobe)


def _photo_sources(sources: str) -> tuple[dict[str, str], dict[str, dict]]:
    """Enumerate only genuinely probed local PNG/JPEG files for photo missions."""
    from eeze_agent.brains.specwriter import collect_sources
    from eeze_agent.verticals.video.probe import find_tools

    _ffmpeg, ffprobe = find_tools()
    names, facts = collect_sources(sources, ffprobe=ffprobe)
    codecs = {".png": "png", ".jpg": "mjpeg", ".jpeg": "mjpeg"}
    accepted = {name: sheet for name, sheet in facts.items()
                if sheet.get("kind") == "image"
                and sheet.get("codec_v") == codecs.get(Path(str(sheet.get("path") or "")).suffix.lower())
                and isinstance(sheet.get("width"), int) and sheet["width"] > 0
                and isinstance(sheet.get("height"), int) and sheet["height"] > 0
                and isinstance(sheet.get("size_bytes"), int) and sheet["size_bytes"] > 0}
    if not accepted:
        raise MissionError("no genuine PNG/JPEG images found in the sources folder")
    return {name: names[name] for name in accepted}, accepted


def draft(*, kind: str, goal: str, name_hint: str = "mission", sources: str = "",
          home: Path | str | None = None, budget_agent: object | None = None) -> dict:
    """Write a plan from a plain-language goal. Real model call; refusals carry the reasons."""
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        raise MissionError(f"unknown kind {kind!r} — 3d | video | photo | task")
    goal = str(goal or "").strip()
    if not goal:
        raise MissionError("the goal is empty — write what the mission should make")
    started = time.perf_counter()

    if kind == "task":
        from eeze_agent.brains.planner import Planner
        from eeze_agent.core.goal import plan_to_task

        planner = Planner()
        planner.budget_agent = budget_agent
        plan = planner.plan(goal)
        task = plan_to_task(plan, name_hint or "mission")
        text = yaml.safe_dump(task.model_dump(exclude_none=True), sort_keys=False, allow_unicode=True)
        model = str(getattr(planner, "model", "") or "")
        tokens = int(getattr(planner, "last_tokens", 0) or 0)
        return {
            "plan": text,
            "plan_kind": "task",
            "model": model,
            "attempts": [{"attempt": 1, "error": None}],
            "tokens": tokens,
            "cost_usd": 0.0 if model.startswith("codex:") else None,
            "ms": round((time.perf_counter() - started) * 1000, 1),
        }

    from eeze_agent.brains.specwriter import SpecWriter

    out_dir = missions_home(home) / "_drafts" / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}"
    out_dir.mkdir(parents=True, exist_ok=True)
    writer = SpecWriter()
    writer.budget_agent = budget_agent
    if kind == "photo" and getattr(writer, "engine", "") != "codex":
        raise MissionError("photo drafting requires the local Codex engine; paid HTTP providers are disabled")
    try:
        if kind == "video":
            if not str(sources or "").strip():
                raise MissionError("a video mission needs a sources dir — point at the folder with the clips/stills")
            names, facts = _sources_facts(str(sources))
            if not names:
                raise MissionError(f"no video/image files found in {sources!r}")
            result = writer.write_video(goal, sources=names, facts=facts, out_dir=out_dir, name_hint=name_hint or "mission")
            result.sources = facts
        elif kind == "photo":
            if not str(sources or "").strip():
                raise MissionError("a photo mission needs a sources folder with PNG/JPEG images")
            names, facts = _photo_sources(str(sources))
            result = writer.write_photo(
                goal, sources=names, facts=facts, out_dir=out_dir, name_hint=name_hint or "mission"
            )
            result.sources = facts
        elif kind == "files":
            from eeze_agent.brains.specwriter import split_sources

            folder, _only = split_sources(str(sources or ""))
            if not str(sources or "").strip() or not folder.is_dir():
                raise MissionError("a files mission needs an existing folder — paste its path")
            result = writer.write_files(goal, folder=str(folder), out_dir=out_dir,
                                        name_hint=name_hint or "files")
        else:
            result = writer.write_scene(goal, out_dir=out_dir, name_hint=name_hint or "mission")
    except MissionError:
        raise
    except Exception as exc:
        report: dict = {}
        try:
            report = json.loads((out_dir / "write-report.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 — no report means the failure was before the first call
            report = {}
        raise MissionDraftError(
            str(exc),
            attempts=report.get("attempts") or [],
            model=str(report.get("model") or ""),
            draft_dir=str(out_dir),
        ) from exc
    return {
        "plan": result.yaml_text,
        "plan_kind": kind,
        "model": result.model,
        "attempts": result.attempts,
        "tokens": result.tokens,
        "cost_usd": result.cost_usd,
        "ms": round((time.perf_counter() - started) * 1000, 1),
        "draft_dir": str(out_dir),
    }


def _eeze_exe() -> str:
    """The CLI that ships next to this interpreter (missions call it from their task)."""
    candidate = Path(sys.executable).with_name("eeze.exe" if os.name == "nt" else "eeze")
    return str(candidate if candidate.exists() else "eeze")


def materialize(mission: dict, *, home: Path | str | None = None) -> Path:
    """Write the mission's plan where the runner reads it; return the TASK path to execute."""
    kind = str(mission.get("kind") or "task")
    plan_text = str(mission.get("plan") or "")
    if not plan_text.strip():
        raise MissionError("mission has no plan yet — generate a draft and save it first")
    store = MissionStore(home)
    root = store.plan_dir(str(mission["id"]))

    if kind == "task":
        task_path = root / "task.yaml"
        task_path.write_text(plan_text, encoding="utf-8")
        _spec_for("task", task_path)  # refuse garbage now, with the loader's reason
        return task_path

    # Content-addressed spec file: the approval digest covers the task (incl. vars.spec and
    # vars.spec_sha256), so editing the plan after approving it can never run the edited
    # plan under the old approval — the path and hash change, the resume is refused.
    digest = hashlib.sha256(plan_text.encode("utf-8")).hexdigest()
    spec_path = root / f"spec-{digest[:16]}.yaml"
    spec_path.write_text(plan_text, encoding="utf-8")
    (root / "spec.yaml").write_text(plan_text, encoding="utf-8")  # stable name for humans
    spec = _spec_for(kind, spec_path)
    output = str(getattr(spec, "output", "") or "")
    report_name = {"3d": "render-report.json", "files": "files-report.json"}.get(kind, "edit-report.json")
    clauses = [
        f"file_exists|{{run_dir}}/{report_name}",
        f"file_size_gt|{{run_dir}}/{report_name}|200",
    ]
    if kind == "files":
        clauses = [f"file_exists|{{run_dir}}/{report_name}"]
    elif output.lower().endswith((".mp4", ".png", ".jpg", ".jpeg", ".gif", ".webm", ".mov")):
        # `output` wrote a literal file name — verify the deliverable too (a step id or a bare name
        # is named by the runner itself, and the CLI's own exit code already fails on a missing one).
        minimum = 100 if kind == "photo" else 2000
        clauses += [f"file_exists|{{run_dir}}/{output}", f"file_size_gt|{{run_dir}}/{output}|{minimum}"]
    extra = ""
    if kind in {"video", "photo"}:
        try:
            from eeze_agent.verticals.video.probe import find_tools

            ffmpeg, _ffprobe = find_tools()
            extra = f' --ffmpeg-dir "{Path(ffmpeg).parent}"'
        except Exception:  # noqa: BLE001 — PATH lookup is the runner's fallback
            extra = ""
    step: dict[str, Any] = {
        "id": "run",
        "action": "run_script",
        # Renaming/moving the owner's own files: its own risk class, so an install_exec grant
        # given to a render mission can never wave a rename batch through (and destructive
        # steps never accept "always allow" grants).
        **({"risk": "destructive"} if kind == "files" else {}),
        "intent": f"Run the mission plan ({kind}): {mission.get('name') or mission['id']}",
        "command": '"{eeze}" ' + kind + f' "{{spec}}" --out "{{run_dir}}"{extra}',
        "timeout_s": RUN_TIMEOUT_S,
        "retries": 0,
        "verify_code": "; ".join(clauses),
    }
    task = {
        "name": f"mission-{mission['id']}",
        "app": "",
        "vars": {"eeze": _eeze_exe(), "spec": str(spec_path), "spec_sha256": digest},
        "steps": [step],
    }
    task_path = root / "task.yaml"
    _atomic_write(task_path, yaml.safe_dump(task, sort_keys=False, allow_unicode=True))
    _spec_for("task", task_path)
    return task_path


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + replace, so a scheduled run never reads half a task file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def sync_schedule(mission: dict, *, home: Path | str | None = None) -> dict:
    """Missions own their schedule; a routine named ``mission:<id>`` mirrors it. One scheduler only."""
    from eeze_agent.core.routines import RoutineStore

    store = RoutineStore()
    routine_id = f"mission:{mission['id']}"
    schedule = _norm_schedule(mission.get("schedule"))
    if schedule.get("type") == "on_demand":
        return {"removed": bool(store.remove(routine_id))}
    task_path = materialize(mission, home=home)
    store.add(
        routine_id,
        name=f"Mission · {mission.get('name') or mission['id']}",
        kind="task",
        schedule=schedule,
        params={"task_path": str(task_path)},
        agent_id=str(mission.get("agent_id") or "default"),
        enabled=True,
    )
    return {"routine_id": routine_id, "task_path": str(task_path)}


def run_mission(mission_id: str, *, repo_root: Path | str, home: Path | str | None = None, brain=None) -> dict:
    """Execute a mission through the gated loop; record the run on the mission; never raises quietly."""
    from eeze_agent.agents.models import AgentContext
    from eeze_agent.agents.registry import load_registry
    from eeze_agent.brains.registry import make_brain
    from eeze_agent.core.approvals import ApprovalStore
    from eeze_agent.core.journal import RunJournal
    from eeze_agent.core.loop import run_set
    from eeze_agent.core.risk import policy_for_agent
    from eeze_agent.core.tasks import load_task
    from eeze_agent.drivers.cua import CuaDriver

    repo_root = Path(repo_root)
    store = MissionStore(home)
    mission = store.get(mission_id)
    if mission is None:
        return {"status": "error", "error": f"unknown mission: {mission_id!r}"}
    try:
        task_path = materialize(mission, home=home)
    except Exception as exc:  # noqa: BLE001 — the reason travels back to the caller
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}

    task = load_task(task_path)
    agent = load_registry(repo_root).get(str(mission.get("agent_id") or "default"))
    runs_root = repo_root / "artifacts" / "runs"
    runset_id = time.strftime("%Y%m%d-%H%M%S") + f"-mission-{mission_id}"
    out_dir = runs_root / runset_id
    journal = RunJournal(runs_root, runset_id, agent_id=agent.id)
    ctx = AgentContext(agent=agent)
    ctx.runset_id = runset_id
    # Visible immediately: the screen polls while a mission is "running".
    store.record_run(mission_id, runset_id=runset_id, status="running", out_dir=str(out_dir))
    try:
        summary = run_set(
            task=task,
            agent_ctx=ctx,
            driver=CuaDriver(),
            brain=brain if brain is not None else make_brain(agent_id=agent.id, repo_root=repo_root, task=task),
            brain_factory=lambda **kw: make_brain(agent_id=agent.id, repo_root=repo_root, task=task, **kw),
            journal=journal,
            runs=1,
            out_dir=out_dir,
            policy=policy_for_agent(agent.permissions),
            approvals=ApprovalStore(),
            task_path=task_path,
        )
    except BaseException as exc:
        # Never leave the mission showing "running" after a crash.
        store.record_run(mission_id, runset_id=runset_id, status="error", out_dir=str(out_dir))
        raise RuntimeError(f"mission run crashed: {type(exc).__name__}: {exc}") from exc
    finally:
        journal.close()
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    from eeze_agent.core.routines import task_routine_status

    # The run-set's own status is only ever "done" or "needs_approval" — a failed 0/1 run
    # used to be recorded as a finished mission. Same mapping as the resume path.
    outcome = task_routine_status(summary)
    status = "done" if outcome == "ok" else outcome
    store.record_run(
        mission_id,
        runset_id=runset_id,
        status=status,
        approval_id=summary.get("approval_id"),
        out_dir=str(out_dir),
    )
    return {
        "status": status,
        "runset_id": runset_id,
        "approval_id": summary.get("approval_id"),
        "out_dir": str(out_dir),
        "success_rate": summary.get("success_rate"),
    }
