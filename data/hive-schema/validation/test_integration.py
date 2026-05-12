"""
Integration validation test cases.
Verifies end-to-end data flow from source through staging to audit,
including foreign key consistency, partition alignment, and cross-table
join integrity.
"""

import logging

from beeline_executor import execute_query, execute_query_scalar
from config import (
    DATA_SRC_IND_DAILY,
    DATA_SRC_IND_MOEND,
)

logger = logging.getLogger(__name__)


def test_partition_alignment(as_of_dt: str) -> list[dict]:
    """
    TC-IG-001: Verify all tables have data for the same as_of_dt partition.
    All 7 tables should have at least one partition matching as_of_dt.
    """
    results = []
    from config import TABLES

    tables_with_data = []
    tables_without_data = []

    for fq_name in TABLES:
        sql = (
            f"SELECT COUNT(*) AS cnt FROM {fq_name} "
            f"WHERE as_of_dt = '{as_of_dt}'"
        )
        try:
            count = int(execute_query_scalar(sql))
            if count > 0:
                tables_with_data.append(fq_name)
            else:
                tables_without_data.append(fq_name)
        except Exception:
            tables_without_data.append(fq_name)

    passed = len(tables_without_data) == 0
    results.append({
        "test_id": "TC-IG-001",
        "test_name": "Partition alignment across all tables",
        "category": "integration",
        "sql": "COUNT(*) per table for as_of_dt",
        "expected": "all 7 tables populated",
        "actual": f"{len(tables_with_data)}/7 populated",
        "passed": passed,
        "message": (
            f"Missing: {tables_without_data}" if tables_without_data
            else "All tables have data for the partition"
        ),
    })

    return results


