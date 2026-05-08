import argparse
import json
from time import sleep
from datetime import date, timedelta
from pathlib import Path

from machine_lib import (
    DEFAULT_RESULTS_CSV,
    build_decay_retest_list,
    check_submission,
    export_feedback_artifacts,
    first_order_factory,
    get_alphas,
    get_datafields,
    get_group_second_order_factory,
    login,
    load_task_pool,
    multi_simulate,
    prepare_alpha_list,
    print_feedback_report,
    print_resume_status,
    process_datafields,
    prune,
    select_high_quality_alphas,
    trade_when_factory,
    ts_ops,
)
from wq_assistant.ai_client import AIConfigError
from wq_assistant.ai_workflow import (
    run_backtest_loop,
    run_enqueue,
    run_improve,
    run_propose,
    run_review,
)
from crawl_datasets import crawl as crawl_datasets_command


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
    "max_alphas_per_run": 3,
    "task_size": 3,
    "pool_size": 1,
    "simulation_mode": "single",
    "alpha_shuffle": False,
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
    "feedback_output_dir": "results",
    "select_min_sharpe": 1.6,
    "select_min_fitness": 1.3,
    "select_top_n": 50,
    "select_expr_width": 96,
    "loop_sleep_seconds": 6,
    "error_sleep_seconds": 6,
    "loop_max_batches": None,
    "ai_api_key": "",
    "ai_base_url": "https://api.deepseek.com/chat/completions",
    "ai_model": "deepseek-chat",
    "ai_timeout_seconds": 120,
    "ai_temperature": 0.2,
    "ai_proposal_count": 20,
    "ai_max_fields": 80,
    "ai_feedback_limit": 80,
    "idea_id_prefix": "ai",
    "fields_for_ai_path": "dataset_catalog/fields_for_ai.jsonl",
    "operator_notes_path": "docs/brain_operators.md",
    "feedback_for_ai_path": "results/simulation_feedback.jsonl",
    "ideas_path": "ideas/alpha_ideas.jsonl",
    "improved_ideas_path": "ideas/improved_ideas.jsonl",
    "ai_review_path": "ideas/ai_review.jsonl",
    "backtest_queue_path": "state/backtest_queue.jsonl",
    "queue_max_attempts": 2,
    "crawl_output_dir": "dataset_catalog",
    "crawl_dataset": [],
    "crawl_dataset_name": [],
    "crawl_limit_datasets": None,
    "crawl_preview": 20,
    "crawl_no_resume": False,
    "crawl_max_retries": 12,
    "crawl_page_delay": 1.5,
    "crawl_jitter": 0.5,
    "crawl_request_timeout": 30,
    "crawl_pause_between_datasets": 3,
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
    max_alphas_per_run = config.get("max_alphas_per_run")
    if max_alphas_per_run is not None:
        max_count = min(int(max_count), int(max_alphas_per_run))

    alpha_list = prepare_alpha_list(
        alpha_list,
        max_count=max_count,
        shuffle=bool(config.get("alpha_shuffle", False)),
        skip_logged=bool(config["skip_logged"]),
        results_csv=config["results_csv"],
    )
    if not alpha_list:
        print("No new alpha expressions to simulate")
        return 0
    pools = make_pools(alpha_list, config)
    multi_simulate(
        pools,
        config["neutralization"],
        config["region"],
        config["universe"],
        0,
        mode=config["simulation_mode"],
        results_csv=config["results_csv"],
        error_sleep_seconds=float(config.get("error_sleep_seconds", 6)),
    )
    return len(alpha_list)


def build_first_order_alpha_list(config):
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
    return [(expr, int(config["init_decay"])) for expr in expressions]


def run_first_order(config):
    alpha_list = build_first_order_alpha_list(config)
    return run_simulations(alpha_list, config, int(config["max_first_order"]))


