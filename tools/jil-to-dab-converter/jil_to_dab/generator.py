"""
DAB YAML Generator — serializes DabBundle objects into Databricks Asset Bundle YAML files.

Produces a databricks.yml file conforming to the DAB schema:
  bundle:
    name: <bundle_name>
  resources:
    jobs:
      <job_key>:
        name: <display_name>
        tasks: [...]
        schedule: { quartz_cron_expression, timezone_id }
        ...

File arrival triggers are emitted as separate trigger resources.
"""

from pathlib import Path

import yaml

from .models import DabBundle, DabJob, DabTask


def _task_to_dict(task: DabTask) -> dict:
    """
    Convert a DabTask dataclass to a plain dict for YAML serialization.
    Only includes non-empty/non-default fields to keep output clean.

    Args:
        task: DabTask to serialize

    Returns:
        Dictionary representation suitable for YAML dumping
    """
    d: dict = {"task_key": task.task_key}

    # Add description if present
    if task.description:
        d["description"] = task.description

    # Add exactly one task type block
    if task.notebook_task:
        d["notebook_task"] = {"notebook_path": task.notebook_task.notebook_path}
    elif task.spark_python_task:
        spark_dict: dict = {"python_file": task.spark_python_task.python_file}
        if task.spark_python_task.parameters:
            spark_dict["parameters"] = task.spark_python_task.parameters
        d["spark_python_task"] = spark_dict
    elif task.shell_task:
        d["shell_command_task"] = {"command": task.shell_task.command}
    elif task.python_wheel_task:
        wheel_dict: dict = {
            "package_name": task.python_wheel_task.package_name,
            "entry_point": task.python_wheel_task.entry_point,
        }
        if task.python_wheel_task.parameters:
            wheel_dict["parameters"] = task.python_wheel_task.parameters
        d["python_wheel_task"] = wheel_dict

    # Add dependencies if any
    if task.depends_on:
        d["depends_on"] = [{"task_key": dep.task_key} for dep in task.depends_on]

    # Add retry policy if configured
    if task.max_retries > 0:
        d["max_retries"] = task.max_retries
        if task.min_retry_interval_millis > 0:
            d["min_retry_interval_millis"] = task.min_retry_interval_millis

    # Add timeout if configured
    if task.timeout_seconds > 0:
        d["timeout_seconds"] = task.timeout_seconds

    return d


def _job_to_dict(job: DabJob) -> dict:
    """
    Convert a DabJob dataclass to a plain dict for YAML serialization.
    Omits empty/default fields for clean output.

    Args:
        job: DabJob to serialize

    Returns:
        Dictionary representation suitable for YAML dumping
    """
    d: dict = {"name": job.name}

    # Serialize all tasks
    if job.tasks:
        d["tasks"] = [_task_to_dict(t) for t in job.tasks]

    # Add schedule if configured
    if job.schedule:
        d["schedule"] = {
            "quartz_cron_expression": job.schedule.quartz_cron_expression,
            "timezone_id": job.schedule.timezone_id,
            "pause_status": job.schedule.pause_status,
        }

    # Add email notifications if configured
    if job.email_notifications:
        notif: dict = {}
        if job.email_notifications.on_failure:
            notif["on_failure"] = job.email_notifications.on_failure
        if job.email_notifications.on_success:
            notif["on_success"] = job.email_notifications.on_success
        if job.email_notifications.on_start:
            notif["on_start"] = job.email_notifications.on_start
        if notif:
            d["email_notifications"] = notif

    # Add max concurrent runs (default is 1)
    if job.max_concurrent_runs != 1:
        d["max_concurrent_runs"] = job.max_concurrent_runs

    # Add job-level timeout
    if job.timeout_seconds > 0:
        d["timeout_seconds"] = job.timeout_seconds

    # Add tags for migration traceability
    if job.tags:
        d["tags"] = job.tags

    return d


def bundle_to_dict(bundle: DabBundle) -> dict:
    """
    Convert a DabBundle to a complete DAB configuration dictionary.

    Produces the full structure expected by the Databricks CLI:
      bundle:
        name: ...
      resources:
        jobs:
          <key>: { ... }

    Args:
        bundle: DabBundle to serialize

    Returns:
        Complete DAB configuration as a nested dictionary
    """
    # Build the top-level bundle structure
    dab_config: dict = {
        "bundle": {
            "name": bundle.name,
        },
        "resources": {},
    }

    # Add jobs
    if bundle.jobs:
        jobs_dict = {}
        for job_key, job in bundle.jobs.items():
            jobs_dict[job_key] = _job_to_dict(job)
        dab_config["resources"]["jobs"] = jobs_dict

    # Add file arrival triggers as a separate section with TODO guidance
    if bundle.triggers:
        triggers_dict = {}
        for trigger_key, trigger in bundle.triggers.items():
            triggers_dict[trigger_key] = {
                "# NOTE": "File arrival triggers — configure in Databricks job trigger settings",
                "file_arrival": {
                    "url": trigger.url,
                    "min_time_between_triggers_seconds": trigger.min_time_between_triggers_seconds,
                    "wait_after_last_change_seconds": trigger.wait_after_last_change_seconds,
                },
            }
        dab_config["resources"]["triggers"] = triggers_dict

    return dab_config


def generate_yaml(bundle: DabBundle) -> str:
    """
    Generate a DAB YAML string from a DabBundle.

    Args:
        bundle: DabBundle to serialize

    Returns:
        YAML string suitable for writing to databricks.yml
    """
    config = bundle_to_dict(bundle)

    # Add a header comment explaining the generated file
    header = (
        "# =============================================================================\n"
        "# Databricks Asset Bundle (DAB) Configuration\n"
        "# Auto-generated by JIL-to-DAB Converter\n"
        "#\n"
        "# This file was automatically generated from AutoSys JIL job definitions.\n"
        "# Review and customize before deploying to your Databricks workspace.\n"
        "#\n"
        "# Deployment:  databricks bundle deploy --target dev\n"
        "# Validation:  databricks bundle validate\n"
        "# =============================================================================\n\n"
    )

    # Use PyYAML with default_flow_style=False for readable block format
    yaml_content = yaml.dump(
        config,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
        width=120,
    )

    return header + yaml_content


def write_yaml(bundle: DabBundle, output_path: str | Path) -> Path:
    """
    Write a DabBundle as a YAML file to disk.

    Args:
        bundle: DabBundle to serialize
        output_path: Target file path (e.g., "output/databricks.yml")

    Returns:
        Path to the written file
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    yaml_content = generate_yaml(bundle)
    path.write_text(yaml_content, encoding="utf-8")

    return path
