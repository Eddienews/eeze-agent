"""EN/PT: every screen string goes through the translator, and both languages are complete.

Guards the dashboard (ui/src) without Node: parses lib/i18n.tsx and scans the .tsx files for
English text that bypasses t(). Add a deliberate exception to ALLOWED with a reason.
"""

from __future__ import annotations

import re
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui" / "src"
KEY = re.compile(r'^\s*"([A-Za-z0-9_.]+)":\s*(?:\n\s*)?"((?:[^"\\]|\\.)*)"', re.M)

# Not user-facing prose: marketing pages (demo build only), brand/product names, example values.
SKIP_FILES = {"routes/index.tsx", "routes/download.tsx", "components/contact-modal.tsx", "lib/i18n.tsx"}
ALLOWED = {
    "Eeze Agents",                      # brand
    "Pro", "Python", "Info", "Debug", "Trace",  # plan/tech names, log levels
    "default", "generalist", "invoices", "ALL",  # ids / slugs / mailbox syntax
    "you@example.com", "you@gmail.com", "xxxx xxxx xxxx xxxx", ".env",
    "tasks/notepad-gated-demo.yaml", "%USERPROFILE%\\.eeze\\api.token",
    "go.xero.com/reconcile", "Suggested match",  # mock of a third-party app screen
}


def _dicts() -> tuple[dict[str, str], dict[str, str]]:
    text = (UI / "lib" / "i18n.tsx").read_text(encoding="utf-8")
    en_src = text[text.index("const en = {"):text.index("export type MessageKey")]
    pt_src = text[text.index("const pt:"):text.index("const DICTS")]
    return dict(KEY.findall(en_src)), dict(KEY.findall(pt_src))


def test_every_english_string_has_a_portuguese_one():
    en, pt = _dicts()
    assert len(en) > 700
    missing = sorted(set(en) - set(pt))
    assert not missing, f"missing Portuguese for: {missing[:20]}"
    assert not sorted(set(pt) - set(en)), "Portuguese keys with no English source"


def test_placeholders_match_between_languages():
    en, pt = _dicts()
    for key, text in en.items():
        a = sorted(re.findall(r"\{(\w+)\}", text))
        b = sorted(re.findall(r"\{(\w+)\}", pt.get(key, text)))
        assert a == b, f"{key}: {a} vs {b}"


def test_portuguese_is_actually_translated():
    en, pt = _dicts()
    same = [k for k, v in pt.items() if v == en[k] and re.search(r"[a-z]{4,}\s+[a-z]{3,}", v)]
    assert len(same) < 10, f"PT identical to EN (untranslated?): {same[:20]}"


JSX_TEXT = re.compile(r">\s*([^<>{}]*[A-Za-z]{2,}[^<>{}]*?)\s*<")
ATTR = re.compile(r'\b(?:placeholder|title|aria-label|label|description|alt)="([^"]*[A-Za-z]{2,}[^"]*)"')
CALL = re.compile(r'\b(?:toast(?:\.\w+)?|setError|setMessage|setNote)\(\s*["`]([^"`]*[A-Za-z]{3,}[^"`]*)["`]')
CODE = re.compile(r"[;=()\[\]|&]|\?\s|=>|\bconst\b|\breturn\b")


def _hardcoded(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    hits = []
    for rx in (JSX_TEXT, ATTR, CALL):
        for match in rx.finditer(text):
            s = match.group(1).strip()
            if not s or s in ALLOWED or re.fullmatch(r"[\W\d_]*", s):
                continue
            if rx is JSX_TEXT and CODE.search(s):
                continue
            line = text.count("\n", 0, match.start()) + 1
            hits.append(f"{path.relative_to(UI).as_posix()}:{line}: {s[:60]}")
    return hits


def test_no_hardcoded_english_on_screens():
    hits = []
    for path in sorted(UI.rglob("*.tsx")):
        rel = path.relative_to(UI).as_posix()
        if rel in SKIP_FILES or rel.startswith("components/ui/"):
            continue
        hits += _hardcoded(path)
    assert not hits, "text shown without t() — add a key to lib/i18n.tsx:\n" + "\n".join(hits)
