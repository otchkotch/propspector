from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request


def fetch_json(url: str, params: dict[str, str]) -> dict:
    request_url = url + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(request_url, timeout=30) as response:
        return json.load(response)


def main() -> None:
    parcel = sys.argv[1] if len(sys.argv) > 1 else "2605000039"
    parcel_url = "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/0/query"
    parcel_data = fetch_json(
        parcel_url,
        {
            "f": "json",
            "where": f"PARCELNO='{parcel}'",
            "outFields": "PARCELNO",
            "returnGeometry": "true",
            "outSR": "102100",
        },
    )
    print("parcel features", len(parcel_data.get("features", [])), parcel_data.get("error"))
    if not parcel_data.get("features"):
        return

    geometry = parcel_data["features"][0]["geometry"]
    for layer_id in (9, 10):
        data = fetch_json(
            f"https://gis.nccde.org/agsserver/rest/services/BaseMaps/Environmental/MapServer/{layer_id}/query",
            {
                "f": "json",
                "where": "1=1",
                "returnCountOnly": "true",
                "geometry": json.dumps(geometry, separators=(",", ":")),
                "geometryType": "esriGeometryPolygon",
                "inSR": "102100",
                "spatialRel": "esriSpatialRelIntersects",
            },
        )
        print(layer_id, data)


if __name__ == "__main__":
    main()
