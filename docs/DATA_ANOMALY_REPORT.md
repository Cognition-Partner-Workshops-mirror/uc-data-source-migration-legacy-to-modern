# Data Anomaly Report — Legacy CDW Tables

> **Generated:** 2026-05-07
> **Source:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`
> **Scope:** CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3     |
| High     | 4     |
| Medium   | 3     |
| Low      | 2     |

---

## ANO-001: Numeric Financial Amounts Stored as VARCHAR with Embedded Commas

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | Critical                  |
| **Table**      | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST, CDW_LN_PROD |
| **Columns**    | BORR_ANN_INCM, LN_ORIG_AMT, LN_CURR_BAL, LN_PMT_AMT, LN_ESCROW_BAL, PROP_APRS_VAL, PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE, PROD_MIN_AMT, PROD_MAX_AMT |

**Example Bad Records:**

| Table | Column | Record ID | Value |
|-------|--------|-----------|-------|
| CDW_BORR_MSTR | BORR_ANN_INCM | B-10001 | `92,500` |
| CDW_LN_ACCT | LN_ORIG_AMT | LN-2021-00567 | `525,000` |
| CDW_LN_ACCT | LN_CURR_BAL | LN-2020-00398 | `312,876.43` |
| CDW_PMT_HIST | PMT_AMT | PMT-2025120002 | `2,924.18` |
| CDW_LN_PROD | PROD_MAX_AMT | FXD30 | `1,500,000` |

**Business Impact:** Every financial calculation — balance checks, payment allocation, LTV computation, loan-to-income ratio — requires parsing these strings first. A malformed value (e.g., `$285,000`, `285 000`, or empty string) will throw `NumberFormatException` at runtime, crashing the API response for that loan. The current `parseLegacyAmount()` in `LoanService.java` strips commas but does not handle currency symbols, whitespace variants, or non-numeric characters, meaning any upstream CDW data entry error propagates as a 500 error.

**Recommended Fix:**
- Add defensive parsing in the service layer that strips `$`, whitespace, and other non-numeric characters before `BigDecimal` conversion.
- Return `BigDecimal.ZERO` with a logged warning for unparseable values instead of throwing.
- Add a `@PostLoad` entity listener or validation layer that flags records with unparseable amounts.

---

## ANO-002: Dates Stored as VARCHAR in MM/DD/YYYY Format — No Format Validation

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | Critical                  |
| **Table**      | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST, CDW_LN_PROD |
| **Columns**    | BORR_DOB_DT, BORR_CRET_DT, BORR_UPDT_DT, LN_ORIG_DT, LN_MAT_DT, LN_1ST_PMT_DT, LN_NXT_PMT_DT, LN_CRET_DT, LN_UPDT_DT, PMT_DT, PMT_RECV_DT, PMT_PROC_DT, PMT_CRET_DT, PMT_UPDT_DT, PROD_EFF_DT, PROD_EXP_DT |

**Example Bad Records:**

| Table | Column | Record ID | Value | Issue |
|-------|--------|-----------|-------|-------|
| CDW_LN_ACCT | LN_ORIG_DT | LN-2019-00142 | `02/15/2019` | Valid MM/DD/YYYY |
| CDW_LN_ACCT | LN_NXT_PMT_DT | all records | `01/15/2026`, `01/01/2026` | Future dates — no boundary validation |
| CDW_LN_PROD | PROD_EXP_DT | all products | `12/31/2099` | Sentinel far-future date used as "no expiry" |

**Note:** The current seed data happens to use consistent `MM/DD/YYYY` format, but the VARCHAR(10) column places no constraint on format. The real CDW is known to contain dates in `YYYY-MM-DD`, `DD-MMM-YY`, and even raw epoch timestamps. The `LoanService.java` passes date strings through to DTOs **without any parsing** — `originationDate` in `LoanSummaryDto` is a raw `String`, so format inconsistencies would surface directly in API responses.

**Business Impact:** Date-dependent logic (delinquency calculations, maturity tracking, next-payment scheduling) will produce incorrect results or fail entirely when encountering non-MM/DD/YYYY formats. Downstream consumers parsing the API response will break on inconsistent formats.

**Recommended Fix:**
- Parse all date strings to `java.time.LocalDate` using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` in the service layer.
- Catch `DateTimeParseException` and fall back to alternative formats (`yyyy-MM-dd`, `dd-MMM-yy`) before logging an error.
- Return parsed dates as ISO-8601 (`yyyy-MM-dd`) in API responses.

---

## ANO-003: No Foreign Key Constraints — Orphaned Record Risk

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | Critical                  |
| **Table**      | CDW_LN_ACCT, CDW_PMT_HIST |
| **Columns**    | CDW_LN_ACCT.BORR_ID, CDW_LN_ACCT.PROD_CD, CDW_PMT_HIST.LN_ACCT_NBR |

