# wq-assistant

`wq-assistant` is a small WorldQuant Brain alpha mining workflow. It generates FASTEXPR alpha expressions, submits them to Brain simulations, filters promising results, then expands them into second-order and third-order variants.

The project is intended for research automation. It does not auto-submit alphas to production; the final submission is still done manually on the Brain website.

## Files

- `machine_lib.py`: login, data-field loading, alpha generation, simulation submission, result filtering, and submission checks.
- `run_workflow.py`: command-line workflow runner for users who do not want to edit Python code.
- `crawl_datasets.py`: dataset and data-field crawler that exports readable CSV and TXT catalogs.
- `wq_assistant/`: AI workflow helpers for DeepSeek proposals, queue backtesting, reviews, and improvements.
- `config.example.json`: editable workflow configuration template.
- `examples/alpha_machine.ipynb`: notebook workflow for running the mining process interactively.
- `credentials.txt`: local Brain credentials. This file is ignored by Git.

## Recommended Simple Workflow

Use this path if you do not want to edit Python code.

0. Install dependencies:

```bash
python -m pip install -r requirements.txt
```

1. Create your local config:

```bash
cp config.example.json config.json
```

2. Edit only these fields in `config.json` first:

```json
{
  "region": "USA",
  "universe": "TOP3000",
  "dataset_id": "analyst4",
  "neutralization": "SUBINDUSTRY",
  "max_first_order": 100,
  "start_date": "05-06",
  "end_date": "05-07"
}
```

The default config is safe for non-consultant accounts:

```json
{
  "simulation_mode": "single",
  "max_alphas_per_run": 3,
  "task_size": 3,
  "pool_size": 1,
  "alpha_shuffle": false,
  "skip_logged": true
}
```

This means each run tests at most 3 new alphas. Completed expressions are logged in `results/simulation_results.csv`; future runs skip them.

3. Run the next 3 first-order alphas:

```bash
python run_workflow.py first --config config.json
```

4. If you are interrupted, run the same command again later:

```bash
python run_workflow.py first --config config.json
```

The workflow resumes by skipping expressions already logged in `results/simulation_results.csv`. If the interruption happens during an active simulation before the result is written, that one active alpha may be retried; completed alphas will not be repeated.

5. If you want it to keep running until you stop it manually:

```bash
python run_workflow.py first-loop --config config.json
```

This still runs at most 3 alphas per batch. After each batch it waits `loop_sleep_seconds` seconds, then starts the next batch. Press `Ctrl+C` to stop. Completed results remain saved in `results/simulation_results.csv`.

When a completed alpha has `fitness > 1.3` and `sharpe > 1.6`, the terminal output marks it as `HIGH QUALITY`, and the JSONL feedback record includes `quality_tag: "HIGH_QUALITY"`.

Use `Ctrl+C` to stop the loop. Do not use `Ctrl+Z`; it suspends the process in the shell. If that happens, run `fg`, then press `Ctrl+C`.

6. Check local progress:

```bash
python run_workflow.py status --config config.json
```

7. Review feedback from completed simulations:

```bash
python run_workflow.py report --config config.json
```

8. Select high-quality alphas in a table, using the default rule `fitness > 1.3` and `sharpe > 1.6`:

```bash
python run_workflow.py select --config config.json
```

This prints a table with `#`, `Sharpe`, `Fit`, `When`, and `Alpha Expression`, and writes:

- `results/high_quality_alphas.csv`: full selected rows.
- `results/high_quality_alphas.txt`: readable table output.

9. Run second-order and third-order expansion only if the report shows promising candidates. These commands also run at most 3 new alphas per call:

```bash
python run_workflow.py second --config config.json
python run_workflow.py third --config config.json
```

10. Re-test high-turnover but promising alphas with higher decay:

```bash
python run_workflow.py retest-decay --config config.json
```

11. Check final candidates and mark passing alphas on Brain:

```bash
python run_workflow.py submit-check --config config.json
```

The workflow writes every completed simulation to `results/simulation_results.csv`. Future runs skip already tested expressions by default, so the workflow keeps learning from previous results instead of repeating the same work.

## Commands

