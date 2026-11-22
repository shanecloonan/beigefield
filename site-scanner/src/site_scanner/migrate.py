"""Apply the site_scan_hits migration with a database credential.

The service-role key can read and write rows. It cannot create the table.
DDL uses DATABASE_URL, SUPABASE_DB_PASSWORD, or SUPABASE_ACCESS_TOKEN.
Passwords stay in the process environment and are never printed.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from site_scanner.store import probe_store

PROJECT_REF = "soswwsvunulnhlcitpwl"
DB_HOST = "db.%s.supabase.co" % PROJECT_REF
SQL_NAME = "20261122120000_site_scan_hits.sql"


def ddl_flags(env: dict[str, str] | None = None) -> dict[str, bool]:
    source = env if env is not None else os.environ
    return {
        "database_url": bool((source.get("DATABASE_URL") or "").strip()),
        "db_password": bool((source.get("SUPABASE_DB_PASSWORD") or "").strip()),
        "access_token": bool((source.get("SUPABASE_ACCESS_TOKEN") or "").strip()),
    }


def missing_ddl_secrets(env: dict[str, str] | None = None) -> list[str]:
    flags = ddl_flags(env)
    missing: list[str] = []
    if not flags["database_url"] and not flags["db_password"]:
        missing.append("DATABASE_URL or SUPABASE_DB_PASSWORD")
    if not flags["access_token"]:
        missing.append("SUPABASE_ACCESS_TOKEN")
    return missing


def pg_env(env: dict[str, str] | None = None) -> dict[str, str] | None:
    """libpq environment for psql. None when no direct credential is set."""
    source = env if env is not None else os.environ
    database_url = (source.get("DATABASE_URL") or "").strip()
    if database_url:
        parsed = urllib.parse.urlparse(database_url)
        if not parsed.hostname:
            return None
        database = (parsed.path or "/postgres").lstrip("/") or "postgres"
        return {
            "PGHOST": parsed.hostname,
            "PGPORT": str(parsed.port or 5432),
            "PGUSER": urllib.parse.unquote(parsed.username or "postgres"),
            "PGPASSWORD": urllib.parse.unquote(parsed.password or ""),
            "PGDATABASE": database,
            "PGSSLMODE": "require",
        }
    password = (source.get("SUPABASE_DB_PASSWORD") or "").strip()
    if not password:
        return None
    user = (source.get("SUPABASE_DB_USER") or "postgres").strip() or "postgres"
    database = (source.get("SUPABASE_DB_NAME") or "postgres").strip() or "postgres"
    port = (source.get("SUPABASE_DB_PORT") or "5432").strip() or "5432"
    if not port.isdigit():
        return None
    return {
        "PGHOST": DB_HOST,
        "PGPORT": port,
        "PGUSER": user,
        "PGPASSWORD": password,
        "PGDATABASE": database,
        "PGSSLMODE": "require",
    }


def _apply_psql(sql_path: str, child_env: dict[str, str]) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["psql", "-v", "ON_ERROR_STOP=1", "-f", sql_path],
            env=child_env,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return {"path": "psql", "status": "missing-binary"}
    return {"path": "psql", "status": "ok" if result.returncode == 0 else "error", "exit": result.returncode}


def _apply_api(sql: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        "https://api.supabase.com/v1/projects/%s/database/query" % PROJECT_REF,
        data=json.dumps({"query": sql}).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": "Bearer %s" % token,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "beigefield-site-scanner/0.1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        return {"path": "management-api", "status": "error", "http": int(exc.code)}
    except Exception:
        return {"path": "management-api", "status": "error", "http": 0}
    return {"path": "management-api", "status": "ok" if status < 300 else "error", "http": status}


def apply_sql(sql_path: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run the migration. The report names paths and statuses, never secret values."""
    source = dict(os.environ if env is None else env)
    attempts: list[dict[str, Any]] = []
    libpq = pg_env(source)
    if libpq:
        child = dict(os.environ)
        child.update(libpq)
        attempts.append(_apply_psql(sql_path, child))
    token = (source.get("SUPABASE_ACCESS_TOKEN") or "").strip()
    if token and not any(item.get("status") == "ok" for item in attempts):
        sql = open(sql_path, encoding="utf-8").read()
        attempts.append(_apply_api(sql, token))
    if not attempts:
        return {"status": "missing-secrets", "missing": missing_ddl_secrets(source), "attempts": []}
    ok = any(item.get("status") == "ok" for item in attempts)
    return {"status": "ok" if ok else "error", "missing": missing_ddl_secrets(source), "attempts": attempts}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="site-scanner-migrate")
    parser.add_argument("--sql", default="supabase/migrations/%s" % SQL_NAME)
    args = parser.parse_args()
    before = probe_store()
    flags = ddl_flags()
    if flags["database_url"] or flags["db_password"] or flags["access_token"]:
        applied = apply_sql(args.sql)
    elif before.get("status") == "ok":
        applied = {
            "status": "already-readable",
            "missing": missing_ddl_secrets(),
            "note": "site_scan_hits is readable. DDL secrets are unset, so this job did not reapply the SQL.",
        }
    else:
        applied = {"status": "missing-secrets", "missing": missing_ddl_secrets()}
    after = probe_store()
    print(json.dumps({"before": before, "apply": applied, "after": after}))


if __name__ == "__main__":
    main()
