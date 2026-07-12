from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.zoning_feasibility_runner import ZoningFeasibilityRunner
from tools.calibrate_propspector import development_projects


def main() -> int:
    result = ZoningFeasibilityRunner("2000 pennsylvania avenue").analyze()
    print("PARCEL", result.parcel.parcel_number)
    print("ADDRESS", result.parcel.address)
    print("OWNER", result.parcel.owner)
    print("MUNICIPALITY", result.municipality)
    print("AREA_AC", round(result.parcel_area_sf / 43560.0, 4))
    print("ZONING", [district.__dict__ for district in result.zoning_districts])
    print("RECOMMENDATIONS")
    for recommendation in result.recommendations:
        print(
            recommendation.development_option,
            recommendation.status,
            recommendation.conservative_yield,
            recommendation.gross_area_yield,
            recommendation.market_value_low,
            recommendation.market_value_high,
        )

    queries = (
        "parcelid LIKE '%2602010008%'",
        "UPPER(projname) LIKE '%PENNSYLVANIA%'",
        "UPPER(descript) LIKE '%PENNSYLVANIA%'",
        "UPPER(projname) LIKE '%GALLERIA%'",
        "UPPER(descript) LIKE '%GALLERIA%'",
    )
    for query in queries:
        print("\nWHERE", query)
        for project in development_projects(query, 30):
            print(project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
