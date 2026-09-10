"""Derived-state queries: entities missing an edge (#11).

Process state is never stored; it is derived. These are the questions an
orchestrator's sensors ask, and the answers stay the caller's to interpret.
"""

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


def _lab() -> None:
    """One specimen extracted, one split into an aliquot but never extracted, one waiting."""
    client.post("/subjects", json={"local_id": "SUBJ-1"})
    for local_id in ("SPEC-EXTRACTED", "SPEC-SPLIT", "SPEC-WAITING", "SPEC-ALIQUOT"):
        client.post("/specimens", json={"local_id": local_id, "subject": "SUBJ-1"})
    client.post("/links/derived-from", json={"from": "SPEC-ALIQUOT", "to": "SPEC-SPLIT"})
    client.post("/extracts", json={"local_id": "EXT-1", "specimen": "SPEC-EXTRACTED"})


def _names(**params: object) -> set[str]:
    r = client.get("/specimens", params=params)
    assert r.status_code == 200, r.text
    return {row["name"].rsplit("/", 1)[1] for row in r.json()}


def test_the_far_end_type_is_what_makes_the_question_right(env: dict[str, str]) -> None:
    """ "no incoming derived_from" and "no extract" are different questions: an aliquot is a
    Specimen derived from a Specimen, so it answers the first and not the
    second. SPEC-SPLIT is the case that separates them."""
    _lab()
    assert _names(without="incoming:derived_from") == {"SPEC-ALIQUOT", "SPEC-WAITING"}
    assert _names(without="incoming:derived_from:Extract") == {
        "SPEC-ALIQUOT",
        "SPEC-SPLIT",
        "SPEC-WAITING",
    }


def test_outgoing_direction_and_other_predicates(env: dict[str, str]) -> None:
    client.post("/subjects", json={"local_id": "SUBJ-1"})
    client.post("/specimens", json={"local_id": "SPEC-1", "subject": "SUBJ-1"})
    client.post("/specimens", json={"local_id": "SPEC-ORPHAN", "no_parent": True})
    # specimens with no outgoing derived_from: the parentless one
    assert _names(without="outgoing:derived_from") == {"SPEC-ORPHAN"}

    client.post("/contexts", json={"local_id": "COHORT-1"})
    client.post("/links/part-of", json={"from": "SPEC-1", "to": "COHORT-1"})
    assert _names(without="outgoing:part_of") == {"SPEC-ORPHAN"}


def test_retracted_edges_do_not_keep_an_entity_off_the_backlog(env: dict[str, str]) -> None:
    _lab()
    assert "SPEC-EXTRACTED" not in _names(without="incoming:derived_from:Extract")
    # withdraw the extract; the specimen is waiting again
    r = client.post("/extracts/EXT-1/retract", json={"reason": "wrong specimen", "cascade": True})
    assert r.status_code == 200, r.text
    assert "SPEC-EXTRACTED" in _names(without="incoming:derived_from:Extract")


def test_filters_compose_and_repeat(env: dict[str, str]) -> None:
    _lab()
    # both conditions must hold
    assert _names(without=["incoming:derived_from:Extract", "outgoing:part_of"]) == {
        "SPEC-ALIQUOT",
        "SPEC-SPLIT",
        "SPEC-WAITING",
    }
    # and it composes with the parent filter and pagination
    assert _names(subject="SUBJ-1", without="incoming:derived_from:Extract", limit=2) <= {
        "SPEC-ALIQUOT",
        "SPEC-SPLIT",
        "SPEC-WAITING",
    }


def test_bad_specs_are_errors(env: dict[str, str]) -> None:
    _lab()
    for spec in (
        "nonsense",
        "sideways:derived_from",
        "incoming:nope",
        "incoming:derived_from:Nope",
    ):
        r = client.get("/specimens", params={"without": spec})
        assert r.status_code == 400, spec


def test_cli_and_graphql(env: dict[str, str]) -> None:
    _lab()
    r = runner.invoke(
        cli_app,
        ["specimen", "list", "--without", "incoming:derived_from:Extract", "--output", "json"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    assert {row["name"].rsplit("/", 1)[1] for row in json.loads(r.output)} == {
        "SPEC-ALIQUOT",
        "SPEC-SPLIT",
        "SPEC-WAITING",
    }
    r = runner.invoke(cli_app, ["specimen", "list", "--without", "bogus"], env=env)
    assert r.exit_code == 1
    assert "DIRECTION:PREDICATE" in r.output

    body = client.post(
        "/graphql",
        json={"query": '{ specimens(without: ["incoming:derived_from:Extract"]) { name } }'},
    ).json()
    assert {n["name"].rsplit("/", 1)[1] for n in body["data"]["specimens"]} == {
        "SPEC-ALIQUOT",
        "SPEC-SPLIT",
        "SPEC-WAITING",
    }
    bad = client.post(
        "/graphql", json={"query": '{ specimens(without: ["bogus"]) { name } }'}
    ).json()
    assert "errors" in bad
