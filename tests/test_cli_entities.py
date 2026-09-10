"""End-to-end CLI tests via Typer's CliRunner (docs/cli-design.md)."""

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


def test_create_specimen_requires_subject(env: dict[str, str]) -> None:
    result = runner.invoke(app, ["specimen", "create", "SPEC-001"], env=env)
    assert result.exit_code != 0
    assert "Missing option" in result.output or "subject" in result.output.lower()


def test_full_lineage_via_cli(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["subject", "create", "SUBJ-001", "--output", "id"], env=env)
    assert r.exit_code == 0, r.output
    subject_id = r.output.strip()

    r = runner.invoke(
        app,
        ["specimen", "create", "SPEC-001", "--subject", "SUBJ-001", "--output", "id"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    specimen_id = r.output.strip()
    assert specimen_id != subject_id

    r = runner.invoke(app, ["specimen", "list", "--subject", "SUBJ-001"], env=env)
    assert r.exit_code == 0, r.output
    assert "SPEC-001" in r.output

    r = runner.invoke(app, ["specimen", "list", "--subject", "SUBJ-001", "--output", "id"], env=env)
    assert r.exit_code == 0, r.output
    assert r.output.strip() == specimen_id

    r = runner.invoke(app, ["specimen", "show", "SPEC-001"], env=env)
    assert r.exit_code == 0, r.output
    assert "Outgoing:" in r.output
    assert "derived_from" in r.output
    assert "SUBJ-001" in r.output


def test_duplicate_name_rejected(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    assert r.exit_code != 0
    assert "already exists" in r.output
    # there is no override any more: --force is gone
    r = runner.invoke(app, ["subject", "create", "SUBJ-001", "--force"], env=env)
    assert r.exit_code != 0


def test_dry_run_does_not_write(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["subject", "create", "SUBJ-001", "--dry-run"], env=env)
    assert r.exit_code == 0, r.output
    assert "dry run" in r.output
    r = runner.invoke(app, ["subject", "list"], env=env)
    assert r.exit_code == 0, r.output
    assert "no Subject entries" in r.output


def test_link_used_type_validation(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    runner.invoke(app, ["specimen", "create", "SPEC-001", "--subject", "SUBJ-001"], env=env)
    runner.invoke(app, ["extract", "create", "EXT-001", "--specimen", "SPEC-001"], env=env)

    # Subject is not a valid `used` target (Protocol/Reagent/Actor/DataFile/DataFileSet -
    # widened from just the first three).
    r = runner.invoke(app, ["link", "used", "--from", "EXT-001", "--to", "SUBJ-001"], env=env)
    assert r.exit_code != 0

    runner.invoke(app, ["reagent", "create", "REAGENT-001"], env=env)
    r = runner.invoke(app, ["link", "used", "--from", "EXT-001", "--to", "REAGENT-001"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(app, ["extract", "show", "EXT-001"], env=env)
    assert "used" in r.output
    assert "REAGENT-001" in r.output


def test_sequencing_run_declares_its_material_via_cli(env: dict[str, str]) -> None:
    """The run states what was loaded on it, not only what its output descended
    from. A pooled run `used` the Pool; a single-sample run `used` the Library directly."""
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    runner.invoke(app, ["specimen", "create", "SPEC-001", "--subject", "SUBJ-001"], env=env)
    runner.invoke(app, ["extract", "create", "EXT-001", "--specimen", "SPEC-001"], env=env)
    runner.invoke(app, ["library", "create", "LIB-001", "--extract", "EXT-001"], env=env)
    runner.invoke(app, ["pool", "create", "POOL-001"], env=env)
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["sequencing-run", "create", "RUN-SOLO"], env=env)

    r = runner.invoke(app, ["link", "used", "--from", "RUN-001", "--to", "POOL-001"], env=env)
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["link", "used", "--from", "RUN-SOLO", "--to", "LIB-001"], env=env)
    assert r.exit_code == 0, r.output

    r = runner.invoke(app, ["sequencing-run", "show", "RUN-001"], env=env)
    assert "used" in r.output and "POOL-001" in r.output

    # Nothing loads a Specimen or an Extract onto a sequencer.
    for ref in ("SPEC-001", "EXT-001"):
        r = runner.invoke(app, ["link", "used", "--from", "RUN-001", "--to", ref], env=env)
        assert r.exit_code == 1, ref


def test_bioinformatics_lineage_via_cli(env: dict[str, str]) -> None:
    """SequencingRun -> raw BCL DataFileSet -> BCLConvert AnalysisRun
    (used the BCL set directly) -> run-level FASTQ DataFileSet -> a nested per-sample
    DataFileSet (part_of the run-level one) -> a secondary pipeline AnalysisRun that used
    the per-sample set directly, end to end through the CLI."""
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(
        app,
        ["data-file-set", "create", "RUN-001-BCL", "--produced-by", "RUN-001"],
        env=env,
    )
    runner.invoke(app, ["analysis-run", "create", "BCLCONVERT-1"], env=env)
    r = runner.invoke(
        app, ["link", "used", "--from", "BCLCONVERT-1", "--to", "RUN-001-BCL"], env=env
    )
    assert r.exit_code == 0, r.output

    runner.invoke(
        app,
        ["data-file-set", "create", "SAMPLE-042-FASTQ", "--produced-by", "BCLCONVERT-1"],
        env=env,
    )
    runner.invoke(
        app,
        ["data-file-set", "create", "RUN-001-FASTQ", "--produced-by", "BCLCONVERT-1"],
        env=env,
    )
    r = runner.invoke(
        app,
        ["link", "part-of", "--from", "SAMPLE-042-FASTQ", "--to", "RUN-001-FASTQ"],
        env=env,
    )
    assert r.exit_code == 0, r.output

    runner.invoke(app, ["analysis-run", "create", "WGS-PIPE-042"], env=env)
    r = runner.invoke(
        app, ["link", "used", "--from", "WGS-PIPE-042", "--to", "SAMPLE-042-FASTQ"], env=env
    )
    assert r.exit_code == 0, r.output

    r = runner.invoke(app, ["data-file-set", "show", "SAMPLE-042-FASTQ"], env=env)
    assert r.exit_code == 0, r.output
    assert "produced_by" in r.output and "BCLCONVERT-1" in r.output
    assert "part_of" in r.output and "RUN-001-FASTQ" in r.output
    assert "used" in r.output and "WGS-PIPE-042" in r.output


def test_missing_org_ns_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    r = runner.invoke(app, ["subject", "list"], env={"OPENNGS_DB_URL": f"sqlite:///{db_path}"})
    assert r.exit_code != 0
    assert "OPENNGS_ORG" in r.output


def test_duplicate_xref_is_stored_once(env: dict[str, str]) -> None:
    r = runner.invoke(
        app,
        ["subject", "create", "SUBJ-001", "--xref", "biosample:SAMN1", "--xref", "biosample:SAMN1"],
        env=env,
    )
    assert r.exit_code == 0, r.output
    r = runner.invoke(app, ["subject", "show", "SUBJ-001", "--output", "json"], env=env)
    assert json.loads(r.output)["xrefs"] == ["biosample:SAMN1"]


def test_empty_local_id_is_a_clean_error(env: dict[str, str]) -> None:
    r = runner.invoke(app, ["subject", "create", ""], env=env)
    assert r.exit_code == 1
    assert r.exception is None or isinstance(r.exception, SystemExit)
    assert "must not be empty" in r.output
    r = runner.invoke(app, ["facet", "schema", "register", "", "--file", "x.json"], env=env)
    assert r.exit_code == 1
    assert "must not be empty" in r.output


def test_link_duplicate_edge_is_a_clean_error(env: dict[str, str]) -> None:
    runner.invoke(app, ["subject", "create", "SUBJ-001"], env=env)
    runner.invoke(app, ["specimen", "create", "SPEC-001", "--subject", "SUBJ-001"], env=env)
    r = runner.invoke(
        app, ["link", "derived-from", "--from", "SPEC-001", "--to", "SUBJ-001"], env=env
    )
    assert r.exit_code == 1
    assert "already exists" in r.output
    r = runner.invoke(app, ["link", "part-of", "--from", "SUBJ-001", "--to", "SUBJ-001"], env=env)
    assert r.exit_code == 1
    assert "itself" in r.output
    # same REF twice on --derived-from is deduped, not a duplicate-edge failure
    runner.invoke(app, ["sequencing-run", "create", "RUN-001"], env=env)
    runner.invoke(app, ["data-file", "create", "R1.fq", "--produced-by", "RUN-001"], env=env)
    r = runner.invoke(
        app,
        [
            "data-file",
            "create",
            "R1.trim.fq",
            "--produced-by",
            "RUN-001",
            "--derived-from",
            "R1.fq",
            "--derived-from",
            "R1.fq",
        ],
        env=env,
    )
    assert r.exit_code == 0, r.output


def test_list_filters_by_valid_time_range(env: dict[str, str]) -> None:
    """valid_time is projected onto the row, so a seasonal range is a filter."""
    runner.invoke(app, ["subject", "create", "SITE-LAKE-01"], env=env)
    for local_id, when in (
        ("LK-JUN", "2025-06-15T09:00:00"),
        ("LK-AUG", "2025-08-20T09:00:00"),
        ("LK-DEC", "2025-12-01T09:00:00"),
    ):
        r = runner.invoke(
            app,
            ["specimen", "create", local_id, "--subject", "SITE-LAKE-01", "--valid-time", when],
            env=env,
        )
        assert r.exit_code == 0, r.output

    def names(*args: str) -> set[str]:
        r = runner.invoke(app, ["specimen", "list", "--output", "json", *args], env=env)
        assert r.exit_code == 0, r.output
        return {row["name"].rsplit("/", 1)[1] for row in json.loads(r.output)}

    assert names() == {"LK-JUN", "LK-AUG", "LK-DEC"}
    assert names("--valid-to", "2025-09-01") == {"LK-JUN", "LK-AUG"}
    assert names("--valid-from", "2025-06-01", "--valid-to", "2025-09-01") == {"LK-JUN", "LK-AUG"}
    assert names("--subject", "SITE-LAKE-01", "--valid-from", "2025-11-01") == {"LK-DEC"}

    # valid_time is visible without --events, in both output modes
    r = runner.invoke(app, ["specimen", "list", "--output", "json"], env=env)
    assert all(row["valid_time"] for row in json.loads(r.output))
    r = runner.invoke(app, ["specimen", "show", "LK-JUN"], env=env)
    assert "valid_time: 2025-06-15T09:00:00+00:00" in r.output

    r = runner.invoke(app, ["specimen", "list", "--valid-from", "nope"], env=env)
    assert r.exit_code == 1
    assert "not a valid ISO 8601" in r.output
