"""
Row count validation test cases.
Verifies record counts across source, staging, and audit layers
for both DAILY and MOEND snapshots, ensuring no data loss or
unexpected duplication during the ETL pipeline.
"""

import logging

from beeline_executor import execute_query_scalar
from config import (
    CURRENT_STATUS_CODES,
    DATA_SRC_IND_DAILY,
    DATA_SRC_IND_MOEND,
    NON_CURRENT_STATUS_CODES,
    TABLES,
)

logger = logging.getLogger(__name__)


def _count_query(fq_table: str, partition_val: str, where_extra: str = "") -> str:
    """Build a COUNT(*) query for a given table, partition, and optional filter."""
    sql = (
        f"SELECT COUNT(*) AS cnt "
        f"FROM {fq_table} "
        f"WHERE as_of_dt = '{partition_val}'"
    )
    if where_extra:
        sql += f" AND {where_extra}"
    return sql


def test_table_not_empty(as_of_dt: str) -> list[dict]:
    """
    TC-RC-001: Verify every table has at least one record for the given as_of_dt.
    Runs against all 7 tables.
    """
    results = []
    for fq_name, meta in TABLES.items():
        sql = _count_query(fq_name, as_of_dt)
        try:
            count = int(execute_query_scalar(sql))
            passed = count > 0
            results.append({
                "test_id": "TC-RC-001",
                "test_name": f"Table not empty: {fq_name}",
                "category": "row_count",
                "sql": sql,
                "expected": ">0",
                "actual": count,
                "passed": passed,
                "message": f"{fq_name} has {count} rows" if passed
                    else f"{fq_name} is EMPTY for as_of_dt={as_of_dt}",
            })
        except Exception as exc:
            results.append({
                "test_id": "TC-RC-001",
                "test_name": f"Table not empty: {fq_name}",
                "category": "row_count",
                "sql": sql,
                "expected": ">0",
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })
    return results


