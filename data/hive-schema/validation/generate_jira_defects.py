#!/usr/bin/env python3
"""
Generate Jira DEFECT drafts from validation report results.
Reads the JSON validation report, extracts all failed test cases,
and produces structured Jira defect tickets in JSON and XLSX formats.

This is a Jira simulation — no actual Jira integration is performed.
Output files:
  - defects_jira_format.json  (structured JSON array of defect tickets)
  - defects_jira_format.xlsx  (tabular Excel workbook for stakeholder review)
"""

import json
import os
import sys
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
VALIDATION_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(VALIDATION_DIR, "reports")

# ---------------------------------------------------------------------------
# Jira project and issue metadata
# ---------------------------------------------------------------------------
JIRA_PROJECT = "CAD"
ISSUE_TYPE = "Bug"
REPORTER = "Validation Automation"
ENVIRONMENT = "Hive / Beeline JDBC — Synthetic Data Simulation"
SNAPSHOT_DATE = "2024-01-31"

# ---------------------------------------------------------------------------
# Defect definitions — one per failed validation
# Each defect maps a test_id to full Jira-style ticket content.
# ---------------------------------------------------------------------------
DEFECT_DEFINITIONS = {
    "TC-TF-001a": {
        "summary": "[CAD] Date Parsing Failure — borr_dob_dt contains NULL for 3 records in cad_id",
        "description": (
            "During the ETL transformation from source (default.td_contracts) to staging "
            "(work_schema.cad_id), the borrower date of birth column (borr_dob_dt) failed "
            "to parse for 3 records. The source table contains valid MM/DD/YYYY string values "
            "for these records, but the staging table has NULL after the STRING-to-DATE conversion.\n\n"
            "This indicates the date parsing logic (expected format: MM/DD/YYYY) does not handle "
            "edge-case formats such as single-digit month/day (e.g., 1/5/1990 vs 01/05/1990) "
            "or other non-standard date representations present in the legacy CDW data."
        ),
        "steps_to_reproduce": (
            "1. Load synthetic data into default.td_contracts for as_of_dt = '2024-01-31'\n"
            "2. Execute the ETL pipeline to populate work_schema.cad_id\n"
            "3. Run validation query:\n"
            "   SELECT COUNT(*) FROM default.td_contracts tc\n"
            "   JOIN work_schema.cad_id ci ON tc.ln_acct_nbr = ci.ln_acct_nbr\n"
            "     AND tc.as_of_dt = ci.as_of_dt\n"
            "   WHERE tc.as_of_dt = '2024-01-31'\n"
            "     AND tc.borr_dob_dt IS NOT NULL\n"
            "     AND TRIM(tc.borr_dob_dt) != ''\n"
            "     AND ci.borr_dob_dt IS NULL\n"
            "4. Observe: query returns 3 (expected: 0)"
        ),
        "expected_result": "0 records with NULL borr_dob_dt in cad_id when source has a valid date string.",
        "actual_result": "3 records have NULL borr_dob_dt in cad_id despite non-empty source values.",
        "priority": "High",
        "severity": "Major",
        "linked_user_story": (
            "US-CAD-101: As a data engineer, I need all borrower date fields "
            "(borr_dob_dt) correctly parsed from MM/DD/YYYY strings to DATE type "
            "during the source-to-staging transformation, so that downstream "
            "age calculations and regulatory reporting are accurate."
        ),
        "component": "ETL — Date Transformation",
        "labels": ["data-quality", "date-parsing", "staging-layer"],
    },
    "TC-TF-003a": {
        "summary": "[CAD] Un-expanded Loan Status Codes — 2 records in cad_cb retain raw CDW codes",
        "description": (
            "The loan status code expansion transformation is incomplete. 2 records in "
            "work_schema.cad_cb still contain raw CDW abbreviations (e.g., 'ACT') instead of "
            "the expanded values defined in the mapping document ('ACTIVE', 'CLOSED', "
            "'DEFAULT', 'FORBEARANCE').\n\n"
            "The column_mappings.md specifies that ln_stat_cd must be expanded via:\n"
            "  ACT → ACTIVE, CLO → CLOSED, DFT → DEFAULT, FRB → FORBEARANCE\n\n"
            "The CASE/WHEN statement in the ETL transform may have a missing branch or "
            "a typo in one of the code values."
        ),
        "steps_to_reproduce": (
            "1. Load synthetic data into default.td_contracts for as_of_dt = '2024-01-31'\n"
            "2. Execute the ETL pipeline to populate work_schema.cad_cb\n"
            "3. Run validation query:\n"
            "   SELECT COUNT(*) FROM work_schema.cad_cb\n"
            "   WHERE as_of_dt = '2024-01-31'\n"
            "     AND ln_stat_cd NOT IN ('ACTIVE','CLOSED','DEFAULT','FORBEARANCE')\n"
            "4. Observe: query returns 2 (expected: 0)"
        ),
        "expected_result": "0 records with un-expanded status codes. All ln_stat_cd values should be one of: ACTIVE, CLOSED, DEFAULT, FORBEARANCE.",
        "actual_result": "2 records contain raw CDW status codes that were not expanded during transformation.",
        "priority": "High",
        "severity": "Major",
        "linked_user_story": (
            "US-CAD-103: As a data analyst, I need all status code columns expanded from "
            "CDW abbreviations to full descriptive values (per column_mappings.md) so that "
            "reports and filters use consistent, human-readable status labels."
        ),
        "component": "ETL — Status Code Expansion",
        "labels": ["data-quality", "status-codes", "staging-layer"],
    },
    "TC-TF-004": {
        "summary": "[CAD] Credit Score Out of FICO Range — 1 record in cad_id has borr_crdt_scr outside 300–850",
        "description": (
            "1 record in work_schema.cad_id has a credit score (borr_crdt_scr) that falls "
            "outside the valid FICO range of 300–850. The source column in td_contracts stores "
            "credit scores as STRING; the ETL converts them to INT. This out-of-range value "
            "could be caused by:\n"
            "  - A malformed string in the source (e.g., '0', '999', negative, or non-numeric)\n"
            "  - A parse error that produced an incorrect integer\n"
            "  - A genuine source data quality issue from the legacy CDW\n\n"
            "Credit scores outside the 300–850 range should be flagged, quarantined, or "
            "defaulted to NULL to prevent invalid inputs to risk models."
        ),
        "steps_to_reproduce": (
            "1. Load synthetic data into default.td_contracts for as_of_dt = '2024-01-31'\n"
            "2. Execute the ETL pipeline to populate work_schema.cad_id\n"
            "3. Run validation query:\n"
            "   SELECT COUNT(*) FROM work_schema.cad_id\n"
            "   WHERE as_of_dt = '2024-01-31'\n"
            "     AND (borr_crdt_scr < 300 OR borr_crdt_scr > 850)\n"
            "4. Observe: query returns 1 (expected: 0)"
        ),
        "expected_result": "0 records with credit scores outside the 300–850 FICO range.",
        "actual_result": "1 record has borr_crdt_scr outside the valid range.",
        "priority": "Medium",
        "severity": "Moderate",
        "linked_user_story": (
            "US-CAD-105: As a risk analyst, I need borrower credit scores correctly converted "
            "from STRING to INT and validated within the FICO range (300–850) so that "
            "credit risk models and underwriting decisions are based on valid data."
        ),
        "component": "ETL — Type Conversion & Validation",
        "labels": ["data-quality", "credit-score", "range-validation"],
    },
    "TC-AG-004": {
        "summary": "[CAD] Payment Component Sum Mismatch — $1,750 delta in MOEND actg_unit_bal_fact",
        "description": (
            "For the MOEND snapshot (data_src_ind = 'M'), the total payment amount "
            "(SUM of last_pmt_amt = $875,000.00) does not equal the sum of payment "
            "components (last_pmt_prin_amt + last_pmt_int_amt + last_pmt_escrow_amt + "
            "last_pmt_late_fee_amt = $873,250.00).\n\n"
            "Delta: $1,750.00 (0.2% of total)\n\n"
            "This mismatch indicates either:\n"
            "  - A rounding error in the DECIMAL arithmetic during ETL\n"
            "  - A missing payment component not captured in the four standard buckets\n"
            "  - An incorrect source-to-audit mapping for one of the component columns\n\n"
            "Note: The DAILY snapshot (data_src_ind = 'D') passes this check with "
            "components summing exactly to the total."
        ),
        "steps_to_reproduce": (
            "1. Load synthetic data for as_of_dt = '2024-01-31'\n"
            "2. Execute the ETL pipeline through to audit.cad_actg_unit_bal_fact\n"
            "3. Run validation query:\n"
            "   SELECT\n"
            "     SUM(last_pmt_amt) AS total_pmt,\n"
            "     SUM(last_pmt_prin_amt + last_pmt_int_amt +\n"
            "         last_pmt_escrow_amt + last_pmt_late_fee_amt) AS component_sum\n"
            "   FROM audit.cad_actg_unit_bal_fact\n"
            "   WHERE as_of_dt = '2024-01-31' AND data_src_ind = 'M'\n"
            "4. Observe: total_pmt = 875000.00, component_sum = 873250.00 (delta = $1,750)"
        ),
        "expected_result": "SUM(last_pmt_amt) = SUM(last_pmt_prin_amt + last_pmt_int_amt + last_pmt_escrow_amt + last_pmt_late_fee_amt) within tolerance of $0.01.",
        "actual_result": "total_pmt = $875,000.00, component_sum = $873,250.00. Delta = $1,750.00 exceeds tolerance.",
        "priority": "Critical",
        "severity": "Critical",
        "linked_user_story": (
            "US-CAD-201: As a finance operations analyst, I need payment amounts in the "
            "audit fact table to be internally consistent (total = sum of components) so "
            "that financial reconciliation reports balance and audit findings are avoided."
        ),
        "component": "ETL — Payment Aggregation",
        "labels": ["data-quality", "financial-reconciliation", "audit-layer", "payment"],
    },
    "TC-IG-002": {
        "summary": "[CAD] Orphan Source Records — 2 MOEND contracts missing from cad_id staging",
        "description": (
            "2 records in default.td_contracts (MOEND snapshot, data_src_ind = 'M') have no "
            "matching record in work_schema.cad_id when joined on ln_acct_nbr + as_of_dt + "
            "data_src_ind. These contracts were loaded into the source layer but were not "
            "propagated to the staging layer.\n\n"
            "This is an integration failure — the source-to-staging ETL step dropped 2 records. "
            "These contracts will be missing from ALL downstream tables (cad_cb/cad_nccb, "
            "audit dimensions and facts), causing incomplete portfolio reporting.\n\n"
            "Note: The DAILY snapshot (data_src_ind = 'D') has no orphan records; this issue "
            "is specific to the MOEND processing path."
        ),
        "steps_to_reproduce": (
            "1. Load synthetic data for as_of_dt = '2024-01-31'\n"
            "2. Execute the ETL pipeline for both DAILY and MOEND snapshots\n"
            "3. Run validation query:\n"
            "   SELECT COUNT(*) FROM default.td_contracts tc\n"
            "   LEFT JOIN work_schema.cad_id ci\n"
            "     ON tc.ln_acct_nbr = ci.ln_acct_nbr\n"
            "     AND tc.as_of_dt = ci.as_of_dt\n"
            "     AND tc.data_src_ind = ci.data_src_ind\n"
            "   WHERE tc.as_of_dt = '2024-01-31'\n"
            "     AND tc.data_src_ind = 'M'\n"
            "     AND ci.ln_acct_nbr IS NULL\n"
            "4. Observe: query returns 2 (expected: 0)"
        ),
        "expected_result": "0 orphan records — every source contract should have a corresponding cad_id record.",
        "actual_result": "2 MOEND source records have no matching cad_id entry. These contracts are missing from all downstream tables.",
        "priority": "Critical",
        "severity": "Critical",
        "linked_user_story": (
            "US-CAD-301: As a data engineer, I need 100% of source contracts to be staged "
            "into cad_id for both DAILY and MOEND snapshots, so that no contracts are lost "
            "during the source-to-staging transformation and downstream reporting is complete."
        ),
        "component": "ETL — Source to Staging Pipeline",
        "labels": ["data-quality", "data-completeness", "integration", "moend"],
    },
    "TC-IG-005b": {
        "summary": "[CAD] Duplicate Record in cad_cb — 1 DAILY contract appears twice on same natural key",
        "description": (
            "1 duplicate record group was found in work_schema.cad_cb for the DAILY snapshot "
            "(data_src_ind = 'D'). The same contract (ln_acct_nbr + data_src_ind) appears more "
            "than once within the same as_of_dt partition.\n\n"
            "This duplicate will cause:\n"
            "  - Double-counting in SUM(ln_curr_bal) and other balance aggregations\n"
            "  - Inflated portfolio metrics and incorrect exposure calculations\n"
            "  - JOIN fan-out when linking to audit fact tables\n\n"
            "The ETL staging INSERT may be missing a DISTINCT clause or deduplication logic "
            "on the natural key (ln_acct_nbr + data_src_ind + as_of_dt)."
        ),
        "steps_to_reproduce": (
            "1. Load synthetic data for as_of_dt = '2024-01-31'\n"
            "2. Execute the ETL pipeline to populate work_schema.cad_cb\n"
            "3. Run validation query:\n"
            "   SELECT COUNT(*) FROM (\n"
            "     SELECT ln_acct_nbr, data_src_ind, COUNT(*) AS cnt\n"
            "     FROM work_schema.cad_cb\n"
            "     WHERE as_of_dt = '2024-01-31' AND data_src_ind = 'D'\n"
            "     GROUP BY ln_acct_nbr, data_src_ind\n"
            "     HAVING COUNT(*) > 1\n"
            "   ) dups\n"
            "4. Observe: query returns 1 (expected: 0)"
        ),
        "expected_result": "0 duplicate record groups — each ln_acct_nbr + data_src_ind combination should appear exactly once per partition.",
        "actual_result": "1 duplicate group found in cad_cb for DAILY snapshot.",
        "priority": "High",
        "severity": "Major",
        "linked_user_story": (
            "US-CAD-302: As a data steward, I need staging tables to enforce uniqueness on "
            "natural keys (ln_acct_nbr + data_src_ind per as_of_dt partition) so that "
            "downstream aggregations are not inflated by duplicate records."
        ),
        "component": "ETL — Deduplication",
        "labels": ["data-quality", "duplicates", "staging-layer", "daily"],
    },
}


