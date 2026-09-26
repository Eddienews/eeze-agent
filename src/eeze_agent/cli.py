"""Eeze CLI — `eeze doctor`, `eeze run`."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

try:  # optional at import time; required at run time for .env loading
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except ImportError:  # pragma: no cover
    pass

from eeze_agent import __version__


def _check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'OK ' if ok else 'MISS'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def doctor() -> int:
    ok = True
    ok &= _check("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0])
    key = os.environ.get("TYPESAFE_API_KEY")
    ok &= _check("TYPESAFE_API_KEY", bool(key), "set" if key else "missing (fill .env)")
    driver = shutil.which("cua-driver")
    ok &= _check("cua-driver on PATH", bool(driver), driver or "install: https://cua.ai/docs")
    try:
        import yaml  # noqa: F401

        ok &= _check("pyyaml importable", True)
    except ImportError:
        ok &= _check("pyyaml importable", False, "run: uv sync")
    return 0 if ok else 1


def cmd_run(args: argparse.Namespace) -> int:
    from eeze_agent.agents.models import AgentContext
    from eeze_agent.agents.registry import load_registry
    from eeze_agent.brains.registry import make_brain
    from eeze_agent.core.approvals import ApprovalStore
    from eeze_agent.core.journal import RunJournal
    from eeze_agent.core.loop import run_set
    from eeze_agent.core.risk import DEFAULT_ALLOWED, RISK_ORDER, Policy
    from eeze_agent.core.tasks import load_task
    from eeze_agent.drivers.cua import CuaDriver

    repo_root = Path(__file__).resolve().parents[2]
    registry = load_registry(repo_root)
    agent = registry.get(args.agent)
    ctx = AgentContext(agent=agent)

    extra = [x.strip() for x in (args.allow or "").split(",") if x.strip()]
    unknown = [x for x in extra if x not in RISK_ORDER]
    if unknown:
        print(f"unknown risk classes in --allow: {unknown} (known: {', '.join(RISK_ORDER)})",
              file=sys.stderr)
        return 2
    allowed = set(agent.permissions.get("risk_classes") or DEFAULT_ALLOWED) | set(extra)
    policy = Policy(frozenset(allowed))

    store = ApprovalStore()
    runs_root = Path(args.out) if args.out else repo_root / "artifacts" / "runs"
    resume_state: dict | None = None
    demo, isolated, runs = args.demo, args.isolated, args.runs

    if args.resume:
        approval = store.get(args.resume)
        state_row = store.run_state_for(args.resume)
        if approval is None or state_row is None:
            print(f"no paused run for approval {args.resume!r}", file=sys.stderr)
            return 2
        if approval.get("status") != "approved":
            print(
                f"approval {args.resume!r} is {approval.get('status')!r} — "
                "approve it first (eeze approvals / the API), then resume",
                file=sys.stderr,
            )
            return 2
        resume_state = json.loads(state_row["payload"])
        task_path = Path(resume_state.get("task_path") or "")
        if not resume_state.get("task_path") or not task_path.exists():
            print("paused run has no task file (task_path missing)", file=sys.stderr)
            return 2
        runset_id = str(resume_state.get("runset_id") or "")
        if not runset_id:
            print("paused run state is incomplete (runset_id missing)", file=sys.stderr)
            return 2
        runs_root = Path(resume_state.get("runs_root") or runs_root)
        out_dir = Path(resume_state.get("out_dir") or (runs_root / runset_id))
        demo = bool(resume_state.get("demo", demo))
        isolated = bool(resume_state.get("isolated", isolated))
        runs = int(resume_state.get("runs") or runs)
        agent = registry.get(str(resume_state.get("agent_id") or args.agent))
        ctx = AgentContext(agent=agent)
        task = load_task(task_path)
    else:
        if not args.task:
            print("usage: eeze run <task.yaml> [--runs N] [--allow a,b]  |  eeze run --resume <approval_id>",
                  file=sys.stderr)
            return 2
        task_path = Path(args.task)
        task = load_task(task_path)
        runset_id = time.strftime("%Y%m%d-%H%M%S") + f"-{task.name}"
        out_dir = runs_root / runset_id

    out_dir.mkdir(parents=True, exist_ok=True)
    journal = RunJournal(runs_root, runset_id, agent_id=ctx.agent_id)
    ctx.runset_id = runset_id

    print(
        f"eeze {__version__} · task={task.name} · agent={agent.id} · runs={runs}"
        + (f" · resume={args.resume}" if args.resume else "")
    )
    try:
        summary = run_set(
            task=task,
            agent_ctx=ctx,
            driver=CuaDriver(),
            brain=make_brain(agent_id=agent.id, repo_root=repo_root, task=task),
            brain_factory=lambda **kw: make_brain(agent_id=agent.id, repo_root=repo_root, task=task, **kw),
            journal=journal,
            runs=runs,
            out_dir=out_dir,
            demo=demo,
            isolated=isolated,
            policy=policy,
            approvals=store,
            task_path=task_path,
            resume_state=resume_state,
        )
    except ValueError as exc:
        if not resume_state or "approval identity mismatch" not in str(exc):
            _close_failed_resume(store, args.resume, resume_state, exc)
            raise
        print("Approval no longer matches this task/context; no action run. "
              "Start a new run to request fresh approval.", file=sys.stderr)
        _close_failed_resume(store, args.resume, resume_state, exc)
        return 2
    except BaseException as exc:
        _close_failed_resume(store, args.resume, resume_state, exc)
        raise
    finally:
        journal.close()
    if args.resume:
        state_row = store.run_state_for(args.resume)
        if state_row is not None and state_row["status"] == "resumed":
            store.set_run_state_status(state_row["id"], "completed")
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("\n== summary ==")
    print(json.dumps(summary, indent=2))
    print(f"\nartifacts: {out_dir}")
    if summary.get("status") == "needs_approval":
        approval_id = summary.get("approval_id")
        print(
            f"\nPAUSED for approval. Approve via the API (POST /approvals/{approval_id}/decide) "
            f"or review in the UI, then: eeze run --resume {approval_id}"
        )
        return 3
    ok_runs, eligible = (int(x) for x in summary["success_rate"].split("/"))
    return 0 if eligible and ok_runs == eligible else 1


def _close_failed_resume(store, approval_id: str | None, resume_state: dict | None,
                         exc: BaseException) -> None:
    """A resume that crashes must still reach a final state.

    Otherwise the run-state stays ``resumed`` and the routine run stays ``needs_approval``
    forever — which kept its routine from ever being scheduled again.
    """
    if not approval_id:
        return
    try:
        state_row = store.run_state_for(approval_id)
        if state_row is not None and state_row["status"] in {"resumed", "waiting"}:
            store.set_run_state_status(state_row["id"], "failed")
        routine_run_id = str((resume_state or {}).get("routine_run_id") or "")
        if routine_run_id:
            from eeze_agent.core.routines import RoutineStore

            RoutineStore(store.path).end_run(
                routine_run_id, str((resume_state or {}).get("routine_id") or ""),
                status="error", detail={"resumed": True, "error": f"{type(exc).__name__}: {exc}"[:300]},
                approval_id=approval_id,
            )
    except Exception:  # noqa: BLE001, S110 — bookkeeping must not mask the original error
        pass


def cmd_api(args: argparse.Namespace) -> int:
    from eeze_agent.api import daemon

    action = getattr(args, "action", "serve") or "serve"
    if action == "start":
        print(json.dumps(
            daemon.start(host=args.host or "127.0.0.1", port=args.port, serve_ui=args.serve_ui),
            indent=2,
        ))
        return 0
    if action == "stop":
        print(json.dumps(daemon.stop(port=args.port), indent=2))
        return 0
    if action == "status":
        print(json.dumps(daemon.status(port=args.port), indent=2))
        return 0

    import uvicorn

    from eeze_agent.api.app import create_app

    host = args.host or "127.0.0.1"
    print(f"Eeze API -> http://{host}:{args.port}  (openapi at /docs)")
    uvicorn.run(create_app(serve_ui=args.serve_ui, scheduler=True), host=host, port=args.port, log_level="warning")
    return 0


def cmd_unpair(args: argparse.Namespace) -> int:
    """Sign every browser out: replace ~/.eeze/api.token (old pairings stop working at once)."""
    import secrets

    from eeze_agent.api import daemon

    home = daemon.HOME
    home.mkdir(parents=True, exist_ok=True)
    token_file = home / "api.token"
    tmp = token_file.with_name("api.token.tmp")
    tmp.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    if os.name != "nt":
        os.chmod(tmp, 0o600)
    os.replace(tmp, token_file)
    (home / "pair-codes.json").unlink(missing_ok=True)
    print("All browsers are signed out. Open Eeze from the 'Eeze Agent' shortcut "
          "(or run `eeze open`) to sign in again.")
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    """Open the dashboard already paired (starts the service if needed). Desktop shortcut."""
    import webbrowser

    from eeze_agent.api import daemon
    from eeze_agent.core.pairing import create_code

    if not daemon.http_up(args.port):
        daemon.start(port=args.port)
    code = create_code(daemon.HOME)
    page = args.page if str(args.page or "").startswith("/") else "/missions"
    url = f"http://127.0.0.1:{args.port}/pair?next={page}#code={code}"
    if args.print_only:
        print(url)
        return 0
    webbrowser.open(url)
    return 0


def cmd_tunnel(args: argparse.Namespace) -> int:
    from eeze_agent.api import tunnel

    action = getattr(args, "action", "url") or "url"
    if action == "start":
        result = tunnel.start(port=args.port)
    elif action == "stop":
        result = tunnel.stop()
    else:
        result = tunnel.url()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("status") not in {"cloudflared_not_found", "exited", "no_url_yet"} else 1


def cmd_ui(args: argparse.Namespace) -> int:
    import subprocess

    ui_dir = Path(__file__).resolve().parents[2] / "ui"
    if not ui_dir.exists():
        print(f"ui/ not found at {ui_dir}", file=sys.stderr)
        return 1
    commands = {
        "install": ["npm", "install", "--no-audit", "--no-fund"],
        "dev": ["npm", "run", "dev"],
        "build": ["npm", "run", "build"],
    }
    cmd = commands[args.action]
    print(f"$ {' '.join(cmd)}   (cwd={ui_dir})")
    rc = subprocess.call(cmd, cwd=str(ui_dir), shell=(sys.platform == "win32"))
    if rc == 0 and args.action == "build":
        shell_html = ui_dir / "dist" / "client" / "_shell.html"
        index_html = ui_dir / "dist" / "client" / "index.html"
        if shell_html.exists() and not index_html.exists():
            shutil.copyfile(shell_html, index_html)
            print(f"normalized: {index_html.name} (from {shell_html.name})")
        fixer = ui_dir.parent / "scripts" / "fix_shell_refs.py"
        if fixer.exists():
            subprocess.call([sys.executable, str(fixer), str(ui_dir / "dist" / "client")])
    return rc


def cmd_invoices(args: argparse.Namespace) -> int:
    from eeze_agent.verticals.invoices import run_vertical

    repo_root = Path(__file__).resolve().parents[2]
    out_dir = Path(args.out) if args.out else repo_root / "artifacts" / "e1-invoices" / "out"
    summary = run_vertical(
        Path(args.input),
        out_dir,
        limit=getattr(args, "limit", None),
        model=getattr(args, "model", None),
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["files"] else 1


def cmd_video(args: argparse.Namespace) -> int:
    from eeze_agent.verticals.video import run_vertical

    spec = Path(args.spec)
    if not spec.exists():
        print(f"spec not found: {spec}", file=sys.stderr)
        return 2
    try:
        summary = run_vertical(
            spec,
            out_dir=Path(args.out) if args.out else None,
            ffmpeg_dir=args.ffmpeg_dir,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if (summary["failed"] == 0 and summary["output"]) else 1


def cmd_photo(args: argparse.Namespace) -> int:
    import yaml

    from eeze_agent.verticals.photo import run_vertical

    try:
        summary = run_vertical(
            Path(args.spec), out_dir=Path(args.out) if args.out else None,
            ffmpeg_dir=args.ffmpeg_dir,
        )
    except (FileNotFoundError, TypeError, ValueError, RuntimeError, yaml.YAMLError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if (summary["failed"] == 0 and summary["output"]) else 1


def cmd_files(args: argparse.Namespace) -> int:
    """Files vertical: --preview shows the plan; otherwise apply it (writes an undo log)."""
    import yaml

    from eeze_agent.verticals.files import apply_plan, load_spec, plan_changes, undo
    from eeze_agent.verticals.files.runner import FilesError

    try:
        if args.undo:
            print(json.dumps(undo(Path(args.undo)), indent=2, ensure_ascii=False))
            return 0
        if not args.spec:
            print("usage: eeze files <spec.yaml> [--preview] [--out DIR] | eeze files --undo <report>",
                  file=sys.stderr)
            return 2
        spec = load_spec(Path(args.spec))
        if args.preview:
            print(json.dumps(plan_changes(spec), indent=2, ensure_ascii=False))
            return 0
        out = Path(args.out) if args.out else Path("artifacts") / "files" / time.strftime("%Y%m%d-%H%M%S")
        report = apply_plan(spec, out)
    except (FilesError, FileNotFoundError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    summary = {k: report.get(k) for k in ("op", "folder", "files", "applied", "duplicates")}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def cmd_render3d(args: argparse.Namespace) -> int:
    from eeze_agent.verticals.render3d import run_vertical

    spec = Path(args.spec)
    if not spec.exists():
        print(f"spec not found: {spec}", file=sys.stderr)
        return 2
    try:
        summary = run_vertical(
            spec,
            out_dir=Path(args.out) if args.out else None,
            blender_path=args.blender,
            timeout_s=args.timeout,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if (summary["failed"] == 0 and summary["output"]) else 1


def cmd_spec(args: argparse.Namespace) -> int:
    """C3: a plain-language goal -> a validated spec for a creative vertical (and --run to execute)."""
    import time as _time

    from eeze_agent.brains.specwriter import SpecWriteError, SpecWriter, collect_sources

    repo_root = Path(__file__).resolve().parents[2]
    out_dir = (
        Path(args.out)
        if args.out
        else repo_root / "artifacts" / "creative" / f"{_time.strftime('%Y%m%d-%H%M%S')}-{args.kind}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    writer = SpecWriter(model=args.model) if args.model else SpecWriter()
    if not writer.api_key:
        print("EEZE_SPEC_API_KEY / EEZE_PLANNER_API_KEY is not set — see DEVELOPMENT.md", file=sys.stderr)
        return 2
    try:
        if args.kind == "video":
            if not args.sources:
                print("--sources DIR is required to write a video spec", file=sys.stderr)
                return 2
            ffprobe = None
            try:
                from eeze_agent.verticals.video.probe import find_tools

                _ff, ffprobe = find_tools(args.ffmpeg_dir)
            except FileNotFoundError:
                print("ffprobe not found — sources will be listed without media facts", file=sys.stderr)
            names, facts = collect_sources(args.sources, ffprobe=ffprobe)
            result = writer.write_video(
                args.goal, sources=names, facts=facts, out_dir=out_dir, name_hint=out_dir.name
            )
            result.sources = facts
        else:
            result = writer.write_scene(args.goal, out_dir=out_dir, name_hint=out_dir.name)
    except (SpecWriteError, ValueError, TypeError, FileNotFoundError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        f"spec written — model={result.model} attempts={len(result.attempts)} "
        f"tokens={result.tokens} est ${result.cost_usd:.6f} -> {result.spec_path}"
    )
    print(result.yaml_text)
    if not args.run:
        print(f'\nrun it:  uv run eeze {args.kind} "{result.spec_path}" --out {out_dir / "run"}')
        return 0

    run_dir = out_dir / "run"
    try:
        if args.kind == "video":
            from eeze_agent.verticals.video import run_vertical

            summary = run_vertical(result.spec_path, out_dir=run_dir, ffmpeg_dir=args.ffmpeg_dir)
        else:
            from eeze_agent.verticals.render3d import run_vertical

            summary = run_vertical(result.spec_path, out_dir=run_dir, blender_path=args.blender)
    except (FileNotFoundError, ValueError) as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nwrite-report: {out_dir / 'write-report.json'} · artifacts: {run_dir}")
    return 0 if (summary["failed"] == 0 and summary["output"]) else 1


def cmd_goal(args: argparse.Namespace) -> int:
    from eeze_agent.agents.models import AgentContext
    from eeze_agent.agents.registry import load_registry
    from eeze_agent.brains.planner import Planner
    from eeze_agent.brains.registry import make_brain
    from eeze_agent.core.approvals import ApprovalStore
    from eeze_agent.core.goal import execute_goal
    from eeze_agent.core.risk import DEFAULT_ALLOWED, RISK_ORDER, Policy
    from eeze_agent.drivers.cua import CuaDriver

    repo_root = Path(__file__).resolve().parents[2]
    registry = load_registry(repo_root)
    agent = registry.get(args.agent)
    ctx = AgentContext(agent=agent)
    extra = [x.strip() for x in (args.allow or "").split(",") if x.strip()]
    unknown = [x for x in extra if x not in RISK_ORDER]
    if unknown:
        print(f"unknown risk classes in --allow: {unknown} (known: {', '.join(RISK_ORDER)})",
              file=sys.stderr)
        return 2
    allowed = set(agent.permissions.get("risk_classes") or DEFAULT_ALLOWED) | set(extra)
    policy = Policy(frozenset(allowed))

    planner = Planner()
    if not planner.api_key:
        print("EEZE_PLANNER_API_KEY is not set — fill it in .env (see DEVELOPMENT.md)",
              file=sys.stderr)
        return 2

    runs_root = Path(args.out) if args.out else repo_root / "artifacts" / "runs"
    result = execute_goal(
        args.goal,
        runs_root=runs_root,
        driver=CuaDriver(),
        brain=make_brain(agent_id=agent.id, repo_root=repo_root, task=args.goal),
        brain_factory=lambda **kw: make_brain(agent_id=agent.id, repo_root=repo_root, task=args.goal, **kw),
        planner=planner,
        agent_ctx=ctx,
        policy=policy,
        approvals=ApprovalStore(),
        runs=args.runs,
        demo=args.demo,
        max_replans=args.max_replans,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    status = result.get("status")
    if status == "needs_approval":
        approval_id = result.get("approval_id")
        print(
            f"\nPAUSED for approval. Approve via the API (POST /approvals/{approval_id}/decide) "
            f"then: eeze run --resume {approval_id}"
        )
        return 3
    return 0 if status == "done" else 1


def cmd_audit(args: argparse.Namespace) -> int:
    from eeze_agent.core.audit import export_bundle

    repo_root = Path(__file__).resolve().parents[2]
    if args.action == "export":
        if not args.id:
            print("usage: eeze audit export <runset_id> [--out DIR]", file=sys.stderr)
            return 2
        runset_dir = repo_root / "artifacts" / "runs" / args.id
        if not runset_dir.exists():
            print(f"unknown runset: {args.id}", file=sys.stderr)
            return 1
        result = export_bundle(runset_dir, out_dir=Path(args.out) if args.out else None)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    print("usage: eeze audit export <runset_id> [--out DIR]", file=sys.stderr)
    return 2


def cmd_replay(args: argparse.Namespace) -> int:
    from eeze_agent.core.replay import replay_runset

    repo_root = Path(__file__).resolve().parents[2]
    allow = [x.strip() for x in (args.allow or "").split(",") if x.strip()] or None
    verdict = replay_runset(args.id, repo_root=repo_root, runs=args.runs, allow=allow)
    print(
        json.dumps(
            {
                k: verdict[k]
                for k in (
                    "original", "replay", "task", "task_source", "original_status", "replay_status",
                    "compared", "matched", "total_original", "all_match", "missing_steps",
                )
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    for row in verdict["rows"]:
        if row["status"] != "match":
            print(
                f"  DIVERGE run {row['run_index']} step {row['step_id']}: "
                f"{row.get('checks') or row.get('detail')}"
            )
    ok = verdict["all_match"] and verdict["replay_status"] == "done"
    print("REPLAY: MATCH" if ok else "REPLAY: DIVERGED — see replay.json in the replay runset")
    return 0 if ok else 1


def cmd_report(args: argparse.Namespace) -> int:
    from eeze_agent.core.report import build_report, render_markdown

    repo_root = Path(__file__).resolve().parents[2]
    report = build_report(repo_root=repo_root, days=args.days)
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    text = render_markdown(report)
    if args.out:
        out = Path(args.out)
        out.write_text(text, encoding="utf-8")
        print(f"report -> {out}")
    else:
        print(text)
    return 0


def cmd_routines(args: argparse.Namespace) -> int:
    from eeze_agent.core.routine_runner import run_resume, run_routine
    from eeze_agent.core.routines import RoutineStore

    repo_root = Path(__file__).resolve().parents[2]
    home = Path.home() / ".eeze"
    store = RoutineStore()
    action = args.action

    if action == "add":
        spec = (args.schedule or "").strip()
        try:
            if spec.startswith("every:"):
                schedule = {"type": "every", "minutes": int(spec.split(":", 1)[1])}
            elif spec.startswith("daily:"):
                schedule = {"type": "daily", "at": spec.split(":", 1)[1]}
            else:
                raise ValueError
        except ValueError:
            print("schedule must be 'daily:HH:MM' or 'every:MINUTES'", file=sys.stderr)
            return 2
        if not args.id:
            print("usage: eeze routines add <id> --kind ... --schedule ...", file=sys.stderr)
            return 2
        params: dict = {}
        if args.search:
            params["search"] = args.search
        if args.email_summary:
            params["email_summary"] = True
        if args.email_to:
            params["email_to"] = args.email_to
        if args.task:
            params["task_path"] = args.task
        if args.allow:
            params["allow"] = [x.strip() for x in args.allow.split(",") if x.strip()]
        if args.runs:
            params["runs"] = args.runs
        row = store.add(
            args.id, name=args.name or args.id, kind=args.kind, schedule=schedule,
            params=params, agent_id=args.agent,
        )
        print(json.dumps(row, indent=2, ensure_ascii=False))
        return 0
    if action == "list":
        print(json.dumps(store.list(), indent=2, ensure_ascii=False))
        return 0
    if action == "run":
        if not args.id:
            print("usage: eeze routines run <id>", file=sys.stderr)
            return 2
        result = run_routine(args.id, repo_root=repo_root, home=home)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("status") in {"ok", "needs_approval"} else 1
    if action == "resume":
        if not args.id:
            print("usage: eeze routines resume <approval_id>", file=sys.stderr)
            return 2
        from eeze_agent.core.approvals import ApprovalStore

        result = run_resume(
            args.id,
            repo_root=repo_root,
            approvals=ApprovalStore(),
            log=home / "routines" / f"resume-{args.id}.log",
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result.get("status") == "ok" else 1
    if action in {"enable", "disable"}:
        if not args.id:
            print(f"usage: eeze routines {action} <id>", file=sys.stderr)
            return 2
        ok = store.set_enabled(args.id, action == "enable")
        print(json.dumps({"ok": ok, "id": args.id, "enabled": action == "enable"}))
        return 0 if ok else 1
    if action == "remove":
        if not args.id:
            print("usage: eeze routines remove <id>", file=sys.stderr)
            return 2
        ok = store.remove(args.id)
        print(json.dumps({"ok": ok, "id": args.id, "removed": ok}))
        return 0 if ok else 1
    if action == "history":
        print(json.dumps(store.runs(args.id or None, limit=args.limit or 50), indent=2, ensure_ascii=False))
        return 0
    print("usage: eeze routines add|list|run|resume|enable|disable|remove|history", file=sys.stderr)
    return 2


def cmd_mission(args: argparse.Namespace) -> int:
    """F7: missions — the app owns them; this is what the app's Run spawns (and a usable fallback)."""
    from eeze_agent.core.missions import MissionStore, run_mission

    repo_root = Path(__file__).resolve().parents[2]
    action = args.action or "list"
    store = MissionStore()

    if action == "list":
        rows = store.list()
        for row in rows:
            last = row.get("last_run") or {}
            sched = row.get("schedule") or {}
            when = sched.get("at") or (f"every {sched.get('minutes')} min" if sched.get("type") == "every" else "on demand")
            print(
                f"{row['id']:<20} {row['kind']:<6} {when:<16} "
                f"plan={'yes' if row['has_plan'] else 'no ':>3} "
                f"last={last.get('status') or 'never'} ({last.get('at') or '-'})"
            )
        if not rows:
            print("no missions yet — create one in the app (/missions) or via POST /api/missions")
        return 0

    if action == "show":
        if not args.id:
            print("usage: eeze mission show <id>", file=sys.stderr)
            return 2
        row = store.get(args.id)
        if row is None:
            print(f"unknown mission: {args.id!r}", file=sys.stderr)
            return 1
        print(json.dumps({k: v for k, v in row.items() if k != "plan"}, indent=2, ensure_ascii=False))
        print("--- plan ---")
        print(row.get("plan") or "(no plan yet)")
        return 0

    if action == "run":
        if not args.id:
            print("usage: eeze mission run <id>", file=sys.stderr)
            return 2
        result = run_mission(args.id, repo_root=repo_root)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        status = str(result.get("status") or "error")
        if status == "needs_approval":
            approval_id = result.get("approval_id")
            print(
                f"\nPAUSED for approval ({approval_id}). Decide it in the app (Approvals) or via "
                f"POST /api/approvals/{approval_id}/decide, then: eeze run --resume {approval_id}"
            )
            return 3
        return 0 if status in ("done", "ok") else 1

    print(f"unknown action {action!r} — list | show | run", file=sys.stderr)
    return 2


