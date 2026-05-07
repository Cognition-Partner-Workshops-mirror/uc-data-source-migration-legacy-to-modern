# Legacy CDW Data Anomaly Report

> **Generated:** 2026-05-07
> **Source:** `src/main/resources/data-legacy.sql` and `src/main/resources/schema-legacy.sql`
> **Scope:** CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST, CDW_LN_PROD

---

## ANO-001: SSN Last-4 Digits Match Phone Number Last-4 Digits

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

**Description:** For all 5 borrowers, the `BORR_SSN_LST4` value in loan accounts is identical to the last 4 digits of the borrower's phone number in `CDW_BORR_MSTR.BORR_PH_NBR`. This strongly suggests the SSN last-4 field was populated from the phone number column instead of the actual encrypted SSN.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_SSN_LST4 | BORR_PH_NBR (from CDW_BORR_MSTR) | Phone Last 4 |
|-------------|---------------|-----------------------------------|--------------|
| LN-2019-00142 | 0142 | 217-555-0142 | 0142 |
| LN-2020-00398 | 0198 | 503-555-0198 | 0198 |
| LN-2018-00089 | 0167 | 512-555-0167 | 0167 |
| LN-2021-00567 | 0134 | 303-555-0134 | 0134 |
| LN-2017-00034 | 0156 | 602-555-0156 | 0156 |

**Business Impact:** SSN last-4 is used for borrower identity verification. If this data is actually phone-derived, identity verification is unreliable and could lead to regulatory compliance failures (GLBA, FCRA). Loan servicing agents relying on SSN last-4 for phone verification would be using circular data.

**Recommended Fix:** Flag all `BORR_SSN_LST4` values as untrusted. Cross-reference against `BORR_SSN_ENCR` to recompute the correct last-4 digits. Add a validation rule that rejects SSN last-4 values matching the borrower's phone suffix.

---

## ANO-002: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** For several payment records, the sum of component amounts (principal + interest + escrow + late fee) does not equal the total payment amount.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | Principal + Interest + Escrow + Late Fee | Discrepancy |
|-------------|---------|------------------------------------------|-------------|
| PMT-2025120001 | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | +$400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | +$400.00 |
| PMT-2025110003 | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | +$47.50 |

**Business Impact:** Financial reporting will show incorrect payment allocations. Escrow account reconciliation will fail. Borrower statements will be inaccurate. Regulatory audits (RESPA) require accurate escrow accounting.

**Recommended Fix:** Add a payment integrity check that validates `PMT_AMT == PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. Flag discrepancies and log warnings. Prevent propagation of unbalanced records to downstream systems.

---

## ANO-003: Unhandled String-to-Numeric Parsing Failures

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_BORR_MSTR`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | All VARCHAR amount/rate/score columns |

**Description:** The service layer parses VARCHAR fields (amounts, rates, scores) to `BigDecimal`/`Integer` using `parseLegacyAmount`, `parseLegacyDecimal`, and `parseLegacyInteger` without try-catch. Any malformed value (e.g., `"$285,000"`, `"N/A"`, `"TBD"`, `"--"`) will throw an uncaught `NumberFormatException`, causing a 500 Internal Server Error on the API.

**Example Scenarios:**
- `LN_ORIG_AMT` = `"$285,000"` (dollar sign) -> `NumberFormatException`
- `BORR_CRDT_SCR` = `"N/A"` or `""` with whitespace -> `NumberFormatException`
- `LN_INT_RT` = `"VARIABLE"` (text instead of number) -> `NumberFormatException`
- `PMT_AMT` = `"1,487.02-"` (trailing minus from mainframe) -> `NumberFormatException`

**Business Impact:** A single corrupt record in the CDW causes the entire API endpoint to return a 500 error, making loan data inaccessible for all borrowers (in the `getAllLoans` case). No graceful degradation exists.

**Recommended Fix:** Wrap all parse methods in try-catch blocks. Return a safe default (e.g., `BigDecimal.ZERO`) for unparseable amounts and log a warning. For critical fields like `currentBalance`, mark the record as requiring manual review rather than silently defaulting.

---