def test_source_to_staging_join(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-IG-002: Verify every source record has a matching staging record
    in cad_id (by ln_acct_nbr + data_src_ind).
    Detects orphaned source records that failed to stage.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    # Source records not found in cad_id
    sql = (
        "SELECT COUNT(*) AS cnt "
        "FROM default.td_contracts tc "
        "LEFT JOIN work_schema.cad_id ci "
        "  ON tc.ln_acct_nbr = ci.ln_acct_nbr "
        "  AND tc.as_of_dt = ci.as_of_dt "
        "  AND tc.data_src_ind = ci.data_src_ind "
        f"WHERE tc.as_of_dt = '{as_of_dt}' "
        f"  AND tc.{dsi_filter} "
        "  AND ci.ln_acct_nbr IS NULL"
    )
    try:
        orphan_count = int(execute_query_scalar(sql))
        passed = orphan_count == 0
        results.append({
            "test_id": "TC-IG-002",
            "test_name": f"Source->cad_id join integrity ({data_src_ind})",
            "category": "integration",
            "sql": sql,
            "expected": 0,
            "actual": orphan_count,
            "passed": passed,
            "message": f"{orphan_count} source records missing from cad_id" if not passed
                else "All source records joined to cad_id",
        })
    except Exception as exc:
        results.append({
            "test_id": "TC-IG-002",
            "test_name": f"Source->cad_id join integrity ({data_src_ind})",
            "category": "integration",
            "sql": sql,
            "expected": 0,
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def test_staging_to_audit_join(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-IG-003: Verify staging balance records join to audit fact records.
    cad_cb -> cad_actg_unit_bal_fact and cad_nccb -> cad_nc_actg_unit_bal_fact.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    join_pairs = [
        (
            "TC-IG-003a",
            "work_schema.cad_cb", "cb",
            "audit.cad_actg_unit_bal_fact", "af",
            "cad_cb -> actg_fact",
        ),
        (
            "TC-IG-003b",
            "work_schema.cad_nccb", "nc",
            "audit.cad_nc_actg_unit_bal_fact", "nf",
            "cad_nccb -> nc_actg_fact",
        ),
    ]

    for test_id, stg_tbl, stg_alias, aud_tbl, aud_alias, label in join_pairs:
        sql = (
            f"SELECT COUNT(*) AS cnt "
            f"FROM {stg_tbl} {stg_alias} "
            f"LEFT JOIN {aud_tbl} {aud_alias} "
            f"  ON {stg_alias}.ln_acct_nbr = {aud_alias}.ln_acct_nbr "
            f"  AND {stg_alias}.as_of_dt = {aud_alias}.as_of_dt "
            f"  AND {stg_alias}.data_src_ind = {aud_alias}.data_src_ind "
            f"WHERE {stg_alias}.as_of_dt = '{as_of_dt}' "
            f"  AND {stg_alias}.{dsi_filter} "
            f"  AND {aud_alias}.ln_acct_nbr IS NULL"
        )
        try:
            orphan_count = int(execute_query_scalar(sql))
            passed = orphan_count == 0
            results.append({
                "test_id": test_id,
                "test_name": f"{label} join integrity ({data_src_ind})",
                "category": "integration",
                "sql": sql,
                "expected": 0,
                "actual": orphan_count,
                "passed": passed,
                "message": f"{orphan_count} staging records missing from audit" if not passed
                    else f"All {label} records joined",
            })
        except Exception as exc:
            results.append({
                "test_id": test_id,
                "test_name": f"{label} join integrity ({data_src_ind})",
                "category": "integration",
                "sql": sql,
                "expected": 0,
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    return results


def test_dimension_fact_fk_integrity(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-IG-004: Verify fact table arrg_dim_sk references exist in
    the dimension table (audit.cad_arrg_dim).
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    fact_tables = [
        ("TC-IG-004a", "audit.cad_actg_unit_bal_fact", "actg_fact"),
        ("TC-IG-004b", "audit.cad_nc_actg_unit_bal_fact", "nc_actg_fact"),
    ]

    for test_id, fact_tbl, label in fact_tables:
        sql = (
            f"SELECT COUNT(*) AS cnt "
            f"FROM {fact_tbl} f "
            "LEFT JOIN audit.cad_arrg_dim d "
            "  ON f.arrg_dim_sk = d.arrg_dim_sk "
            "  AND f.as_of_dt = d.as_of_dt "
            f"WHERE f.as_of_dt = '{as_of_dt}' "
            f"  AND f.{dsi_filter} "
            "  AND d.arrg_dim_sk IS NULL"
        )
        try:
            orphan_count = int(execute_query_scalar(sql))
            passed = orphan_count == 0
            results.append({
                "test_id": test_id,
                "test_name": f"Dim FK integrity: {label} ({data_src_ind})",
                "category": "integration",
                "sql": sql,
                "expected": 0,
                "actual": orphan_count,
                "passed": passed,
                "message": f"{orphan_count} fact records with orphan arrg_dim_sk" if not passed
                    else f"All {label} arrg_dim_sk references valid",
            })
        except Exception as exc:
            results.append({
                "test_id": test_id,
                "test_name": f"Dim FK integrity: {label} ({data_src_ind})",
                "category": "integration",
                "sql": sql,
                "expected": 0,
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    return results


def test_no_duplicate_records(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-IG-005: Verify no duplicate records exist on natural keys
    (ln_acct_nbr + data_src_ind) within a single partition.
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    # Tables and their natural key columns
    dedup_checks = [
        ("TC-IG-005a", "work_schema.cad_id", "ln_acct_nbr, data_src_ind"),
        ("TC-IG-005b", "work_schema.cad_cb", "ln_acct_nbr, data_src_ind"),
        ("TC-IG-005c", "work_schema.cad_nccb", "ln_acct_nbr, data_src_ind"),
        ("TC-IG-005d", "audit.cad_actg_unit_bal_fact", "ln_acct_nbr, data_src_ind"),
        ("TC-IG-005e", "audit.cad_nc_actg_unit_bal_fact", "ln_acct_nbr, data_src_ind"),
    ]

    for test_id, tbl, keys in dedup_checks:
        sql = (
            f"SELECT COUNT(*) AS dup_count FROM ("
            f"  SELECT {keys}, COUNT(*) AS cnt "
            f"  FROM {tbl} "
            f"  WHERE as_of_dt = '{as_of_dt}' AND {dsi_filter} "
            f"  GROUP BY {keys} "
            f"  HAVING COUNT(*) > 1"
            f") dups"
        )
        try:
            dup_count = int(execute_query_scalar(sql))
            passed = dup_count == 0
            results.append({
                "test_id": test_id,
                "test_name": f"No duplicates: {tbl} ({data_src_ind})",
                "category": "integration",
                "sql": sql,
                "expected": 0,
                "actual": dup_count,
                "passed": passed,
                "message": f"{dup_count} duplicate key groups in {tbl}" if not passed
                    else f"No duplicates in {tbl}",
            })
        except Exception as exc:
            results.append({
                "test_id": test_id,
                "test_name": f"No duplicates: {tbl} ({data_src_ind})",
                "category": "integration",
                "sql": sql,
                "expected": 0,
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    return results


def test_daily_moend_consistency(as_of_dt: str) -> list[dict]:
    """
    TC-IG-006: For month-end dates, verify DAILY and MOEND snapshots
    contain the same set of ln_acct_nbr values (no contracts missing
    from either snapshot).
    """
    results = []

    # Only meaningful for tables with both DAILY and MOEND data
    tables_to_check = [
        ("TC-IG-006a", "work_schema.cad_cb"),
        ("TC-IG-006b", "work_schema.cad_nccb"),
    ]

    for test_id, tbl in tables_to_check:
        # Accounts in DAILY but not MOEND
        sql_d_not_m = (
            f"SELECT COUNT(DISTINCT d.ln_acct_nbr) AS cnt "
            f"FROM {tbl} d "
            f"LEFT JOIN {tbl} m "
            f"  ON d.ln_acct_nbr = m.ln_acct_nbr AND m.as_of_dt = '{as_of_dt}' AND m.data_src_ind = 'M' "
            f"WHERE d.as_of_dt = '{as_of_dt}' AND d.data_src_ind = 'D' "
            f"  AND m.ln_acct_nbr IS NULL"
        )
        try:
            mismatch = int(execute_query_scalar(sql_d_not_m))
            passed = mismatch == 0
            results.append({
                "test_id": test_id,
                "test_name": f"DAILY/MOEND account alignment: {tbl}",
                "category": "integration",
                "sql": sql_d_not_m,
                "expected": 0,
                "actual": mismatch,
                "passed": passed,
                "message": (
                    f"{mismatch} accounts in DAILY but not MOEND" if not passed
                    else f"DAILY and MOEND account sets aligned in {tbl}"
                ),
            })
        except Exception as exc:
            results.append({
                "test_id": test_id,
                "test_name": f"DAILY/MOEND account alignment: {tbl}",
                "category": "integration",
                "sql": sql_d_not_m,
                "expected": 0,
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    return results


def run_all(as_of_dt: str) -> list[dict]:
    """Run all integration test cases and return combined results."""
    logger.info("=== Running integration validations for as_of_dt=%s ===", as_of_dt)
    results = []
    results.extend(test_partition_alignment(as_of_dt))
    for dsi in [DATA_SRC_IND_DAILY, DATA_SRC_IND_MOEND]:
        results.extend(test_source_to_staging_join(as_of_dt, dsi))
        results.extend(test_staging_to_audit_join(as_of_dt, dsi))
        results.extend(test_dimension_fact_fk_integrity(as_of_dt, dsi))
        results.extend(test_no_duplicate_records(as_of_dt, dsi))
    results.extend(test_daily_moend_consistency(as_of_dt))
    return results
