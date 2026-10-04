"""Build the compact US wage snapshot from WageDex's published OEWS CSV.

Download https://wagedex.com/data/wagedex-occupation-wages.csv, then run
`python radar/data/build_pay_estimates.py <downloaded-csv>` after each annual release.
WageDex compilation: CC BY 4.0; underlying BLS OEWS figures: public domain.
"""
import csv
import json
import sys
from pathlib import Path

OCCUPATIONS = {
    "15-1252", "15-1253", "15-2051", "15-1212", "15-1211", "15-1244",
    "17-2061", "17-2071", "17-2141", "17-2112", "17-2051", "13-2051",
    "13-1111", "13-1161", "13-2011", "15-2031", "15-1254", "27-1024",
    "13-1081", "15-1251",
}


def main(path):
    with open(path, newline="") as source:
        rows = {r["occ_code"]: {"occupation": r["occ_title"],
                                "p10": int(r["pct10_annual_wage"]),
                                "p25": int(r["pct25_annual_wage"])}
                for r in csv.DictReader(line for line in source if not line.startswith("#"))
                if r["occ_code"] in OCCUPATIONS and r["pct10_annual_wage"] and r["pct25_annual_wage"]}
    missing = OCCUPATIONS - rows.keys()
    if missing:
        raise ValueError(f"missing wage rows: {sorted(missing)}")
    Path(__file__).with_name("pay_estimates.json").write_text(json.dumps({"year": 2025, "US": rows}, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv[1])
