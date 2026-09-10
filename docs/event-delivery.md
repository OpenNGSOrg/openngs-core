# Event delivery

Every write in OpenNGS appends a CloudEvents record to an append-only log. This page is
about getting those events *out* — to an orchestrator, a results service, a notifier.

There are two ways, and they are the same mechanism seen from different sides.

**Poll it yourself.** `GET /events?after=<last event you handled>` is a range scan over the
log's primary key. The log is append-only, so an event already returned never moves and a
new one only ever appears after your cursor. Keep the last `event_id` you processed and
you have a correct, resumable subscription with no extra moving parts.

**Let OpenNGS push.** `openngs event relay` does exactly that polling for you and publishes
each event to a sink. Use it when the consumer would rather receive than ask.

The relay is an ordinary consumer that ships with the project. It reads what `GET /events`
returns and nothing more — a sink is never privileged — and it never writes to the log.

## Running a relay

```bash
openngs event relay --sink webhook --url https://consumer.example/openngs
```

```bash
openngs event relay --sink file --path ./events.jsonl
```

It runs in the foreground until stopped. `--once` delivers whatever is waiting and exits,
which is what you want from cron, or from a test.

| Option | Default | Meaning |
|---|---|---|
| `--sink` | `webhook` | `webhook` or `file` |
| `--url` | | The endpoint, for `--sink webhook` |
| `--path` | | The JSONL file, for `--sink file` |
| `--state` | `openngs-relay.json` | Where this subscriber's cursor is kept |
| `--start` | `now` | On the first run only: `now`, `beginning`, or an `event_id` |
| `--poll-interval` | `5.0` | Seconds between polls when the log is quiet |
| `--batch-size` | `100` | Events read per poll |
| `--max-retries` | `5` | Retries per event before it fails |
| `--dead-letter` | | Record undeliverable events here and keep going |
| `--type` | | Only these event types, repeatable |
| `--source` | | Only events from this producer |
| `--header` | | Extra HTTP header, `Name: value`, repeatable |
| `--once` | off | Deliver what is waiting, then exit |

Give each subscriber its own `--state` file. Two relays feeding two systems are two
independent positions in the log.

## The delivery guarantee

The cursor advances **only after a sink reports success**:

```
read a batch after the cursor
  for each event:
      publish it
      advance the cursor      <- only now
```

So a crash, a kill, or a failed send leaves the cursor on the last *delivered* event, and
everything after it is sent again. Delivery is **at-least-once**.

**Your consumer must deduplicate.** A timeout where the request actually landed is
indistinguishable from one where it did not, so the relay sends again. The CloudEvents `id`
is the stored `event_id` and is stable across redeliveries — key on it.

Ordering is per relay: one relay delivers in log order, and two relays are independent.

## What arrives

CloudEvents 1.0 in structured mode: `content-type: application/cloudevents+json`, and the
whole envelope as the body.

```json
{
  "specversion": "1.0",
  "id": "01a086a6-6eba-7322-bcc8-fca47e157ff1",
  "source": "openngs-cli",
  "type": "entity_created",
  "subject": "01a086a6-6eba-7322-bcc8-fca315d51b47",
  "time": "2026-09-09T14:50:49.401619+00:00",
  "datacontenttype": "application/json",
  "data": {
    "entity_type": "Subject",
    "internal_id": "01a086a6-6eba-7322-bcc8-fca315d51b47",
    "name": "openngs://acme-genomics/core-lab/subject/SUBJ-001",
    "xrefs": [],
    "valid_time": "2026-09-09T14:50:49.401619+00:00",
    "transaction_time": "2026-09-09T14:50:49.401619+00:00",
    "recorded_by": "pauloburke"
  }
}
```

The top level carries CloudEvents attributes and nothing else. OpenNGS's own fields —
`valid_time`, `transaction_time`, `recorded_by`, and `supersedes`/`supersede_reason` on a
correction — live in `data`, because a CloudEvents extension attribute may only be
lowercase alphanumeric and `valid_time` is not a legal name.

`source` says which program produced the event (`openngs-api`, `openngs-cli`);
`recorded_by` says which principal was behind it. `subject` is the record the event is
about, and is absent on the few events that describe no single record.

## When delivery fails

A sink decides whether a failure is worth retrying. For the webhook sink:

| Response | Treated as |
|---|---|
| 2xx | delivered |
| 5xx, connection refused, timeout | retryable — exponential backoff, up to `--max-retries` |
| 408, 429 | retryable |
| other 4xx | permanent — no retries |

A 400 will still be a 400 after eight seconds of backoff, and retrying it only delays every
event behind it.

**When an event finally cannot be delivered**, what happens depends on whether you said
where to put it:

- **With `--dead-letter PATH`**, the event is written there whole, with the reason, and the
  cursor moves past it. One bad event cannot wedge the stream.
- **Without it, the relay stops.** Nothing is skipped, and nothing after the failure is
  marked delivered.

That asymmetry is deliberate. Skipping an event is only safe when there is a record that it
was skipped; a relay that silently advanced past failures would look exactly like one that
was working. Dead-lettered records hold the full envelope, so they can be replayed by hand
once the consumer is fixed.

## Where a new subscriber starts

`--start` applies only when the state file does not yet exist.

- **`now`** (default) — deliver only what happens from here. Pointing a fresh relay at an
  established database would otherwise replay its whole history at your endpoint.
- **`beginning`** — deliver the entire log. This is the backfill.
- **`<event_id>`** — resume after a specific event, for a subscriber whose state file was
  lost but whose last processed id is known.

## Filtering

```bash
openngs event relay --sink webhook --url https://... \
  --type entity_created --type edge_created --source openngs-api
```

Filtering happens in the query, so filtered-out events are never read. The cursor still
advances past them: it is a position in the log, not a count of what was sent.

## Deployment notes

The relay is a foreground process with no supervision, restart policy or metrics of its
own — run it under whatever already supervises your services. It needs database access
(`OPENNGS_DB_URL`), which is full read access to the graph; see
[authentication](authentication.md) on what that means.

Point the webhook at something that terminates TLS. The relay sends whatever `--header`
values you give it, which is where an auth token for the consumer goes:

```bash
openngs event relay --sink webhook --url https://consumer.example/openngs \
  --header "Authorization: Bearer $CONSUMER_TOKEN" \
  --state /var/lib/openngs/results-relay.json \
  --dead-letter /var/lib/openngs/results-dead.jsonl
```

A broker sink (Kafka, NATS) is not built; it is tracked as
[#23](https://github.com/OpenNGSOrg/openngs-core/issues/23). The `Sink` protocol in
`src/openngs/sinks/` is the whole of what one has to satisfy.
