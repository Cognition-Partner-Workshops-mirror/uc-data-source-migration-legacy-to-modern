# Data Quality Anomaly Report

> **Service:** uc-data-source-migration-legacy-to-modern (Loan Service)
> **Data Source:** Legacy CDW (Corporate Data Warehouse) — H2 in-memory
> **Analysis Date:** 2026-05-07
> **Scope:** `schema-legacy.sql`, `data-legacy.sql`, `LoanService.java`, column mappings

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2     |
| High     | 4     |
| Medium   | 4     |
| Low      | 2     |
| **Total**| **12**|

---

## Critical Anomalies

### ANO-001: SSN Last-4 Digits Match Phone Number Last-4 Digits

| Field           | Value |
|-----------------|-------|
| **Severity**    | Critical |
| **Table**       | `CDW_LN_ACCT` |
| **Column**      | `BORR_SSN_LST4` |

**Description:** Every loan account's `BORR_SSN_LST4` value is identical to the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR.BORR_PH_NBR`.

**Example Bad Records:**

| Loan Account     | BORR_SSN_LST4 | Borrower Phone  | Phone Last 4 |
|------------------|---------------|-----------------|---------------|
| LN-2019-00142    | 0142          | 217-555-**0142** | 0142          |
| LN-2020-00398    | 0198          | 503-555-**0198** | 0198          |
| LN-2018-00089    | 0167          | 512-555-**0167** | 0167          |
| LN-2021-00567    | 0134          | 303-555-**0134** | 0134          |
| LN-2017-00034    | 0156          | 602-555-**0156** | 0156          |

**Business Impact:** This strongly indicates the SSN last-4 field was incorrectly populated from phone numbers during a legacy ETL process. This is a PII data corruption issue: downstream systems relying on SSN last-4 for identity verification (KYC, fraud checks, borrower matching) would be using phone digits instead of actual SSN data, leading to false identity matches or missed duplicates.

**Recommended Fix:** Flag all `BORR_SSN_LST4` values as untrusted. Do not migrate this column to the modern schema without re-sourcing from the authoritative SSN system. Add a data quality flag column to track records needing SSN re-verification.

---

### ANO-002: Payment Component Amounts Do Not Sum to Total

| Field           | Value |
|-----------------|-------|
| **Severity**    | Critical |
| **Table**       | `CDW_PMT_HIST` |
| **Columns**     | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** For some payment records, the sum of principal + interest + escrow + late fee does not equal the stated total payment amount.

**Example Bad Records:**

| Payment ID       | Total    | Principal | Interest  | Escrow  | Late Fee | Sum      | Difference |
|------------------|----------|-----------|-----------|---------|----------|----------|------------|
| PMT-2025120001   | 1,487.02 | 456.78    | 1,074.69  | 355.55  | 0.00     | 1,887.02 | -400.00    |
| PMT-2025110001   | 1,487.02 | 454.97    | 1,076.50  | 355.55  | 0.00     | 1,887.02 | -400.00    |
| PMT-2025110003   | 1,077.05 | 295.82    | 781.23    | 0.00    | 47.50    | 1,124.55 | -47.50     |

Payments that do balance correctly (8 out of 10):

| Payment ID       | Total    | Sum      | Status |
|------------------|----------|----------|--------|
| PMT-2025120002   | 2,924.18 | 2,924.18 | OK     |
| PMT-2025110002   | 2,924.18 | 2,924.18 | OK     |
| PMT-2025120003   | 1,077.05 | 1,077.05 | OK     |
| PMT-2025120004   | 2,468.35 | 2,468.35 | OK     |
| PMT-2025110004   | 2,468.35 | 2,468.35 | OK     |
| PMT-2025120005   | 811.61   | 811.61   | OK     |
| PMT-2025110005   | 811.61   | 811.61   | OK     |

