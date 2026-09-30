"""Persistence helpers for provenance-preserving provider ingestion."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.settings import configured_database_url


def _database():
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Install psycopg before ingesting provider data") from exc
    url = configured_database_url()
    if not url:
        raise RuntimeError("Set DATABASE_URL or DATABASE_DSN before ingesting provider data")
    return psycopg.connect(url)


def persist_observations(observations: list[Any]) -> dict[str, int]:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("Install psycopg before ingesting provider data") from exc
    inserted = skipped = 0
    with _database() as connection:
        with connection.cursor() as cursor:
            for item in observations:
                if not item.observed_at:
                    skipped += 1
                    continue
                state = item.quality_state
                quality_score = 1.0 if state in {"VALID", "VALID_ZERO"} else 0.25 if item.value is not None else 0.0
                cursor.execute(
                    """INSERT INTO observations
                       (entity_type,entity_id,variable,value,unit,datum,observed_at,source_id,source_record_id,
                        quality_state,quality_score,observation_type,raw_payload)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (source_id,source_record_id,variable,observed_at)
                         WHERE source_record_id IS NOT NULL DO NOTHING
                       RETURNING observation_id,observed_at""",
                    (item.entity_type, item.entity_id, item.variable, item.value, item.unit, item.datum,
                     item.observed_at, item.source_id, item.source_record_id, state, quality_score,
                     item.observation_type, Jsonb({**item.raw_payload, "physics_eligible": item.physics_eligible, "semantic_status": item.semantic_status})),
                )
                row = cursor.fetchone()
                if not row:
                    skipped += 1
                    continue
                cursor.execute(
                    """INSERT INTO observation_quality
                       (observation_id,observed_at,timestamp_ok,range_ok,unit_ok,datum_ok,semantics_ok,reasons)
                       VALUES (%s,%s,true,%s,%s,%s,%s,%s)""",
                    (row[0], row[1], item.value is not None, bool(item.unit), bool(item.datum),
                     item.semantic_status == "VERIFIED" and item.physics_eligible, Jsonb(list(item.reasons))),
                )
                inserted += 1
    return {"inserted": inserted, "skipped_or_duplicate": skipped}


def persist_official_warnings(records: list[Any]) -> dict[str, int]:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("Install psycopg before ingesting provider data") from exc
    from app.services.admin_scope import resolve_scope, scope_table

    inserted = skipped = 0
    with _database() as connection:
        with connection.cursor() as cursor:
            for record in records:
                if not record.observed_at:
                    skipped += 1
                    continue
                row = record.payload.get("row", [])
                message = " | ".join(str(value) for value in row)
                scope = resolve_scope(cursor, message)
                table = scope_table(scope.get("admin_level", "")) if scope.get("resolved") else None
                cursor.execute(
                    """INSERT INTO official_warnings
                       (source_id,provider_warning_id,issued_at,title,message,raw_payload,
                        scope_method,scope_confidence,admin_level,admin_code,scope_text_normalized)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (source_id,provider_warning_id) WHERE provider_warning_id IS NOT NULL
                       DO UPDATE SET issued_at=EXCLUDED.issued_at,title=EXCLUDED.title,
                         message=EXCLUDED.message,raw_payload=EXCLUDED.raw_payload,
                         scope_method=EXCLUDED.scope_method,scope_confidence=EXCLUDED.scope_confidence,
                         admin_level=EXCLUDED.admin_level,admin_code=EXCLUDED.admin_code,
                         scope_text_normalized=EXCLUDED.scope_text_normalized,geom=NULL""",
                    (record.source_id, record.record_id, record.observed_at,
                     str(row[2])[:180] if record.source_id == "dwr_ews_warnings" and len(row) > 2 else
                     str(row[0]) if row else None, message, Jsonb(record.payload),
                     scope.get("scope_method"), scope.get("scope_confidence"), scope.get("admin_level"),
                     scope.get("admin_code"), scope.get("scope_text_normalized")),
                )
                changed = cursor.rowcount
                if table:
                    cursor.execute(
                        f"""UPDATE official_warnings w SET geom=a.geom FROM {table[0]} a
                            WHERE w.source_id=%s AND w.provider_warning_id=%s AND a.{table[1]}=%s""",
                        (record.source_id, record.record_id, scope["admin_code"]),
                    )
                inserted += changed
                if not changed:
                    skipped += 1
    return {"inserted": inserted, "skipped": skipped}


def persist_catalog_schema(source_id: str, resources: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        from psycopg.types.json import Jsonb
    except ImportError as exc:
        raise RuntimeError("Install psycopg before saving source schema metadata") from exc
    encoded = json.dumps(resources, ensure_ascii=False, sort_keys=True)
    import hashlib
    version = "catalog:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    with _database() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """INSERT INTO source_schema_versions(source_id,schema_version,valid_from,schema_definition,parser_version)
                   VALUES (%s,%s,now(),%s,'1') ON CONFLICT (source_id,schema_version) DO NOTHING""",
                (source_id, version, Jsonb({"resource_count": len(resources), "resources": resources})),
            )
    return {"schema_version": version, "resources": len(resources)}


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)
    except ValueError:
        return None
