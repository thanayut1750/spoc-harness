"""Isolated databases keep integration workers away from interactive local runs."""

import os
from uuid import uuid4

import pytest
from psycopg import AsyncConnection, sql
from psycopg.conninfo import make_conninfo


@pytest.fixture
async def postgres_url():
    base = os.getenv("SPOC_TEST_DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not base:
        pytest.skip(
            "Set SPOC_TEST_DATABASE_URL to a Postgres role with CREATEDB for integration tests"
        )
    name = f"spoc_test_{uuid4().hex}"
    admin = await AsyncConnection.connect(base, autocommit=True)
    try:
        await admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        try:
            yield make_conninfo(base, dbname=name)
        finally:
            await admin.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
    finally:
        await admin.close()
