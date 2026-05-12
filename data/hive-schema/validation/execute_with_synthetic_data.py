#!/usr/bin/env python3
"""
Execute validation scripts using synthetic data.
Patches beeline_executor to return simulated Hive query results,
including deliberate defect scenarios to demonstrate failure detection.

This script simulates a realistic ETL pipeline where:
  - 500 contracts are loaded from source (default.td_contracts)
  - 350 are current (ACT/FRB) -> cad_cb -> cad_actg_unit_bal_fact
  - 150 are non-current (CLO/DFT) -> cad_nccb -> cad_nc_actg_unit_bal_fact
  - All 500 flow to cad_id and cad_arrg_dim

Injected defects (to demonstrate failure scenarios):
  1. 3 date parse failures in cad_id.borr_dob_dt (TC-TF-001a)
  2. 2 un-expanded loan status codes in cad_cb (TC-TF-003a)
  3. 1 credit score outside FICO range in cad_id (TC-TF-004)
  4. Payment component sum mismatch in MOEND audit fact (TC-AG-004)
  5. 2 orphan records in source->cad_id join for MOEND (TC-IG-002)
  6. 1 duplicate record in cad_cb for DAILY (TC-IG-005b)
"""

import logging
import os
import re
import sys
import time
from decimal import Decimal
from unittest.mock import patch

# Add validation directory to path
VALIDATION_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, VALIDATION_DIR)

import config
import report_generator
import test_aggregates
import test_integration
import test_regression
import test_row_counts
import test_transformations

logger = logging.getLogger(__name__)

# =============================================================================
# Synthetic Dataset Configuration
# =============================================================================
# Simulated snapshot dates
AS_OF_DT = "2024-01-31"         # Current snapshot (month-end)
AS_OF_DT_PREV = "2023-12-31"    # Previous snapshot (prior month-end)

# Base record counts for the current snapshot
# Source: 500 total contracts
# Current (ACT/FRB): 350 -> cad_cb, cad_actg_unit_bal_fact
# Non-current (CLO/DFT): 150 -> cad_nccb, cad_nc_actg_unit_bal_fact
# All 500 -> cad_id, cad_arrg_dim
SOURCE_TOTAL_D = 500
SOURCE_TOTAL_M = 500
SOURCE_CURRENT_D = 350
SOURCE_CURRENT_M = 350
SOURCE_NC_D = 150
SOURCE_NC_M = 150

# Previous snapshot counts (for regression comparison)
PREV_SOURCE_TOTAL_D = 490
PREV_SOURCE_TOTAL_M = 490
PREV_CB_D = 345
PREV_NCCB_D = 145

# Balance totals (synthetic)
SRC_BALANCE_TOTAL = Decimal("42500000.00")   # ~$42.5M total current balance
CB_BALANCE = Decimal("35000000.00")          # current contracts
NCCB_BALANCE = Decimal("7500000.00")         # non-current contracts
SRC_ORIG_AMT = Decimal("65000000.00")
CB_ORIG_AMT = Decimal("52000000.00")
NCCB_ORIG_AMT = Decimal("13000000.00")
CB_ESCROW = Decimal("1750000.00")
ANNUAL_INCOME_TOTAL = Decimal("38500000.00")

# Injected defect counts
DEFECT_DATE_PARSE_FAILURES = 3      # borr_dob_dt NULLs where source was non-NULL
DEFECT_UNEXPANDED_STATUSES = 2      # raw CDW codes left in cad_cb.ln_stat_cd
DEFECT_CREDIT_SCORE_RANGE = 1       # score outside 300-850
DEFECT_PMT_COMPONENT_MISMATCH = True  # total != sum of components (MOEND only)
DEFECT_ORPHAN_SOURCE_RECORDS = 2     # source rows missing from cad_id (MOEND)
DEFECT_DUPLICATE_CB_RECORDS = 1      # duplicate in cad_cb (DAILY)


# =============================================================================
# SQL Pattern Matching Engine
# =============================================================================
# Maps SQL query patterns to synthetic results.
# Uses regex matching to identify query intent and return appropriate data.

def _is_join_query(sql: str) -> bool:
    """Detect whether a SQL query contains a JOIN clause."""
    sql_lower = sql.lower()
    return "join " in sql_lower or "left join " in sql_lower


