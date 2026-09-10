"""Shared test configuration.

Every test that talks to the HTTP interfaces runs with authentication off. The server
refuses to serve a deployment that has neither configured tokens nor explicitly opted out
(src/openngs/auth.py), so the opt-out has to be stated somewhere; stating it once here
keeps it out of every individual fixture. tests/test_auth.py overrides it to exercise the
authenticated paths.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _auth_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENNGS_AUTH_MODE", "none")
    monkeypatch.delenv("OPENNGS_AUTH_TOKENS", raising=False)
    monkeypatch.delenv("OPENNGS_AUTH_TOKENS_FILE", raising=False)
    monkeypatch.delenv("OPENNGS_PRINCIPAL", raising=False)
