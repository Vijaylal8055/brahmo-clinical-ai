"""Audit events for the prototype.

Backends (in order of preference):
  1. Supabase (durable) — when SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY are set
  2. In-memory ring buffer (always; works on Streamlit Community Cloud for current process)
  3. Local SQLite (local dev only; not durable on Community Cloud)

Schema expected in Supabase (see supabase/schema.sql):

  audit_events(id, event_type, event_status, details jsonb, app_version, created_at)
  source_versions(id, source_name, version_label, content_hash, status, created_at)

Do not store patient-identifiable information.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from brahmo import __version__ as APP_VERSION

_MEMORY_EVENTS: List[Dict[str, Any]] = []
_MEMORY_LIMIT = 200

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "audit_demo.sqlite"

logger = logging.getLogger("brahmo.audit")

_supabase_client = None
_supabase_init_attempted = False
_supabase_cache_key: Optional[tuple] = None
_supabase_init_error: Optional[str] = None
_last_supabase_error: Optional[str] = None


def _get_supabase():
    """Lazy-init Supabase client from Streamlit secrets or environment variables."""
    global _supabase_client, _supabase_init_attempted, _supabase_init_error
    global _supabase_cache_key

    url = None
    key = None

    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            url = st.secrets.get("SUPABASE_URL") or st.secrets.get("supabase_url")
            key = (
                st.secrets.get("SUPABASE_SERVICE_ROLE_KEY")
                or st.secrets.get("SUPABASE_KEY")
                or st.secrets.get("supabase_service_role_key")
            )
    except Exception:
        pass

    url = url or os.environ.get("SUPABASE_URL")
    key = key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")

    if not url or not key:
        _supabase_init_error = "SUPABASE_URL or key missing in secrets/env"
        _supabase_client = None
        _supabase_cache_key = None
        return None

    url = str(url).strip()
    key = str(key).strip()

    # Rebuild the client whenever the URL or key changes (e.g. secrets edited).
    if _supabase_client is not None and _supabase_cache_key == (url, key):
        return _supabase_client
    _supabase_init_attempted = True
    _supabase_cache_key = (url, key)

    try:
        from supabase import create_client
        _supabase_client = create_client(url, key)
        return _supabase_client
    except Exception as exc:
        _supabase_init_error = f"{type(exc).__name__}: {exc}"[:300]
        logger.error("Supabase client init failed: %s", _supabase_init_error)
        _supabase_client = None
        return None


def supabase_last_error() -> Optional[str]:
    """Most recent init/insert error, for display in the UI."""
    return _last_supabase_error or _supabase_init_error


def supabase_diagnose() -> Dict[str, Any]:
    """Round-trip test: insert a row into audit_events, read it back, report errors."""
    report: Dict[str, Any] = {"client_created": False, "insert_ok": False, "select_ok": False}
    client = _get_supabase()
    if client is None:
        report["error"] = _supabase_init_error or "client not created"
        return report
    report["client_created"] = True
    try:
        client.table("audit_events").insert(
            {
                "event_type": "diagnostic_ping",
                "event_status": "OK",
                "details": {"prototype": True},
                "app_version": APP_VERSION,
            }
        ).execute()
        report["insert_ok"] = True
    except Exception as exc:
        report["insert_error"] = f"{type(exc).__name__}: {exc}"[:500]
    try:
        client.table("audit_events").select("id").limit(1).execute()
        report["select_ok"] = True
    except Exception as exc:
        report["select_error"] = f"{type(exc).__name__}: {exc}"[:500]
    return report


def supabase_configured() -> bool:
    return _get_supabase() is not None


def _try_db_connect() -> Optional[sqlite3.Connection]:
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=2)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                id TEXT PRIMARY KEY,
                ts REAL NOT NULL,
                event_type TEXT NOT NULL,
                event_status TEXT NOT NULL DEFAULT 'RECORDED',
                payload TEXT NOT NULL
            )
            """
        )
        conn.commit()
        return conn
    except Exception:
        return None