```bash
python run_workflow.py first --config config.json        # generate and simulate first-order alphas
python run_workflow.py first-loop --config config.json   # keep running first-order batches until Ctrl+C
python run_workflow.py status --config config.json       # show local resume/progress status
python run_workflow.py report --config config.json       # summarize all local backtest feedback
python run_workflow.py select --config config.json       # print/write fitness>1.3 and sharpe>1.6 alphas
python run_workflow.py second --config config.json       # expand promising alphas with group operators
python run_workflow.py third --config config.json        # expand promising alphas with trade_when events
python run_workflow.py retest-decay --config config.json # retest high-turnover alphas with higher decay
python run_workflow.py submit-check --config config.json # check final candidates
```

## AI Agent Workflow

Set your DeepSeek API key first:

```bash
export DEEPSEEK_API_KEY="your_deepseek_api_key"
```

Or put it in `config.json`:

```json
{
  "ai_api_key": "your_deepseek_api_key",
  "ai_model": "deepseek-chat"
}
```

Minimal AI loop:

```bash
python run_workflow.py crawl-fields --config config.json
python run_workflow.py propose --config config.json
python run_workflow.py enqueue --config config.json
python run_workflow.py backtest-loop --config config.json
python run_workflow.py review --config config.json
python run_workflow.py improve --config config.json
python run_workflow.py enqueue --config config.json
python run_workflow.py backtest-loop --config config.json
```

What each command does:

- `crawl-fields`: fetches dataset fields and writes `dataset_catalog/fields_for_ai.jsonl`.
- `propose`: asks DeepSeek to generate hypothesis-backed FASTEXPR ideas into `ideas/alpha_ideas.jsonl`.
- `enqueue`: dedupes ideas and writes runnable items to `state/backtest_queue.jsonl`.
- `backtest-loop`: runs queued expressions, at most 3 per batch, with Ctrl+C resume support.
- `review`: asks DeepSeek to review recent backtest feedback and write `ideas/ai_review.jsonl`.
- `improve`: converts AI review suggestions into `ideas/improved_ideas.jsonl`.

Local generated folders `ideas/`, `state/`, `results/`, and `dataset_catalog/` are ignored by Git.

The high-quality selection thresholds are configurable:

```json
{
  "max_alphas_per_run": 3,
  "simulation_mode": "single",
  "alpha_shuffle": false,
  "loop_sleep_seconds": 6,
  "error_sleep_seconds": 6,
  "loop_max_batches": null,
  "select_min_sharpe": 1.6,
  "select_min_fitness": 1.3,
  "select_top_n": 50,
  "select_expr_width": 96
}
```

## Data Field Crawler

Use `crawl_datasets.py` when you want to inspect the data fields inside Brain datasets before designing a strategy.

Fetch all datasets for a region and universe:

```bash
python crawl_datasets.py --region USA --universe TOP3000 --delay 1
```

Fetch only one or several datasets:

```bash
python crawl_datasets.py --region USA --universe TOP3000 --dataset analyst4 --dataset news12
```

Fetch the fields shown under a dataset page by dataset name/search text:

```bash
python crawl_datasets.py --region USA --universe TOP3000 --dataset-name "Company Fundamental"
```

Test with only the first few datasets:

```bash
python crawl_datasets.py --region USA --universe TOP3000 --limit-datasets 5
```

Outputs are written to `dataset_catalog/`:

- `field_dictionary.csv`: main table of fields, with dataset id, field id, type, name, and description.
- Main columns match the Brain Fields table: `field`, `description`, `type`, `coverage`, `date_coverage`, `alphas`.
- `fields_for_ai.jsonl`: one field per line, with dataset metadata and field context, suitable for feeding to an AI model.
- `fields_by_dataset.txt`: readable text index of fields grouped by dataset.
- `datafields_raw_all.csv`: raw field table returned by the API.
- `datasets.csv`: dataset index, used only to know which datasets were scanned.
- `by_dataset/*.csv`: raw fields for each dataset.

The crawler resumes by default. If a per-dataset CSV already exists, it skips that dataset. Use `--no-resume` to force a fresh fetch. The defaults are intentionally gentle: it waits between dataset pages, adds random jitter, honors `Retry-After` on 429 responses, and reuses the first field-page response instead of requesting offset 0 twice. You can slow it further with:

