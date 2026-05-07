# Data Anomaly Report — Legacy CDW Tables

> **Generated:** 2026-05-07
> **Scope:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`
> **Service:** loan-service (Spring Boot)

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2     |
| High     | 4     |
| Medium   | 3     |
| Low      | 1     |

---

## ANO-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:**
Payment component amounts (principal + interest + escrow + late fee) do not sum to the stated total payment amount for multiple records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | Principal + Interest + Escrow + Late Fee | Difference |
|-------------|---------|------------------------------------------|------------|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | **+47.50** |

For `PMT-2025120001` and `PMT-2025110001` (loan `LN-2019-00142`), escrow is systematically excluded from the total. For `PMT-2025110003`, the late fee is excluded. The remaining 7 records sum correctly.

**Business Impact:**
Financial reporting produces incorrect payment breakdowns. Downstream systems relying on the total amount will under-report collections by up to $400/payment. Regulatory reporting and escrow account reconciliation will fail.

**Recommended Fix:**
Add a validation rule that asserts `PMT_AMT == PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` at ingestion time. Flag mismatches for manual review. Recompute the total from components when the discrepancy is detected.

---

## ANO-002: SSN Last-4 Matches Phone Last-4 (PII Corruption)

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` (cross-referenced with `CDW_BORR_MSTR`) |
| **Affected Columns** | `BORR_SSN_LST4` (CDW_LN_ACCT), `BORR_PH_NBR` (CDW_BORR_MSTR) |

**Description:**
Every borrower's SSN last-4 digits in the loan account table exactly matches the last 4 digits of their phone number in the borrower master table.

**Example Bad Records:**

| BORR_ID | BORR_SSN_LST4 | BORR_PH_NBR | Match? |
|---------|---------------|-------------|--------|
| B-10001 | 0142 | 217-555-**0142** | Yes |
| B-10002 | 0198 | 503-555-**0198** | Yes |
| B-10003 | 0167 | 512-555-**0167** | Yes |
| B-10004 | 0134 | 303-555-**0134** | Yes |
| B-10005 | 0156 | 602-555-**0156** | Yes |

A 100% match rate across all records is statistically impossible for real data, indicating either a data generation bug that leaked placeholder data into production, or a copy-paste error in an ETL pipeline.

**Business Impact:**
If these SSN values are serving downstream identity verification, credit checks, or regulatory reports, they are returning fabricated data. This is a potential compliance violation (GLBA, FCRA).

**Recommended Fix:**
Flag all `BORR_SSN_LST4` values where the last 4 digits match `BORR_PH_NBR`. Quarantine affected records and cross-reference against the encrypted SSN (`BORR_SSN_ENCR`) in the borrower master to derive the correct last-4.

---

## ANO-003: Delinquency Days vs. Status Code Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:**
Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). Per standard mortgage servicing rules, a loan 15+ days past due should reflect a delinquency status or at minimum a warning flag. The associated payment `PMT-2025110003` confirms the delinquency with a late fee of $47.50 and a received date 17 days after the due date.

**Example Bad Records:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Late Fee on Recent Payment |
|-------------|-------------|------------|---------------------------|
| LN-2018-00089 | 15 | ACT | $47.50 (PMT-2025110003) |

**Business Impact:**
Delinquent loans reported as "Active" will be excluded from delinquency reports, distorting portfolio risk metrics and potentially violating regulatory reporting requirements (HMDA, Call Reports).

**Recommended Fix:**
Validate that `LN_DLQ_DAYS > 0` implies `LN_STAT_CD` is not `'ACT'`, or add a separate delinquency flag. Apply business rule: DLQ_DAYS >= 30 triggers status change to `'DLQ'`, >= 90 to `'DFT'`.

---

## ANO-004: No Foreign Key Constraints (Orphan Risk)

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:**
The legacy schema declares zero foreign key constraints. Any of the following could exist without detection:
- A loan account referencing a non-existent borrower ID
- A loan account referencing a non-existent product code
- A payment referencing a non-existent loan account number

The service layer in `LoanService.java` (line 62) does `loanProductRepository.findById(acct.getProductCode()).orElse(null)` — returning null for missing products and silently displaying the raw product code instead of a description.

