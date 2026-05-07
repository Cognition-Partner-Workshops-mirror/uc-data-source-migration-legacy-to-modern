# Data Anomaly Report - Legacy CDW Tables

> **Generated:** 2026-05-07
> **Scope:** `src/main/resources/schema-legacy.sql` and `src/main/resources/data-legacy.sql`
> **Tables analyzed:** CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3     |
| High     | 3     |
| Medium   | 3     |
| Low      | 1     |

---

## ANO-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE |

**Description:**
The total payment amount (`PMT_AMT`) does not equal the sum of its component parts (principal + interest + escrow + late fee) for multiple records. This is a fundamental financial integrity violation.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | Principal | Interest | Escrow | Late Fee | Component Sum | Delta |
|---|---|---|---|---|---|---|---|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | **+400.00** |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | **+400.00** |
| PMT-2025110003 | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | **+47.50** |

**Business Impact:**
- Financial reports will show incorrect payment breakdowns
- Escrow account reconciliation will fail
- Regulatory reporting of principal vs. interest allocation will be inaccurate
- Downstream accounting systems consuming this data will propagate the error

**Recommended Fix:**
Add a payment component sum validation that checks `|total - (principal + interest + escrow + late_fee)| < 0.01` at ingestion time. Flag mismatches and log them. For PMT-2025120001 / PMT-2025110001, the escrow value (355.55) appears to have been added erroneously to a non-escrow loan payment. For PMT-2025110003, the late fee (47.50) was recorded but not included in the total.

---

## ANO-002: Numeric Strings with No Parse Error Handling

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Tables** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST, CDW_LN_PROD |
| **Affected Columns** | BORR_ANN_INCM, BORR_CRDT_SCR, LN_ORIG_AMT, LN_CURR_BAL, LN_INT_RT, LN_PMT_AMT, LN_ESCROW_BAL, LN_LTV_PCT, LN_DLQ_DAYS, PROP_APRS_VAL, PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE, PROD_TERM_MOS, PROD_MIN_AMT, PROD_MAX_AMT |

**Description:**
All numeric values are stored as VARCHAR strings (e.g., `"285,000"`, `"4.750"`, `"745"`). The current `parseLegacyAmount()` method strips commas and calls `new BigDecimal(...)`, while `parseLegacyInteger()` calls `Integer.parseInt()`. Neither method handles unexpected characters such as `$`, `%`, spaces, alphabetic text (`"N/A"`, `"PENDING"`), or empty strings beyond blank. Any such value causes an uncaught `NumberFormatException` that propagates as an HTTP 500 error.

**Example Risk Scenarios:**
- An amount stored as `"$285,000"` or `"285,000.00 USD"` would crash `parseLegacyAmount()`
- A credit score stored as `"N/A"` or `"---"` would crash `parseLegacyInteger()`
- An interest rate of `"5.250%"` would crash `parseLegacyDecimal()`

**Business Impact:**
- A single malformed record causes the entire API request to fail with HTTP 500
- `GET /api/loans` (which loads all loans) would return zero results if any one record is corrupt
- No visibility into which record or field caused the failure

**Recommended Fix:**
Wrap all parse methods in try-catch blocks. On `NumberFormatException`, log the field name, raw value, and record ID. Return a safe default (`BigDecimal.ZERO` for amounts, `null` for optional integers) and include a warning in the response or an internal validation log.

---

## ANO-003: Date Strings with No Format Validation

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Tables** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST, CDW_LN_PROD |
| **Affected Columns** | All `*_DT` columns (BORR_DOB_DT, BORR_CRET_DT, BORR_UPDT_DT, LN_ORIG_DT, LN_MAT_DT, LN_1ST_PMT_DT, LN_NXT_PMT_DT, PMT_DT, PMT_RECV_DT, PMT_PROC_DT, etc.) |

**Description:**
All date fields are VARCHAR(10) with an expected format of `MM/DD/YYYY`, but there is no validation or parsing in the service layer. The `LoanService` passes raw date strings directly to the DTOs (`dto.setOriginationDate(acct.getOriginationDate())`). During migration to the modern schema (which uses `DATE` / `TIMESTAMP` types), the `MM/DD/YYYY` string must be parsed via `DateTimeFormatter`. Any date in a different format (e.g., `YYYY-MM-DD`, `DD/MM/YYYY`, `13/45/2025`) will cause a `DateTimeParseException`.

**Example Risk Scenarios:**
- `"2025-03-15"` (ISO format from a different source system) would fail MM/DD/YYYY parsing
- `"02/30/2020"` (invalid day for February) would fail
- `""` (empty string) or `"TBD"` would fail

**Business Impact:**
- Migration to the modern schema will fail on any non-conforming date
- The column mappings document specifies `Parse MM/DD/YYYY -> DATE` for 15+ columns across 4 tables
- API responses currently expose raw date strings, so any inconsistency is visible to consumers

**Recommended Fix:**
Add date format validation at ingestion. Parse each date string with `DateTimeFormatter.ofPattern("MM/dd/yyyy")` wrapped in try-catch. On failure, log the anomaly and either reject the record or store a sentinel date value.

