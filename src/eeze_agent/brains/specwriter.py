"""Spec writer (C3): a goal in plain language -> a VALIDATED spec for a creative vertical.

The model writes; the code verifies. Order of trust:

1. the vocabulary in the prompt is generated from the vertical's own code (`vocab.py`,
   test-locked against the validators) — never hand-written prose that can drift;
2. the reply is parsed as JSON and validated through the vertical's OWN pydantic spec model;
3. the spec is checked for feasibility against REAL media facts (ffprobe of the sources):
   no invented footage, no trims past the end of a clip;
4. any failure is fed BACK to the model (bounded attempts) and every attempt is recorded
   in ``write-report.json`` — the loop tells itself no, it never repairs silently;
5. the writer never executes anything: the caller runs the vertical, whose steps are verified
   again against the artifacts they actually produced.

Model: ``EEZE_SPEC_MODEL`` -> ``EEZE_PLANNER_MODEL`` (the hard tier by policy — writing a
strict spec is exactly the "hard" work `brains/router.py` names), same OpenRouter transport
as the planner. ``EEZE_SPEC_ENGINE`` (falling back to ``EEZE_PLANNER_ENGINE``) may be
``codex``: then the spec is written on the owner's Codex subscription
(``brains/codex.py: codex_client``, tier ``hard`` = ``gpt-6-sol``) — local-only, no paid
spend, a CLI failure retried then raised as ``SpecWriteError``.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from eeze_agent.core.jsonx import parse_json_object
from eeze_agent.core.pricing import estimate_cost_usd

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openai/gpt-6-sol"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".png", ".jpg", ".jpeg", ".bmp", ".webp"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

RULES = """You write ONE spec as a JSON object and nothing else — no prose, no markdown.
Rules:
- Use ONLY the ops and fields in the vocabulary below; never invent ops or extra fields.
- Source names come from the SOURCES table; reference them by NAME, never by path.
- Steps are ordered; a step may reference sources and EARLIER step ids only.
- Numbers must respect the stated constraints (sizes even, durations positive).
- Prefer the simplest chain that achieves the goal; keep step ids short and descriptive.
- The document must be a single JSON object (the spec), parseable by json.loads."""


class SpecWriteError(RuntimeError):
    """The writer could not produce a spec that validates and runs."""


@dataclass
class WriteResult:
    kind: str  # "video" | "3d"
    spec: Any
    spec_path: Path
    yaml_text: str
    attempts: list[dict] = field(default_factory=list)
    model: str = ""
    tokens: int = 0
    cost_usd: float = 0.0
    sources: dict[str, dict] = field(default_factory=dict)

    def as_report(self) -> dict:
        return {
            "kind": self.kind,
            "model": self.model,
            "attempts": self.attempts,
            "tokens": self.tokens,
            "cost_estimate_usd": self.cost_usd,
            "sources": self.sources,
            "spec_path": str(self.spec_path),
        }


def split_sources(sources: str | Path) -> tuple[Path, Path | None]:
    """``(folder, single file or None)`` for what the user typed as "sources".

    Accepts a folder or ONE file (then only that file is used), with or without the
    surrounding quotes Windows adds on "Copy as path". A file used to crash with
    ``WinError 267 The directory name is invalid``.
    """
    text = str(sources or "").strip().strip('"').strip("'").strip()
    path = Path(text)
    if path.is_file():
        return path.parent, path
    return path, None


def collect_sources(sources_dir: str | Path, *, ffprobe: Path | None = None) -> tuple[dict[str, str], dict[str, dict]]:
    """Enumerate a sources dir (or one file) into ``{name: absolute path}`` + probed fact sheets."""
    root, only = split_sources(sources_dir)
    if not root.exists():
        raise FileNotFoundError(f"sources folder not found: {root}")
    if not root.is_dir():
        raise FileNotFoundError(f"sources must be a folder or a file inside one: {root}")
    names: dict[str, str] = {}
    facts: dict[str, dict] = {}
    candidates = [only] if only is not None else sorted(p for p in root.iterdir() if p.is_file())
    for path in candidates:
        if path.suffix.lower() not in VIDEO_EXTS:
            continue
        name = path.stem.lower().replace(" ", "-")
        stamp = 2
        while name in names:
            name = f"{path.stem.lower().replace(' ', '-')}-{stamp}"
            stamp += 1
        names[name] = str(path.resolve())
        sheet: dict = {"kind": "image" if path.suffix.lower() in IMAGE_EXTS else "video"}
        sheet["path"] = str(path.resolve())
        if ffprobe is not None:
            try:
                from eeze_agent.verticals.video.probe import probe

                info = probe(ffprobe, path)
                sheet.update(
                    {
                        "kind": info.kind,
                        "codec_v": info.codec_v,
                        "width": info.width,
                        "height": info.height,
                        "duration_s": info.duration_s,
                        "fps": info.fps,
                        "has_audio": info.has_audio,
                        "size_bytes": info.size_bytes,
                    }
                )
            except Exception as exc:  # noqa: BLE001 — facts degrade honestly, never block
                sheet["probe_error"] = f"{type(exc).__name__}: {str(exc)[:120]}"
        else:
            try:
                sheet["size_bytes"] = path.stat().st_size
            except OSError:
                pass
        facts[name] = {k: v for k, v in sheet.items() if v is not None}
    if not names:
        raise SpecWriteError(f"no usable sources in {root} (looked for: {sorted(VIDEO_EXTS)})")
    return names, facts


def _sources_block(names: dict[str, str], facts: dict[str, dict]) -> str:
    lines = ["SOURCES (reference by name; copy the path EXACTLY into spec.sources):"]
    for name in sorted(names):
        sheet = facts.get(name, {})
        pretty = ", ".join(
            f"{k}={v}" for k, v in sheet.items() if k not in ("kind", "path")
        ) or "no probe facts"
        lines.append(f'- "{name}": {sheet.get("path", names[name])} — {sheet.get("kind", "unknown")}, {pretty}')
    return "\n".join(lines)


class SpecWriter:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 240.0,
        client: Callable[[str, str], tuple[str, int]] | None = None,
        engine: str | None = None,
        provider: object | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("EEZE_SPEC_BASE_URL") or os.environ.get("EEZE_PLANNER_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.api_key = (
            api_key or os.environ.get("EEZE_SPEC_API_KEY") or os.environ.get("EEZE_PLANNER_API_KEY") or ""
        )
        self.model = (
            model or os.environ.get("EEZE_SPEC_MODEL") or os.environ.get("EEZE_PLANNER_MODEL")
            or DEFAULT_MODEL
        )
        self.timeout = timeout
        self.provider_id = ""
        self.provider_source = "default"
        self.engine = (
            engine
            or os.environ.get("EEZE_SPEC_ENGINE")
            or os.environ.get("EEZE_PLANNER_ENGINE")
            or "http"
        ).strip().lower()
        self._client = client
        if self._client is None and self.engine == "codex":
            from eeze_agent.brains.codex import codex_client, codex_model_for_tier

            self._client = codex_client(tier="hard")  # spec writing is the hard tier by policy
            self.model = f"codex:{codex_model_for_tier('hard')}"
        elif self._client is None and self.engine == "http":
            # Provider layer (P2): a stored key/endpoint wins over env, which wins over the default.
            from eeze_agent.core.providers import (
                require_key_for_endpoint_override,
                resolve_provider,
            )

            cfg = provider if provider is not None else resolve_provider("spec")
            require_key_for_endpoint_override(base_url, api_key, cfg)
            self.provider_id = getattr(cfg, "provider_id", "") or "openrouter"
            self.provider_source = getattr(cfg, "source", "default")
            if not base_url and getattr(cfg, "base_url", ""):
                self.base_url = str(cfg.base_url).rstrip("/")
            # The resolved config owns the credential, including the empty (unconfigured) case.
            self.api_key = api_key if api_key is not None else str(getattr(cfg, "api_key", ""))
            if not model and getattr(cfg, "model", ""):
                self.model = str(cfg.model)
        self.max_attempts = max(1, int(max_attempts))
        self.calls = 0
        # Whose daily budget pays for spec calls (missions pass their agent).
        self.budget_agent: object | None = None

    # -- transport -------------------------------------------------------------

    def _chat(self, system: str, user: str) -> tuple[str, int, float]:
        self.calls += 1
        t0 = time.perf_counter()
        if self._client is not None:
            try:
                reply, tokens = self._client(system, user)
            except SpecWriteError:
                raise
            except Exception as exc:
                raise SpecWriteError(f"spec engine failed: {exc}") from exc
            return reply, tokens, (time.perf_counter() - t0) * 1000
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
        ms = (time.perf_counter() - t0) * 1000
        if response.status_code != 200:
            raise SpecWriteError(f"spec writer HTTP {response.status_code}: {response.text[:300]}")
        body = response.json()
        try:
            reply = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise SpecWriteError(f"spec writer reply missing choices: {str(body)[:200]}") from exc
        usage = body.get("usage") or {}
        tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        return reply, tokens, ms

    # -- the write loop --------------------------------------------------------

    def _write(
        self,
        *,
        kind: str,
        goal: str,
        system: str,
        user: str,
        validate: Callable[[dict], Any],
        feasibility: Callable[[Any], list[str]],
        spec_path: Path,
    ) -> WriteResult:
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        attempts: list[dict] = []
        last_error = ""
        total_tokens = 0
        from eeze_agent.core import spend

        for attempt in range(1, self.max_attempts + 1):
            try:
                spend.check_budget(self.budget_agent)
            except spend.BudgetExceeded as exc:
                raise SpecWriteError(str(exc)) from exc
            prompt = user if not last_error else (
                f"{user}\n\nYOUR PREVIOUS ATTEMPT WAS REJECTED — fix exactly this and answer "
                f"with the full corrected JSON again:\n{last_error}"
            )
            reply, tokens, ms = self._chat(system, prompt)
            total_tokens += tokens
            try:
                spend.record(getattr(self.budget_agent, "id", "default"), self.model, tokens,
                             source=f"specwriter:{kind}")
            except Exception:  # noqa: BLE001, S110 — bookkeeping never blocks a spec
                pass
            try:
                data = parse_json_object(reply, what="spec reply")
                spec = validate(data)
                problems = feasibility(spec)
                if problems:
                    raise SpecWriteError("feasibility: " + "; ".join(problems))
            except Exception as exc:  # noqa: BLE001 — a rejected attempt is data, not a crash
                last_error = f"{type(exc).__name__}: {str(exc)[:500]}"
                attempts.append(
                    {"attempt": attempt, "ms": round(ms, 1), "tokens": tokens,
                     "error": last_error, "reply_head": reply[:300]}
                )
                continue
            import yaml

            yaml_text = yaml.safe_dump(
                spec.model_dump(mode="json", exclude_unset=(kind == "photo")),
                sort_keys=False, allow_unicode=True,
            )
            spec_path.write_text(yaml_text, encoding="utf-8")
            attempts.append({"attempt": attempt, "ms": round(ms, 1), "tokens": tokens, "error": None})
            result = WriteResult(
                kind=kind,
                spec=spec,
                spec_path=spec_path,
                yaml_text=yaml_text,
                attempts=attempts,
                model=self.model,
                tokens=total_tokens,
                cost_usd=estimate_cost_usd(self.model, total_tokens),
            )
            (spec_path.parent / "write-report.json").write_text(
                json.dumps(result.as_report(), indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return result
        failure = {
            "kind": kind, "model": self.model, "attempts": attempts,
            "tokens": total_tokens, "cost_estimate_usd": estimate_cost_usd(self.model, total_tokens),
            "spec_path": str(spec_path), "status": "failed",
        }
        (spec_path.parent / "write-report.json").write_text(
            json.dumps(failure, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        raise SpecWriteError(
            f"no valid spec after {self.max_attempts} attempt(s) — last error: {last_error}"
        )

    # -- video -----------------------------------------------------------------

    def write_video(
        self,
        goal: str,
        *,
        sources: dict[str, str],
        facts: dict[str, dict],
        out_dir: str | Path,
        name_hint: str = "goal-edit",
    ) -> WriteResult:
        from eeze_agent.verticals.video.spec import VideoSpec
        from eeze_agent.verticals.video.vocab import describe_video_vocab

        system = f"{RULES}\n\n{describe_video_vocab()}"
        user = (
            f"GOAL (plain language):\n{goal}\n\n"
            f"{_sources_block(sources, facts)}\n\n"
            f'Answer with the complete JSON spec, for example {{"name": "{name_hint}", "sources": '
            f'{{"clip": "<the absolute path given to you>"}}, "steps": [...], "output": "..."}} — '
            f"use the paths exactly as listed above."
        )
        return self._write(
            kind="video",
            goal=goal,
            system=system,
            user=user,
            validate=lambda data: VideoSpec(**data),
            feasibility=lambda spec: _feasibility_video(spec, facts),
            spec_path=Path(out_dir) / "spec.yaml",
        )

    # -- photo ----------------------------------------------------------------

    def write_photo(
        self,
        goal: str,
        *,
        sources: dict[str, str],
        facts: dict[str, dict],
        out_dir: str | Path,
        name_hint: str = "photo-edit",
    ) -> WriteResult:
        from eeze_agent.verticals.photo.spec import PhotoSpec
        from eeze_agent.verticals.photo.vocab import describe_photo_vocab

        system = (
            "Write exactly one local photo-edit spec as a JSON object, no markdown. "
            "Use only the vocabulary and exact source paths below; never execute.\n\n"
            + describe_photo_vocab()
        )
        user = (
            f"GOAL (plain language):\n{goal}\n\n{_sources_block(sources, facts)}\n\n"
            f'Answer with a full JSON object: {{"name": "{name_hint}", '
            '"source": "<exact absolute path listed above>", "steps": [...], '
            '"output": "<safe-name>.png"}}.'
        )
        return self._write(
            kind="photo", goal=goal, system=system, user=user,
            validate=lambda data: PhotoSpec(**data),
            feasibility=lambda spec: _feasibility_photo(spec, facts),
            spec_path=Path(out_dir) / "spec.yaml",
        )

    # -- files -----------------------------------------------------------------

    def write_files(
        self, goal: str, *, folder: str, out_dir: str | Path, name_hint: str = "files"
    ) -> WriteResult:
        from eeze_agent.verticals.files.spec import FilesSpec
        from eeze_agent.verticals.files.vocab import describe_files_vocab

        system = f"{RULES}\n\n{describe_files_vocab()}"
        user = (
            f"GOAL (plain language, English or Portuguese):\n{goal}\n\n"
            f"FOLDER (use exactly this path): {folder}\n\n"
            f'Answer with the complete JSON spec, for example {{"name": "{name_hint}", '
            f'"folder": {json.dumps(folder)}, "op": "rename", "pattern": "photo{{n:03}}"}}'
        )
        return self._write(
            kind="files", goal=goal, system=system, user=user,
            validate=lambda data: FilesSpec(**data),
            feasibility=lambda spec: _feasibility_files(spec, folder),
            spec_path=Path(out_dir) / "spec.yaml",
        )

    # -- 3d --------------------------------------------------------------------

    def write_scene(
        self, goal: str, *, out_dir: str | Path, name_hint: str = "goal-scene"
    ) -> WriteResult:
        from eeze_agent.verticals.render3d.spec import Scene3DSpec
        from eeze_agent.verticals.render3d.vocab import describe_3d_vocab

        system = f"{RULES}\n\n{describe_3d_vocab()}"
        user = (
            f"GOAL (plain language):\n{goal}\n\n"
            f'Answer with the complete JSON spec, for example {{"name": "{name_hint}", "scene": '
            f'{{"objects": [...], "camera": {{...}}, "lights": [...]}}, "render": {{...}}, '
            f'"steps": [{{"id": "anim", "op": "render_animation"}}], "output": "anim.mp4"}}'
        )
        return self._write(
            kind="3d",
            goal=goal,
            system=system,
            user=user,
            validate=lambda data: Scene3DSpec(**data),
            feasibility=lambda spec: _feasibility_3d(spec),
            spec_path=Path(out_dir) / "spec.yaml",
        )


# -- feasibility against real facts -------------------------------------------


def _feasibility_video(spec: Any, facts: dict[str, dict]) -> list[str]:
    """Refuse specs that cannot run: unknown sources, wrong kinds, trims past the end.

    Mirrors the runner's own `_resolve`: a step with no `input` cuts from the previous step,
    and the first step of a chain has nothing to cut from. Only SOURCE durations are checked
    here — an earlier step's output duration is known only after it runs, and the runner
    verifies that artifact for real.
    """
    problems: list[str] = []
    for name, value in (getattr(spec, "sources", None) or {}).items():
        sheet = facts.get(name)
        if sheet is None:
            problems.append(
                f"sources[{name!r}] is not one of the provided sources ({', '.join(sorted(facts))})"
            )
            continue
        want = str(sheet.get("path") or "").replace("\\", "/")
        if want and str(value).replace("\\", "/") != want:
            problems.append(
                f"sources[{name!r}] must be the exact path {want!r} (got {str(value)!r})"
            )
    previous: str | None = None
    for step in spec.steps:
        if step.op == "still_to_video":
            sheet = facts.get(step.source or "")
            if sheet is None:
                problems.append(f"step {step.id!r}: source {step.source!r} does not exist")
            elif sheet.get("kind") not in ("image", "unknown"):
                problems.append(
                    f"step {step.id!r}: still_to_video needs a still image, but {step.source!r} is a {sheet.get('kind')}"
                )
        if step.op == "trim":
            ref = step.input or previous
            if ref is None:
                problems.append(
                    f"step {step.id!r}: trim has no input and there is no previous step to cut from"
                )
            elif (sheet := facts.get(ref)) is not None:
                duration = sheet.get("duration_s")
                if duration is not None:
                    start = float(step.start or 0)
                    wanted = step.duration if step.duration is not None else float(step.end or 0) - start
                    if start >= duration:
                        problems.append(
                            f"step {step.id!r}: start {start}s is past the end of {ref!r} ({duration}s)"
                        )
                    elif wanted > 0 and start + wanted > duration + 0.05:
                        problems.append(
                            f"step {step.id!r}: start {start} + duration {wanted} exceeds {ref!r} ({duration}s)"
                        )
        previous = step.id
    return problems


def _feasibility_photo(spec: Any, facts: dict[str, dict]) -> list[str]:
    """Bind one photo to a probed local source; check every crop against current size."""
    problems: list[str] = []
    source = str(spec.source).replace("\\", "/")
    sheets = [sheet for sheet in facts.values()
              if str(sheet.get("path") or "").replace("\\", "/") == source]
    if not sheets:
        return ["source must be the exact path of one provided image"]
    sheet = sheets[0]
    if sheet.get("kind") != "image" or sheet.get("codec_v") not in ("png", "mjpeg"):
        return ["source must be a probed PNG or JPEG image"]
    width, height = sheet.get("width"), sheet.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width < 1 or height < 1:
        return ["source dimensions unavailable — cannot validate crops"]
    for step in spec.steps:
        if step.op == "crop":
            if step.x + step.width > width or step.y + step.height > height:
                problems.append(f"step {step.id!r}: crop is outside current {width}x{height} image")
            width, height = step.width, step.height
        elif step.op == "resize":
            width, height = step.width, step.height
    return problems


def _feasibility_files(spec: Any, folder: str) -> list[str]:
    """The plan must target exactly the folder the user chose, and it must exist."""
    wanted = Path(str(folder).strip().strip('"').strip("'"))
    got = spec.folder_path()
    if not got.is_dir():
        return [f"folder not found: {got}"]
    try:
        same = got.resolve() == wanted.resolve()
    except OSError:
        same = False
    return [] if same else [f"folder must be exactly {wanted}"]


def _feasibility_3d(spec: Any) -> list[str]:
    """A 1-frame 'animation' is almost never what a goal asking for motion wants."""
    problems: list[str] = []
    ops = {s.op for s in spec.steps}
    if "render_animation" in ops and spec.render.frames < 2:
        problems.append("render_animation with render.frames < 2 produces a still — set frames/fps for a real clip")
    return problems
