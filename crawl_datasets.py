import argparse
import re
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


def fetch_dataset_fields(s, dataset_id, region, universe, delay, output_dir, resume=True):
    dataset_path = output_dir / "by_dataset" / f"{safe_filename(dataset_id)}.csv"
    if resume and dataset_path.exists():
        print(f"Skipping {dataset_id}; existing file found")
        df = pd.read_csv(dataset_path)
        return df

    print(f"Fetching data fields for dataset={dataset_id}")
    df = get_datafields(
        s,
        dataset_id=dataset_id,
        region=region,
        universe=universe,
        delay=delay,
    )
    if df.empty:
        print(f"No fields found for dataset={dataset_id}")
        return df

    df = flatten_list_values(df)
    df.insert(0, "dataset_id", dataset_id)
    df.insert(1, "region", region)
    df.insert(2, "universe", universe)
    df.insert(3, "delay", delay)
    save_csv(df, dataset_path)
    return df


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
    return parser.parse_args()


if __name__ == "__main__":
    crawl(parse_args())
