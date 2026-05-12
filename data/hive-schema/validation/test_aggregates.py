"""
Aggregate validation test cases.
Verifies that balance totals, payment sums, and other aggregated measures
are consistent across source, staging, and audit layers.
"""

import logging
from decimal import Decimal

from beeline_executor import execute_query, execute_query_scalar
from config import (
    DATA_SRC_IND_DAILY,
    DATA_SRC_IND_MOEND,
)

logger = logging.getLogger(__name__)

# Tolerance for floating-point comparison in DECIMAL aggregates
DECIMAL_TOLERANCE = Decimal("0.01")


def _compare_sums(expected: str, actual: str) -> bool:
    """Compare two decimal string values within tolerance."""
    try:
        exp = Decimal(expected)
        act = Decimal(actual)
        return abs(exp - act) <= DECIMAL_TOLERANCE
    except Exception:
        return expected == actual


def test_balance_sum_consistency(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-AG-001: Verify total balance sums match between source and staging.
    SUM(ln_curr_bal) in source (after removing commas) should match staging.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    # Source: ln_curr_bal is STRING with commas; cast after removing commas
    src_sql = (
        "SELECT COALESCE(SUM(CAST(REGEXP_REPLACE(ln_curr_bal, ',', '') AS DECIMAL(12,2))), 0) AS total "
        "FROM default.td_contracts "
        f"WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter} "
        "  AND ln_curr_bal IS NOT NULL AND TRIM(ln_curr_bal) != ''"
    )
    # Staging: cad_cb (current) + cad_nccb (non-current) should sum to source total
    stg_cb_sql = (
        "SELECT COALESCE(SUM(ln_curr_bal), 0) AS total "
        f"FROM work_schema.cad_cb WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )
    stg_nccb_sql = (
        "SELECT COALESCE(SUM(ln_curr_bal), 0) AS total "
        f"FROM work_schema.cad_nccb WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )

    try:
        src_total = execute_query_scalar(src_sql)
        cb_total = execute_query_scalar(stg_cb_sql)
        nccb_total = execute_query_scalar(stg_nccb_sql)

        stg_total = str(Decimal(cb_total) + Decimal(nccb_total))
        passed = _compare_sums(src_total, stg_total)

        results.append({
            "test_id": "TC-AG-001",
            "test_name": f"Balance sum: source vs staging ({data_src_ind})",
            "category": "aggregate",
            "sql": f"source={src_sql}; staging=cb+nccb",
            "expected": src_total,
            "actual": stg_total,
            "passed": passed,
            "message": f"Source total={src_total}, Staging total={stg_total}",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-AG-001",
            "test_name": f"Balance sum: source vs staging ({data_src_ind})",
            "category": "aggregate",
            "sql": "multiple",
            "expected": "match",
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def test_original_amount_sum(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-AG-002: Verify SUM(ln_orig_amt) between staging and audit layers.
    cad_cb.ln_orig_amt sum should match cad_actg_unit_bal_fact.ln_orig_amt sum.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    # Current: staging vs audit
    stg_sql = (
        f"SELECT COALESCE(SUM(ln_orig_amt), 0) AS total FROM work_schema.cad_cb "
        f"WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )
    aud_sql = (
        f"SELECT COALESCE(SUM(ln_orig_amt), 0) AS total FROM audit.cad_actg_unit_bal_fact "
        f"WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )
    try:
        stg_total = execute_query_scalar(stg_sql)
        aud_total = execute_query_scalar(aud_sql)
        passed = _compare_sums(stg_total, aud_total)
        results.append({
            "test_id": "TC-AG-002a",
            "test_name": f"Original amount sum: cad_cb vs actg_fact ({data_src_ind})",
            "category": "aggregate",
            "sql": f"{stg_sql} vs {aud_sql}",
            "expected": stg_total,
            "actual": aud_total,
            "passed": passed,
            "message": f"Staging={stg_total}, Audit={aud_total}",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-AG-002a",
            "test_name": f"Original amount sum: cad_cb vs actg_fact ({data_src_ind})",
            "category": "aggregate",
            "sql": "multiple",
            "expected": "match",
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    # Non-current: staging vs audit
    stg_nc_sql = (
        f"SELECT COALESCE(SUM(ln_orig_amt), 0) AS total FROM work_schema.cad_nccb "
        f"WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )
    aud_nc_sql = (
        f"SELECT COALESCE(SUM(ln_orig_amt), 0) AS total FROM audit.cad_nc_actg_unit_bal_fact "
        f"WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )
    try:
        stg_total = execute_query_scalar(stg_nc_sql)
        aud_total = execute_query_scalar(aud_nc_sql)
        passed = _compare_sums(stg_total, aud_total)
        results.append({
            "test_id": "TC-AG-002b",
            "test_name": f"Original amount sum: cad_nccb vs nc_actg_fact ({data_src_ind})",
            "category": "aggregate",
            "sql": f"{stg_nc_sql} vs {aud_nc_sql}",
            "expected": stg_total,
            "actual": aud_total,
            "passed": passed,
            "message": f"Staging={stg_total}, Audit={aud_total}",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-AG-002b",
            "test_name": f"Original amount sum: cad_nccb vs nc_actg_fact ({data_src_ind})",
            "category": "aggregate",
            "sql": "multiple",
            "expected": "match",
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def test_escrow_balance_sum(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-AG-003: Verify SUM(ln_escrow_bal) between staging and audit.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    stg_sql = (
        f"SELECT COALESCE(SUM(ln_escrow_bal), 0) AS total FROM work_schema.cad_cb "
        f"WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )
    aud_sql = (
        f"SELECT COALESCE(SUM(ln_escrow_bal), 0) AS total FROM audit.cad_actg_unit_bal_fact "
        f"WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )
    try:
        stg_total = execute_query_scalar(stg_sql)
        aud_total = execute_query_scalar(aud_sql)
        passed = _compare_sums(stg_total, aud_total)
        results.append({
            "test_id": "TC-AG-003",
            "test_name": f"Escrow balance sum: staging vs audit ({data_src_ind})",
            "category": "aggregate",
            "sql": f"{stg_sql} vs {aud_sql}",
            "expected": stg_total,
            "actual": aud_total,
            "passed": passed,
            "message": f"Staging={stg_total}, Audit={aud_total}",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-AG-003",
            "test_name": f"Escrow balance sum: staging vs audit ({data_src_ind})",
            "category": "aggregate",
            "sql": "multiple",
            "expected": "match",
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def test_payment_amount_sum(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-AG-004: Verify last_pmt_amt sum in audit fact equals the sum of
    its component parts (principal + interest + escrow + late_fee).
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    sql = (
        "SELECT "
        "  COALESCE(SUM(last_pmt_amt), 0) AS total_pmt, "
        "  COALESCE(SUM(last_pmt_prin_amt), 0) + "
        "  COALESCE(SUM(last_pmt_int_amt), 0) + "
        "  COALESCE(SUM(last_pmt_escrow_amt), 0) + "
        "  COALESCE(SUM(last_pmt_late_fee), 0) AS component_sum "
        "FROM audit.cad_actg_unit_bal_fact "
        f"WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )
    try:
        rows = execute_query(sql)
        if rows:
            total_pmt = rows[0].get("total_pmt", "0")
            component_sum = rows[0].get("component_sum", "0")
            passed = _compare_sums(total_pmt, component_sum)
            results.append({
                "test_id": "TC-AG-004",
                "test_name": f"Payment component sum check ({data_src_ind})",
                "category": "aggregate",
                "sql": sql,
                "expected": total_pmt,
                "actual": component_sum,
                "passed": passed,
                "message": f"total_pmt={total_pmt}, components={component_sum}",
            })
        else:
            results.append({
                "test_id": "TC-AG-004",
                "test_name": f"Payment component sum check ({data_src_ind})",
                "category": "aggregate",
                "sql": sql,
                "expected": "data",
                "actual": "no rows",
                "passed": False,
                "message": "No rows returned from audit fact table",
            })
    except Exception as exc:
        results.append({
            "test_id": "TC-AG-004",
            "test_name": f"Payment component sum check ({data_src_ind})",
            "category": "aggregate",
            "sql": sql,
            "expected": "match",
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def test_annual_income_sum(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-AG-005: Verify SUM(borr_ann_incm) between source (parsed) and cad_id.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    src_sql = (
        "SELECT COALESCE(SUM(CAST(REGEXP_REPLACE(borr_ann_incm, ',', '') AS DECIMAL(12,2))), 0) AS total "
        "FROM default.td_contracts "
        f"WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter} "
        "  AND borr_ann_incm IS NOT NULL AND TRIM(borr_ann_incm) != ''"
    )
    stg_sql = (
        "SELECT COALESCE(SUM(borr_ann_incm), 0) AS total "
        f"FROM work_schema.cad_id WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter}"
    )
    try:
        src_total = execute_query_scalar(src_sql)
        stg_total = execute_query_scalar(stg_sql)
        passed = _compare_sums(src_total, stg_total)
        results.append({
            "test_id": "TC-AG-005",
            "test_name": f"Annual income sum: source vs cad_id ({data_src_ind})",
            "category": "aggregate",
            "sql": f"{src_sql} vs {stg_sql}",
            "expected": src_total,
            "actual": stg_total,
            "passed": passed,
            "message": f"Source={src_total}, Staging={stg_total}",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-AG-005",
            "test_name": f"Annual income sum: source vs cad_id ({data_src_ind})",
            "category": "aggregate",
            "sql": "multiple",
            "expected": "match",
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def run_all(as_of_dt: str) -> list[dict]:
    """Run all aggregate test cases and return combined results."""
    logger.info("=== Running aggregate validations for as_of_dt=%s ===", as_of_dt)
    results = []
    for dsi in [DATA_SRC_IND_DAILY, DATA_SRC_IND_MOEND]:
        results.extend(test_balance_sum_consistency(as_of_dt, dsi))
        results.extend(test_original_amount_sum(as_of_dt, dsi))
        results.extend(test_escrow_balance_sum(as_of_dt, dsi))
        results.extend(test_payment_amount_sum(as_of_dt, dsi))
        results.extend(test_annual_income_sum(as_of_dt, dsi))
    return results
