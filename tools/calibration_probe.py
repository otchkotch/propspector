from __future__ import annotations

import json
import urllib.request


ROOT = "https://gis.nccde.org/agsserver/rest/services"


def fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def main() -> None:
    root = fetch(f"{ROOT}/?f=pjson")
    print("folders:", ", ".join(root.get("folders") or ()))
    needles = ("plan", "land", "develop", "subdiv", "record", "permit", "project", "zoning", "base")
    for folder in root.get("folders") or ():
        data = fetch(f"{ROOT}/{folder}?f=pjson")
        hits = [
            service.get("name", "")
            for service in data.get("services", [])
            if any(needle in service.get("name", "").lower() for needle in needles)
        ]
        if hits:
            print(f"\n{folder}")
            for name in hits:
                print(name)

    for service in (
        "BaseMaps/Plans_Basemap",
        "BaseMaps/LandUse",
        "CustomMaps/Permits",
        "BaseMaps/Assessment",
    ):
        data = fetch(f"{ROOT}/{service}/MapServer?f=pjson")
        print(f"\nSERVICE {service}")
        for layer in data.get("layers") or ():
            print(layer.get("id"), layer.get("name"))

    for service, layer_ids in {
        "BaseMaps/Plans_Basemap": (75, 83, 85, 96, 97, 110, 118, 141, 146, 156, 167),
        "BaseMaps/LandUse": (3,),
    }.items():
        for layer_id in layer_ids:
            data = fetch(f"{ROOT}/{service}/MapServer/{layer_id}?f=pjson")
            print(f"\nFIELDS {service}/{layer_id} {data.get('name')}")
            for field in data.get("fields") or ():
                print(field.get("name"), "-", field.get("alias"), "-", field.get("type"))


if __name__ == "__main__":
    main()
