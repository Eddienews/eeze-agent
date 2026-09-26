"""Test isolation defaults.

A test must never read (or write) the operator's real ``~/.eeze`` state. Two sharp edges:

1. **The provider secret store**: a brain built without an explicit provider resolves through
   ``core.providers.resolve_provider`` → the real ``secrets.json``, so a suite that passes on an
   empty machine would start failing the day a real key is stored. Point it at a throwaway file
   (``EEZE_SECRETS``); tests that name their own home/path still win over it.
2. **The process environment**: code under test loads the real repo ``.env`` into ``os.environ``
   (``brains/jev.py`` does it whenever a Jev brain is built). Without a snapshot/restore, one test
   that runs the real loop leaks ``EEZE_BRAIN=codex`` and real IMAP credentials into every test
   after it — which flips unrelated checks (found when F7's run test broke the pilot/router tests).
   The environment is therefore restored verbatim after every test.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_env():
    snapshot = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(snapshot)


@pytest.fixture(autouse=True)
def _isolated_secret_store(tmp_path, monkeypatch):
    monkeypatch.setenv("EEZE_SECRETS", str(tmp_path / "secrets.json"))


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Retries back off in production (1 s, 2 s, 4 s…); tests must not sleep."""
    monkeypatch.setenv("EEZE_RETRY_BACKOFF_S", "0")


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path_factory, monkeypatch):
    """Never touch the operator's ~/.eeze/eeze.db (journals now feed the spend ledger).

    Tests that need a specific database still set EEZE_DB themselves; that wins.
    """
    monkeypatch.setenv("EEZE_DB", str(tmp_path_factory.mktemp("db") / "eeze.db"))