```bash
python crawl_datasets.py --region USA --universe TOP3000 --page-delay 3 --jitter 2 --pause-between-datasets 8
```

## Backtest Feedback For AI

Every completed simulation is appended to:

- `results/simulation_results.csv`: table format for spreadsheet analysis and duplicate skipping.
- `results/simulation_feedback.jsonl`: one JSON record per backtest with band, detected issues, suggested next actions, operators, fields, metrics, and expression.

Running the report command also writes:

- `results/feedback_for_ai.jsonl`: regenerated full feedback log for AI analysis.
- `results/feedback_summary.json`: compact diagnostic summary with issue counts, operator/field counts, thresholds, and top candidates.
- `results/candidate_alphas.csv`: filtered candidate table.

## Credentials

The code first tries environment variables:

```bash
export WQB_USERNAME="your_username"
export WQB_PASSWORD="your_password"
```

If those are not set, it reads `credentials.txt` in the project root:

```json
{"username": "your_username", "password": "your_password"}
```

## Basic Workflow

Open `examples/alpha_machine.ipynb` or run the same code in a Python session.

```python
from machine_lib import *

s = login()
```

Choose a market, universe, dataset, and neutralization style:

```python
region = "USA"
universe = "TOP3000"
dataset_id = "analyst4"
neutralization = "SUBINDUSTRY"
```

Load and preprocess data fields:

```python
df = get_datafields(
    s,
    dataset_id=dataset_id,
    region=region,
    universe=universe,
    delay=1,
)

fields = process_datafields(df, "matrix")
```

Generate first-order alphas:

```python
first_order = first_order_factory(fields, ts_ops)
fo_alpha_list = [(alpha, 6) for alpha in first_order]
fo_alpha_list = prepare_alpha_list(fo_alpha_list, max_count=100, shuffle=True)
```

`prepare_alpha_list()` removes duplicate expressions and, by default, skips expressions already present in `results/simulation_results.csv`.

Run simulations:

```python
fo_pools = load_task_pool(fo_alpha_list, 10, 3)
multi_simulate(fo_pools, neutralization, region, universe, 0, mode="auto")
```

`mode="auto"` checks whether your account has multi-simulation permission. If not, it falls back to single-alpha simulations with retry handling.

After each completed simulation, the code prints a readable result line:

```text
Result 0.0: id=... sharpe= 1.523 fitness= 1.114 turnover= 0.271 margin= 0.0042 decay=6
  expr: ts_rank(...)
```

The same result is appended to `results/simulation_results.csv`, including alpha ID, Sharpe, Fitness, Turnover, Margin, Decay, date, region, universe, neutralization, status, and expression. The `results/` folder is ignored by Git.

## Filtering Results

Use `get_alphas()` to fetch promising alphas created in a date window. You can pass `MM-DD` dates, or full `YYYY-MM-DD` dates.

```python
fo_tracker = get_alphas("05-05", "05-06", 1.2, 1, "USA", 100, "track")
```

Parameters:

- `start_date`, `end_date`: date window. End date is exclusive.
- `sharpe_th`: minimum Sharpe.
- `fitness_th`: minimum Fitness.
- `region`: Brain region.
- `alpha_num`: maximum records to scan.
- `usage`: use `"track"` for research and `"submit"` for final candidates.
- `year`: optional year when using `MM-DD`, for example `year=2026`.

`usage="track"` also searches strongly negative alphas and flips their sign. `usage="submit"` only searches positive candidates.

## Second-Order Expansion

Second-order alphas apply group operations to promising first-order alphas:

```python
fo_layer = prune(fo_tracker, "analyst", 5)

group_ops = ["group_neutralize", "group_rank", "group_zscore"]
so_alpha_list = []

for expr, decay in fo_layer:
    for alpha in get_group_second_order_factory([expr], group_ops, region, core_groups_only=True, group_limit=8):
        so_alpha_list.append((alpha, decay))

so_alpha_list = prepare_alpha_list(so_alpha_list, max_count=200, shuffle=True)
so_pools = load_task_pool(so_alpha_list, 10, 3)
multi_simulate(so_pools, neutralization, region, universe, 0)
```

