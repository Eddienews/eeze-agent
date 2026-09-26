"""F0 spike: live Jev call — latency, answers, usage.

Sends one realistic "screen state" (a Notepad Save-as moment) through the TypeSafe API
with the three judgments the F1 loop depends on:

  - select_element (Choice over code-built candidates + ``none_match``)
  - step_done     (Noul — has the save dialog appeared?)
  - blocker       (Choice: none | dialog | login | captcha | error)

Runs the request three times to get a latency distribution, then prints the last
response's model, usage, and a cost estimate.

Usage:  uv run python spikes/spike_jev.py
Needs:  TYPESAFE_API_KEY in .env (repo root) or the environment.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from typesafe_sdk import Choice, Noul, TypeSafeClient

PRICE_PER_MTOK_INPUT = 0.042  # USD, jev (vercel gateway listing, Sep 2026)

FIXTURE = {
    "goal": "Save the current document as 'notes.txt' in the Documents folder.",
    "window": {"app": "Notepad", "title": "Untitled - Notepad"},
    "candidates": [
        {"id": "e1", "role": "Button", "name": "File", "bounds": [10, 10, 60, 30]},
        {"id": "e2", "role": "Button", "name": "Save", "bounds": [80, 10, 60, 30]},
        {"id": "e3", "role": "MenuItem", "name": "Save as", "bounds": [80, 40, 120, 24]},
        {"id": "e4", "role": "Edit", "name": "Document text", "bounds": [10, 60, 900, 500]},
    ],
    "recent_actions": ["click e3 (File > Save as)"],
}

QUESTIONS = {
    "select_element": Choice(
        instructions=(
            "Which candidate element should be clicked next to advance the goal? "
            "Each candidate is an on-screen control."
        ),
        criteria={
            "e1": "File menu button",
            "e2": "Save button — saves the document",
            "e3": "Save as menu item — lets you choose filename/location",
            "e4": "Document text area",
            "none_match": "No candidate is the right thing to click",
        },
    ),
    "step_done": Noul(
        instructions=(
            "Does the window state show that a Save-as dialog for choosing the "
            "filename/location is open?"
        )
    ),
    "blocker": Choice(
        instructions="Is there a blocker preventing progress right now?",
        criteria={
            "none": "No blocker",
            "dialog": "An unexpected dialog is present",
            "login": "A login form is present",
            "captcha": "A captcha is present",
            "error": "An error message is shown",
        },
    ),
}


def main() -> None:
    if not os.environ.get("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY missing — put it in .env at the repo root")

    client = TypeSafeClient()
    try:
        models = client.models.list()
        items = getattr(models, "data", None)
        names = (
            [getattr(m, "id", m) for m in items]
            if isinstance(items, list)
            else str(models)[:160]
        )
        print(f"models: {names}")
    except Exception as exc:  # noqa: BLE001
        print(f"models.list failed: {exc!r}")

    latencies: list[float] = []
    resp = None
    for _ in range(3):
        t0 = time.perf_counter()
        resp = client.system_one(state=FIXTURE, questions=QUESTIONS)
        latencies.append((time.perf_counter() - t0) * 1000)

    assert resp is not None
    usage = resp.usage
    input_tokens = getattr(usage, "input_tokens", None)
    cost = (input_tokens or 0) * PRICE_PER_MTOK_INPUT / 1e6

    selected = resp.answers["select_element"]
    blocker = resp.answers["blocker"]
    print(
        json.dumps(
            {
                "model": resp.model,
                "request_id": resp.request_id,
                "latency_ms": {
                    "runs": [round(x, 1) for x in latencies],
                    "median": round(statistics.median(latencies), 1),
                },
                "usage": {
                    "input_tokens": input_tokens,
                    "output_tokens": getattr(usage, "output_tokens", None),
                    "billing_units": getattr(usage, "billing_units", None),
                },
                "cost_estimate_usd": round(cost, 7),
                "answers": {
                    "select_element": getattr(selected, "choice", None),
                    "select_element_confidence": getattr(selected, "confidence", None),
                    "select_element_probabilities": getattr(selected, "probabilities", None),
                    "step_done_noul": getattr(resp.answers["step_done"], "noul", None),
                    "blocker": getattr(blocker, "choice", None),
                },
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    main()
