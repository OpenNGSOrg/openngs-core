# Authentication and access control

How to secure an OpenNGS deployment, what the protection actually covers, and what it
does not. Read the last section before putting this anywhere real.

## The short version

The HTTP interfaces (REST, GraphQL, and the MCP server in front of them) authenticate
**static bearer tokens**. Each token maps to a **principal**, a name that lands on every
event that token writes. Each principal is either read-only or read-write.

A server must be told which it is doing. One of these has to be set, or it refuses every
request:

```bash
# Tokens: a JSON object of token -> principal.
export OPENNGS_AUTH_TOKENS='{"tok-airflow":"airflow"}'

# Or, for anything with real secrets, a file that can be a mounted secret.
export OPENNGS_AUTH_TOKENS_FILE=/run/secrets/openngs-tokens.json

# Or, explicitly, no authentication at all.
export OPENNGS_AUTH_MODE=none
```

There is no default. A server with none of them set answers every request with a 500
saying so. That is deliberate: this graph holds barcodes, accessions and patient-linked
lineage, and both possible defaults are worse than making someone decide. Defaulting open
means a mistyped token path silently serves everything; defaulting closed with no way to
opt out would misrepresent what this release can enforce.

## Configuring tokens

### The token file

`OPENNGS_AUTH_TOKENS_FILE` is preferred over `OPENNGS_AUTH_TOKENS`: a file can be a
Kubernetes secret or a Docker secret with restrictive permissions, while an environment
variable is visible to anything that can read the process table.

```json
{
  "9f2a...": "airflow",
  "4c81...": { "principal": "grafana", "role": "read" },
  "b70e...": { "principal": "jdoe", "role": "write" }
}
```

A bare string is shorthand for `{"principal": ..., "role": "write"}`.

The **key is the secret**; the value is the name you want to see in the audit trail. Give
each integration and each person their own token, so a compromised one can be withdrawn
without disturbing anything else, and so `recorded_by` says something useful.

### Generating a token

OpenNGS does not generate tokens. Use anything with real entropy:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Never reuse a token across environments, and never commit one. The example tokens in
`docker-compose.yml` are for local development only and are not secret by definition,
since they are in the repository.

### Rotating a token

Add the new token alongside the old one, move clients over, then remove the old one.
Configuration is read fresh on every request, so a change to `OPENNGS_AUTH_TOKENS_FILE`
takes effect on the next request with no restart. Changing an environment variable does
require restarting the process.

There is no expiry, no revocation list and no refresh: a token is valid until you remove
it from the configuration.

## Making requests

```bash
curl -H "Authorization: Bearer 9f2a..." http://localhost:8000/subjects
```

| Response | Meaning |
|---|---|
| **401** | No `Authorization: Bearer` header, or a token that is not configured |
| **403** | A read-only principal attempted a write |
| **500** | The server has made no authentication decision, or its token file is unreadable or malformed |

A 500 here is about the server, not about you: the message says exactly which setting is
missing or wrong. It is not a 401 because retrying with a different credential cannot help.

## Roles

Two roles, decided by HTTP method: `GET`, `HEAD` and `OPTIONS` are reads, everything else
is a write.

`/graphql` is the one exception. It is query-only by construction, with no mutations, but
every GraphQL query arrives as a `POST`, so it is authorized as a **read**. A read-only
token can therefore run any GraphQL query, which is the intended behaviour: GraphQL is the
interface built for reading.

Per-entity and per-namespace rules do not exist. A principal that can read, can read
everything in the namespace the server serves; a principal that can write, can write
anything in it.

## The audit trail

Every event carries `recorded_by`, the principal behind the write:

```bash
curl -H "Authorization: Bearer 9f2a..." "localhost:8000/events?limit=1"
```

```json
{"event_id": "...", "source": "openngs-api", "recorded_by": "airflow", "type": "entity_created", "...": "..."}
```

`source` and `recorded_by` answer different questions. `source` is which program produced
the event (`openngs-api`, `openngs-cli`). `recorded_by` is who was behind it. An auditor
asking "who changed this" wants the second.

With `OPENNGS_AUTH_MODE=none` the principal is `anonymous`. That is an honest answer, not
a placeholder: the deployment genuinely does not know.

## Each interface

**REST and GraphQL** authenticate as described above.

