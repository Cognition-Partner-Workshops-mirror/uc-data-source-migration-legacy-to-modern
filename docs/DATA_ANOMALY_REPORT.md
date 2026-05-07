# Data Anomaly Report: Legacy CDW Tables

> **Generated:** 2026-05-07
> **Source:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`
> **Scope:** CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST

---

## ANO-001: All Numeric Fields Stored as VARCHAR with Embedded Commas

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | `BORR_ANN_INCM`, `BORR_CRDT_SCR`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `LN_LTV_PCT`, `PROP_APRS_VAL`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PROD_TERM_MOS`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Example Bad Records:**
- `BORR_ANN_INCM = '92,500'` (borrower B-10001) — comma-formatted string, not a number
- `LN_ORIG_AMT = '285,000'` (loan LN-2019-00142) — must strip commas before parsing
- `LN_CURR_BAL = '271,432.56'` (loan LN-2019-00142) — mixed commas and decimal point
- `PROD_MIN_AMT = '0'` vs `'50,000'` — inconsistent formatting (VA30 has no comma)

**Business Impact:** Any `BigDecimal` or `Integer.parseInt()` call on an unstripped value throws `NumberFormatException`, crashing the API endpoint. The service currently strips commas in `parseLegacyAmount()`, but a malformed value (e.g., `'$285,000'`, `'N/A'`, or an empty string) would still cause an unhandled exception, returning a 500 error to consumers.

**Recommended Fix:** Add try-catch with fallback defaults around all numeric parsing. Validate numeric fields contain only digits, commas, periods, and optional leading minus. Log warnings for unparseable values.

---

