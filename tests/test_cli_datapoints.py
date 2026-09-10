"""End-to-end CLI tests for `openngs datapoint ...`."""

from __future__ import annotations

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


def _setup_datafile(env: dict[str, str]) -> None:
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001"], env=env)


def test_create_list_show_round_trip(env: dict[str, str]) -> None:
    _setup_datafile(env)
    r = runner.invoke(
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
            "--output",
            "id",
        ],
        env=env,
    )
    assert r.exit_code == 0, r.output
    dp_id = r.output.strip()

    r = runner.invoke(app, ["datapoint", "list", "--for", "R1.fastq.gz"], env=env)
    assert r.exit_code == 0, r.output
    assert "percent_duplication=12.3" in r.output

    r = runner.invoke(app, ["datapoint", "show", dp_id], env=env)
    assert r.exit_code == 0, r.output
    assert "value (number): 12.3" in r.output
    assert "characterizes" in r.output
    assert "DataFile" in r.output


def test_create_text_and_boolean_kinds(env: dict[str, str]) -> None:
    _setup_datafile(env)
    r = runner.invoke(
        app,
        [
            "datapoint",
            "create",
            "status",
            "--for",
            "R1.fastq.gz",
            "--type",
            "acme:status",
            "--kind",
            "text",
            "--value",
            "PASS",
        ],
        env=env,
    )
    assert r.exit_code == 0, r.output

    r = runner.invoke(
        app,
        [
            "datapoint",
            "create",
            "flagged",
            "--for",
            "R1.fastq.gz",
            "--type",
            "acme:flagged",
            "--kind",
            "boolean",
            "--value",
            "true",
        ],
        env=env,
    )
    assert r.exit_code == 0, r.output

    r = runner.invoke(app, ["datapoint", "list", "--for", "R1.fastq.gz"], env=env)
    assert "acme:status=PASS" in r.output
    assert "acme:flagged=True" in r.output


def test_create_rejects_bad_kind(env: dict[str, str]) -> None:
    _setup_datafile(env)
    r = runner.invoke(
        app,
        [
            "datapoint",
            "create",
            "bad",
            "--for",
            "R1.fastq.gz",
            "--type",
            "x:y",
            "--kind",
            "weird",
            "--value",
            "1",
        ],
        env=env,
    )
    assert r.exit_code != 0
    assert "must be one of" in r.output


def test_create_rejects_unknown_for_ref(env: dict[str, str]) -> None:
    r = runner.invoke(
        app,
        [
            "datapoint",
            "create",
            "orphan",
            "--for",
            "NOPE",
            "--type",
            "x:y",
            "--kind",
            "number",
            "--value",
            "1",
        ],
        env=env,
    )
    assert r.exit_code != 0


def test_dry_run_does_not_write(env: dict[str, str]) -> None:
    _setup_datafile(env)
    r = runner.invoke(
        app,
        [
            "datapoint",
            "create",
            "pct-dup",
            "--for",
            "R1.fastq.gz",
            "--type",
            "x:y",
            "--kind",
            "number",
            "--value",
            "1",
            "--dry-run",
        ],
        env=env,
    )
    assert r.exit_code == 0, r.output
    assert "dry run" in r.output
    r = runner.invoke(app, ["datapoint", "list"], env=env)
    assert "no DataPoint entries" in r.output


def test_generic_link_characterizes_escape_hatch(env: dict[str, str]) -> None:
    _setup_datafile(env)
    runner.invoke(app, ["sequencing-run", "create", "RUN-002"], env=env)
    r = runner.invoke(
        app,
        [
            "datapoint",
            "create",
            "shared-dp",
            "--for",
            "R1.fastq.gz",
            "--type",
            "x:y",
            "--kind",
            "number",
            "--value",
            "1",
            "--output",
            "id",
        ],
        env=env,
    )
    dp_id = r.output.strip()
    r = runner.invoke(app, ["link", "characterizes", "--from", dp_id, "--to", "RUN-002"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(app, ["datapoint", "show", dp_id], env=env)
    assert r.output.count("characterizes") == 2  # once to R1.fastq.gz, once to RUN-002

    # --from must be a DataPoint: the schema defines characterizes as DataPoint -> Entity
    r = runner.invoke(app, ["link", "characterizes", "--from", "RUN-002", "--to", dp_id], env=env)
    assert r.exit_code == 1
    assert "DataPoint" in r.output