**Example Scenario:**

The schema explicitly states "No foreign key constraints." The relationships are:
- `CDW_LN_ACCT.BORR_ID` → should reference `CDW_BORR_MSTR.BORR_ID`
- `CDW_LN_ACCT.PROD_CD` → should reference `CDW_LN_PROD.PROD_CD`
- `CDW_PMT_HIST.LN_ACCT_NBR` → should reference `CDW_LN_ACCT.LN_ACCT_NBR`

The current seed data maintains referential integrity, but production CDW data is known to contain:
- Loan accounts referencing deleted/merged borrower IDs
- Payment records with mistyped loan account numbers
- Loan accounts referencing discontinued product codes

In `LoanService.java` line 54, `products.get(acct.getProductCode())` returns `null` for an unknown product code. This `null` is passed to `toLoanSummary()` where line 107 handles it with a fallback (`product != null ? product.getDescription() : acct.getProductCode()`), but this masks the data quality issue silently.

In `LoanService.java` line 61, `loanProductRepository.findById(acct.getProductCode()).orElse(null)` returns `null` for orphaned product references — again silently handled.

**Business Impact:** Orphaned borrower references mean loan accounts cannot be attributed to a customer, breaking the borrower detail view. Orphaned payment records mean payment history is incomplete or attributed to wrong loans, causing balance discrepancies. Silent null handling means these issues go undetected until a customer reports incorrect data.

**Recommended Fix:**
- Add referential integrity validation at ingestion time.
- Log warnings for orphaned records with specific IDs.
- Return structured error indicators in API responses rather than silently substituting defaults.

---

## ANO-004: Abbreviated Status Codes with No Enumeration Constraint

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | High                      |
| **Table**      | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST, CDW_LN_PROD |
| **Columns**    | BORR_STAT_CD, LN_STAT_CD, PMT_STAT_CD, PMT_TYP_CD, PROD_STAT_CD |

**Example Values:**

| Table | Column | Known Valid Codes | Risk Codes |
|-------|--------|-------------------|------------|
| CDW_LN_ACCT | LN_STAT_CD | ACT, CLO, DFT, FRB | Any other string (e.g., `ACTV`, `act`, `A`, `ACTIVE`) |
| CDW_PMT_HIST | PMT_STAT_CD | PST, REV, NSF, PND | Mixed-case variants, typos |
| CDW_PMT_HIST | PMT_TYP_CD | REG, EXT, PRT, PRE | Unknown codes |
| CDW_BORR_MSTR | BORR_STAT_CD | ACT, INA | No constraint on column |

**Business Impact:** The `expandStatusCode()` method in `LoanService.java` (line 167-175) uses a `switch` expression with a `default -> code` fallback. An unrecognized status code like `"ACTV"` would pass through as-is, appearing in the API response as a cryptic abbreviation instead of the expected expanded value. Downstream systems filtering by status (e.g., "show all Active loans") would miss these records. The same pattern applies to `expandPropertyType()`, `expandPaymentType()`, and `expandPaymentStatus()`.

**Recommended Fix:**
- Validate status codes against a known allowlist at ingestion time.
- Log unrecognized codes as warnings.
- Map common misspellings/variants to canonical codes (e.g., `ACTV` → `ACT`, `act` → `ACT`).

---

## ANO-005: Denormalized Borrower Data in Loan Accounts — Inconsistency Risk

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | High                      |
| **Table**      | CDW_LN_ACCT              |
| **Columns**    | BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 (duplicated from CDW_BORR_MSTR) |

**Example Records:**

| LN_ACCT_NBR | BORR_ID | LN.BORR_FST_NM | LN.BORR_LST_NM | MSTR.BORR_FST_NM | MSTR.BORR_LST_NM | Match? |
|-------------|---------|-----------------|-----------------|-------------------|-------------------|--------|
| LN-2019-00142 | B-10001 | James | Mitchell | James | Mitchell | Yes |
| LN-2020-00398 | B-10002 | Sarah | Chen | Sarah | Chen | Yes |

The current seed data is consistent, but in production CDW systems, denormalized fields frequently drift when the master record is updated but the loan account's embedded copy is not. For example, a borrower name change (marriage, legal update) would update `CDW_BORR_MSTR` but leave `CDW_LN_ACCT.BORR_FST_NM`/`BORR_LST_NM` stale.

In `LoanService.java` line 106, the `toLoanSummary()` method uses the **denormalized** loan-account copy (`acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`) rather than looking up the borrower master. This means API responses will show stale names if the master was updated.

