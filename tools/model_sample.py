from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from parcel_packet.zoning_feasibility_runner import ZoningFeasibilityRunner


def main() -> None:
    parcels = sys.argv[1:] or ["0804930379", "1000100074", "1000100014", "0902800058", "1105400001", "2605000039"]
    for parcel in parcels:
        try:
            result = ZoningFeasibilityRunner(parcel).analyze()
        except Exception as exc:
            print("\nPARCEL", parcel, "ERROR", exc)
            continue
        print("\nPARCEL", parcel)
        print("municipality", result.municipality)
        print("area_ac", f"{result.parcel_area_sf / 43560:.2f}")
        print("zoning", ",".join(d.code for d in result.zoning_districts))
        print("owner", result.parcel.owner)
        for item in result.recommendations[:5]:
            print(" -", item.development_option, item.status, item.conservative_yield, item.market_basis, item.note[:180])


if __name__ == "__main__":
    main()