def build_jira_defects() -> list[dict]:
    """
    Build a list of Jira-formatted defect ticket dicts.
    Each defect includes all fields requested: project, issue type, summary,
    description, steps to reproduce, expected/actual, evidence, priority,
    severity, and linked user story.
    """
    # Read the validation report to get SQL evidence for each failed test
    report_files = sorted(
        f for f in os.listdir(REPORTS_DIR) if f.endswith(".json")
    )
    if not report_files:
        print("ERROR: No JSON report found in reports/", file=sys.stderr)
        sys.exit(1)

    report_path = os.path.join(REPORTS_DIR, report_files[-1])
    with open(report_path) as fh:
        report = json.load(fh)

    # Extract failed results and index by test_id
    failed_results = [r for r in report["results"] if not r.get("passed")]
    failed_by_id = {}
    for r in failed_results:
        tid = r["test_id"]
        if tid not in failed_by_id:
            failed_by_id[tid] = r

    # Build defect tickets
    defects = []
    for i, (test_id, defn) in enumerate(DEFECT_DEFINITIONS.items(), 1):
        # Get the actual test result for evidence
        test_result = failed_by_id.get(test_id, {})
        evidence_sql = str(test_result.get("sql", "N/A"))
        evidence_expected = str(test_result.get("expected", "N/A"))
        evidence_actual = str(test_result.get("actual", "N/A"))
        evidence_message = str(test_result.get("message", "N/A"))

        defect = {
            # -- Jira ticket metadata --
            "jira_project": JIRA_PROJECT,
            "issue_type": ISSUE_TYPE,
            "defect_id": f"CAD-DEF-{i:03d}",
            "test_case_id": test_id,
            "reporter": REPORTER,
            "created_date": datetime.now().strftime("%Y-%m-%d"),
            "environment": ENVIRONMENT,
            "snapshot_date": SNAPSHOT_DATE,

            # -- Core defect content --
            "summary": defn["summary"],
            "description": defn["description"],
            "steps_to_reproduce": defn["steps_to_reproduce"],
            "expected_result": defn["expected_result"],
            "actual_result": defn["actual_result"],

            # -- Evidence from validation execution --
            "evidence": {
                "sql_query": evidence_sql,
                "expected_value": evidence_expected,
                "actual_value": evidence_actual,
                "validation_message": evidence_message,
            },

            # -- Classification --
            "priority": defn["priority"],
            "severity": defn["severity"],
            "component": defn["component"],
            "labels": defn["labels"],

            # -- Traceability --
            "linked_user_story": defn["linked_user_story"],
        }
        defects.append(defect)

    return defects