**Business Impact:** Financial reports using these payment records will show incorrect totals. For loan LN-2019-00142, the component breakdown overstates each payment by $400, which over the loan lifetime could compound into significant accounting discrepancies. The late fee exclusion in PMT-2025110003 means late fee revenue is not reflected in payment totals.

**Recommended Fix:** Add a payment validation rule that checks `total == principal + interest + escrow + late_fee` at ingestion time. Flag imbalanced records and route them for manual review. Consider whether the `PMT_AMT` or the component fields are the source of truth.

---

## High Anomalies

### ANO-003: Numeric Amounts Stored as Comma-Formatted Strings

| Field           | Value |
|-----------------|-------|
| **Severity**    | High |
| **Tables**      | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Columns**     | `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, all `PMT_*_AMT` columns |

**Description:** All monetary values are stored as VARCHAR with embedded commas (e.g., `"285,000"`, `"1,487.02"`, `"92,500"`). The service layer's `parseLegacyAmount()` strips commas before parsing to `BigDecimal`, but has no error handling for malformed values such as `"$285,000"`, `"N/A"`, `"TBD"`, or empty strings beyond blank checks. A single corrupt value will throw an unhandled `NumberFormatException`, crashing the API request.

**Example Values at Risk:**
```
"285,000"    -> 285000    (works)
"1,487.02"   -> 1487.02   (works)
"$285,000"   -> Exception (dollar sign not stripped)
"N/A"        -> Exception (non-numeric)
""           -> ZERO       (silent default — may be incorrect)
```

**Business Impact:** Any corrupt monetary value in the legacy warehouse will cause a 500 Internal Server Error on all API endpoints that touch that record, with no indication of which field or record caused the failure.

**Recommended Fix:** Wrap all parsing in try-catch with logging. Add validation that parsed amounts are non-negative. Return a sentinel or flag instead of crashing.

---

### ANO-004: Dates Stored as Unvalidated VARCHAR Strings

| Field           | Value |
|-----------------|-------|
| **Severity**    | High |
| **Tables**      | All tables |
| **Columns**     | All `*_DT` columns (`BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, etc.) |

**Description:** All date fields are VARCHAR(10) with an expected format of MM/DD/YYYY, but there is no database-level constraint enforcing this format. The service layer passes date strings directly to DTOs (e.g., `dto.setOriginationDate(acct.getOriginationDate())`) without parsing or validating them. Invalid dates like `"13/32/2025"`, `"2025-01-15"` (ISO format), or `"TBD"` would pass through silently to API consumers.

**Example Values:**
- Current data: `"03/15/1978"`, `"02/15/2019"` (all valid MM/DD/YYYY)
- Risk scenarios: `"00/00/0000"`, `"2025-01-15"`, `"TBD"`, `NULL`

**Business Impact:** API consumers expecting consistent date formats will break. The column_mappings.md specifies `Parse MM/DD/YYYY -> DATE` for migration, but if any legacy record has a non-conforming format, the migration script will fail mid-batch.

**Recommended Fix:** Validate all date strings against MM/DD/YYYY pattern at ingestion. Parse to `LocalDate` to catch invalid calendar dates (e.g., Feb 30). Log and flag unparseable dates.

---

### ANO-005: No Foreign Key Constraints Enable Orphaned Records

| Field           | Value |
|-----------------|-------|
| **Severity**    | High |
| **Tables**      | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Columns**     | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema explicitly has no foreign key constraints (noted in the schema header comments). This means:
- A loan account could reference a `BORR_ID` that doesn't exist in `CDW_BORR_MSTR`
- A loan account could reference a `PROD_CD` that doesn't exist in `CDW_LN_PROD`
- A payment could reference an `LN_ACCT_NBR` that doesn't exist in `CDW_LN_ACCT`

The current seed data is consistent, but the schema allows any future insert to create orphaned records. In `LoanService.getLoanById()`, if `acct.getProductCode()` doesn't match any product, the product lookup returns `null` and the code falls back to showing the raw product code — a silent data quality degradation.

