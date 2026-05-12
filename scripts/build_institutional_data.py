#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
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

FIELD_ALIASES = {
    "ticker": ["Ticker", "ticker"],
    "company": ["Company", "company"],
    "totalValue": ["Total_Value", "totalValue"],
    "totalDeltaValue": ["Total_Delta_Value", "totalDeltaValue"],
    "buyerCount": ["Buyer_Count", "buyerCount"],
    "sellerCount": ["Seller_Count", "sellerCount"],
    "holderCount": ["Holder_Count", "holderCount"],
    "newHolderCount": ["New_Holder_Count", "newHolderCount"],
    "closeCount": ["Close_Count", "closeCount"],
    "highConvictionCount": ["High_Conviction_Count", "highConvictionCount"],
    "netBuyers": ["Net_Buyers", "netBuyers"],
    "buyerSellerRatio": ["Buyer_Seller_Ratio", "buyerSellerRatio"],
    "delta": ["Delta", "delta"],
    "maxPortfolioPct": ["Max_Portfolio_Pct", "maxPortfolioPct"],
    "avgPortfolioPct": ["Avg_Portfolio_Pct", "avgPortfolioPct", "Portfolio_Concentration_Avg", "portfolioConcentrationAvg"],
    "ownershipDeltaAvg": ["Ownership_Delta_Avg", "ownershipDeltaAvg"],
    "portfolioConcentrationAvg": ["Portfolio_Concentration_Avg", "portfolioConcentrationAvg", "Avg_Portfolio_Pct", "avgPortfolioPct"],
}

QUARTER_PATTERN = re.compile(r"^20\d{2}Q[1-4]$")
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build static institutional toolbox data artifacts.")
    parser.add_argument("--source", type=Path, default=Path("database"), help="Source database directory containing quarter folders")
    parser.add_argument("--output", type=Path, default=Path("data/institutional"), help="Output directory for static JSON artifacts")
    return parser.parse_args()


def raw_value(row: dict[str, Any], aliases: list[str]) -> Any:
    for alias in aliases:
        if alias in row:
            return row[alias]
    return None


def number(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else 0.0
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


def metric(row: dict[str, Any], name: str) -> float:
    return number(raw_value(row, FIELD_ALIASES[name]))


def text_metric(row: dict[str, Any], name: str) -> str:
    value = raw_value(row, FIELD_ALIASES[name])
    if value is None:
        return ""
    return str(value).strip()


def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": text_metric(row, "ticker"),
        "company": text_metric(row, "company"),
        "totalValue": metric(row, "totalValue"),
        "totalDeltaValue": metric(row, "totalDeltaValue"),
        "maxPortfolioPct": metric(row, "maxPortfolioPct"),
        "avgPortfolioPct": metric(row, "avgPortfolioPct"),
        "buyerCount": int(metric(row, "buyerCount")),
        "sellerCount": int(metric(row, "sellerCount")),
        "closeCount": int(metric(row, "closeCount")),
        "holderCount": int(metric(row, "holderCount")),
        "newHolderCount": int(metric(row, "newHolderCount")),
        "highConvictionCount": int(metric(row, "highConvictionCount")),
        "ownershipDeltaAvg": metric(row, "ownershipDeltaAvg"),
        "portfolioConcentrationAvg": metric(row, "portfolioConcentrationAvg"),
        "netBuyers": int(metric(row, "netBuyers")),
        "delta": metric(row, "delta"),
        "buyerSellerRatio": metric(row, "buyerSellerRatio"),
    }


def discover_quarters(source: Path) -> list[str]:
    if not source.exists():
        raise FileNotFoundError(f"Source directory does not exist: {source}")
    quarters = sorted(path.name for path in source.iterdir() if path.is_dir() and QUARTER_PATTERN.match(path.name))
    if not quarters:
        raise FileNotFoundError(f"No quarter directories matching 20??Q[1-4] found in {source}")
    return quarters


def load_raw_analysis(source: Path, quarter: str) -> list[dict[str, Any]]:
    analysis_path = source / quarter / "analysis.json"
    if analysis_path.exists():
        with analysis_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            raise ValueError(f"Expected list in {analysis_path}")
        return [row for row in data if isinstance(row, dict)]

    from app.analysis.stocks import quarter_analysis

    df = quarter_analysis(quarter)
    records = df.to_dict(orient="records")
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(analysis_path, records)
    return records


