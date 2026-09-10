"""Outbound event delivery (#12).

The property under test throughout is the cursor rule: it advances only after a sink says
an event is delivered. Everything else - retries, dead-lettering, resuming - is a
consequence of that, so most of these tests are about what the cursor does after a failure.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from openngs.cli import app
from openngs.relay import RelayState, deliver, initial_cursor, run_relay
from openngs.sinks import DeliveryError, FileSink, WebhookSink, to_cloudevent

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
        "OPENNGS_AUTH_MODE": "none",
    }


def _seed(env: dict[str, str], count: int = 3) -> None:
    """`count` subjects, so the log has that many entity_created events and nothing else."""
    for i in range(count):
        r = runner.invoke(app, ["subject", "create", f"SUBJ-{i}"], env=env)
        assert r.exit_code == 0, r.output


class RecordingSink:
    """Publishes into a list, and fails on demand.

    `fail_on` names the local_ids whose events should fail; `permanent` decides whether the
    failure claims to be worth retrying. `attempts` counts every call, which is how the
    retry tests tell one attempt from four.
    """

    def __init__(self, fail_on: set[str] | None = None, permanent: bool = False) -> None:
        self.name = "recording"
        self.published: list[dict[str, Any]] = []
        self.attempts = 0
        self.closed = False
        self._fail_on = fail_on or set()
        self._permanent = permanent

    def publish(self, event: dict[str, Any]) -> None:
        self.attempts += 1
        name = str(event["payload"].get("name", ""))
        if any(bad in name for bad in self._fail_on):
            raise DeliveryError(f"refusing {name}", retryable=not self._permanent)
        self.published.append(event)

    def close(self) -> None:
        self.closed = True


def _run(env: dict[str, str], state_path: Path, sink: Any, **kwargs: Any) -> int:
    return run_relay(
        env["OPENNGS_DB_URL"],
        sink,
        RelayState.load(state_path),
        once=True,
        sleep=lambda _seconds: None,
        **kwargs,
    )


# --- the wire envelope --------------------------------------------------------------------


def test_a_stored_event_becomes_a_cloudevent(env: dict[str, str], tmp_path: Path) -> None:
    _seed(env, 1)
    sink = RecordingSink()
    _run(env, tmp_path / "s.json", sink)

    envelope = to_cloudevent(sink.published[0])
    assert envelope["specversion"] == "1.0"
    assert envelope["id"] == sink.published[0]["event_id"]
    assert envelope["source"] == "openngs-cli"
    assert envelope["type"] == "entity_created"
    assert envelope["datacontenttype"] == "application/json"

    # OpenNGS's own fields travel inside data: CloudEvents reserves the top level, and an
    # extension attribute may only be lowercase alphanumeric, which valid_time is not.
    assert envelope["data"]["valid_time"] == sink.published[0]["valid_time"]
    assert envelope["data"]["transaction_time"] == sink.published[0]["transaction_time"]
    assert envelope["data"]["name"].endswith("/subject/SUBJ-0")
    assert set(envelope) <= {
        "specversion",
        "id",
        "source",
        "type",
        "subject",
        "time",
        "datacontenttype",
        "data",
    }


def test_subject_is_omitted_rather_than_null() -> None:
    event = {
        "event_id": "e1",
        "source": "s",
        "type": "t",
        "specversion": "1.0",
        "subject": None,
        "time": "T",
        "datacontenttype": "application/json",
        "valid_time": "V",
        "transaction_time": "TT",
        "recorded_by": None,
        "supersedes": None,
        "supersede_reason": None,
        "payload": {},
    }
    assert "subject" not in to_cloudevent(event)


def test_a_correction_carries_its_supersedes_into_data(env: dict[str, str], tmp_path: Path) -> None:
    _seed(env, 1)
    runner.invoke(
        app, ["subject", "correct", "SUBJ-0", "--reason", "typo", "--local-id", "SUBJ-9"], env=env
    )
    sink = RecordingSink()
    _run(env, tmp_path / "s.json", sink)
    corrected = [e for e in sink.published if e["type"] == "entity_corrected"]
    assert len(corrected) == 1
    data = to_cloudevent(corrected[0])["data"]
    assert data["supersedes"] and data["supersede_reason"] == "typo"


# --- the cursor ---------------------------------------------------------------------------


def test_the_cursor_advances_and_a_rerun_delivers_nothing(
    env: dict[str, str], tmp_path: Path
) -> None:
    _seed(env, 3)
    state = tmp_path / "state.json"
    first = RecordingSink()
    assert _run(env, state, first) == 3
    assert json.loads(state.read_text())["cursor"] == first.published[-1]["event_id"]

    second = RecordingSink()
    assert _run(env, state, second) == 0
    assert second.published == []


def test_only_events_after_the_cursor_are_delivered(env: dict[str, str], tmp_path: Path) -> None:
    _seed(env, 2)
    state = tmp_path / "state.json"
    _run(env, state, RecordingSink())

    runner.invoke(app, ["subject", "create", "LATER"], env=env)
    sink = RecordingSink()
    assert _run(env, state, sink) == 1
    assert sink.published[0]["payload"]["name"].endswith("/LATER")


def test_a_failure_leaves_the_cursor_on_the_last_delivered_event(
    env: dict[str, str], tmp_path: Path
) -> None:
    """The point of the whole design: nothing after the failure is marked delivered, so a
    rerun re-sends it. At-least-once, never at-most-once."""
    _seed(env, 3)
    state = tmp_path / "state.json"
    sink = RecordingSink(fail_on={"SUBJ-1"}, permanent=True)
    with pytest.raises(DeliveryError):
        _run(env, state, sink, max_retries=0)

    assert [e["payload"]["name"][-6:] for e in sink.published] == ["SUBJ-0"]
    assert json.loads(state.read_text())["cursor"] == sink.published[0]["event_id"]

    # The endpoint recovers; the rerun picks up exactly SUBJ-1 and SUBJ-2.
    recovered = RecordingSink()
    assert _run(env, state, recovered) == 2
    assert [e["payload"]["name"][-6:] for e in recovered.published] == ["SUBJ-1", "SUBJ-2"]


def test_state_survives_a_truncated_write(tmp_path: Path) -> None:
    """The cursor is written to a temporary file and renamed, so a crash mid-write cannot
    leave a half-written cursor - which would silently re-deliver the whole log."""
    state = RelayState(path=tmp_path / "s.json", cursor="abc", delivered=7)
    state.save()
    assert not (tmp_path / "s.json.tmp").exists()
    assert RelayState.load(tmp_path / "s.json").cursor == "abc"
    assert RelayState.load(tmp_path / "s.json").delivered == 7


# --- retries and dead-lettering ------------------------------------------------------------


def test_a_retryable_failure_is_retried_then_succeeds() -> None:
    calls = {"n": 0}

    class Flaky:
        name = "flaky"

        def publish(self, event: dict[str, Any]) -> None:
            calls["n"] += 1
            if calls["n"] < 3:
                raise DeliveryError("503", retryable=True)

        def close(self) -> None: ...

    slept: list[float] = []
    deliver(Flaky(), {"event_id": "e"}, max_retries=5, backoff=1.0, sleep=slept.append)
    assert calls["n"] == 3
    assert slept == [1.0, 2.0]  # exponential, not a fixed interval


def test_a_permanent_failure_is_not_retried() -> None:
    """A 400 will still be a 400 in eight seconds, and retrying it delays every event
    queued behind it."""
    calls = {"n": 0}

    class Broken:
        name = "broken"

        def publish(self, event: dict[str, Any]) -> None:
            calls["n"] += 1
            raise DeliveryError("400", retryable=False)

        def close(self) -> None: ...

    with pytest.raises(DeliveryError):
        deliver(Broken(), {"event_id": "e"}, max_retries=5, backoff=0.0, sleep=lambda _s: None)
    assert calls["n"] == 1


def test_without_a_dead_letter_the_relay_stops(env: dict[str, str], tmp_path: Path) -> None:
    _seed(env, 3)
    with pytest.raises(DeliveryError):
        _run(env, tmp_path / "s.json", RecordingSink(fail_on={"SUBJ-1"}, permanent=True))


def test_with_a_dead_letter_the_relay_continues(env: dict[str, str], tmp_path: Path) -> None:
    _seed(env, 3)
    dead = tmp_path / "dead.jsonl"
    sink = RecordingSink(fail_on={"SUBJ-1"}, permanent=True)
    assert _run(env, tmp_path / "s.json", sink, dead_letter=dead) == 3

    assert [e["payload"]["name"][-6:] for e in sink.published] == ["SUBJ-0", "SUBJ-2"]
    records = [json.loads(line) for line in dead.read_text().splitlines()]
    assert len(records) == 1
    assert "refusing" in records[0]["reason"]
    # The whole envelope is kept, so a dead-lettered event can be replayed by hand.
    assert records[0]["event"]["data"]["name"].endswith("SUBJ-1")


# --- where a new subscriber starts ---------------------------------------------------------


def test_initial_cursor_now_skips_history(env: dict[str, str], tmp_path: Path) -> None:
    _seed(env, 3)
    cursor = initial_cursor(env["OPENNGS_DB_URL"], "now")
    state = RelayState(path=tmp_path / "s.json", cursor=cursor)
    state.save()

    sink = RecordingSink()
    assert _run(env, tmp_path / "s.json", sink) == 0

    runner.invoke(app, ["subject", "create", "AFTER"], env=env)
    assert _run(env, tmp_path / "s.json", sink) == 1


def test_initial_cursor_beginning_replays_everything(env: dict[str, str]) -> None:
    _seed(env, 3)
    assert initial_cursor(env["OPENNGS_DB_URL"], "beginning") is None


def test_initial_cursor_now_on_an_empty_log_is_the_beginning(env: dict[str, str]) -> None:
    assert initial_cursor(env["OPENNGS_DB_URL"], "now") is None


# --- filtering -----------------------------------------------------------------------------


def test_a_sink_can_be_narrowed_by_type(env: dict[str, str], tmp_path: Path) -> None:
    _seed(env, 1)
    runner.invoke(app, ["specimen", "create", "SPEC-1", "--subject", "SUBJ-0"], env=env)
    sink = RecordingSink()
    _run(env, tmp_path / "s.json", sink, types=["edge_created"])
    assert [e["type"] for e in sink.published] == ["edge_created"]


# --- the sinks themselves ------------------------------------------------------------------


def test_file_sink_writes_one_json_line_per_event(env: dict[str, str], tmp_path: Path) -> None:
    _seed(env, 2)
    out = tmp_path / "nested" / "events.jsonl"
    assert _run(env, tmp_path / "s.json", FileSink(out)) == 2
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["specversion"] == "1.0"


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(500, True), (503, True), (429, True), (408, True), (400, False), (404, False), (403, False)],
)
def test_webhook_classifies_failures(status: int, retryable: bool) -> None:
    """Whether a failure is worth retrying is the sink's call, and it decides the difference
    between a delayed event and a dead-lettered one."""
    transport = httpx.MockTransport(lambda _request: httpx.Response(status, text="no"))
    sink = WebhookSink("http://example.invalid/hook", transport=transport)
    with pytest.raises(DeliveryError) as caught:
        sink.publish(
            {
                "event_id": "e1",
                "source": "s",
                "type": "t",
                "specversion": "1.0",
                "subject": None,
                "time": "T",
                "datacontenttype": "application/json",
                "valid_time": "V",
                "transaction_time": "TT",
                "recorded_by": None,
                "supersedes": None,
                "supersede_reason": None,
                "payload": {},
            }
        )
    assert caught.value.retryable is retryable
    sink.close()


def test_webhook_sends_structured_cloudevents() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["content_type"] = request.headers["content-type"]
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(204)

    sink = WebhookSink(
        "http://example.invalid/hook",
        headers={"authorization": "Bearer tok"},
        transport=httpx.MockTransport(handler),
    )
    sink.publish(
        {
            "event_id": "e1",
            "source": "openngs-api",
            "type": "entity_created",
            "specversion": "1.0",
            "subject": "sub",
            "time": "T",
            "datacontenttype": "application/json",
            "valid_time": "V",
            "transaction_time": "TT",
            "recorded_by": "airflow",
            "supersedes": None,
            "supersede_reason": None,
            "payload": {"name": "n"},
        }
    )
    assert seen["content_type"] == "application/cloudevents+json"
    assert seen["auth"] == "Bearer tok"
    assert seen["body"]["id"] == "e1"
    assert seen["body"]["data"]["recorded_by"] == "airflow"
    sink.close()


# --- the CLI -------------------------------------------------------------------------------


def test_cli_relay_to_a_file(env: dict[str, str], tmp_path: Path) -> None:
    _seed(env, 2)
    out = tmp_path / "events.jsonl"
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "openngs.cli",
            "event",
            "relay",
            "--sink",
            "file",
            "--path",
            str(out),
            "--state",
            str(tmp_path / "s.json"),
            "--start",
            "beginning",
            "--once",
        ],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", **env},
    )
    assert done.returncode == 0, done.stderr
    assert "delivered 2 events" in done.stdout
    assert len(out.read_text().splitlines()) == 2


def test_cli_relay_rejects_a_sink_without_its_target(env: dict[str, str], tmp_path: Path) -> None:
    for args in (["--sink", "webhook"], ["--sink", "file"], ["--sink", "kafka", "--url", "x"]):
        done = subprocess.run(
            [
                sys.executable,
                "-m",
                "openngs.cli",
                "event",
                "relay",
                *args,
                "--state",
                str(tmp_path / "s.json"),
                "--once",
            ],
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", **env},
        )
        assert done.returncode == 1, args
        assert "error:" in done.stderr