Choose the `prune()` prefix to match your dataset field prefix. If you use `analyst4`, do not leave an old prefix like `mdl26`.

Use `core_groups_only=True` and `group_limit=...` to keep the group search space under control.

## Third-Order Expansion

Third-order alphas wrap the current expression with `trade_when()` events:

```python
so_tracker = get_alphas("05-05", "05-06", 1.4, 1, region, 200, "track")
so_layer = prune(so_tracker, "analyst", 5)

th_alpha_list = []
for expr, decay in so_layer:
    for alpha in trade_when_factory("trade_when", expr, region, include_region_events=True, max_events=20):
        th_alpha_list.append((alpha, decay))

th_alpha_list = prepare_alpha_list(th_alpha_list, max_count=200, shuffle=True)
th_pools = load_task_pool(th_alpha_list, 10, 3)
multi_simulate(th_pools, neutralization, region, universe, 0)
```

`include_region_events=True` adds region-specific event triggers where available. Use `max_events` to keep the search size controlled.

## Submission Check

Find stronger final candidates:

```python
th_tracker = get_alphas("05-05", "05-06", 1.58, 1, region, 200, "submit")
stone_bag = [alpha[0] for alpha in th_tracker]

gold_bag = []
check_submission(stone_bag, gold_bag, 0)
view_alphas(gold_bag)
```

`view_alphas()` prints candidates sorted by Sharpe and includes `PROD_CORRELATION`.

By default, `check_submission()` marks passing alphas on Brain with color `GREEN` and tags `submittable` and `wq-assistant`. To customize:

```python
check_submission(
    stone_bag,
    gold_bag,
    0,
    mark_passed=True,
    mark_color="GREEN",
    mark_tags=["submittable", "wq-assistant", "review"],
)
```

## Key Parameters To Tune

- `dataset_id`: source of raw signals, such as `analyst4` or `news12`.
- `region`: market, such as `USA`, `EUR`, `CHN`, `JPN`.
- `universe`: stock universe, such as `TOP3000`.
- `neutralization`: common values include `MARKET`, `SECTOR`, `INDUSTRY`, `SUBINDUSTRY`.
- `init_decay`: initial decay attached to generated alphas. Larger values usually reduce turnover.
- `ts_ops`: time-series operators used in first-order generation.
- `ts_factory()` windows: currently `[5, 22, 66, 120, 240]`.
- `group_ops`: second-order group transformations.
- `trade_when_factory()` events: third-order entry and exit logic.
- `max_count`: practical limit for each simulation layer.
- `group_limit`: maximum group definitions used per group operator.
- `core_groups_only`: use only core market, sector, industry, subindustry, cap, volatility, and liquidity groups.
- `results_csv`: local CSV log path used for result persistence and duplicate skipping.

## Practical Advice

Start small. Run 50 to 200 alphas first, inspect result quality, then scale up.

Use stricter thresholds at later layers:

```python
first_order_threshold = 1.2
second_order_threshold = 1.4
submit_threshold = 1.58
```

Keep `load_task_pool(..., 10, 3)` conservative if your account is rate-limited. Increase the second value only if simulations are stable.

Always verify final candidates on the Brain website before submitting.

---

# wq-assistant 中文版

`wq-assistant` 是一个用于 WorldQuant Brain 的 alpha 挖掘工作流。它会生成 FASTEXPR alpha 表达式，提交到 Brain 做模拟回测，筛选表现较好的结果，然后继续扩展成二阶和三阶 alpha。

这个项目用于研究自动化。它不会自动把 alpha 提交到生产环境；最终提交仍然需要你在 Brain 网页上手动完成。

## 文件说明

- `machine_lib.py`：负责登录、加载数据字段、生成 alpha、提交模拟、筛选结果和提交前检查。
- `run_workflow.py`：命令行工作流脚本，适合不想改 Python 代码的用户。
- `crawl_datasets.py`：数据集和字段爬取脚本，会导出便于阅读的 CSV 和 TXT 目录。
- `wq_assistant/`：DeepSeek 候选生成、队列回测、AI 复盘和改进相关辅助代码。
- `config.example.json`：可编辑的工作流配置模板。
- `examples/alpha_machine.ipynb`：交互式 notebook 工作流，用来一步步运行挖掘流程。
- `credentials.txt`：本地 Brain 账号凭据。这个文件已经被 Git 忽略，不会上传。