## ANO-002: All Date Fields Stored as VARCHAR Strings with No Format Enforcement

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST, CDW_LN_PROD |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT` |

**Example Bad Records:**
- `BORR_DOB_DT = '03/15/1978'` — stored as MM/DD/YYYY string, not a DATE type
- Schema comment says "MM/DD/YYYY" but no CHECK constraint enforces the format
- A value like `'2025-01-15'` (ISO format) or `'15/03/1978'` (DD/MM/YYYY) would be accepted by the VARCHAR column silently

**Business Impact:** The service passes date strings directly through to API responses (e.g., `dto.setOriginationDate(acct.getOriginationDate())`) without parsing or validating. Consumers receive unparseable or inconsistently-formatted date strings. If date parsing is later added during migration, unvalidated formats will cause `DateTimeParseException` failures.

**Recommended Fix:** Parse all date fields at the service layer using `MM/dd/yyyy` format. Catch parse failures and log them. Normalize output to ISO-8601 (`yyyy-MM-dd`) in DTOs.

---

## ANO-003: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Example Bad Records:**
- Current seed data is consistent, but the schema has **zero foreign key constraints**:
  - `CDW_LN_ACCT.BORR_ID` has no FK to `CDW_BORR_MSTR.BORR_ID`
  - `CDW_LN_ACCT.PROD_CD` has no FK to `CDW_LN_PROD.PROD_CD`
  - `CDW_PMT_HIST.LN_ACCT_NBR` has no FK to `CDW_LN_ACCT.LN_ACCT_NBR`
- Nothing prevents inserting a loan with `BORR_ID = 'B-99999'` (non-existent borrower) or a payment referencing a non-existent loan

**Business Impact:** In `LoanService.getLoanById()`, when `acct.getProductCode()` references a non-existent product, `loanProductRepository.findById()` returns `Optional.empty()`, and the code sets `product = null`. This causes `toLoanSummary()` to fall back to showing the raw product code instead of the description — a silent data quality degradation. For borrower lookups, an orphaned `BORR_ID` means `getBorrowerById()` and the loan-borrower join will silently produce incomplete results.

**Recommended Fix:** Validate referential integrity at ingestion time. When loading a loan account, verify the borrower and product exist. Log warnings for orphaned references and either skip or flag the record.

---

## ANO-004: Denormalized Borrower Data in Loan Accounts (Data Drift Risk)

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Example Bad Records:**
- Loan LN-2019-00142 has `BORR_FST_NM='James'`, `BORR_LST_NM='Mitchell'` — matches CDW_BORR_MSTR B-10001
- But no constraint ensures these stay in sync. If the borrower's name is updated in CDW_BORR_MSTR, the loan record retains the stale name
- `BORR_SSN_LST4='0142'` for B-10001 but the phone number ends in `0142` — the SSN last-4 is derived from the phone number, not actual SSN, suggesting data entry error or incorrect ETL mapping

**Business Impact:** `toLoanSummary()` builds borrower name from `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()` (the denormalized copy), NOT from the authoritative borrower table. If the denormalized copy drifts, the API returns stale borrower names.

**Recommended Fix:** Use the authoritative CDW_BORR_MSTR record for borrower names rather than the denormalized copy. Cross-validate denormalized fields during ingestion and log discrepancies.

---

## ANO-005: NULL Values in Conditionally Required Fields

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | CDW_BORR_MSTR |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

**Example Bad Records:**
- B-10005 (Robert Williams): `BORR_MID_INIT = NULL` — the only borrower without a middle initial
- B-10002, B-10003, B-10005: `BORR_ADDR_LN2 = NULL`

**Business Impact:** In `toBorrowerDto()`, the code handles null `middleInitial` correctly with a ternary check. However, no schema-level NOT NULL constraints exist on `BORR_FST_NM` or `BORR_LST_NM` either. A null first or last name would cause the fullName construction to produce `"null R. Mitchell"` or `"James null"` in the API response — because Java string concatenation converts null to the literal string `"null"`.

**Recommended Fix:** Add null checks for `firstName` and `lastName` before string concatenation. Define required fields and validate they are non-null at ingestion time.

---

## ANO-006: No Schema-Level NOT NULL Constraints on Any Column

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Tables** | CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | All non-PK columns |

**Example Bad Records:**
- Every column except the PRIMARY KEY is defined as nullable VARCHAR
- `BORR_FST_NM VARCHAR(50)` — no NOT NULL, even though a borrower without a name is nonsensical
- `LN_STAT_CD VARCHAR(5)` — no NOT NULL, though a loan without a status breaks status expansion logic

**Business Impact:** The schema permits insertion of entirely empty records (only the PK is required). The service layer has no null guards on critical fields like `statusCode`, `productCode`, `loanAccountNumber` (for payments), amounts, or dates. A null `statusCode` on a loan would return `"Unknown"` from `expandStatusCode()`, silently hiding a data quality issue.

**Recommended Fix:** Add service-layer validation that rejects or flags records missing required business fields (status codes, amounts, dates, names).

---

## ANO-007: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Example Bad Records:**
- PMT-2025120001: `PMT_AMT='1,487.02'`, components: `456.78 + 1,074.69 + 355.55 + 0.00 = 1,887.02` — **overstated by $400.00**
- PMT-2025120002: `PMT_AMT='2,924.18'`, components: `1,842.56 + 815.50 + 266.12 + 0.00 = 2,924.18` — correct
- PMT-2025110003: `PMT_AMT='1,077.05'`, components: `295.82 + 781.23 + 0.00 + 47.50 = 1,124.55` — **overstated by $47.50** (late fee not included in total or total not adjusted)

**Business Impact:** Financial reporting that relies on payment components will show discrepancies. If downstream systems reconcile totals against component sums, these records will fail reconciliation. The API exposes both the total and components without validation, so consumers may see contradictory data.

**Recommended Fix:** Validate at ingestion that `principal + interest + escrow + lateFee == total`. Log discrepancies as warnings. Consider whether to trust the total or the components as the source of truth.

---

## ANO-008: Delinquency Days Inconsistent with Loan Status

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Example Bad Records:**
- LN-2018-00089 (Michael Torres): `LN_STAT_CD='ACT'` but `LN_DLQ_DAYS='15'` — an active loan with 15 delinquency days should likely be flagged or have a different status
- All other active loans have `LN_DLQ_DAYS='0'`

**Business Impact:** Reporting on delinquent loans by status alone would miss this loan. Risk scoring and regulatory reporting that filters by status code would not flag this account, while delinquency-day-based reports would. This inconsistency causes conflicting views of portfolio health.

**Recommended Fix:** Cross-validate status and delinquency days at ingestion. If `delinquencyDays > 0` and status is `ACT`, log a warning and consider whether to auto-escalate the status.

---

## ANO-009: Late Payment Detection — Received Date After Payment Due Date

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT` |

**Example Bad Records:**
- PMT-2025110003 (loan LN-2018-00089): `PMT_DT='11/01/2025'`, `PMT_RECV_DT='11/18/2025'`, `PMT_PROC_DT='11/19/2025'` — received 17 days after due date, with a $47.50 late fee
- PMT-2025120003 (same loan): `PMT_DT='12/01/2025'`, `PMT_RECV_DT='12/05/2025'` — received 4 days late but no late fee

