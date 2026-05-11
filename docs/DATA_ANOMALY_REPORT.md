# Data Anomaly Report — Legacy CDW Tables

> **Generated:** 2026-05-11  
> **Scope:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`  
> **Reviewed tables:** `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`

---

## ANO-001: Payment Amount Component Mismatch

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:**  
The invariant `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` is violated in 3 of 10 payment records (30%).

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN+INT+ESC+FEE | Δ |
|---|---|---|---|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | **+47.50** |

**Business Impact:**  
Financial reporting and loan accounting will be incorrect. The $400 discrepancy on loan `LN-2019-00142` affects balance calculations, principal/interest splits for tax reporting (Form 1098), and escrow analysis. The late-fee discrepancy on `PMT-2025110003` means either the total is understated or the late fee is phantom.

**Recommended Fix:**  
Add a validation check that verifies payment component sums equal the total amount at ingestion time. Flag records where the invariant is violated and quarantine them for manual review. Correct the interest amount on `PMT-2025120001`/`PMT-2025110001` (likely overstated by $400) and resolve whether the late fee on `PMT-2025110003` should be included in the total.

---

## ANO-002: SSN Last-4 Digits Contaminated with Phone Number Data

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_SSN_LST4` |

**Description:**  
All 5 loan account records have `BORR_SSN_LST4` values that exactly match the last 4 digits of the borrower's phone number from `CDW_BORR_MSTR.BORR_PH_NBR`, rather than the actual last 4 digits of their SSN.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_SSN_LST4 | BORR_PH_NBR (from master) | Phone Last-4 |
|---|---|---|---|
| `LN-2019-00142` | 0142 | 217-555-**0142** | 0142 |
| `LN-2020-00398` | 0198 | 503-555-**0198** | 0198 |
| `LN-2018-00089` | 0167 | 512-555-**0167** | 0167 |
| `LN-2021-00567` | 0134 | 303-555-**0134** | 0134 |
| `LN-2017-00034` | 0156 | 602-555-**0156** | 0156 |

**Business Impact:**  
This is a PII cross-contamination issue. Identity verification workflows that rely on SSN-last-4 matching will fail or produce false positives. Any downstream system using this field for borrower verification is compromised. This could also be a compliance issue (GLBA, FCRA) if the field is exposed externally as SSN data.

**Recommended Fix:**  
Flag `BORR_SSN_LST4` as untrusted. Do not use this field for identity verification until it can be repopulated from the authoritative SSN source (e.g., deriving from `BORR_SSN_ENCR` in the borrower master table). Add a cross-reference validation that checks SSN-last-4 does not match known non-SSN fields (phone, zip, etc.).

---

## ANO-003: No NULL Constraints on Required Business Fields

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | All tables (`CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST`) |
| **Affected Columns** | All non-PK columns |

**Description:**  
The legacy schema defines every non-primary-key column as nullable `VARCHAR` with no `NOT NULL` constraints. Critical business fields such as borrower first/last name, loan amounts, interest rates, payment amounts, and dates can all be `NULL`. The current seed data already shows `NULL` for `BORR_MID_INIT` (B-10005) and `BORR_ADDR_LN2` (B-10002, B-10003, B-10005), demonstrating that NULLs flow through.

**Example Risk Scenario:**  
If a borrower record arrives with `BORR_FST_NM = NULL`, the service layer's `toBorrowerDto()` method executes:
```java
dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
```
This produces `"null R. Mitchell"` — the string literal "null" is concatenated into the name.

Similarly, `parseLegacyAmount(null)` returns `BigDecimal.ZERO`, silently converting missing loan amounts to $0.00 rather than flagging the data issue.

**Business Impact:**  
Null values in required fields propagate silently through the service layer, producing corrupted API responses ("null" in names, $0.00 for missing amounts) without any error signal. This masks data quality issues and can cause incorrect downstream processing.