## 推荐的简易工作流

如果你不想改代码，按这个流程走。

0. 安装依赖：

```bash
python -m pip install -r requirements.txt
```

1. 创建自己的本地配置：

```bash
cp config.example.json config.json
```

2. 先只修改 `config.json` 里的这些字段：

```json
{
  "region": "USA",
  "universe": "TOP3000",
  "dataset_id": "analyst4",
  "neutralization": "SUBINDUSTRY",
  "max_first_order": 100,
  "start_date": "05-06",
  "end_date": "05-07"
}
```

默认配置已经按非顾问账号处理：

```json
{
  "simulation_mode": "single",
  "max_alphas_per_run": 3,
  "task_size": 3,
  "pool_size": 1,
  "alpha_shuffle": false,
  "skip_logged": true
}
```

含义是：每次命令最多测 3 个新 alpha；完成的表达式会写入 `results/simulation_results.csv`，以后自动跳过。

3. 跑下一批 3 个一阶 alpha：

```bash
python run_workflow.py first --config config.json
```

4. 如果中途被打断，回来后直接重新跑同一个命令：

```bash
python run_workflow.py first --config config.json
```

脚本会读取 `results/simulation_results.csv`，跳过已经完成并记录过的表达式，从后面继续。只有一种情况可能重测：刚好在某个 alpha 正在回测、还没写入结果时被强制中断，那么这个正在跑的 alpha 下次可能会再测一次；已经完成并写入日志的不会重复。

5. 如果想让它一直跑，直到你手动停止：

```bash
python run_workflow.py first-loop --config config.json
```

它仍然是每轮最多回测 3 个 alpha。每轮结束后会等待 `loop_sleep_seconds` 秒，然后开始下一轮。你按 `Ctrl+C` 就会停止。已完成结果会保存在 `results/simulation_results.csv`，下次再跑会自动跳过。

如果某个 alpha 满足 `fitness > 1.3` 且 `sharpe > 1.6`，终端会标注 `HIGH QUALITY`，JSONL 反馈里也会写入 `quality_tag: "HIGH_QUALITY"`。

停止循环要用 `Ctrl+C`。不要用 `Ctrl+Z`，它只是把进程挂起；如果已经挂起，先输入 `fg` 恢复，再按 `Ctrl+C`。

6. 查看本地断点状态：

```bash
python run_workflow.py status --config config.json
```

7. 查看已完成回测的反馈报告：

```bash
python run_workflow.py report --config config.json
```

8. 按 `fitness > 1.3` 且 `sharpe > 1.6` 筛选高质量 alpha，并打印成表格：

```bash
python run_workflow.py select --config config.json
```

这个命令会输出 `#`、`Sharpe`、`Fit`、`When`、`Alpha Expression` 表格，并写入：

- `results/high_quality_alphas.csv`：完整筛选结果。
- `results/high_quality_alphas.txt`：可读表格结果。

9. 如果报告里有不错的候选，再运行二阶和三阶扩展。它们同样每次最多只测 3 个新 alpha：

```bash
python run_workflow.py second --config config.json
python run_workflow.py third --config config.json
```

10. 对高换手但表现不错的 alpha，用更高 decay 重新测试：

```bash
python run_workflow.py retest-decay --config config.json
```

11. 检查最终候选，并把通过检查的 alpha 在 Brain 上标注出来：

```bash
python run_workflow.py submit-check --config config.json
```

每次完成的回测都会写入 `results/simulation_results.csv`。后续运行默认会跳过已经测过的表达式，所以工作流会基于历史反馈继续推进，而不是重复做同样的回测。

## 常用命令

