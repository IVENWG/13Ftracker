#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROMISE_SCORE_WEIGHTS = {
    "High_Conviction_Count": 0.22,
    "New_Holder_Count": 0.14,
    "Net_Buyers": 0.14,
    "Total_Delta_Value": 0.12,
    "Ownership_Delta_Avg": 0.10,
    "Max_Portfolio_Pct": 0.10,
    "Portfolio_Concentration_Avg": 0.08,
    "Buyer_Count": 0.06,
    "Holder_Count": 0.04,
    "Seller_Count": -0.05,
    "Close_Count": -0.05,
}

FIELD_MAP = {
    "Ticker": "ticker",
    "Company": "company",
    "Total_Value": "totalValue",
    "Total_Delta_Value": "totalDeltaValue",
    "Buyer_Count": "buyerCount",
    "Seller_Count": "sellerCount",
    "Holder_Count": "holderCount",
    "New_Holder_Count": "newHolderCount",
    "Close_Count": "closeCount",
    "High_Conviction_Count": "highConvictionCount",
    "Net_Buyers": "netBuyers",
    "Buyer_Seller_Ratio": "buyerSellerRatio",
    "Delta": "delta",
    "Max_Portfolio_Pct": "maxPortfolioPct",
    "Ownership_Delta_Avg": "ownershipDeltaAvg",
    "Portfolio_Concentration_Avg": "portfolioConcentrationAvg",
}

QUARTER_PATTERN = re.compile(r"^20\d{2}Q[1-4]$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static institutional toolbox data artifacts.")
    parser.add_argument("--source", type=Path, default=Path("database"), help="Source database directory containing quarter folders")
    parser.add_argument("--output", type=Path, default=Path("data/institutional"), help="Output directory for static JSON artifacts")
    return parser.parse_args()


def number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        if math.isfinite(value):
            return float(value)
        return 0.0
    if isinstance(value, str):
        cleaned = value.strip().replace(",", "").replace("$", "").replace("%", "")
        if not cleaned or cleaned.lower() in {"nan", "none", "null", "inf", "-inf"}:
            return 0.0
        multiplier = 1.0
        suffix = cleaned[-1:].upper()
        if suffix == "K":
            multiplier = 1_000.0
            cleaned = cleaned[:-1]
        elif suffix == "M":
            multiplier = 1_000_000.0
            cleaned = cleaned[:-1]
        elif suffix == "B":
            multiplier = 1_000_000_000.0
            cleaned = cleaned[:-1]
        try:
            parsed = float(cleaned) * multiplier
            return parsed if math.isfinite(parsed) else 0.0
        except ValueError:
            return 0.0
    return 0.0


def text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def discover_quarters(source: Path) -> list[str]:
    if not source.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source}")
    quarters = sorted(path.name for path in source.iterdir() if path.is_dir() and QUARTER_PATTERN.match(path.name))
    if not quarters:
        raise FileNotFoundError(f"No quarter directories matching 20??Q[1-4] found in {source}")
    return quarters


def load_analysis(source: Path, quarter: str) -> list[dict[str, Any]]:
    analysis_path = source / quarter / "analysis.json"
    if not analysis_path.exists():
        raise FileNotFoundError(
            f"Missing {analysis_path}. Generate quarter analysis in 13Ftracker before building static toolbox data."
        )
    with analysis_path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"Expected list in {analysis_path}")
    return [row for row in data if isinstance(row, dict)]