def _match_count_query(sql: str) -> str | None:
    """
    Match simple (non-JOIN) COUNT(*) queries and return synthetic counts.
    Returns the count as a string, or None if no pattern matches.
    Skips JOIN queries — those are handled by _match_join_query.
    """
    sql_lower = sql.lower().strip()

    # Skip JOIN queries — they have their own handler
    if _is_join_query(sql_lower):
        return None

    # Also skip subquery-based duplicate checks (HAVING)
    if "having count(*)" in sql_lower:
        return None

    # Determine which table and filters
    table_match = re.search(r'from\s+(\w+\.\w+)', sql_lower)
    if not table_match:
        return None
    table = table_match.group(1)

    is_daily = "data_src_ind = 'd'" in sql_lower
    is_moend = "data_src_ind = 'm'" in sql_lower
    is_current = AS_OF_DT.lower() in sql_lower
    is_prev = AS_OF_DT_PREV.lower() in sql_lower

    # --- Source table counts ---
    if table == "default.td_contracts":
        has_current_filter = ("'act'" in sql_lower and "'frb'" in sql_lower)
        has_nc_filter = ("'clo'" in sql_lower and "'dft'" in sql_lower)
        has_invalid_dsi = "data_src_ind is null" in sql_lower or "data_src_ind not in" in sql_lower

        if has_invalid_dsi:
            return "0"

        if is_current or (not is_prev):
            if has_current_filter:
                return str(SOURCE_CURRENT_D if is_daily else SOURCE_CURRENT_M)
            elif has_nc_filter:
                return str(SOURCE_NC_D if is_daily else SOURCE_NC_M)
            else:
                return str(SOURCE_TOTAL_D if is_daily else SOURCE_TOTAL_M) if (is_daily or is_moend) else str(SOURCE_TOTAL_D + SOURCE_TOTAL_M)
        elif is_prev:
            if has_current_filter:
                return str(PREV_CB_D)
            elif has_nc_filter:
                return str(PREV_NCCB_D)
            else:
                return str(PREV_SOURCE_TOTAL_D if is_daily else PREV_SOURCE_TOTAL_M)

    # --- Staging: cad_id ---
    elif table == "work_schema.cad_id":
        has_invalid_dsi = "data_src_ind is null" in sql_lower or "data_src_ind not in" in sql_lower
        has_borr_stat = "borr_stat_cd not in" in sql_lower
        has_credit_score = "borr_crdt_scr" in sql_lower

        if has_invalid_dsi:
            return "0"
        if has_borr_stat:
            return "0"  # All borrower statuses correctly expanded
        if has_credit_score:
            # DEFECT: 1 credit score outside range
            return str(DEFECT_CREDIT_SCORE_RANGE)

        if is_current or (not is_prev):
            return str(SOURCE_TOTAL_D if is_daily else SOURCE_TOTAL_M) if (is_daily or is_moend) else str(SOURCE_TOTAL_D + SOURCE_TOTAL_M)
        elif is_prev:
            return str(PREV_SOURCE_TOTAL_D if is_daily else PREV_SOURCE_TOTAL_M)

    # --- Staging: cad_cb ---
    elif table == "work_schema.cad_cb":
        has_invalid_dsi = "data_src_ind is null" in sql_lower or "data_src_ind not in" in sql_lower
        has_neg_check = "< 0" in sql_lower
        has_stat_check = "ln_stat_cd not in" in sql_lower

        if has_invalid_dsi:
            return "0"
        if has_neg_check:
            return "0"  # No negative amounts
        if has_stat_check:
            # DEFECT: 2 un-expanded status codes
            return str(DEFECT_UNEXPANDED_STATUSES)

        if is_current or (not is_prev):
            return str(SOURCE_CURRENT_D if is_daily else SOURCE_CURRENT_M) if (is_daily or is_moend) else str(SOURCE_CURRENT_D + SOURCE_CURRENT_M)
        elif is_prev:
            return str(PREV_CB_D if is_daily else PREV_CB_D)

    # --- Staging: cad_nccb ---
    elif table == "work_schema.cad_nccb":
        has_invalid_dsi = "data_src_ind is null" in sql_lower or "data_src_ind not in" in sql_lower
        if has_invalid_dsi:
            return "0"

        if is_current or (not is_prev):
            return str(SOURCE_NC_D if is_daily else SOURCE_NC_M) if (is_daily or is_moend) else str(SOURCE_NC_D + SOURCE_NC_M)
        elif is_prev:
            return str(PREV_NCCB_D if is_daily else PREV_NCCB_D)

    # --- Audit: cad_arrg_dim ---
    elif table == "audit.cad_arrg_dim":
        has_invalid_dsi = "data_src_ind is null" in sql_lower or "data_src_ind not in" in sql_lower
        if has_invalid_dsi:
            return "0"

        if is_current or (not is_prev):
            return str(SOURCE_TOTAL_D if is_daily else SOURCE_TOTAL_M) if (is_daily or is_moend) else str(SOURCE_TOTAL_D + SOURCE_TOTAL_M)
        elif is_prev:
            return str(PREV_SOURCE_TOTAL_D if is_daily else PREV_SOURCE_TOTAL_M)

    # --- Audit: cad_actg_unit_bal_fact ---
    elif table == "audit.cad_actg_unit_bal_fact":
        has_invalid_dsi = "data_src_ind is null" in sql_lower or "data_src_ind not in" in sql_lower
        has_pmt_type = "last_pmt_typ_cd not in" in sql_lower

        if has_invalid_dsi:
            return "0"
        if has_pmt_type:
            return "0"  # All payment types expanded correctly

        if is_current or (not is_prev):
            return str(SOURCE_CURRENT_D if is_daily else SOURCE_CURRENT_M) if (is_daily or is_moend) else str(SOURCE_CURRENT_D + SOURCE_CURRENT_M)
        elif is_prev:
            return str(PREV_CB_D if is_daily else PREV_CB_D)

    # --- Audit: cad_nc_actg_unit_bal_fact ---
    elif table == "audit.cad_nc_actg_unit_bal_fact":
        has_invalid_dsi = "data_src_ind is null" in sql_lower or "data_src_ind not in" in sql_lower
        if has_invalid_dsi:
            return "0"

        if is_current or (not is_prev):
            return str(SOURCE_NC_D if is_daily else SOURCE_NC_M) if (is_daily or is_moend) else str(SOURCE_NC_D + SOURCE_NC_M)
        elif is_prev:
            return str(PREV_NCCB_D if is_daily else PREV_NCCB_D)

    return None