**Business Impact:** Orphaned loan accounts would display without borrower details. Orphaned payments would be invisible (no loan to attach them to). The `getAllLoans()` method could throw a `NullPointerException` if the products map returns null for an unknown product code — though the current `toLoanSummary` handles this with a null check.

**Recommended Fix:** Add referential integrity validation at ingestion time. Before processing a loan account, verify the borrower and product exist. Before processing a payment, verify the loan account exists. Log warnings for any orphaned references.

---

### ANO-006: Active Loan Status with Non-Zero Delinquency Days

| Field           | Value |
|-----------------|-------|
| **Severity**    | High |
| **Table**       | `CDW_LN_ACCT` |
| **Columns**     | `LN_STAT_CD`, `LN_DLQ_DAYS` |

**Description:** Loan `LN-2018-00089` (Michael Torres) has `LN_STAT_CD = 'ACT'` (Active) but `LN_DLQ_DAYS = '15'` (15 days delinquent). This is a business logic contradiction: a loan that is 15+ days delinquent should not be in Active status. The payment history confirms late payments for this loan — PMT-2025110003 was received on 11/18 for a 11/01 due date (17 days late) with a $47.50 late fee.

**Example Bad Record:**

| Loan Account   | Status | Delinquency Days | Nov Payment Received | Late Fee |
|----------------|--------|------------------|---------------------|----------|
| LN-2018-00089  | ACT    | 15               | 11/18/2025          | $47.50   |

**Business Impact:** Regulatory reporting that uses status codes to identify at-risk loans would miss this delinquent loan. Collections workflows triggered by non-Active status would not engage. Risk models using status as a feature would undercount delinquent exposure.

**Recommended Fix:** Add cross-field validation: if `delinquency_days > 0`, status should not be `ACT`. Flag or auto-correct based on business rules (e.g., > 30 days = `DFT`, > 0 days = `DLQ`).

---

## Medium Anomalies

### ANO-007: NULL Middle Initial Without Consistent Handling

| Field           | Value |
|-----------------|-------|
| **Severity**    | Medium |
| **Table**       | `CDW_BORR_MSTR` |
| **Column**      | `BORR_MID_INIT` |

