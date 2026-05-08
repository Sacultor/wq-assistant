import argparse
import json
import re
from random import uniform
from time import sleep
from pathlib import Path

import pandas as pd

from machine_lib import get_datafields, get_datasets, login


DEFAULT_COLUMNS = [
    "dataset_id",
    "id",
    "type",
    "name",
    "description",
    "category",
    "subcategory",
    "region",
    "universe",
    "delay",
]


def safe_filename(value):
    value = str(value).strip()
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    return value or "unknown"


def ensure_columns(df, columns):
    for col in columns:
        if col not in df.columns:
            df[col] = None
    return df


def save_csv(df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"Wrote {path} ({len(df)} rows)")


def select_dataset_ids(datasets_df, requested_ids=None, limit=None):
    if requested_ids:
        return requested_ids
    if "id" not in datasets_df.columns:
        raise ValueError("Dataset response does not include an id column")
    ids = datasets_df["id"].dropna().astype(str).tolist()
    if limit is not None:
        ids = ids[:limit]
    return ids


def flatten_list_values(df):
    for col in df.columns:
        df[col] = df[col].apply(
            lambda value: ", ".join(map(str, value)) if isinstance(value, list) else value
        )
    return df


def set_or_insert_column(df, position, column, value):
    if column in df.columns:
        df[column] = value
    else:
        df.insert(position, column, value)


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError:
            return value
    return value


def get_datafields_with_retry(
    s,
    dataset_id,
    region,
    universe,
    delay,
    max_retries=12,
    jitter=1,
):
    for attempt in range(1, max_retries + 1):
        try:
            return get_datafields(
                s,
                dataset_id=dataset_id,
                region=region,
                universe=universe,
                delay=delay,
            )
        except Exception as e:
            message = str(e)
            if "rate limit" not in message.lower() and "429" not in message:
                raise
            if attempt >= max_retries:
                raise
            wait_seconds = min(120, 2 ** attempt) + uniform(0, jitter)
            print(
                f"Rate limited while fetching {dataset_id}; "
                f"waiting {wait_seconds:.0f}s ({attempt}/{max_retries})"
            )
            sleep(wait_seconds)


def fetch_dataset_fields(
    s,
    dataset_id,
    region,
    universe,
    delay,
    output_dir,
    resume=True,
    max_retries=12,
    page_delay=3,
    jitter=1,
    timeout=30,
):
    dataset_path = output_dir / "by_dataset" / f"{safe_filename(dataset_id)}.csv"
    if resume and dataset_path.exists():
        print(f"Skipping {dataset_id}; existing file found")
        df = pd.read_csv(dataset_path)
        return df

    print(f"Fetching data fields for dataset={dataset_id}")
    if page_delay > 0:
        sleep(max(0, page_delay + uniform(0, jitter)))
    df = get_datafields_with_retry(
        s,
        dataset_id=dataset_id,
        region=region,
        universe=universe,
        delay=delay,
        max_retries=max_retries,
        jitter=jitter,
    )
    if df.empty:
        print(f"No fields found for dataset={dataset_id}")
        return df

    df = flatten_list_values(df)
    set_or_insert_column(df, 0, "dataset_id", dataset_id)
    set_or_insert_column(df, 1, "region", region)
    set_or_insert_column(df, 2, "universe", universe)
    set_or_insert_column(df, 3, "delay", delay)
    save_csv(df, dataset_path)
    return df


