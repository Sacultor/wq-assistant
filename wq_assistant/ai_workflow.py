from datetime import datetime
from pathlib import Path

from machine_lib import (
    DEFAULT_RESULTS_CSV,
    load_logged_expressions,
    load_results,
    multi_simulate,
    print_resume_status,
)

from .ai_client import AIConfigError, make_ai_client, parse_json_response
from .jsonl_utils import append_jsonl, read_jsonl, write_jsonl


def project_path(config, key, default):
    return Path(config.get(key, default))


def ideas_path(config):
    return project_path(config, "ideas_path", "ideas/alpha_ideas.jsonl")


def improved_ideas_path(config):
    return project_path(config, "improved_ideas_path", "ideas/improved_ideas.jsonl")


def review_path(config):
    return project_path(config, "ai_review_path", "ideas/ai_review.jsonl")


def queue_path(config):
    return project_path(config, "backtest_queue_path", "state/backtest_queue.jsonl")


def fields_path(config):
    return project_path(config, "fields_for_ai_path", "dataset_catalog/fields_for_ai.jsonl")


def feedback_path(config):
    return project_path(config, "feedback_for_ai_path", "results/simulation_feedback.jsonl")


def existing_expressions(config):
    expressions = set(load_logged_expressions(config.get("results_csv", DEFAULT_RESULTS_CSV)))
    for path in [ideas_path(config), improved_ideas_path(config), queue_path(config)]:
        for record in read_jsonl(path):
            expr = record.get("expression")
            if expr:
                expressions.add(str(expr))
    return expressions


def load_recent_jsonl(path, limit):
    records = read_jsonl(path)
    if limit:
        return records[-int(limit):]
    return records


def normalize_idea(raw, idea_id, source="ai"):
    expression = str(raw.get("expression", "")).strip()
    fields_used = raw.get("fields_used") or raw.get("fields") or []
    if isinstance(fields_used, str):
        fields_used = [fields_used]
    return {
        "idea_id": raw.get("idea_id") or idea_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
        "hypothesis": str(raw.get("hypothesis", "")).strip(),
        "fields_used": fields_used,
        "expression": expression,
        "decay": int(raw.get("decay") or 6),
        "reason": str(raw.get("reason", raw.get("research_basis", ""))).strip(),
        "expected_effect": str(raw.get("expected_effect", "")).strip(),
        "risk": str(raw.get("risk", "")).strip(),
        "status": "pending",
    }


def next_idea_id(existing_count, prefix):
    return f"{prefix}_{existing_count + 1:04d}"


def make_propose_prompt(config, fields, feedback, existing_exprs):
    max_ideas = int(config.get("ai_proposal_count", 20))
    return f"""
You are helping generate WorldQuant Brain FASTEXPR alpha ideas.

Constraints:
- Return ONLY a valid JSON array.
- Generate at most {max_ideas} ideas.
- Each idea must include: hypothesis, fields_used, expression, decay, reason, expected_effect, risk.
- Use only fields shown in the provided field records.
- Avoid expressions already tested or queued.
- Prefer simple, interpretable expressions.
- Use FASTEXPR syntax only.
- Do not submit anything; only propose expressions for later backtesting.
- Account is non-consultant, so ideas will be backtested slowly in batches of 3.

Default preprocessing pattern for raw matrix fields:
winsorize(ts_backfill(FIELD, 120), std=4)

Useful operators:
rank, zscore, normalize, ts_rank, ts_delta, ts_mean, ts_sum, ts_zscore,
group_neutralize, group_rank, group_zscore, trade_when.

Recent feedback can guide you:
- High turnover: smooth more, increase decay, use ts_mean or longer windows.
- Low fitness: reduce noise, try group neutralization, avoid overly reactive transforms.
- Negative sharpe: consider reversing direction in later variants.

Fields:
{fields}

Recent backtest feedback:
{feedback}

Already used expressions:
{list(existing_exprs)[:200]}
""".strip()