**Description:** Borrower B-10005 (Robert Williams) has a NULL middle initial. While `toBorrowerDto()` handles this with a null check for name formatting, the `toLoanSummary()` method only uses first + last name from the denormalized loan account fields (which don't include middle initial). This creates inconsistent name representations across API endpoints.

**Example:** B-10005 appears as "Robert Williams" in both loan and borrower views (consistent by accident), while B-10001 appears as "James Mitchell" in loans but "James R. Mitchell" in borrower detail.

**Business Impact:** Name matching and deduplication processes may fail to correlate the same borrower across different API responses.

**Recommended Fix:** Standardize name formatting. Either always include middle initial when available, or never include it, across all DTOs.

---

### ANO-008: Denormalized Borrower Data Can Drift From Master

| Field           | Value |
|-----------------|-------|
| **Severity**    | Medium |
| **Tables**      | `CDW_LN_ACCT` vs `CDW_BORR_MSTR` |
| **Columns**     | `BORR_FST_NM`, `BORR_LST_NM` in both tables |

**Description:** `CDW_LN_ACCT` contains denormalized copies of borrower first and last names. Without update triggers or referential constraints, these can drift from the master record in `CDW_BORR_MSTR`. The current seed data is consistent, but the architecture allows silent divergence.

**Business Impact:** If a borrower's name is updated in the master table but not in the loan account table, API responses will show different names depending on which endpoint is called (`/api/loans` vs `/api/borrowers/{id}`).

**Recommended Fix:** During ingestion, cross-validate denormalized fields against the master table. Log warnings for any mismatches. In the modern schema, use foreign key relationships instead of denormalization.

---

### ANO-009: LTV Percent Represents Original LTV, Not Current

| Field           | Value |
|-----------------|-------|
| **Severity**    | Medium |
| **Table**       | `CDW_LN_ACCT` |
| **Column**      | `LN_LTV_PCT` |

**Description:** The `LN_LTV_PCT` field stores the loan-to-value ratio at origination (original amount / appraised value), not the current LTV (current balance / appraised value). The field name does not clarify this.

**Verification:**

| Loan            | Original Amt | Appraised Val | Orig LTV Calc | Stored LTV | Current Bal  | Current LTV Calc |
|-----------------|-------------|---------------|---------------|------------|-------------|-----------------|
| LN-2019-00142   | 285,000     | 345,000       | 82.6%         | 82.5       | 271,432.56  | 78.7%           |
| LN-2020-00398   | 420,000     | 615,000       | 68.3%         | 68.2       | 312,876.43  | 50.9%           |
| LN-2018-00089   | 195,000     | 260,000       | 75.0%         | 75.0       | 178,234.12  | 68.6%           |

**Business Impact:** Risk assessments using this field as current LTV would overstate risk exposure. Regulatory reporting (e.g., PMI requirements triggered by LTV > 80%) could be incorrect.

**Recommended Fix:** Rename to `LN_ORIG_LTV_PCT` in modern schema. Calculate current LTV dynamically from `current_balance / appraised_value`. Document the distinction clearly.

---

### ANO-010: String-Based Date Sorting Produces Incorrect Chronological Order

| Field           | Value |
|-----------------|-------|
| **Severity**    | Medium |
| **Table**       | `CDW_PMT_HIST` |
| **Column**      | `PMT_DT` |

**Description:** The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts `PMT_DT` (a VARCHAR column) using string comparison. For MM/DD/YYYY format, string sorting happens to produce correct results within a single year, but will fail across year boundaries (e.g., `"01/01/2026"` would sort before `"12/31/2025"` in string comparison, but is chronologically after it).

**Business Impact:** Payment history would display in wrong order once data spans multiple years, causing confusion in customer-facing statements and audit trails.

**Recommended Fix:** Parse date strings to `LocalDate` in the service layer and sort programmatically, or convert to ISO format (YYYY-MM-DD) which sorts correctly as strings.

---

## Low Anomalies

### ANO-011: Credit Score Stored as VARCHAR Without Range Validation

| Field           | Value |
|-----------------|-------|
| **Severity**    | Low |
| **Table**       | `CDW_BORR_MSTR` |
| **Column**      | `BORR_CRDT_SCR` |

**Description:** Credit scores are stored as VARCHAR(5). Valid FICO scores range 300-850. The `parseLegacyInteger()` method parses to Integer but does not validate the range. A value of `"0"`, `"999"`, or `"-1"` would parse successfully but represent invalid data.

**Current Values:** 745, 780, 692, 810, 658 (all within valid range)

**Business Impact:** Invalid credit scores could affect loan eligibility calculations and risk scoring.

**Recommended Fix:** Add range validation (300-850) after parsing. Flag out-of-range values.

---

### ANO-012: All-VARCHAR Schema Prevents Database-Level Type Safety

| Field           | Value |
|-----------------|-------|
| **Severity**    | Low |
| **Tables**      | All tables |
| **Columns**     | All columns |

**Description:** The entire legacy schema uses VARCHAR for every column, including fields that should be INTEGER (term months, delinquency days, credit score), DECIMAL (amounts, rates, percentages), DATE (all date fields), and BOOLEAN (status active/inactive). This means the database provides zero type-level protection against inserting invalid data.

**Business Impact:** Any ETL process or manual data entry can insert semantically invalid data (e.g., `"abc"` in a credit score field) without any database error. All validation burden falls on the application layer, which currently has minimal safeguards.

**Recommended Fix:** This is the core reason for the modern schema migration. The modern schema uses proper types (DATE, DECIMAL, INTEGER, BOOLEAN) which will enforce type safety at the database level.
