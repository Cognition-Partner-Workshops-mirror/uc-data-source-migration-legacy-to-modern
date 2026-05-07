# Legacy CDW Data Anomaly Report

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## ANM-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** The sum of payment component amounts (principal + interest + escrow + late fee) does not equal the total payment amount for several records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | Principal + Interest + Escrow + Late Fee | Discrepancy |
|-------------|---------|------------------------------------------|-------------|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | +400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | +400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | +47.50 |

**Business Impact:** Financial reconciliation failures. Any downstream system or report that cross-checks payment components against the total will produce discrepancies. Accounting audits will flag these records. The consistent +400.00 overage on loan `LN-2019-00142` suggests the escrow portion was double-counted or incorrectly included in the component breakdown.

**Recommended Fix:** Add a validation rule at ingestion that asserts `principal + interest + escrow + lateFee == totalAmount` (within a rounding tolerance of $0.01). Flag non-conforming records for manual review rather than silently accepting them.

---

## ANM-002: String-Based Date Storage Prevents Correct Sorting

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST`, `CDW_LN_ACCT`, `CDW_BORR_MSTR` |
| **Affected Columns** | All date columns (`PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `LN_ORIG_DT`, `BORR_DOB_DT`, etc.) |

**Description:** All dates are stored as `VARCHAR` in `MM/DD/YYYY` format. String-based sorting on this format produces incorrect chronological ordering because the month comes first (e.g., `"02/01/2026"` sorts before `"12/01/2025"` lexicographically, even though December 2025 precedes February 2026).

**Example Bad Records:**