**Recommended Fix:**  
Add null-check validation in the service layer for all required fields before processing. Reject or quarantine records with null values in business-critical fields (first name, last name, loan amounts, interest rate, payment amounts, dates). Log warnings for nullable fields that are unexpectedly empty.

---

## ANO-004: Delinquency Days / Status Code Inconsistency

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:**  
Loan account `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). Standard mortgage servicing rules require that delinquent loans be flagged differently from current/performing loans.

**Example Bad Records:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|---|---|---|---|
| `LN-2018-00089` | 15 | ACT | DLQ or at minimum flagged |

**Business Impact:**  
Delinquent loans reported as "Active" will be excluded from delinquency reports, loss-reserve calculations, and collection workflows. Regulatory reporting (Call Reports, HMDA) requires accurate delinquency classification.

**Recommended Fix:**  
Add cross-field validation: if `LN_DLQ_DAYS > 0`, verify that `LN_STAT_CD` is not `ACT` (or flag for review). Consider adding a delinquency status tier (30-day, 60-day, 90-day) based on the `LN_DLQ_DAYS` value.

---

## ANO-005: No Foreign Key Constraints (Orphan Record Risk)

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ID`, `PROD_CD`, `LN_ACCT_NBR` |

**Description:**  
The legacy schema has no foreign key constraints between tables:
- `CDW_LN_ACCT.BORR_ID` → `CDW_BORR_MSTR.BORR_ID` (no FK)
- `CDW_LN_ACCT.PROD_CD` → `CDW_LN_PROD.PROD_CD` (no FK)
- `CDW_PMT_HIST.LN_ACCT_NBR` → `CDW_LN_ACCT.LN_ACCT_NBR` (no FK)

This means orphaned records (e.g., a loan referencing a non-existent borrower) can exist without detection.

**Example Risk Scenario:**  
If a loan account references `BORR_ID = 'B-99999'` (non-existent), `LoanService.getAllLoans()` will still process it, producing a response with a borrower name built from the denormalized fields only — no error is raised, and the borrower detail endpoint would fail.

**Business Impact:**  
Orphaned loan or payment records would cause silent data inconsistencies in API responses and could trigger `NullPointerException` when the service looks up related entities (e.g., `products.get(acct.getProductCode())` returns `null`).

**Recommended Fix:**  
Add referential integrity validation in the service layer: verify that every `BORR_ID` in loan accounts exists in the borrower master, every `PROD_CD` exists in loan products, and every `LN_ACCT_NBR` in payments exists in loan accounts. Log and reject orphaned records.

---

## ANO-006: Numeric Values Stored as Formatted Strings

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_ANN_INCM`, `BORR_CRDT_SCR`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, etc. |

**Description:**  
All numeric values (monetary amounts, interest rates, credit scores, term months, delinquency days) are stored as `VARCHAR` strings. Monetary amounts include comma formatting (e.g., `'285,000'`, `'1,487.02'`). The service layer's `parseLegacyAmount()` strips commas and parses to `BigDecimal`, but has no error handling for malformed values.

**Example Risk Scenario:**  
If a value like `'N/A'`, `'$285,000'`, `'285 000'` (space separator), or an empty string arrives, `new BigDecimal(...)` throws an uncaught `NumberFormatException`, causing a 500 Internal Server Error for the entire API response.

**Business Impact:**  
A single malformed numeric value in any record will crash the entire API endpoint, not just skip the bad record. This makes the service fragile to any variation in legacy data formatting.

**Recommended Fix:**  
Wrap all numeric parsing in try-catch with meaningful error logging. Return fallback values or exclude the record from results with a warning. Validate that amounts are non-negative and within reasonable bounds (e.g., loan amounts between $0 and $10M).

---

## ANO-007: Date Strings Not Validated

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All `*_DT` columns (`BORR_DOB_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.) |

**Description:**  
All date fields are stored as `VARCHAR(10)` with an expected format of `MM/DD/YYYY`. The service layer passes date strings through to API responses without parsing or validation. There is no guarantee that the strings are valid dates (e.g., `'02/30/2020'`, `'13/01/2020'`, `'00/00/0000'`).

