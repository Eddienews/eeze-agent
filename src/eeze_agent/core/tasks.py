"""Task loading — YAML task specs into TaskSpec models."""

from __future__ import annotations

from pathlib import Path

from eeze_agent.core.models import TaskSpec


def load_task(path: Path) -> TaskSpec:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError(f"{path}: task file must contain a YAML mapping")
    return TaskSpec(**data)
