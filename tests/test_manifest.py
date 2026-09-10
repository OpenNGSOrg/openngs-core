"""Loading a CSV/TSV manifest (#10).

A manifest is a spreadsheet the lab already keeps, so most of what matters here is
tolerance of how spreadsheets actually look - blank lines, unknown columns, a stray comment
row - paired with refusing to write anything at all when one line is wrong.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openngs.api import app
from openngs.batch import BatchShapeError
from openngs.manifest import parse_manifest

client = TestClient(app)

HEADER = "kind\ttype\tlocal_id\tparent\tfrom\tto\txrefs\tvalid_time\tfor\tvalue_kind\tvalue\n"

TRIO = HEADER + (
    "# the lab's own note, ignored\n"
    "entity\tsubject\tSUBJ-1\t\t\t\tbiosample:SAMN1\t2026-09-01T09:00:00Z\t\t\t\n"
    "\n"
    "entity\tspecimen\tSPEC-1\tSUBJ-1\t\t\tbarcode:TUBE-1\t2026-09-01T10:30:00Z\t\t\t\n"
    "entity\textract\tEXT-1\tSPEC-1\t\t\t\t\t\t\t\n"
    "entity\tactor\tINSTR-1\t\t\t\t\t\t\t\t\n"
    "edge\tused\t\t\tEXT-1\tINSTR-1\t\t\t\t\t\n"
    "datapoint\topenngs-dp:mean_coverage\tDP-1\t\t\t\t\t\tEXT-1\tnumber\t31.4\n"
)


@pytest.fixture
def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "test.db"
    schema_sql = (Path(__file__).parent.parent / "generated" / "schema.sql").read_text()
    conn = sqlite3.connect(path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    monkeypatch.setenv("OPENNGS_ORG", "acme-genomics")
    monkeypatch.setenv("OPENNGS_NAMESPACE", "core-lab")
    monkeypatch.setenv("OPENNGS_DB_URL", f"sqlite:///{path}")
    return path


def _post(manifest: str, **body: Any) -> Any:
    params = body.pop("params", {})
    return client.post("/ingest/manifest", json={"manifest": manifest, **body}, params=params)


def _cli(db: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "openngs.cli", *args],
        capture_output=True,
        text=True,
        env={
            "PATH": "/usr/bin:/bin",
            "OPENNGS_ORG": "acme-genomics",
            "OPENNGS_NAMESPACE": "core-lab",
            "OPENNGS_DB_URL": f"sqlite:///{db}",
            "OPENNGS_AUTH_MODE": "none",
        },
    )


# --- parsing ----------------------------------------------------------------------------


def test_blank_and_comment_lines_are_skipped() -> None:
    parsed = parse_manifest(TRIO)
    assert len(parsed) == 6
    # Line numbers are the file's own, counting the header, the comment and the blank line,
    # so an error points at what the author is looking at in their editor.
    assert parsed.lines == [3, 5, 6, 7, 8, 9]


def test_a_csv_is_read_as_readily_as_a_tsv() -> None:
    csv = "kind,type,local_id\nentity,subject,SUBJ-1\n"
    assert parse_manifest(csv).operations[0].local_id == "SUBJ-1"


def test_unknown_columns_are_ignored() -> None:
    """A sheet exported from a LIMS carries columns OpenNGS has no use for."""
    text = "kind,type,local_id,operator,rack_position\nentity,subject,SUBJ-1,jdoe,A7\n"
    assert len(parse_manifest(text)) == 1


def test_several_xrefs_in_one_cell() -> None:
    text = "kind,type,local_id,xrefs\nentity,subject,SUBJ-1,biosample:SAMN1;ena:ERS1\n"
    assert parse_manifest(text).operations[0].xrefs == ["biosample:SAMN1", "ena:ERS1"]


def test_a_per_kind_type_column_wins_over_the_generic_one() -> None:
    text = "kind,type,entity_type,local_id\nentity,nonsense,subject,SUBJ-1\n"
    assert parse_manifest(text).operations[0].entity_type == "subject"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty"),
        ("kind,type\n", "no rows"),
        ("type,local_id\nsubject,SUBJ-1\n", "'kind' column"),
        ("kind,type,local_id\nsample,subject,SUBJ-1\n", "unknown kind"),
        ("kind,type,local_id,valid_time\nentity,subject,S1,last tuesday\n", "not ISO 8601"),
        ("kind,type,from,to,confidence\nedge,same_as,A,B,very\n", "not a number"),
    ],
)
def test_a_malformed_manifest_is_refused_before_any_write(text: str, message: str) -> None:
    with pytest.raises(BatchShapeError, match=message):
        parse_manifest(text)


def test_the_failing_line_is_named() -> None:
    text = "kind,type,local_id,valid_time\nentity,subject,S1,\nentity,subject,S2,whenever\n"
    with pytest.raises(BatchShapeError, match="line 3"):
        parse_manifest(text)


def test_a_data_cell_reads_a_file_beside_the_manifest(tmp_path: Path) -> None:
    (tmp_path / "qc.json").write_text('{"percent_duplication": 0.11}')
    text = "kind,type,to,producer,schema_url,data\nfacet,QcMetrics,X,fastqc,s.json,@qc.json\n"
    op = parse_manifest(text, base=tmp_path).operations[0]
    assert op.data == {"percent_duplication": 0.11}


def test_a_file_reference_is_refused_when_files_are_not_allowed(tmp_path: Path) -> None:
    """Over HTTP a `@` path would name a file on the server, not one the sender can see."""
    text = "kind,type,to,producer,schema_url,data\nfacet,QcMetrics,X,fastqc,s.json,@/etc/passwd\n"
    with pytest.raises(BatchShapeError, match="only read from a local manifest"):
        parse_manifest(text, allow_files=False)


# --- applying, over HTTP ----------------------------------------------------------------


def test_a_manifest_is_applied_in_file_order(db_path: Path) -> None:
    r = _post(TRIO)
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 6

    # a later row resolved an entity an earlier row created
    shown = client.get("/specimens/SPEC-1").json()
    assert shown["xrefs"] == ["barcode:TUBE-1"]
    assert [e["predicate"] for e in shown["outgoing"]] == ["derived_from"]
    # each row's own valid_time was honoured, not the load time
    assert shown["valid_time"].startswith("2026-09-01T10:30")

    dp = client.get("/datapoints/DP-1").json()
    assert dp["value"] == 31.4


def test_a_bad_row_leaves_nothing_behind(db_path: Path) -> None:
    text = HEADER + (
        "entity\tsubject\tSUBJ-9\t\t\t\t\t\t\t\t\nentity\tspecimen\tSPEC-9\tNOPE\t\t\t\t\t\t\t\n"
    )
    r = _post(text)
    assert r.status_code == 400
    assert "line 3" in r.json()["detail"]
    assert client.get("/subjects").json() == []


def test_dry_run_validates_the_whole_file_and_writes_nothing(db_path: Path) -> None:
    r = _post(TRIO, params={"dry_run": "true"})
    assert r.status_code == 200, r.text
    assert r.json() == {"applied": 0, "dry_run": True, "results": r.json()["results"]}
    assert client.get("/subjects").json() == []


def test_resending_collides_but_skip_makes_it_idempotent(db_path: Path) -> None:
    assert _post(TRIO).status_code == 200
    again = _post(TRIO)
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]

    skipped = _post(TRIO, if_exists="skip")
    assert skipped.status_code == 200, skipped.text
    assert [x.get("created") for x in skipped.json()["results"] if "created" in x] == [False] * 6
    assert len(client.get("/subjects").json()) == 1


def test_a_repeated_datapoint_with_a_different_value_is_not_a_repeat(db_path: Path) -> None:
    """Skip means "I sent this already", not "overwrite it". A changed measurement is a
    correction, and answering with the old row would hide the difference."""
    assert _post(TRIO).status_code == 200
    changed = TRIO.replace("31.4", "44.2")
    r = _post(changed, if_exists="skip")
    assert r.status_code == 409
    assert "different value" in r.json()["detail"]


def test_a_file_reference_over_http_is_refused(db_path: Path) -> None:
    text = "kind,type,to,producer,schema_url,data\nfacet,QcMetrics,X,fastqc,s.json,@/etc/passwd\n"
    r = _post(text)
    assert r.status_code == 422
    assert "local manifest" in r.json()["detail"]


def test_if_exists_takes_only_the_two_documented_values(db_path: Path) -> None:
    assert _post(TRIO, if_exists="overwrite").status_code == 422


# --- applying, from the CLI -------------------------------------------------------------


def test_the_cli_loads_the_same_file(db_path: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "run.tsv"
    manifest.write_text(TRIO)
    done = _cli(db_path, "ingest", "manifest", str(manifest), "--output", "json")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["applied"] == 6

    rerun = _cli(db_path, "ingest", "manifest", str(manifest))
    assert rerun.returncode == 1
    assert "line 3" in rerun.stderr and "already exists" in rerun.stderr

    skipped = _cli(db_path, "ingest", "manifest", str(manifest), "--if-exists", "skip")
    assert skipped.returncode == 0, skipped.stderr


def test_the_cli_dry_run_writes_nothing(db_path: Path, tmp_path: Path) -> None:
    manifest = tmp_path / "run.tsv"
    manifest.write_text(TRIO)
    done = _cli(db_path, "ingest", "manifest", str(manifest), "--dry-run")
    assert done.returncode == 0, done.stderr
    assert "would apply 6 rows" in done.stdout
    assert client.get("/subjects").json() == []


def test_the_shipped_example_manifest_loads(db_path: Path) -> None:
    """docs/examples/intake-manifest.tsv is the intake half of the worked example. If it
    stops loading, the documentation is wrong."""
    example = Path(__file__).parent.parent / "docs" / "examples" / "intake-manifest.tsv"
    r = _post(example.read_text())
    assert r.status_code == 200, r.text
    assert r.json()["applied"] == 45

    pool = client.get("/pools/POOL-20260113").json()
    assert sorted(e["other_name"].rsplit("/", 1)[1] for e in pool["incoming"]) == [
        "LIB-0042-F",
        "LIB-0042-M",
        "LIB-0042-P",
    ]
    # a row's own valid_time survived the load, months before the load itself
    assert client.get("/specimens/SPEC-0042-P").json()["valid_time"].startswith("2026-01-08")
