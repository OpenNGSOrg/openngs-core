"""End-to-end CLI tests for corrections and retractions."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openngs.cli import app

runner = CliRunner()
FIXTURE_SCHEMA = str(Path(__file__).parent / "fixtures" / "qc_metrics.schema.json")


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    return {
        "OPENNGS_ORG": "acme-genomics",
        "OPENNGS_NAMESPACE": "core-lab",
        "OPENNGS_DB_URL": f"sqlite:///{db_path}",
    }


def _run(env: dict[str, str], *args: str) -> str:
    result = runner.invoke(app, list(args), env=env)
    assert result.exit_code == 0, result.output
    return result.output


def _fails(env: dict[str, str], *args: str) -> str:
    result = runner.invoke(app, list(args), env=env)
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit)
    return result.output


# --- correcting -----------------------------------------------------------------------------


def test_correct_entity_local_id_frees_the_old_name(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "SUBJ-001", "--xref", "barcode:A")
    _run(env, "subject", "correct", "SUBJ-001", "--local-id", "SUBJ-999", "--reason", "mislabelled")

    assert "no entity found" in _fails(env, "subject", "show", "SUBJ-001")
    shown = _run(env, "subject", "show", "SUBJ-999", "--output", "json")
    body = json.loads(shown)
    assert body["name"].endswith("/SUBJ-999")
    assert body["xrefs"] == ["barcode:A"]  # untouched fields survive a correction
    assert "retracted_by_event" not in body  # a correction is not a retraction

    # the old local_id is free for a new record
    _run(env, "subject", "create", "SUBJ-001")


def test_correct_entity_replaces_xrefs_wholesale(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "SUBJ-001", "--xref", "barcode:A", "--xref", "barcode:B")
    _run(env, "subject", "correct", "SUBJ-001", "--xref", "barcode:C", "--reason", "rescanned")
    body = json.loads(_run(env, "subject", "show", "SUBJ-001", "--output", "json"))
    assert body["xrefs"] == ["barcode:C"]

    _run(env, "subject", "correct", "SUBJ-001", "--clear-xrefs", "--reason", "not ours")
    assert json.loads(_run(env, "subject", "show", "SUBJ-001", "--output", "json"))["xrefs"] == []


def test_correct_requires_a_reason_and_a_change(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "SUBJ-001")
    result = runner.invoke(app, ["subject", "correct", "SUBJ-001", "--local-id", "X"], env=env)
    assert result.exit_code != 0  # --reason is a required option
    assert "nothing to correct" in _fails(env, "subject", "correct", "SUBJ-001", "--reason", "x")


def test_correct_datapoint_value(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "SUBJ-001")
    _run(
        env,
        "datapoint",
        "create",
        "DP-1",
        "--for",
        "SUBJ-001",
        "--type",
        "openngs-dp:percent_duplication",
        "--kind",
        "number",
        "--value",
        "12.3",
    )
    _run(env, "datapoint", "correct", "DP-1", "--value", "14.7", "--reason", "re-measured")
    body = json.loads(_run(env, "datapoint", "show", "DP-1", "--output", "json"))
    assert body["value_number"] == 14.7
    assert body["value"] == 14.7

    # changing how the value parses requires the value too
    assert "pass --value" in _fails(
        env, "datapoint", "correct", "DP-1", "--kind", "text", "--reason", "x"
    )


def test_correct_facet_data_keeps_the_facet_id(env: dict[str, str]) -> None:
    _run(env, "sequencing-run", "create", "RUN-001")
    _run(env, "data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001")
    facet_id = _run(
        env,
        "facet",
        "attach",
        "--to",
        "R1.fastq.gz",
        "--schema-url",
        FIXTURE_SCHEMA,
        "--type",
        "QcMetricsFacet",
        "--producer",
        "fastqc/0.12.1",
        "--data",
        '{"metric_name":"openngs-dp:percent_duplication","metric_value":12.3}',
    ).strip()

    _run(
        env,
        "facet",
        "correct",
        facet_id,
        "--reason",
        "re-ran fastqc",
        "--data",
        '{"metric_name":"openngs-dp:percent_duplication","metric_value":14.7}',
    )
    body = json.loads(_run(env, "facet", "show", facet_id, "--output", "json"))
    assert body["facet_id"] == facet_id
    assert body["data"]["metric_value"] == 14.7

    # corrected data still has to satisfy the instance's own schema
    assert "does not validate" in _fails(
        env, "facet", "correct", facet_id, "--reason", "bad", "--data", '{"tool":"fastqc"}'
    )


# --- retracting -----------------------------------------------------------------------------


def test_retract_edge_and_reassert_it(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "SUBJ-001")
    _run(env, "context", "create", "COHORT-001")
    edge_id = _run(env, "link", "part-of", "--from", "SUBJ-001", "--to", "COHORT-001").strip()

    _run(env, "link", "retract", edge_id, "--reason", "wrong cohort")
    body = json.loads(_run(env, "subject", "show", "SUBJ-001", "--output", "json"))
    assert body["outgoing"] == []

    # the same relationship can be asserted again once withdrawn
    _run(env, "link", "part-of", "--from", "SUBJ-001", "--to", "COHORT-001")
    body = json.loads(_run(env, "subject", "show", "SUBJ-001", "--output", "json"))
    assert [e["predicate"] for e in body["outgoing"]] == ["part_of"]

    assert "no live edge" in _fails(env, "link", "retract", edge_id, "--reason", "again")


def test_retract_entity_refuses_live_edges_then_cascades(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "SUBJ-001")
    _run(env, "specimen", "create", "SPEC-001", "--subject", "SUBJ-001")

    out = _fails(env, "subject", "retract", "SUBJ-001", "--reason", "duplicate")
    assert "still has 1 live edge" in out
    assert "--cascade" in out

    out = _run(env, "subject", "retract", "SUBJ-001", "--reason", "duplicate", "--cascade")
    assert "1 edge(s)" in out

    assert "no entity found" in _fails(env, "subject", "show", "SUBJ-001")
    assert _run(env, "subject", "list").strip() == "(no Subject entries)"
    # the specimen survives; only the edge to the retracted subject is gone
    body = json.loads(_run(env, "specimen", "show", "SPEC-001", "--output", "json"))
    assert body["outgoing"] == []


def test_retracted_entity_is_still_inspectable(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "SUBJ-001")
    _run(env, "subject", "retract", "SUBJ-001", "--reason", "never existed")

    table = _run(env, "subject", "show", "SUBJ-001", "--include-retracted")
    assert "[RETRACTED]" in table
    assert "retracted_by_event:" in table
    body = json.loads(
        _run(env, "subject", "show", "SUBJ-001", "--include-retracted", "--output", "json")
    )
    assert body["retracted_by_event"]
    assert (
        len(json.loads(_run(env, "subject", "list", "--include-retracted", "--output", "json")))
        == 1
    )


def test_retract_facet_and_datapoint(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "SUBJ-001")
    facet_id = _run(
        env,
        "facet",
        "attach",
        "--to",
        "SUBJ-001",
        "--schema-url",
        FIXTURE_SCHEMA,
        "--type",
        "QcMetricsFacet",
        "--producer",
        "p",
        "--data",
        '{"metric_name":"m","metric_value":1.0}',
    ).strip()
    _run(env, "facet", "retract", facet_id, "--reason", "attached to the wrong entity")
    assert _run(env, "facet", "list", "--to", "SUBJ-001").strip() == "(no facet instances)"
    assert "no facet instance" in _fails(env, "facet", "show", facet_id)

    _run(
        env,
        "datapoint",
        "create",
        "DP-1",
        "--for",
        "SUBJ-001",
        "--type",
        "x:m",
        "--kind",
        "number",
        "--value",
        "1",
    )
    # its characterizes edge is an edge like any other
    assert "live edge" in _fails(env, "datapoint", "retract", "DP-1", "--reason", "wrong")
    _run(env, "datapoint", "retract", "DP-1", "--reason", "wrong", "--cascade")
    assert _run(env, "datapoint", "list").strip() == "(no DataPoint entries)"


# --- the log ---------------------------------------------------------------------------------


def test_correction_chain_and_events(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "SUBJ-001")
    _run(env, "subject", "correct", "SUBJ-001", "--local-id", "SUBJ-002", "--reason", "first")
    _run(env, "subject", "correct", "SUBJ-002", "--local-id", "SUBJ-003", "--reason", "second")

    events = json.loads(_run(env, "event", "list", "--output", "json"))
    corrections = [e for e in events if e["type"] == "entity_corrected"]
    assert [e["supersede_reason"] for e in corrections] == ["first", "second"]
    # the second correction supersedes the first, not the original creation
    created = next(e for e in events if e["type"] == "entity_created")
    assert corrections[0]["supersedes"] == created["event_id"]
    assert corrections[1]["supersedes"] == corrections[0]["event_id"]

    shown = json.loads(_run(env, "subject", "show", "SUBJ-003", "--events", "--output", "json"))
    assert [e["type"] for e in shown["events"]] == [
        "entity_created",
        "entity_corrected",
        "entity_corrected",
    ]


def test_replay_reproduces_corrected_and_retracted_state(env: dict[str, str]) -> None:
    _run(env, "subject", "create", "KEEP-001")
    _run(env, "subject", "create", "GONE-001")
    _run(env, "subject", "correct", "KEEP-001", "--local-id", "KEPT-001", "--reason", "typo")
    _run(env, "subject", "retract", "GONE-001", "--reason", "duplicate")

    before = _run(env, "subject", "list", "--include-retracted", "--output", "json")
    _run(env, "event", "replay", "--yes")
    assert _run(env, "subject", "list", "--include-retracted", "--output", "json") == before
    assert len(json.loads(_run(env, "subject", "list", "--output", "json"))) == 1
