# Legacy Data Anomaly Report

## Overview

This report documents data quality anomalies found in the legacy CDW (Corporate Data Warehouse)
seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`). Each anomaly is categorized by
severity and includes affected records, business impact, and recommended fixes.

---

## ANO-001: Payment Component Amounts Do Not Sum to Total

**Severity:** Critical

**Affected Table/Column:** `CDW_PMT_HIST` — `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`

**Description:** For loan `LN-2019-00142`, the sum of principal + interest + escrow + late_fee
does not equal the recorded total payment amount. The discrepancy is $400.00 in every payment
for this loan.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN | INT | ESCROW | LATE_FEE | Computed Sum | Discrepancy |
|---|---|---|---|---|---|---|---|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | +400.00 |

Other loans (LN-2020-00398, LN-2018-00089, LN-2021-00567, LN-2017-00034) balance correctly.

**Business Impact:** Financial reporting and reconciliation will produce incorrect numbers.
Downstream consumers of the `/api/loans/{id}/payments` endpoint receive data where component
amounts don't reconcile, creating audit and compliance failures.

**Recommended Fix:** Validate at ingestion that `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE == PMT_AMT`.
Flag records that fail this check. Investigate the source system feeding LN-2019-00142 payments
to determine whether the interest amount or the escrow amount is inflated.

---

## ANO-002: SSN Last-4 Field Contains Phone Number Last-4

**Severity:** Critical

**Affected Table/Column:** `CDW_LN_ACCT` — `BORR_SSN_LST4`

**Description:** The `BORR_SSN_LST4` column in the loan accounts table is populated with the
last 4 digits of the borrower's phone number instead of their SSN. Every record in the dataset
exhibits this mismatch.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | Borrower Phone (CDW_BORR_MSTR) | Phone Last 4 |
|---|---|---|---|---|
| LN-2019-00142 | B-10001 | 0142 | 217-555-0142 | 0142 |
| LN-2020-00398 | B-10002 | 0198 | 503-555-0198 | 0198 |
| LN-2018-00089 | B-10003 | 0167 | 512-555-0167 | 0167 |
| LN-2021-00567 | B-10004 | 0134 | 303-555-0134 | 0134 |
| LN-2017-00034 | B-10005 | 0156 | 602-555-0156 | 0156 |

**Business Impact:** Identity verification during migration will fail — cross-referencing SSN
data against the loan record yields the wrong value. This is also a compliance risk: phone
digits masquerading as SSN data may be treated as PII-level sensitive when they are not, and
actual SSN data is missing from the expected location.

**Recommended Fix:** Drop this column during migration (the column mapping already marks it as
"dropped"). Do not rely on `BORR_SSN_LST4` for any identity verification logic. If SSN last-4
is needed, derive it from the encrypted SSN in `CDW_BORR_MSTR.BORR_SSN_ENCR`.

---

## ANO-003: Delinquent Loan Marked as Active

**Severity:** High

**Affected Table/Column:** `CDW_LN_ACCT` — `LN_STAT_CD`, `LN_DLQ_DAYS`

**Description:** Loan `LN-2018-00089` (borrower B-10003, Michael Torres) has 15 days of
delinquency (`LN_DLQ_DAYS = '15'`) but its status code is `ACT` (Active). Business rules
typically require loans with >0 delinquency days to be flagged or, at minimum, to have a
status that reflects the delinquent state.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_ID | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|---|---|---|---|---|
| LN-2018-00089 | B-10003 | 15 | ACT | DLQ or at minimum flagged |

**Business Impact:** The API exposes this loan as "Active" without any delinquency indicator.
Risk management, collections workflows, and regulatory reporting that rely on the status code
will miss this delinquent loan. The `LoanSummaryDto` does not include `delinquencyDays`, so
the 15-day delinquency is completely invisible to API consumers.

**Recommended Fix:** Add validation that cross-checks `LN_DLQ_DAYS > 0` against `LN_STAT_CD`.
Expose delinquency days in the API DTO so downstream consumers can apply their own business
rules. Consider adding a `DLQ` status code or a separate delinquency flag.

---

## ANO-004: No Foreign Key Constraints — Orphan Risk

**Severity:** High

**Affected Table/Column:** `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR`

**Description:** The legacy schema defines no foreign key constraints. `CDW_LN_ACCT.BORR_ID`
is not constrained to `CDW_BORR_MSTR.BORR_ID`, `PROD_CD` is not constrained to
`CDW_LN_PROD.PROD_CD`, and `CDW_PMT_HIST.LN_ACCT_NBR` is not constrained to
`CDW_LN_ACCT.LN_ACCT_NBR`. This means orphaned records (referencing non-existent parents)
can exist without any database-level enforcement.

**Example Bad Records:** No orphans exist in the current seed data, but there is zero
protection against them being inserted. The code in `LoanService.getLoanById()` calls
`loanProductRepository.findById(acct.getProductCode()).orElse(null)` — this returns null
silently if the product code doesn't exist.

**Business Impact:** If a loan references a non-existent borrower or product, the API will
either return incomplete data (null product description) or throw a `NullPointerException`
when accessing the missing relationship. During migration, orphaned records will fail FK
lookups against the modern normalized schema.

**Recommended Fix:** Add referential integrity validation at the service layer. Before
processing a loan, verify that `BORR_ID` exists in the borrower table and `PROD_CD` exists
in the product table. Log and quarantine orphaned records.

---

## ANO-005: All Numeric Fields Stored as VARCHAR — Parsing Failures

**Severity:** High

**Affected Table/Column:** Multiple columns across all tables — `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_TERM_MOS`, `LN_DLQ_DAYS`, `LN_LTV_PCT`, `PMT_AMT`, etc.

**Description:** Every numeric value (credit scores, amounts, rates, terms, days) is stored
as `VARCHAR`. The service layer parses these with `Integer.parseInt()` and
`new BigDecimal(...)`, both of which throw unchecked exceptions on malformed input. Current
seed data is well-formed, but the schema allows any string — including empty strings, dollar
signs, spaces, or alphabetic characters.

**Example Parsing Risks:**

| Column | Sample Value | Parse Method | Failure Scenario |
|---|---|---|---|
| `BORR_CRDT_SCR` | "745" | `Integer.parseInt()` | "N/A", "", "745a" → `NumberFormatException` |
| `BORR_ANN_INCM` | "92,500" | `BigDecimal` after comma strip | "$92,500" → exception |
| `LN_INT_RT` | "5.250" | `BigDecimal` | "5.25%" → exception |
| `LN_DLQ_DAYS` | "15" | not parsed in current code | Would fail if parsed |
| `LN_LTV_PCT` | "82.5" | not parsed in current code | Would fail if parsed |

**Business Impact:** A single malformed numeric record causes an unhandled `NumberFormatException`
that propagates as a 500 Internal Server Error from the API. The entire request fails rather
than gracefully degrading for one bad record.

**Recommended Fix:** Wrap all parse operations in try-catch with fallback defaults
(`BigDecimal.ZERO` for amounts, `null` for optional integers). Log a warning for each parse
failure so bad data is visible without crashing the service.

---

## ANO-006: Date Strings Not Validated

**Severity:** Medium

**Affected Table/Column:** All date columns across all tables — `BORR_DOB_DT`, `BORR_CRET_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.

