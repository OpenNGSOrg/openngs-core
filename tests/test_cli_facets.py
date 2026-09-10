"""End-to-end CLI tests for `openngs facet ...`."""

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


def _attach_args(to: str, data: str, facet_type: str = "QcMetricsFacet") -> list[str]:
    return [
        "facet",
        "attach",
        "--to",
        to,
        "--schema-url",
        FIXTURE_SCHEMA,
        "--type",
        facet_type,
        "--producer",
        "fastqc/0.12.1",
        "--data",
        data,
    ]


def test_attach_list_show_round_trip(env: dict[str, str], tmp_path: Path) -> None:
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001"], env=env)

    data = json.dumps(
        {"tool": "fastqc", "metric_name": "percent_duplication", "metric_value": 12.3}
    )
    args = _attach_args("R1.fastq.gz", data, "QcMetricsFacet") + ["--output", "id"]
    r = runner.invoke(app, args, env=env)
    assert r.exit_code == 0, r.output
    facet_id = r.output.strip()

    r = runner.invoke(app, ["facet", "list", "--to", "R1.fastq.gz"], env=env)
    assert r.exit_code == 0, r.output
    assert facet_id in r.output
    assert "QcMetricsFacet" in r.output

    r = runner.invoke(app, ["facet", "show", facet_id], env=env)
    assert r.exit_code == 0, r.output
    assert "percent_duplication" in r.output
    assert "DataFile" in r.output  # resolved attached_to type/name


def test_attach_data_from_file(env: dict[str, str], tmp_path: Path) -> None:
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001"], env=env)

    data_file = tmp_path / "data.json"
    data_file.write_text(json.dumps({"metric_name": "percent_gc", "metric_value": 41.2}))

    r = runner.invoke(
        app, _attach_args("R1.fastq.gz", f"@{data_file}") + ["--output", "id"], env=env
    )
    assert r.exit_code == 0, r.output


def test_attach_rejects_invalid_data(env: dict[str, str]) -> None:
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001"], env=env)

    r = runner.invoke(app, _attach_args("R1.fastq.gz", json.dumps({"tool": "fastqc"})), env=env)
    assert r.exit_code != 0
    assert "required" in r.output.lower() or "does not validate" in r.output.lower()


def test_attach_rejects_missing_schema_file(env: dict[str, str]) -> None:
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001"], env=env)

    r = runner.invoke(
        app,
        [
            "facet",
            "attach",
            "--to",
            "R1.fastq.gz",
            "--schema-url",
            "/nope/nope.json",
            "--type",
            "QcMetricsFacet",
            "--producer",
            "p",
            "--data",
            "{}",
        ],
        env=env,
    )
    assert r.exit_code != 0
    assert "doesn't resolve to a local file" in r.output


def test_attach_to_an_edge(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    runner.invoke(app, ["specimen", "create", "SPEC-001", "--subject", "SUBJ-001"], env=env)
    runner.invoke(app, ["extract", "create", "EXT-001", "--specimen", "SPEC-001"], env=env)
    runner.invoke(app, ["reagent", "create", "REAGENT-001"], env=env)
    r = runner.invoke(app, ["link", "used", "--from", "EXT-001", "--to", "REAGENT-001"], env=env)
    edge_id = r.output.strip()

    data = json.dumps({"metric_name": "x", "metric_value": 1.0})
    r = runner.invoke(app, _attach_args(edge_id, data) + ["--output", "id"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(app, ["facet", "list", "--to", edge_id], env=env)
    assert r.exit_code == 0, r.output
    assert "QcMetricsFacet" in r.output


def test_facet_show_not_found(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["facet", "show", "018f5b2a-0000-7000-8000-999999999999"], env=env)
    assert r.exit_code != 0
    assert "no facet instance found" in r.output


# --- `facet schema` store -------------------------------------------------------


def test_schema_register_list_show_round_trip(env: dict[str, str]) -> None:
    r = runner.invoke(
        app,
        ["facet", "schema", "register", "qc-metrics", "--file", FIXTURE_SCHEMA, "--output", "id"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    schema_id = r.output.strip()

    r = runner.invoke(app, ["facet", "schema", "list", "--name", "qc-metrics"], env=env)
    assert r.exit_code == 0, r.output
    assert schema_id in r.output

    r = runner.invoke(app, ["facet", "schema", "show", schema_id], env=env)
    assert r.exit_code == 0, r.output
    assert "QcMetricsFacet" in r.output


def test_schema_reregister_creates_new_version(env: dict[str, str]) -> None:
    args = ["facet", "schema", "register", "qc-metrics", "--file", FIXTURE_SCHEMA, "--output", "id"]
    first = runner.invoke(app, args, env=env).output.strip()
    second = runner.invoke(app, args, env=env).output.strip()
    assert first != second

    r = runner.invoke(app, ["facet", "schema", "list", "--name", "qc-metrics"], env=env)
    assert first in r.output
    assert second in r.output


def test_schema_register_missing_file(env: dict[str, str]) -> None:
    r = runner.invoke(
        app,
        ["facet", "schema", "register", "qc-metrics", "--file", "/nope/nope.json"],
        env=env,
    )
    assert r.exit_code != 0
    assert "does not exist" in r.output


def test_attach_with_schema_id(env: dict[str, str]) -> None:
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001"], env=env)
    runner.invoke(
        app, ["facet", "schema", "register", "qc-metrics", "--file", FIXTURE_SCHEMA], env=env
    )

    data = json.dumps({"metric_name": "percent_duplication", "metric_value": 12.3})
    r = runner.invoke(
        app,
        [
            "facet",
            "attach",
            "--to",
            "R1.fastq.gz",
            "--schema-id",
            "qc-metrics",
            "--type",
            "QcMetricsFacet",
            "--producer",
            "fastqc/0.12.1",
            "--data",
            data,
            "--output",
            "id",
        ],
        env=env,
    )
    assert r.exit_code == 0, r.output
    facet_id = r.output.strip()

    r = runner.invoke(app, ["facet", "show", facet_id], env=env)
    assert "openngs-schema://" in r.output


def test_attach_requires_exactly_one_schema_source(env: dict[str, str]) -> None:
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fastq.gz", "--produced-by", "RUN-001"], env=env)

    base = [
        "facet",
        "attach",
        "--to",
        "R1.fastq.gz",
        "--type",
        "QcMetricsFacet",
        "--producer",
        "p",
        "--data",
        "{}",
    ]
    r = runner.invoke(app, base, env=env)
    assert r.exit_code != 0
    assert "exactly one of" in r.output

    both = base + ["--schema-url", FIXTURE_SCHEMA, "--schema-id", "qc-metrics"]
    r = runner.invoke(app, both, env=env)
    assert r.exit_code != 0
    assert "exactly one of" in r.output


def test_attach_data_from_missing_file_is_a_clean_error(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    r = runner.invoke(
        app,
        [
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
            "@/nonexistent/data.json",
        ],
        env=env,
    )
    assert r.exit_code == 1
    assert r.exception is None or isinstance(r.exception, SystemExit)
    assert "cannot read file" in r.output
