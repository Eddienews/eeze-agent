"""Spec-writer vocabulary for the files vertical (kept in sync with FilesSpec by tests)."""

from __future__ import annotations


def describe_files_vocab() -> str:
    return "\n".join([
        "FILES SPEC — one JSON object with fields:",
        "- name: lowercase slug (letters/digits/hyphens)",
        "- folder: the EXACT folder path given to you (never another folder)",
        "- op: one of rename | organize | duplicates",
        '- include: "images" (default) | "videos" | "all" | a list like [".jpg", ".png"]',
        "RENAME (op=rename):",
        "- pattern: the new name WITHOUT extension, with tokens: {n} counter, {n:03} counter padded",
        "  to 3 digits (001), {date} YYYY-MM-DD, {time} HHMMSS, {name} the current name.",
        "  It must contain {n} (or {name}). The original extension is always kept; never write {ext}.",
        "- start: first counter value (default 1)",
        '- order: "name" (natural order, default) | "taken" (date the photo was taken) | "modified"',
        "ORGANIZE (op=organize): moves files into sub-folders of the same folder:",
        '- by: "month" (YYYY-MM, default) | "day" | "year" | "type" (Images/Videos/Other)',
        "DUPLICATES (op=duplicates): only reports identical files; never deletes.",
        "EXAMPLES:",
        '- "rename img001, img002 to park001, park002" -> {"op": "rename", "pattern": "park{n:03}", "start": 1}',
        '- "renomeie as fotos para viagem_1, viagem_2 pela data" -> '
        '{"op": "rename", "pattern": "viagem_{n}", "order": "taken"}',
        '- "organize by month" / "organize por mês" -> {"op": "organize", "by": "month"}',
        "CONSTRAINTS: no other ops or fields; nothing is ever deleted or overwritten; the user",
        "sees a preview and approves before anything changes. The goal may be in English or Portuguese.",
    ])
