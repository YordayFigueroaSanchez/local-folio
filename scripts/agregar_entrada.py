import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from urllib import request


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
        description="Append a reward entry with exchange rates and calculated metrics."
    )
    parser.add_argument("--date", required=True, help="Entry date in YYYY-MM-DD format")
    parser.add_argument("--reward", required=True, type=float, help="Reward amount in ONT")
    parser.add_argument(
        "--ont-usd",
        type=float,
        help="ONT price in USD for the entry date (optional when using --fetch-rates)",
    )
    parser.add_argument(
        "--usd-uyu",
        type=float,
        help="USD to UYU exchange rate for the entry date (optional when using --fetch-rates)",
    )
    parser.add_argument(
        "--fetch-rates",
        action="store_true",
        help="Fetch ONT/USD and USD/UYU from external services",
    )
    parser.add_argument(
        "--coingecko-url",
        default="https://api.coingecko.com/api/v3/simple/price?ids=ontology&vs_currencies=usd",
        help="Service URL for ONT/USD price",
    )
    parser.add_argument(
        "--fx-url",
        default="https://open.er-api.com/v6/latest/USD",
        help="Service URL for USD base exchange rates",
    )
    parser.add_argument(
        "--http-timeout",
        type=float,
        default=10.0,
        help="HTTP timeout in seconds for rate providers",
    )
    parser.add_argument(
        "--target-uyu",
        required=True,
        type=float,
        help="Target amount in UYU",
    )
    parser.add_argument(
        "--salary-min-uyu",
        required=True,
        type=float,
        help="Reference minimum salary in UYU",
    )
    parser.add_argument("--notes", default="", help="Optional free text note")
    parser.add_argument(
        "--file",
        default="registro/recompensas.csv",
        help="Registry CSV file path",
    )
    return parser.parse_args()


def validate_date(value: str) -> str:
    dt.datetime.strptime(value, "%Y-%m-%d")
    return value


def validate_reward(value: float) -> float:
    if value < 0:
        raise ValueError("reward must be >= 0")
    return value


def validate_positive(value: float, field_name: str) -> float:
    if value <= 0:
        raise ValueError(f"{field_name} must be > 0")
    return value


def fetch_json(url: str, timeout: float) -> dict:
    with request.urlopen(url, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected JSON payload from {url}")
    return data


def fetch_ont_usd(url: str, timeout: float) -> float:
    data = fetch_json(url, timeout)
    try:
        return float(data["ontology"]["usd"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Could not parse ONT/USD from provider response") from exc


def fetch_usd_uyu(url: str, timeout: float) -> float:
    data = fetch_json(url, timeout)
    try:
        return float(data["rates"]["UYU"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Could not parse USD/UYU from provider response") from exc


def resolve_rates(args: argparse.Namespace) -> tuple[float, float]:
    if args.fetch_rates:
        ont_usd = fetch_ont_usd(args.coingecko_url, args.http_timeout)
        usd_uyu = fetch_usd_uyu(args.fx_url, args.http_timeout)
        print(
            "Fetched rates from services: "
            f"ONT/USD={ont_usd:.8f}, USD/UYU={usd_uyu:.8f}"
        )
        return ont_usd, usd_uyu

    if args.ont_usd is None or args.usd_uyu is None:
        raise ValueError(
            "Provide --ont-usd and --usd-uyu, or use --fetch-rates to query services"
        )

    return args.ont_usd, args.usd_uyu


def ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=HEADER)
            writer.writeheader()


def parse_float_or_zero(text: str | None) -> float:
    if text is None:
        return 0.0
    value = text.strip()
    if value == "":
        return 0.0
    return float(value)


def get_previous_totals(path: Path) -> tuple[float, float, float]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != HEADER:
            raise ValueError(
                "Unexpected registry header. Run migration to cumulative CSV schema first."
            )
        rows = list(reader)

    if not rows:
        return 0.0, 0.0, 0.0

    last = rows[-1]
    return (
        parse_float_or_zero(last.get("accumulated_reward_ont")),
        parse_float_or_zero(last.get("accumulated_reward_usd")),
        parse_float_or_zero(last.get("accumulated_reward_uyu")),
    )


def append_entry(
    path: Path,
    date: str,
    reward: float,
    ont_usd: float,
    usd_uyu: float,
    target_uyu: float,
    salary_min_uyu: float,
    notes: str,
) -> None:
    created_at = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    if created_at.endswith("+00:00"):
        created_at = created_at.replace("+00:00", "Z")

    prev_ont, prev_usd, prev_uyu = get_previous_totals(path)

    reward_usd = reward * ont_usd
    reward_uyu = reward_usd * usd_uyu
    accumulated_reward_ont = prev_ont + reward
    accumulated_reward_usd = prev_usd + reward_usd
    accumulated_reward_uyu = prev_uyu + reward_uyu
    progress_target_pct = (accumulated_reward_uyu * 100.0) / target_uyu
    salary_minimum_pct = (accumulated_reward_uyu * 100.0) / salary_min_uyu

    safe_notes = notes.replace("\n", " ")
    row = {
        "date": date,
        "reward_ont": f"{reward:.8f}",
        "accumulated_reward_ont": f"{accumulated_reward_ont:.8f}",
        "ont_price_usd": f"{ont_usd:.8f}",
        "usd_to_uyu": f"{usd_uyu:.8f}",
        "reward_usd": f"{reward_usd:.8f}",
        "reward_uyu": f"{reward_uyu:.8f}",
        "accumulated_reward_usd": f"{accumulated_reward_usd:.8f}",
        "accumulated_reward_uyu": f"{accumulated_reward_uyu:.8f}",
        "target_uyu": f"{target_uyu:.8f}",
        "salary_minimum_uyu": f"{salary_min_uyu:.8f}",
        "progress_target_pct": f"{progress_target_pct:.6f}",
        "salary_minimum_pct": f"{salary_minimum_pct:.6f}",
        "notes": safe_notes,
        "created_at_utc": created_at,
    }
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writerow(row)


def main() -> None:
    args = parse_args()
    date = validate_date(args.date)
    reward = validate_reward(args.reward)
    ont_usd, usd_uyu = resolve_rates(args)
    ont_usd = validate_positive(ont_usd, "ont-usd")
    usd_uyu = validate_positive(usd_uyu, "usd-uyu")
    target_uyu = validate_positive(args.target_uyu, "target-uyu")
    salary_min_uyu = validate_positive(args.salary_min_uyu, "salary-min-uyu")
    file_path = Path(args.file)
    ensure_file(file_path)
    append_entry(
        file_path,
        date,
        reward,
        ont_usd,
        usd_uyu,
        target_uyu,
        salary_min_uyu,
        args.notes,
    )
    print(f"Entry appended to {file_path}")


if __name__ == "__main__":
    main()