**Business Impact:** Customer-facing loan summaries may display outdated borrower names, causing confusion and potential compliance issues (e.g., name mismatch on legal documents). The SSN last-4 field (`BORR_SSN_LST4`) mismatch could trigger false fraud alerts.

**Recommended Fix:**
- Cross-reference denormalized fields against the master table during ingestion.
- Log discrepancies as warnings.
- Prefer master-table fields in API responses.

---

## ANO-006: NULL Values in Conditionally Required Fields

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | High                      |
| **Table**      | CDW_BORR_MSTR, CDW_LN_ACCT |
| **Columns**    | BORR_MID_INIT, BORR_ADDR_LN2 |

**Example Bad Records:**

| Table | Column | Record ID | Value |
|-------|--------|-----------|-------|
| CDW_BORR_MSTR | BORR_MID_INIT | B-10005 (Robert Williams) | `NULL` |
| CDW_BORR_MSTR | BORR_ADDR_LN2 | B-10002, B-10003, B-10005 | `NULL` |

While `BORR_MID_INIT` and `BORR_ADDR_LN2` are legitimately optional, **every column in the schema is nullable** because the DDL uses `VARCHAR` without `NOT NULL` constraints. This means truly required fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_ID`, `LN_ACCT_NBR`, etc.) can also be `NULL` in production.

In `LoanService.java` line 123-124, the `toBorrowerDto()` method handles `middleInitial` nulls correctly with a ternary. But `firstName` and `lastName` have no null guard — a null `firstName` would produce `"null Mitchell"` as the full name.

**Business Impact:** Null required fields cause `NullPointerException` in string concatenation, display "null" literals in customer-facing names, and break downstream integrations that expect non-null identifiers.

**Recommended Fix:**
- Validate required fields (first name, last name, borrower ID, loan account number, amounts) are non-null at ingestion.
- Replace nulls in optional fields with explicit defaults (empty string for middle initial, "N/A" for address line 2).

---

## ANO-007: Credit Score Stored as VARCHAR — Range and Parse Risk

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | High                      |
| **Table**      | CDW_BORR_MSTR             |
| **Columns**    | BORR_CRDT_SCR             |

**Example Records:**

| Record ID | Value | Valid Range? |
|-----------|-------|-------------|
| B-10001 | `745` | Yes (300-850) |
| B-10004 | `810` | Yes |
| B-10005 | `658` | Yes |

The VARCHAR(5) column can hold any string up to 5 characters. Production CDW data is known to contain values like `N/A`, empty strings, negative numbers, and scores above 850 (e.g., legacy FICO models). The `parseLegacyInteger()` method in `LoanService.java` (line 162-165) uses `Integer.parseInt()` which throws `NumberFormatException` for non-numeric strings.

**Business Impact:** A non-numeric credit score crashes the borrower detail API endpoint. Invalid credit scores (outside 300-850 range) can cause incorrect loan eligibility determinations.

**Recommended Fix:**
- Catch `NumberFormatException` and return `null` with a warning.
- Validate parsed scores are within 300-850 range.
- Log out-of-range scores as anomalies.

---

## ANO-008: Payment Component Amounts Don't Sum to Total

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | Medium                    |
| **Table**      | CDW_PMT_HIST              |
| **Columns**    | PMT_AMT vs. PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE |

**Example Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN | INT | ESCROW | LATE_FEE | Computed Sum | Delta |
|-------------|---------|------|-----|--------|----------|-------------|-------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | **+400.00** |
| PMT-2025120002 | 2,924.18 | 1,842.56 | 815.50 | 266.12 | 0.00 | 2,924.18 | 0.00 |
| PMT-2025120003 | 1,077.05 | 297.12 | 779.93 | 0.00 | 0.00 | 1,077.05 | 0.00 |
| PMT-2025120004 | 2,468.35 | 857.23 | 1,611.12 | 0.00 | 0.00 | 2,468.35 | 0.00 |
| PMT-2025120005 | 811.61 | 306.45 | 505.16 | 0.00 | 0.00 | 811.61 | 0.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | **+400.00** |

Payments for loan `LN-2019-00142` have component sums (principal + interest + escrow + late fee) that exceed the total payment amount by $400.00. The escrow amount of $355.55 appears to be double-counted or the total is under-reported.

**Business Impact:** Financial reconciliation reports will show discrepancies. If the total amount is used for cash-flow reporting while component amounts are used for amortization schedules, the books won't balance.

**Recommended Fix:**
- Add a validation check that `PMT_AMT == PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` (within a small tolerance for rounding).
- Log discrepancies with the delta amount.

---

## ANO-009: Delinquency Days Inconsistent with Status Code

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | Medium                    |
| **Table**      | CDW_LN_ACCT               |
| **Columns**    | LN_DLQ_DAYS, LN_STAT_CD   |

**Example Records:**

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Consistent? |
|-------------|-----------|-------------|-------------|
| LN-2019-00142 | ACT | 0 | Yes |
| LN-2018-00089 | ACT | 15 | **No** — 15 days delinquent but status is Active, not Default |
| LN-2021-00567 | ACT | 0 | Yes |

Loan `LN-2018-00089` shows 15 delinquency days but retains an `ACT` (Active) status. While industry practice may allow up to 30 days before changing status to Default, the late fee on its November payment ($47.50) confirms the delinquency is real. This inconsistency suggests status updates lag behind delinquency tracking.

**Business Impact:** Risk reports filtering by status code will undercount delinquent loans. Collection workflows triggered by status won't engage for loans that are delinquent but still marked Active.

**Recommended Fix:**
- Add business rule validation: if `LN_DLQ_DAYS > 0` and `LN_STAT_CD == 'ACT'`, flag as warning.
- If `LN_DLQ_DAYS >= 90`, require status to be `DFT` or `FRB`.

---

## ANO-010: LTV Percent Not Derivable from Available Data

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | Medium                    |
| **Table**      | CDW_LN_ACCT               |
| **Columns**    | LN_LTV_PCT, LN_CURR_BAL, PROP_APRS_VAL |

**Example Records:**

| LN_ACCT_NBR | LN_LTV_PCT | LN_CURR_BAL | PROP_APRS_VAL | Computed LTV | Match? |
|-------------|-----------|-------------|--------------|-------------|--------|
| LN-2019-00142 | 82.5 | 271,432.56 | 345,000 | 78.7% | **No** |
| LN-2020-00398 | 68.2 | 312,876.43 | 615,000 | 50.9% | **No** |
| LN-2018-00089 | 75.0 | 178,234.12 | 260,000 | 68.6% | **No** |

The stored `LN_LTV_PCT` values do not match `LN_CURR_BAL / PROP_APRS_VAL * 100`. This suggests the LTV was calculated at origination using `LN_ORIG_AMT` rather than being updated with the current balance, or the appraised value has been updated since the LTV was recorded. Either way, the stored LTV is stale.

**Business Impact:** Risk assessments using the stored LTV will overestimate exposure. Loans that have been paid down significantly will appear riskier than they actually are.

**Recommended Fix:**
- Recompute LTV from current balance and appraised value during ingestion.
- Store both the original LTV and current LTV.
- Log discrepancies between stored and computed values.

---

## ANO-011: Loan Origination Date Precedes Borrower Created Date

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | Low                       |
| **Table**      | CDW_LN_ACCT, CDW_BORR_MSTR |
| **Columns**    | LN_CRET_DT, BORR_CRET_DT  |

**Example Records:**

| BORR_ID | BORR_CRET_DT | LN_ACCT_NBR | LN_CRET_DT | Loan Before Borrower? |
|---------|-------------|-------------|------------|----------------------|
| B-10003 | 06/10/2018 | LN-2018-00089 | 06/15/2018 | No (OK) |
| B-10005 | 02/14/2017 | LN-2017-00034 | 02/20/2017 | No (OK) |

The current seed data is consistent, but in production, data migration/merger events often create borrower records with `BORR_CRET_DT` set to the migration date rather than the original account opening date. This can make it appear that loans were originated before the borrower existed.

**Business Impact:** Audit trail integrity is compromised. Regulatory reports showing loan origination timelines may flag these as data quality issues.

**Recommended Fix:**
- Validate that `LN_CRET_DT >= BORR_CRET_DT` for each loan-borrower pair.
- Log violations for manual review.

---

## ANO-012: Duplicate/Near-Duplicate Detection — Borrower Records

| Field          | Value                     |
|----------------|---------------------------|
| **Severity**   | Low                       |
| **Table**      | CDW_BORR_MSTR             |
| **Columns**    | BORR_FST_NM, BORR_LST_NM, BORR_DOB_DT, BORR_SSN_ENCR |

The current seed data has 5 distinct borrowers with no duplicates. However, the schema has no unique constraint on any combination of name + DOB + SSN. In production CDW data, the same person can appear multiple times due to:
- Re-entry during system migrations
- Name variations (e.g., "James" vs "Jim" Mitchell)
- Duplicate SSN entries from manual data entry errors

**Business Impact:** Duplicate borrower records lead to fragmented loan portfolios per customer, incorrect total exposure calculations, and compliance issues with KYC (Know Your Customer) requirements.

**Recommended Fix:**
- Implement fuzzy matching on name + DOB + SSN-last-4 during ingestion.
- Flag potential duplicates for manual review.
- Establish a merge/deduplicate workflow.
