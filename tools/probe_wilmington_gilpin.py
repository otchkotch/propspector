from __future__ import annotations

import json
import urllib.parse
import urllib.request


PARCEL_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/0/query"
MUNICIPAL_ZONING_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Zoning/MapServer/4/query"
MUNICIPALITY_URL = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/2/query"


def fetch_json(url: str, params: dict[str, str]) -> dict:
    request_url = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(request_url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parcel_data = fetch_json(
        PARCEL_URL,
        {
            "f": "json",
            "where": "STNO = '1021' AND UPPER(STNAME) = 'GILPIN'",
            "outFields": "PARCELNO,PRCLID,SHORTPRCL,ADDRESS,STNO,STNAME,SUFFIX,PROPCITY,PROPSTATE,PROPZIP,CNTCTLAST,INCORP,LOTSZ,LOTFRONTAG,LOTDPTH",
            "returnGeometry": "true",
            "outSR": "102657",
        },
    )
    features = parcel_data.get("features") or []
    print("parcel features", len(features))
    for feature in features:
        print(json.dumps(feature.get("attributes") or {}, indent=2))
    if not features:
        return 1

    geometry = features[0]["geometry"]
    for label, url in (("municipality", MUNICIPALITY_URL), ("municipal zoning", MUNICIPAL_ZONING_URL)):
        data = fetch_json(
            url,
            {
                "f": "json",
                "where": "1=1",
                "outFields": "*",
                "returnGeometry": "false",
                "geometry": json.dumps(geometry, separators=(",", ":")),
                "geometryType": "esriGeometryPolygon",
                "inSR": "102657",
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        print(label, len(data.get("features") or []))
        for feature in data.get("features") or []:
            print(json.dumps(feature.get("attributes") or {}, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
