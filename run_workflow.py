import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from machine_lib import (
    DEFAULT_RESULTS_CSV,
    build_decay_retest_list,
    check_submission,
    first_order_factory,
    get_alphas,
    get_datafields,
    get_group_second_order_factory,
    login,
    load_task_pool,
    multi_simulate,
    prepare_alpha_list,
    print_feedback_report,
    process_datafields,
    prune,
    trade_when_factory,
    ts_ops,
)


DEFAULT_CONFIG = {
    "region": "USA",
    "universe": "TOP3000",
    "dataset_id": "analyst4",
    "data_type": "matrix",
    "neutralization": "SUBINDUSTRY",
    "init_decay": 6,
    "first_order_ops": ["rank", "zscore", "ts_rank", "ts_delta", "ts_mean"],
    "max_first_order": 100,
    "max_second_order": 200,
    "max_third_order": 200,
    "task_size": 10,
    "pool_size": 3,
    "simulation_mode": "auto",
    "results_csv": str(DEFAULT_RESULTS_CSV),
    "skip_logged": True,
    "first_order_sharpe": 1.2,
    "second_order_sharpe": 1.4,
    "submit_sharpe": 1.58,
    "fitness": 1.0,
    "scan_alpha_num": 200,
    "prune_prefix": "analyst",
    "prune_keep": 5,
    "group_ops": ["group_neutralize", "group_rank", "group_zscore"],
    "core_groups_only": True,
    "group_limit": 8,
    "include_region_events": True,
    "max_trade_events": 20,
    "submit_mark_color": "GREEN",
    "submit_mark_tags": ["submittable", "wq-assistant"],
    "feedback_min_sharpe": 1.2,
    "feedback_min_fitness": 1.0,
    "feedback_max_turnover": 0.7,
}


def default_dates():
    today = date.today()
    tomorrow = today + timedelta(days=1)
    return today.strftime("%m-%d"), tomorrow.strftime("%m-%d")


def load_config(path):
    config = DEFAULT_CONFIG.copy()
    start_date, end_date = default_dates()
    config.setdefault("start_date", start_date)
    config.setdefault("end_date", end_date)

    path = Path(path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            config.update(json.load(f))
    else:
        print(f"Config file {path} not found; using defaults")

    return config


def make_pools(alpha_list, config):
    return load_task_pool(alpha_list, int(config["task_size"]), int(config["pool_size"]))


def run_simulations(alpha_list, config, max_count):
    alpha_list = prepare_alpha_list(
        alpha_list,
        max_count=max_count,
        shuffle=True,
        skip_logged=bool(config["skip_logged"]),
        results_csv=config["results_csv"],
    )
    if not alpha_list:
        print("No new alpha expressions to simulate")
        return
    pools = make_pools(alpha_list, config)
    multi_simulate(
        pools,
        config["neutralization"],
        config["region"],
        config["universe"],
        0,
        mode=config["simulation_mode"],
        results_csv=config["results_csv"],
    )


def run_first_order(config):
    s = login()
    df = get_datafields(
        s,
        dataset_id=config["dataset_id"],
        region=config["region"],
        universe=config["universe"],
        delay=1,
    )
    fields = process_datafields(df, config["data_type"])
    ops = config.get("first_order_ops") or ts_ops
    expressions = first_order_factory(fields, ops)
    alpha_list = [(expr, int(config["init_decay"])) for expr in expressions]
    run_simulations(alpha_list, config, int(config["max_first_order"]))


def run_second_order(config):
    tracker = get_alphas(
        config["start_date"],
        config["end_date"],
        config["first_order_sharpe"],
        config["fitness"],
        config["region"],
        config["scan_alpha_num"],
        "track",
    )
    layer = prune(tracker, config["prune_prefix"], int(config["prune_keep"]))
    alpha_list = []
    for expr, decay in layer:
        for alpha in get_group_second_order_factory(
            [expr],
            config["group_ops"],
            config["region"],
            group_limit=config["group_limit"],
            core_groups_only=config["core_groups_only"],
        ):
            alpha_list.append((alpha, decay))
    run_simulations(alpha_list, config, int(config["max_second_order"]))


def run_third_order(config):
    tracker = get_alphas(
        config["start_date"],
        config["end_date"],
        config["second_order_sharpe"],
        config["fitness"],
        config["region"],
        config["scan_alpha_num"],
        "track",
    )
    layer = prune(tracker, config["prune_prefix"], int(config["prune_keep"]))
    alpha_list = []
    for expr, decay in layer:
        for alpha in trade_when_factory(
            "trade_when",
            expr,
            config["region"],
            include_region_events=config["include_region_events"],
            max_events=config["max_trade_events"],
        ):
            alpha_list.append((alpha, decay))
    run_simulations(alpha_list, config, int(config["max_third_order"]))


def run_retest_decay(config):
    alpha_list = build_decay_retest_list(
        config["results_csv"],
        min_sharpe=config["feedback_min_sharpe"],
        min_fitness=config["feedback_min_fitness"],
        min_turnover=0.3,
        max_count=int(config["max_first_order"]),
    )
    # Same expression with a changed decay is a deliberate re-test.
    config = config.copy()
    config["skip_logged"] = False
    run_simulations(alpha_list, config, int(config["max_first_order"]))


def run_submit_check(config):
    tracker = get_alphas(
        config["start_date"],
        config["end_date"],
        config["submit_sharpe"],
        config["fitness"],
        config["region"],
        config["scan_alpha_num"],
        "submit",
    )
    alpha_ids = [alpha[0] for alpha in tracker]
    gold_bag = []
    check_submission(
        alpha_ids,
        gold_bag,
        0,
        mark_passed=True,
        mark_color=config["submit_mark_color"],
        mark_tags=config["submit_mark_tags"],
    )


def run_report(config):
    print_feedback_report(
        config["results_csv"],
        min_sharpe=config["feedback_min_sharpe"],
        min_fitness=config["feedback_min_fitness"],
        max_turnover=config["feedback_max_turnover"],
    )


def main():
    parser = argparse.ArgumentParser(description="Run the WorldQuant Brain alpha mining workflow")
    parser.add_argument(
        "action",
        choices=["first", "second", "third", "retest-decay", "submit-check", "report", "all"],
        help="Workflow step to run",
    )
    parser.add_argument("--config", default="config.example.json", help="Path to JSON config file")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.action in {"first", "all"}:
        run_first_order(config)
    if args.action in {"second", "all"}:
        run_second_order(config)
    if args.action in {"third", "all"}:
        run_third_order(config)
    if args.action == "retest-decay":
        run_retest_decay(config)
    if args.action in {"submit-check", "all"}:
        run_submit_check(config)
    if args.action in {"report", "all"}:
        run_report(config)


if __name__ == "__main__":
    main()
