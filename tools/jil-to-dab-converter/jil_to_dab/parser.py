"""
AutoSys JIL Parser — reads JIL text and produces a list of JilJob objects.

JIL (Job Information Language) is a line-oriented format where each job starts
with an 'insert_job' or 'delete_job' directive, followed by attribute lines
in the form:  attribute_name: value

This parser handles:
  - insert_job / delete_job / update_job directives
  - Inline job_type on the insert_job line (e.g., insert_job: x  job_type: CMD)
  - Multi-line and quoted values
  - Condition parsing (s/f/d/n dependency expressions)
  - All major job types: CMD, BOX, FW, FT
"""

import re
from pathlib import Path

from .models import JilCondition, JilJob, JilJobType


# Regex to match the start of a new job definition
# Captures: (insert|delete|update)_job: job_name   [job_type: TYPE]
_JOB_START_RE = re.compile(
    r"^(insert_job|delete_job|update_job)\s*:\s*(\S+)"
    r"(?:\s+job_type\s*:\s*(\S+))?",
    re.IGNORECASE,
)

# Regex to match a standard attribute line: attribute_name: value
_ATTR_RE = re.compile(r"^(\w+)\s*:\s*(.*?)\s*$")

# Regex to parse individual condition expressions like s(job_a), f(job_b)
_CONDITION_EXPR_RE = re.compile(r"([sfdn])\((\w+)\)", re.IGNORECASE)


def parse_conditions(condition_str: str) -> list[JilCondition]:
    """
    Parse an AutoSys condition string into a list of JilCondition objects.

    AutoSys conditions use operators like:
      s(job_name) — success of job_name
      f(job_name) — failure of job_name
      d(job_name) — done (success or failure)
      n(job_name) — notrunning

    Conditions can be combined with & (AND) and | (OR).
    This parser extracts all individual condition references.

    Args:
        condition_str: Raw condition string from JIL, e.g., "s(job_a) & s(job_b)"

    Returns:
        List of JilCondition objects representing each dependency
    """
    conditions = []
    for match in _CONDITION_EXPR_RE.finditer(condition_str):
        cond_type = match.group(1).lower()
        job_name = match.group(2)
        conditions.append(JilCondition(condition_type=cond_type, job_name=job_name))
    return conditions