def _match_join_query(sql: str) -> str | None:
    """Match JOIN-based and subquery-based queries (transformation, integration checks)."""
    sql_lower = sql.lower().strip()

    # --- TC-TF-001a: date parse failure in cad_id.borr_dob_dt ---
    if "ci.borr_dob_dt is null" in sql_lower and "tc.borr_dob_dt is not null" in sql_lower:
        # DEFECT: 3 date parse failures
        return str(DEFECT_DATE_PARSE_FAILURES)

    # --- TC-TF-001b: date parse failure in cad_cb date columns ---
    for col in ["ln_orig_dt", "ln_mat_dt", "ln_1st_pmt_dt", "ln_nxt_pmt_dt"]:
        if f"cb.{col} is null" in sql_lower and f"tc.{col} is not null" in sql_lower:
            return "0"  # No parse failures for cad_cb date columns

    # --- TC-TF-002b: annual income parse failure ---
    if "borr_ann_incm" in sql_lower and "ci.borr_ann_incm is null" in sql_lower:
        return "0"  # No income parse failures

    # --- TC-IG-002: source->cad_id join orphans ---
    # SQL: FROM default.td_contracts tc LEFT JOIN work_schema.cad_id ci ... AND ci.ln_acct_nbr IS NULL
    if "td_contracts" in sql_lower and "cad_id" in sql_lower and "ci.ln_acct_nbr is null" in sql_lower:
        if "data_src_ind = 'm'" in sql_lower:
            # DEFECT: 2 orphan records in MOEND
            return str(DEFECT_ORPHAN_SOURCE_RECORDS)
        return "0"  # No orphans in DAILY

    # --- TC-IG-003a: cad_cb -> cad_actg_unit_bal_fact join ---
    # SQL: FROM work_schema.cad_cb cb LEFT JOIN audit.cad_actg_unit_bal_fact af ... AND af.ln_acct_nbr IS NULL
    if "cad_cb" in sql_lower and "cad_actg_unit_bal_fact" in sql_lower and "af.ln_acct_nbr is null" in sql_lower:
        return "0"  # No staging->audit orphans

    # --- TC-IG-003b: cad_nccb -> cad_nc_actg_unit_bal_fact join ---
    if "cad_nccb" in sql_lower and "nc_actg_unit_bal_fact" in sql_lower and "nf.ln_acct_nbr is null" in sql_lower:
        return "0"  # No staging->audit orphans

    # --- TC-IG-004: dimension FK integrity ---
    # SQL: FROM <fact_table> f LEFT JOIN audit.cad_arrg_dim d ... AND d.arrg_dim_sk IS NULL
    if "arrg_dim_sk" in sql_lower and "d.arrg_dim_sk is null" in sql_lower:
        return "0"  # No FK violations

    # --- TC-IG-005: duplicate detection (subquery with HAVING) ---
    if "having count(*) > 1" in sql_lower:
        # DEFECT: 1 duplicate in cad_cb DAILY
        if "cad_cb" in sql_lower and "data_src_ind = 'd'" in sql_lower:
            return str(DEFECT_DUPLICATE_CB_RECORDS)
        return "0"

    # --- TC-IG-006: DAILY/MOEND alignment ---
    # SQL: FROM <table> d LEFT JOIN <table> m ... AND m.data_src_ind = 'M' ... AND m.ln_acct_nbr IS NULL
    if "m.ln_acct_nbr is null" in sql_lower and "d.data_src_ind = 'd'" in sql_lower:
        return "0"  # Perfect alignment

    return None