def load_analysis(source: Path, quarter: str) -> list[dict[str, Any]]:
    return [normalize_row(row) for row in load_raw_analysis(source, quarter)]


def top_stocks(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    sorted_rows = sorted(rows, key=lambda row: row["totalDeltaValue"], reverse=True)
    return [
        {
            "ticker": row["ticker"],
            "company": row["company"],
            "value": row["totalValue"],
            "deltaValue": row["totalDeltaValue"],
        }
        for row in sorted_rows[:limit]
    ]


def top_sectors(raw_rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    sector_totals: dict[str, dict[str, float]] = defaultdict(lambda: {"value": 0.0, "deltaValue": 0.0})
    for row in raw_rows:
        sector = raw_value(row, ["Sector", "GICS_Sector", "Industry", "sector"])
        sector_name = "" if sector is None else str(sector).strip()
        if not sector_name:
            continue
        normalized = normalize_row(row)
        sector_totals[sector_name]["value"] += normalized["totalValue"]
        sector_totals[sector_name]["deltaValue"] += normalized["totalDeltaValue"]
    return [
        {"name": name, "value": totals["value"], "deltaValue": totals["deltaValue"]}
        for name, totals in sorted(sector_totals.items(), key=lambda item: item[1]["deltaValue"], reverse=True)[:limit]
    ]


def build_quarterly_trend(quarter: str, rows: list[dict[str, Any]], raw_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "quarter": quarter,
        "totalInstitutionalValue": sum(row["totalValue"] for row in rows),
        "totalDeltaValue": sum(row["totalDeltaValue"] for row in rows),
        "buyerCount": sum(row["buyerCount"] for row in rows),
        "sellerCount": sum(row["sellerCount"] for row in rows),
        "newHolderCount": sum(row["newHolderCount"] for row in rows),
        "closedPositionCount": sum(row["closeCount"] for row in rows),
        "highConvictionCount": sum(row["highConvictionCount"] for row in rows),
        "netBuyers": sum(row["netBuyers"] for row in rows),
        "topSectors": top_sectors(raw_rows),
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
        percentile = ((index + end) / 2) / (len(values) - 1)
        for offset in range(index, end + 1):
            ranks[indexed[offset][0]] = percentile
        index = end + 1

    return ranks


def build_scores(rows: list[dict[str, Any]], raw_rows: list[dict[str, Any]], quarter: str, limit: int = 100) -> list[dict[str, Any]]:
    raw_scores = [0.0] * len(rows)

    for metric_name, weight in PROMISE_SCORE_WEIGHTS.items():
        values = [number(raw_value(raw_row, [metric_name])) for raw_row in raw_rows]
        ranks = percentile_ranks(values)
        for index, rank in enumerate(ranks):
            raw_scores[index] += rank * weight

    min_score = min(raw_scores) if raw_scores else 0.0
    max_score = max(raw_scores) if raw_scores else 0.0
    spread = max_score - min_score

    scored_rows: list[dict[str, Any]] = []
    for row, raw_score in zip(rows, raw_scores, strict=True):
        promise_score = 100.0 if spread == 0 and raw_scores else ((raw_score - min_score) / spread) * 100.0
        scored_rows.append({"quarter": quarter, "promiseScore": round(promise_score, 2), **row})

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


def main() -> None:
    args = parse_args()
    source = args.source
    output = args.output
    quarters = discover_quarters(source)
    raw_analyses = {quarter: load_raw_analysis(source, quarter) for quarter in quarters}
    analyses = {quarter: [normalize_row(row) for row in raw_analyses[quarter]] for quarter in quarters}
    latest_quarter = quarters[-1]

    metadata = {
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "latestQuarter": latest_quarter,
        "quarters": quarters,
        "source": "13Ftracker",
        "schemaVersion": 1,
    }
    quarterly_trends = [build_quarterly_trend(quarter, analyses[quarter], raw_analyses[quarter]) for quarter in quarters]
    most_promising = build_scores(analyses[latest_quarter], raw_analyses[latest_quarter], latest_quarter)

    write_json(output / "metadata.json", metadata)
    write_json(output / "quarterly-trends.json", quarterly_trends)
    write_json(output / "most-promising-stocks.json", most_promising)
    for quarter in quarters:
        write_json(output / "quarters" / quarter / "analysis.json", analyses[quarter])

    print(f"Wrote institutional artifacts for {len(quarters)} quarters to {output}")


if __name__ == "__main__":
    main()