```bash
python run_workflow.py first --config config.json        # 生成并回测一阶 alpha
python run_workflow.py first-loop --config config.json   # 持续跑一阶 alpha，直到 Ctrl+C 停止
python run_workflow.py status --config config.json       # 查看本地断点/进度状态
python run_workflow.py report --config config.json       # 汇总本地回测反馈
python run_workflow.py select --config config.json       # 打印/写入 fitness>1.3 且 sharpe>1.6 的 alpha
python run_workflow.py second --config config.json       # 对候选 alpha 做 group 二阶扩展
python run_workflow.py third --config config.json        # 对候选 alpha 做 trade_when 三阶扩展
python run_workflow.py retest-decay --config config.json # 用更高 decay 复测高换手 alpha
python run_workflow.py submit-check --config config.json # 检查最终候选
```

## AI Agent 工作流

先配置 DeepSeek API Key：

```bash
export DEEPSEEK_API_KEY="你的 deepseek api key"
```

也可以写入 `config.json`：

```json
{
  "ai_api_key": "你的 deepseek api key",
  "ai_model": "deepseek-chat"
}
```

最小 AI 闭环：

```bash
python run_workflow.py crawl-fields --config config.json
python run_workflow.py propose --config config.json
python run_workflow.py enqueue --config config.json
python run_workflow.py backtest-loop --config config.json
python run_workflow.py review --config config.json
python run_workflow.py improve --config config.json
python run_workflow.py enqueue --config config.json
python run_workflow.py backtest-loop --config config.json
```

命令含义：

- `crawl-fields`：拉取字段，写入 `dataset_catalog/fields_for_ai.jsonl`。
- `propose`：调用 DeepSeek 生成带假设的 FASTEXPR 候选，写入 `ideas/alpha_ideas.jsonl`。
- `enqueue`：对候选表达式去重，加入 `state/backtest_queue.jsonl`。
- `backtest-loop`：从队列中每轮最多回测 3 个，支持 Ctrl+C 停止和续跑。
- `review`：调用 DeepSeek 复盘近期回测反馈，写入 `ideas/ai_review.jsonl`。
- `improve`：把复盘建议里的改进表达式写入 `ideas/improved_ideas.jsonl`。

`ideas/`、`state/`、`results/`、`dataset_catalog/` 都是本地生成数据，已被 Git 忽略。

高质量 alpha 的筛选阈值可以在 `config.json` 里改：

```json
{
  "max_alphas_per_run": 3,
  "simulation_mode": "single",
  "alpha_shuffle": false,
  "loop_sleep_seconds": 6,
  "error_sleep_seconds": 6,
  "loop_max_batches": null,
  "select_min_sharpe": 1.6,
  "select_min_fitness": 1.3,
  "select_top_n": 50,
  "select_expr_width": 96
}
```

## 数据字段爬取工具

当你想查看每个 Brain dataset 里面具体有哪些数据字段，再决定策略方向时，使用 `crawl_datasets.py`。

爬取某个区域和股票池下的全部数据集：

```bash
python crawl_datasets.py --region USA --universe TOP3000 --delay 1
```

只爬取一个或几个指定数据集：

```bash
python crawl_datasets.py --region USA --universe TOP3000 --dataset analyst4 --dataset news12
```

按 dataset 页面名称或关键词爬取 Fields 表：

```bash
python crawl_datasets.py --region USA --universe TOP3000 --dataset-name "Company Fundamental"
```

先用前几个数据集测试：

```bash
python crawl_datasets.py --region USA --universe TOP3000 --limit-datasets 5
```

输出会保存在 `dataset_catalog/`：

- `field_dictionary.csv`：最主要的字段总表，包含 dataset id、field id、字段类型、字段名称和字段描述。
- 主列会对应 Brain 页面里的 Fields 表：`field`、`description`、`type`、`coverage`、`date_coverage`、`alphas`。
- `fields_for_ai.jsonl`：一行一个字段，包含 dataset 元信息和字段上下文，适合直接喂给 AI 做思路分析。
- `fields_by_dataset.txt`：按 dataset 分组的可读字段索引。
- `datafields_raw_all.csv`：API 返回的原始字段总表。
- `datasets.csv`：dataset 索引，只用于确认扫描了哪些 dataset。
- `by_dataset/*.csv`：每个 dataset 单独的原始字段表。

