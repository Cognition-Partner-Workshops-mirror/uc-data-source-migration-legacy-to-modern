# Data Anomaly Report — Legacy CDW Tables

This report documents data quality anomalies discovered in the legacy Corporate Data Warehouse
(CDW) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`).

---

## ANO-001: Payment Component Sum Mismatch

| Field            | Value |
|------------------|-------|
| **Severity**     | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:**
The total payment amount (`PMT_AMT`) does not equal the sum of its component parts
(principal + interest + escrow + late fee) for multiple payment records.

**Example Bad Records:**

| PMT_SEQ_NBR      | PMT_AMT   | Principal | Interest  | Escrow  | Late Fee | Computed Sum | Delta    |
|-------------------|-----------|-----------|-----------|---------|----------|--------------|----------|
| PMT-2025120001   | 1,487.02  | 456.78    | 1,074.69  | 355.55  | 0.00     | 1,887.02     | -400.00  |
| PMT-2025110001   | 1,487.02  | 454.97    | 1,076.50  | 355.55  | 0.00     | 1,887.02     | -400.00  |
| PMT-2025110003   | 1,077.05  | 295.82    | 781.23    | 0.00    | 47.50    | 1,124.55     | -47.50   |

**Business Impact:**
Financial reporting, loan balance reconciliation, and escrow accounting will be incorrect.
API consumers relying on `totalAmount` to cross-check component sums will encounter silent
discrepancies. Regulatory audits (TILA, RESPA) require accurate payment breakdowns.

**Recommended Fix:**
Add a validation check at ingestion that compares `PMT_AMT` against the sum of component
amounts. When a mismatch is detected, either flag the record for manual review or recompute
the total from the components and log a warning.

---

## ANO-002: Uncaught NumberFormatException on Malformed Numeric Strings

| Field            | Value |
|------------------|-------|
| **Severity**     | Critical |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `LN_LTV_PCT`, `PMT_AMT`, and all payment amount columns |

**Description:**
All financial amounts, credit scores, and numeric fields are stored as `VARCHAR` strings.
The service layer methods `parseLegacyAmount()`, `parseLegacyDecimal()`, and
`parseLegacyInteger()` perform direct parsing (`new BigDecimal(...)`, `Integer.parseInt(...)`)
with no try-catch. Any non-numeric character (currency symbols like `$`, text like `N/A`,
extra spaces, or encoding artifacts) will throw an uncaught `NumberFormatException`, resulting
in a 500 Internal Server Error.

**Example Risk Scenarios:**
- A legacy record with `BORR_ANN_INCM = '$92,500'` (dollar sign included) will fail on `BigDecimal` parse
- A record with `BORR_CRDT_SCR = 'N/A'` or empty string will fail on `Integer.parseInt`
- A record with `LN_INT_RT = '5.250%'` (percent sign included) will fail on `BigDecimal` parse
- Encoding corruption producing `LN_CURR_BAL = '271,432\u00A056'` (non-breaking space)

**Business Impact:**
A single malformed record causes the entire API endpoint to fail with an unhandled 500 error.
`GET /api/loans` and `GET /api/borrowers` both call `findAll()`, meaning one bad record
prevents all records from being returned.

**Recommended Fix:**
Wrap all parsing methods in try-catch blocks. On parse failure, log a warning with the
record ID and field name, and return a safe fallback (e.g., `BigDecimal.ZERO` for amounts,
`null` for optional integers). Add a `ValidationResult` concept that tracks which records
had parse issues.

---

## ANO-003: Delinquent Loan Flagged as Active

| Field            | Value |
|------------------|-------|
| **Severity**     | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_STAT_CD`, `LN_DLQ_DAYS` |

**Description:**
Loan `LN-2018-00089` (borrower Michael Torres) has `LN_DLQ_DAYS = '15'` indicating
15 days of delinquency, but `LN_STAT_CD = 'ACT'` (Active). A loan with 15 days delinquency
should be flagged with a delinquent or watchlist status, not reported as "Active."