The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` uses JPA `ORDER BY` on `PMT_DT`. With string sorting:
- `"12/15/2025"` > `"11/15/2025"` (happens to be correct for same-year, same-century)
- `"02/01/2026"` < `"12/01/2025"` (WRONG: Feb 2026 sorts before Dec 2025)

All date columns across all four tables share this problem.

**Business Impact:** Payment history displayed in the wrong order. Any query relying on date ordering (latest payment, first payment date, maturity date comparisons) will produce incorrect results when dates span year boundaries. This affects API responses for payment history and any delinquency calculations.

**Recommended Fix:** Parse `MM/DD/YYYY` strings into `java.time.LocalDate` at the service layer. Sort programmatically on parsed dates rather than relying on database string ordering. Validate date format on ingestion and reject unparseable values.

---

## ANM-003: Numeric Parsing Without Error Handling

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, all amount/numeric columns |

**Description:** All numeric values are stored as `VARCHAR` strings. The service layer parses these with `BigDecimal(string)` and `Integer.parseInt(string)` but has no exception handling. Any malformed value (e.g., `"N/A"`, `"---"`, `"$285,000"`, `"TBD"`, extra whitespace beyond `.trim()`) will throw an uncaught `NumberFormatException`, crashing the entire API request.

**Example Risk Scenarios:**

| Column | Current Value | Potential Bad Value | Result |
|--------|--------------|--------------------|---------| 
| `BORR_CRDT_SCR` | `"745"` | `"N/A"` or `"PENDING"` | `NumberFormatException` in `parseLegacyInteger` |
| `LN_ORIG_AMT` | `"285,000"` | `"$285,000"` or `"285.000,00"` (European format) | `NumberFormatException` in `parseLegacyAmount` |
| `LN_INT_RT` | `"4.750"` | `"4.750%"` or `"VARIABLE"` | `NumberFormatException` in `parseLegacyDecimal` |

**Business Impact:** A single malformed record causes the entire `/api/loans` or `/api/borrowers` endpoint to return HTTP 500, making all records inaccessible. There is no record-level error isolation.

**Recommended Fix:** Wrap all numeric parsing in try-catch blocks. Return sensible defaults (e.g., `BigDecimal.ZERO`, `null` for credit score) on parse failure. Log warnings for unparseable values. Add format validation at ingestion time.

---

## ANM-004: No Foreign Key Constraints (Orphaned Record Risk)

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema has zero foreign key constraints. `CDW_LN_ACCT.BORR_ID` is not constrained to reference `CDW_BORR_MSTR.BORR_ID`. `CDW_LN_ACCT.PROD_CD` is not constrained to reference `CDW_LN_PROD.PROD_CD`. `CDW_PMT_HIST.LN_ACCT_NBR` is not constrained to reference `CDW_LN_ACCT.LN_ACCT_NBR`.

**Example Risk:** If a loan account references `BORR_ID = 'B-99999'` (non-existent borrower), or `PROD_CD = 'XYZ'` (non-existent product), the application will either:
- Return `null` product descriptions (handled with fallback in `toLoanSummary`)
- Throw `RuntimeException("Borrower not found")` in `getBorrowerById` when looking up orphaned borrower IDs

**Business Impact:** Orphaned loan records cause cascading lookup failures. The `getAllLoans()` method would return loans with missing product descriptions. The `getBorrowerById()` method would throw exceptions for orphaned borrower references.

**Recommended Fix:** Validate referential integrity at ingestion time. Verify that `BORR_ID` exists in the borrower table, `PROD_CD` exists in the product table, and `LN_ACCT_NBR` exists in the loan account table before accepting records.

---

## ANM-005: Denormalized Borrower Data Drift

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** Borrower first name, last name, and SSN last 4 digits are duplicated in the loan account table (denormalized from `CDW_BORR_MSTR`). These copies can drift from the source-of-truth borrower record if the borrower updates their name or if data entry errors occur.

**Example:**
- `CDW_BORR_MSTR` for `B-10001`: `BORR_FST_NM = 'James'`, `BORR_LST_NM = 'Mitchell'`
- `CDW_LN_ACCT` for `LN-2019-00142`: `BORR_FST_NM = 'James'`, `BORR_LST_NM = 'Mitchell'`
- If borrower updates name in `CDW_BORR_MSTR` to "James Mitchell-Smith", the loan account retains "Mitchell"

The API uses the loan account copy in `toLoanSummary()` (returns "James Mitchell") but the borrower table copy in `toBorrowerDto()`. Different endpoints can return different names for the same person.

**Business Impact:** Inconsistent borrower names across API endpoints. Customer-facing applications may show different names on the loan detail page vs. the borrower profile page. Legal/compliance issues if name on loan documents differs from official borrower record.

**Recommended Fix:** Cross-validate denormalized fields against the borrower master at ingestion. Flag records where `CDW_LN_ACCT.BORR_FST_NM` differs from `CDW_BORR_MSTR.BORR_FST_NM` for the same `BORR_ID`. Prefer the borrower master as the source of truth.

---

## ANM-006: SSN Last-4 Contains Phone Number Digits

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

**Description:** The `BORR_SSN_LST4` values in the loan account table match the last 4 digits of the borrower's phone number rather than the actual SSN last 4 digits.

**Example Bad Records:**

| BORR_ID | Phone (CDW_BORR_MSTR) | SSN_LST4 (CDW_LN_ACCT) | Match? |
|---------|----------------------|------------------------|--------|
| B-10001 | 217-555-**0142** | **0142** | Phone last 4 |
| B-10002 | 503-555-**0198** | **0198** | Phone last 4 |
| B-10003 | 512-555-**0167** | **0167** | Phone last 4 |
| B-10004 | 303-555-**0134** | **0134** | Phone last 4 |
| B-10005 | 602-555-**0156** | **0156** | Phone last 4 |

All 5 records exhibit this pattern — 100% of SSN last-4 values are actually phone number suffixes.

**Business Impact:** Identity verification processes that rely on SSN last-4 matching will fail or produce false positives. This is a potential compliance risk under financial regulations that require accurate identity verification (KYC/AML). Customers could pass verification with phone digits when SSN digits should be required.

**Recommended Fix:** Add validation at ingestion to flag SSN_LST4 values that match the corresponding borrower's phone number suffix. Cross-reference against the encrypted SSN field if decryption is available. Mark these records for manual review.

---

## ANM-007: Delinquency Days Inconsistent with Payment History

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `LN_DLQ_DAYS` |

**Description:** The stored delinquency days value does not match the actual payment lateness derived from payment history records.

**Example:**
- Loan `LN-2018-00089`: `LN_DLQ_DAYS = '15'`
- Most recent payment `PMT-2025120003`: due `12/01/2025`, received `12/05/2025` (4 days late), late fee = $0.00
- Previous payment `PMT-2025110003`: due `11/01/2025`, received `11/18/2025` (17 days late), late fee = $47.50
- The stored 15 days does not match either the current 4-day lateness or the previous 17-day lateness

**Business Impact:** Incorrect delinquency reporting affects collections workflows, credit bureau reporting, and risk assessments. A borrower could be reported as more or less delinquent than they actually are.

**Recommended Fix:** Validate delinquency days against the most recent payment's received-vs-due date delta at ingestion. Flag records where the stored value deviates from the calculated value by more than a configurable threshold.

---

## ANM-008: Late Fee Inconsistency with Payment Lateness

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_LATE_FEE`, `PMT_DT`, `PMT_RECV_DT` |