---

## ANO-004: Denormalized Borrower SSN Last-4 Populated from Phone Digits

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Column** | BORR_SSN_LST4 |

**Description:**
The `BORR_SSN_LST4` column in CDW_LN_ACCT is intended to hold the last 4 digits of the borrower's SSN. However, the values match the last 4 digits of the borrower's phone number instead:

| Borrower | Phone | SSN_LST4 in CDW_LN_ACCT | Match |
|---|---|---|---|
| B-10001 (James Mitchell) | 217-555-**0142** | **0142** | Phone last 4 |
| B-10002 (Sarah Chen) | 503-555-**0198** | **0198** | Phone last 4 |
| B-10003 (Michael Torres) | 512-555-**0167** | **0167** | Phone last 4 |
| B-10004 (Emily Johnson) | 303-555-**0134** | **0134** | Phone last 4 |
| B-10005 (Robert Williams) | 602-555-**0156** | **0156** | Phone last 4 |

All 5 records exhibit this pattern with 100% correlation to phone number last 4 digits and 0% correlation to any known SSN data.

**Business Impact:**
- Identity verification workflows relying on SSN last-4 will produce false negatives
- Compliance and KYC (Know Your Customer) checks are compromised
- If this data migrates to the modern schema, PII integrity is undermined

**Recommended Fix:**
Flag `BORR_SSN_LST4` as unreliable during migration. Cross-reference with the encrypted SSN in CDW_BORR_MSTR (`BORR_SSN_ENCR`) to derive the correct last 4 digits. Until then, mark the field as "unverified" in the modern schema.

---

## ANO-005: Denormalized Borrower Data Divergence Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | BORR_FST_NM, BORR_LST_NM (in CDW_LN_ACCT vs CDW_BORR_MSTR) |

**Description:**
CDW_LN_ACCT contains denormalized copies of borrower first name and last name alongside the `BORR_ID` foreign key. In the current seed data, names happen to match between the two tables. However, there is no constraint or trigger enforcing consistency. Any update to a borrower's name in CDW_BORR_MSTR will not propagate to CDW_LN_ACCT, creating a silent divergence.

The service layer uses the **loan account's** copy of the borrower name (`acct.getBorrowerFirstName()` in `toLoanSummary()` at line 106) rather than looking up the canonical borrower record, so stale names in loan records will appear in API responses.

**Example Risk Scenario:**
If borrower "Sarah Chen" (B-10002) changes her last name, CDW_BORR_MSTR gets updated but CDW_LN_ACCT still shows "Chen". The `/api/loans` endpoint returns the old name; the `/api/borrowers/B-10002` endpoint returns the new name.

**Business Impact:**
- Inconsistent borrower names across API endpoints
- Loan-level reports show different names than borrower-level reports
- Potential compliance issues with name-based identity checks

**Recommended Fix:**
In `toLoanSummary()`, look up the borrower from CDW_BORR_MSTR by `BORR_ID` instead of using the denormalized fields. During migration to the modern schema, drop the denormalized columns and use FK joins.

---

## ANO-006: No Foreign Key Constraints - Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | CDW_LN_ACCT.BORR_ID, CDW_LN_ACCT.PROD_CD, CDW_PMT_HIST.LN_ACCT_NBR |

**Description:**
The legacy schema explicitly has no foreign key constraints (noted in the schema header: "No foreign key constraints"). This means:
- A loan account can reference a non-existent borrower ID
- A loan account can reference a non-existent product code
- A payment can reference a non-existent loan account number

The service layer performs lookups that will silently produce incorrect results:
- `products.get(acct.getProductCode())` returns `null` for orphaned product codes (line 54 of LoanService.java), causing the product description to fall back to the raw code
- `loanAccountRepository.findById()` returns empty for orphaned loan references, causing NPE or empty results

**Business Impact:**
- Orphaned payments would not appear under any loan
- Loans with invalid product codes show cryptic codes instead of descriptions
- Data migration will fail when attempting to create FK-constrained modern records from orphaned legacy records

**Recommended Fix:**
Add referential integrity validation at ingestion. Before processing a loan account, verify `BORR_ID` exists in CDW_BORR_MSTR and `PROD_CD` exists in CDW_LN_PROD. Before processing a payment, verify `LN_ACCT_NBR` exists in CDW_LN_ACCT. Log violations and quarantine orphaned records.

---

## ANO-007: Payment Received After Payment Date

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_DT, PMT_RECV_DT, PMT_PROC_DT |

**Description:**
Some payment records have a `PMT_RECV_DT` (received date) that is significantly later than `PMT_DT` (payment due date), suggesting either backdated entries or a confused field mapping:

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | PMT_PROC_DT | Gap (days) |
|---|---|---|---|---|
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 12/06/2025 | 4 |
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 11/19/2025 | 17 |

Both records belong to loan LN-2018-00089 (Michael Torres), which also has 15 delinquency days.