def run_propose(config):
    fields = load_recent_jsonl(fields_path(config), int(config.get("ai_max_fields", 80)))
    if not fields:
        raise FileNotFoundError(
            f"No field records found at {fields_path(config)}. Run crawl_datasets.py first."
        )
    feedback = load_recent_jsonl(feedback_path(config), int(config.get("ai_feedback_limit", 80)))
    used = existing_expressions(config)

    client = make_ai_client(config)
    system = "You are a quantitative researcher. Respond only with JSON."
    prompt = make_propose_prompt(config, fields, feedback, used)
    content = client.chat(system, prompt)
    parsed = parse_json_response(content)
    if isinstance(parsed, dict):
        parsed = parsed.get("ideas", [])
    if not isinstance(parsed, list):
        raise ValueError("AI response must be a JSON array of ideas")

    current = read_jsonl(ideas_path(config))
    seen = existing_expressions(config)
    new_ideas = []
    for raw in parsed:
        idea = normalize_idea(
            raw,
            next_idea_id(len(current) + len(new_ideas), config.get("idea_id_prefix", "ai")),
        )
        if not idea["expression"] or idea["expression"] in seen:
            continue
        seen.add(idea["expression"])
        new_ideas.append(idea)

    append_jsonl(ideas_path(config), new_ideas)
    print(f"Wrote {len(new_ideas)} new AI idea(s) to {ideas_path(config)}")
    return new_ideas


def read_all_ideas_for_enqueue(config):
    return read_jsonl(ideas_path(config)) + read_jsonl(improved_ideas_path(config))


def run_enqueue(config):
    ideas = read_all_ideas_for_enqueue(config)
    queue = read_jsonl(queue_path(config))
    queued_exprs = {item.get("expression") for item in queue}
    logged_exprs = set(load_logged_expressions(config.get("results_csv", DEFAULT_RESULTS_CSV)))
    new_items = []
    for idea in ideas:
        expr = idea.get("expression")
        if not expr or expr in queued_exprs or expr in logged_exprs:
            continue
        if idea.get("status") not in {None, "", "pending"}:
            continue
        item = {
            "queue_id": f"q_{len(queue) + len(new_items) + 1:06d}",
            "idea_id": idea.get("idea_id"),
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "expression": expr,
            "decay": int(idea.get("decay") or config.get("init_decay", 6)),
            "status": "queued",
            "attempt": 0,
            "last_error": "",
        }
        new_items.append(item)
        queued_exprs.add(expr)
    if new_items:
        queue.extend(new_items)
        write_jsonl(queue_path(config), queue)
    print(f"Enqueued {len(new_items)} new alpha(s) into {queue_path(config)}")
    return new_items


def update_queue_items(path, queue):
    write_jsonl(path, queue)


def run_backtest_queue_once(config):
    qpath = queue_path(config)
    queue = read_jsonl(qpath)
    if not queue:
        print(f"No queue found at {qpath}. Run propose and enqueue first.")
        return 0

    logged = set(load_logged_expressions(config.get("results_csv", DEFAULT_RESULTS_CSV)))
    for item in queue:
        if item.get("expression") in logged and item.get("status") != "completed":
            item["status"] = "completed"
            item["completed_at"] = datetime.now().isoformat(timespec="seconds")

    batch_size = int(config.get("max_alphas_per_run", 3))
    batch = [item for item in queue if item.get("status") == "queued"][:batch_size]
    if not batch:
        update_queue_items(qpath, queue)
        print("No queued alpha expressions remain.")
        return 0

    for item in batch:
        item["status"] = "running"
        item["attempt"] = int(item.get("attempt") or 0) + 1
        item["started_at"] = datetime.now().isoformat(timespec="seconds")
    update_queue_items(qpath, queue)

    alpha_list = [(item["expression"], int(item.get("decay") or config.get("init_decay", 6))) for item in batch]
    multi_simulate(
        [ [alpha_list] ],
        config["neutralization"],
        config["region"],
        config["universe"],
        0,
        mode=config.get("simulation_mode", "single"),
        results_csv=config.get("results_csv", DEFAULT_RESULTS_CSV),
        error_sleep_seconds=float(config.get("error_sleep_seconds", 6)),
    )

    logged = set(load_logged_expressions(config.get("results_csv", DEFAULT_RESULTS_CSV)))
    max_attempts = int(config.get("queue_max_attempts", 2))
    for item in batch:
        if item["expression"] in logged:
            item["status"] = "completed"
            item["completed_at"] = datetime.now().isoformat(timespec="seconds")
            item["last_error"] = ""
        elif int(item.get("attempt") or 0) >= max_attempts:
            item["status"] = "failed"
            item["failed_at"] = datetime.now().isoformat(timespec="seconds")
            item["last_error"] = "not_logged_after_backtest_attempt"
        else:
            item["status"] = "queued"
            item["last_error"] = "not_logged_after_backtest_attempt"
    update_queue_items(qpath, queue)
    return len(batch)


