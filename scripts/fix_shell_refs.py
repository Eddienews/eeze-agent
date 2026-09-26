"""Fix stale /assets/* references in the SPA shell/index after a build.

Observed with TanStack Start SPA builds: the prerendered shell can reference a
client-entry hash from a previous generation (stale manifest cache), producing a
dead ``<script src>``. This rewrites every ``/assets/<prefix>-<hash>.<ext>`` whose
file does not exist to the actual (newest) built file with that prefix.

Usage:  python scripts/fix_shell_refs.py ui/dist-site/client
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REF_RE = re.compile(r"/assets/([A-Za-z0-9_.@-]+?)-([A-Za-z0-9_-]+)\.(js|css)")

# The TanStack prerender snapshot drops these (the client-side head has them),
# so crawlers reading raw HTML would miss the link preview image. Inject them.
REQUIRED_METAS = (
    ('<meta property="og:image" content="https://eeze.app/assets/eeze.png"/>', "og:image"),
    ('<meta name="twitter:image" content="https://eeze.app/assets/eeze.png"/>', "twitter:image"),
)


def ensure_metas(page: Path, text: str) -> str:
    for tag, key in REQUIRED_METAS:
        if key not in text:
            text = text.replace("</head>", tag + "</head>", 1)
            print(f"{page.name}: injected {key}")
    return text


# Browsers cache favicons per-URL almost indefinitely, and the prerendered shell
# can be stale, so version the icon links here (deterministic post-build).
ICON_VERSION = "v=2"


def version_icons(page: Path, text: str) -> str:
    changed = False
    for name in ("/favicon.ico", "/favicon.svg", "/apple-touch-icon.png"):
        old = f'href="{name}"'
        new = f'href="{name}?{ICON_VERSION}"'
        if old in text:
            text = text.replace(old, new)
            changed = True
    if changed:
        print(f"{page.name}: icon links -> ?{ICON_VERSION}")
    return text


def fix_dir(dist: Path) -> int:
    assets = dist / "assets"
    if not assets.is_dir():
        print(f"no assets dir: {assets}")
        return 1
    changed = 0
    for fname in ("_shell.html", "index.html"):
        page = dist / fname
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8")

        def repl(match: re.Match[str], fname: str = fname) -> str:
            prefix, digest, ext = match.group(1), match.group(2), match.group(3)
            if (assets / f"{prefix}-{digest}.{ext}").exists():
                return match.group(0)
            candidates = sorted(
                assets.glob(f"{prefix}-*.{ext}"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not candidates:
                print(f"WARN: no candidate for {match.group(0)}")
                return match.group(0)
            print(f"{fname}: {prefix}-{digest}.{ext} -> {candidates[0].name}")
            return f"/assets/{candidates[0].name}"

        fixed = REF_RE.sub(repl, text)
        fixed = ensure_metas(page, fixed)
        fixed = version_icons(page, fixed)
        if fixed != text:
            page.write_text(fixed, encoding="utf-8")
            print(f"updated {fname}")
            changed += 1
        else:
            print(f"{fname}: refs ok")
    return 0 if changed >= 0 else 1


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "ui/dist/client")
    raise SystemExit(fix_dir(target))