## ANO-004: No Foreign Key Constraints Enable Orphaned Records

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ID`, `PROD_CD`, `LN_ACCT_NBR` |

**Description:** The legacy schema explicitly has no foreign key constraints (noted in schema comments). This means:
- `CDW_LN_ACCT.BORR_ID` can reference a non-existent borrower
- `CDW_LN_ACCT.PROD_CD` can reference a non-existent product
- `CDW_PMT_HIST.LN_ACCT_NBR` can reference a non-existent loan

In `LoanService.getAllLoans()`, the product lookup `products.get(acct.getProductCode())` returns null for unknown product codes, which is handled with a fallback. However, no such validation exists for borrower references.

**Example Scenario:** If a loan account references `BORR_ID = 'B-99999'` (non-existent), the API still returns the loan using the denormalized name fields, silently hiding the orphan.

**Business Impact:** Orphaned loan accounts cannot be traced to a borrower master record. During migration to the modern normalized schema, FK lookups will fail for orphaned records, causing data loss or migration errors.

**Recommended Fix:** Add referential integrity validation at the service layer. Before returning loan data, verify that `BORR_ID` exists in borrower master and `PROD_CD` exists in product table. Log warnings for orphaned records.

---

## ANO-005: Active Loan with Non-Zero Delinquency Days

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_STAT_CD`, `LN_DLQ_DAYS` |

**Description:** Loan `LN-2018-00089` has status `ACT` (Active) but `LN_DLQ_DAYS = '15'`. An active loan with 15 days delinquent should trigger a status transition. This is corroborated by payment `PMT-2025110003` which was received 17 days late (received 11/18 for 11/01 payment) and carries a $47.50 late fee.

**Example Bad Record:**

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Late Payment Evidence |
|-------------|------------|-------------|----------------------|
| LN-2018-00089 | ACT | 15 | PMT-2025110003: due 11/01, received 11/18, late fee $47.50 |

**Business Impact:** Delinquent loans reported as active distort portfolio risk metrics. Regulatory reporting (call reports, HMDA) would misrepresent the delinquency rate. Collections workflows may not be triggered for this borrower.

**Recommended Fix:** Add business rule validation: if `LN_DLQ_DAYS > 0` and `LN_STAT_CD = 'ACT'`, flag the record and log a warning. Consider status transitions: 30+ days -> early delinquency, 60+ -> serious delinquency, 90+ -> default.

---

## ANO-006: Date Fields Stored as Unvalidated VARCHAR Strings

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | All tables |
| **Affected Columns** | All `*_DT` columns (18 total) |

**Description:** All date fields are stored as `VARCHAR(10)` with an expected format of `MM/DD/YYYY`. The service layer passes date strings directly to API DTOs without parsing or validation. Invalid dates like `"13/32/2025"`, `"02/29/2023"` (non-leap year), or `"00/00/0000"` would be served to API consumers as-is.

Additionally, the `findByLoanAccountNumberOrderByPaymentDateDesc` repository method sorts by `PMT_DT` as a string, which produces incorrect ordering for dates spanning different years (e.g., `"12/15/2024"` sorts before `"01/15/2025"` lexicographically).

**Example Scenario:**
- `PMT_DT = '13/45/2025'` would be returned in the API response unchecked
- Payments from 2024 and 2025 would sort incorrectly

**Business Impact:** API consumers receive unvalidated date strings that may cause downstream parsing failures. Incorrect payment ordering could mislead borrowers viewing payment history.

**Recommended Fix:** Parse all date strings with `DateTimeFormatter.ofPattern("MM/dd/yyyy")` at the service layer. Return `null` or a sentinel value for unparseable dates. Log warnings for invalid dates.

---

## ANO-007: Nullable Required Fields with No Schema Constraints

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_MID_INIT`, `BORR_ADDR_LN2` |

**Description:** The schema defines no `NOT NULL` constraints on any column except primary keys. Business-critical fields like borrower first/last name can be null. The service layer concatenates names without null checks in `toLoanSummary`: `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`, which would produce `"null null"` for a borrower with null names.

**Example Current Data:**
- `B-10005`: `BORR_MID_INIT = NULL` (handled by conditional in `toBorrowerDto`)
- `B-10002`, `B-10003`, `B-10005`: `BORR_ADDR_LN2 = NULL`

**Business Impact:** Null first/last names produce `"null null"` in API responses, confusing UI consumers. Null address fields are less critical but still affect correspondence and compliance reporting.

**Recommended Fix:** Add null-safe string handling for name concatenation. Validate that required fields (first name, last name, borrower ID) are non-null before processing. Return a meaningful default or flag the record.

---

## ANO-008: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM` (duplicated in both tables) |

