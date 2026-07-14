# JIL-to-DAB Converter

Automated tool to convert AutoSys JIL (Job Information Language) job definitions into Databricks Asset Bundle (DAB) YAML configurations.

## Features

- **Parses all major AutoSys job types**: CMD, BOX, FW (file watcher), FT (file transfer)
- **Box-to-multi-task mapping**: AutoSys BOX jobs become Databricks multi-task jobs with proper dependency chains
- **Schedule conversion**: AutoSys `days_of_week` + `start_times` → Quartz cron expressions
- **File watcher migration**: FW jobs → Databricks file arrival triggers
- **SQL detection**: SQL script commands auto-map to Databricks notebook tasks
- **Retry & timeout mapping**: AutoSys `n_retrys` / `term_run_time` → DAB retry/timeout policies
- **Traceability tags**: Each generated DAB job is tagged with its AutoSys source job name

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Convert a JIL file to DAB YAML
python -m jil_to_dab.cli your_jobs.jil -o databricks.yml --verbose

# Dry run (print to stdout without writing)
python -m jil_to_dab.cli your_jobs.jil --dry-run

# Custom bundle name
python -m jil_to_dab.cli your_jobs.jil -o databricks.yml --bundle-name my_pipeline
```

## Conversion Mapping

| AutoSys Concept | Databricks DAB Equivalent |
|---|---|
| BOX job + children | Multi-task Job with `depends_on` |
| CMD job (shell script) | `shell_command_task` |
| CMD job (SQL script) | `notebook_task` |
| FW (file watcher) | `file_arrival` trigger + processing job |
| FT (file transfer) | `shell_command_task` with `dbutils.fs.cp` |
| `condition: s(job_a)` | `depends_on: [{task_key: job_a}]` |
| `days_of_week` + `start_times` | `schedule.quartz_cron_expression` |
| `alarm_if_fail` + `owner` | `email_notifications.on_failure` |
| `n_retrys` | `max_retries` |
| `term_run_time` | `timeout_seconds` |
| `profile` | Prepended `source <profile> &&` in shell command |

## Project Structure

```
jil-to-dab-converter/
├── jil_to_dab/
│   ├── __init__.py       # Package init
│   ├── models.py         # Data models for JIL and DAB
│   ├── parser.py         # JIL file parser
│   ├── converter.py      # JIL → DAB conversion logic
│   ├── generator.py      # DAB YAML output generator
│   └── cli.py            # Command-line interface
├── samples/
│   ├── sample_jobs.jil           # Example AutoSys JIL file
│   └── expected_output/
│       └── databricks.yml        # Generated DAB output from sample
├── tests/
│   └── test_converter.py         # Unit and integration tests
├── requirements.txt
└── README.md
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Post-Conversion Steps

1. **Review generated YAML** — verify notebook paths, cluster configurations, and schedules
2. **Create Databricks notebooks** — for SQL-mapped tasks, implement the Spark SQL logic
3. **Configure cloud storage** — update `dbfs:/mnt/data` paths to your actual mount points
4. **Add cluster configuration** — specify `job_clusters` or `existing_cluster_id` in the YAML
5. **Validate** — run `databricks bundle validate` against your workspace
6. **Deploy** — run `databricks bundle deploy --target dev` for initial testing