def test_source_to_staging_counts(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-RC-002: Source -> staging row count consistency.
    For a given data_src_ind:
      - td_contracts total should equal cad_id total (1:1 borrower extraction)
      - td_contracts with current status -> cad_cb count
      - td_contracts with non-current status -> cad_nccb count
      - cad_cb + cad_nccb should equal td_contracts total
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    # Total source count
    src_sql = _count_query("default.td_contracts", as_of_dt, dsi_filter)
    # Staging: cad_id should match source 1:1
    id_sql = _count_query("work_schema.cad_id", as_of_dt, dsi_filter)
    # Staging: current balance (ACT, FRB)
    current_codes = ",".join(f"'{c}'" for c in CURRENT_STATUS_CODES)
    src_current_sql = _count_query(
        "default.td_contracts", as_of_dt,
        f"{dsi_filter} AND ln_stat_cd IN ({current_codes})"
    )
    cb_sql = _count_query("work_schema.cad_cb", as_of_dt, dsi_filter)
    # Staging: non-current balance (CLO, DFT)
    nc_codes = ",".join(f"'{c}'" for c in NON_CURRENT_STATUS_CODES)
    src_nc_sql = _count_query(
        "default.td_contracts", as_of_dt,
        f"{dsi_filter} AND ln_stat_cd IN ({nc_codes})"
    )
    nccb_sql = _count_query("work_schema.cad_nccb", as_of_dt, dsi_filter)

    try:
        src_count = int(execute_query_scalar(src_sql))
        id_count = int(execute_query_scalar(id_sql))
        src_current = int(execute_query_scalar(src_current_sql))
        cb_count = int(execute_query_scalar(cb_sql))
        src_nc = int(execute_query_scalar(src_nc_sql))
        nccb_count = int(execute_query_scalar(nccb_sql))

        # Check 1: source total == cad_id total
        passed_id = src_count == id_count
        results.append({
            "test_id": "TC-RC-002a",
            "test_name": f"Source->cad_id count match ({data_src_ind})",
            "category": "row_count",
            "sql": f"{src_sql} vs {id_sql}",
            "expected": src_count,
            "actual": id_count,
            "passed": passed_id,
            "message": f"Source={src_count}, cad_id={id_count}",
        })

        # Check 2: source current == cad_cb
        passed_cb = src_current == cb_count
        results.append({
            "test_id": "TC-RC-002b",
            "test_name": f"Source current->cad_cb count match ({data_src_ind})",
            "category": "row_count",
            "sql": f"{src_current_sql} vs {cb_sql}",
            "expected": src_current,
            "actual": cb_count,
            "passed": passed_cb,
            "message": f"Source current={src_current}, cad_cb={cb_count}",
        })

        # Check 3: source non-current == cad_nccb
        passed_nccb = src_nc == nccb_count
        results.append({
            "test_id": "TC-RC-002c",
            "test_name": f"Source non-current->cad_nccb count match ({data_src_ind})",
            "category": "row_count",
            "sql": f"{src_nc_sql} vs {nccb_sql}",
            "expected": src_nc,
            "actual": nccb_count,
            "passed": passed_nccb,
            "message": f"Source non-current={src_nc}, cad_nccb={nccb_count}",
        })

        # Check 4: cad_cb + cad_nccb == source total
        staging_total = cb_count + nccb_count
        passed_total = staging_total == src_count
        results.append({
            "test_id": "TC-RC-002d",
            "test_name": f"cad_cb+cad_nccb == source total ({data_src_ind})",
            "category": "row_count",
            "sql": f"{cb_sql} + {nccb_sql} vs {src_sql}",
            "expected": src_count,
            "actual": staging_total,
            "passed": passed_total,
            "message": f"cb+nccb={staging_total}, source={src_count}",
        })

    except Exception as exc:
        results.append({
            "test_id": "TC-RC-002",
            "test_name": f"Source->staging counts ({data_src_ind})",
            "category": "row_count",
            "sql": "multiple",
            "expected": "counts match",
            "actual": "ERROR",
            "passed": False,
            "message": str(exc),
        })

    return results


def test_staging_to_audit_counts(as_of_dt: str, data_src_ind: str) -> list[dict]:
    """
    TC-RC-003: Staging -> audit row count consistency.
    For a given data_src_ind:
      - cad_cb count should equal cad_actg_unit_bal_fact count
      - cad_nccb count should equal cad_nc_actg_unit_bal_fact count
      - cad_id count should match cad_arrg_dim count (one dim row per contract)
    """
    results = []
    dsi_filter = f"data_src_ind = '{data_src_ind}'"

    pairs = [
        ("TC-RC-003a", "work_schema.cad_cb", "audit.cad_actg_unit_bal_fact",
         "cad_cb -> actg_unit_bal_fact"),
        ("TC-RC-003b", "work_schema.cad_nccb", "audit.cad_nc_actg_unit_bal_fact",
         "cad_nccb -> nc_actg_unit_bal_fact"),
        ("TC-RC-003c", "work_schema.cad_id", "audit.cad_arrg_dim",
         "cad_id -> arrg_dim"),
    ]

    for test_id, staging_tbl, audit_tbl, label in pairs:
        stg_sql = _count_query(staging_tbl, as_of_dt, dsi_filter)
        aud_sql = _count_query(audit_tbl, as_of_dt, dsi_filter)
        try:
            stg_count = int(execute_query_scalar(stg_sql))
            aud_count = int(execute_query_scalar(aud_sql))
            passed = stg_count == aud_count
            results.append({
                "test_id": test_id,
                "test_name": f"{label} count match ({data_src_ind})",
                "category": "row_count",
                "sql": f"{stg_sql} vs {aud_sql}",
                "expected": stg_count,
                "actual": aud_count,
                "passed": passed,
                "message": f"staging={stg_count}, audit={aud_count}",
            })
        except Exception as exc:
            results.append({
                "test_id": test_id,
                "test_name": f"{label} count match ({data_src_ind})",
                "category": "row_count",
                "sql": f"{stg_sql} vs {aud_sql}",
                "expected": "match",
                "actual": "ERROR",
                "passed": False,
                "message": str(exc),
            })

    return results


def test_data_src_ind_completeness(as_of_dt: str) -> list[dict]:
    """
    TC-RC-004: Verify both DAILY and MOEND records exist for each table
    on the given as_of_dt (when it is a month-end date).
    """
    results = []
    for fq_name in TABLES:
        for dsi, label in [(DATA_SRC_IND_DAILY, "DAILY"), (DATA_SRC_IND_MOEND, "MOEND")]:
            sql = _count_query(fq_name, as_of_dt, f"data_src_ind = '{dsi}'")
            try:
                count = int(execute_query_scalar(sql))
                passed = count > 0
                results.append({
                    "test_id": "TC-RC-004",
                    "test_name": f"data_src_ind={label} present: {fq_name}",
                    "category": "row_count",
                    "sql": sql,
                    "expected": ">0",
                    "actual": count,
                    "passed": passed,
                    "message": f"{fq_name} {label}: {count} rows",
                })
            except Exception as exc:
                results.append({
                    "test_id": "TC-RC-004",
                    "test_name": f"data_src_ind={label} present: {fq_name}",
                    "category": "row_count",
                    "sql": sql,
                    "expected": ">0",
                    "actual": "ERROR",
                    "passed": False,
                    "message": str(exc),
                })
    return results


def run_all(as_of_dt: str) -> list[dict]:
    """Run all row count test cases and return combined results."""
    logger.info("=== Running row count validations for as_of_dt=%s ===", as_of_dt)
    results = []
    results.extend(test_table_not_empty(as_of_dt))
    # Run source->staging and staging->audit for both DAILY and MOEND
    for dsi in [DATA_SRC_IND_DAILY, DATA_SRC_IND_MOEND]:
        results.extend(test_source_to_staging_counts(as_of_dt, dsi))
        results.extend(test_staging_to_audit_counts(as_of_dt, dsi))
    results.extend(test_data_src_ind_completeness(as_of_dt))
    return results
