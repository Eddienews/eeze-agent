# Contributing

Thanks for helping! Eeze Agent is young, so small focused pull requests work best.

1. `uv sync` then `uv run pytest` — all tests should pass on Windows.
2. Dashboard changes: `cd ui && npm ci && npx tsc --noEmit -p .`
3. User-facing text in the dashboard lives in `ui/src/lib/i18n.tsx` — add both the English
   and the Portuguese (`pt`) string.
4. Never commit `.env`, anything from `~/.eeze/`, or personal paths/emails.
5. Anything that changes or deletes user files must go through an approval with a preview
   and an undo — see how the Files vertical does it (`src/eeze_agent/verticals/files`).

By contributing you agree that your contribution is licensed under the Apache License 2.0.