**Example Bad Records:**

| LN_ACCT_NBR     | LN_STAT_CD | LN_DLQ_DAYS | Expected Status |
|------------------|------------|-------------|-----------------|
| LN-2018-00089   | ACT        | 15          | DLQ or FRB      |

**Business Impact:**
The API returns `"status": "Active"` for a delinquent loan, masking credit risk.
Downstream risk assessment, collections workflows, and regulatory reporting
(delinquency rate calculations) will under-report delinquent loans.

**Recommended Fix:**
Add a cross-field validation rule: if `LN_DLQ_DAYS > 0` and `LN_STAT_CD = 'ACT'`,
flag the anomaly and either override the status to reflect delinquency or include
a `delinquencyWarning` field in the API response.

---

## ANO-004: No NOT NULL Constraints on Required Fields

| Field            | Value |
|------------------|-------|
| **Severity**     | High |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_ENCR`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `PMT_AMT` |

**Description:**
The legacy schema defines every non-PK column as nullable `VARCHAR`. Business-critical
fields like borrower name, SSN, loan amounts, and payment amounts have no `NOT NULL`
constraints, allowing null values to enter the system.

**Example Bad Records:**
- `B-10005` (Robert Williams): `BORR_MID_INIT = NULL` — handled in code, but demonstrates the nullable pattern
- `B-10002`, `B-10003`, `B-10005`: `BORR_ADDR_LN2 = NULL` — address line 2 can be legitimately null
- Any future insert with `BORR_FST_NM = NULL` would be accepted by the DB

**Business Impact:**
Null borrower names cause `NullPointerException` in `toBorrowerDto()` when concatenating
`borrower.getFirstName() + middle + " " + borrower.getLastName()`. Null loan amounts
default to `BigDecimal.ZERO` via `parseLegacyAmount`, silently reporting a $0 loan.

**Recommended Fix:**
Add null-checks for required fields at the service layer. For truly required fields
(first name, last name, loan amount), reject the record or substitute a sentinel value
(e.g., `"[MISSING]"`) and log a warning. For optional fields (middle initial, address line 2),
handle gracefully with safe defaults.

---

## ANO-005: Denormalized Borrower Data Drift Risk

| Field            | Value |
|------------------|-------|
| **Severity**     | High |
| **Affected Table** | `CDW_LN_ACCT` vs `CDW_BORR_MSTR` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_FST_NM`, `CDW_LN_ACCT.BORR_LST_NM`, `CDW_LN_ACCT.BORR_SSN_LST4` |

**Description:**
Borrower name and SSN last-4 are duplicated in both `CDW_BORR_MSTR` (authoritative) and
`CDW_LN_ACCT` (denormalized copy). With no referential integrity constraints and no
synchronization mechanism, these copies can drift apart over time (e.g., name change
after marriage, data correction in master but not in loan table).

**Example Records (currently matching but at risk):**

| Source           | BORR_ID  | First Name | Last Name | SSN Last 4 |
|------------------|----------|------------|-----------|------------|
| CDW_BORR_MSTR   | B-10001  | James      | Mitchell  | (encrypted)|
| CDW_LN_ACCT     | B-10001  | James      | Mitchell  | 0142       |

**Business Impact:**
The `toLoanSummary()` method reads borrower name from the loan account table (denormalized copy),
not from the borrower master. If these drift, the API returns stale borrower names on loan
summaries, creating identity mismatches for servicing, correspondence, and legal documents.

**Recommended Fix:**
At ingestion time, cross-reference borrower data in `CDW_LN_ACCT` against `CDW_BORR_MSTR`.
Log warnings on any mismatch. In the service layer, prefer the authoritative `CDW_BORR_MSTR`
data over the denormalized copy in `CDW_LN_ACCT`.

---

