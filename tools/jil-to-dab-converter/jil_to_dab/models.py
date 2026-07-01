"""
Data models for AutoSys JIL jobs and Databricks Asset Bundle (DAB) configurations.

JIL models capture the parsed representation of AutoSys job definitions.
DAB models represent the target Databricks Asset Bundle YAML structure.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# =============================================================================
# AutoSys JIL Models
# =============================================================================

class JilJobType(Enum):
    """Supported AutoSys job types."""
    CMD = "CMD"       # Command job — executes a shell command or script
    BOX = "BOX"       # Box job — container that groups child jobs
    FW = "FW"         # File watcher — monitors for file arrival
    FT = "FT"         # File transfer — moves files between machines


@dataclass
class JilCondition:
    """
    Represents an AutoSys job dependency condition.
    Examples: s(job_a) — success, f(job_b) — failure, d(job_c) — done.
    """
    condition_type: str   # 's' (success), 'f' (failure), 'd' (done), 'n' (notrunning)
    job_name: str         # Name of the dependent job


@dataclass
class JilJob:
    """
    Represents a single parsed AutoSys JIL job definition.
    All optional fields default to None/empty to handle partial JIL definitions.
    """
    # Core identifiers
    job_name: str
    job_type: JilJobType

    # Execution details
    machine: Optional[str] = None
    owner: Optional[str] = None
    command: Optional[str] = None
    description: Optional[str] = None
    profile: Optional[str] = None

    # Box membership — the parent box this job belongs to
    box_name: Optional[str] = None

    # Scheduling attributes
    date_conditions: bool = False
    days_of_week: Optional[str] = None          # e.g., "mo,tu,we,th,fr"
    start_times: Optional[str] = None           # e.g., "08:00"
    start_mins: Optional[str] = None            # e.g., "0,15,30,45"
    run_calendar: Optional[str] = None          # Named calendar reference
    exclude_calendar: Optional[str] = None      # Named exclusion calendar
    timezone: Optional[str] = None              # e.g., "US/Eastern"

    # Dependency conditions — parsed from the 'condition:' attribute
    conditions: list[JilCondition] = field(default_factory=list)

    # File watcher attributes
    watch_file: Optional[str] = None
    watch_interval: Optional[int] = None        # Polling interval in seconds
    watch_file_min_size: Optional[int] = None   # Minimum file size in bytes

    # File transfer attributes
    src_machine: Optional[str] = None
    dest_machine: Optional[str] = None
    src_file: Optional[str] = None
    dest_file: Optional[str] = None

    # Alerting and retry
    alarm_if_fail: bool = False
    max_run_alarm: Optional[int] = None         # Max runtime in minutes before alarm
    n_retrys: int = 0                           # Number of automatic retries
    term_run_time: Optional[int] = None         # Max runtime before termination (minutes)

    # Output redirection
    std_out_file: Optional[str] = None
    std_err_file: Optional[str] = None

    # Permission and priority
    permission: Optional[str] = None
    priority: Optional[int] = None

    # Auto-delete flag — some JIL definitions use delete_job instead of insert_job
    is_delete: bool = False


# =============================================================================
# Databricks Asset Bundle (DAB) Models
# =============================================================================

@dataclass
class DabTaskDependency:
    """Represents a task dependency within a Databricks multi-task job."""
    task_key: str


@dataclass
class DabNotebookTask:
    """Databricks notebook task configuration."""
    notebook_path: str


@dataclass
class DabPythonWheelTask:
    """Databricks Python wheel task configuration."""
    package_name: str
    entry_point: str
    parameters: list[str] = field(default_factory=list)


@dataclass
class DabSparkPythonTask:
    """Databricks Spark Python (PySpark script) task configuration."""
    python_file: str
    parameters: list[str] = field(default_factory=list)


@dataclass
class DabShellTask:
    """
    Databricks shell command task — used for migrated command jobs.
    Maps AutoSys CMD jobs that run shell scripts/commands.
    """
    command: str


@dataclass
class DabFileArrivalTrigger:
    """
    Databricks file arrival trigger — replaces AutoSys file watcher jobs.
    Monitors a cloud storage path for new files.
    """
    url: str                                     # Cloud storage URL (e.g., s3://, dbfs:/)
    min_time_between_triggers_seconds: int = 60  # Minimum interval between triggers
    wait_after_last_change_seconds: int = 30     # Wait time after last file change


@dataclass
class DabSchedule:
    """Cron-based schedule for a Databricks job."""
    quartz_cron_expression: str
    timezone_id: str = "UTC"
    pause_status: str = "UNPAUSED"


@dataclass
class DabEmailNotifications:
    """Email notification settings for a Databricks job."""
    on_failure: list[str] = field(default_factory=list)
    on_success: list[str] = field(default_factory=list)
    on_start: list[str] = field(default_factory=list)


@dataclass
class DabTask:
    """
    A single task within a Databricks multi-task job.
    Each task maps to one AutoSys job (or a sub-step of a box job).
    """
    task_key: str
    description: Optional[str] = None

    # Exactly one of these task types should be set
    notebook_task: Optional[DabNotebookTask] = None
    spark_python_task: Optional[DabSparkPythonTask] = None
    python_wheel_task: Optional[DabPythonWheelTask] = None
    shell_task: Optional[DabShellTask] = None

    # Task dependencies — other tasks that must complete first
    depends_on: list[DabTaskDependency] = field(default_factory=list)

    # Retry policy — maps from AutoSys n_retrys
    max_retries: int = 0
    min_retry_interval_millis: int = 0

    # Timeout — maps from AutoSys term_run_time
    timeout_seconds: int = 0


@dataclass
class DabJob:
    """
    A complete Databricks job definition.
    Box jobs become a single DabJob with multiple tasks.
    Standalone CMD jobs become a DabJob with one task.
    """
    name: str
    tasks: list[DabTask] = field(default_factory=list)
    schedule: Optional[DabSchedule] = None
    email_notifications: Optional[DabEmailNotifications] = None
    max_concurrent_runs: int = 1
    timeout_seconds: int = 0

    # Metadata — tracks the source AutoSys job for traceability
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class DabBundle:
    """
    Top-level Databricks Asset Bundle configuration.
    Contains all converted jobs and bundle metadata.
    """
    name: str
    jobs: dict[str, DabJob] = field(default_factory=dict)

    # File arrival triggers — generated from file watcher jobs
    triggers: dict[str, DabFileArrivalTrigger] = field(default_factory=dict)
