# Project Structure

This repo keeps source code and local runtime data separate.

## Source Files

- `run_workflow.py`: main CLI entrypoint.
- `machine_lib.py`: WorldQuant Brain login, alpha generation, simulation, result logging, and filtering helpers.
- `crawl_datasets.py`: dataset and data-field crawler.
- `wq_assistant/`: AI workflow modules.
  - `ai_client.py`: DeepSeek API client.
  - `ai_workflow.py`: AI propose/enqueue/backtest/review/improve workflow.
  - `jsonl_utils.py`: JSONL read/write helpers.
- `config.example.json`: safe default configuration template.
- `requirements.txt`: Python dependencies.

## Documentation

- `README.md`: project overview and commands.
- `docs/使用方法.txt`: quick Chinese usage guide.
- `docs/brain_operators.md`: compact FASTEXPR operator notes used by the AI proposal step.
- `docs/*.pdf`: local reference papers. Check licensing before publishing them.

## What You May Still See In VS Code

The following folders can still appear in the file tree during local use. That is normal:

- `__pycache__/`: Python bytecode cache.
- `.vscode/`: local editor settings.
- `dataset_catalog/`: local crawled fields.
- `results/`: local backtest results.

They are ignored by Git and should not be committed.

## Examples

- `examples/alpha_machine.ipynb`: interactive notebook version of the workflow.
- `examples/test.ipynb`: old experimental notebook; keep only as a reference.

## Local Runtime Data

These folders are ignored by Git and should not be committed:

- `results/`: simulation logs, feedback files, selected alpha tables.
- `dataset_catalog/`: crawled dataset and field catalogs.
- `ideas/`: AI-generated alpha ideas and reviews.
- `state/`: backtest queue and run state.

## Local Secrets And Cache

These are ignored by Git:

- `credentials.txt`
- `config.json`
- `.env`
- `__pycache__/`
- `.vscode/`
