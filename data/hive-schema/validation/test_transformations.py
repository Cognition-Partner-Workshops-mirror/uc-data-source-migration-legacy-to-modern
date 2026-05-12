"""
Transformation validation test cases.
Verifies that data type conversions, status code expansions, and
amount/date parsing are correctly applied per column_mappings.md.
"""

import logging

from beeline_executor import execute_query, execute_query_scalar
from config import (
    BORROWER_STATUS_MAP,
    DATA_SRC_IND_DAILY,
    DATA_SRC_IND_MOEND,
    LOAN_STATUS_MAP,
    PAYMENT_STATUS_MAP,
    PAYMENT_TYPE_MAP,
    PROPERTY_TYPE_MAP,
)

logger = logging.getLogger(__name__)


def test_date_parsing(as_of_dt: str) -> list[dict]:
    """
    TC-TF-001: Verify MM/DD/YYYY string dates in source are correctly
    parsed to DATE type in staging (cad_id.borr_dob_dt, cad_cb date cols).
    Checks for NULL dates that were non-NULL in source (parse failures).
    """
    results = []

    # Check cad_id: borr_dob_dt should not be NULL when source borr_dob_dt is non-NULL
    sql = (
        "SELECT COUNT(*) AS cnt FROM work_schema.cad_id ci "
        "JOIN default.td_contracts tc "
        "  ON ci.ln_acct_nbr = tc.ln_acct_nbr "
        "  AND ci.as_of_dt = tc.as_of_dt "
        "  AND ci.data_src_ind = tc.data_src_ind "
        f"WHERE ci.as_of_dt = '{as_of_dt}' "
        "  AND tc.borr_dob_dt IS NOT NULL "
        "  AND TRIM(tc.borr_dob_dt) != '' "
        "  AND ci.borr_dob_dt IS NULL"
    )
    try:
        failed_parses = int(execute_query_scalar(sql))
        passed = failed_parses == 0
        results.append({
            "test_id": "TC-TF-001a",
            "test_name": "Date parsing: borr_dob_dt (cad_id)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": failed_parses,
            "passed": passed,
            "message": f"{failed_parses} date parse failures" if not passed
                else "All borr_dob_dt values parsed successfully",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-TF-001a",
            "test_name": "Date parsing: borr_dob_dt (cad_id)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    # Check cad_cb: ln_orig_dt, ln_mat_dt should parse without NULL gaps
    for col in ["ln_orig_dt", "ln_mat_dt", "ln_1st_pmt_dt", "ln_nxt_pmt_dt"]:
        sql = (
            f"SELECT COUNT(*) AS cnt FROM work_schema.cad_cb cb "
            "JOIN default.td_contracts tc "
            "  ON cb.ln_acct_nbr = tc.ln_acct_nbr "
            "  AND cb.as_of_dt = tc.as_of_dt "
            "  AND cb.data_src_ind = tc.data_src_ind "
            f"WHERE cb.as_of_dt = '{as_of_dt}' "
            f"  AND tc.{col} IS NOT NULL "
            f"  AND TRIM(tc.{col}) != '' "
            f"  AND cb.{col} IS NULL"
        )
        try:
            failed = int(execute_query_scalar(sql))
            passed = failed == 0
            results.append({
                "test_id": "TC-TF-001b",
                "test_name": f"Date parsing: {col} (cad_cb)",
                "category": "transformation",
                "sql": sql,
                "expected": 0,
                "actual": failed,
                "passed": passed,
                "message": f"{failed} parse failures for {col}" if not passed
                    else f"All {col} values parsed successfully",
            })
        except Exception as exc:
            results.append({
                "test_id": "TC-TF-001b",
                "test_name": f"Date parsing: {col} (cad_cb)",
                "category": "transformation",
                "sql": sql,
                "expected": 0,
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    return results


def test_amount_parsing(as_of_dt: str) -> list[dict]:
    """
    TC-TF-002: Verify string amounts with commas in source are correctly
    parsed to DECIMAL in staging. Checks that no negative amounts appear
    where source had positive values (sign-flip errors).
    """
    results = []

    # Check cad_cb balance columns: should be non-negative when source is non-negative
    amount_cols = [
        ("ln_orig_amt", "original amount"),
        ("ln_curr_bal", "current balance"),
        ("ln_pmt_amt", "monthly payment"),
        ("ln_escrow_bal", "escrow balance"),
    ]
    for col, label in amount_cols:
        sql = (
            f"SELECT COUNT(*) AS cnt FROM work_schema.cad_cb "
            f"WHERE as_of_dt = '{as_of_dt}' "
            f"  AND {col} < 0"
        )
        try:
            neg_count = int(execute_query_scalar(sql))
            passed = neg_count == 0
            results.append({
                "test_id": "TC-TF-002",
                "test_name": f"Amount non-negative: {label} (cad_cb)",
                "category": "transformation",
                "sql": sql,
                "expected": 0,
                "actual": neg_count,
                "passed": passed,
                "message": f"{neg_count} negative {label} values" if not passed
                    else f"All {label} values are non-negative",
            })
        except Exception as exc:
            results.append({
                "test_id": "TC-TF-002",
                "test_name": f"Amount non-negative: {label} (cad_cb)",
                "category": "transformation",
                "sql": sql,
                "expected": 0,
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    # Check cad_id: annual income should parse correctly
    sql = (
        "SELECT COUNT(*) AS cnt FROM work_schema.cad_id ci "
        "JOIN default.td_contracts tc "
        "  ON ci.borr_id = tc.borr_id "
        "  AND ci.as_of_dt = tc.as_of_dt "
        "  AND ci.data_src_ind = tc.data_src_ind "
        f"WHERE ci.as_of_dt = '{as_of_dt}' "
        "  AND tc.borr_ann_incm IS NOT NULL "
        "  AND TRIM(tc.borr_ann_incm) != '' "
        "  AND ci.borr_ann_incm IS NULL"
    )
    try:
        failed = int(execute_query_scalar(sql))
        passed = failed == 0
        results.append({
            "test_id": "TC-TF-002b",
            "test_name": "Amount parsing: annual income (cad_id)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": failed,
            "passed": passed,
            "message": f"{failed} income parse failures" if not passed
                else "All annual_income values parsed successfully",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-TF-002b",
            "test_name": "Amount parsing: annual income (cad_id)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def test_status_code_expansion(as_of_dt: str) -> list[dict]:
    """
    TC-TF-003: Verify status codes are expanded per column_mappings.md.
    No raw CDW codes (ACT, CLO, etc.) should exist in staging/audit layers.
    """
    results = []

    # Loan status in cad_cb — should only contain expanded values
    valid_loan_statuses = set(LOAN_STATUS_MAP.values())
    valid_str = ",".join(f"'{v}'" for v in valid_loan_statuses)
    sql = (
        f"SELECT COUNT(*) AS cnt FROM work_schema.cad_cb "
        f"WHERE as_of_dt = '{as_of_dt}' "
        f"  AND ln_stat_cd NOT IN ({valid_str})"
    )
    try:
        invalid_count = int(execute_query_scalar(sql))
        passed = invalid_count == 0
        results.append({
            "test_id": "TC-TF-003a",
            "test_name": "Loan status expansion (cad_cb)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": invalid_count,
            "passed": passed,
            "message": f"{invalid_count} un-expanded loan statuses" if not passed
                else "All loan statuses correctly expanded",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-TF-003a",
            "test_name": "Loan status expansion (cad_cb)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    # Borrower status in cad_id — should only contain expanded values
    valid_borr_statuses = set(BORROWER_STATUS_MAP.values())
    valid_str = ",".join(f"'{v}'" for v in valid_borr_statuses)
    sql = (
        f"SELECT COUNT(*) AS cnt FROM work_schema.cad_id "
        f"WHERE as_of_dt = '{as_of_dt}' "
        f"  AND borr_stat_cd NOT IN ({valid_str})"
    )
    try:
        invalid_count = int(execute_query_scalar(sql))
        passed = invalid_count == 0
        results.append({
            "test_id": "TC-TF-003b",
            "test_name": "Borrower status expansion (cad_id)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": invalid_count,
            "passed": passed,
            "message": f"{invalid_count} un-expanded borrower statuses" if not passed
                else "All borrower statuses correctly expanded",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-TF-003b",
            "test_name": "Borrower status expansion (cad_id)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    # Payment type/status in audit fact tables
    valid_pmt_types = set(PAYMENT_TYPE_MAP.values())
    valid_str = ",".join(f"'{v}'" for v in valid_pmt_types)
    sql = (
        f"SELECT COUNT(*) AS cnt FROM audit.cad_actg_unit_bal_fact "
        f"WHERE as_of_dt = '{as_of_dt}' "
        f"  AND last_pmt_typ_cd IS NOT NULL "
        f"  AND last_pmt_typ_cd NOT IN ({valid_str})"
    )
    try:
        invalid_count = int(execute_query_scalar(sql))
        passed = invalid_count == 0
        results.append({
            "test_id": "TC-TF-003c",
            "test_name": "Payment type expansion (actg_unit_bal_fact)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": invalid_count,
            "passed": passed,
            "message": f"{invalid_count} un-expanded payment types" if not passed
                else "All payment types correctly expanded",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-TF-003c",
            "test_name": "Payment type expansion (actg_unit_bal_fact)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def test_credit_score_integer_conversion(as_of_dt: str) -> list[dict]:
    """
    TC-TF-004: Verify credit scores are parsed from STRING to INT in cad_id.
    Valid range: 300-850 (standard FICO range).
    """
    results = []
    sql = (
        f"SELECT COUNT(*) AS cnt FROM work_schema.cad_id "
        f"WHERE as_of_dt = '{as_of_dt}' "
        f"  AND borr_crdt_scr IS NOT NULL "
        f"  AND (borr_crdt_scr < 300 OR borr_crdt_scr > 850)"
    )
    try:
        out_of_range = int(execute_query_scalar(sql))
        passed = out_of_range == 0
        results.append({
            "test_id": "TC-TF-004",
            "test_name": "Credit score range validation (cad_id)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": out_of_range,
            "passed": passed,
            "message": f"{out_of_range} credit scores outside 300-850 range" if not passed
                else "All credit scores within valid FICO range",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-TF-004",
            "test_name": "Credit score range validation (cad_id)",
            "category": "transformation",
            "sql": sql,
            "expected": 0,
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def test_data_src_ind_values(as_of_dt: str) -> list[dict]:
    """
    TC-TF-005: Verify data_src_ind only contains valid values ('D' or 'M')
    across all tables. No NULLs or unexpected codes.
    """
    results = []
    from config import TABLES, VALID_DATA_SRC_IND_VALUES

    valid_str = ",".join(f"'{v}'" for v in VALID_DATA_SRC_IND_VALUES)
    for fq_name in TABLES:
        sql = (
            f"SELECT COUNT(*) AS cnt FROM {fq_name} "
            f"WHERE as_of_dt = '{as_of_dt}' "
            f"  AND (data_src_ind IS NULL OR data_src_ind NOT IN ({valid_str}))"
        )
        try:
            invalid = int(execute_query_scalar(sql))
            passed = invalid == 0
            results.append({
                "test_id": "TC-TF-005",
                "test_name": f"data_src_ind valid values: {fq_name}",
                "category": "transformation",
                "sql": sql,
                "expected": 0,
                "actual": invalid,
                "passed": passed,
                "message": f"{invalid} invalid data_src_ind values in {fq_name}" if not passed
                    else f"All data_src_ind values valid in {fq_name}",
            })
        except Exception as exc:
            results.append({
                "test_id": "TC-TF-005",
                "test_name": f"data_src_ind valid values: {fq_name}",
                "category": "transformation",
                "sql": sql,
                "expected": 0,
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    return results


def run_all(as_of_dt: str) -> list[dict]:
    """Run all transformation test cases and return combined results."""
    logger.info("=== Running transformation validations for as_of_dt=%s ===", as_of_dt)
    results = []
    results.extend(test_date_parsing(as_of_dt))
    results.extend(test_amount_parsing(as_of_dt))
    results.extend(test_status_code_expansion(as_of_dt))
    results.extend(test_credit_score_integer_conversion(as_of_dt))
    results.extend(test_data_src_ind_values(as_of_dt))
    return results
