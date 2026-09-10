"""Server-side settings and the per-request `Database` dependency, shared by `api.py` (REST,
Phase 3) and `graphql_schema.py` (GraphQL, Phase 4) - split out so neither has to import the
other just to get at this. Same three env vars the CLI already reads
(`OPENNGS_ORG`/`OPENNGS_NAMESPACE`/`OPENNGS_DB_URL`); a deployment serves one lab's
namespace, the same way one CLI invocation's env already does.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request

from openngs.auth import Principal, authenticate
from openngs.store import Database
from openngs.store.db import DEFAULT_DB_URL


@dataclass
class Settings:
    org: str | None
    ns: str | None
    db_url: str


def get_settings() -> Settings:
    """Read fresh on every call, not cached at import/startup - tests set env vars per
    request via monkeypatch, and a long-lived server process re-reading os.environ costs
    nothing measurable per request."""
    return Settings(
        org=os.environ.get("OPENNGS_ORG"),
        ns=os.environ.get("OPENNGS_NAMESPACE"),
        db_url=os.environ.get("OPENNGS_DB_URL", DEFAULT_DB_URL),
    )


def get_validated_settings(
    settings: Annotated[Settings, Depends(get_settings)],
) -> tuple[str, str, str]:
    """(db_url, org, ns) with org/ns confirmed present - no connection opened.
    The REST
       dependency below builds on this by also opening one; the GraphQL context_getter uses
       this directly instead, deliberately *not* sharing one connection across a whole
       query's resolver tree - see graphql_schema.py's module docstring for why."""
    if not settings.org or not settings.ns:
        raise HTTPException(
            status_code=500,
            detail="OPENNGS_ORG and OPENNGS_NAMESPACE must both be set on the server",
        )
    return settings.db_url, settings.org, settings.ns


ValidatedSettings = Annotated[tuple[str, str, str], Depends(get_validated_settings)]


def get_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Authenticate the request, and decide read versus write from the HTTP method.

    One dependency rather than a decorator on each route: `get_db_ctx` below depends on it,
    every route depends on that, and so a route added later cannot forget to authenticate.
    """
    return authenticate(request.method, authorization)


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def get_read_principal(
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    """Authenticate a request that only ever reads, whatever HTTP method it arrived by.

    GraphQL is the reason this exists: it is query-only by construction (no
    mutations) but every query is a POST, so judging read-versus-write by method alone
    would refuse a read-only token the one interface built for reading. Authorization is
    about what the request can do, and this one can only read.
    """
    return authenticate("GET", authorization)


ReadPrincipal = Annotated[Principal, Depends(get_read_principal)]


def get_db_ctx(
    settings: ValidatedSettings,
    principal: CurrentPrincipal,
) -> Iterator[tuple[Database, str, str]]:
    """One Database connection per request, commit-or-rollback on the way out - the same
    lifecycle `with Database.connect(...) as db:` gives the CLI, just as a FastAPI
    dependency so every REST route doesn't repeat it. Safe here because a REST request
    handler runs as a single blocking call on a single thread; not safe for GraphQL - see
    `get_validated_settings` and graphql_schema.py."""
    db_url, org, ns = settings
    # The principal rides on the connection, so every event this request emits records who
    # was behind it without any write path having to pass it along (Event.recorded_by).
    with Database.connect(db_url, recorded_by=principal.name) as db:
        yield db, org, ns


DbCtx = Annotated[tuple[Database, str, str], Depends(get_db_ctx)]