def _strip_quotes(value: str) -> str:
    """Remove surrounding single or double quotes from a value string."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _apply_attribute(job: JilJob, attr_name: str, attr_value: str) -> None:
    """
    Apply a single parsed JIL attribute to a JilJob object.

    Maps each known AutoSys attribute name to the corresponding JilJob field.
    Unknown attributes are silently ignored to allow forward compatibility.

    Args:
        job: The JilJob being populated
        attr_name: Lowercase attribute name from JIL
        attr_value: Raw attribute value string
    """
    value = _strip_quotes(attr_value)

    # -- Core execution attributes --
    if attr_name == "job_type":
        # job_type may appear on a separate line if not inline with insert_job
        try:
            job.job_type = JilJobType(value.upper())
        except ValueError:
            # Unsupported job type — keep the default; converter will handle it
            pass
    elif attr_name == "machine":
        job.machine = value
    elif attr_name == "owner":
        job.owner = value
    elif attr_name == "command":
        job.command = value
    elif attr_name == "description":
        job.description = value
    elif attr_name == "profile":
        job.profile = value

    # -- Box membership --
    elif attr_name == "box_name":
        job.box_name = value

    # -- Scheduling attributes --
    elif attr_name == "date_conditions":
        job.date_conditions = value in ("1", "y", "yes", "true")
    elif attr_name == "days_of_week":
        job.days_of_week = value
    elif attr_name == "start_times":
        job.start_times = _strip_quotes(value)
    elif attr_name == "start_mins":
        job.start_mins = value
    elif attr_name == "run_calendar":
        job.run_calendar = value
    elif attr_name == "exclude_calendar":
        job.exclude_calendar = value
    elif attr_name == "timezone":
        job.timezone = value

    # -- Dependency conditions --
    elif attr_name == "condition":
        job.conditions = parse_conditions(value)

    # -- File watcher attributes --
    elif attr_name == "watch_file":
        job.watch_file = value
    elif attr_name == "watch_interval":
        job.watch_interval = int(value) if value.isdigit() else None
    elif attr_name == "watch_file_min_size":
        job.watch_file_min_size = int(value) if value.isdigit() else None

    # -- File transfer attributes --
    elif attr_name == "src_machine":
        job.src_machine = value
    elif attr_name == "dest_machine":
        job.dest_machine = value
    elif attr_name == "src_file":
        job.src_file = value
    elif attr_name == "dest_file":
        job.dest_file = value

    # -- Alerting and retry --
    elif attr_name == "alarm_if_fail":
        job.alarm_if_fail = value in ("1", "y", "yes", "true")
    elif attr_name == "max_run_alarm":
        job.max_run_alarm = int(value) if value.isdigit() else None
    elif attr_name == "n_retrys":
        job.n_retrys = int(value) if value.isdigit() else 0
    elif attr_name == "term_run_time":
        job.term_run_time = int(value) if value.isdigit() else None

    # -- Output redirection --
    elif attr_name == "std_out_file":
        job.std_out_file = value
    elif attr_name == "std_err_file":
        job.std_err_file = value

    # -- Permission and priority --
    elif attr_name == "permission":
        job.permission = value
    elif attr_name == "priority":
        job.priority = int(value) if value.isdigit() else None


def parse_jil_text(jil_text: str) -> list[JilJob]:
    """
    Parse raw JIL text content into a list of JilJob objects.

    Processes the text line by line, creating a new JilJob each time an
    insert_job/delete_job/update_job directive is encountered, then applying
    subsequent attribute lines to that job until the next directive.

    Args:
        jil_text: Complete JIL file content as a string

    Returns:
        List of parsed JilJob objects in definition order
    """
    jobs: list[JilJob] = []
    current_job: JilJob | None = None

    for raw_line in jil_text.splitlines():
        line = raw_line.strip()

        # Skip blank lines and comments
        if not line or line.startswith("/*") or line.startswith("#"):
            continue

        # Check for a new job definition start
        job_match = _JOB_START_RE.match(line)
        if job_match:
            directive = job_match.group(1).lower()   # insert_job, delete_job, update_job
            job_name = job_match.group(2)
            job_type_str = job_match.group(3)        # May be None if not inline

            # Determine the job type; default to CMD if not specified yet
            try:
                job_type = JilJobType(job_type_str.upper()) if job_type_str else JilJobType.CMD
            except ValueError:
                job_type = JilJobType.CMD

            # Create a new job and add it to the list
            current_job = JilJob(
                job_name=job_name,
                job_type=job_type,
                is_delete=(directive == "delete_job"),
            )
            jobs.append(current_job)

            # Check for additional attributes on the same line after job_type
            # e.g., "insert_job: x  job_type: CMD  machine: server1"
            remainder = line[job_match.end():]
            for extra_match in _ATTR_RE.finditer(remainder):
                if current_job:
                    _apply_attribute(current_job, extra_match.group(1).lower(), extra_match.group(2))

            continue

        # Apply attribute to current job
        attr_match = _ATTR_RE.match(line)
        if attr_match and current_job:
            attr_name = attr_match.group(1).lower()
            attr_value = attr_match.group(2)
            _apply_attribute(current_job, attr_name, attr_value)

    return jobs


def parse_jil_file(file_path: str | Path) -> list[JilJob]:
    """
    Parse a JIL file from disk into a list of JilJob objects.

    Args:
        file_path: Path to the JIL file

    Returns:
        List of parsed JilJob objects

    Raises:
        FileNotFoundError: If the JIL file does not exist
        UnicodeDecodeError: If the file cannot be decoded as UTF-8
    """
    path = Path(file_path)
    jil_text = path.read_text(encoding="utf-8")
    return parse_jil_text(jil_text)