def run_first_order_loop(config):
    batch = 0
    sleep_seconds = float(config.get("loop_sleep_seconds", 6))
    max_batches = config.get("loop_max_batches")
    max_batches = int(max_batches) if max_batches is not None else None

    print("Continuous first-order mode started.")
    print("Press Ctrl+C to stop. Completed results are saved after each simulation.")
    print(
        "Each batch runs at most %s alpha(s), then waits %.0f seconds."
        % (config.get("max_alphas_per_run", 3), sleep_seconds)
    )
    print("Building first-order alpha queue once for this loop...")
    alpha_list = build_first_order_alpha_list(config)

    try:
        while True:
            if max_batches is not None and batch >= max_batches:
                print(f"Reached loop_max_batches={max_batches}; stopping.")
                break
            batch += 1
            print(f"\n=== First-order batch {batch} ===")
            simulated_count = run_simulations(alpha_list, config, int(config["max_first_order"]))
            if simulated_count == 0:
                print("No new first-order alpha expressions remain; stopping loop.")
                break
            print_resume_status(config["results_csv"], recent_n=3)
            if sleep_seconds > 0:
                print(f"Waiting {sleep_seconds:.0f}s before next batch...")
                sleep(sleep_seconds)
    except KeyboardInterrupt:
        print("\nStopped by user. You can resume with the same command later.")


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
    export_feedback_artifacts(
        config["results_csv"],
        output_dir=config["feedback_output_dir"],
        min_sharpe=config["feedback_min_sharpe"],
        min_fitness=config["feedback_min_fitness"],
        max_turnover=config["feedback_max_turnover"],
    )


def run_select(config):
    select_high_quality_alphas(
        config["results_csv"],
        output_dir=config["feedback_output_dir"],
        min_sharpe=config["select_min_sharpe"],
        min_fitness=config["select_min_fitness"],
        top_n=config["select_top_n"],
        expr_width=config["select_expr_width"],
    )


def run_status(config):
    print_resume_status(config["results_csv"])


def run_crawl_fields(config):
    args = argparse.Namespace(
        region=config["region"],
        universe=config["universe"],
        delay=int(config.get("delay", 1)),
        dataset=config.get("crawl_dataset") or [config["dataset_id"]],
        dataset_name=config.get("crawl_dataset_name") or None,
        limit_datasets=config.get("crawl_limit_datasets"),
        output_dir=config.get("crawl_output_dir", "dataset_catalog"),
        preview=int(config.get("crawl_preview", 20)),
        no_resume=bool(config.get("crawl_no_resume", False)),
        max_retries=int(config.get("crawl_max_retries", 12)),
        page_delay=float(config.get("crawl_page_delay", 1.5)),
        jitter=float(config.get("crawl_jitter", 0.5)),
        request_timeout=float(config.get("crawl_request_timeout", 30)),
        pause_between_datasets=float(config.get("crawl_pause_between_datasets", 3)),
    )
    crawl_datasets_command(args)


def run_ai_command(fn, config):
    try:
        return fn(config)
    except AIConfigError as e:
        print(e)
        print("Example:")
        print('  export DEEPSEEK_API_KEY="your_api_key"')
        print("or set ai_api_key in config.json.")
        return None
    except FileNotFoundError as e:
        print(e)
        print("If this is about fields_for_ai.jsonl, run:")
        print("  python run_workflow.py crawl-fields --config config.json")
        return None


def main():
    parser = argparse.ArgumentParser(description="Run the WorldQuant Brain alpha mining workflow")
    parser.add_argument(
        "action",
        choices=[
            "first",
            "first-loop",
            "second",
            "third",
            "retest-decay",
            "submit-check",
            "report",
            "select",
            "status",
            "crawl-fields",
            "propose",
            "enqueue",
            "backtest-loop",
            "review",
            "improve",
            "all",
        ],
        help="Workflow step to run",
    )
    parser.add_argument("--config", default="config.example.json", help="Path to JSON config file")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.action in {"first", "all"}:
        run_first_order(config)
    if args.action == "first-loop":
        run_first_order_loop(config)
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
    if args.action in {"select", "all"}:
        run_select(config)
    if args.action == "status":
        run_status(config)
    if args.action == "crawl-fields":
        run_crawl_fields(config)
    if args.action == "propose":
        run_ai_command(run_propose, config)
    if args.action == "enqueue":
        run_enqueue(config)
    if args.action == "backtest-loop":
        run_backtest_loop(config)
    if args.action == "review":
        run_ai_command(run_review, config)
    if args.action == "improve":
        run_improve(config)


if __name__ == "__main__":
    main()
