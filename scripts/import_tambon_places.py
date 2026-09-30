"""Cache official GISTDA/DOPA tambon reference points for fast Thai place search."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

from app.settings import ROOT

SOURCE = "https://gistdaportal.gistda.or.th/data/rest/services/opendata/Tambon/MapServer/0/query"
FIELDS = "OBJECTID,TA_ID,TAMBON_T,AMPHOE_T,CHANGWAT_T,LAT,LONG"


def request(**params):
    url = SOURCE + "?" + urlencode({**params, "f": "json"})
    with urlopen(url, timeout=30) as response:
        payload = json.load(response)
    if payload.get("error"):
        raise RuntimeError(f"GISTDA tambon query failed: {payload['error'].get('message')}")
    return payload


def main() -> None:
    ids = request(where="1=1", returnIdsOnly="true").get("objectIds", [])
    if not ids:
        raise RuntimeError("Official tambon source returned no object IDs")
    records = []
    for offset in range(0, len(ids), 200):
        chunk = ids[offset:offset + 200]
        payload = request(objectIds=",".join(map(str, chunk)), outFields=FIELDS, returnGeometry="false")
        records.extend(feature["attributes"] for feature in payload.get("features", []))
        print(f"Tambon points {len(records)}/{len(ids)}", flush=True)
    if len(records) != len(ids):
        raise RuntimeError(f"Expected {len(ids)} official points, got {len(records)}")
    places = []
    for item in records:
        lat, lon = item.get("LAT"), item.get("LONG")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            continue
        if not (5 <= lat <= 22 and 97 <= lon <= 106):
            continue
        places.append({"id": str(item["TA_ID"]), "tambon": item["TAMBON_T"],
                       "amphoe": item["AMPHOE_T"], "province": item["CHANGWAT_T"],
                       "lat": lat, "lon": lon})
    destination = ROOT / "data" / "static" / "places" / "tambons.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"source": SOURCE.rsplit("/query", 1)[0],
                                       "source_note": "GISTDA service; DOPA administrative reference points, last updated 2018-08-22",
                                       "imported_at": datetime.now(timezone.utc).isoformat(),
                                       "places": places}, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(places)} tambon reference points to {destination}")


if __name__ == "__main__":
    main()
