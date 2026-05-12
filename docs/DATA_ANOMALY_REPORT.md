# Data Anomaly Report — Legacy CDW Tables

> **Generated:** 2026-05-12  
> **Scope:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`  
> **Tables analyzed:** `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`

---

## ANM-001: SSN Last-4 Digits Match Phone Number Last-4 Digits

| Field | Value |
|-------|-------|
| **Severity** | **Critical** |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

### Example Bad Records

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | Phone (from CDW_BORR_MSTR) |
|-------------|---------|---------------|----------------------------|
| LN-2019-00142 | B-10001 | 0142 | 217-555-**0142** |
| LN-2020-00398 | B-10002 | 0198 | 503-555-**0198** |
| LN-2018-00089 | B-10003 | 0167 | 512-555-**0167** |
| LN-2021-00567 | B-10004 | 0134 | 303-555-**0134** |
| LN-2017-00034 | B-10005 | 0156 | 602-555-**0156** |

All 5 loan accounts (100%) have `BORR_SSN_LST4` identical to the last 4 digits of the borrower's phone number, not the actual SSN. This is a PII data corruption pattern — SSN fields were likely populated from the wrong source column during a prior ETL job.

### Business Impact

- **Regulatory risk:** SSN-based identity verification will fail, violating KYC (Know Your Customer) requirements.
- **Fraud detection:** SSN-based duplicate/fraud checks are non-functional.
- **Migration risk:** Propagating corrupted SSN data to the modern schema poisons downstream systems.

### Recommended Fix

- Flag all `BORR_SSN_LST4` values as untrusted; do not migrate them to the modern schema without re-extraction from the authoritative SSN source.
- Add validation that `BORR_SSN_LST4` does not match the last 4 digits of `BORR_PH_NBR` from the master borrower record.

---

## ANM-002: Payment Component Amounts Do Not Reconcile With Total

| Field | Value |
|-------|-------|
| **Severity** | **Critical** |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT (Total) | PMT_PRIN_AMT | PMT_INT_AMT | PMT_ESCROW_AMT | PMT_LATE_FEE | Sum of Components | Discrepancy |
|-------------|-----------------|--------------|-------------|----------------|-------------|-------------------|-------------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | **+400.00** |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | **+400.00** |

The remaining 8 payment records reconcile correctly (principal + interest + escrow + late_fee = total). Only the two payments for loan `LN-2019-00142` (borrower B-10001, James Mitchell) have a consistent +400.00 discrepancy between component sum and stated total.

### Business Impact

- **Financial reporting:** Incorrect totals lead to misstated balances and regulatory filing errors.
- **Amortization schedules:** Principal/interest split is wrong — loan payoff projections will be inaccurate.
- **Audit trail:** Discrepancy between total and components is a red flag in SOX compliance audits.

### Recommended Fix

- Add a reconciliation check at ingestion: `|PMT_AMT - (PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE)| < 0.01`.
- Reject or quarantine records that fail the check, with logging for manual review.

---

## ANM-003: All Numeric and Date Fields Stored as VARCHAR — No Type Safety

| Field | Value |
|-------|-------|
| **Severity** | **Critical** |
| **Affected Tables** | All four CDW tables |
| **Affected Columns** | Every date column (12+), every amount column (15+), credit score, term months, delinquency days, LTV percent |

### Example Bad Records (Potential)

The current seed data is syntactically valid, but the VARCHAR schema provides **zero protection** against:

| Column | Current Value | What Could Be Inserted |
|--------|--------------|----------------------|
| `BORR_CRDT_SCR` | `'745'` | `'N/A'`, `'PENDING'`, `''`, `'745.5'` |
| `BORR_ANN_INCM` | `'92,500'` | `'$92,500'`, `'92500.00'`, `'UNKNOWN'` |
| `BORR_DOB_DT` | `'03/15/1978'` | `'1978-03-15'`, `'15/03/1978'`, `'March 15, 1978'` |
| `LN_ORIG_AMT` | `'285,000'` | `'285000'`, `'$285,000.00'`, `'-285,000'` |
| `LN_DLQ_DAYS` | `'15'` | `'fifteen'`, `'15+'`, `'N/A'` |

The service layer's `parseLegacyAmount()`, `parseLegacyInteger()`, and `parseLegacyDecimal()` methods will throw unhandled `NumberFormatException` for any non-numeric value.

### Business Impact

- **Runtime crashes:** Any malformed numeric string causes an unhandled `NumberFormatException` that propagates as HTTP 500 to API consumers.
- **Silent data loss:** `parseLegacyAmount()` returns `BigDecimal.ZERO` for null/blank — a $0 balance is indistinguishable from a missing value.
- **Date parsing failures:** No date validation at all in the current code; dates are passed through as raw strings.

### Recommended Fix

- Add try-catch with logging around all parse methods; return validated defaults or throw a descriptive domain exception.
- Add input validation at ingestion that rejects records with non-parseable numeric/date fields.

---

## ANM-004: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|-------|-------|
| **Severity** | **High** |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Description

The legacy schema has **zero foreign key constraints**. The three cross-table references are:

| Child Column | Expected Parent | Constraint? |
|-------------|-----------------|-------------|
| `CDW_LN_ACCT.BORR_ID` | `CDW_BORR_MSTR.BORR_ID` | None |
| `CDW_LN_ACCT.PROD_CD` | `CDW_LN_PROD.PROD_CD` | None |
| `CDW_PMT_HIST.LN_ACCT_NBR` | `CDW_LN_ACCT.LN_ACCT_NBR` | None |

Current seed data has valid references, but nothing prevents orphaned records from being inserted. In LoanService, `getLoanById()` does `loanProductRepository.findById(acct.getProductCode()).orElse(null)` — a null product results in falling back to the raw product code, hiding the data issue.

### Business Impact

- **Broken loan lookups:** A loan with a non-existent `BORR_ID` cannot be associated with a borrower.
- **NullPointerException risk:** Code paths that assume non-null relationships will crash.
- **Data migration failure:** FK resolution (`Lookup borrowers.id by external_id` per column_mappings.md) will fail for orphaned records.

### Recommended Fix

- Validate referential integrity at ingestion: verify `BORR_ID`, `PROD_CD`, and `LN_ACCT_NBR` exist in their parent tables before accepting a record.

---

## ANM-005: Delinquency Days > 0 With Active Status

| Field | Value |
|-------|-------|
| **Severity** | **High** |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

### Example Bad Records

| LN_ACCT_NBR | BORR_ID | LN_STAT_CD | LN_DLQ_DAYS |
|-------------|---------|-----------|-------------|
| LN-2018-00089 | B-10003 | ACT | 15 |

Loan `LN-2018-00089` has 15 delinquency days but status remains `ACT` (Active). Per standard mortgage servicing rules, delinquency > 0 should trigger at least a sub-status flag or transition to a delinquent state. The November payment for this loan was received 17 days late (`PMT_RECV_DT` = 11/18/2025 vs `PMT_DT` = 11/01/2025) and incurred a $47.50 late fee, confirming the delinquency is real.

### Business Impact

- **Regulatory reporting:** Delinquent loans reported as Active understate portfolio risk.
- **Collections:** No automated collections workflow is triggered.
- **Investor reporting:** For securitized loans, mis-reported delinquency is a serious compliance violation.

### Recommended Fix

- Add a validation rule: if `LN_DLQ_DAYS > 0`, status must not be `ACT` — flag for review or automatically set to `DLQ` (delinquent).

---

## ANM-006: Null Fields in Borrower Records With No Schema Enforcement

| Field | Value |
|-------|-------|
| **Severity** | **Medium** |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

### Example Bad Records

| BORR_ID | BORR_MID_INIT | BORR_ADDR_LN2 |
|---------|--------------|---------------|
| B-10005 | NULL | NULL |
| B-10002 | L | NULL |
| B-10003 | A | NULL |

While `BORR_MID_INIT` and `BORR_ADDR_LN2` are legitimately optional, the schema has **no NOT NULL constraints on any column**, including business-critical fields like `BORR_FST_NM`, `BORR_LST_NM`, `BORR_EMAIL_ADDR`, and `BORR_SSN_ENCR`. A null first/last name will produce `"null null"` in the API response via string concatenation in `LoanService.toBorrowerDto()`.

### Business Impact

- **API data quality:** Null names appear as literal string `"null"` in API responses.
- **Downstream systems:** Systems consuming the API cannot distinguish "null" (string) from missing data.

### Recommended Fix

- Add null-safe handling in name concatenation logic.
- Validate that required business fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_ENCR`) are non-null at ingestion.