**Description:** Dates are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. The current service
layer passes dates through as raw strings without parsing or validation. Invalid dates
(e.g., `02/30/2020`, `13/01/2020`, `00/00/0000`) will be accepted and served via the API.

**Example Bad Records:** No invalid dates in current seed data, but the schema provides no
protection against invalid values being inserted.

**Business Impact:** During migration, invalid date strings will cause parse errors when
converting to `DATE` or `TIMESTAMP` types. The column mappings document specifies
`Parse MM/DD/YYYY → DATE` as the transformation, so bad dates will break the migration ETL.

**Recommended Fix:** Add date format validation at the service layer. Attempt to parse each
date string with `MM/dd/yyyy` format; flag records with unparseable dates. Provide a fallback
(e.g., epoch date or null) for non-critical date fields.

---

## ANO-007: Denormalized Borrower Data May Drift from Master

**Severity:** Medium

**Affected Table/Column:** `CDW_LN_ACCT` — `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`

**Description:** The loan accounts table embeds borrower first name, last name, and SSN last-4
as denormalized copies of data from `CDW_BORR_MSTR`. Without triggers or application logic to
keep them in sync, these copies can drift from the master record.

**Example:** In the current seed data, names are consistent between `CDW_LN_ACCT` and
`CDW_BORR_MSTR`. However, the `BORR_SSN_LST4` field is already wrong (see ANO-002), which
demonstrates the risk of denormalized data becoming unreliable.