**Description:** Late fees are not consistently applied relative to payment lateness.

**Example:**
- `PMT-2025120003`: Due `12/01/2025`, received `12/05/2025` (4 days late) — late fee = **$0.00**
- `PMT-2025110003`: Due `11/01/2025`, received `11/18/2025` (17 days late) — late fee = **$47.50**

While the December payment may fall within a grace period, there is no explicit grace period field or rule documented in the schema. The inconsistency cannot be validated without business rules.

**Business Impact:** Potential revenue loss from uncollected late fees, or potential regulatory violations from incorrectly charged fees. Inconsistent fee application creates audit findings.

**Recommended Fix:** Add validation at ingestion that checks whether late fees align with payment lateness based on configurable grace period rules. Flag payments that are late but have zero late fee, and payments that are on-time but have a non-zero late fee.

---

## ANM-009: Stale LTV Percent (Calculated from Original, Not Current Balance)

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `LN_LTV_PCT` |

**Description:** The loan-to-value (LTV) percentage appears to be calculated from the original loan amount rather than the current balance.

**Example:**
| Loan | Original Amount | Current Balance | Appraised Value | Stored LTV | Calculated (Original) | Calculated (Current) |
|------|----------------|-----------------|-----------------|------------|----------------------|---------------------|
| LN-2019-00142 | 285,000 | 271,432.56 | 345,000 | 82.5% | 82.6% | 78.7% |
| LN-2020-00398 | 420,000 | 312,876.43 | 615,000 | 68.2% | 68.3% | 50.9% |
| LN-2021-00567 | 525,000 | 498,123.78 | 721,000 | 72.8% | 72.8% | 69.1% |

**Business Impact:** Overstated LTV ratios lead to incorrect risk assessments. Loans that have been paid down significantly appear riskier than they actually are. This affects PMI (private mortgage insurance) removal decisions and portfolio risk reporting.

**Recommended Fix:** Add validation at ingestion that recalculates LTV from current balance and appraised value. Flag records where the stored LTV deviates from the calculated LTV by more than 1 percentage point. Consider whether the business intent is original-LTV or current-LTV and document accordingly.

---

## ANM-010: NULL Values in Optional-but-Important Fields

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

**Description:** Several columns contain NULL values. While the schema allows NULLs on all non-PK columns (no NOT NULL constraints exist), some NULL values have downstream implications.

**Example:**
- `B-10005` (Robert Williams): `BORR_MID_INIT = NULL` — handled correctly in code
- `B-10002`, `B-10003`, `B-10005`: `BORR_ADDR_LN2 = NULL` — acceptable for address line 2

The schema has no NOT NULL constraints on any non-PK column, meaning critical fields like `BORR_FST_NM`, `BORR_LST_NM`, `BORR_EMAIL_ADDR`, `LN_CURR_BAL`, etc. could also be NULL. A NULL first or last name would cause `NullPointerException` in the string concatenation within `toBorrowerDto()` and `toLoanSummary()`.

**Business Impact:** Low impact for current seed data (NULLs are in truly optional fields). However, the lack of NOT NULL constraints means future data loads could introduce NULLs in critical fields, causing runtime exceptions.

**Recommended Fix:** Add null-safety checks in the service layer for all fields used in string concatenation or arithmetic. Validate that business-critical fields (first name, last name, loan amounts, dates) are non-null at ingestion time.

---

## Summary

| ID | Title | Severity | Table(s) |
|----|-------|----------|----------|
| ANM-001 | Payment Component Sum Mismatch | Critical | CDW_PMT_HIST |
| ANM-002 | String-Based Date Storage Prevents Correct Sorting | Critical | All |
| ANM-003 | Numeric Parsing Without Error Handling | Critical | All |
| ANM-004 | No Foreign Key Constraints (Orphaned Record Risk) | High | CDW_LN_ACCT, CDW_PMT_HIST |
| ANM-005 | Denormalized Borrower Data Drift | High | CDW_LN_ACCT |
| ANM-006 | SSN Last-4 Contains Phone Number Digits | High | CDW_LN_ACCT |
| ANM-007 | Delinquency Days Inconsistent with Payment History | Medium | CDW_LN_ACCT |
| ANM-008 | Late Fee Inconsistency with Payment Lateness | Medium | CDW_PMT_HIST |
| ANM-009 | Stale LTV Percent | Medium | CDW_LN_ACCT |
| ANM-010 | NULL Values in Optional-but-Important Fields | Low | CDW_BORR_MSTR |