**Example Risk Scenario:**  
A date value of `'02/30/2025'` (February 30th) would pass through the service layer silently and appear in the API response, but would fail if a downstream consumer attempts to parse it.

**Business Impact:**  
Invalid dates would be silently propagated to API consumers, causing failures in downstream date processing, reporting, and compliance systems.

**Recommended Fix:**  
Parse all date strings to `java.time.LocalDate` during ingestion. Flag records with unparseable or logically invalid dates (e.g., origination date in the future, DOB implying age < 18 or > 120).

---

## ANO-008: Denormalized Borrower Data Consistency Risk

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:**  
`CDW_LN_ACCT` contains denormalized copies of borrower first name, last name, and SSN-last-4 alongside the `BORR_ID` foreign key reference. These copies can drift from the master record in `CDW_BORR_MSTR` if the borrower updates their name and only the master table is refreshed.

**Example Risk Scenario:**  
The service builds the borrower name in `toLoanSummary()` from the denormalized fields:
```java
dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
```
While `toBorrowerDto()` uses the master table fields. This means the same borrower could appear with different names depending on which endpoint is called.

**Business Impact:**  
Inconsistent borrower names across API endpoints erodes trust in the data and can cause issues with name-matching in downstream systems (e.g., identity verification, mail merge, regulatory reporting).

**Recommended Fix:**  
Add a cross-reference check comparing denormalized fields against the master record. Log warnings when mismatches are detected. Prefer the master table as the source of truth for borrower name in all service methods.

---

## ANO-009: Payment Date Sorting is Lexicographic, Not Chronological

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT` |

**Description:**  
The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts by the `PMT_DT` `VARCHAR` column. Because dates are stored as `MM/DD/YYYY` strings, the sort is lexicographic: month is compared first, then day, then year. This means `12/01/2024` sorts before `02/01/2025` (because `'12' > '02'` lexicographically), producing incorrect chronological ordering.

**Example:**  
Lexicographic DESC order: `12/15/2025`, `12/01/2025`, `11/15/2025`, `11/01/2025` — happens to be correct for same-year data, but would break across year boundaries (e.g., `12/01/2024` would appear before `01/01/2025`).

**Business Impact:**  
Payment history displayed to users or consumed by downstream systems could be in incorrect chronological order, causing confusion and incorrect "most recent payment" determinations.

**Recommended Fix:**  
Parse date strings to proper `DATE` types before sorting, or reformat to `YYYY-MM-DD` for correct lexicographic sorting. In the service layer, sort payments after retrieval using parsed dates.

---

## ANO-010: Missing or Optional Fields with Silent Defaults

| Field | Value |
|---|---|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

**Description:**  
Some fields are legitimately nullable (middle initial, address line 2), and the current data has `NULL` values for these. The service layer handles the middle initial correctly with a null check, but does not distinguish between "intentionally blank" and "data quality issue."

**Example Records:**  
- `B-10005` (Robert Williams): `BORR_MID_INIT = NULL`
- `B-10002`, `B-10003`, `B-10005`: `BORR_ADDR_LN2 = NULL`

**Business Impact:**  
Minimal direct impact, but without a clear distinction between "not applicable" and "missing data," it becomes harder to identify true data quality issues in optional fields.

**Recommended Fix:**  
Document which fields are considered optional vs. required. For optional fields, accept `NULL` gracefully. For fields that should always be populated, treat `NULL` as an anomaly and log a warning.

---

## Summary

| Severity | Count | IDs |
|---|---|---|
| **Critical** | 3 | ANO-001, ANO-002, ANO-003 |
| **High** | 3 | ANO-004, ANO-005, ANO-006 |
| **Medium** | 3 | ANO-007, ANO-008, ANO-009 |
| **Low** | 1 | ANO-010 |
| **Total** | **10** | |