def cmd_inbox(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from eeze_agent.verticals.invoices.imap_source import (
        ImapConfigError,
        ImapError,
        pull_pdf_attachments,
    )

    repo_root = Path(__file__).resolve().parents[2]
    out_dir = Path(args.out) if args.out else repo_root / "artifacts" / "e1-invoices" / "inbox"
    try:
        result = pull_pdf_attachments(
            out_dir,
            folder=getattr(args, "folder", "INBOX"),
            search=getattr(args, "search", "ALL"),
            limit=getattr(args, "limit", None),
        )
    except (ImapConfigError, ImapError) as exc:
        print(f"inbox: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(result), indent=2, ensure_ascii=False))
    return 0


def cmd_doctor_pilot(args: argparse.Namespace) -> int:
    from eeze_agent.core.pilot import pilot_checks

    repo_root = Path(__file__).resolve().parents[2]
    result = pilot_checks(repo_root=repo_root)
    for check in result["checks"]:
        mark = "OK" if check["ok"] else ("FAIL" if check["critical"] else "warn")
        print(f"  [{mark:4}] {check['name']}: {check['detail']}")
    print("PILOT READY" if result["ok"] else "PILOT NOT READY — fix the FAIL items above")
    return 0 if result["ok"] else 1


def cmd_backup(args: argparse.Namespace) -> int:
    from eeze_agent.core.backup import create_backup

    repo_root = Path(__file__).resolve().parents[2]
    result = create_backup(
        repo_root=repo_root,
        out_dir=Path(args.out) if args.out else None,
        with_runs=bool(args.with_runs),
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_approvals(args: argparse.Namespace) -> int:
    """List pending approvals, or abandon one that can never resume (legacy rows)."""
    from eeze_agent.core.approvals import ApprovalStore

    store = ApprovalStore()
    if args.action == "list":
        rows = store.list(status=None if args.all else "pending", limit=100)
        for row in rows:
            print(f"{row['id']}  {row['status']:<10} {row.get('created_at') or '':<26} "
                  f"{row.get('risk_class') or '':<14} {row.get('task') or ''} · {row.get('step_id') or ''}")
        if not rows:
            print("no pending approvals" if not args.all else "no approvals")
        return 0
    if args.action == "abandon":
        if not args.id:
            print("usage: eeze approvals abandon <approval_id> [--reason TEXT]", file=sys.stderr)
            return 2
        try:
            row = store.abandon(args.id, decided_by="cli", reason=args.reason)
        except KeyError:
            print(f"no pending approval {args.id!r}", file=sys.stderr)
            return 1
        print(f"abandoned {row['id']} — nothing was run; its routine can schedule again")
        return 0
    if args.action == "expire":
        from eeze_agent.core.approvals import pending_ttl_hours

        hours = args.hours if args.hours is not None else pending_ttl_hours()
        expired = store.expire_stale(hours)
        print(f"expired {len(expired)} approval(s) older than {hours:g}h: {', '.join(expired) or '-'}")
        return 0
    return 2


def cmd_doctor_focus(args: argparse.Namespace) -> int:
    from eeze_agent.core.focus import run_focus_audit

    repo_root = Path(__file__).resolve().parents[2]
    task_path = Path(args.task) if args.task else repo_root / "tasks" / "notepad-gated-demo.yaml"
    result = run_focus_audit(task_path=task_path, repo_root=repo_root, runs=args.runs or 1)
    summary = {
        "pass": result["pass"],
        "focus_pass": result["focus_pass"],
        "cursor_pass": result["cursor_pass"],
        "samples": result["samples"],
        "focus_change_count": result["focus_change_count"],
        "cursor_move_count": result["cursor_move_count"],
        "run_status": result["run_status"],
        "success_rate": result["success_rate"],
        "artifact": result["artifact"],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("FOCUS AUDIT: PASS" if result["pass"] else "FOCUS AUDIT: FAIL — see the artifact for evidence")
    return 0 if result["pass"] else 1


def cmd_doctor_input(args: argparse.Namespace) -> int:
    import importlib.util

    repo_root = Path(__file__).resolve().parents[2]
    tool = repo_root / "tools" / "diagnose_input.py"
    spec = importlib.util.spec_from_file_location("eeze_diagnose_input", tool)
    if spec is None or spec.loader is None:
        print(f"diagnosis tool not found: {tool}", file=sys.stderr)
        return 1
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    report = mod.run_diagnosis(seconds=args.seconds)
    mod.print_report(report)
    return 0 if "error" not in report else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eeze", description="Eeze Agent")
    sub = parser.add_subparsers(dest="cmd")


    doctor_p = sub.add_parser("doctor", help="environment self-check")
    doctor_p.add_argument(
        "what",
        nargs="?",
        default=None,
        choices=[None, "input", "focus", "pilot"],
        help=(
            "optional: 'input' runs the keyboard-input diagnosis (hardware vs software); "
            "'focus' runs the zero focus-steal audit against a real task; "
            "'pilot' checks everything the scheduled routine depends on"
        ),
    )
    doctor_p.add_argument("--seconds", type=int, default=60, help="doctor input: capture window")
    doctor_p.add_argument("--task", default=None, help="doctor focus: task YAML (default: notepad demo)")
    doctor_p.add_argument("--runs", type=int, default=1, help="doctor focus: runs")

    open_p = sub.add_parser("open", help="open the dashboard in the browser, already paired")
    open_p.add_argument("page", nargs="?", default="/missions", help="page to land on, e.g. /setup")
    open_p.add_argument("--port", type=int, default=8765)
    open_p.add_argument("--print-only", action="store_true", help="print the one-time link instead")

    sub.add_parser("unpair", help="sign every browser out (replaces ~/.eeze/api.token)")

    api_p = sub.add_parser("api", help="read-only HTTP API (F1.5): serve | start | stop | status")
    api_p.add_argument(
        "action",
        nargs="?",
        default="serve",
        choices=["serve", "start", "stop", "status"],
        help="serve = foreground (default); start/stop/status = detached daemon (~/.eeze/api.pid)",
    )
    api_p.add_argument(
        "--host", default=None, help="bind host (default 127.0.0.1 — local-only; use 0.0.0.0 to expose on the LAN)"
    )
    api_p.add_argument("--port", type=int, default=8765)
    api_p.add_argument(
        "--serve-ui",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="serve ui/dist at / (default: auto when ui/dist/index.html exists)",
    )

    tun_p = sub.add_parser("tunnel", help="cloudflared quick tunnel: start | url | stop")
    tun_p.add_argument("action", nargs="?", default="url", choices=["start", "url", "stop"])
    tun_p.add_argument("--port", type=int, default=8765)

    ui_p = sub.add_parser("ui", help="frontend (ui/): build | dev | install")
    ui_p.add_argument("action", nargs="?", default="build", choices=["build", "dev", "install"])

    inv_p = sub.add_parser(
        "invoices", help="invoice vertical (E1): folder of PDFs -> ledger.csv + anomalies.md"
    )
    inv_p.add_argument("--input", required=True, help="folder with invoice PDFs")
    inv_p.add_argument("--out", default=None, help="output folder (default: artifacts/e1-invoices/out)")
    inv_p.add_argument("--limit", type=int, default=None, help="process at most N files")
    inv_p.add_argument("--model", default=None, help="override the extraction model")

    inbox_p = sub.add_parser(
        "inbox", help="read-only mailbox pull (E2): PDF attachments -> local folder"
    )
    inbox_p.add_argument("action", nargs="?", default="pull", choices=["pull"])
    inbox_p.add_argument("--out", default=None, help="local folder (default: artifacts/e1-invoices/inbox)")
    inbox_p.add_argument("--folder", default="INBOX", help="IMAP folder (default INBOX)")
    inbox_p.add_argument("--search", default="ALL", help="IMAP search (default ALL; e.g. UNSEEN)")
    inbox_p.add_argument("--limit", type=int, default=None, help="most recent N matching messages")

    video_p = sub.add_parser(
        "video", help="video vertical (C1): spec-driven ffmpeg edit, every step ffprobe-verified"
    )
    video_p.add_argument("spec", help="edit spec YAML (see specs/)")
    video_p.add_argument(
        "--out", default=None, help="output dir (default: artifacts/video/<stamp>-<name>)"
    )
    video_p.add_argument("--ffmpeg-dir", default=None, help="dir containing ffmpeg/ffprobe")

    photo_p = sub.add_parser(
        "photo", help="local photo vertical (A18): crop, resize and adjust; verified PNG output"
    )
    photo_p.add_argument("spec", help="photo edit spec YAML (see specs/)")
    photo_p.add_argument("--out", default=None, help="output dir (default: artifacts/photo/<stamp>-<name>)")
    photo_p.add_argument("--ffmpeg-dir", default=None, help="dir containing ffmpeg/ffprobe")

    files_p = sub.add_parser(
        "files", help="files vertical: batch rename / organize / duplicates, with preview and undo"
    )
    files_p.add_argument("spec", nargs="?", default=None, help="files spec YAML")
    files_p.add_argument("--out", default=None, help="where the report + undo log go")
    files_p.add_argument("--preview", action="store_true", help="show the changes, touch nothing")
    files_p.add_argument("--undo", default=None, help="undo a previous run from its files-report.json")

    three_d_p = sub.add_parser(
        "3d",
        help="3D vertical (C2): declarative scene rendered in Blender headless, artifacts verified",
    )
    three_d_p.add_argument("spec", help="scene spec YAML (see specs/)")
    three_d_p.add_argument(
        "--out", default=None, help="output dir (default: artifacts/3d/<stamp>-<name>)"
    )
    three_d_p.add_argument("--blender", default=None, help="path to the Blender binary")
    three_d_p.add_argument(
        "--timeout", type=float, default=None, help="Blender run timeout in seconds (default 900)"
    )

    spec_p = sub.add_parser(
        "spec",
        help="C3 creative writer: a plain-language goal -> a validated spec (and --run to execute it)",
    )
    spec_p.add_argument("kind", choices=["video", "3d"], help="which vertical the spec is for")
    spec_p.add_argument("goal", help="the goal, in plain language")
    spec_p.add_argument("--sources", default=None, help="video: dir with the source clips/stills")
    spec_p.add_argument("--out", default=None, help="output dir (default: artifacts/creative/<stamp>-<kind>)")
    spec_p.add_argument("--run", action="store_true", help="execute the spec after writing it")
    spec_p.add_argument("--model", default=None, help="override the writer model (default EEZE_SPEC_MODEL/planner)")
    spec_p.add_argument("--ffmpeg-dir", default=None, help="dir containing ffmpeg/ffprobe (video)")
    spec_p.add_argument("--blender", default=None, help="path to the Blender binary (3d)")

    run_p = sub.add_parser("run", help="run a task spec (YAML); resume a paused (gated) run with --resume")
    run_p.add_argument("task", nargs="?", default=None, help="path to a task YAML file")
    run_p.add_argument("--runs", type=int, default=1)
    run_p.add_argument("--agent", default="default")
    run_p.add_argument("--demo", action="store_true", help="save per-step screenshots")
    run_p.add_argument(
        "--isolated",
        action="store_true",
        help="pre-run isolation: single fresh app window + empty doc (kills only our leftovers)",
    )
    run_p.add_argument("--out", default=None, help="artifacts output root")
    run_p.add_argument(
        "--allow",
        default=None,
        help="extra risk classes allowed without approval, comma-separated (F2 gate)",
    )
    run_p.add_argument(
        "--resume",
        default=None,
        metavar="APPROVAL_ID",
        help="resume a run-set paused by the risk gate (approval must be approved first)",
    )

    goal_p = sub.add_parser(
        "goal", help="System-2 planner: natural-language goal -> plan -> gated execution (F2)"
    )
    goal_p.add_argument("goal", help="the goal, in plain language")
    goal_p.add_argument("--agent", default="default")
    goal_p.add_argument("--runs", type=int, default=1)
    goal_p.add_argument("--demo", action="store_true")
    goal_p.add_argument("--max-replans", type=int, default=2)
    goal_p.add_argument("--allow", default=None, help="extra risk classes, comma-separated")
    goal_p.add_argument("--out", default=None, help="artifacts output root")

    routines_p = sub.add_parser(
        "routines",
        help="scheduled routines (F4): add|list|run|resume|enable|disable|remove|history",
    )
    routines_p.add_argument("action", nargs="?", default="list")
    routines_p.add_argument("id", nargs="?", default=None)
    routines_p.add_argument("--kind", default="invoices", choices=["invoices", "task"])
    routines_p.add_argument("--name", default=None)
    routines_p.add_argument("--schedule", default=None, help="daily:HH:MM | every:MINUTES")
    routines_p.add_argument("--search", default=None, help="IMAP search for the invoices kind")
    routines_p.add_argument("--email-summary", action="store_true", help="send the summary (GATED)")
    routines_p.add_argument("--email-to", default=None)
    routines_p.add_argument("--task", default=None, help="task YAML path (kind=task)")
    routines_p.add_argument("--agent", default="default", help="agent id this routine runs as")
    routines_p.add_argument("--allow", default=None, help="extra risk classes for this routine")
    routines_p.add_argument("--runs", type=int, default=None)
    routines_p.add_argument("--limit", type=int, default=50)

    mission_p = sub.add_parser(
        "mission",
        help="missions (F7): list|show|run — write/edit yours in the app (/missions)",
    )
    mission_p.add_argument("action", nargs="?", default="list")
    mission_p.add_argument("id", nargs="?", default=None)

    report_p = sub.add_parser(
        "report", help="weekly metrics report (runs, routines, approvals, focus audits)"
    )
    report_p.add_argument("--days", type=int, default=7)
    report_p.add_argument("--json", action="store_true", help="raw JSON instead of markdown")
    report_p.add_argument("--out", default=None, help="write markdown to a file")

    audit_p = sub.add_parser("audit", help="audit trail (F3): export <runset_id> [--out DIR]")
    audit_p.add_argument("action", nargs="?", default="export")
    audit_p.add_argument("id", nargs="?", default=None)
    audit_p.add_argument("--out", default=None, help="bundle output dir")

    replay_p = sub.add_parser("replay", help="replay a runset's task and diff the outcomes (F3)")
    replay_p.add_argument("id", help="runset id (artifacts/runs/<id>)")
    replay_p.add_argument("--runs", type=int, default=None)
    replay_p.add_argument("--allow", default=None, help="extra risk classes, comma-separated")

    appr_p = sub.add_parser(
        "approvals", help="approvals queue: list [--all] | abandon <id> | expire [--hours N]"
    )
    appr_p.add_argument("action", choices=["list", "abandon", "expire"])
    appr_p.add_argument("id", nargs="?", default=None)
    appr_p.add_argument("--all", action="store_true", help="list every status, not only pending")
    appr_p.add_argument("--reason", default=None)
    appr_p.add_argument("--hours", type=float, default=None,
                        help="expire pending approvals older than this (default EEZE_APPROVAL_TTL_HOURS or 72)")

    backup_p = sub.add_parser("backup", help="zip the local state (store, .env, logs)")
    backup_p.add_argument("--out", default=None, help="output dir (default: <repo>/backups)")
    backup_p.add_argument("--with-runs", action="store_true", help="include artifacts (runs/routines/audits)")

    args = parser.parse_args(argv)
    if args.cmd == "doctor":
        if getattr(args, "what", None) == "input":
            return cmd_doctor_input(args)
        if getattr(args, "what", None) == "focus":
            return cmd_doctor_focus(args)
        if getattr(args, "what", None) == "pilot":
            return cmd_doctor_pilot(args)
        return doctor()
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "approvals":
        return cmd_approvals(args)
    if args.cmd == "files":
        return cmd_files(args)
    if args.cmd == "open":
        return cmd_open(args)
    if args.cmd == "unpair":
        return cmd_unpair(args)
    if args.cmd == "goal":
        return cmd_goal(args)
    if args.cmd == "routines":
        return cmd_routines(args)
    if args.cmd == "mission":
        return cmd_mission(args)
    if args.cmd == "report":
        return cmd_report(args)
    if args.cmd == "audit":
        return cmd_audit(args)
    if args.cmd == "replay":
        return cmd_replay(args)
    if args.cmd == "backup":
        return cmd_backup(args)
    if args.cmd == "api":
        return cmd_api(args)
    if args.cmd == "tunnel":
        return cmd_tunnel(args)
    if args.cmd == "ui":
        return cmd_ui(args)
    if args.cmd == "invoices":
        return cmd_invoices(args)
    if args.cmd == "inbox":
        return cmd_inbox(args)
    if args.cmd == "video":
        return cmd_video(args)
    if args.cmd == "photo":
        return cmd_photo(args)
    if args.cmd == "spec":
        return cmd_spec(args)
    if args.cmd == "3d":
        return cmd_render3d(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
