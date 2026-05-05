# wq-assistant

`wq-assistant` is a small WorldQuant Brain alpha mining workflow. It generates FASTEXPR alpha expressions, submits them to Brain simulations, filters promising results, then expands them into second-order and third-order variants.

The project is intended for research automation. It does not auto-submit alphas to production; the final submission is still done manually on the Brain website.

## Files

- `machine_lib.py`: login, data-field loading, alpha generation, simulation submission, result filtering, and submission checks.
- `Alpha Machine.ipynb`: notebook workflow for running the mining process interactively.
- `credentials.txt`: local Brain credentials. This file is ignored by Git.

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

Open `Alpha Machine.ipynb` or run the same code in a Python session.

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
    for alpha in get_group_second_order_factory([expr], group_ops, region):
        so_alpha_list.append((alpha, decay))

so_alpha_list = prepare_alpha_list(so_alpha_list, max_count=200, shuffle=True)
so_pools = load_task_pool(so_alpha_list, 10, 3)
multi_simulate(so_pools, neutralization, region, universe, 0)
```

Choose the `prune()` prefix to match your dataset field prefix. If you use `analyst4`, do not leave an old prefix like `mdl26`.

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
- `Alpha Machine.ipynb`：交互式 notebook 工作流，用来一步步运行挖掘流程。
- `credentials.txt`：本地 Brain 账号凭据。这个文件已经被 Git 忽略，不会上传。

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

打开 `Alpha Machine.ipynb`，或者在 Python 会话里运行同样的代码。

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
    for alpha in get_group_second_order_factory([expr], group_ops, region):
        so_alpha_list.append((alpha, decay))

so_alpha_list = prepare_alpha_list(so_alpha_list, max_count=200, shuffle=True)
so_pools = load_task_pool(so_alpha_list, 10, 3)
multi_simulate(so_pools, neutralization, region, universe, 0)
```

`prune()` 的 prefix 要和你的数据字段前缀匹配。如果你使用的是 `analyst4`，不要保留旧的 `mdl26` 之类的 prefix。

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
