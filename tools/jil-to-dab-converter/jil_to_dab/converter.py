"""
Converter — transforms parsed JilJob objects into Databricks Asset Bundle (DAB) models.

Conversion strategy:
  - BOX jobs become a single DabJob containing multiple DabTasks (one per child CMD job)
  - Standalone CMD jobs (not inside a box) become individual DabJobs with one task
  - File watcher (FW) jobs become DabJobs with file_arrival triggers
  - File transfer (FT) jobs become DabJobs with shell tasks running dbutils/cloud CLI copy commands
  - AutoSys conditions (s/f/d) map to DAB task depends_on relationships
  - AutoSys schedules (days_of_week + start_times) map to Quartz cron expressions
  - AutoSys retry/alarm settings map to DAB retry/timeout policies
"""

import re

from .models import (
    DabBundle,
    DabEmailNotifications,
    DabFileArrivalTrigger,
    DabJob,
    DabNotebookTask,
    DabSchedule,
    DabShellTask,
    DabTask,
    DabTaskDependency,
    JilJob,
    JilJobType,
)

# Map AutoSys day abbreviations to Quartz cron day names
_DAY_MAP = {
    "su": "SUN", "mo": "MON", "tu": "TUE", "we": "WED",
    "th": "THU", "fr": "FRI", "sa": "SAT",
    "all": "MON-SUN",
}

# Default cloud storage prefix for migrated file watcher paths
_DEFAULT_CLOUD_STORAGE_PREFIX = "dbfs:/mnt/data"

# Default notebook base path in Databricks workspace
_DEFAULT_NOTEBOOK_BASE = "/Workspace/migrated_jobs"


def _sanitize_key(name: str) -> str:
    """
    Convert an AutoSys job name to a valid DAB task/job key.
    Replaces non-alphanumeric characters with underscores and lowercases.
    """
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()


def _build_quartz_cron(job: JilJob) -> str | None:
    """
    Convert AutoSys scheduling attributes to a Quartz cron expression.

    Quartz format: seconds minutes hours day-of-month month day-of-week [year]
    Example: "0 0 8 ? * MON-FRI" = 8:00 AM on weekdays

    Args:
        job: JilJob with scheduling attributes (start_times, days_of_week, start_mins)

    Returns:
        Quartz cron expression string, or None if insufficient scheduling info
    """
    if not job.date_conditions:
        return None

    # Parse hours and minutes from start_times (format: "HH:MM" or "HH:MM,HH:MM")
    hours = "0"
    minutes = "0"
    if job.start_times:
        # Handle multiple start times — take the first one for the primary schedule
        time_parts = job.start_times.split(",")[0].strip().split(":")
        if len(time_parts) >= 2:
            hours = time_parts[0].strip()
            minutes = time_parts[1].strip()
        elif len(time_parts) == 1:
            hours = time_parts[0].strip()

    # Override minutes if start_mins is specified (sub-hour scheduling)
    if job.start_mins:
        minutes = job.start_mins

    # Parse days of week; default to '*' (every day) so the cron stays valid when
    # no weekday list is present — Quartz requires exactly one of day-of-month /
    # day-of-week to be '?', not both.
    days = "*"
    if job.days_of_week:
        day_list = [d.strip().lower() for d in job.days_of_week.split(",")]
        mapped_days = [_DAY_MAP.get(d, d.upper()) for d in day_list]
        days = ",".join(mapped_days)

    # Build Quartz cron: seconds minutes hours day-of-month month day-of-week
    # Use '?' for day-of-month when day-of-week is specified (Quartz requirement)
    return f"0 {minutes} {hours} ? * {days}"