def write_fields_for_ai_jsonl(fields_df, datasets_df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    dataset_meta = {}
    if not datasets_df.empty and "id" in datasets_df.columns:
        for _, row in datasets_df.iterrows():
            dataset_meta[str(row.get("id"))] = {
                "dataset_id": row.get("id"),
                "dataset_name": row.get("name"),
                "category": row.get("category"),
                "subcategory": row.get("subcategory"),
                "description": row.get("description"),
            }
    with open(path, "w", encoding="utf-8") as f:
        for _, row in fields_df.iterrows():
            dataset_id = str(row.get("dataset_id", ""))
            record = {
                "dataset": dataset_meta.get(dataset_id, {"dataset_id": dataset_id}),
                "field": {
                    "id": row.get("id"),
                    "description": row.get("description") or row.get("name"),
                    "type": row.get("type"),
                    "coverage": row.get("coverage"),
                    "date_coverage": row.get("dateCoverage") or row.get("date_coverage"),
                    "alphas": row.get("alphaCount") or row.get("alphas"),
                },
                "context": {
                    "region": row.get("region"),
                    "universe": row.get("universe"),
                    "delay": row.get("delay"),
                },
            }
            f.write(json.dumps(json_safe(record), ensure_ascii=False) + "\n")
    print(f"Wrote {path}")


def write_readable_txt(fields_df, datasets_df, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields_df = ensure_columns(fields_df.copy(), DEFAULT_COLUMNS)

    dataset_name_by_id = {}
    if not datasets_df.empty and {"id", "name"}.issubset(datasets_df.columns):
        dataset_name_by_id = dict(zip(datasets_df["id"], datasets_df["name"]))

    with open(path, "w", encoding="utf-8") as f:
        f.write("WorldQuant Brain Dataset Catalog\n")
        f.write("=" * 36 + "\n\n")
        f.write(f"Total datasets: {fields_df['dataset_id'].nunique()}\n")
        f.write(f"Total fields: {len(fields_df)}\n\n")

        for dataset_id, group in fields_df.groupby("dataset_id", sort=True):
            dataset_name = dataset_name_by_id.get(dataset_id, "")
            title = f"{dataset_id}"
            if dataset_name and dataset_name != dataset_id:
                title += f" - {dataset_name}"
            f.write(title + "\n")
            f.write("-" * len(title) + "\n")
            f.write(f"Field count: {len(group)}\n\n")

            for _, row in group.sort_values(["type", "id"]).iterrows():
                field_id = row.get("id") or ""
                field_type = row.get("type") or ""
                name = row.get("name") or ""
                description = row.get("description") or ""
                category = row.get("category") or ""
                subcategory = row.get("subcategory") or ""

                f.write(f"- {field_id} [{field_type}]\n")
                if name:
                    f.write(f"  name: {name}\n")
                if category or subcategory:
                    f.write(f"  category: {category} / {subcategory}\n")
                if description:
                    f.write(f"  description: {description}\n")
                f.write("\n")
            f.write("\n")
    print(f"Wrote {path}")


def crawl(args):
    output_dir = Path(args.output_dir)
    s = login()

    datasets_df = get_datasets(
        s,
        region=args.region,
        universe=args.universe,
        delay=args.delay,
    )
    datasets_df = flatten_list_values(datasets_df)
    save_csv(datasets_df, output_dir / "datasets.csv")

    dataset_ids = select_dataset_ids(datasets_df, args.dataset, args.limit_datasets)
    print(f"Selected {len(dataset_ids)} datasets")

    all_fields = []
    for dataset_id in dataset_ids:
        try:
            fields_df = fetch_dataset_fields(
                s,
                dataset_id,
                args.region,
                args.universe,
                args.delay,
                output_dir,
                resume=not args.no_resume,
                max_retries=getattr(args, "max_retries", 12),
                page_delay=getattr(args, "page_delay", 3),
                jitter=getattr(args, "jitter", 1),
                timeout=getattr(args, "request_timeout", 30),
            )
            if not fields_df.empty:
                all_fields.append(fields_df)
        except Exception as e:
            print(f"Failed dataset={dataset_id}: {e}")

    if not all_fields:
        print("No data fields were fetched")
        return

    fields_all = pd.concat(all_fields, ignore_index=True)
    fields_all = flatten_list_values(fields_all)
    save_csv(fields_all, output_dir / "datafields_all.csv")

    readable_cols = [col for col in DEFAULT_COLUMNS if col in fields_all.columns]
    extra_cols = [col for col in fields_all.columns if col not in readable_cols]
    save_csv(fields_all[readable_cols + extra_cols], output_dir / "datafields_readable.csv")
    write_fields_for_ai_jsonl(fields_all, datasets_df, output_dir / "fields_for_ai.jsonl")
    write_readable_txt(fields_all, datasets_df, output_dir / "datafields_readable.txt")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Crawl WorldQuant Brain datasets and data fields into CSV and TXT files."
    )
    parser.add_argument("--region", default="USA", help="Brain region, for example USA, EUR, CHN, JPN")
    parser.add_argument("--universe", default="TOP3000", help="Brain universe, for example TOP3000")
    parser.add_argument("--delay", default=1, type=int, help="Data delay")
    parser.add_argument(
        "--dataset",
        action="append",
        help="Dataset id to fetch. Can be used multiple times. If omitted, fetches all datasets.",
    )
    parser.add_argument("--limit-datasets", type=int, help="Limit number of datasets when fetching all")
    parser.add_argument("--output-dir", default="dataset_catalog", help="Output folder")
    parser.add_argument("--no-resume", action="store_true", help="Re-fetch datasets even if CSV files exist")
    parser.add_argument("--max-retries", type=int, default=12, help="Maximum retries after API 429 rate limits")
    parser.add_argument("--page-delay", type=float, default=3, help="Seconds to wait between field pages")
    parser.add_argument("--jitter", type=float, default=1, help="Extra random seconds added to page waits")
    parser.add_argument("--request-timeout", type=float, default=30, help="HTTP request timeout in seconds")
    return parser.parse_args()


if __name__ == "__main__":
    crawl(parse_args())
