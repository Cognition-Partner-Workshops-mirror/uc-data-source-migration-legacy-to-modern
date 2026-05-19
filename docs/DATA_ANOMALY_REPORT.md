# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql`, `data-legacy.sql`, and `column_mappings.md`

---

## ANO-001: Payment Component Amounts Do Not Sum to Total

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | Critical                                                              |
| **Affected Table** | `CDW_PMT_HIST`                                                     |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:**
The total payment amount (`PMT_AMT`) does not equal the sum of its component parts
(`PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`) in several records.

**Example Bad Records:**

| PMT_SEQ_NBR      | PMT_AMT   | PRIN    | INT      | ESCROW | LATE_FEE | Computed Sum | Discrepancy |
|-------------------|-----------|---------|----------|--------|----------|-------------|-------------|
| PMT-2025120001    | 1,487.02  | 456.78  | 1,074.69 | 355.55 | 0.00     | 1,887.02    | +400.00     |
| PMT-2025110001    | 1,487.02  | 454.97  | 1,076.50 | 355.55 | 0.00     | 1,887.02    | +400.00     |
| PMT-2025110003    | 1,077.05  | 295.82  | 781.23   | 0.00   | 47.50    | 1,124.55    | +47.50      |

**Business Impact:**
Financial reporting will produce incorrect totals. Downstream systems relying on component
breakdown for accounting (principal vs. interest allocation for tax reporting, escrow
analysis) will have inconsistent data. This can lead to regulatory compliance failures and
incorrect borrower statements.

**Recommended Fix:**
Add a validation check at ingestion time that verifies `total == principal + interest + escrow + late_fee`.
Flag mismatched records for manual review and log warnings. Do not silently accept mismatched amounts.

---

## ANO-002: SSN Last-4 Digits Match Phone Number Last-4 Digits (Systematic Data Corruption)

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | Critical                                                              |
| **Affected Table** | `CDW_LN_ACCT`                                                      |
| **Affected Columns** | `BORR_SSN_LST4`, cross-referenced with `CDW_BORR_MSTR.BORR_PH_NBR` |

**Description:**
Every record in `CDW_LN_ACCT` has a `BORR_SSN_LST4` value that exactly matches the last 4
digits of the borrower's phone number from `CDW_BORR_MSTR`. This indicates the SSN field was
systematically populated from the phone number column — a catastrophic data integrity failure.

**Example Bad Records:**

| BORR_ID  | BORR_SSN_LST4 (in CDW_LN_ACCT) | BORR_PH_NBR (in CDW_BORR_MSTR) | Phone Last-4 |
|----------|----------------------------------|---------------------------------|--------------|
| B-10001  | 0142                             | 217-555-0142                    | 0142         |
| B-10002  | 0198                             | 503-555-0198                    | 0198         |
| B-10003  | 0167                             | 512-555-0167                    | 0167         |
| B-10004  | 0134                             | 303-555-0134                    | 0134         |
| B-10005  | 0156                             | 602-555-0156                    | 0156         |

**Business Impact:**
SSN last-4 is commonly used for borrower identity verification. If this data is used for
verification purposes, it would accept a phone number as a valid SSN match. This is both a
**PII integrity violation** and a **security risk** — identity verification based on this
field is completely unreliable.

**Recommended Fix:**
Flag `BORR_SSN_LST4` as untrusted. Cross-validate against the encrypted SSN in
`CDW_BORR_MSTR.BORR_SSN_ENCR` before use. Add validation that SSN last-4 does not match
the borrower's phone number last-4 digits. During migration, derive SSN last-4 from the
encrypted SSN source rather than the denormalized loan account field.

---