def _match_sum_query(sql: str) -> str | None:
    """Match SUM/aggregate queries."""
    sql_lower = sql.lower().strip()
    is_daily = "data_src_ind = 'd'" in sql_lower
    is_moend = "data_src_ind = 'm'" in sql_lower

    # --- TC-AG-001: SUM(ln_curr_bal) source (with REGEXP_REPLACE) ---
    if "regexp_replace" in sql_lower and "ln_curr_bal" in sql_lower:
        return str(SRC_BALANCE_TOTAL)

    # --- TC-AG-001: SUM(ln_curr_bal) in cad_cb ---
    if "sum(ln_curr_bal)" in sql_lower and "cad_cb" in sql_lower:
        return str(CB_BALANCE)

    # --- TC-AG-001: SUM(ln_curr_bal) in cad_nccb ---
    if "sum(ln_curr_bal)" in sql_lower and "cad_nccb" in sql_lower:
        return str(NCCB_BALANCE)

    # --- TC-AG-002: SUM(ln_orig_amt) ---
    if "sum(ln_orig_amt)" in sql_lower:
        if "cad_cb" in sql_lower:
            return str(CB_ORIG_AMT)
        if "cad_nccb" in sql_lower:
            return str(NCCB_ORIG_AMT)
        if "actg_unit_bal_fact" in sql_lower and "nc" not in sql_lower.split("from")[1]:
            return str(CB_ORIG_AMT)
        if "nc_actg_unit_bal_fact" in sql_lower:
            return str(NCCB_ORIG_AMT)

    # --- TC-AG-003: SUM(ln_escrow_bal) ---
    if "sum(ln_escrow_bal)" in sql_lower:
        return str(CB_ESCROW)

    # --- TC-AG-005: SUM(borr_ann_incm) with REGEXP_REPLACE ---
    if "regexp_replace" in sql_lower and "borr_ann_incm" in sql_lower:
        return str(ANNUAL_INCOME_TOTAL)

    # --- TC-AG-005: SUM(borr_ann_incm) in cad_id ---
    if "sum(borr_ann_incm)" in sql_lower and "cad_id" in sql_lower:
        return str(ANNUAL_INCOME_TOTAL)

    return None


def mock_execute_query_scalar(sql: str, timeout: int | None = None) -> str:
    """
    Mock beeline execute_query_scalar.
    Parses the SQL to determine what synthetic result to return.
    """
    sql_clean = sql.strip()

    # Try join/subquery queries first (they also contain COUNT/SUM keywords)
    result = _match_join_query(sql_clean)
    if result is not None:
        return result

    # Try simple (non-JOIN) count queries
    result = _match_count_query(sql_clean)
    if result is not None:
        return result

    # Try sum/aggregate queries
    result = _match_sum_query(sql_clean)
    if result is not None:
        return result

    # Default: return 0 for unmatched COUNT queries
    if "count(*)" in sql_clean.lower():
        return "0"

    # Default: return 0 for unmatched SUM queries
    if "sum(" in sql_clean.lower():
        return "0"

    logger.warning("Unmatched scalar query: %s", sql_clean[:150])
    return "0"


