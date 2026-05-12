"""
Beeline JDBC execution utility.
Runs Hive SQL statements via beeline subprocess and returns parsed results.
Supports single queries, multi-statement scripts, and result-set extraction.
"""

import csv
import io
import logging
import subprocess
import tempfile
import time
from typing import Any

from config import (
    BEELINE_EXTRA_ARGS,
    BEELINE_JDBC_URL,
    BEELINE_PASSWORD,
    BEELINE_USER,
    QUERY_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class BeelineExecutionError(Exception):
    """Raised when a beeline command fails."""
    pass


def _build_beeline_cmd(sql_file_path: str) -> list[str]:
    """
    Build the beeline CLI command list.
    Uses -f <file> to execute a SQL file, with --silent=true and
    --outputformat=csv2 for machine-readable output.
    """
    cmd = [
        "beeline",
        "-u", BEELINE_JDBC_URL,
        "-n", BEELINE_USER,
        "--silent=true",
        "--outputformat=csv2",  # CSV output for easy parsing
        "-f", sql_file_path,
    ]
    # Add password if provided
    if BEELINE_PASSWORD:
        cmd.extend(["-p", BEELINE_PASSWORD])
    # Add any extra args (e.g. --hiveconf, Kerberos principal)
    if BEELINE_EXTRA_ARGS:
        cmd.extend(BEELINE_EXTRA_ARGS.split())
    return cmd


def execute_query(sql: str, timeout: int | None = None) -> list[dict[str, Any]]:
    """
    Execute a single HiveQL query via beeline and return the result set
    as a list of dicts (column_name -> value).

    Args:
        sql: The HiveQL query string to execute.
        timeout: Optional override for execution timeout in seconds.

    Returns:
        List of row dicts. Empty list for DDL/DML with no result set.

    Raises:
        BeelineExecutionError: If beeline exits with a non-zero code or
            produces error output indicating failure.
    """
    effective_timeout = timeout or QUERY_TIMEOUT_SECONDS

    # Write SQL to a temp file for beeline -f
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".hql", delete=False
    ) as tmp:
        tmp.write(sql.strip() + ";\n")
        tmp_path = tmp.name

    cmd = _build_beeline_cmd(tmp_path)
    logger.info("Executing beeline query: %s", sql[:200])
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - start_time
        raise BeelineExecutionError(
            f"Query timed out after {elapsed:.1f}s: {sql[:200]}"
        ) from exc

    elapsed = time.time() - start_time
    logger.info("Beeline completed in %.2fs (exit code %d)", elapsed, result.returncode)

    # Check for errors
    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        raise BeelineExecutionError(
            f"Beeline failed (exit {result.returncode}): {error_msg}"
        )

    # Parse CSV output into list of dicts
    return _parse_csv_output(result.stdout)


def execute_script(sql_script: str, timeout: int | None = None) -> str:
    """
    Execute a multi-statement HiveQL script via beeline.
    Returns the raw stdout. Use this for DDL or scripts where
    you don't need structured result parsing.

    Args:
        sql_script: Multi-statement HiveQL script.
        timeout: Optional override for execution timeout in seconds.

    Returns:
        Raw stdout from beeline.
    """
    effective_timeout = timeout or QUERY_TIMEOUT_SECONDS

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".hql", delete=False
    ) as tmp:
        tmp.write(sql_script)
        tmp_path = tmp.name

    cmd = _build_beeline_cmd(tmp_path)
    logger.info("Executing beeline script (%d chars)", len(sql_script))
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=effective_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.time() - start_time
        raise BeelineExecutionError(
            f"Script timed out after {elapsed:.1f}s"
        ) from exc

    elapsed = time.time() - start_time
    logger.info("Script completed in %.2fs (exit code %d)", elapsed, result.returncode)

    if result.returncode != 0:
        error_msg = result.stderr.strip() or result.stdout.strip()
        raise BeelineExecutionError(
            f"Script failed (exit {result.returncode}): {error_msg}"
        )

    return result.stdout


def execute_query_scalar(sql: str, timeout: int | None = None) -> Any:
    """
    Execute a query expected to return a single scalar value (e.g. COUNT(*)).
    Returns the value from the first column of the first row.

    Args:
        sql: A query that returns exactly one row and one column.
        timeout: Optional timeout override.

    Returns:
        The scalar value (str). Caller should cast as needed.

    Raises:
        BeelineExecutionError: If no rows returned or query fails.
    """
    rows = execute_query(sql, timeout=timeout)
    if not rows:
        raise BeelineExecutionError(f"Scalar query returned no rows: {sql[:200]}")
    first_row = rows[0]
    # Return the first column value regardless of name
    return next(iter(first_row.values()))


def _parse_csv_output(stdout: str) -> list[dict[str, Any]]:
    """
    Parse beeline CSV2-format output into a list of dicts.
    Handles empty output (DDL statements) gracefully.
    """
    # Strip leading/trailing whitespace and filter out blank lines
    lines = [line for line in stdout.strip().splitlines() if line.strip()]
    if not lines:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    rows = []
    for row in reader:
        # Strip whitespace from keys and values
        cleaned = {k.strip(): v.strip() if v else v for k, v in row.items()}
        rows.append(cleaned)
    return rows
