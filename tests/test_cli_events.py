"""End-to-end CLI tests for `openngs event ...` and `--valid-time`."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from openngs.cli import app

runner = CliRunner()


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


def test_create_emits_event(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(app, ["event", "list"], env=env)
    assert r.exit_code == 0, r.output
    assert "entity_created" in r.output


def test_valid_time_defaults_to_transaction_time(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["subject", "create", "SUBJ-001", "--output", "id"], env=env)
    event_id = _first_event_id(env)
    r = runner.invoke(app, ["event", "show", event_id, "--output", "json"], env=env)
    assert r.exit_code == 0, r.output
    event = json.loads(r.output)
    assert event["valid_time"] == event["transaction_time"]


def test_valid_time_can_diverge_from_transaction_time(env: dict[str, str]) -> None:
    r = runner.invoke(
        app,
        ["subject", "create", "SUBJ-001", "--valid-time", "2026-01-15T09:00:00"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    event_id = _first_event_id(env)
    r = runner.invoke(app, ["event", "show", event_id, "--output", "json"], env=env)
    event = json.loads(r.output)
    # No offset given -> taken as UTC, stored aware, so it sorts/compares with every other
    # (always UTC-aware) timestamp in the log.
    assert event["valid_time"] == "2026-01-15T09:00:00+00:00"
    assert event["transaction_time"] != event["valid_time"]


def test_valid_time_with_offset_is_normalized_to_utc(env: dict[str, str]) -> None:
    r = runner.invoke(
        app,
        ["subject", "create", "SUBJ-001", "--valid-time", "2026-01-15T09:00:00+02:00"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    event_id = _first_event_id(env)
    r = runner.invoke(app, ["event", "show", event_id, "--output", "json"], env=env)
    assert json.loads(r.output)["valid_time"] == "2026-01-15T07:00:00+00:00"


def test_valid_time_rejects_bad_iso8601(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["subject", "create", "SUBJ-001", "--valid-time", "not-a-date"], env=env)
    assert r.exit_code != 0
    assert "not a valid ISO 8601" in r.output


def test_event_list_output_id_and_json(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    runner.invoke(app, ["subject", "create", "SUBJ-002"], env=env)

    r = runner.invoke(app, ["event", "list", "--output", "id"], env=env)
    assert r.exit_code == 0, r.output
    ids = r.output.strip().splitlines()
    assert len(ids) == 2

    r = runner.invoke(app, ["event", "list", "--output", "json"], env=env)
    assert r.exit_code == 0, r.output
    events = json.loads(r.output)
    assert len(events) == 2
    assert {e["event_id"] for e in events} == set(ids)


def test_event_list_respects_limit(env: dict[str, str]) -> None:
    for i in range(5):
        runner.invoke(app, ["subject", "create", f"SUBJ-{i:03d}"], env=env)
    r = runner.invoke(app, ["event", "list", "--limit", "2", "--output", "id"], env=env)
    assert r.exit_code == 0, r.output
    assert len(r.output.strip().splitlines()) == 2


def test_event_show_unknown_id_fails(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["event", "show", "018f5b2a-0000-7000-8000-999999999999"], env=env)
    assert r.exit_code != 0
    assert "no event found" in r.output


def test_event_replay_requires_yes(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    r = runner.invoke(app, ["event", "replay"], env=env)
    assert r.exit_code != 0
    assert "--yes" in r.output


def test_event_replay_reproduces_projection(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    runner.invoke(app, ["specimen", "create", "SPEC-001", "--subject", "SUBJ-001"], env=env)

    before = runner.invoke(app, ["specimen", "show", "SPEC-001"], env=env)
    assert before.exit_code == 0, before.output

    r = runner.invoke(app, ["event", "replay", "--yes"], env=env)
    assert r.exit_code == 0, r.output
    assert "replayed" in r.output

    after = runner.invoke(app, ["specimen", "show", "SPEC-001"], env=env)
    assert after.exit_code == 0, after.output
    assert after.output == before.output


def test_entity_show_events_lists_creation_and_edge_events(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    runner.invoke(app, ["specimen", "create", "SPEC-001", "--subject", "SUBJ-001"], env=env)

    without = runner.invoke(app, ["specimen", "show", "SPEC-001"], env=env)
    assert without.exit_code == 0, without.output
    assert "Events:" not in without.output

    r = runner.invoke(app, ["specimen", "show", "SPEC-001", "--events"], env=env)
    assert r.exit_code == 0, r.output
    assert "Events:" in r.output
    assert "entity_created" in r.output
    assert "edge_created" in r.output

    # SUBJ-001's own creation event isn't "related to" SPEC-001 - only SPEC-001's own
    # entity_created plus the derived_from edge_created linking it to SUBJ-001 should show.
    all_events = runner.invoke(app, ["event", "list", "--output", "id"], env=env)
    all_event_ids = all_events.output.strip().splitlines()
    assert len(all_event_ids) == 3
    shown_event_ids = [line.split()[0] for line in r.output.splitlines() if "_created" in line]
    assert len(shown_event_ids) == 2
    assert set(shown_event_ids) < set(all_event_ids)


def test_entity_show_events_json_includes_events_key(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    r = runner.invoke(app, ["subject", "show", "SUBJ-001", "--events", "--output", "json"], env=env)
    assert r.exit_code == 0, r.output
    shown = json.loads(r.output)
    assert len(shown["events"]) == 1
    assert shown["events"][0]["type"] == "entity_created"
    assert shown["events"][0]["subject"] == shown["internal_id"]


def test_entity_show_without_events_flag_omits_events_key(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    r = runner.invoke(app, ["subject", "show", "SUBJ-001", "--output", "json"], env=env)
    assert r.exit_code == 0, r.output
    assert "events" not in json.loads(r.output)


def test_datapoint_show_events(env: dict[str, str]) -> None:
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001"], env=env)
    runner.invoke(
        app,
        [
            "datapoint",
            "create",
            "pct-dup",
            "--for",
            "R1.fastq.gz",
            "--type",
            "openngs-dp:percent_duplication",
            "--kind",
            "number",
            "--value",
            "12.3",
        ],
        env=env,
    )
    r = runner.invoke(app, ["datapoint", "show", "pct-dup", "--events"], env=env)
    assert r.exit_code == 0, r.output
    assert "Events:" in r.output
    assert "entity_created" in r.output
    assert "edge_created" in r.output


def test_facet_show_events(env: dict[str, str], tmp_path: Path) -> None:
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001"], env=env)
    schema_path = (
        Path(__file__).parent.parent
        / "docs"
        / "facets"
        / "examples"
        / "qc_metrics"
        / "qc_metrics.schema.json"
    )
    r = runner.invoke(
        app,
        [
            "facet",
            "attach",
            "--to",
            "R1.fastq.gz",
            "--schema-url",
            str(schema_path),
            "--type",
            "QcMetricsFacet",
            "--producer",
            "fastqc/0.12.1",
            "--data",
            '{"metric_name":"openngs-dp:percent_duplication","metric_value":12.3}',
            "--output",
            "id",
        ],
        env=env,
    )
    assert r.exit_code == 0, r.output
    facet_id = r.output.strip()

    r = runner.invoke(app, ["facet", "show", facet_id, "--events"], env=env)
    assert r.exit_code == 0, r.output
    assert "Events:" in r.output
    assert "facet_instance_attached" in r.output


def test_facet_schema_show_events(env: dict[str, str]) -> None:
    schema_path = (
        Path(__file__).parent.parent
        / "docs"
        / "facets"
        / "examples"
        / "qc_metrics"
        / "qc_metrics.schema.json"
    )
    r = runner.invoke(
        app,
        ["facet", "schema", "register", "qc-metrics", "--file", str(schema_path), "--output", "id"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    schema_id = r.output.strip()

    r = runner.invoke(app, ["facet", "schema", "show", schema_id, "--events"], env=env)
    assert r.exit_code == 0, r.output
    assert "Events:" in r.output
    assert "facet_schema_registered" in r.output


def _first_event_id(env: dict[str, str]) -> str:
    r = runner.invoke(app, ["event", "list", "--output", "id"], env=env)
    return r.output.strip().splitlines()[0]
