"""
Regression validation test cases.
Compares results between two as_of_dt snapshots to detect unexpected
changes in row counts, balance totals, and status distributions.
Used to catch ETL regressions when re-running the pipeline.
"""

import logging
from decimal import Decimal

from beeline_executor import execute_query, execute_query_scalar
from config import (
    DATA_SRC_IND_DAILY,
    DATA_SRC_IND_MOEND,
    TABLES,
)

logger = logging.getLogger(__name__)

# Maximum allowed percentage change between snapshots before flagging regression
MAX_ROW_COUNT_CHANGE_PCT = 10.0  # 10% threshold for row count fluctuation
MAX_BALANCE_CHANGE_PCT = 15.0    # 15% threshold for balance total fluctuation


def _pct_change(old_val: float, new_val: float) -> float:
    """Calculate percentage change between two values. Returns 0 if old is 0."""
    if old_val == 0:
        return 0.0 if new_val == 0 else 100.0
    return abs((new_val - old_val) / old_val) * 100


def test_row_count_regression(
    as_of_dt_current: str, as_of_dt_previous: str, data_src_ind: str
) -> list[dict]:
    """
    TC-RG-001: Compare row counts between current and previous snapshot.
    Flags tables where counts changed by more than MAX_ROW_COUNT_CHANGE_PCT.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    for fq_name in TABLES:
        prev_sql = (
            f"SELECT COUNT(*) AS cnt FROM {fq_name} "
            f"WHERE as_of_dt = '{as_of_dt_previous}' AND {dsi_filter}"
        )
        curr_sql = (
            f"SELECT COUNT(*) AS cnt FROM {fq_name} "
            f"WHERE as_of_dt = '{as_of_dt_current}' AND {dsi_filter}"
        )
        try:
            prev_count = int(execute_query_scalar(prev_sql))
            curr_count = int(execute_query_scalar(curr_sql))
            change_pct = _pct_change(prev_count, curr_count)
            passed = change_pct <= MAX_ROW_COUNT_CHANGE_PCT

            results.append({
                "test_id": "TC-RG-001",
                "test_name": f"Row count regression: {fq_name} ({data_src_ind})",
                "category": "regression",
                "sql": f"{prev_sql} vs {curr_sql}",
                "expected": f"<={MAX_ROW_COUNT_CHANGE_PCT}% change",
                "actual": f"{change_pct:.1f}% (prev={prev_count}, curr={curr_count})",
                "passed": passed,
                "message": (
                    f"{fq_name}: {prev_count} -> {curr_count} ({change_pct:.1f}% change)"
                    + ("" if passed else " ** REGRESSION **")
                ),
            })
        except Exception as exc:
            results.append({
                "test_id": "TC-RG-001",
                "test_name": f"Row count regression: {fq_name} ({data_src_ind})",
                "category": "regression",
                "sql": f"{prev_sql} vs {curr_sql}",
                "expected": "comparable",
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    return results


def test_balance_total_regression(
    as_of_dt_current: str, as_of_dt_previous: str, data_src_ind: str
) -> list[dict]:
    """
    TC-RG-002: Compare SUM(ln_curr_bal) between snapshots for cad_cb and cad_nccb.
    Flags if the total balance shifted by more than MAX_BALANCE_CHANGE_PCT.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    balance_tables = [
        ("work_schema.cad_cb", "current balance"),
        ("work_schema.cad_nccb", "non-current balance"),
    ]
    for tbl, label in balance_tables:
        prev_sql = (
            f"SELECT COALESCE(SUM(ln_curr_bal), 0) AS total FROM {tbl} "
            f"WHERE as_of_dt = '{as_of_dt_previous}' AND {dsi_filter}"
        )
        curr_sql = (
            f"SELECT COALESCE(SUM(ln_curr_bal), 0) AS total FROM {tbl} "
            f"WHERE as_of_dt = '{as_of_dt_current}' AND {dsi_filter}"
        )
        try:
            prev_total = float(execute_query_scalar(prev_sql))
            curr_total = float(execute_query_scalar(curr_sql))
            change_pct = _pct_change(prev_total, curr_total)
            passed = change_pct <= MAX_BALANCE_CHANGE_PCT

            results.append({
                "test_id": "TC-RG-002",
                "test_name": f"Balance regression: {label} ({data_src_ind})",
                "category": "regression",
                "sql": f"{prev_sql} vs {curr_sql}",
                "expected": f"<={MAX_BALANCE_CHANGE_PCT}% change",
                "actual": f"{change_pct:.1f}% (prev={prev_total}, curr={curr_total})",
                "passed": passed,
                "message": (
                    f"{label}: {prev_total} -> {curr_total} ({change_pct:.1f}%)"
                    + ("" if passed else " ** REGRESSION **")
                ),
            })
        except Exception as exc:
            results.append({
                "test_id": "TC-RG-002",
                "test_name": f"Balance regression: {label} ({data_src_ind})",
                "category": "regression",
                "sql": f"{prev_sql} vs {curr_sql}",
                "expected": "comparable",
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    return results


def test_status_distribution_regression(
    as_of_dt_current: str, as_of_dt_previous: str, data_src_ind: str
) -> list[dict]:
    """
    TC-RG-003: Compare loan status distribution between snapshots.
    Detects if a status category unexpectedly appeared or disappeared.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    sql_template = (
        "SELECT ln_stat_cd, COUNT(*) AS cnt "
        "FROM work_schema.cad_cb "
        "WHERE as_of_dt = '{dt}' AND {dsi} "
        "GROUP BY ln_stat_cd ORDER BY ln_stat_cd"
    )
    prev_sql = sql_template.format(dt=as_of_dt_previous, dsi=dsi_filter)
    curr_sql = sql_template.format(dt=as_of_dt_current, dsi=dsi_filter)

    try:
        prev_rows = execute_query(prev_sql)
        curr_rows = execute_query(curr_sql)

        prev_statuses = {r["ln_stat_cd"] for r in prev_rows if r.get("ln_stat_cd")}
        curr_statuses = {r["ln_stat_cd"] for r in curr_rows if r.get("ln_stat_cd")}

        # Check for disappeared statuses
        disappeared = prev_statuses - curr_statuses
        new_statuses = curr_statuses - prev_statuses
        passed = len(disappeared) == 0

        results.append({
            "test_id": "TC-RG-003",
            "test_name": f"Status distribution regression ({data_src_ind})",
            "category": "regression",
            "sql": f"{prev_sql} vs {curr_sql}",
            "expected": "no disappeared statuses",
            "actual": f"disappeared={disappeared}, new={new_statuses}",
            "passed": passed,
            "message": (
                f"Previous statuses={prev_statuses}, Current={curr_statuses}"
                + (f" ** DISAPPEARED: {disappeared} **" if disappeared else "")
            ),
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-RG-003",
            "test_name": f"Status distribution regression ({data_src_ind})",
            "category": "regression",
            "sql": "multiple",
            "expected": "comparable",
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def run_all(as_of_dt_current: str, as_of_dt_previous: str) -> list[dict]:
    """Run all regression test cases comparing two snapshots."""
    logger.info(
        "=== Running regression validations: %s vs %s ===",
        as_of_dt_current, as_of_dt_previous,
    )
    results = []
    for dsi in [DATA_SRC_IND_DAILY, DATA_SRC_IND_MOEND]:
        results.extend(test_row_count_regression(as_of_dt_current, as_of_dt_previous, dsi))
        results.extend(test_balance_total_regression(as_of_dt_current, as_of_dt_previous, dsi))
        results.extend(test_status_distribution_regression(as_of_dt_current, as_of_dt_previous, dsi))
    return results