**The MCP server** is a client of the REST API like any other. Set `OPENNGS_MCP_TOKEN` to a
token the API knows, and give it a principal of its own (`"mcp"`), so `recorded_by` says
which door a write came through. Note what this does and does not mean: the credential
belongs to the MCP server, not to whoever is talking to it. OpenNGS cannot tell one
agent's user from another's, so anything the MCP server can do, every one of its clients
can do.

**The CLI does not authenticate at all**, and this is the most important thing on this
page. See below.

## What this protects, and what it does not

Authentication guards **the HTTP interfaces**. It is not a boundary around your data.

- **The CLI bypasses it completely.** `openngs` connects straight to the database. Anyone
  who can read `openngs.db`, or who has the Postgres credentials, can read and write the
  entire graph with no token, whatever the API is configured to require. Configuring
  tokens does not protect the database; file permissions and database credentials do.
  Treat access to `OPENNGS_DB_URL` as equivalent to full write access.
- **There is no TLS.** `make api` and the container image serve plain HTTP. A bearer token
  sent over plain HTTP is readable by anything on the path. Terminate TLS in front of
  OpenNGS: an ingress, a reverse proxy, or a service mesh.
- **`/docs`, `/redoc`, `/openapi.json` and `/health` need no token.** The shape of the API
  is public; none of your data is. If even the shape matters, block those paths at your
  proxy.
- **GraphiQL needs a token to load.** Opening `/graphql` in a browser returns 401 on a
  secured deployment, because the interactive editor is served from the same authenticated
  route. Use a client that can set a header, or explore against an unsecured development
  instance.
- **No rate limiting, no lockout, no audit of failed attempts.** A brute-force attempt
  against the token endpoint is not slowed down or recorded. Use tokens with real entropy,
  and put a proxy in front if you need throttling.
- **Tokens do not expire.** There is no session, no refresh, and no revocation beyond
  editing the configuration.
- **No identity provider, and there will not be one.** Authenticating a person is
  deliberately out of scope: OpenNGS has no user table, no passwords and no sessions, and
  will not validate credentials against a directory. That belongs to a gateway, a proxy, or
  your SSO. What is planned is a contract for accepting the principal such a gateway
  establishes, so it reaches `recorded_by`
  ([#27](https://github.com/OpenNGSOrg/openngs-core/issues/27)); the internal `Principal` type is
  the seam. **A deployment carrying PHI must run a gateway in front of OpenNGS.** The static
  tokens here are for machines — a pipeline hook, the relay, an Airflow task — not people.
- **Reads are not audited.** Every write records `recorded_by`; no read records anything.
  "Who looked at this patient's record" is not a question this release can answer
  ([#28](https://github.com/OpenNGSOrg/openngs-core/issues/28)).

## Deployment patterns

**Local development.** `export OPENNGS_AUTH_MODE=none`. Nothing is exposed beyond your
machine, and the database file is already the real boundary.

**Docker Compose.** `docker-compose.yml` ships example tokens inline so the stack starts.
Replace them before it is reachable by anything you do not control, and prefer a file:

```yaml
services:
  api:
    environment:
      OPENNGS_AUTH_TOKENS_FILE: /run/secrets/openngs-tokens
    secrets:
      - openngs-tokens
secrets:
  openngs-tokens:
    file: ./tokens.json
```

**Kubernetes.** Mount a `Secret` and point `OPENNGS_AUTH_TOKENS_FILE` at it. Terminate TLS
at the ingress. Keep the Postgres credentials at least as well protected as the tokens,
since they grant strictly more (see above).

**Dashboards and analysis.** Give the BI tool a read-only token, not a write one. If it
queries the database directly rather than through the API, give it a read-only database
role instead; that is tracked as
[#22](https://github.com/OpenNGSOrg/openngs-core/issues/22).

## Troubleshooting

**Everything returns 500 with a message about `OPENNGS_AUTH_MODE`.** The server has not
been told what to do. Set tokens, or set `OPENNGS_AUTH_MODE=none`.

**Everything returns 401 with a token I am sure is right.** Check the header is
`Authorization: Bearer <token>` and that the token is a key in the JSON object, not a
value. If you are using a file, check the process can read it: an unreadable file is a 500,
but a file containing a *different* object is a clean 401.

**Writes return 403.** The token's role is `read`. Roles are per token, so check which one
the client is sending.

**GraphiQL will not load in a browser.** Expected on a secured deployment; the editor is
behind the same authentication as the queries.

**Events say `recorded_by: anonymous`.** The server is running with
`OPENNGS_AUTH_MODE=none`, or the write came from the CLI without `OPENNGS_PRINCIPAL` set.