## ANO-006: No Foreign Key Constraints (Orphan Risk)

| Field            | Value |
|------------------|-------|
| **Severity**     | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:**
The legacy schema has zero foreign key constraints. Loan accounts reference borrowers
(`BORR_ID`) and products (`PROD_CD`), and payments reference loan accounts (`LN_ACCT_NBR`),
but none of these are enforced. Orphaned records (e.g., a payment referencing a deleted loan,
or a loan referencing a non-existent borrower) can exist.

**Example Risk Scenarios:**
- Insert `CDW_LN_ACCT` with `BORR_ID = 'B-99999'` (non-existent borrower) — accepted
- Insert `CDW_PMT_HIST` with `LN_ACCT_NBR = 'LN-0000-00000'` (non-existent loan) — accepted
- In code: `products.get(acct.getProductCode())` returns null for unknown product codes

**Business Impact:**
`getLoanById()` calls `loanProductRepository.findById(acct.getProductCode()).orElse(null)`.
If the product is null, `toLoanSummary()` falls back to `acct.getProductCode()` as the
description, returning a cryptic code like `"FXD30"` instead of a human-readable name.
Orphaned payments would appear in API results with no valid parent loan.

**Recommended Fix:**
Validate foreign key references at ingestion time. Verify that `BORR_ID` exists in
`CDW_BORR_MSTR`, `PROD_CD` exists in `CDW_LN_PROD`, and `LN_ACCT_NBR` exists in
`CDW_LN_ACCT` before processing. Log orphaned records and exclude them from API results.

---

## ANO-007: Dates Stored as Unparsed Strings in API Responses

| Field            | Value |
|------------------|-------|
| **Severity**     | Medium |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `LN_ORIG_DT`, `PMT_DT`, and all date columns |

**Description:**
All date fields are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. The service layer passes
`originationDate` and `paymentDate` directly to DTOs as raw strings without parsing them
to `java.time.LocalDate`. This means:
1. No validation that the date is actually a valid date (e.g., `"02/30/2020"` would be accepted)
2. API consumers receive US-formatted date strings instead of ISO-8601 (`yyyy-MM-dd`)
3. String comparison sorting (used by `ORDER BY` in payment queries) works incorrectly for dates
   spanning different months/years (e.g., `"02/01/2025"` < `"11/01/2024"` lexicographically)

**Example Bad Scenarios:**
- `"13/01/2025"` (invalid month 13) — accepted by DB, no parse validation
- `"02/29/2023"` (2023 is not a leap year) — accepted by DB, no parse validation
- Payment sort by `PMT_DT DESC` orders lexicographically, not chronologically

**Business Impact:**
API consumers expecting ISO-8601 dates will get locale-specific strings. Invalid dates
will propagate without error. Payment history ordering may be incorrect.

**Recommended Fix:**
Parse all date strings to `java.time.LocalDate` at ingestion time using
`DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Catch `DateTimeParseException` for invalid
dates. Return ISO-8601 formatted strings in API responses.

---

## ANO-008: Payment Received After Payment Date (Late Payment Indicator)

| Field            | Value |
|------------------|-------|
| **Severity**     | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_LATE_FEE` |

**Description:**
Some payments have `PMT_RECV_DT` significantly later than `PMT_DT`, indicating late
receipt. The late-fee field is inconsistently applied — one record is late but has no
late fee, while another has a late fee that causes a component sum mismatch (see ANO-001).

**Example Records:**

| PMT_SEQ_NBR      | PMT_DT     | PMT_RECV_DT | Days Late | PMT_LATE_FEE |
|-------------------|------------|-------------|-----------|--------------|
| PMT-2025120003   | 12/01/2025 | 12/05/2025  | 4         | 0.00         |
| PMT-2025110003   | 11/01/2025 | 11/18/2025  | 17        | 47.50        |