def top_stocks(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    sorted_rows = sorted(rows, key=lambda row: number(row.get("Total_Delta_Value")), reverse=True)
    return [
        {
            "ticker": text(row.get("Ticker")),
            "company": text(row.get("Company")),
            "value": number(row.get("Total_Value")),
            "deltaValue": number(row.get("Total_Delta_Value")),
        }
        for row in sorted_rows[:limit]
    ]


def top_sectors(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    sector_totals: dict[str, dict[str, float]] = defaultdict(lambda: {"value": 0.0, "deltaValue": 0.0})
    for row in rows:
        sector = text(row.get("Sector") or row.get("GICS_Sector") or row.get("Industry") or row.get("sector"))
        if not sector:
            continue
        sector_totals[sector]["value"] += number(row.get("Total_Value"))
        sector_totals[sector]["deltaValue"] += number(row.get("Total_Delta_Value"))
    return [
        {"name": name, "value": totals["value"], "deltaValue": totals["deltaValue"]}
        for name, totals in sorted(sector_totals.items(), key=lambda item: item[1]["deltaValue"], reverse=True)[:limit]
    ]


def build_quarterly_trend(quarter: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "quarter": quarter,
        "totalInstitutionalValue": sum(number(row.get("Total_Value")) for row in rows),
        "totalDeltaValue": sum(number(row.get("Total_Delta_Value")) for row in rows),
        "buyerCount": int(sum(number(row.get("Buyer_Count")) for row in rows)),
        "sellerCount": int(sum(number(row.get("Seller_Count")) for row in rows)),
        "newHolderCount": int(sum(number(row.get("New_Holder_Count")) for row in rows)),
        "closedPositionCount": int(sum(number(row.get("Close_Count")) for row in rows)),
        "highConvictionCount": int(sum(number(row.get("High_Conviction_Count")) for row in rows)),
        "netBuyers": int(sum(number(row.get("Net_Buyers")) for row in rows)),
        "topSectors": top_sectors(rows),
        "topStocks": top_stocks(rows),
    }


def percentile_ranks(values: list[float]) -> list[float]:
    if not values:
        return []
    if len(values) == 1:
        return [1.0]

    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0

    while index < len(indexed):
        end = index
        while end + 1 < len(indexed) and indexed[end + 1][1] == indexed[index][1]:
            end += 1
        average_rank = (index + end) / 2
        percentile = average_rank / (len(values) - 1)
        for offset in range(index, end + 1):
            original_index = indexed[offset][0]
            ranks[original_index] = percentile
        index = end + 1

    return ranks


def build_scores(rows: list[dict[str, Any]], quarter: str, limit: int = 100) -> list[dict[str, Any]]:
    raw_scores = [0.0] * len(rows)

    for metric, weight in PROMISE_SCORE_WEIGHTS.items():
        values = [number(row.get(metric)) for row in rows]
        ranks = percentile_ranks(values)
        for index, rank in enumerate(ranks):
            raw_scores[index] += rank * weight

    min_score = min(raw_scores) if raw_scores else 0.0
    max_score = max(raw_scores) if raw_scores else 0.0
    spread = max_score - min_score

    scored_rows: list[dict[str, Any]] = []
    for row, raw_score in zip(rows, raw_scores, strict=True):
        promise_score = 100.0 if spread == 0 and raw_scores else ((raw_score - min_score) / spread) * 100.0
        normalized = {target: number(row.get(source)) for source, target in FIELD_MAP.items() if target not in {"ticker", "company"}}
        scored_rows.append(
            {
                "ticker": text(row.get("Ticker")),
                "company": text(row.get("Company")),
                "quarter": quarter,
                "promiseScore": round(promise_score, 2),
                **normalized,
            }
        )

    scored_rows.sort(key=lambda row: row["promiseScore"], reverse=True)
    ranked = scored_rows[:limit]
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
        file.write("\n")


def copy_analysis_files(source: Path, output: Path, quarters: list[str]) -> None:
    for quarter in quarters:
        destination = output / "quarters" / quarter / "analysis.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / quarter / "analysis.json", destination)


def main() -> None:
    args = parse_args()
    source = args.source
    output = args.output
    quarters = discover_quarters(source)
    analyses = {quarter: load_analysis(source, quarter) for quarter in quarters}
    latest_quarter = quarters[-1]

    metadata = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "latestQuarter": latest_quarter,
        "quarters": quarters,
        "source": "13Ftracker",
        "schemaVersion": 1,
    }
    quarterly_trends = [build_quarterly_trend(quarter, analyses[quarter]) for quarter in quarters]
    most_promising = build_scores(analyses[latest_quarter], latest_quarter)

    write_json(output / "metadata.json", metadata)
    write_json(output / "quarterly-trends.json", quarterly_trends)
    write_json(output / "most-promising-stocks.json", most_promising)
    copy_analysis_files(source, output, quarters)

    print(f"Wrote institutional artifacts for {len(quarters)} quarters to {output}")


if __name__ == "__main__":
    main()