脚本默认支持断点续爬。如果某个 dataset 的 CSV 已经存在，就会跳过它。使用 `--no-resume` 可以强制重新爬取。默认策略偏温和：分页请求之间会等待并加随机抖动，遇到 429 会遵守 `Retry-After`，并且会复用第一页响应，避免重复请求 offset 0。想更慢一点可以这样：

```bash
python crawl_datasets.py --region USA --universe TOP3000 --page-delay 3 --jitter 2 --pause-between-datasets 8
```

## 回测反馈与 AI 分析

每次 simulation 完成后会自动写入：

- `results/simulation_results.csv`：表格格式，方便筛选，也用于以后跳过重复表达式。
- `results/simulation_feedback.jsonl`：一行一个回测反馈，包含分层标签、问题类型、建议动作、operator、字段、指标和表达式。

执行报告命令：

```bash
python run_workflow.py report --config config.json
```

还会生成：

- `results/feedback_for_ai.jsonl`：重新汇总后的 AI 输入文件。
- `results/feedback_summary.json`：诊断摘要，包含问题计数、operator/field 计数、阈值和候选 alpha。
- `results/candidate_alphas.csv`：通过阈值筛选后的候选表。

## 凭据配置

代码会优先读取环境变量：

```bash
export WQB_USERNAME="your_username"
export WQB_PASSWORD="your_password"
```

如果没有设置环境变量，就会读取项目根目录下的 `credentials.txt`：

```json
{"username": "your_username", "password": "your_password"}
```

## 基础工作流

打开 `examples/alpha_machine.ipynb`，或者在 Python 会话里运行同样的代码。

```python
from machine_lib import *

s = login()
```

先选择市场、股票池、数据集和中性化方式：

```python
region = "USA"
universe = "TOP3000"
dataset_id = "analyst4"
neutralization = "SUBINDUSTRY"
```

加载并预处理数据字段：

```python
df = get_datafields(
    s,
    dataset_id=dataset_id,
    region=region,
    universe=universe,
    delay=1,
)

fields = process_datafields(df, "matrix")
```

生成一阶 alpha：

```python
first_order = first_order_factory(fields, ts_ops)
fo_alpha_list = [(alpha, 6) for alpha in first_order]
fo_alpha_list = prepare_alpha_list(fo_alpha_list, max_count=100, shuffle=True)
```

运行模拟回测：

```python
fo_pools = load_task_pool(fo_alpha_list, 10, 3)
multi_simulate(fo_pools, neutralization, region, universe, 0, mode="auto")
```

`mode="auto"` 会检查你的账号是否有 multi-simulation 权限。如果没有，就自动降级为单 alpha 模拟，并带有重试处理。

每个模拟完成后，代码会打印一行可读的结果：

```text
Result 0.0: id=... sharpe= 1.523 fitness= 1.114 turnover= 0.271 margin= 0.0042 decay=6
  expr: ts_rank(...)
```

同一条结果也会写入 `results/simulation_results.csv`，包括 alpha ID、Sharpe、Fitness、Turnover、Margin、Decay、日期、市场、股票池、中性化方式、状态和表达式。`results/` 目录已经被 Git 忽略。

## 筛选结果

使用 `get_alphas()` 获取某个日期区间内表现较好的 alpha。你可以传 `MM-DD` 短日期，也可以传完整的 `YYYY-MM-DD` 日期。

```python
fo_tracker = get_alphas("05-05", "05-06", 1.2, 1, "USA", 100, "track")
```

参数说明：

- `start_date`, `end_date`：日期窗口。结束日期不包含在内。
- `sharpe_th`：最低 Sharpe。
- `fitness_th`：最低 Fitness。
- `region`：Brain 市场区域。
- `alpha_num`：最多扫描多少条记录。
- `usage`：研究阶段用 `"track"`，最终提交候选用 `"submit"`。
- `year`：当使用 `MM-DD` 日期时可以指定年份，例如 `year=2026`。

`usage="track"` 会同时搜索强负 Sharpe 的 alpha，并把表达式取反。`usage="submit"` 只搜索正向候选。

## 二阶扩展

二阶 alpha 会对表现较好的一阶 alpha 套用 group 操作：