**Business Impact:**
Inconsistent late-fee application may indicate a business rule gap or data entry error.
The 4-day late payment with no fee may be within a grace period, but this is not documented
or validated in code.

**Recommended Fix:**
Add validation that checks if `PMT_RECV_DT > PMT_DT` and cross-references the late fee.
If the payment is received beyond a configurable grace period (e.g., 15 days) and no late
fee is assessed, flag the record for review.

---

## ANO-009: Credit Score Range Not Validated

| Field            | Value |
|------------------|-------|
| **Severity**     | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_CRDT_SCR` |

**Description:**
Credit scores are stored as `VARCHAR(5)` with no range validation. Valid FICO scores
range from 300 to 850. The `parseLegacyInteger()` method converts the string to an
`Integer` but does not validate the range. Values like `0`, `999`, or negative numbers
would be accepted and returned in the API.

**Example Current Records (all valid but unvalidated):**

| BORR_ID  | BORR_CRDT_SCR | In Range? |
|----------|---------------|-----------|
| B-10001  | 745           | Yes       |
| B-10002  | 780           | Yes       |
| B-10003  | 692           | Yes       |
| B-10004  | 810           | Yes       |
| B-10005  | 658           | Yes       |

**Business Impact:**
An out-of-range credit score would distort risk assessments, loan eligibility decisions,
and reporting metrics. API consumers may trust the score without validation.

**Recommended Fix:**
Add range validation (300-850) for credit scores at ingestion time. Reject or flag
scores outside this range.

---

## ANO-010: Annual Income Stored with Commas — Parsing Risk with Currency Symbols

| Field            | Value |
|------------------|-------|
| **Severity**     | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_ANN_INCM` |

**Description:**
Annual income values are stored as comma-formatted strings (e.g., `"92,500"`, `"125,000"`).
The `parseLegacyAmount()` method strips commas but does not handle currency symbols (`$`),
whitespace padding, or locale-specific formatting (e.g., European `92.500,00`).

**Example Current Records:**

| BORR_ID  | BORR_ANN_INCM | Parsed Value |
|----------|---------------|--------------|
| B-10001  | 92,500        | 92500 (OK)   |
| B-10002  | 125,000       | 125000 (OK)  |
| B-10003  | 78,000        | 78000 (OK)   |

**Business Impact:**
If upstream systems begin including currency symbols or change locale formatting,
the parser will silently fail with a `NumberFormatException`, crashing the entire
borrower listing API.

**Recommended Fix:**
Enhance `parseLegacyAmount()` to strip `$`, whitespace, and other non-numeric characters
(except `.` and `-`) before parsing. Add try-catch with logging.

---

## Summary Table

| ID      | Title                                      | Severity | Table(s)                    |
|---------|--------------------------------------------|----------|-----------------------------|
| ANO-001 | Payment Component Sum Mismatch             | Critical | CDW_PMT_HIST                |
| ANO-002 | Uncaught NumberFormatException             | Critical | All tables                  |
| ANO-003 | Delinquent Loan Flagged as Active          | High     | CDW_LN_ACCT                 |
| ANO-004 | No NOT NULL on Required Fields             | High     | All tables                  |
| ANO-005 | Denormalized Borrower Data Drift Risk      | High     | CDW_LN_ACCT / CDW_BORR_MSTR|
| ANO-006 | No Foreign Key Constraints (Orphan Risk)   | High     | CDW_LN_ACCT / CDW_PMT_HIST  |
| ANO-007 | Dates as Unparsed Strings in API           | Medium   | CDW_LN_ACCT / CDW_PMT_HIST  |
| ANO-008 | Late Payment with Inconsistent Late Fees   | Medium   | CDW_PMT_HIST                |
| ANO-009 | Credit Score Range Not Validated            | Medium   | CDW_BORR_MSTR               |
| ANO-010 | Income Parsing Risk with Currency Symbols  | Medium   | CDW_BORR_MSTR               |
