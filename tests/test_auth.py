"""Bearer-token authentication, coarse authorization, and recorded_by (#5)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openngs.api import app
from openngs.auth import AuthConfigError, Principal, cli_principal, load_tokens
from openngs.cli import app as cli_app

client = TestClient(app)
runner = CliRunner()

WRITER = "tok-writer"
READER = "tok-reader"
TOKENS = json.dumps(
    {
        WRITER: "airflow",
        READER: {"principal": "grafana", "role": "read"},
        "tok-shorthand": "alice",
    }
)


@pytest.fixture
def db_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    monkeypatch.setenv("OPENNGS_ORG", "acme-genomics")
    monkeypatch.setenv("OPENNGS_NAMESPACE", "core-lab")
    monkeypatch.setenv("OPENNGS_DB_URL", f"sqlite:///{db_path}")


@pytest.fixture
def secured(db_only: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENNGS_AUTH_MODE", raising=False)
    monkeypatch.setenv("OPENNGS_AUTH_TOKENS", TOKENS)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- configuration ----------------------------------------------------------------------------


def test_a_server_with_no_auth_configured_refuses_to_serve(
    db_only: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not a 401: the caller did nothing wrong. The deployment has not chosen."""
    monkeypatch.delenv("OPENNGS_AUTH_MODE", raising=False)
    r = client.get("/subjects")
    assert r.status_code == 500
    assert "OPENNGS_AUTH_MODE=none" in r.json()["detail"]


def test_disabling_auth_must_be_explicit(db_only: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENNGS_AUTH_MODE", "none")
    assert client.get("/subjects").status_code == 200


def test_tokens_from_a_file(db_only: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "tokens.json"
    path.write_text(TOKENS)
    monkeypatch.delenv("OPENNGS_AUTH_MODE", raising=False)
    monkeypatch.setenv("OPENNGS_AUTH_TOKENS_FILE", str(path))
    assert client.get("/subjects", headers=_auth(WRITER)).status_code == 200
    assert client.get("/subjects").status_code == 401


def test_malformed_configuration_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENNGS_AUTH_MODE", raising=False)
    with pytest.raises(AuthConfigError, match="not valid JSON"):
        load_tokens({"OPENNGS_AUTH_TOKENS": "{oops"})
    with pytest.raises(AuthConfigError, match="empty"):
        load_tokens({"OPENNGS_AUTH_TOKENS": "{}"})
    with pytest.raises(AuthConfigError, match="read.*write"):
        load_tokens({"OPENNGS_AUTH_TOKENS": '{"t": {"principal": "x", "role": "admin"}}'})
    with pytest.raises(AuthConfigError, match="cannot be read"):
        load_tokens({"OPENNGS_AUTH_TOKENS_FILE": "/nope/tokens.json"})
    assert load_tokens({"OPENNGS_AUTH_TOKENS": '{"t": "alice"}'})["t"] == Principal("alice", True)


# --- enforcement -------------------------------------------------------------------------------


def test_a_token_is_required(secured: None) -> None:
    r = client.get("/subjects")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    assert client.get("/subjects", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/subjects", headers=_auth("wrong")).status_code == 401
    assert client.get("/subjects", headers=_auth(WRITER)).status_code == 200


def test_a_read_only_token_cannot_write(secured: None) -> None:
    assert client.get("/subjects", headers=_auth(READER)).status_code == 200
    r = client.post("/subjects", json={"local_id": "S1"}, headers=_auth(READER))
    assert r.status_code == 403
    assert "read-only" in r.json()["detail"]
    assert (
        client.post("/subjects", json={"local_id": "S1"}, headers=_auth(WRITER)).status_code == 200
    )


def test_graphql_needs_a_token_too(secured: None) -> None:
    """Reading the whole graph in one query is still reading it."""
    query = {"query": "{ subjects { name } }"}
    assert client.post("/graphql", json=query).status_code == 401
    r = client.post("/graphql", json=query, headers=_auth(READER))
    assert r.status_code == 200, r.text
    assert "errors" not in r.json()


def test_every_route_is_covered_including_health(secured: None) -> None:
    """Coverage comes from the shared dependency, not from remembering per route."""
    for method, path in (
        ("get", "/events"),
        ("get", "/facets"),
        ("get", "/facet-schemas"),
        ("get", "/datapoints"),
        ("get", "/specimens"),
    ):
        assert getattr(client, method)(path).status_code == 401, path
    # /health deliberately needs no database, and no credential either
    assert client.get("/health").status_code == 200


# --- recorded_by --------------------------------------------------------------------------------


def test_events_record_the_principal_behind_them(secured: None) -> None:
    client.post("/subjects", json={"local_id": "S1"}, headers=_auth(WRITER))
    events = client.get("/events", headers=_auth(READER)).json()
    assert [e["recorded_by"] for e in events] == ["airflow"]
    assert [e["source"] for e in events] == ["openngs-api"]  # who vs. which program


def test_anonymous_when_auth_is_off(db_only: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENNGS_AUTH_MODE", "none")
    client.post("/subjects", json={"local_id": "S1"})
    assert client.get("/events").json()[0]["recorded_by"] == "anonymous"


def test_cli_records_its_own_identity(db_only: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENNGS_AUTH_MODE", "none")
    monkeypatch.setenv("OPENNGS_PRINCIPAL", "jdoe")
    env = {
        "OPENNGS_ORG": "acme-genomics",
        "OPENNGS_NAMESPACE": "core-lab",
        "OPENNGS_DB_URL": __import__("os").environ["OPENNGS_DB_URL"],
        "OPENNGS_PRINCIPAL": "jdoe",
        "OPENNGS_AUTH_MODE": "none",
    }
    r = runner.invoke(cli_app, ["subject", "create", "S1"], env=env)
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli_app, ["event", "list", "--output", "json"], env=env)
    events = json.loads(r.output)
    assert [e["recorded_by"] for e in events] == ["jdoe"]
    assert [e["source"] for e in events] == ["openngs-cli"]


def test_cli_principal_falls_back_to_the_os_user() -> None:
    assert cli_principal({"OPENNGS_PRINCIPAL": "configured"}) == "configured"
    assert cli_principal({}) != ""
