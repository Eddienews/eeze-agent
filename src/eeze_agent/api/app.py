"""Read-only HTTP API (F1.5 slice): agents · approvals(stub) · runs · system.

All endpoints are side-effect free. Data sources:
- agents:  ``agents.yaml`` registry (falls back to the built-in ``default`` agent)
- runs:    ``artifacts/runs/<runset>/{journal.jsonl, summary.json}``
- system:  ``cua-driver status`` (cached) + journal aggregates

Wire contract: see ``docs/API.md``. Write endpoints (POST/PATCH/…) arrive with F2.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from eeze_agent.agents.registry import load_registry
from eeze_agent.api import schemas
from eeze_agent.core import spend as _spend
from eeze_agent.core.approvals import ApprovalStore
from eeze_agent.core.notify import RoutineFailureWatcher


def create_app(
    repo_root: Path | None = None,
    serve_ui: bool | None = None,
    eeze_home: Path | None = None,
    scheduler: bool = False,
) -> FastAPI:
    root = repo_root or Path(__file__).resolve().parents[3]
    home = eeze_home or Path.home() / ".eeze"
    store = ApprovalStore()
    # Developer conveniences are opt-in: the Vite dev-server origins and FastAPI's schema
    # pages. Left on, any page served on localhost:3000/5173 (any npm dev server) got the
    # operator's cookie, and /docs exposed the whole API map to anyone with a tunnel URL.
    dev_mode = (os.environ.get("EEZE_DEV_ORIGINS") or "").strip().lower() in {"1", "true", "yes", "on"}
    app = FastAPI(
        title="Eeze Agent API", version="0.1.0-f4",
        docs_url="/docs" if dev_mode else None,
        redoc_url="/redoc" if dev_mode else None,
        openapi_url="/openapi.json" if dev_mode else None,
    )
    router = APIRouter()

    if scheduler:
        from eeze_agent.core.notify import ApprovalWatcher
        from eeze_agent.core.routines import RoutineStore, Scheduler
        from eeze_agent.core.settings import SettingsStore

        routines = RoutineStore()
        settings = SettingsStore()
        routine_scheduler = Scheduler(routines, repo_root=root, home=home, interval_s=30.0)
        routine_scheduler.start()
        app.state.scheduler = routine_scheduler

        watcher = ApprovalWatcher(store, settings)
        watcher.start()
        app.state.notify_watcher = watcher
        from eeze_agent.core.notify import StaleApprovalReminder

        reminder = StaleApprovalReminder(store, settings)
        reminder.start()
        app.state.approval_reminder = reminder
        failure_watcher = RoutineFailureWatcher(routines, settings)
        failure_watcher.tick()  # baseline old runs before the notification thread starts
        failure_watcher.start()
        app.state.routine_failure_watcher = failure_watcher

    # Only explicit local development origins may receive credentialed responses.
    # Register CORS last, outside authentication, so even 401s carry CORS headers.
    local_dev_origins = ["http://localhost:5173", "http://localhost:3000"] if dev_mode else []

    # ---------------- local operator boundary ----------------

    # How long a signed-in browser stays signed in (cookie + server-side check).
    # `eeze unpair` rotates api.token, which signs every browser out at once.
    try:
        session_s = int(max(1.0, min(365.0, float(os.environ.get("EEZE_SESSION_DAYS", "30")))) * 86400)
    except ValueError:
        session_s = 30 * 86400

    def _local_token() -> str:
        """Per-machine write token (F2). Created on first use; never leaves the box."""
        home.mkdir(parents=True, exist_ok=True)
        token_file = home / "api.token"
        if not token_file.exists():
            token_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
            if os.name != "nt":
                os.chmod(token_file, 0o600)
        return token_file.read_text(encoding="utf-8").strip()

    def _peer_allowed(request: Request) -> bool:
        peer = request.client.host if request.client else ""
        try:
            loopback = ipaddress.ip_address(peer).is_loopback
        except ValueError:
            loopback = peer == "testclient"  # Starlette's in-process test transport only
        host = request.url.hostname or ""
        try:
            local_host = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local_host = host in {"localhost", "testserver"}
        return (loopback and local_host
                and not request.headers.get("x-forwarded-for")
                and not request.headers.get("cf-connecting-ip"))

    def _origin_allowed(request: Request) -> bool:
        origin = request.headers.get("origin")
        if origin is None:
            return True  # local CLI; browser writes always include Origin
        return origin == f"{request.url.scheme}://{request.url.netloc}" or origin in local_dev_origins

    def _valid_cookie(request: Request, expected: str) -> bool:
        value = request.cookies.get("eeze_operator", "")
        try:
            issued, nonce, signature = value.split(".", 2)
            age = int(time.time()) - int(issued)
            if not (0 <= age <= session_s) or not nonce:
                return False
        except (ValueError, AttributeError):
            return False
        signed = f"{issued}.{nonce}".encode()
        expected_sig = hmac.new(expected.encode(), signed, hashlib.sha256).hexdigest()
        return secrets.compare_digest(signature, expected_sig)

    def _read_token() -> str:
        token_file = home / "api.token"
        return token_file.read_text(encoding="utf-8").strip() if token_file.is_file() else ""

    def _valid_header(supplied: str | None) -> bool:
        expected = _read_token()
        return bool(supplied and expected and secrets.compare_digest(supplied, expected))

    def _valid_session(request: Request) -> bool:
        expected = _read_token()
        return bool(expected and _valid_cookie(request, expected))

    def _operator_allowed(request: Request) -> bool:
        return _valid_header(request.headers.get("x-eeze-token")) or _valid_session(request)

    @app.middleware("http")
    async def operator_boundary(request: Request, call_next):
        path = request.url.path
        if not (path in {"/api", "/artifacts"}
                or path.startswith(("/api/", "/artifacts/"))):
            return await call_next(request)
        if not _peer_allowed(request) or not _origin_allowed(request):
            return JSONResponse({"error": {"code": "forbidden", "message": "local operator only"}},
                                status_code=403)
        if request.method == "OPTIONS":
            return await call_next(request)
        if path in {"/api/session/pair", "/api/session/token", "/api/health"}:
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response
        if not _operator_allowed(request):
            return JSONResponse({"error": {"code": "unauthorized",
                                           "message": "Local operator pairing required"}},
                                status_code=401, headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    def _require_write(request: Request, supplied: str | None) -> None:
        """Same local operator credential as the read boundary; no remote/proxy writes."""
        if not _peer_allowed(request) or not _origin_allowed(request):
            raise HTTPException(status_code=403, detail="local operator only")
        # Cookie writes must be browser-originated; scripts without Origin use the
        # explicit header instead. This also keeps existing CLI callers stable.
        if _valid_header(supplied) or (request.headers.get("origin") and _valid_session(request)):
            return
        raise HTTPException(status_code=401, detail="operator pairing required")

    def _spawn_resume(approval_id: str) -> str:
        """Detached resume of a paused run/routine; returns the log path.

        The resume command comes from the run-state payload (``resume_argv``) so tasks
        and routines share one path; defaults to ``run --resume``.
        """
        from eeze_agent.core.routines import spawn_detached

        home.mkdir(parents=True, exist_ok=True)
        log_path = home / f"resume-{approval_id}.log"
        argv = ["run", "--resume", approval_id]
        state = store.run_state_for(approval_id)
        if state is not None:
            try:
                payload = json.loads(state["payload"])
                candidate = payload.get("resume_argv")
                if isinstance(candidate, list) and all(isinstance(x, str) for x in candidate):
                    argv = candidate
            except (json.JSONDecodeError, TypeError):
                pass
        spawn_detached(argv, cwd=root, log_path=log_path)
        return str(log_path)

    def _approval_resumable(row: dict) -> bool:
        state = store.run_state_for(row["id"])
        return bool(row.get("action_digest") and state and state["status"] == "waiting")

    def _approval_public(row: dict) -> schemas.Approval:
        try:
            preview = json.loads(row.get("payload") or "{}")
        except json.JSONDecodeError:
            preview = {}
        preview = {**preview, "reason": row.get("reason")}
        return schemas.Approval(
            id=row["id"],
            agent_id=row.get("agent_id") or "default",
            run_id=f"{row.get('runset_id')}.{row.get('run_index')}",
            step_id=row.get("step_id") or "",
            title=f"{row.get('task')} · {row.get('step_id')}",
            risk_class=row.get("risk_class") or "write_local",
            payload_preview=preview,
            requested_at=row.get("created_at"),
            status=row.get("status") or "pending",
            resumable=_approval_resumable(row),
        )

    def _grant_public(row: dict) -> schemas.Grant:
        now_iso = datetime.now(UTC).isoformat(timespec="seconds")
        if row.get("revoked_at"):
            status = "revoked"
        elif row.get("expires_at") and row["expires_at"] <= now_iso:
            status = "expired"
        else:
            status = "active"
        return schemas.Grant(
            id=row["id"],
            agent_id=row["agent_id"],
            risk_class=row["risk_class"],
            scope=row["scope"],
            task=row.get("task"),
            created_at=row.get("created_at"),
            expires_at=row.get("expires_at"),
            revoked_at=row.get("revoked_at"),
            status=status,
        )

    def runs_root() -> Path:
        return root / "artifacts" / "runs"

    def _journal(path: Path) -> list[dict]:
        rows: list[dict] = []
        if not path.exists():
            return rows
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return rows
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return rows

    def _runsets(limit: int = 100) -> list[Path]:
        rr = runs_root()
        if not rr.exists():
            return []
        dirs = [p for p in rr.iterdir() if (p / "journal.jsonl").exists()]
        return sorted(dirs, key=lambda p: p.name, reverse=True)[:limit]

    def _runs_from(journal: list[dict], runset_id: str) -> list[schemas.Run]:
        meta = next((e for e in journal if e.get("kind") == "runset_start"), {})
        task = str(meta.get("task") or "")
        agent = meta.get("agent_id")
        starts = {e.get("run_index"): e for e in journal if e.get("kind") == "run_start"}
        interfered: set = set()
        for e in journal:
            if e.get("kind") == "step_end" and e.get("interference"):
                interfered.add(e.get("run_index"))
            if e.get("kind") == "run_error" and e.get("error") == "external_input_detected":
                interfered.add(e.get("run_index"))
        out: list[schemas.Run] = []
        for e in journal:
            if e.get("kind") != "run_end":
                continue
            ix = e.get("run_index")
            st = starts.get(ix, {})
            interference = ix in interfered or e.get("error") == "external_input_detected"
            status = "interference" if interference else ("ok" if e.get("ok") else "failed")
            out.append(
                schemas.Run(
                    id=f"{runset_id}.{ix}",
                    runset_id=runset_id,
                    agent_id=st.get("agent_id") or agent,
                    task_name=task,
                    status=status,
                    started_at=st.get("ts"),
                    ended_at=e.get("ts"),
                    cycle_ms=e.get("cycle_ms"),
                    interference=interference,
                    error=e.get("error"),
                )
            )
        return out

    def _all_runs(limit_runsets: int = 50) -> list[schemas.Run]:
        runs: list[schemas.Run] = []
        for d in _runsets(limit_runsets):
            runs.extend(_runs_from(_journal(d / "journal.jsonl"), d.name))
        return runs

    def _run_detail(runset_id: str, run_ix: int) -> schemas.RunDetail | None:
        d = runs_root() / runset_id
        journal = _journal(d / "journal.jsonl")
        if not journal:
            return None
        base = next(
            (r for r in _runs_from(journal, runset_id) if r.id == f"{runset_id}.{run_ix}"),
            None,
        )
        if base is None:
            return None
        sels: dict = {}
        for e in journal:
            if (
                e.get("run_index") == run_ix
                and e.get("kind") == "judgment"
                and e.get("judgment_kind") == "select_element"
            ):
                sels[e.get("step_id")] = e
        run_dir = d / f"run-{run_ix:02d}"
        step_files: list[str] = []
        if run_dir.exists():
            step_files = [
                f"run-{run_ix:02d}/{p.name}" for p in sorted(run_dir.iterdir()) if p.is_file()
            ]
        steps: list[schemas.RunStep] = []
        idx = 0
        for e in journal:
            if e.get("kind") != "step_end" or e.get("run_index") != run_ix:
                continue
            idx += 1
            sid = str(e.get("step_id"))
            j = sels.get(sid)
            steps.append(
                schemas.RunStep(
                    id=sid,
                    index=idx,
                    ok=bool(e.get("ok")),
                    attempts=int(e.get("attempts") or 1),
                    ms=e.get("ms"),
                    interference=bool(e.get("interference")),
                    selected=e.get("selected"),
                    write_method=e.get("write_method"),
                    verification=e.get("verify"),
                    artifacts=[f for f in step_files if f"step-{sid}" in f],
                    judgment=(
                        schemas.RunStepJudgment(
                            kind="select_element",
                            question=str(j.get("question") or ""),
                            answer=j.get("answer"),
                            confidence=j.get("confidence"),
                            ms=j.get("ms"),
                        )
                        if j
                        else None
                    ),
                )
            )
        summary = None
        sj = d / "summary.json"
        if sj.exists():
            try:
                summary = json.loads(sj.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                summary = None
        return schemas.RunDetail(
            **base.model_dump(),
            steps=steps,
            journal_url=f"/artifacts/runs/{runset_id}/journal.jsonl",
            summary=summary,
        )

    _daemon_cache: dict = {"at": 0.0, "value": schemas.DaemonStatus()}

    def _daemon_status(ttl_s: float = 10.0) -> schemas.DaemonStatus:
        now = time.time()
        if now - _daemon_cache["at"] < ttl_s:
            return _daemon_cache["value"]
        st = schemas.DaemonStatus()
        try:
            proc = subprocess.run(
                ["cua-driver", "status"],
                capture_output=True, text=True, timeout=8, check=False,
            )
            text = proc.stdout + proc.stderr
            st.running = "daemon is running" in text.lower()
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("pid:"):
                    try:
                        st.pid = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
                if line.startswith("permission mode:"):
                    st.permission_mode = line.split(":", 1)[1].strip()
        except (OSError, subprocess.TimeoutExpired):
            st.running = False
        _daemon_cache.update({"at": now, "value": st})
        return st

    def _within_24h(ts: str | None) -> bool:
        if not ts:
            return False
        try:
            started = datetime.fromisoformat(ts)
        except ValueError:
            return False
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return (datetime.now(UTC) - started) <= timedelta(hours=24)

    def _agent_public(agent_id: str, runs: list[schemas.Run]) -> schemas.Agent:
        registry = load_registry(root, home)
        a = registry.get(agent_id)
        perms = a.permissions or {}
        mine = [r for r in runs if (r.agent_id or "default") == a.id]
        ok = [r for r in mine if not r.interference and r.status == "ok"]
        eligible = [r for r in mine if not r.interference]
        cycles = [r.cycle_ms for r in mine if r.cycle_ms]
        cost = 0.0
        for d in _runsets(50):
            journal = _journal(d / "journal.jsonl")
            if any((e.get("agent_id") or "default") == a.id for e in journal[:2]):
                sj = d / "summary.json"
                if sj.exists():
                    try:
                        cost += float(json.loads(sj.read_text(encoding="utf-8")).get("cost_estimate_usd") or 0)
                    except (OSError, json.JSONDecodeError, TypeError, ValueError):
                        pass
        metrics = schemas.AgentMetrics(
            runs_total=len(mine),
            runs_24h=sum(1 for r in mine if _within_24h(r.started_at)),
            success_rate=(len(ok) / len(eligible)) if eligible else None,
            avg_cycle_ms=(sum(cycles) / len(cycles)) if cycles else None,
            cost_usd=round(cost, 6),
        )
        return schemas.Agent(
            id=a.id,
            name=a.name,
            role=a.role,
            description=a.description,
            permissions=schemas.AgentPermissions(
                risk_classes=[str(x) for x in perms.get("risk_classes", [])],
                apps=[str(x) for x in perms.get("apps", ["*"])],
                allow_foreground=bool(perms.get("allow_foreground", False)),
            ),
            tools=a.tools,
            model=a.model or {"brain": "jev"},
            metrics=metrics,
            budget_usd_daily=a.budget_usd_daily,
            budget_effective_usd=_spend.budget_for(a),
            spent_today_usd=round(_spend.spent_today(a.id), 6),
            source="user" if a.id in {u.get("id") for u in _read_user_agents()} else "repo",
        )

    # ---------------- endpoints ----------------

    @app.exception_handler(StarletteHTTPException)
    async def _http_exc(request, exc):
        code = {404: "not_found", 400: "invalid_input", 409: "conflict"}.get(
            exc.status_code, f"http_{exc.status_code}"
        )
        # `message` is the operator-facing line; a dict detail keeps its structure (e.g. the spec
        # writer's per-attempt reasons) instead of being flattened into one string.
        detail = exc.detail
        if isinstance(detail, dict):
            message = str(detail.get("message") or detail.get("error") or "request refused")
            payload = {k: v for k, v in detail.items() if k != "message"}
        else:
            message, payload = str(detail), {}
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": message, "detail": payload}},
        )

    @router.get("/agents", response_model=schemas.Page[schemas.Agent])
    def list_agents() -> schemas.Page[schemas.Agent]:
        runs = _all_runs()
        registry = load_registry(root, home)
        items = [_agent_public(agent_id, runs) for agent_id in registry.ids()]
        return schemas.Page[schemas.Agent](items=items, total=len(items), limit=len(items), offset=0)

    @router.get("/agents/{agent_id}", response_model=schemas.Agent)
    def get_agent(agent_id: str) -> schemas.Agent:
        try:
            return _agent_public(agent_id, _all_runs())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown agent: {agent_id}") from exc

    @router.get("/approvals", response_model=schemas.Page[schemas.Approval])
    def list_approvals(
        status: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> schemas.Page[schemas.Approval]:
        rows = store.list(status=status, limit=limit, offset=offset)
        items = [_approval_public(r) for r in rows]
        return schemas.Page[schemas.Approval](
            items=items, total=store.count(status=status), limit=limit, offset=offset
        )

    started_at = time.time()

    @router.get("/system/freshness")
    def freshness() -> dict:
        """Is an update waiting? New code on disk the service has not loaded, or UI sources
        newer than the built screens -> the app shows "run install.cmd"."""
        def newest(base: Path, pattern: str) -> float:
            try:
                return max((p.stat().st_mtime for p in base.rglob(pattern)), default=0.0)
            except OSError:
                return 0.0

        code = newest(root / "src" / "eeze_agent", "*.py")
        ui_src = newest(root / "ui" / "src", "*.ts*")
        built = root / "ui" / "dist" / "client" / "index.html"
        ui_built = built.stat().st_mtime if built.exists() else 0.0
        service_stale = code > started_at + 5
        ui_stale = bool(ui_built) and ui_src > ui_built + 5
        return {"update_ready": service_stale or ui_stale,
                "service_stale": service_stale, "ui_stale": ui_stale}

    @router.get("/fs/list")
    def fs_list(path: str | None = None, files: bool = False) -> dict:
        """Folder browser for the "Browse…" buttons (names only, read-only)."""
        from eeze_agent.core.fsbrowse import list_dir

        try:
            return list_dir(path, include_files=files)
        except (FileNotFoundError, PermissionError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/spend/today", response_model=schemas.SpendToday)
    def spend_today() -> schemas.SpendToday:
        """Today's estimated spend per agent against its daily cap (paid model calls only)."""
        registry = load_registry(root, home)
        by_agent = _spend.today_by_agent()
        rows = []
        for agent_id in sorted(set(registry.ids()) | set(by_agent)):
            used = by_agent.get(agent_id, {"usd": 0.0, "tokens": 0, "calls": 0})
            try:
                cap = _spend.budget_for(registry.get(agent_id))
            except KeyError:
                cap = _spend.budget_for(None)
            rows.append(schemas.SpendAgent(
                agent_id=agent_id, spent_usd=used["usd"], tokens=used["tokens"],
                calls=used["calls"], budget_usd=cap,
                remaining_usd=None if cap is None else round(max(0.0, cap - used["usd"]), 6),
            ))
        return schemas.SpendToday(day=_spend._today(),
                                  total_usd=round(sum(r.spent_usd for r in rows), 6), agents=rows)

    @router.get("/health")
    def health() -> dict:
        """Non-sensitive loopback readiness check; never returns operator data.

        When this process owns the scheduler, also says whether its thread is alive and
        when it last ticked — "the API answers" is not the same as "routines will fire".
        """
        out: dict = {"service": "eeze", "status": "ok"}
        sched = getattr(app.state, "scheduler", None)
        if sched is not None:
            out["scheduler"] = {"alive": sched.alive(), "last_tick_at": sched.last_tick_at}
            if not sched.alive():
                out["status"] = "degraded"
        return out

    @router.get("/session/token", status_code=410)
    def session_token() -> dict:
        """The browser must pair with a secret it obtained outside HTTP."""
        return {"error": "token disclosure removed; use local operator pairing"}

    @router.post("/session/pair")
    def pair_operator(request: Request, response: Response, body: dict) -> dict:
        if not _peer_allowed(request) or not _origin_allowed(request):
            raise HTTPException(status_code=403, detail="local operator only")
        supplied = body.get("token")
        code = body.get("code")
        if isinstance(code, str) and code:
            # One-time code from `eeze open` (the desktop shortcut): no token shown to anyone.
            from eeze_agent.core.pairing import consume_code

            if not consume_code(home, code):
                raise HTTPException(status_code=401, detail="pairing link expired — open Eeze again")
            supplied = _local_token()
        elif not isinstance(supplied, str) or not secrets.compare_digest(supplied, _local_token()):
            raise HTTPException(status_code=401, detail="invalid local operator token")
        issued = str(int(time.time()))
        nonce = secrets.token_urlsafe(16)
        message = f"{issued}.{nonce}"
        signature = hmac.new(supplied.encode(), message.encode(),
                             hashlib.sha256).hexdigest()
        response.set_cookie("eeze_operator", f"{message}.{signature}", httponly=True,
                            secure=request.url.scheme == "https", samesite="strict",
                            max_age=session_s, path="/")
        response.headers["Cache-Control"] = "no-store"
        return {"ok": True}

    @router.post("/approvals/{approval_id}/decide")
    def decide_approval(
        approval_id: str,
        body: schemas.ApprovalDecision,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        row = store.get(approval_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown approval: {approval_id}")
        if row["status"] != "pending":
            raise HTTPException(status_code=409, detail=f"approval already {row['status']}")
        if body.decision == "abandon":
            # Never runs anything, so it is safe on legacy/non-resumable rows — the way out
            # for approvals that used to freeze their routine forever.
            updated = store.abandon(approval_id, decided_by="api", reason=body.reason)
            return {"ok": True, "approval": _approval_public(updated).model_dump(),
                    "grant_id": None, "resumed": False, "resume_log": None}
        if not _approval_resumable(row):
            raise HTTPException(status_code=409, detail="approval cannot resume; start a new run for a fresh approval")
        grant_id = None
        grant_refused = None
        if body.decision == "approve" and body.grant is not None and row.get("risk_class") == "destructive":
            # Steps that change or remove the owner's files are approved one batch at a time.
            grant_refused = "destructive steps are always approved one at a time"
        elif body.decision == "approve" and body.grant is not None:
            grant_id = store.grant(
                agent_id=row.get("agent_id") or "default",
                risk_class=row.get("risk_class") or "write_local",
                scope=body.grant.scope,
                task=row.get("task") if body.grant.scope == "task" else None,
                ttl_hours=body.grant.ttl_hours,
            )
        updated = store.decide(approval_id, body.decision, decided_by="api", reason=body.reason)
        if grant_id:
            store.link_grant(approval_id, grant_id)
        resumed = False
        resume_log = None
        if body.decision == "approve" and body.auto_resume and store.run_state_for(approval_id):
            try:
                resume_log = _spawn_resume(approval_id)
                resumed = True
            except OSError as exc:
                resume_log = f"resume spawn failed: {exc}"
        return {
            "ok": True,
            "approval": _approval_public(updated).model_dump(),
            "grant_id": grant_id,
            **({"grant_refused": grant_refused} if grant_refused else {}),
            "resumed": resumed,
            "resume_log": resume_log,
        }

    @router.get("/grants", response_model=schemas.Page[schemas.Grant])
    def list_grants(
        include_revoked: bool = False,
        limit: int = Query(100, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> schemas.Page[schemas.Grant]:
        rows = store.list_grants(include_revoked=include_revoked)
        page = rows[offset : offset + limit]
        items = [_grant_public(r) for r in page]
        return schemas.Page[schemas.Grant](items=items, total=len(rows), limit=limit, offset=offset)

    @router.delete("/grants/{grant_id}")
    def revoke_grant(
        grant_id: str,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        if not store.revoke_grant(grant_id):
            raise HTTPException(status_code=404, detail=f"unknown or already revoked grant: {grant_id}")
        return {"ok": True, "grant_id": grant_id, "status": "revoked"}

    # ---------------- routines + setup (F5) ----------------

    from eeze_agent.core.envfile import read_env, update_env
    from eeze_agent.core.routines import RoutineStore, compute_next_run, spawn_detached
    from eeze_agent.core.settings import SettingsStore

    routine_store = RoutineStore()
    settings_store = SettingsStore()

    def _routine_public(row: dict) -> schemas.Routine:
        return schemas.Routine(**row)

    @router.get("/routines", response_model=schemas.Page[schemas.Routine])
    def list_routines() -> schemas.Page[schemas.Routine]:
        rows = routine_store.list()
        items = [_routine_public(r) for r in rows]
        return schemas.Page[schemas.Routine](items=items, total=len(items), limit=len(items), offset=0)

    @router.post("/routines", response_model=schemas.Routine)
    def create_routine(
        body: schemas.RoutineCreate,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> schemas.Routine:
        _require_write(request, x_eeze_token)
        schedule = body.schedule.model_dump(exclude_none=True)
        try:
            compute_next_run(schedule)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        params = body.params.model_dump(exclude_defaults=True)
        row = routine_store.add(
            body.id,
            name=body.name or body.id,
            kind=body.kind,
            schedule=schedule,
            params=params,
            agent_id=body.agent_id,
            enabled=body.enabled,
        )
        return _routine_public(row)

    @router.post("/routines/{routine_id}/enable")
    def enable_routine(
        routine_id: str,
        body: schemas.RoutineEnable,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        if routine_store.get(routine_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown routine: {routine_id}")
        ok = routine_store.set_enabled(routine_id, body.enabled)
        return {"ok": ok, "id": routine_id, "enabled": body.enabled}

    @router.post("/routines/{routine_id}/run")
    def run_routine_now(
        routine_id: str,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        if routine_store.get(routine_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown routine: {routine_id}")
        from eeze_agent.core.routines import routine_log_path

        log = routine_log_path(home, routine_id)
        spawn_detached(["routines", "run", routine_id], cwd=root, log_path=log)
        return {"ok": True, "id": routine_id, "spawned": True, "log": str(log)}

    @router.delete("/routines/{routine_id}")
    def remove_routine(
        routine_id: str,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        ok = routine_store.remove(routine_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"unknown routine: {routine_id}")
        return {"ok": True, "id": routine_id, "removed": True}

    @router.get("/routines/{routine_id}/runs", response_model=schemas.Page[schemas.RoutineRun])
    def routine_runs(
        routine_id: str,
        limit: int = Query(50, ge=1, le=200),
    ) -> schemas.Page[schemas.RoutineRun]:
        if routine_store.get(routine_id) is None:
            raise HTTPException(status_code=404, detail=f"unknown routine: {routine_id}")
        rows = routine_store.runs(routine_id, limit=limit)
        items = [schemas.RoutineRun(**r) for r in rows]
        return schemas.Page[schemas.RoutineRun](items=items, total=len(items), limit=limit, offset=0)

    def _env_path() -> Path:
        return root / ".env"

    # ------------- providers (P2): BYO keys, stored locally, never echoed -------------

    def _provider_rows() -> list[dict]:
        from eeze_agent.core.providers import provider_status

        return provider_status(home=home)

    def _provider_or_404(provider_id: str):
        from eeze_agent.core.providers import get_provider

        try:
            return get_provider(provider_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def _row_for(provider_id: str) -> schemas.ProviderRow:
        row = next((r for r in _provider_rows() if r["id"] == provider_id), None)
        if row is None:  # pragma: no cover - the catalog is static
            raise HTTPException(status_code=404, detail=f"unknown provider: {provider_id}")
        return schemas.ProviderRow(**row)

    @router.get("/providers", response_model=list[schemas.ProviderRow])
    def list_providers() -> list[schemas.ProviderRow]:
        """Provider inventory + status. Presence and `last4` only — never the key value."""
        return [schemas.ProviderRow(**r) for r in _provider_rows()]

    @router.post("/providers/{provider_id}/key")
    def set_provider_key(
        provider_id: str,
        body: schemas.ProviderKeySet,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        """Store the user's key for a provider (write-only: no endpoint reads it back)."""
        _require_write(request, x_eeze_token)
        from eeze_agent.core.secrets_local import SecretStore

        provider = _provider_or_404(provider_id)
        if provider.kind == "oauth_external":
            raise HTTPException(
                status_code=409,
                detail="the Codex subscription uses the local CLI session — it needs no API key",
            )
        if provider.kind == "local":
            raise HTTPException(
                status_code=409, detail=f"{provider.label} needs no API key (local server)"
            )
        if not provider.compatible:
            raise HTTPException(status_code=409, detail=f"refused: {provider.note}")
        from eeze_agent.core.providers import url_host

        store = SecretStore(home)
        try:
            store.set(f"provider.{provider.id}", body.key)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        # Bind the key to the endpoint it was entered for (see providers.stored_key_allowed).
        endpoint = (store.get(f"provider.{provider.id}.base_url") or provider.base_url or "")
        if url_host(endpoint):
            store.set(f"provider.{provider.id}.key_host", url_host(endpoint))
        return {
            "ok": True,
            "id": provider.id,
            "key_last4": store.last4(f"provider.{provider.id}"),
            "configured": True,
        }

    @router.delete("/providers/{provider_id}/key")
    def delete_provider_key(
        provider_id: str,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        from eeze_agent.core.secrets_local import SecretStore

        provider = _provider_or_404(provider_id)
        removed = SecretStore(home).delete(f"provider.{provider.id}")
        return {"ok": True, "id": provider.id, "removed": removed}

    @router.put("/providers/{provider_id}", response_model=schemas.ProviderRow)
    def update_provider(
        provider_id: str,
        body: schemas.ProviderOverride,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> schemas.ProviderRow:
        """Endpoint/model overrides + default flag. Values are validated, never invented."""
        _require_write(request, x_eeze_token)
        from eeze_agent.core.secrets_local import SecretStore

        provider = _provider_or_404(provider_id)
        store = SecretStore(home)
        if body.base_url is not None:
            from eeze_agent.core.providers import is_loopback_host, url_host

            url = body.base_url.strip().rstrip("/")
            if url and not url.lower().startswith(("http://", "https://")):
                raise HTTPException(status_code=422, detail="base_url must start with http(s)://")
            if url and not url_host(url):
                raise HTTPException(status_code=422, detail="base_url has no host")
            if url.lower().startswith("http://") and not is_loopback_host(url_host(url)):
                # Keys travel in headers: plain http is only acceptable to this machine.
                raise HTTPException(status_code=422,
                                    detail="plain http:// is only allowed for localhost; use https://")
            if url:
                store.set(f"provider.{provider.id}.base_url", url)
            else:
                store.delete(f"provider.{provider.id}.base_url")
        if body.default_models is not None:
            models = {k: v.strip() for k, v in body.default_models.items() if v and v.strip()}
            from eeze_agent.core.providers import valid_model_id

            bad = sorted(v for v in models.values() if not valid_model_id(v))
            if bad:
                raise HTTPException(status_code=422, detail="invalid model id (letters, digits, . _ : / - only)")
            if models:
                store.set(f"provider.{provider.id}.models", json.dumps(models, sort_keys=True))
            else:
                store.delete(f"provider.{provider.id}.models")
        if body.set_default:
            store.set("provider.default", provider.id)
        return _row_for(provider.id)

    @router.post("/providers/{provider_id}/test", response_model=schemas.ProbeResult)
    def test_provider(
        provider_id: str,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> schemas.ProbeResult:
        """LIVE connection test — it may spend a paid call, hence the write gate."""
        _require_write(request, x_eeze_token)
        from eeze_agent.core.providers import probe_provider, resolve_provider

        provider = _provider_or_404(provider_id)
        config = resolve_provider("brain", provider_id=provider.id, home=home)
        return schemas.ProbeResult(**probe_provider(provider.id, config))

    # ------------- missions (F7): a goal, an editable plan, a gated run -------------

    def _approval_status(approval_id: str) -> str | None:
        row = store.get(approval_id)
        return row.get("status") if row else None

    def _mission_store():
        from eeze_agent.core.missions import MissionStore

        return MissionStore(home)

    @router.get("/missions", response_model=schemas.Page[schemas.Mission])
    def list_missions() -> schemas.Page[schemas.Mission]:
        rows = _mission_store().list(approval_status=_approval_status)
        items = [schemas.Mission(**row) for row in rows]
        return schemas.Page[schemas.Mission](items=items, total=len(items), limit=max(len(items), 1), offset=0)

    @router.get("/recipes")
    def list_recipes() -> dict:
        """Ready-made mission starters (pre-fill the form; nothing runs)."""
        from eeze_agent.core.mission_ux import recipes

        return {"items": recipes()}

    @router.post("/missions/describe")
    def describe_mission_plan(body: schemas.MissionValidateRequest, lang: str = "en") -> dict:
        """The plan in plain language, en or pt (best effort; never runs or validates anything)."""
        from eeze_agent.core.mission_ux import describe_plan

        return {"lines": describe_plan(str(body.kind or ""), body.plan or "", lang=lang)}

    def _mission_or_404(mission_id: str) -> dict:
        from eeze_agent.core.missions import MissionError

        try:
            row = _mission_store().get(mission_id)
        except MissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown mission: {mission_id}")
        return row

    @router.get("/missions/{mission_id}/outputs")
    def mission_outputs(mission_id: str) -> dict:
        """Result files of the last run (images/videos/models) + the source media, for previews."""
        from eeze_agent.core.mission_ux import output_files, source_files
        from eeze_agent.core.missions import effective_last_run

        row = _mission_or_404(mission_id)
        last = effective_last_run(row.get("last_run"), approval_status=_approval_status) or {}
        report = None
        out_dir = last.get("out_dir")
        if row.get("kind") == "files" and out_dir and Path(out_dir).is_dir():
            from eeze_agent.verticals.files.runner import REPORT_NAME

            found = sorted(Path(out_dir).rglob(REPORT_NAME))
            if found:
                try:
                    data = json.loads(found[-1].read_text(encoding="utf-8"))
                    report = {k: data.get(k) for k in ("op", "folder", "files", "applied", "undone",
                                                       "duplicates", "conflicts", "error")}
                    report["changes"] = (data.get("changes") or [])[:300]
                except (OSError, ValueError):
                    report = None
        return {
            "status": last.get("status"),
            "runset_id": last.get("runset_id"),
            "report": report,
            "files": output_files(root, last.get("out_dir")),
            "sources": [
                {**f, "url": f"/api/missions/{mission_id}/source-file?name={quote(f['name'])}"}
                for f in source_files(str(row.get("sources") or ""))
            ],
        }

    @router.post("/files/preview")
    def files_preview(body: schemas.MissionValidateRequest) -> dict:
        """What a files plan WOULD change — reads names only, touches nothing."""
        import tempfile

        from eeze_agent.verticals.files import load_spec, plan_changes

        with tempfile.TemporaryDirectory(prefix="eeze-files-") as tmp:
            path = Path(tmp) / "spec.yaml"
            path.write_text(body.plan or "", encoding="utf-8")
            try:
                plan = plan_changes(load_spec(path))
            except Exception as exc:  # noqa: BLE001 — a preview explains, it never fails loudly
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        plan["ok"] = True
        plan["total_changes"] = len(plan["changes"])
        plan["changes"] = plan["changes"][:300]
        return plan

    @router.post("/missions/{mission_id}/undo")
    def undo_mission(
        mission_id: str,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        """Put every file of the last files run back where it was (refuses if anything moved)."""
        _require_write(request, x_eeze_token)
        from eeze_agent.verticals.files.runner import REPORT_NAME, FilesError, undo

        _mission_or_404(mission_id)
        # The newest batch of THIS mission that changed files and was not undone yet — a later
        # run that changed nothing (or was refused) must not hide an earlier undo.
        runs_dir = root / "artifacts" / "runs"
        candidates = sorted(runs_dir.glob(f"*-mission-{mission_id}/**/{REPORT_NAME}"),
                            key=lambda p: p.stat().st_mtime, reverse=True) if runs_dir.is_dir() else []
        target = None
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not data.get("undone") and data.get("undo") and data.get("status") in {
                    "applied", "partial", "applying", None}:
                target = path
                break
        if target is None:
            raise HTTPException(status_code=404, detail="nothing to undo for this mission")
        try:
            return {"ok": True, **undo(target)}
        except FilesError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/missions/{mission_id}/source-file")
    def mission_source_file(mission_id: str, name: str) -> FileResponse:
        """One source image/video of the mission (the "before"), read-only."""
        from eeze_agent.core.mission_ux import resolve_source_file

        row = _mission_or_404(mission_id)
        path = resolve_source_file(str(row.get("sources") or ""), name)
        if path is None:
            raise HTTPException(status_code=404, detail="no such source file")
        return FileResponse(path)

    @router.get("/missions/{mission_id}", response_model=schemas.Mission)
    def get_mission(mission_id: str) -> schemas.Mission:
        from eeze_agent.core.missions import MissionError, to_public

        store = _mission_store()
        try:
            row = store.get(mission_id)
        except MissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown mission: {mission_id}")
        return schemas.Mission(**to_public(row, plan=True, approval_status=_approval_status))

    @router.post("/missions/draft")
    def draft_mission(
        body: schemas.MissionDraftRequest,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        """Write a plan from a plain-language goal. A real model call (the local subscription is $0);
        a refusal comes back with the writer's attempts instead of a silent fallback."""
        _require_write(request, x_eeze_token)
        from eeze_agent.core.missions import MissionDraftError, MissionError, draft

        registry = load_registry(root, home)
        try:
            budget_agent = registry.get(body.agent_id or "default")
        except KeyError:
            budget_agent = registry.default()
        try:
            return draft(
                kind=body.kind,
                goal=body.goal,
                name_hint=(body.name or "").strip() or "mission",
                sources=body.sources or "",
                home=home,
                budget_agent=budget_agent,
            )
        except MissionDraftError as exc:
            raise HTTPException(
                status_code=422,
                detail={"message": str(exc), "attempts": exc.attempts, "model": exc.model, "draft_dir": exc.draft_dir},
            ) from exc
        except MissionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/missions", response_model=schemas.Mission)
    def save_mission(
        body: schemas.MissionSave,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> schemas.Mission:
        """Create or update. Saving a plan is what turns a mission into something that can run."""
        _require_write(request, x_eeze_token)
        from eeze_agent.core.missions import MissionError, sync_schedule, to_public

        store = _mission_store()
        payload = body.model_dump()
        payload["schedule"] = body.schedule.model_dump()
        try:
            saved = store.save(payload)
        except MissionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        stored = store.get(saved["id"]) or {}
        note = ""
        if str(stored.get("plan") or "").strip():
            try:
                sync = sync_schedule(stored, home=home)
            except Exception as exc:  # noqa: BLE001 — the mission is saved; the schedule reports why not
                sync = {"error": f"{type(exc).__name__}: {exc}"}
            if sync.get("error"):
                note = f"saved — the schedule was NOT attached: {sync['error']}"
            elif sync.get("routine_id"):
                note = f"saved — scheduled as routine {sync['routine_id']}"
            elif sync.get("removed"):
                note = "saved — on demand (the previous schedule was removed)"
            else:
                note = "saved — on demand (no schedule attached)"
        elif (stored.get("schedule") or {}).get("type") != "on_demand":
            note = "saved — a scheduled mission needs a plan first; the schedule starts once you save one"
        row = to_public(stored, plan=True)
        row["note"] = note
        return schemas.Mission(**row)

    @router.delete("/missions/{mission_id}")
    def remove_mission(
        mission_id: str,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        from eeze_agent.core.missions import MissionError

        store = _mission_store()
        try:
            if store.get(mission_id) is None:
                raise HTTPException(status_code=404, detail=f"unknown mission: {mission_id}")
        except MissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        routine_removed = False
        try:
            from eeze_agent.core.routines import RoutineStore

            routine_removed = bool(RoutineStore().remove(f"mission:{mission_id}"))
        except Exception:  # noqa: BLE001 — a dangling routine is worse than a reported failure
            routine_removed = False
        ok = store.remove(mission_id)
        return {"ok": ok, "id": mission_id, "removed": ok, "routine_removed": routine_removed}

    @router.post("/missions/validate")
    def validate_draft(body: schemas.MissionValidateRequest) -> dict:
        """Stateless check of an UNSAVED draft (the screen validates before the first save)."""
        from eeze_agent.core.missions import validate_plan

        if body.kind is None:
            raise HTTPException(status_code=422, detail="kind is required to validate a draft")
        return validate_plan(kind=body.kind, plan_text=body.plan, sources=body.sources or "")

    @router.post("/missions/{mission_id}/validate")
    def validate_mission(mission_id: str, body: schemas.MissionValidateRequest) -> dict:
        """Stateless check of the CURRENT text (unsaved edits included) with the runner's own loaders."""
        from eeze_agent.core.missions import MissionError, validate_plan

        store = _mission_store()
        try:
            row = store.get(mission_id)
        except MissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown mission: {mission_id}")
        plan = body.plan if str(body.plan or "").strip() else str(row.get("plan") or "")
        sources = body.sources if body.sources is not None else str(row.get("sources") or "")
        return validate_plan(kind=str(row.get("kind") or "task"), plan_text=plan, sources=sources)

    @router.post("/missions/{mission_id}/run")
    def run_mission_now(
        mission_id: str,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        """Start the mission now (detached, same pattern as a routine). No plan -> 409, not a shrug."""
        _require_write(request, x_eeze_token)
        from eeze_agent.core.missions import MissionError

        store = _mission_store()
        try:
            row = store.get(mission_id)
        except MissionError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if row is None:
            raise HTTPException(status_code=404, detail=f"unknown mission: {mission_id}")
        if not str(row.get("plan") or "").strip():
            raise HTTPException(
                status_code=409,
                detail="this mission has no plan yet — generate a draft, edit it if you want, and save it",
            )
        log_dir = home / "missions"
        log_dir.mkdir(parents=True, exist_ok=True)
        log = log_dir / f"run-{mission_id}.log"
        spawn_detached(["mission", "run", mission_id], cwd=root, log_path=log)
        return {"ok": True, "id": mission_id, "spawned": True, "log": str(log)}

    @router.get("/system/info", response_model=schemas.SystemInfo)
    def system_info() -> schemas.SystemInfo:
        """Runtime facts for the Settings page (paths, key presence, counts). No secrets."""
        import platform

        env = read_env(_env_path())
        key_specs = [
            ("typesafe", ("TYPESAFE_API_KEY",)),
            ("brain", ("EEZE_BRAIN_API_KEY", "EEZE_PLANNER_API_KEY")),
            ("planner", ("EEZE_PLANNER_API_KEY",)),
            ("extract", ("EEZE_EXTRACT_API_KEY",)),
            ("imap", ("EEZE_IMAP_APP_PASSWORD",)),
        ]
        keys = {
            name: any(bool((env.get(var) or os.environ.get(var) or "").strip()) for var in vars_)
            for name, vars_ in key_specs
        }
        runs_dir = root / "artifacts" / "runs"
        runsets = len([d for d in runs_dir.glob("*") if d.is_dir()]) if runs_dir.exists() else 0
        backups_dir = Path(root) / "backups"
        backups = len(list(backups_dir.glob("*.zip"))) if backups_dir.exists() else 0
        try:
            from importlib.metadata import version as _pkg_version

            version = _pkg_version("eeze-agent")
        except Exception:  # noqa: BLE001 — metadata missing in odd environments
            version = "0.0.1"
        return schemas.SystemInfo(
            version=version,
            python=platform.python_version(),
            api_pid=os.getpid(),
            daemon=_daemon_status(),
            store_path=str(store.path),
            token_path=str(home / "api.token"),
            user_agents_path=str(home / "agents.yaml"),
            repo_agents_path=str(Path(root) / "agents.yaml"),
            artifacts_path=str(Path(root) / "artifacts"),
            keys=keys,
            runsets=runsets,
            backups=backups,
        )

    def _creative_tools() -> dict[str, str | None]:
        """Where ffmpeg, Blender and the Codex CLI are (None = not found). Never raises."""
        import shutil as _shutil

        found: dict[str, str | None] = {}
        try:
            from eeze_agent.verticals.video.probe import find_tools

            found["ffmpeg"] = str(find_tools()[0])
        except Exception:  # noqa: BLE001
            found["ffmpeg"] = None
        try:
            from eeze_agent.verticals.render3d.blender import find_blender

            found["blender"] = str(find_blender())
        except Exception:  # noqa: BLE001
            found["blender"] = None
        codex = os.environ.get("EEZE_CODEX_BIN") or _shutil.which("codex")
        found["codex"] = str(codex) if codex else None
        return found

    @router.get("/setup/state", response_model=schemas.SetupState)
    def setup_state() -> schemas.SetupState:
        env = read_env(_env_path())
        user = env.get("EEZE_IMAP_USER") or None
        return schemas.SetupState(
            needs_setup=not settings_store.get_bool("setup_done"),
            imap_configured=bool(user and env.get("EEZE_IMAP_APP_PASSWORD")),
            imap_user=user,
            imap_host=env.get("EEZE_IMAP_HOST"),
            routines_count=len(routine_store.list()),
            daemon_running=_daemon_status().running,
            tools=_creative_tools(),
        )

    @router.post("/setup/imap")
    def setup_imap(
        body: schemas.SetupImap,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        import re as _re

        host = body.host.strip() or "imap.gmail.com"
        user = body.user.strip()
        if not _re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host):
            raise HTTPException(status_code=422, detail="IMAP host must be a plain host name")
        if not _re.fullmatch(r"[^@\s]{1,64}@[A-Za-z0-9.-]{1,253}", user):
            raise HTTPException(status_code=422, detail="IMAP user must be an e-mail address")
        try:
            update_env(
                _env_path(),
                {
                    "EEZE_IMAP_HOST": host,
                    "EEZE_IMAP_USER": user,
                    "EEZE_IMAP_APP_PASSWORD": body.app_password,
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"ok": True, "saved": ["EEZE_IMAP_HOST", "EEZE_IMAP_USER", "EEZE_IMAP_APP_PASSWORD"]}

    @router.post("/setup/imap/test")
    def setup_imap_test(
        body: schemas.SetupImap,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        from eeze_agent.verticals.invoices.imap_source import ImapError, test_login

        try:
            info = test_login(body.host, body.user, body.app_password)
        except ImapError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, **info}

    @router.post("/setup/complete")
    def setup_complete(
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        settings_store.set("setup_done", "1")
        return {"ok": True}

    @router.post("/setup/notify")
    def setup_notify(
        body: schemas.NotifyToggle,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        """Toggle desktop notifications when a run pauses for approval."""
        _require_write(request, x_eeze_token)
        settings_store.set("notify_approvals", "1" if body.enabled else "0")
        return {"ok": True, "enabled": body.enabled}

    @router.post("/setup/notify-routines")
    def setup_routine_failure_notifications(
        body: schemas.NotifyToggle,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        """Opt in to separate routine failure alerts; defaults to off."""
        _require_write(request, x_eeze_token)
        failure_alerts = RoutineFailureWatcher(routine_store, settings_store)
        if body.enabled:
            failure_alerts.baseline()  # enabling never replays failures from the off period
        settings_store.set("notify_routine_failures", "1" if body.enabled else "0")
        if not body.enabled:
            failure_alerts.baseline()
        return {"ok": True, "enabled": body.enabled}

    # ---------------- agent management (v2): user-level agents ----------------

    def _user_agents_path() -> Path:
        return home / "agents.yaml"

    def _read_user_agents() -> list[dict]:
        path = _user_agents_path()
        if not path.exists():
            return []
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return [a for a in (data.get("agents") or []) if isinstance(a, dict)]

    def _write_user_agents(agents: list[dict]) -> None:
        import yaml

        home.mkdir(parents=True, exist_ok=True)
        _user_agents_path().write_text(
            yaml.safe_dump({"agents": agents}, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

    @router.post("/agents", response_model=schemas.Agent)
    def create_agent(
        body: schemas.AgentCreate,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> schemas.Agent:
        _require_write(request, x_eeze_token)
        from eeze_agent.brains.registry import VALID_BRAINS
        from eeze_agent.core.risk import RISK_ORDER

        brain = str(body.model.get("brain") or "jev")
        if brain not in VALID_BRAINS:
            raise HTTPException(status_code=422, detail=f"unknown brain {brain!r} — valid: {list(VALID_BRAINS)}")
        unknown = [c for c in body.permissions.risk_classes if c not in RISK_ORDER]
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown risk classes: {unknown}")
        entry = {
            "id": body.id,
            "name": body.name,
            "role": body.role,
            **({"description": body.description} if body.description else {}),
            "permissions": body.permissions.model_dump(),
            "tools": body.tools,
            "model": {**body.model, "brain": brain},
            **({"budget_usd_daily": body.budget_usd_daily}
               if body.budget_usd_daily is not None else {}),
        }
        agents = [a for a in _read_user_agents() if a.get("id") != body.id]
        agents.append(entry)
        _write_user_agents(agents)
        return _agent_public(body.id, _all_runs())

    @router.delete("/agents/{agent_id}")
    def delete_agent(
        agent_id: str,
        request: Request,
        x_eeze_token: str | None = Header(default=None, alias="X-EEZE-Token"),
    ) -> dict:
        _require_write(request, x_eeze_token)
        agents = _read_user_agents()
        kept = [a for a in agents if a.get("id") != agent_id]
        if len(kept) == len(agents):
            raise HTTPException(
                status_code=404,
                detail=f"{agent_id!r} is not a user-level agent (repo agents are not deletable here)",
            )
        _write_user_agents(kept)
        return {"ok": True, "id": agent_id, "removed": True}

    @router.get("/runs", response_model=schemas.Page[schemas.Run])
    def list_runs(
        agent_id: str | None = None,
        status: str | None = None,
        task_name: str | None = None,
        interference: bool | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> schemas.Page[schemas.Run]:
        runs = _all_runs()
        if agent_id:
            runs = [r for r in runs if r.agent_id == agent_id]
        if status:
            runs = [r for r in runs if r.status == status]
        if task_name:
            runs = [r for r in runs if r.task_name == task_name]
        if interference is not None:
            runs = [r for r in runs if r.interference == interference]
        runs.sort(key=lambda r: (r.started_at or "", r.id), reverse=True)
        page = runs[offset : offset + limit]
        return schemas.Page[schemas.Run](items=page, total=len(runs), limit=limit, offset=offset)

    @router.get("/runs/{run_id}", response_model=schemas.RunDetail)
    def get_run(run_id: str) -> schemas.RunDetail:
        runset_id, _, ix = run_id.rpartition(".")
        if not runset_id or not ix.isdigit():
            raise HTTPException(status_code=400, detail="run id must be '<runset_id>.<run_index>'")
        detail = _run_detail(runset_id, int(ix))
        if detail is None:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
        return detail

    @router.get("/system/status", response_model=schemas.SystemStatus)
    def system_status() -> schemas.SystemStatus:
        runs = _all_runs()
        calls = 0
        costs = 0.0
        p50s: list[float] = []
        interference = 0
        for d in _runsets(50):
            journal = _journal(d / "journal.jsonl")
            for e in journal:
                if e.get("kind") == "external_input_detected":
                    interference += 1
            sj = d / "summary.json"
            if sj.exists():
                try:
                    s = json.loads(sj.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                calls += int(s.get("jev_calls") or 0)
                costs += float(s.get("cost_estimate_usd") or 0)
                if s.get("jev_ms_p50"):
                    p50s.append(float(s["jev_ms_p50"]))
        p50s.sort()
        jstatus = schemas.JevStatus(
            calls=calls,
            latency_ms_p50=(p50s[len(p50s) // 2] if p50s else None),
            cost_usd=round(costs, 6),
        )
        agents = [
            _agent_public(aid, runs)
            for aid in load_registry(root, home).ids()
        ]
        return schemas.SystemStatus(
            daemon=_daemon_status(),
            jev=jstatus,
            agents=agents,
            runs_total=len(runs),
            interference_events=interference,
            pending_approvals=store.count(status="pending"),
            notifications_enabled=(settings_store.get("notify_approvals") or "1").strip() != "0",
            routine_failure_notifications_enabled=(
                (settings_store.get("notify_routine_failures") or "1").strip() != "0"),
        )

    # API lives under /api only (canonical — the UI and the Vite dev proxy call it).
    # The root belongs to the SPA: a root alias here would shadow client-side routes
    # (e.g. GET /approvals must reach the SPA, not the API).
    app.include_router(router, prefix="/api")

    artifacts = root / "artifacts"
    # Created up front: it is gitignored, and mounting only when it already existed meant a
    # fresh install served the SPA page instead of the first mission's results.
    artifacts.mkdir(parents=True, exist_ok=True)
    if artifacts.exists():
        app.mount("/artifacts", StaticFiles(directory=str(artifacts)), name="artifacts")

    # Self-hosted UI: serve the built SPA (ui/dist/client) with a SPA fallback.
    dist = root / "ui" / "dist"
    client = dist / "client" if (dist / "client").exists() else dist
    entry = client / "index.html"
    if not entry.exists() and (client / "_shell.html").exists():
        entry = client / "_shell.html"
    if serve_ui is None:
        serve_ui = entry.exists()
    if serve_ui and entry.exists():
        assets = client / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="ui-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def _spa(full_path: str) -> FileResponse:
            candidate = (client / full_path).resolve()
            if full_path and candidate.is_file() and candidate.is_relative_to(client.resolve()):
                return FileResponse(candidate)
            return FileResponse(entry)

    # CORS must wrap the operator boundary so unauthenticated local dev calls receive 401,
    # not an opaque browser network failure. No public/tunnel origin is trusted here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=local_dev_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-EEZE-Token"],
        allow_credentials=True,
    )
    # The browser cannot fetch its bootstrap secret over HTTP. Make the local
    # token file available on first launch so the operator can read it out of band.
    _local_token()
    return app