def write_json(defects: list[dict], output_path: str) -> None:
    """Write defects to a JSON file."""
    with open(output_path, "w") as fh:
        json.dump(defects, fh, indent=2, default=str)
    print(f"JSON written: {output_path}")


def write_xlsx(defects: list[dict], output_path: str) -> None:
    """
    Write defects to an XLSX workbook with formatted headers,
    column widths, and conditional formatting for priority/severity.
    """
    wb = openpyxl.Workbook()

    # ---- Sheet 1: Defect Summary ----
    ws = wb.active
    ws.title = "Defect Summary"

    # Column definitions for the summary sheet
    columns = [
        ("Defect ID", 14),
        ("Test Case ID", 14),
        ("Jira Project", 13),
        ("Issue Type", 11),
        ("Priority", 10),
        ("Severity", 10),
        ("Summary", 70),
        ("Component", 30),
        ("Labels", 35),
        ("Snapshot Date", 14),
        ("Created Date", 14),
        ("Reporter", 22),
        ("Linked User Story", 80),
    ]

    # Style definitions
    header_font = Font(name="Calibri", bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    cell_alignment = Alignment(vertical="top", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    # Priority color fills
    priority_fills = {
        "Critical": PatternFill(start_color="FF4444", end_color="FF4444", fill_type="solid"),
        "High": PatternFill(start_color="FF8C00", end_color="FF8C00", fill_type="solid"),
        "Medium": PatternFill(start_color="FFD700", end_color="FFD700", fill_type="solid"),
        "Low": PatternFill(start_color="90EE90", end_color="90EE90", fill_type="solid"),
    }

    # Write headers
    for col_idx, (col_name, col_width) in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        ws.column_dimensions[get_column_letter(col_idx)].width = col_width

    # Write defect rows
    for row_idx, d in enumerate(defects, 2):
        row_data = [
            d["defect_id"],
            d["test_case_id"],
            d["jira_project"],
            d["issue_type"],
            d["priority"],
            d["severity"],
            d["summary"],
            d["component"],
            ", ".join(d["labels"]),
            d["snapshot_date"],
            d["created_date"],
            d["reporter"],
            d["linked_user_story"],
        ]
        for col_idx, value in enumerate(row_data, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = cell_alignment
            cell.border = thin_border

        # Color-code priority column
        priority_cell = ws.cell(row=row_idx, column=5)
        if priority_cell.value in priority_fills:
            priority_cell.fill = priority_fills[priority_cell.value]
            if priority_cell.value == "Critical":
                priority_cell.font = Font(bold=True, color="FFFFFF")

        # Color-code severity column
        severity_cell = ws.cell(row=row_idx, column=6)
        if severity_cell.value in priority_fills:
            severity_cell.fill = priority_fills[severity_cell.value]
            if severity_cell.value == "Critical":
                severity_cell.font = Font(bold=True, color="FFFFFF")

    # Freeze header row
    ws.freeze_panes = "A2"
    # Auto-filter
    ws.auto_filter.ref = f"A1:{get_column_letter(len(columns))}{len(defects) + 1}"

    # ---- Sheet 2: Defect Details ----
    ws2 = wb.create_sheet("Defect Details")

    detail_columns = [
        ("Defect ID", 14),
        ("Summary", 60),
        ("Description", 80),
        ("Steps to Reproduce", 80),
        ("Expected Result", 60),
        ("Actual Result", 60),
        ("Evidence — SQL Query", 80),
        ("Evidence — Expected Value", 25),
        ("Evidence — Actual Value", 25),
        ("Evidence — Message", 50),
    ]

    # Write headers for details sheet
    for col_idx, (col_name, col_width) in enumerate(detail_columns, 1):
        cell = ws2.cell(row=1, column=col_idx, value=col_name)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border
        ws2.column_dimensions[get_column_letter(col_idx)].width = col_width

    # Write detail rows
    for row_idx, d in enumerate(defects, 2):
        detail_data = [
            d["defect_id"],
            d["summary"],
            d["description"],
            d["steps_to_reproduce"],
            d["expected_result"],
            d["actual_result"],
            d["evidence"]["sql_query"],
            d["evidence"]["expected_value"],
            d["evidence"]["actual_value"],
            d["evidence"]["validation_message"],
        ]
        for col_idx, value in enumerate(detail_data, 1):
            cell = ws2.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = cell_alignment
            cell.border = thin_border

    ws2.freeze_panes = "A2"

    # Save workbook
    wb.save(output_path)
    print(f"XLSX written: {output_path}")


def main():
    """Generate Jira defect drafts in JSON and XLSX formats."""
    print("=" * 70)
    print("JIRA DEFECT DRAFT GENERATION")
    print("=" * 70)

    defects = build_jira_defects()

    print(f"\nGenerated {len(defects)} defect drafts:\n")
    for d in defects:
        print(f"  {d['defect_id']} [{d['priority']}] {d['summary']}")

    # Write JSON output
    json_path = os.path.join(REPORTS_DIR, "defects_jira_format.json")
    write_json(defects, json_path)

    # Write XLSX output
    xlsx_path = os.path.join(REPORTS_DIR, "defects_jira_format.xlsx")
    write_xlsx(defects, xlsx_path)

    print(f"\nOutput files:")
    print(f"  JSON: {json_path}")
    print(f"  XLSX: {xlsx_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