**Business Impact:** If a borrower's name is updated in `CDW_BORR_MSTR` but not in
`CDW_LN_ACCT`, the API will show inconsistent names depending on which endpoint is called.
The `/api/loans` endpoint uses the denormalized name while `/api/borrowers/{id}` uses the
master name.

**Recommended Fix:** During migration, drop the denormalized columns from the loan table
(as specified in column_mappings.md) and use a foreign key to the borrowers table instead.
In the interim, add a consistency check that compares denormalized fields to the master.

---

## ANO-008: No NOT NULL Constraints on Required Fields

**Severity:** Medium

**Affected Table/Column:** All tables — every non-PK column allows NULL

**Description:** The schema defines no `NOT NULL` constraints except on primary keys. Fields
that are logically required (borrower first/last name, loan amounts, payment amounts, dates)
can be NULL. The service layer handles some nulls (e.g., `parseLegacyAmount` returns
`BigDecimal.ZERO` for null) but not all (e.g., `toBorrowerDto` will produce "null null" for
a borrower with null first and last name).

**Example:** `borrower.getFirstName()` returns null → `toBorrowerDto` constructs fullName
as `"null null"` because Java string concatenation converts null to the literal string "null".

**Business Impact:** NULL values in required fields cause incorrect display ("null Mitchell"),
incorrect calculations, and NullPointerExceptions in code paths that don't check for null.

**Recommended Fix:** Add null-checks for required fields at the service layer. Reject or flag
records missing required data (first name, last name, loan amounts, payment amounts).

---

## ANO-009: Late Fee Inclusion Inconsistency in Payment Totals

**Severity:** Medium

**Affected Table/Column:** `CDW_PMT_HIST` — `PMT_AMT`, `PMT_LATE_FEE`

**Description:** For payment `PMT-2025110003` (LN-2018-00089), the late fee is $47.50 but the
total payment amount ($1,077.05) equals only principal + interest. The late fee is not included
in the total. This is inconsistent with the convention in other payments where all components
(including escrow) sum to the total.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN + INT + ESCROW + LATE | Late Fee Included? |
|---|---|---|---|
| PMT-2025120002 | 2,924.18 | 2,924.18 | Yes (escrow included) |
| PMT-2025110003 | 1,077.05 | 1,124.55 | No (47.50 late fee excluded) |

**Business Impact:** Reports that calculate total fees collected or total payments received
will be inconsistent depending on whether they use the total field or sum the components.

**Recommended Fix:** Establish a clear convention: either PMT_AMT always includes all
components, or it excludes optional fees. Validate consistency at ingestion.

---

## ANO-010: Payment Received After Payment Date (Potential Late Payment Misclassification)

**Severity:** Low

**Affected Table/Column:** `CDW_PMT_HIST` — `PMT_DT`, `PMT_RECV_DT`

**Description:** Some payments have `PMT_RECV_DT` significantly after `PMT_DT`, indicating the
payment was received late. For example, PMT-2025110003 has `PMT_DT = 11/01/2025` but
`PMT_RECV_DT = 11/18/2025` (17 days late). This is not inherently wrong, but the late fee
of $47.50 suggests this should be flagged systematically.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | Days Late | Late Fee |
|---|---|---|---|---|
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 17 | 47.50 |
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 4 | 0.00 |

**Business Impact:** Inconsistent late fee application — one payment 17 days late has a fee,
another 4 days late does not. This may be correct (grace periods), but without validation
rules the data is opaque to consumers.

**Recommended Fix:** Add validation that checks if `PMT_RECV_DT > PMT_DT` and cross-references
with late fee amounts. Log warnings for late payments without fees and payments with fees that
aren't late.

---

## Summary Table

| ID | Title | Severity | Table |
|---|---|---|---|
| ANO-001 | Payment components don't sum to total | Critical | CDW_PMT_HIST |
| ANO-002 | SSN last-4 contains phone last-4 | Critical | CDW_LN_ACCT |
| ANO-003 | Delinquent loan marked Active | High | CDW_LN_ACCT |
| ANO-004 | No FK constraints — orphan risk | High | All |
| ANO-005 | Numeric fields as VARCHAR — parse failures | High | All |
| ANO-006 | Date strings not validated | Medium | All |
| ANO-007 | Denormalized borrower data drift risk | Medium | CDW_LN_ACCT |
| ANO-008 | No NOT NULL on required fields | Medium | All |
| ANO-009 | Late fee inclusion inconsistency | Medium | CDW_PMT_HIST |
| ANO-010 | Late payment date / fee mismatch | Low | CDW_PMT_HIST |