def _convert_cmd_to_task(job: JilJob, all_jobs: dict[str, JilJob]) -> DabTask:
    """
    Convert an AutoSys CMD job to a Databricks task.

    If the command looks like a SQL script, it maps to a notebook task.
    Otherwise, it maps to a shell command task.

    Args:
        job: The CMD JilJob to convert
        all_jobs: All parsed jobs (for resolving dependencies)

    Returns:
        A DabTask representing the converted job
    """
    task_key = _sanitize_key(job.job_name)

    # Determine task type based on the command content
    shell_task = None
    notebook_task = None

    if job.command:
        command_lower = job.command.lower()
        # SQL scripts get converted to notebook tasks for Databricks Spark SQL execution
        if command_lower.endswith(".sql") or "sqlplus" in command_lower or "bteq" in command_lower:
            # Map SQL scripts to a Databricks notebook that runs Spark SQL
            notebook_path = f"{_DEFAULT_NOTEBOOK_BASE}/{_sanitize_key(job.job_name)}"
            notebook_task = DabNotebookTask(notebook_path=notebook_path)
        else:
            # Shell scripts and generic commands map to shell tasks
            # Prepend profile sourcing if specified in the original JIL
            command = job.command
            if job.profile:
                command = f"source {job.profile} && {command}"
            shell_task = DabShellTask(command=command)
    else:
        # No command specified — create a placeholder notebook task
        notebook_path = f"{_DEFAULT_NOTEBOOK_BASE}/{_sanitize_key(job.job_name)}"
        notebook_task = DabNotebookTask(notebook_path=notebook_path)

    # Build task dependency list from AutoSys conditions
    depends_on = []
    for cond in job.conditions:
        # Only map success conditions to strict dependencies; failure/done/notrunning
        # have no equivalent depends_on semantics in Databricks and are skipped.
        if cond.condition_type != "s":
            continue
        dep_key = _sanitize_key(cond.job_name)
        # Skip self-referencing box conditions (child depending on its own box start)
        if dep_key != task_key:
            depends_on.append(DabTaskDependency(task_key=dep_key))

    # Map retry and timeout settings
    max_retries = job.n_retrys
    timeout_seconds = (job.term_run_time * 60) if job.term_run_time else 0

    return DabTask(
        task_key=task_key,
        description=job.description or f"Migrated from AutoSys job: {job.job_name}",
        notebook_task=notebook_task,
        shell_task=shell_task,
        depends_on=depends_on,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
    )


def _convert_fw_to_trigger(job: JilJob) -> DabFileArrivalTrigger:
    """
    Convert an AutoSys file watcher job to a Databricks file arrival trigger.

    Maps the watched file path to a cloud storage URL and the watch_interval
    to the trigger polling configuration.

    Args:
        job: The FW JilJob to convert

    Returns:
        A DabFileArrivalTrigger configuration
    """
    # Map the watched file path to a cloud storage URL
    # Original on-prem paths need manual remapping; we provide a sensible default
    watched_path = job.watch_file or "/unknown/path"
    cloud_url = f"{_DEFAULT_CLOUD_STORAGE_PREFIX}{watched_path}"

    interval = job.watch_interval or 60

    return DabFileArrivalTrigger(
        url=cloud_url,
        min_time_between_triggers_seconds=interval,
        wait_after_last_change_seconds=min(interval, 30),
    )


def _convert_ft_to_task(job: JilJob) -> DabTask:
    """
    Convert an AutoSys file transfer job to a Databricks shell task.

    File transfers are mapped to dbutils.fs.cp commands or cloud CLI equivalents.

    Args:
        job: The FT JilJob to convert

    Returns:
        A DabTask with a shell command for file transfer
    """
    src = job.src_file or "/unknown/source"
    dest = job.dest_file or "/unknown/destination"
    # Generate a dbutils-based copy command as the migration target
    command = (
        f"# Migrated from AutoSys FT job: {job.job_name}\n"
        f"# Original: {job.src_machine or 'unknown'}:{src} -> {job.dest_machine or 'unknown'}:{dest}\n"
        f"dbutils.fs.cp('{_DEFAULT_CLOUD_STORAGE_PREFIX}{src}', '{_DEFAULT_CLOUD_STORAGE_PREFIX}{dest}')"
    )

    return DabTask(
        task_key=_sanitize_key(job.job_name),
        description=job.description or f"File transfer migrated from AutoSys job: {job.job_name}",
        shell_task=DabShellTask(command=command),
        max_retries=job.n_retrys,
    )