## ANO-003: Delinquency Days > 0 with Active Status

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | High                                                                  |
| **Affected Table** | `CDW_LN_ACCT`                                                      |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD`                                      |

**Description:**
Loan account `LN-2018-00089` has `LN_DLQ_DAYS = '15'` while `LN_STAT_CD = 'ACT'` (Active).
A loan with 15 days delinquency should trigger a status transition or at minimum carry
a delinquency indicator. The corroborating payment record (`PMT-2025110003`) shows a late fee
of $47.50 and was received 17 days after the due date (due 11/01, received 11/18).

**Example Bad Records:**

| LN_ACCT_NBR   | LN_DLQ_DAYS | LN_STAT_CD | Corroborating Payment        |
|----------------|-------------|------------|------------------------------|
| LN-2018-00089  | 15          | ACT        | PMT-2025110003: late_fee=$47.50, recv 11/18 for 11/01 due date |

**Business Impact:**
Risk assessment and portfolio reporting will understate delinquency exposure. Loans with
active delinquency that show as "Active" will not be flagged in early warning systems,
potentially delaying collections outreach and loss mitigation.

**Recommended Fix:**
Add cross-field validation: if `LN_DLQ_DAYS > 0`, status should not be plain "ACT" without
an additional delinquency indicator. Consider adding a derived status like "ACT-DLQ" or
requiring status transition to "DFT" when delinquency exceeds a threshold (e.g., 30 days).

---

## ANO-004: All Numeric Fields Stored as VARCHAR — Parsing Failure Risk

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | High                                                                  |
| **Affected Table** | All tables (`CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST`) |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_TERM_MOS`, `LN_DLQ_DAYS`, `LN_LTV_PCT`, `PMT_AMT`, all payment amounts, `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT` |

**Description:**
Every numeric field in the schema is declared as `VARCHAR`. Values contain formatting
characters (commas in amounts like `'92,500'`, `'285,000'`) that require stripping before
parsing. The current `LoanService` uses `Integer.parseInt()` and `new BigDecimal()` without
try-catch blocks — any unexpected character (e.g., `$`, letters, extra whitespace) will cause
an unhandled `NumberFormatException` that crashes the API endpoint.

**Example Risky Fields:**

| Table          | Column        | Example Value | Target Type | Risk                           |
|----------------|---------------|--------------|-------------|--------------------------------|
| CDW_BORR_MSTR  | BORR_CRDT_SCR | '745'        | Integer     | Non-numeric string → crash     |
| CDW_BORR_MSTR  | BORR_ANN_INCM | '92,500'     | Decimal     | Commas must be stripped         |
| CDW_LN_ACCT    | LN_ORIG_AMT   | '285,000'    | Decimal     | Commas must be stripped         |
| CDW_LN_ACCT    | LN_INT_RT     | '4.750'      | Decimal     | Leading/trailing spaces → crash |
| CDW_LN_ACCT    | LN_LTV_PCT    | '82.5'       | Decimal     | Commas/symbols → crash         |

**Business Impact:**
A single malformed record in the legacy warehouse can bring down the entire API endpoint,
affecting all consumers. There is no graceful degradation — one bad record fails the
entire request.

**Recommended Fix:**
Wrap all parsing in try-catch with logging. Use fallback defaults (e.g., `BigDecimal.ZERO`
for amounts, `null` for credit scores) and log warnings for unparseable values rather than
crashing the service.

---

## ANO-005: Date Strings Stored as MM/DD/YYYY — Sort and Parse Failures

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | High                                                                  |
| **Affected Table** | All tables                                                          |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PROD_EFF_DT`, `PROD_EXP_DT` |

**Description:**
All date fields are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. This causes two problems:
1. **Lexicographic sorting is incorrect:** The repository method
   `findByLoanAccountNumberOrderByPaymentDateDesc` sorts by `PMT_DT` as a string.
   `MM/DD/YYYY` strings do not sort chronologically across different months/years
   (e.g., `"02/01/2026"` < `"12/01/2025"` as strings, but chronologically 02/01/2026 is later).
2. **No format validation:** Malformed dates (e.g., `"13/32/2025"`, `"2025-01-01"`) would be
   accepted by the VARCHAR column and silently corrupted.

**Example:**
Payment history for loan `LN-2019-00142` could return November before December in a
cross-year query because `"11/"` < `"12/"` as strings.

**Business Impact:**
Payment history displayed to borrowers or used for delinquency calculations may appear in
wrong order. Date parsing during migration would fail for any records with non-MM/DD/YYYY
formats.

**Recommended Fix:**
Parse date strings to `java.time.LocalDate` at ingestion time with explicit
`DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Catch `DateTimeParseException` and log invalid
dates. For sort correctness, convert to proper date types before ordering.