**Example Scenario:**
If a `CDW_PMT_HIST` record references loan account `LN-9999-00000` (which doesn't exist), the `getPaymentsByLoan` endpoint would return payments for a non-existent loan without error.

**Business Impact:**
Orphaned records corrupt aggregation queries, cause silent null pointer exceptions in the service layer, and produce incorrect loan portfolio summaries.

**Recommended Fix:**
Validate referential integrity at ingestion time: verify `BORR_ID` exists in `CDW_BORR_MSTR`, `PROD_CD` exists in `CDW_LN_PROD`, and `LN_ACCT_NBR` exists in `CDW_LN_ACCT` before accepting records.

---

## ANO-005: All-VARCHAR Typing with Numeric Parsing Risks

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_DLQ_DAYS`, `LN_LTV_PCT`, `PROD_TERM_MOS`, `PMT_AMT`, etc. |

**Description:**
All numeric values are stored as `VARCHAR` with embedded formatting (commas in amounts, no validation). The service layer parses these with `BigDecimal(amount.replace(",", ""))` and `Integer.parseInt(value.trim())` — neither of which handles:
- Currency symbols (`$285,000`)
- Spaces or non-breaking spaces
- Alphabetic characters mixed in (`285,O00` — letter O instead of zero)
- Empty strings that aren't blank (e.g., a single space)

Any of these malformations cause an unhandled `NumberFormatException` that propagates as a 500 Internal Server Error.

**Example Risk Values:**

| Column | Current Value | Risk Scenario |
|--------|---------------|---------------|
| `BORR_CRDT_SCR` | "745" | "N/A" or "pending" would throw NumberFormatException |
| `BORR_ANN_INCM` | "92,500" | "$92,500" would throw NumberFormatException |
| `LN_ORIG_AMT` | "285,000" | "285 000" (space separator) would throw NumberFormatException |

**Business Impact:**
A single malformed record causes the entire API endpoint to fail with HTTP 500, taking down the service for all borrowers/loans, not just the bad record.

**Recommended Fix:**
Wrap all parsing in try-catch blocks with fallback defaults. Log warnings for unparseable values. Return null or a sentinel value rather than crashing.

---

## ANO-006: Date String Sorting Bug in Repository

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT` |

**Description:**
The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` generates an `ORDER BY PMT_DT DESC` SQL clause. Since `PMT_DT` is stored as `VARCHAR` in `MM/DD/YYYY` format, the ordering is lexicographic, not chronological.

**Example Incorrect Sort (cross-year):**

| PMT_DT (VARCHAR) | Lexicographic Order (DESC) | Correct Chronological Order (DESC) |
|-------------------|---------------------------|-------------------------------------|
| "12/15/2024" | 1st (highest) | 2nd |
| "02/15/2025" | 2nd | 1st |

`"12/15/2024"` > `"02/15/2025"` lexicographically because `'1' > '0'`, but chronologically Feb 2025 is after Dec 2024.

Current seed data happens to work because all payments are within the same two months (Nov-Dec 2025), but cross-year or cross-month queries will return incorrectly ordered results.

**Business Impact:**
Payment history displayed to borrowers or used for amortization calculations will be out of order, leading to incorrect "most recent payment" lookups and wrong next-payment-date calculations.

**Recommended Fix:**
Parse date strings to `LocalDate` in the service layer before sorting, or convert the column to a proper `DATE` type. In the interim, validate date format at ingestion and reject non-conforming dates.

---

## ANO-007: Denormalized Borrower Data Drift

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:**
`CDW_LN_ACCT` duplicates borrower first name, last name, and SSN last-4 from `CDW_BORR_MSTR`. If a borrower's name changes in the master table (e.g., after marriage), the loan account table retains the old name. There is no mechanism to keep these in sync.

The service layer uses the denormalized names from `CDW_LN_ACCT` (line 106: `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`) rather than joining to the borrower master, so the API will return stale names.

**Example:**
Current data is consistent, but the architecture guarantees eventual drift in a live system.

**Business Impact:**
Borrower correspondence, statements, and reports may display outdated names, causing customer confusion and potential legal issues with loan documents.

**Recommended Fix:**
In the service layer, always fetch the borrower name from `CDW_BORR_MSTR` via the `BORR_ID` foreign key rather than using the denormalized copy. Add a reconciliation check that flags mismatches.

---

## ANO-008: Inconsistent Late Fee Inclusion in Payment Totals

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_LATE_FEE` |

**Description:**
Late fees are sometimes included in the total payment amount and sometimes excluded. This overlaps with ANO-001 but specifically concerns the late fee handling convention.

| PMT_SEQ_NBR | Total | Components (no late fee) | Late Fee | Sum w/ Late Fee | Convention |
|-------------|-------|--------------------------|----------|-----------------|------------|
| PMT-2025110003 | 1,077.05 | 295.82 + 781.23 + 0.00 = 1,077.05 | 47.50 | 1,124.55 | Late fee **excluded** from total |
| All others with $0 late fee | Match | Match | 0.00 | Match | N/A |

**Business Impact:**
Inconsistent convention makes it impossible to determine whether the total amount represents the base payment or the full amount collected, affecting cash application and general ledger posting.

**Recommended Fix:**
Standardize the convention: total should always equal principal + interest + escrow + late fee. Add validation at ingestion time.

---

## ANO-009: No NOT NULL Constraints on Business-Critical Fields

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All columns except primary keys |

**Description:**
The legacy schema defines all non-PK columns as nullable `VARCHAR`. Business-critical fields like `BORR_FST_NM`, `BORR_LST_NM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `PMT_AMT`, `LN_STAT_CD` can all be NULL.

The service layer handles some null cases (e.g., `parseLegacyAmount` returns `BigDecimal.ZERO` for null) but not all. For example, `toBorrowerDto` (line 124) concatenates `borrower.getFirstName()` without a null check — a null first name produces `"null R. Mitchell"`.

**Example Risk:**
A borrower record with `BORR_FST_NM = NULL` would produce `borrowerName = "null Mitchell"` in the API response.

**Business Impact:**
Null values in required fields corrupt API responses and downstream data consumers. Financial calculations on null amounts silently default to zero, masking data quality issues.

**Recommended Fix:**
Add null checks and validation for all business-critical fields at ingestion time. Reject or quarantine records missing required values.

---

## ANO-010: Null Middle Initial Handling

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT` |

**Description:**
Borrower `B-10005` (Robert Williams) has a NULL middle initial. The service layer handles this correctly with a ternary check (line 123), but there is no consistent convention — some records have a middle initial and some don't, with no way to distinguish "unknown" from "not applicable."

**Example:**
| BORR_ID | BORR_MID_INIT | Full Name Output |
|---------|---------------|------------------|
| B-10001 | R | "James R. Mitchell" |
| B-10005 | NULL | "Robert Williams" |

**Business Impact:**
Minimal. Name formatting works correctly. However, downstream systems that require a middle initial field may interpret NULL differently (empty string vs. absent).

**Recommended Fix:**
Normalize NULL middle initials to an empty string at ingestion time for consistency. Document the convention.

---

## Appendix: Anomaly Summary Table

| ID | Title | Severity | Table | Key Columns | Records Affected |
|----|-------|----------|-------|-------------|------------------|
| ANO-001 | Payment Component Sum Mismatch | Critical | CDW_PMT_HIST | PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE | 3 of 10 (30%) |
| ANO-002 | SSN Last-4 Matches Phone Last-4 | Critical | CDW_LN_ACCT / CDW_BORR_MSTR | BORR_SSN_LST4, BORR_PH_NBR | 5 of 5 (100%) |
| ANO-003 | Delinquency vs. Status Inconsistency | High | CDW_LN_ACCT | LN_DLQ_DAYS, LN_STAT_CD | 1 of 5 (20%) |
| ANO-004 | No Foreign Key Constraints | High | CDW_LN_ACCT, CDW_PMT_HIST | BORR_ID, PROD_CD, LN_ACCT_NBR | Structural |
| ANO-005 | Numeric String Parsing Risks | High | All | All numeric VARCHAR columns | Structural |
| ANO-006 | Date String Sorting Bug | High | CDW_PMT_HIST | PMT_DT | Structural |
| ANO-007 | Denormalized Borrower Data Drift | Medium | CDW_LN_ACCT | BORR_FST_NM, BORR_LST_NM | Structural |
| ANO-008 | Inconsistent Late Fee in Totals | Medium | CDW_PMT_HIST | PMT_AMT, PMT_LATE_FEE | 1 of 10 (10%) |
| ANO-009 | No NOT NULL on Required Fields | Medium | All | All non-PK columns | Structural |
| ANO-010 | Null Middle Initial Handling | Low | CDW_BORR_MSTR | BORR_MID_INIT | 1 of 5 (20%) |
