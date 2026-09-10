"""Adding an external identifier to an entity that already exists (#6)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from openngs.api import app
from openngs.cli import app as cli_app

client = TestClient(app)
runner = CliRunner()


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    settings = {
        "OPENNGS_ORG": "acme-genomics",
        "OPENNGS_NAMESPACE": "core-lab",
        "OPENNGS_DB_URL": f"sqlite:///{db_path}",
    }
    for key, value in settings.items():
        monkeypatch.setenv(key, value)
    return settings


def test_accessions_arriving_later_are_added_not_corrected(env: dict[str, str]) -> None:
    """The metagenomics case: a specimen is submitted to ENA and the accessions come back
    weeks after it was registered."""
    client.post("/subjects", json={"local_id": "SITE-01"})
    client.post(
        "/specimens",
        json={"local_id": "LK-001", "subject": "SITE-01", "xrefs": ["barcode:BOT-0417"]},
    )

    r = client.post(
        "/specimens/LK-001/xrefs",
        json={"xrefs": ["biosample:SAMN12345678", "ena:ERS1234567"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["xrefs"] == [
        "barcode:BOT-0417",
        "biosample:SAMN12345678",
        "ena:ERS1234567",
    ]

    # one event per xref, and none of them is a correction
    events = client.get("/specimens/LK-001", params={"events": "true"}).json()["events"]
    added = [e for e in events if e["type"] == "entity_xref_added"]
    assert len(added) == 2
    assert all(e["supersedes"] is None for e in added)
    assert {e["payload"]["xref"] for e in added} == {
        "biosample:SAMN12345678",
        "ena:ERS1234567",
    }


def test_duplicate_xref_is_refused(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "S1", "xrefs": ["a:1"]})
    r = client.post("/subjects/S1/xrefs", json={"xrefs": ["a:1"]})
    assert r.status_code == 400
    assert "already has xref" in r.json()["detail"]
    # and nothing was written
    assert client.get("/subjects/S1").json()["xrefs"] == ["a:1"]


def test_xref_request_shape(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "S1"})
    assert client.post("/subjects/S1/xrefs", json={"xrefs": []}).status_code == 422
    assert client.post("/subjects/NOPE/xrefs", json={"xrefs": ["a:1"]}).status_code == 404


def test_replay_reproduces_added_xrefs(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "S1", "xrefs": ["a:1"]})
    client.post("/subjects/S1/xrefs", json={"xrefs": ["b:2"]})
    before = client.get("/subjects/S1").json()["xrefs"]
    assert client.post("/events/replay", params={"yes": "true"}).status_code == 200
    assert client.get("/subjects/S1").json()["xrefs"] == before == ["a:1", "b:2"]


def test_correction_still_replaces_the_whole_set(env: dict[str, str]) -> None:
    """Adding and correcting are different operations: one appends a name, the other says
    the previous content was wrong."""
    client.post("/subjects", json={"local_id": "S1", "xrefs": ["a:1"]})
    client.post("/subjects/S1/xrefs", json={"xrefs": ["b:2"]})
    client.post("/subjects/S1/correct", json={"xrefs": ["c:3"], "reason": "rescanned"})
    assert client.get("/subjects/S1").json()["xrefs"] == ["c:3"]
    # ...and the removal is recorded as a correction, with its reason
    events = client.get("/subjects/S1", params={"events": "true"}).json()["events"]
    corrected = [e for e in events if e["type"] == "entity_corrected"]
    assert [e["supersede_reason"] for e in corrected] == ["rescanned"]


def test_cli_xref_add(env: dict[str, str]) -> None:
    runner.invoke(cli_app, ["subject", "create", "SITE-01"], env=env)
    r = runner.invoke(
        cli_app, ["subject", "xref", "add", "SITE-01", "envo:00000020", "gaz:00002462"], env=env
    )
    assert r.exit_code == 0, r.output
    assert "added 2 xref(s)" in r.output

    r = runner.invoke(cli_app, ["subject", "show", "SITE-01", "--output", "json"], env=env)
    assert json.loads(r.output)["xrefs"] == ["envo:00000020", "gaz:00002462"]

    r = runner.invoke(cli_app, ["subject", "xref", "add", "SITE-01", "envo:00000020"], env=env)
    assert r.exit_code == 1
    assert "already has xref" in r.output


def test_cli_datapoint_xref_add(env: dict[str, str]) -> None:
    runner.invoke(cli_app, ["subject", "create", "S1"], env=env)
    runner.invoke(
        cli_app,
        [
            "datapoint",
            "create",
            "DP-1",
            "--for",
            "S1",
            "--type",
            "x:m",
            "--kind",
            "number",
            "--value",
            "1",
        ],
        env=env,
    )
    r = runner.invoke(cli_app, ["datapoint", "xref", "add", "DP-1", "lims:42"], env=env)
    assert r.exit_code == 0, r.output
    body = client.post("/graphql", json={"query": '{ datapoint(ref: "DP-1") { xrefs } }'}).json()
    assert body["data"]["datapoint"]["xrefs"] == ["lims:42"]