def mock_execute_query(sql: str, timeout: int | None = None) -> list[dict]:
    """
    Mock beeline execute_query.
    Returns list of row dicts for queries that need full result sets.
    """
    sql_lower = sql.lower().strip()
    is_daily = "data_src_ind = 'd'" in sql_lower
    is_moend = "data_src_ind = 'm'" in sql_lower

    # --- TC-AG-004: Payment component sum query ---
    if "last_pmt_amt" in sql_lower and "last_pmt_prin_amt" in sql_lower:
        if is_moend:
            # DEFECT: component sum doesn't match total for MOEND
            return [{
                "total_pmt": "875000.00",
                "component_sum": "873250.00",  # $1,750 mismatch
            }]
        else:
            # DAILY: components match
            return [{
                "total_pmt": "875000.00",
                "component_sum": "875000.00",
            }]

    # --- TC-RG-003: Status distribution ---
    if "ln_stat_cd" in sql_lower and "group by" in sql_lower:
        if AS_OF_DT_PREV in sql_lower:
            return [
                {"ln_stat_cd": "ACTIVE", "cnt": "280"},
                {"ln_stat_cd": "FORBEARANCE", "cnt": "65"},
            ]
        else:
            return [
                {"ln_stat_cd": "ACTIVE", "cnt": "290"},
                {"ln_stat_cd": "FORBEARANCE", "cnt": "60"},
            ]

    logger.warning("Unmatched query: %s", sql_lower[:150])
    return []


def run_synthetic_validation():
    """
    Execute all validation modules with synthetic data by patching
    beeline_executor functions.
    """
    configure_logging()

    logger.info("=" * 70)
    logger.info("EXECUTING VALIDATION SCRIPTS WITH SYNTHETIC DATA")
    logger.info("=" * 70)
    logger.info("Snapshot date (current):  %s", AS_OF_DT)
    logger.info("Snapshot date (previous): %s", AS_OF_DT_PREV)
    logger.info("")
    logger.info("Synthetic dataset:")
    logger.info("  Source contracts:     %d (DAILY) / %d (MOEND)", SOURCE_TOTAL_D, SOURCE_TOTAL_M)
    logger.info("  Current (ACT/FRB):   %d", SOURCE_CURRENT_D)
    logger.info("  Non-current (CLO/DFT): %d", SOURCE_NC_D)
    logger.info("")
    logger.info("Injected defects:")
    logger.info("  1. %d date parse failures in cad_id.borr_dob_dt", DEFECT_DATE_PARSE_FAILURES)
    logger.info("  2. %d un-expanded loan statuses in cad_cb", DEFECT_UNEXPANDED_STATUSES)
    logger.info("  3. %d credit score outside FICO range", DEFECT_CREDIT_SCORE_RANGE)
    logger.info("  4. Payment component sum mismatch (MOEND)")
    logger.info("  5. %d orphan source->cad_id records (MOEND)", DEFECT_ORPHAN_SOURCE_RECORDS)
    logger.info("  6. %d duplicate in cad_cb (DAILY)", DEFECT_DUPLICATE_CB_RECORDS)
    logger.info("=" * 70)

    start_time = time.time()
    all_results = []

    # Patch beeline_executor functions for all test modules
    with patch("test_row_counts.execute_query_scalar", side_effect=mock_execute_query_scalar), \
         patch("test_transformations.execute_query_scalar", side_effect=mock_execute_query_scalar), \
         patch("test_transformations.execute_query", side_effect=mock_execute_query), \
         patch("test_aggregates.execute_query_scalar", side_effect=mock_execute_query_scalar), \
         patch("test_aggregates.execute_query", side_effect=mock_execute_query), \
         patch("test_regression.execute_query_scalar", side_effect=mock_execute_query_scalar), \
         patch("test_regression.execute_query", side_effect=mock_execute_query), \
         patch("test_integration.execute_query_scalar", side_effect=mock_execute_query_scalar), \
         patch("test_integration.execute_query", side_effect=mock_execute_query):

        # Run each category
        categories = [
            ("row_count", lambda: test_row_counts.run_all(AS_OF_DT)),
            ("transformation", lambda: test_transformations.run_all(AS_OF_DT)),
            ("aggregate", lambda: test_aggregates.run_all(AS_OF_DT)),
            ("regression", lambda: test_regression.run_all(AS_OF_DT, AS_OF_DT_PREV)),
            ("integration", lambda: test_integration.run_all(AS_OF_DT)),
        ]

        for cat_name, cat_fn in categories:
            logger.info("")
            logger.info("-" * 50)
            logger.info("Running category: %s", cat_name)
            logger.info("-" * 50)

            cat_results = cat_fn()
            all_results.extend(cat_results)

            cat_passed = sum(1 for r in cat_results if r.get("passed"))
            cat_failed = len(cat_results) - cat_passed
            logger.info(
                "  %s: %d/%d passed (%d failed)",
                cat_name, cat_passed, len(cat_results), cat_failed,
            )

    elapsed = time.time() - start_time
    total = len(all_results)
    passed = sum(1 for r in all_results if r.get("passed"))
    failed = total - passed

    logger.info("")
    logger.info("=" * 70)
    logger.info(
        "OVERALL: %d/%d passed, %d failed (%.1fs)",
        passed, total, failed, elapsed,
    )
    logger.info("=" * 70)

    # Generate reports
    run_params = {
        "as_of_dt": AS_OF_DT,
        "as_of_dt_previous": AS_OF_DT_PREV,
        "execution_time": f"{elapsed:.1f}s",
        "jdbc_url": "SYNTHETIC_DATA (no live Hive connection)",
        "categories": ["row_count", "transformation", "aggregate", "regression", "integration"],
        "mode": "synthetic_data_simulation",
        "injected_defects": [
            f"{DEFECT_DATE_PARSE_FAILURES} date parse failures (borr_dob_dt)",
            f"{DEFECT_UNEXPANDED_STATUSES} un-expanded loan statuses (cad_cb)",
            f"{DEFECT_CREDIT_SCORE_RANGE} credit score outside FICO range",
            "Payment component sum mismatch (MOEND)",
            f"{DEFECT_ORPHAN_SOURCE_RECORDS} orphan source->cad_id records (MOEND)",
            f"{DEFECT_DUPLICATE_CB_RECORDS} duplicate in cad_cb (DAILY)",
        ],
    }

    # Generate all 3 report formats
    text_path = report_generator.generate_text_report(all_results, run_params)
    html_path = report_generator.generate_html_report(all_results, run_params)
    json_path = report_generator.generate_json_report(all_results, run_params)

    logger.info("")
    logger.info("Reports generated:")
    logger.info("  Text: %s", text_path)
    logger.info("  HTML: %s", html_path)
    logger.info("  JSON: %s", json_path)

    # Print summary to stdout for quick review
    print_summary(all_results)

    return all_results, text_path, html_path, json_path