---

## ANO-006: No Foreign Key Constraints — Orphaned Records Possible

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | Medium                                                                |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST`                                     |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:**
The schema explicitly has no foreign key constraints (noted in the schema header). This means:
- A loan account can reference a `BORR_ID` that does not exist in `CDW_BORR_MSTR`
- A loan account can reference a `PROD_CD` that does not exist in `CDW_LN_PROD`
- A payment can reference an `LN_ACCT_NBR` that does not exist in `CDW_LN_ACCT`

The `LoanService.getLoanById()` does a product lookup with `orElse(null)`, which would
silently produce a loan summary with just the product code instead of a description — a
silent data quality degradation.

**Example Risk:**
If `CDW_LN_ACCT` contained a record with `PROD_CD = 'XYZ'`, the `products.get("XYZ")` call
in `getAllLoans()` would return `null`, and `toLoanSummary()` would fall back to displaying
the raw code. No error would be logged.

**Business Impact:**
Orphaned records produce incomplete or misleading API responses without any indication that
referenced data is missing. Loan summaries may show raw codes instead of descriptions,
confusing end users.

**Recommended Fix:**
Add referential integrity validation at ingestion time. Verify that every `BORR_ID` in
loan accounts exists in the borrower table, every `PROD_CD` exists in products, and every
`LN_ACCT_NBR` in payments exists in loan accounts. Log warnings for orphaned references.

---

## ANO-007: Denormalized Borrower Data in Loan Accounts — Drift Risk

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | Medium                                                                |
| **Affected Table** | `CDW_LN_ACCT`                                                      |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`                   |

**Description:**
Borrower first name, last name, and SSN last-4 are duplicated in the loan account table.
If a borrower's name is updated in `CDW_BORR_MSTR` (e.g., name change after marriage), the
denormalized copies in `CDW_LN_ACCT` will be stale. The `LoanService.toLoanSummary()` method
uses the denormalized `BORR_FST_NM`/`BORR_LST_NM` from the loan account rather than looking
up the current name from the borrower master.

**Example Risk:**
Borrower B-10002 "Sarah Chen" changes name to "Sarah Chen-Williams". The loan account
`LN-2020-00398` would still show "Sarah Chen" while the borrower endpoint shows the
updated name.

**Business Impact:**
Inconsistent borrower names across different API endpoints. Legal documents or correspondence
generated from loan data may use outdated names.

**Recommended Fix:**
During validation, cross-check denormalized fields against the master table and log
discrepancies. In the service layer, prefer the borrower master table as the source of
truth for borrower name.

---

## ANO-008: Payment Late Fee Present but Escrow Amount Zero for Escrowed Loan

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | Medium                                                                |
| **Affected Table** | `CDW_PMT_HIST`                                                     |
| **Affected Columns** | `PMT_ESCROW_AMT`, `PMT_LATE_FEE`                                 |

**Description:**
Loan `LN-2018-00089` has an escrow balance of `$2,100.00` in the loan account, but all
payment records for this loan show `PMT_ESCROW_AMT = '0.00'`. Meanwhile, the November
payment carries a late fee of `$47.50`. If the loan has an escrow account, payments should
include an escrow component.

**Example Bad Records:**