---

## ANM-007: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | **Medium** |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

### Description

`CDW_LN_ACCT` contains denormalized copies of borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) alongside the `BORR_ID` foreign key reference. With no triggers or constraints enforcing sync, these copies can drift from the master record in `CDW_BORR_MSTR`.

The current seed data is consistent for names (both sources agree), but this is only coincidence — there is no mechanism to maintain consistency.

### Business Impact

- **Conflicting borrower identities:** Loan documents showing a different name than the borrower master record.
- **Legal and compliance issues:** Mismatched names can create issues in loan servicing and foreclosure proceedings.

### Recommended Fix

- During migration, use only `CDW_BORR_MSTR` as the source of truth for borrower fields (as specified in `column_mappings.md`).
- Add a validation check comparing denormalized fields against the master record.

---

## ANM-008: Escrow Balance With Zero Escrow Payments

| Field | Value |
|-------|-------|
| **Severity** | **Medium** |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.LN_ESCROW_BAL`, `CDW_PMT_HIST.PMT_ESCROW_AMT` |

### Example Bad Records

| LN_ACCT_NBR | LN_ESCROW_BAL | Recent PMT_ESCROW_AMT |
|-------------|--------------|----------------------|
| LN-2018-00089 | 2,100.00 | 0.00, 0.00 |
| LN-2021-00567 | 6,750.00 | 0.00, 0.00 |
| LN-2017-00034 | 1,890.45 | 0.00, 0.00 |

Three of five loans (60%) have non-zero escrow balances but zero escrow amounts in all recent payments. The escrow balance should decrease or stay steady if no escrow is being collected — a positive balance with zero contributions suggests either stale balance data or escrow payments being recorded elsewhere.

### Business Impact

- **Escrow analysis errors:** Escrow shortage/surplus calculations will be wrong.
- **Borrower statements:** Incorrect escrow information on monthly statements.

### Recommended Fix

- Add a consistency check: if `LN_ESCROW_BAL > 0`, at least some recent payments should have `PMT_ESCROW_AMT > 0`, or the escrow balance should be flagged for review.

---

## ANM-009: Late Payment Received After Due Date With Inconsistent Late Fee

| Field | Value |
|-------|-------|
| **Severity** | **Low** |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_LATE_FEE` |

