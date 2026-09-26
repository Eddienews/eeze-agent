"""Judgment/run eval report from a runset journal.

Usage:  uv run python scripts/judgment_eval.py artifacts/runs/<runset>
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def load(journal_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return round(s[int(p * (len(s) - 1))], 1)


def main() -> None:
    runset = Path(sys.argv[1])
    ev = load(runset / "journal.jsonl")

    runs = [e for e in ev if e.get("kind") == "run_end"]
    steps = [e for e in ev if e.get("kind") == "step_end"]
    judgments = [e for e in ev if e.get("kind") == "judgment"]
    sels = [j for j in judgments if j.get("judgment_kind") == "select_element"]
    vers = [j for j in judgments if j.get("judgment_kind") == "verify"]
    rungs = [e for e in ev if e.get("kind") == "write_rung"]

    print(f"=== runset {runset.name} ===")
    ok = sum(1 for r in runs if r.get("ok"))
    cycles = [r["cycle_ms"] for r in runs if r.get("cycle_ms")]
    print(
        f"runs: {ok}/{len(runs)} ok; cycle p50 {pct(cycles, 0.5)} ms, "
        f"p95 {pct(cycles, 0.95)} ms"
    )

    per_step: dict[str, list[float]] = defaultdict(list)
    for s in steps:
        per_step[s.get("step_id")].append(s.get("ms") or 0)
    print("\nstep durations (p50 ms):")
    for sid, vals in per_step.items():
        print(f"  {sid:<16} n={len(vals):<3} p50={pct(vals, 0.5)}")

    print(f"\nselections: n={len(sels)}")
    confs = [s.get("confidence") for s in sels if s.get("confidence") is not None]
    if confs:
        print(
            f"  confidence: min={min(confs):.2f} p25={pct(confs, 0.25)} "
            f"median={statistics.median(confs):.2f}"
        )
    print(f"  none_match answers: {sum(1 for s in sels if s.get('answer') == 'none_match')}")
    print(f"  answers: {Counter(s.get('answer') for s in sels).most_common(8)}")

    print(f"\nverifies: n={len(vers)}")
    nouls = [v.get("noul") for v in vers if v.get("noul") is not None]
    if nouls:
        print(f"  noul: min={min(nouls):.2f} median={statistics.median(nouls):.2f}")

    agree, disagree = 0, 0
    for s in steps:
        reason = s.get("verify") or ""
        if "code:" in reason and "jev:" in reason:
            code_ok = "-> True" in reason.split("jev:")[0]
            jev_ok = "-> True" in reason.split("jev:")[-1]
            if code_ok == jev_ok:
                agree += 1
            else:
                disagree += 1
    print(f"\ncode-vs-jev agreement on verified steps: {agree} agree / {disagree} disagree")

    print("\nwrite rungs (successful):")
    for rung, c in Counter(r.get("rung") for r in rungs if r.get("result") == "ok").most_common():
        print(f"  {rung}: {c}")
    attempts = Counter((s.get("step_id"), s.get("attempts")) for s in steps)
    retried = {k: v for k, v in attempts.items() if k[1] and k[1] > 1}
    print(f"  steps needing retries: {len(retried)} {dict(list(retried.items())[:8])}")

    ms = [j.get("ms") for j in judgments if j.get("ms")]
    toks = sum(int(j.get("tokens") or 0) for j in judgments)
    print(
        f"\njev: calls={len(judgments)} p50={pct(ms, 0.5)} ms p95={pct(ms, 0.95)} ms; "
        f"tokens={toks}; cost≈${toks * 0.042 / 1e6:.6f}"
    )


if __name__ == "__main__":
    main()