**Business Impact:** Inconsistent late fee application. One late payment incurs a fee and another does not, with no clear business rule. The service layer does not expose received/processed dates in the DTO, hiding late-payment information from API consumers.

**Recommended Fix:** Validate that late fees are consistently applied based on a configurable grace period. Expose received date and processed date in the payment DTO.

---

## ANO-010: Credit Score Stored as String with No Range Validation

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | CDW_BORR_MSTR |
| **Affected Column** | `BORR_CRDT_SCR` |

**Example Bad Records:**
- Valid range for FICO scores is 300-850
- B-10005: `BORR_CRDT_SCR = '658'` (valid but near subprime threshold)
- No constraint prevents values like `'999'`, `'0'`, `'-1'`, or `'ABC'` being stored
- `parseLegacyInteger()` in the service will throw `NumberFormatException` for non-numeric strings

**Business Impact:** Invalid credit scores would corrupt risk assessments and loan eligibility decisions. The service parses with `Integer.parseInt()` and has no range validation, so any non-numeric value causes a 500 error on the borrower API.

**Recommended Fix:** Validate credit score is numeric and within 300-850 range. Use a fallback null value for unparseable scores and log the anomaly.

---

## ANO-011: Borrower SSN Last-4 Appears Derived from Phone Number

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Column** | `BORR_SSN_LST4` |

**Example Bad Records:**
- B-10001: phone `217-555-0142`, SSN last-4 in loan: `0142`
- B-10002: phone `503-555-0198`, SSN last-4 in loan: `0198`
- B-10003: phone `512-555-0167`, SSN last-4 in loan: `0167`
- B-10004: phone `303-555-0134`, SSN last-4 in loan: `0134`
- B-10005: phone `602-555-0156`, SSN last-4 in loan: `0156`

All 5 borrowers have `BORR_SSN_LST4` matching the last 4 digits of their phone number — a 100% correlation that is statistically impossible if these were independent fields.

**Business Impact:** This indicates a data entry error or ETL bug where phone number digits were copied into the SSN field. Using this field for identity verification or duplicate detection would be unreliable. Regulatory audits (KYC/AML) that rely on SSN last-4 for identity validation would be compromised.

**Recommended Fix:** Flag `BORR_SSN_LST4` as unreliable. Cross-reference against the encrypted SSN in CDW_BORR_MSTR if possible. Do not use this field for identity verification without remediation.

---

## ANO-012: Payment Date Ordering Anomaly — String-Based Sorting

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Column** | `PMT_DT` |

**Example Bad Records:**
- Repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts by `PMT_DT` as a VARCHAR
- String sort of `'12/01/2025'` vs `'11/01/2025'` works by coincidence (same year/day)
- But `'02/01/2026'` would sort BEFORE `'12/01/2025'` in string order (0 < 1), producing incorrect chronological ordering

**Business Impact:** Payment history displayed to customers or used for amortization calculations would be in wrong order when months cross single/double digit boundaries or span year boundaries. The `OrderByPaymentDateDesc` repository method relies on H2's string comparison, not date comparison.

**Recommended Fix:** Parse date strings to actual dates before sorting, or sort in the service layer after parsing. Alternatively, store dates in a sortable format (ISO-8601 or actual DATE type).

---

## Summary

| ID | Title | Severity | Table(s) |
|---|---|---|---|
| ANO-001 | Numeric fields as VARCHAR with commas | Critical | All |
| ANO-002 | Date fields as VARCHAR without format enforcement | Critical | All |
| ANO-003 | No foreign key constraints | Critical | CDW_LN_ACCT, CDW_PMT_HIST |
| ANO-004 | Denormalized borrower data drift risk | High | CDW_LN_ACCT |
| ANO-005 | NULL values in conditionally required fields | High | CDW_BORR_MSTR |
| ANO-006 | No NOT NULL constraints on any column | High | All |
| ANO-007 | Payment components don't sum to total | High | CDW_PMT_HIST |
| ANO-008 | Delinquency days inconsistent with status | Medium | CDW_LN_ACCT |
| ANO-009 | Late payment fee inconsistency | Medium | CDW_PMT_HIST |
| ANO-010 | Credit score as string with no range validation | Medium | CDW_BORR_MSTR |
| ANO-011 | SSN last-4 derived from phone number | Medium | CDW_LN_ACCT |
| ANO-012 | String-based date sorting produces wrong order | Medium | CDW_PMT_HIST |
