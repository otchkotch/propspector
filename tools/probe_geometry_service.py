from __future__ import annotations

import json
import urllib.parse
import urllib.request


def post_json(url: str, params: dict[str, str]) -> dict:
    request = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


parcel = post_json(
    "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Base_Layers/MapServer/0/query",
    {
        "f": "json",
        "where": "PARCELNO='2605000039' OR PRCLID='2605000039' OR SHORTPRCL='2605000039'",
        "outFields": "PARCELNO",
        "returnGeometry": "true",
        "outSR": "102657",
    },
)["features"][0]["geometry"]
parcel["spatialReference"] = {"wkid": 102657}

features = post_json(
    "https://gis.nccde.org/agsserver/rest/services/BaseMaps/Environmental/MapServer/9/query",
    {
        "f": "json",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "102657",
        "geometry": json.dumps(parcel, separators=(",", ":")),
        "geometryType": "esriGeometryPolygon",
        "inSR": "102657",
        "spatialRel": "esriSpatialRelIntersects",
    },
).get("features", [])
print("features", len(features))

if features:
    feature_geometries = []
    for feature in features[:3]:
        geometry = feature["geometry"]
        geometry["spatialReference"] = {"wkid": 102657}
        feature_geometries.append(geometry)
    intersected = post_json(
        "https://gis.nccde.org/agsserver/rest/services/Utilities/Geometry/GeometryServer/intersect",
        {
            "f": "json",
            "sr": "102657",
            "geometry": json.dumps(
                {"geometryType": "esriGeometryPolygon", "geometry": parcel},
                separators=(",", ":"),
            ),
            "geometries": json.dumps(
                {"geometryType": "esriGeometryPolygon", "geometries": feature_geometries},
                separators=(",", ":"),
            ),
        },
    )
    print("intersect", intersected.keys(), intersected.get("error"), len(intersected.get("geometries", [])))
    areas = post_json(
        "https://gis.nccde.org/agsserver/rest/services/Utilities/Geometry/GeometryServer/areasAndLengths",
        {
            "f": "json",
            "sr": "102657",
            "polygons": json.dumps(intersected.get("geometries", []), separators=(",", ":")),
            "lengthUnit": "9003",
            "areaUnit": json.dumps({"areaUnit": "esriSquareFeet"}, separators=(",", ":")),
            "calculationType": "planar",
        },
    )
    print(areas)
