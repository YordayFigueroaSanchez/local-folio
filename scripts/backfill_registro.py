import argparse
import csv
from pathlib import Path


OLD_HEADER = [
    "date",
    "reward_ont",
    "ont_price_usd",
    "usd_to_uyu",
    "reward_usd",
    "reward_uyu",
    "target_uyu",
    "salary_minimum_uyu",
    "progress_target_pct",
    "salary_minimum_pct",
    "notes",
    "created_at_utc",
]

HEADER = [
    "date",
    "reward_ont",
    "accumulated_reward_ont",
    "ont_price_usd",
    "usd_to_uyu",
    "reward_usd",
    "reward_uyu",
    "accumulated_reward_usd",
    "accumulated_reward_uyu",
    "target_uyu",
    "salary_minimum_uyu",
    "progress_target_pct",
    "salary_minimum_pct",
    "notes",
    "created_at_utc",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill missing FX and calculated fields for historical registry rows."
    )
    parser.add_argument("--date", required=True, help="Row date in YYYY-MM-DD format")
    parser.add_argument(
        "--ont-usd", required=True, type=float, help="ONT price in USD for the row date"
    )
    parser.add_argument(
        "--usd-uyu", required=True, type=float, help="USD to UYU exchange rate for the row date"
    )
    parser.add_argument("--target-uyu", required=True, type=float, help="Target amount in UYU")
    parser.add_argument(
        "--salary-min-uyu",
        required=True,
        type=float,
        help="Reference minimum salary in UYU",
    )
    parser.add_argument(
        "--notes-contains",
        default="",
        help="Optional filter: only rows whose notes contain this text",
    )
    parser.add_argument(
        "--file",
        default="registro/recompensas.csv",
        help="Registry CSV file path",
    )
    return parser.parse_args()


def validate_positive(value: float, field_name: str) -> float:
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return value


def to_float(text: str) -> float:
    return float(text.strip())


def to_float_or_zero(text: str | None) -> float:
    if text is None:
        return 0.0
    value = text.strip()
    if value == "":
        return 0.0
    return float(value)


def is_missing(text: str) -> bool:
    return text.strip() == ""


def apply_rates_to_row(
    row: dict[str, str],
    ont_usd: float,
    usd_uyu: float,
    target_uyu: float,
    salary_min_uyu: float,
) -> dict[str, str]:
    reward = to_float_or_zero(row.get("reward_ont"))
    reward_usd = reward * ont_usd
    reward_uyu = reward_usd * usd_uyu

    row["ont_price_usd"] = f"{ont_usd:.8f}"
    row["usd_to_uyu"] = f"{usd_uyu:.8f}"
    row["reward_usd"] = f"{reward_usd:.8f}"
    row["reward_uyu"] = f"{reward_uyu:.8f}"
    row["target_uyu"] = f"{target_uyu:.8f}"
    row["salary_minimum_uyu"] = f"{salary_min_uyu:.8f}"
    return row


def should_backfill(row: dict[str, str], date: str, notes_filter: str) -> bool:
    if row["date"] != date:
        return False
    if notes_filter and notes_filter not in row["notes"]:
        return False
    fields = [
        row["ont_price_usd"],
        row["usd_to_uyu"],
        row["reward_usd"],
        row["reward_uyu"],
        row["target_uyu"],
        row["salary_minimum_uyu"],
        row["progress_target_pct"],
        row["salary_minimum_pct"],
    ]
    return any(is_missing(value) for value in fields)


def normalize_row(row: dict[str, str], header: list[str]) -> dict[str, str]:
    if header == HEADER:
        return {key: row.get(key, "") for key in HEADER}

    if header == OLD_HEADER:
        return {
            "date": row.get("date", ""),
            "reward_ont": row.get("reward_ont", ""),
            "accumulated_reward_ont": "",
            "ont_price_usd": row.get("ont_price_usd", ""),
            "usd_to_uyu": row.get("usd_to_uyu", ""),
            "reward_usd": row.get("reward_usd", ""),
            "reward_uyu": row.get("reward_uyu", ""),
            "accumulated_reward_usd": "",
            "accumulated_reward_uyu": "",
            "target_uyu": row.get("target_uyu", ""),
            "salary_minimum_uyu": row.get("salary_minimum_uyu", ""),
            "progress_target_pct": row.get("progress_target_pct", ""),
            "salary_minimum_pct": row.get("salary_minimum_pct", ""),
            "notes": row.get("notes", ""),
            "created_at_utc": row.get("created_at_utc", ""),
        }

    raise ValueError("Unexpected registry header. Use known schema before backfill.")


def recompute_cumulative(rows: list[dict[str, str]]) -> None:
    accumulated_ont = 0.0
    accumulated_usd = 0.0
    accumulated_uyu = 0.0

    for row in rows:
        reward_ont = to_float_or_zero(row.get("reward_ont"))
        reward_usd = to_float_or_zero(row.get("reward_usd"))
        reward_uyu = to_float_or_zero(row.get("reward_uyu"))

        accumulated_ont += reward_ont
        accumulated_usd += reward_usd
        accumulated_uyu += reward_uyu

        row["accumulated_reward_ont"] = f"{accumulated_ont:.8f}"
        row["accumulated_reward_usd"] = f"{accumulated_usd:.8f}"
        row["accumulated_reward_uyu"] = f"{accumulated_uyu:.8f}"

        target_uyu = to_float_or_zero(row.get("target_uyu"))
        salary_min_uyu = to_float_or_zero(row.get("salary_minimum_uyu"))

        if target_uyu > 0:
            row["progress_target_pct"] = f"{(accumulated_uyu * 100.0) / target_uyu:.6f}"
        else:
            row["progress_target_pct"] = ""

        if salary_min_uyu > 0:
            row["salary_minimum_pct"] = f"{(accumulated_uyu * 100.0) / salary_min_uyu:.6f}"
        else:
            row["salary_minimum_pct"] = ""


def main() -> None:
    args = parse_args()
    ont_usd = validate_positive(args.ont_usd, "ont-usd")
    usd_uyu = validate_positive(args.usd_uyu, "usd-uyu")
    target_uyu = validate_positive(args.target_uyu, "target-uyu")
    salary_min_uyu = validate_positive(args.salary_min_uyu, "salary-min-uyu")

    file_path = Path(args.file)
    if not file_path.exists():
        raise FileNotFoundError(f"Registry file not found: {file_path}")

    with file_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        source_header = reader.fieldnames or []
        rows = [normalize_row(row, source_header) for row in reader]

    updated = 0

    for row in rows:
        if should_backfill(row, args.date, args.notes_contains):
            row = apply_rates_to_row(row, ont_usd, usd_uyu, target_uyu, salary_min_uyu)
            updated += 1

    recompute_cumulative(rows)

    with file_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Rows updated: {updated}")
    print(f"File updated: {file_path}")


if __name__ == "__main__":
    main()