def print_summary(results: list[dict]):
    """Print a concise summary of passed/failed tests to stdout."""
    print("\n")
    print("=" * 80)
    print("TEST EXECUTION SUMMARY")
    print("=" * 80)

    total = len(results)
    passed_results = [r for r in results if r.get("passed")]
    failed_results = [r for r in results if not r.get("passed")]

    print(f"\nTotal: {total} | Passed: {len(passed_results)} | Failed: {len(failed_results)}")
    print(f"Pass Rate: {len(passed_results)/total*100:.1f}%\n")

    # Category breakdown
    categories = {}
    for r in results:
        cat = r.get("category", "unknown")
        if cat not in categories:
            categories[cat] = {"passed": 0, "failed": 0}
        if r.get("passed"):
            categories[cat]["passed"] += 1
        else:
            categories[cat]["failed"] += 1

    print("-" * 80)
    print(f"{'Category':<25} {'Passed':>8} {'Failed':>8} {'Status':>10}")
    print("-" * 80)
    for cat in sorted(categories.keys()):
        c = categories[cat]
        status = "PASS" if c["failed"] == 0 else "FAIL"
        print(f"  {cat:<23} {c['passed']:>8} {c['failed']:>8} {status:>10}")
    print("-" * 80)

    # Passed tests
    if passed_results:
        print(f"\nPASSED VALIDATIONS ({len(passed_results)}):")
        print("-" * 80)
        for r in passed_results:
            print(f"  [PASS] {r['test_id']:<12} {r['test_name']}")

    # Failed tests with details
    if failed_results:
        print(f"\nFAILED VALIDATIONS ({len(failed_results)}):")
        print("-" * 80)
        for r in failed_results:
            print(f"  [FAIL] {r['test_id']:<12} {r['test_name']}")
            print(f"         Expected: {r.get('expected', '?')}")
            print(f"         Actual:   {r.get('actual', '?')}")
            print(f"         Message:  {r.get('message', '')}")
            print()

    # Sample defect scenarios
    print("=" * 80)
    print("SAMPLE DEFECT SCENARIOS (injected for demonstration)")
    print("=" * 80)
    defect_scenarios = [
        {
            "defect": "Date Parse Failure",
            "table": "work_schema.cad_id",
            "column": "borr_dob_dt",
            "test_id": "TC-TF-001a",
            "description": (
                "3 records where source borr_dob_dt had a valid MM/DD/YYYY value "
                "but the staging table has NULL. Indicates the date parsing logic "
                "failed to handle edge-case formats (e.g. single-digit month/day)."
            ),
            "impact": "Borrower age calculations and regulatory reporting will be inaccurate.",
            "remediation": "Fix date parser to handle M/D/YYYY and MM/DD/YYYY variants.",
        },
        {
            "defect": "Un-expanded Status Code",
            "table": "work_schema.cad_cb",
            "column": "ln_stat_cd",
            "test_id": "TC-TF-003a",
            "description": (
                "2 records still contain raw CDW status codes (e.g. 'ACT') instead of "
                "the expanded form ('ACTIVE'). The status expansion CASE statement "
                "may have missed a code or has a typo."
            ),
            "impact": "Downstream reports filtering on 'ACTIVE' will miss these 2 contracts.",
            "remediation": "Add missing code to the CASE/WHEN expansion in the ETL transform.",
        },
        {
            "defect": "Credit Score Out of Range",
            "table": "work_schema.cad_id",
            "column": "borr_crdt_scr",
            "test_id": "TC-TF-004",
            "description": (
                "1 record has a credit score outside the valid FICO range (300-850). "
                "This could be a parse error or source data quality issue."
            ),
            "impact": "Risk model scoring and underwriting decisions may be affected.",
            "remediation": "Add range validation in ETL; flag or quarantine out-of-range values.",
        },
        {
            "defect": "Payment Component Sum Mismatch",
            "table": "audit.cad_actg_unit_bal_fact",
            "column": "last_pmt_amt vs components",
            "test_id": "TC-AG-004",
            "description": (
                "For MOEND snapshot, total payment amount ($875,000.00) does not equal "
                "the sum of principal + interest + escrow + late_fee ($873,250.00). "
                "Delta of $1,750.00 indicates rounding or missing component."
            ),
            "impact": "Financial reconciliation will not balance; audit finding risk.",
            "remediation": "Review payment component extraction logic; check for rounding mode.",
        },
        {
            "defect": "Orphan Source Records",
            "table": "work_schema.cad_id",
            "column": "ln_acct_nbr (join)",
            "test_id": "TC-IG-002",
            "description": (
                "2 source records in td_contracts (MOEND) have no matching record "
                "in cad_id. These contracts were loaded but not staged."
            ),
            "impact": "2 contracts are missing from all downstream tables and reports.",
            "remediation": "Investigate ETL staging step; check for filter conditions dropping records.",
        },
        {
            "defect": "Duplicate Record",
            "table": "work_schema.cad_cb",
            "column": "ln_acct_nbr + data_src_ind",
            "test_id": "TC-IG-005b",
            "description": (
                "1 duplicate record found in cad_cb for DAILY snapshot. "
                "The same contract appears twice with the same data_src_ind."
            ),
            "impact": "Double-counting in balance aggregations; inflated portfolio metrics.",
            "remediation": "Add DISTINCT or dedup logic to the staging INSERT statement.",
        },
    ]

    for i, d in enumerate(defect_scenarios, 1):
        print(f"\n  Defect #{i}: {d['defect']}")
        print(f"  Test ID:     {d['test_id']}")
        print(f"  Table:       {d['table']}")
        print(f"  Column:      {d['column']}")
        print(f"  Description: {d['description']}")
        print(f"  Impact:      {d['impact']}")
        print(f"  Remediation: {d['remediation']}")

    print("\n" + "=" * 80)


def configure_logging():
    """Set up logging for synthetic execution."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


if __name__ == "__main__":
    results, text_path, html_path, json_path = run_synthetic_validation()
    total = len(results)
    failed = sum(1 for r in results if not r.get("passed"))
    sys.exit(0 if failed == 0 else 1)