**Description:** Borrower names are stored in both `CDW_BORR_MSTR` and `CDW_LN_ACCT` (denormalized). When a borrower's name changes (e.g., marriage), the master record may be updated while the loan account's embedded copy becomes stale. Currently the data is consistent, but no mechanism prevents drift.

The API uses the denormalized names from `CDW_LN_ACCT` for loan summaries (`toLoanSummary`) but the master names from `CDW_BORR_MSTR` for borrower details (`toBorrowerDto`), so a single borrower could appear with different names in different API responses.

**Business Impact:** Inconsistent borrower names across endpoints degrade API consumer trust. Legal correspondence may use an outdated name.

**Recommended Fix:** Add cross-reference validation comparing `CDW_LN_ACCT.BORR_FST_NM/LST_NM` against `CDW_BORR_MSTR.BORR_FST_NM/LST_NM` for the same `BORR_ID`. Log warnings on mismatch.

---

## ANO-009: Incomplete Status Code Expansion

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_STAT_CD` |

**Description:** The `column_mappings.md` documents status expansion `ACT->ACTIVE, INA->INACTIVE` for borrower status codes. However, the `expandStatusCode` method in `LoanService` only handles loan status codes (ACT, CLO, DFT, FRB) and is not applied to borrower records at all -- `toBorrowerDto` does not include the borrower's status in the DTO output.

Additionally, the `expandStatusCode` fallback for unrecognized codes silently returns the raw code (e.g., `"INA"`) without logging, making it impossible to detect new or invalid status codes entering the system.

**Business Impact:** Borrower status is not exposed in the API, preventing consumers from filtering inactive borrowers. Unknown status codes silently pass through without alerting operators.

**Recommended Fix:** Add borrower status to `BorrowerDto`. Create a separate borrower status expansion method. Log warnings for unrecognized status codes in all expansion methods.

---

## ANO-010: Payment Late Fees Present but Not Reflected in Delinquency

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Tables** | `CDW_PMT_HIST`, `CDW_LN_ACCT` |
| **Affected Columns** | `PMT_LATE_FEE`, `LN_DLQ_DAYS` |

**Description:** Payment `PMT-2025110003` for loan `LN-2018-00089` has a late fee of $47.50 and was received 17 days after the due date. However, the delinquency days on the loan record shows `15`, not `17`. This suggests delinquency tracking is not synchronized with actual payment receipt.

**Business Impact:** Minor discrepancy in delinquency day tracking could compound over multiple payment periods, leading to inaccurate aging reports.

**Recommended Fix:** Add validation cross-referencing late fees against delinquency days. If a payment has a late fee, verify the loan's delinquency days reflect the actual delay.

---

## Summary

| ID | Title | Severity | Table(s) |
|----|-------|----------|----------|
| ANO-001 | SSN Last-4 Matches Phone Last-4 | Critical | CDW_LN_ACCT |
| ANO-002 | Payment Component Sum Mismatch | Critical | CDW_PMT_HIST |
| ANO-003 | Unhandled String-to-Numeric Parsing | Critical | All |
| ANO-004 | No FK Constraints / Orphaned Records | High | CDW_LN_ACCT, CDW_PMT_HIST |
| ANO-005 | Active Loan with Delinquency Days | High | CDW_LN_ACCT |
| ANO-006 | Unvalidated Date Strings | High | All |
| ANO-007 | Nullable Required Fields | Medium | CDW_BORR_MSTR, CDW_LN_ACCT |
| ANO-008 | Denormalized Data Drift Risk | Medium | CDW_BORR_MSTR, CDW_LN_ACCT |
| ANO-009 | Incomplete Status Code Expansion | Medium | CDW_BORR_MSTR |
| ANO-010 | Late Fees vs Delinquency Mismatch | Low | CDW_PMT_HIST, CDW_LN_ACCT |