def write_audit_event(
    event_type: str,
    payload: Dict[str, Any],
    *,
    event_status: str = "RECORDED",
) -> str:
    """Append an audit event. Never include PHI in payload."""
    event_id = str(uuid.uuid4())
    ts = time.time()
    safe_payload = {"prototype": True, **payload}

    record = {
        "id": event_id,
        "ts": ts,
        "event_type": event_type,
        "event_status": event_status,
        "payload": safe_payload,
    }
    _MEMORY_EVENTS.append(record)
    if len(_MEMORY_EVENTS) > _MEMORY_LIMIT:
        del _MEMORY_EVENTS[:-_MEMORY_LIMIT]

    client = _get_supabase()
    if client is not None:
        try:
            client.table("audit_events").insert(
                {
                    "event_type": event_type,
                    "event_status": event_status,
                    "details": safe_payload,
                    "app_version": APP_VERSION,
                }
            ).execute()
        except Exception as exc:
            global _last_supabase_error
            _last_supabase_error = f"{type(exc).__name__}: {exc}"[:500]
            logger.error("Supabase audit insert failed: %s", _last_supabase_error)
            record["payload"]["_supabase_error"] = str(exc)[:200]

    conn = _try_db_connect()
    if conn is not None:
        try:
            conn.execute(
                "INSERT INTO audit_events (id, ts, event_type, event_status, payload) VALUES (?, ?, ?, ?, ?)",
                (event_id, ts, event_type, event_status, json.dumps(safe_payload, default=str)),
            )
            conn.commit()
        except Exception:
            pass
        finally:
            conn.close()

    return event_id


def recent_audit_events(limit: int = 25) -> List[Dict[str, Any]]:
    """Prefer Supabase, else memory, else local SQLite."""
    client = _get_supabase()
    if client is not None:
        try:
            resp = (
                client.table("audit_events")
                .select("id, event_type, event_status, details, app_version, created_at")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            rows = []
            for row in resp.data or []:
                details = row.get("details") or {}
                rows.append(
                    {
                        "id": row.get("id"),
                        "ts": row.get("created_at"),
                        "event_type": row.get("event_type"),
                        "event_status": row.get("event_status"),
                        "app_version": row.get("app_version"),
                        "payload": json.dumps(details, default=str)[:500],
                    }
                )
            if rows:
                return rows
        except Exception:
            pass

    if _MEMORY_EVENTS:
        rows = []
        for r in reversed(_MEMORY_EVENTS[-limit:]):
            rows.append(
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "event_type": r["event_type"],
                    "event_status": r.get("event_status", "RECORDED"),
                    "app_version": APP_VERSION,
                    "payload": json.dumps(r["payload"], default=str)[:500],
                }
            )
        return rows

    conn = _try_db_connect()
    if conn is None:
        return []
    try:
        cur = conn.execute(
            "SELECT id, ts, event_type, event_status, payload FROM audit_events ORDER BY ts DESC LIMIT ?",
            (limit,),
        )
        return [
            {
                "id": row[0],
                "ts": row[1],
                "event_type": row[2],
                "event_status": row[3],
                "app_version": APP_VERSION,
                "payload": (row[4] or "")[:500],
            }
            for row in cur.fetchall()
        ]
    except Exception:
        return []
    finally:
        conn.close()


def register_source_version(
    source_name: str,
    version_label: str,
    *,
    content_hash: Optional[str] = None,
    status: str = "DRAFT",
) -> bool:
    client = _get_supabase()
    if client is None:
        return False
    try:
        client.table("source_versions").upsert(
            {
                "source_name": source_name,
                "version_label": version_label,
                "content_hash": content_hash,
                "status": status,
            },
            on_conflict="source_name,version_label",
        ).execute()
        return True
    except Exception:
        return False


def list_source_versions(limit: int = 50) -> List[Dict[str, Any]]:
    client = _get_supabase()
    if client is None:
        return []
    try:
        resp = (
            client.table("source_versions")
            .select("id, source_name, version_label, content_hash, status, created_at")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(resp.data or [])
    except Exception:
        return []
    