def run_backtest_loop(config):
    from time import sleep

    max_batches = config.get("loop_max_batches")
    max_batches = int(max_batches) if max_batches is not None else None
    sleep_seconds = float(config.get("loop_sleep_seconds", 6))
    batch = 0
    print("AI queue backtest loop started. Press Ctrl+C to stop.")
    try:
        while True:
            if max_batches is not None and batch >= max_batches:
                print(f"Reached loop_max_batches={max_batches}; stopping.")
                break
            batch += 1
            print(f"\n=== AI queue batch {batch} ===")
            count = run_backtest_queue_once(config)
            print_resume_status(config.get("results_csv", DEFAULT_RESULTS_CSV), recent_n=3)
            if count == 0:
                break
            if sleep_seconds > 0:
                print(f"Waiting {sleep_seconds:.0f}s before next batch...")
                sleep(sleep_seconds)
    except KeyboardInterrupt:
        print("\nStopped by user. Queue state is saved; rerun the same command to resume.")


def make_review_prompt(config, feedback_records, ideas):
    return f"""
Review recent WorldQuant Brain alpha backtests.

Return ONLY a valid JSON array. Each item must include:
idea_id, expression, verdict, likely_reason, suggested_changes, next_expression, decay.

Rules:
- verdict must be one of: promising, improve, reject.
- If sharpe > 1.6 and fitness > 1.3, mark promising.
- For high turnover, suggest smoother expression or higher decay.
- For weak sharpe/fitness, suggest a concrete improved FASTEXPR expression.
- Use fields from the original idea when possible.
- Do not duplicate the original expression as next_expression.

Recent feedback:
{feedback_records}

Known ideas:
{ideas}
""".strip()


def run_review(config):
    feedback = load_recent_jsonl(feedback_path(config), int(config.get("ai_feedback_limit", 80)))
    if not feedback:
        print(f"No feedback found at {feedback_path(config)}")
        return []
    ideas = read_all_ideas_for_enqueue(config)
    client = make_ai_client(config)
    content = client.chat(
        "You are a quantitative research reviewer. Respond only with JSON.",
        make_review_prompt(config, feedback, ideas[-100:]),
    )
    parsed = parse_json_response(content)
    if isinstance(parsed, dict):
        parsed = parsed.get("reviews", [])
    if not isinstance(parsed, list):
        raise ValueError("AI review response must be a JSON array")
    for record in parsed:
        record["created_at"] = datetime.now().isoformat(timespec="seconds")
    append_jsonl(review_path(config), parsed)
    print(f"Wrote {len(parsed)} review record(s) to {review_path(config)}")
    return parsed


def run_improve(config):
    reviews = read_jsonl(review_path(config))
    if not reviews:
        print(f"No reviews found at {review_path(config)}. Run review first.")
        return []
    used = existing_expressions(config)
    current = read_jsonl(improved_ideas_path(config))
    new_ideas = []
    for review in reviews[-int(config.get("ai_feedback_limit", 80)):]:
        expr = str(review.get("next_expression", "")).strip()
        if not expr or expr in used:
            continue
        idea = normalize_idea(
            {
                "hypothesis": review.get("likely_reason", ""),
                "fields_used": review.get("fields_used", []),
                "expression": expr,
                "decay": review.get("decay") or config.get("init_decay", 6),
                "reason": "; ".join(review.get("suggested_changes", []))
                if isinstance(review.get("suggested_changes"), list)
                else str(review.get("suggested_changes", "")),
                "expected_effect": f"improved from {review.get('idea_id', '')}",
                "risk": "AI-generated improvement; requires backtest",
            },
            next_idea_id(len(current) + len(new_ideas), "improved"),
            source="ai_review",
        )
        used.add(expr)
        new_ideas.append(idea)
    append_jsonl(improved_ideas_path(config), new_ideas)
    print(f"Wrote {len(new_ideas)} improved idea(s) to {improved_ideas_path(config)}")
    return new_ideas