| PMT_SEQ_NBR   | LN_ACCT_NBR   | PMT_ESCROW_AMT | Loan Escrow Balance |
|---------------|----------------|-----------------|---------------------|
| PMT-2025120003 | LN-2018-00089 | 0.00            | 2,100.00            |
| PMT-2025110003 | LN-2018-00089 | 0.00            | 2,100.00            |

**Business Impact:**
Escrow analysis and impound account reconciliation will fail. The escrow balance exists but
no payments are contributing to it — the balance source is unexplained.

**Recommended Fix:**
Add cross-validation: if a loan has a non-zero escrow balance, warn when payments
consistently show zero escrow amounts. Flag for manual review.

---

## ANO-009: Annual Income Not Exposed in API — Silent Data Loss

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | Low                                                                   |
| **Affected Table** | `CDW_BORR_MSTR`                                                    |
| **Affected Columns** | `BORR_ANN_INCM`                                                  |

**Description:**
The `toBorrowerDto()` method in `LoanService.java` does not map the borrower's annual income
(`BORR_ANN_INCM`) to the `BorrowerDto`. The DTO does not have an `annualIncome` field.
This means the income data is read from the database but silently dropped in the API response.

**Business Impact:**
API consumers cannot access borrower income data for debt-to-income calculations,
affordability assessments, or underwriting decisions.

**Recommended Fix:**
Add `annualIncome` (as `BigDecimal`) to `BorrowerDto` and map it in `toBorrowerDto()` using
the existing `parseLegacyAmount()` method.

---

## ANO-010: Null Middle Initial Handling Produces Inconsistent Name Formatting

| Field            | Value                                                                 |
|------------------|-----------------------------------------------------------------------|
| **Severity**     | Low                                                                   |
| **Affected Table** | `CDW_BORR_MSTR`                                                    |
| **Affected Columns** | `BORR_MID_INIT`                                                   |

**Description:**
Borrower B-10005 (Robert Williams) has `BORR_MID_INIT = NULL`. The `toBorrowerDto()` method
handles this by conditionally including the middle initial, but the `toLoanSummary()` method
uses `BORR_FST_NM + " " + BORR_LST_NM` from the denormalized loan account fields — a
different format than the borrower endpoint which includes the middle initial.

**Example:**
- Borrower endpoint: `"James R. Mitchell"` (with middle initial)
- Loan summary: `"James Mitchell"` (without middle initial)
- Borrower B-10005: `"Robert Williams"` (consistent, since no middle initial)

**Business Impact:**
Minor — name format inconsistency between endpoints may cause confusion in UI displays
or customer communications.

**Recommended Fix:**
Standardize name construction. Either always include middle initial from the borrower master
table, or consistently omit it from both endpoints.

---

## Summary Table

| ID      | Title                                              | Severity | Table(s)                    |
|---------|----------------------------------------------------|----------|-----------------------------|
| ANO-001 | Payment components don't sum to total              | Critical | CDW_PMT_HIST                |
| ANO-002 | SSN last-4 matches phone last-4 (data corruption)  | Critical | CDW_LN_ACCT / CDW_BORR_MSTR |
| ANO-003 | Delinquency > 0 with Active status                | High     | CDW_LN_ACCT                 |
| ANO-004 | Numeric fields as VARCHAR — parse crash risk       | High     | All tables                  |
| ANO-005 | Date strings — incorrect sort & parse risk         | High     | All tables                  |
| ANO-006 | No FK constraints — orphaned records possible      | Medium   | CDW_LN_ACCT, CDW_PMT_HIST   |
| ANO-007 | Denormalized borrower data — drift risk            | Medium   | CDW_LN_ACCT                 |
| ANO-008 | Zero escrow payments for escrowed loan             | Medium   | CDW_PMT_HIST                |
| ANO-009 | Annual income not exposed in API                   | Low      | CDW_BORR_MSTR               |
| ANO-010 | Inconsistent name formatting across endpoints      | Low      | CDW_BORR_MSTR / CDW_LN_ACCT |
