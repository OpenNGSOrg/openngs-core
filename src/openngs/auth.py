"""Bearer-token authentication and coarse authorization for the HTTP interfaces.

The graph carries barcodes, accessions and patient-linked lineage, so an unauthenticated
deployment is only ever safe behind someone else's gateway. This module makes that a
decision a deployer takes on purpose rather than one they inherit by not noticing: a
server with neither tokens configured nor authentication explicitly disabled refuses every
request and says which of the two to do.

Static tokens, deliberately. Validating an OIDC/JWT against a lab's identity provider is
the shape most real deployments will eventually want, but it needs a JWT dependency and a
key-rotation story, and neither is worth committing to before a deployment asks for it.
`Principal` is the seam: swapping in a token verifier that returns one changes nothing
above this module.

Authorization is read versus write, by HTTP method. Per-entity or per-namespace rules are
a later step and would go behind the same `Principal`.
"""

from __future__ import annotations

import hmac
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import HTTPException

# Any mapping of environment variables: os.environ in production, a plain dict in tests.
Env = Mapping[str, str]

READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class Principal:
    """Who is making a request, and how much they may do.

    `name` is what lands in an event's `recorded_by`, so it should say something an auditor
    can act on - a person, a service account - rather than the token itself.
    """

    name: str
    can_write: bool = True

    @property
    def role(self) -> str:
        return "write" if self.can_write else "read"


ANONYMOUS = Principal(name="anonymous", can_write=True)


class AuthConfigError(RuntimeError):
    """The deployment's authentication settings cannot be made sense of."""


def _parse_tokens(raw: str, origin: str) -> dict[str, Principal]:
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AuthConfigError(f"{origin} is not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise AuthConfigError(f"{origin} must be a JSON object mapping token -> principal")
    tokens: dict[str, Principal] = {}
    for token, value in loaded.items():
        if isinstance(value, str):
            tokens[token] = Principal(name=value)
            continue
        if not isinstance(value, dict) or "principal" not in value:
            raise AuthConfigError(
                f"{origin}: token entries must be a principal name, or an object with "
                '"principal" and an optional "role" of "read" or "write"'
            )
        role = value.get("role", "write")
        if role not in ("read", "write"):
            raise AuthConfigError(f'{origin}: role must be "read" or "write", got {role!r}')
        tokens[token] = Principal(name=str(value["principal"]), can_write=role == "write")
    if not tokens:
        raise AuthConfigError(f"{origin} is empty - configure at least one token")
    return tokens


def load_tokens(env: Env | None = None) -> dict[str, Principal] | None:
    """The configured tokens, or None when authentication is off.

    `OPENNGS_AUTH_TOKENS_FILE` wins over `OPENNGS_AUTH_TOKENS`, since a file can be a
    mounted secret while an environment variable is visible to anything that can read the
    process table. Either holds a JSON object:

        {"tok_airflow": "airflow", "tok_dash": {"principal": "grafana", "role": "read"}}

    A bare string is shorthand for write access.
    """
    env = os.environ if env is None else env
    path = env.get("OPENNGS_AUTH_TOKENS_FILE")
    if path:
        try:
            raw = open(path).read()  # noqa: SIM115
        except OSError as exc:
            raise AuthConfigError(
                f"OPENNGS_AUTH_TOKENS_FILE {path!r} cannot be read: {exc}"
            ) from exc
        return _parse_tokens(raw, f"OPENNGS_AUTH_TOKENS_FILE ({path})")
    inline = env.get("OPENNGS_AUTH_TOKENS")
    if inline:
        return _parse_tokens(inline, "OPENNGS_AUTH_TOKENS")
    if env.get("OPENNGS_AUTH_MODE") == "none":
        return None
    raise AuthConfigError(
        "no authentication configured. Set OPENNGS_AUTH_TOKENS (or "
        "OPENNGS_AUTH_TOKENS_FILE) to a JSON object of token -> principal, or set "
        "OPENNGS_AUTH_MODE=none to run without authentication on a trusted network. "
        "Refusing to guess, because the wrong guess exposes the graph."
    )


def _match_token(tokens: dict[str, Principal], presented: str) -> Principal | None:
    """Find the presented token without short-circuiting on the first differing byte.

    A dict lookup would be simpler and would compare the secret with ==, whose running
    time depends on how much of it matched. The leak is small next to network jitter, but
    comparing secrets in constant time costs nothing here: a deployment has a handful of
    tokens, not thousands. Every candidate is compared even after a match, for the same
    reason.
    """
    found: Principal | None = None
    for token, principal in tokens.items():
        if hmac.compare_digest(token, presented):
            found = principal
    return found


def authenticate(method: str, authorization: str | None, env: Env | None = None) -> Principal:
    """Resolve a request's principal, or raise the HTTP error that should be returned.

    A misconfigured server is a 500, not a 401: the caller did nothing wrong and telling
    them to try another credential would be a lie.
    """
    try:
        tokens = load_tokens(env)
    except AuthConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if tokens is None:
        return ANONYMOUS

    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="a bearer token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    principal = _match_token(tokens, authorization[len("bearer ") :].strip())
    if principal is None:
        raise HTTPException(
            status_code=401,
            detail="unknown token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if method.upper() not in READ_ONLY_METHODS and not principal.can_write:
        raise HTTPException(status_code=403, detail=f"principal {principal.name!r} is read-only")
    return principal


def cli_principal(env: Env | None = None) -> str:
    """Who a CLI invocation records itself as: `OPENNGS_PRINCIPAL` if set, otherwise the
    operating-system user. The CLI has no credential to check - anyone who can run it
    already has the database - so this is provenance, not authorization."""
    env = os.environ if env is None else env
    configured = env.get("OPENNGS_PRINCIPAL")
    if configured:
        return configured
    import getpass

    try:
        return getpass.getuser()
    except Exception:  # pragma: no cover - only on an environment with no user at all
        return "unknown"
