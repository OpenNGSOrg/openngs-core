"""Creating a record with no parent edge: controls, and unknown provenance (#7)."""

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


def test_extraction_blank_is_a_real_extract_with_no_specimen(env: dict[str, str]) -> None:
    """The metagenomics case: a negative control shares a kit lot with real samples, which
    is the whole point of tracking it, but it came from no specimen."""
    runner.invoke(cli_app, ["reagent", "create", "KIT-LOT-A1"], env=env)
    runner.invoke(cli_app, ["subject", "create", "SITE-01"], env=env)
    runner.invoke(cli_app, ["specimen", "create", "LK-001", "--subject", "SITE-01"], env=env)
    runner.invoke(cli_app, ["extract", "create", "EXT-001", "--specimen", "LK-001"], env=env)

    r = runner.invoke(cli_app, ["extract", "create", "BLANK-01", "--no-parent"], env=env)
    assert r.exit_code == 0, r.output

    for extract in ("EXT-001", "BLANK-01"):
        assert (
            runner.invoke(
                cli_app, ["link", "used", "--from", extract, "--to", "KIT-LOT-A1"], env=env
            ).exit_code
            == 0
        )

    # the blank has no derived_from, only the reagent it used
    body = json.loads(
        runner.invoke(cli_app, ["extract", "show", "BLANK-01", "--output", "json"], env=env).output
    )
    assert [e["predicate"] for e in body["outgoing"]] == ["used"]

    # and the contamination question reaches both
    body = json.loads(
        runner.invoke(
            cli_app, ["reagent", "show", "KIT-LOT-A1", "--output", "json"], env=env
        ).output
    )
    assert {e["other_name"].rsplit("/", 1)[1] for e in body["incoming"]} == {
        "EXT-001",
        "BLANK-01",
    }


def test_a_forgotten_parent_is_still_an_error(env: dict[str, str]) -> None:
    """--no-parent has to be explicit, or a typo silently orphans a record."""
    r = runner.invoke(cli_app, ["extract", "create", "EXT-001"], env=env)
    assert r.exit_code == 1
    assert "--specimen is required" in r.output
    assert "--no-parent" in r.output

    r = runner.invoke(
        cli_app, ["extract", "create", "EXT-001", "--specimen", "X", "--no-parent"], env=env
    )
    assert r.exit_code == 1
    assert "not both" in r.output


def test_no_parent_on_every_entity_that_has_one(env: dict[str, str]) -> None:
    for noun, local_id in (
        ("specimen", "MOCK-01"),  # a mock community, from no subject
        ("extract", "BLANK-01"),  # an extraction blank
        ("library", "NTC-01"),  # a no-template control
        ("data-file", "legacy.bam"),  # a file of unknown provenance
        ("data-file-set", "legacy/"),
    ):
        r = runner.invoke(cli_app, [noun, "create", local_id, "--no-parent"], env=env)
        assert r.exit_code == 0, f"{noun}: {r.output}"
        body = json.loads(
            runner.invoke(cli_app, [noun, "show", local_id, "--output", "json"], env=env).output
        )
        assert body["outgoing"] == []


def test_rest_requires_the_opt_out_explicitly(env: dict[str, str]) -> None:
    assert (
        client.post("/extracts", json={"local_id": "BLANK-01", "no_parent": True}).status_code
        == 200
    )
    assert client.get("/extracts/BLANK-01").json()["outgoing"] == []

    r = client.post("/extracts", json={"local_id": "EXT-9"})
    assert r.status_code == 422
    assert "no_parent" in r.json()["detail"]

    r = client.post("/extracts", json={"local_id": "EXT-9", "specimen": "X", "no_parent": True})
    assert r.status_code == 422
    assert "not both" in r.json()["detail"]


def test_the_role_of_a_control_is_a_facet_not_a_core_field(env: dict[str, str]) -> None:
    """Nothing in core says "this is a blank"; that is the lab's own facet."""
    fixture = str(Path(__file__).parent / "fixtures" / "qc_metrics.schema.json")
    client.post("/extracts", json={"local_id": "BLANK-01", "no_parent": True})
    r = client.post(
        "/facets",
        json={
            "to": "BLANK-01",
            "schema_url": fixture,
            "type": "QcMetricsFacet",
            "producer": "acme-lims/1.0",
            "data": {"metric_name": "acme:control_role", "metric_value": 1.0},
        },
    )
    assert r.status_code == 200, r.text
    assert len(client.get("/facets", params={"to": "BLANK-01"}).json()) == 1


def test_replay_reproduces_parentless_records(env: dict[str, str]) -> None:
    client.post("/extracts", json={"local_id": "BLANK-01", "no_parent": True})
    client.post("/subjects", json={"local_id": "SITE-01"})
    client.post("/specimens", json={"local_id": "LK-001", "subject": "SITE-01"})
    before = client.get("/extracts").json()
    assert client.post("/events/replay", params={"yes": "true"}).status_code == 200
    assert client.get("/extracts").json() == before
    assert client.get("/extracts/BLANK-01").json()["outgoing"] == []