```python
fo_layer = prune(fo_tracker, "analyst", 5)

group_ops = ["group_neutralize", "group_rank", "group_zscore"]
so_alpha_list = []

for expr, decay in fo_layer:
    for alpha in get_group_second_order_factory([expr], group_ops, region, core_groups_only=True, group_limit=8):
        so_alpha_list.append((alpha, decay))

so_alpha_list = prepare_alpha_list(so_alpha_list, max_count=200, shuffle=True)
so_pools = load_task_pool(so_alpha_list, 10, 3)
multi_simulate(so_pools, neutralization, region, universe, 0)
```

`prune()` 的 prefix 要和你的数据字段前缀匹配。如果你使用的是 `analyst4`，不要保留旧的 `mdl26` 之类的 prefix。

使用 `core_groups_only=True` 和 `group_limit=...` 可以控制 group 搜索空间，避免二阶 alpha 数量过大。

## 三阶扩展

三阶 alpha 会用 `trade_when()` 事件条件包裹当前表达式：

```python
so_tracker = get_alphas("05-05", "05-06", 1.4, 1, region, 200, "track")
so_layer = prune(so_tracker, "analyst", 5)

th_alpha_list = []
for expr, decay in so_layer:
    for alpha in trade_when_factory("trade_when", expr, region, include_region_events=True, max_events=20):
        th_alpha_list.append((alpha, decay))

th_alpha_list = prepare_alpha_list(th_alpha_list, max_count=200, shuffle=True)
th_pools = load_task_pool(th_alpha_list, 10, 3)
multi_simulate(th_pools, neutralization, region, universe, 0)
```

`include_region_events=True` 会在可用时加入对应地区的事件触发条件。使用 `max_events` 可以控制搜索规模，避免三阶 alpha 数量爆炸。

## 提交前检查

查找更强的最终候选：

```python
th_tracker = get_alphas("05-05", "05-06", 1.58, 1, region, 200, "submit")
stone_bag = [alpha[0] for alpha in th_tracker]

gold_bag = []
check_submission(stone_bag, gold_bag, 0)
view_alphas(gold_bag)
```

`view_alphas()` 会按 Sharpe 排序打印候选，并显示 `PROD_CORRELATION`。

默认情况下，`check_submission()` 会把通过检查的 alpha 在 Brain 上标成绿色，并添加 `submittable` 和 `wq-assistant` 标签。你也可以自定义：

```python
check_submission(
    stone_bag,
    gold_bag,
    0,
    mark_passed=True,
    mark_color="GREEN",
    mark_tags=["submittable", "wq-assistant", "review"],
)
```

## 关键可调参数

- `dataset_id`：原始信号来源，例如 `analyst4` 或 `news12`。
- `region`：市场区域，例如 `USA`、`EUR`、`CHN`、`JPN`。
- `universe`：股票池，例如 `TOP3000`。
- `neutralization`：常见值包括 `MARKET`、`SECTOR`、`INDUSTRY`、`SUBINDUSTRY`。
- `init_decay`：生成 alpha 时绑定的初始 decay。数值越大通常换手越低。
- `ts_ops`：一阶生成时使用的时间序列算子。
- `ts_factory()` 窗口：当前是 `[5, 22, 66, 120, 240]`。
- `group_ops`：二阶 group 变换方式。
- `trade_when_factory()` 事件：三阶开仓和平仓逻辑。
- `max_count`：每一层实际提交模拟的数量上限。
- `group_limit`：每个 group 算子最多使用多少个分组定义。
- `core_groups_only`：只使用市场、行业、市值、波动率、流动性等核心分组。
- `results_csv`：本地 CSV 日志路径，用于保存回测结果和跳过已跑表达式。

## 实用建议

先小规模运行。建议先跑 50 到 200 个 alpha，观察结果质量，再扩大规模。

越往后层，筛选阈值可以越严格：

```python
first_order_threshold = 1.2
second_order_threshold = 1.4
submit_threshold = 1.58
```

如果你的账号容易被限流，建议先保持 `load_task_pool(..., 10, 3)` 这个保守配置。只有在模拟稳定时再调大第二个参数。

最终提交前，始终在 Brain 网页上再次检查候选 alpha。
