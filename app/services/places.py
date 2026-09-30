"""Search a local cache of official tambon reference points."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from app.settings import ROOT
from app.settings import configured_database_url


@lru_cache(maxsize=1)
def _places() -> list[dict]:
    path = ROOT / "data" / "static" / "places" / "tambons.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["places"]


def _normalize(value: str) -> str:
    value = re.sub(r"\s+", "", value.casefold())
    return re.sub(r"(จังหวัด|อำเภอ|ตำบล|แขวง|เขต|จ\.|อ\.|ต\.)", "", value)


def search_places(query: str, limit: int = 12) -> dict:
    term = _normalize(query)
    if not term:
        return {"query": query, "items": [], "total": 0, "source": "GISTDA/DOPA tambon reference points"}
    tokens = [_normalize(part) for part in re.split(r"[\s,]+", query) if _normalize(part)]
    try:
        import psycopg
        from psycopg.rows import dict_row

        clauses = ["(tam_name_th ILIKE %s OR amp_name_th ILIKE %s OR prov_name_th ILIKE %s)" for _ in tokens]
        params = [f"%{token}%" for token in tokens for _ in range(3)]
        with psycopg.connect(configured_database_url(), connect_timeout=3, row_factory=dict_row) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT count(*) AS total FROM admin_tambon WHERE " + " AND ".join(clauses), params)
                total = cursor.fetchone()["total"]
                cursor.execute(
                    """SELECT tam_code,tam_name_th,amp_name_th,prov_name_th,
                              ST_Y(ST_PointOnSurface(geom)) AS lat,
                              ST_X(ST_PointOnSurface(geom)) AS lon
                       FROM admin_tambon WHERE """ + " AND ".join(clauses) +
                    " ORDER BY CASE WHEN tam_name_th=%s THEN 0 WHEN tam_name_th ILIKE %s THEN 1 ELSE 2 END,"
                    " prov_name_th,amp_name_th,tam_name_th LIMIT %s",
                    (*params, term, f"{term}%", limit),
                )
                rows = cursor.fetchall()
        items = [{"tam_code": row["tam_code"], "tambon": row["tam_name_th"],
                  "amphoe": row["amp_name_th"], "province": row["prov_name_th"],
                  "lat": row["lat"], "lon": row["lon"],
                  "label": f"{row['tam_name_th']} · {row['amp_name_th']} · {row['prov_name_th']}"}
                 for row in rows]
        return {"query": query, "items": items, "total": total,
                "source": "DPM administrative polygons", "reference_only": True}
    except (ImportError, OSError, ValueError, TypeError):
        pass
    except Exception:
        pass
    matches = []
    for place in _places():
        tambon = _normalize(place.get("tambon") or "")
        amphoe = _normalize(place.get("amphoe") or "")
        province = _normalize(place.get("province") or "")
        combined = tambon + amphoe + province
        if not (term in combined or all(any(token in field for field in (tambon, amphoe, province)) for token in tokens)):
            continue
        score = 0 if tambon == term else 1 if tambon.startswith(term) else 2 if term in tambon else 3
        label = f"{place['tambon']} · {place['amphoe']} · {place['province']}"
        matches.append((score, label, {**place, "label": label}))
    matches.sort(key=lambda item: (item[0], item[1]))
    return {"query": query, "items": [item[2] for item in matches[:limit]], "total": len(matches),
            "source": "GISTDA/DOPA tambon reference points", "reference_only": True}