def convert_jobs(jobs: list[JilJob], bundle_name: str = "migrated_autosys_jobs") -> DabBundle:
    """
    Convert a list of parsed AutoSys JilJob objects into a DabBundle.

    Conversion logic:
      1. Index all jobs by name for dependency resolution
      2. Group child jobs under their parent BOX jobs
      3. Convert BOX jobs → multi-task DabJobs
      4. Convert standalone CMD jobs → single-task DabJobs
      5. Convert FW jobs → DabJobs with file arrival triggers
      6. Convert FT jobs → DabJobs with shell tasks for file copy
      7. Apply scheduling, notifications, and retry policies

    Args:
        jobs: List of JilJob objects from the parser
        bundle_name: Name for the output DAB bundle

    Returns:
        A fully populated DabBundle ready for YAML generation
    """
    bundle = DabBundle(name=bundle_name)

    # Index all jobs by name for lookups
    all_jobs: dict[str, JilJob] = {j.job_name: j for j in jobs}

    # Skip delete directives — they don't produce DAB output
    active_jobs = [j for j in jobs if not j.is_delete]

    # Group child jobs by their parent box name
    box_children: dict[str, list[JilJob]] = {}
    for job in active_jobs:
        if job.box_name:
            box_children.setdefault(job.box_name, []).append(job)

    # Track which jobs have been processed (to avoid duplicates)
    processed: set[str] = set()

    # --- Pass 1: Convert BOX jobs and their children ---
    for job in active_jobs:
        if job.job_type != JilJobType.BOX:
            continue

        job_key = _sanitize_key(job.job_name)
        children = box_children.get(job.job_name, [])

        # Build tasks for each child job in the box
        tasks: list[DabTask] = []
        for child in children:
            if child.job_type == JilJobType.CMD:
                tasks.append(_convert_cmd_to_task(child, all_jobs))
            elif child.job_type == JilJobType.FT:
                tasks.append(_convert_ft_to_task(child))
            elif child.job_type == JilJobType.FW:
                # File watcher inside a box — convert to a polling shell task
                task = DabTask(
                    task_key=_sanitize_key(child.job_name),
                    description=f"File watcher migrated from AutoSys: {child.job_name}",
                    shell_task=DabShellTask(
                        command=f"# TODO: Replace with Auto Loader or cloud event trigger\n"
                                f"# Original watched file: {child.watch_file or 'unknown'}"
                    ),
                )
                tasks.append(task)
            processed.add(child.job_name)

        # Build schedule from the box job's timing attributes
        schedule = None
        cron_expr = _build_quartz_cron(job)
        if cron_expr:
            schedule = DabSchedule(
                quartz_cron_expression=cron_expr,
                timezone_id=job.timezone or "UTC",
            )

        # Build notification settings
        notifications = None
        if job.alarm_if_fail and job.owner:
            notifications = DabEmailNotifications(on_failure=[job.owner])

        # Create the DAB job for this box
        dab_job = DabJob(
            name=job.description or job.job_name,
            tasks=tasks,
            schedule=schedule,
            email_notifications=notifications,
            max_concurrent_runs=1,
            timeout_seconds=(job.term_run_time * 60) if job.term_run_time else 0,
            tags={"autosys_source": job.job_name, "migration_type": "box_job"},
        )
        bundle.jobs[job_key] = dab_job
        processed.add(job.job_name)

    # --- Pass 2: Convert standalone jobs (not in any box) ---
    for job in active_jobs:
        if job.job_name in processed:
            continue

        job_key = _sanitize_key(job.job_name)

        if job.job_type == JilJobType.CMD:
            task = _convert_cmd_to_task(job, all_jobs)

            schedule = None
            cron_expr = _build_quartz_cron(job)
            if cron_expr:
                schedule = DabSchedule(
                    quartz_cron_expression=cron_expr,
                    timezone_id=job.timezone or "UTC",
                )

            notifications = None
            if job.alarm_if_fail and job.owner:
                notifications = DabEmailNotifications(on_failure=[job.owner])

            dab_job = DabJob(
                name=job.description or job.job_name,
                tasks=[task],
                schedule=schedule,
                email_notifications=notifications,
                max_concurrent_runs=1,
                timeout_seconds=(job.term_run_time * 60) if job.term_run_time else 0,
                tags={"autosys_source": job.job_name, "migration_type": "command_job"},
            )
            bundle.jobs[job_key] = dab_job

        elif job.job_type == JilJobType.FW:
            # File watcher — create a trigger + a placeholder processing job
            trigger = _convert_fw_to_trigger(job)
            bundle.triggers[job_key] = trigger

            # Create a companion job that runs when the file arrives
            task = DabTask(
                task_key=f"{job_key}_process",
                description=f"Processing task triggered by file watcher: {job.job_name}",
                notebook_task=DabNotebookTask(
                    notebook_path=f"{_DEFAULT_NOTEBOOK_BASE}/{job_key}_process"
                ),
            )
            dab_job = DabJob(
                name=f"File arrival handler for {job.job_name}",
                tasks=[task],
                tags={"autosys_source": job.job_name, "migration_type": "file_watcher"},
            )
            bundle.jobs[job_key] = dab_job

        elif job.job_type == JilJobType.FT:
            task = _convert_ft_to_task(job)

            schedule = None
            cron_expr = _build_quartz_cron(job)
            if cron_expr:
                schedule = DabSchedule(
                    quartz_cron_expression=cron_expr,
                    timezone_id=job.timezone or "UTC",
                )

            dab_job = DabJob(
                name=job.description or job.job_name,
                tasks=[task],
                schedule=schedule,
                tags={"autosys_source": job.job_name, "migration_type": "file_transfer"},
            )
            bundle.jobs[job_key] = dab_job

        processed.add(job.job_name)

    return bundle