### Example Bad Records

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | Days Late | PMT_LATE_FEE |
|-------------|--------|-------------|-----------|-------------|
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 4 | 0.00 |
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 17 | 47.50 |

For loan `LN-2018-00089`, the December payment was received 4 days late but has no late fee, while the November payment was 17 days late and has a $47.50 fee. Most mortgage grace periods are 15 days, so the December payment (4 days late) may legitimately avoid a late fee. However, the inconsistency between payment timing and fee assessment should be validated.

### Business Impact

- Minor risk of revenue leakage if late fees are not consistently assessed.

### Recommended Fix

- Add a validation rule: if `PMT_RECV_DT - PMT_DT > grace_period_days` and `PMT_LATE_FEE = 0`, flag the record for review.

---

## ANM-010: No Validation on Status Codes

| Field | Value |
|-------|-------|
| **Severity** | **Low** |
| **Affected Tables** | All four CDW tables |
| **Affected Columns** | `BORR_STAT_CD`, `PROD_STAT_CD`, `LN_STAT_CD`, `PMT_TYP_CD`, `PMT_STAT_CD` |

### Description

Status code columns are VARCHAR with no CHECK constraints. Valid codes are only documented implicitly in the service layer's switch statements and the column mappings doc. Any unknown code silently falls through to the `default` case, returning the raw code string instead of a meaningful label.

Current seed data uses only valid codes, but there is no enforcement at the database level.

### Business Impact

- **Silent data corruption:** An invalid status code (e.g., `'XXX'`) would be served to API consumers as-is without warning.
- **Migration risk:** Unknown codes won't map to modern schema enum values.

### Recommended Fix

- Add status code validation at ingestion with a whitelist of known codes per table.
- Log warnings for unknown codes encountered during runtime translation.

---

## Summary

| ID | Title | Severity | Table(s) |
|----|-------|----------|----------|
| ANM-001 | SSN Last-4 = Phone Last-4 (PII Corruption) | Critical | CDW_LN_ACCT |
| ANM-002 | Payment Component Reconciliation Failure | Critical | CDW_PMT_HIST |
| ANM-003 | VARCHAR-Only Schema — No Type Safety | Critical | All |
| ANM-004 | No Foreign Key Constraints | High | CDW_LN_ACCT, CDW_PMT_HIST |
| ANM-005 | Delinquency > 0 With Active Status | High | CDW_LN_ACCT |
| ANM-006 | Null Fields With No Schema Enforcement | Medium | CDW_BORR_MSTR |
| ANM-007 | Denormalized Borrower Data Drift Risk | Medium | CDW_LN_ACCT |
| ANM-008 | Escrow Balance With Zero Escrow Payments | Medium | CDW_LN_ACCT, CDW_PMT_HIST |
| ANM-009 | Late Payment Without Consistent Late Fee | Low | CDW_PMT_HIST |
| ANM-010 | No Status Code Validation | Low | All |