**Business Impact:**
- Late payment detection depends on the correct interpretation of these date fields
- If `PMT_DT` is the due date and `PMT_RECV_DT` is when payment was actually received, the 17-day gap on PMT-2025110003 indicates a severely late payment
- Interest accrual calculations may be incorrect if using `PMT_DT` instead of `PMT_RECV_DT`

**Recommended Fix:**
Validate that `PMT_RECV_DT <= PMT_DT + grace_period` (typically 15 days for mortgages). Flag records where received date exceeds payment date by more than the grace period. Ensure the service layer uses the correct date for interest calculations.

---

## ANO-008: Delinquency Days Inconsistent with Loan Status

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | LN_DLQ_DAYS, LN_STAT_CD |

**Description:**
Loan LN-2018-00089 has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'` (Active). A loan with 15 days of delinquency should not be in a simple "Active" status. Industry practice is to flag loans as delinquent at 30 days, but 15 days of delinquency is a warning state that should be surfaced.

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|---|---|---|---|
| LN-2018-00089 | 15 | ACT | ACT (with delinquency warning) |
| LN-2019-00142 | 0 | ACT | ACT |
| LN-2020-00398 | 0 | ACT | ACT |
| LN-2021-00567 | 0 | ACT | ACT |
| LN-2017-00034 | 0 | ACT | ACT |

**Business Impact:**
- Risk management dashboards that filter on status code alone will miss delinquent loans
- The `expandStatusCode()` method maps "ACT" -> "Active" without considering delinquency
- Collections workflows that trigger on status code will not flag this loan

**Recommended Fix:**
Add a composite validation: if `LN_DLQ_DAYS > 0` and `LN_STAT_CD = 'ACT'`, append a delinquency warning to the status or add a separate delinquency flag to the DTO. Consider introducing a "DELINQUENT" status for loans with >30 days.

---

## ANO-009: Schema Has No NOT NULL Constraints

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | All (CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST) |
| **Affected Columns** | All non-PK columns |

**Description:**
Every column in every table (except primary keys) is nullable. Business-critical fields that should never be null lack constraints:
- `CDW_BORR_MSTR.BORR_FST_NM` / `BORR_LST_NM` (borrower name)
- `CDW_LN_ACCT.BORR_ID` (borrower reference)
- `CDW_LN_ACCT.LN_ORIG_AMT` / `LN_CURR_BAL` (financial amounts)
- `CDW_LN_ACCT.LN_STAT_CD` (loan status)
- `CDW_PMT_HIST.LN_ACCT_NBR` (loan reference)
- `CDW_PMT_HIST.PMT_AMT` (payment total)

A null in `BORR_FST_NM` causes `toBorrowerDto()` to produce `"null R. Mitchell"` as the full name. A null in `LN_ORIG_AMT` returns `BigDecimal.ZERO` (from `parseLegacyAmount`), masking a data quality issue as a zero-dollar loan.

**Business Impact:**
- Null borrower names produce malformed API responses
- Null financial amounts silently become zero, hiding missing data
- Null status codes produce "Unknown" in API responses with no way for consumers to distinguish "intentionally unknown" from "data missing"

**Recommended Fix:**
Add null-check validation for business-critical fields at ingestion. Reject or quarantine records missing required fields. In the service layer, explicitly check for nulls before string concatenation.

---

## ANO-010: Unrecognized Status Codes Pass Through Silently

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Tables** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | BORR_STAT_CD, LN_STAT_CD, PMT_STAT_CD, PMT_TYP_CD, PROP_TYP_CD |

**Description:**
The `expandStatusCode()`, `expandPropertyType()`, `expandPaymentType()`, and `expandPaymentStatus()` methods use switch expressions with a `default -> code` fallback. Any unrecognized code passes through as-is to the API response. The current data uses only known codes, but any new or corrupted code will appear as a cryptic abbreviation (e.g., `"XYZ"`) in API responses with no logging.

**Business Impact:**
- API consumers receive inconsistent status formats (some expanded, some raw codes)
- No alerting when new or unknown codes appear in the data
- Frontend applications may not handle unexpected status values

**Recommended Fix:**
Log a warning when an unrecognized status code is encountered. Optionally return a structured "UNKNOWN (raw: XYZ)" format so consumers can distinguish recognized from unrecognized codes.

---

## Appendix: Anomaly Cross-Reference Matrix

| Anomaly | CDW_BORR_MSTR | CDW_LN_PROD | CDW_LN_ACCT | CDW_PMT_HIST |
|---------|:---:|:---:|:---:|:---:|
| ANO-001 Payment Sum Mismatch | | | | X |
| ANO-002 Numeric Parse Risk | X | X | X | X |
| ANO-003 Date Format Risk | X | X | X | X |
| ANO-004 SSN from Phone | | | X | |
| ANO-005 Denorm Divergence | X | | X | |
| ANO-006 No FK Constraints | | | X | X |
| ANO-007 Late Received Dates | | | | X |
| ANO-008 Delinquency/Status | | | X | |
| ANO-009 No NOT NULL | X | X | X | X |
| ANO-010 Unknown Status Codes | X | | X | X |
