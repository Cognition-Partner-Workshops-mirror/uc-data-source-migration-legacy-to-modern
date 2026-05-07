# Legacy CDW Data Anomaly Report

> **Generated from:** `src/main/resources/data-legacy.sql` and `src/main/resources/schema-legacy.sql`
> **Service:** `loan-service` (uc-data-source-migration-legacy-to-modern)

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3     |
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

**Description:** The sum of payment components (principal + interest + escrow + late fee) does not equal the total payment amount for multiple records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT (Total) | Principal | Interest | Escrow | Late Fee | Component Sum | Delta |
|-------------|-----------------|-----------|----------|--------|----------|---------------|-------|
| `PMT-2025120001` | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | **1,887.02** | +400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | **1,887.02** | +400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | **1,124.55** | +47.50 |

**Business Impact:** Incorrect payment breakdowns cause regulatory reporting errors (TILA, RESPA), wrong escrow analysis statements, and inaccurate interest income calculations. Downstream systems consuming these amounts would produce mismatched general ledger entries.

**Recommended Fix:** Validate that `principal + interest + escrow + late_fee == total` at ingestion. When a mismatch is detected, log the anomaly and flag the record for manual review. Do not silently adjust component amounts.

---

## ANO-002: SSN Last-4 Populated from Phone Numbers

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

**Description:** The `BORR_SSN_LST4` field in the loan accounts table contains the last 4 digits of the borrower's phone number rather than their actual SSN.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | Borrower Phone (CDW_BORR_MSTR) | Phone Last 4 |
|-------------|---------|---------------|-------------------------------|--------------|
| `LN-2019-00142` | B-10001 | 0142 | 217-555-**0142** | 0142 |
| `LN-2020-00398` | B-10002 | 0198 | 503-555-**0198** | 0198 |
| `LN-2018-00089` | B-10003 | 0167 | 512-555-**0167** | 0167 |
| `LN-2021-00567` | B-10004 | 0134 | 303-555-**0134** | 0134 |
| `LN-2017-00034` | B-10005 | 0156 | 602-555-**0156** | 0156 |

Every record is affected (100% of loan accounts). The pattern is systematic, indicating a data load or ETL mapping error.

**Business Impact:** PII misidentification is a compliance violation (GLBA, FCRA). Any process using SSN last-4 for identity verification (customer service, fraud checks) is matching against phone digits instead. This could cause false identity matches or failed verifications.

**Recommended Fix:** Flag the `BORR_SSN_LST4` column as unreliable. Cross-reference against `CDW_BORR_MSTR.BORR_SSN_ENCR` to derive correct SSN last-4 values. Never use the current values for identity verification.

---

## ANO-003: No Foreign Key Constraints (Orphan Risk)

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | All legacy tables |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema defines zero foreign key constraints. Referential integrity is not enforced at the database level, meaning:
- `CDW_LN_ACCT.BORR_ID` can reference a non-existent borrower
- `CDW_LN_ACCT.PROD_CD` can reference a non-existent product
- `CDW_PMT_HIST.LN_ACCT_NBR` can reference a non-existent loan account

**Example Bad Records:** The current seed data happens to have consistent references, but the schema permits any arbitrary string in FK columns. A single bad data load could introduce orphaned records.

**Business Impact:** Orphaned loan accounts produce `NullPointerException` in `LoanService.toLoanSummary()` when the product lookup returns null (line 54: `products.get(acct.getProductCode())` returns null). Orphaned payments are silently associated with non-existent loans, creating phantom transaction history.

**Recommended Fix:** Validate all FK references at ingestion time before processing. For loan accounts, verify `BORR_ID` exists in `CDW_BORR_MSTR` and `PROD_CD` exists in `CDW_LN_PROD`. For payments, verify `LN_ACCT_NBR` exists in `CDW_LN_ACCT`.

---

## ANO-004: Numeric Strings with Parsing Risks

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | All amount, rate, score, and count columns |

**Description:** All numeric values are stored as VARCHAR strings with embedded formatting (commas, potential dollar signs, spaces). The current `parseLegacyAmount()` method only strips commas. The `parseLegacyInteger()` method only trims whitespace. Neither handles:
- Currency symbols (`$285,000`)
- Parenthetical negatives (`(1,487.02)`)
- Letters or special characters (`N/A`, `---`, `PENDING`)
- Extra whitespace or non-breaking spaces

**Example columns at risk:**
- `BORR_CRDT_SCR` (credit score): parsed via `Integer.parseInt()` -- any non-numeric value throws `NumberFormatException`
- `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`: parsed via `new BigDecimal()` -- malformed strings cause unhandled exceptions
- `LN_DLQ_DAYS`, `PROD_TERM_MOS`: integer fields stored as strings

**Business Impact:** A single malformed record causes an unhandled `NumberFormatException` that propagates as an HTTP 500 error, breaking the entire API response (including valid records returned in list endpoints).

**Recommended Fix:** Wrap all parsing in try-catch with fallback defaults. Log malformed values as warnings. Return a sanitized default (e.g., `BigDecimal.ZERO` for amounts, `null` for scores) instead of crashing.

---

## ANO-005: Delinquent Loan Marked as Active

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_STAT_CD`, `LN_DLQ_DAYS` |

**Description:** Loan `LN-2018-00089` (borrower Michael Torres) has `LN_DLQ_DAYS = '15'` while `LN_STAT_CD = 'ACT'`. A loan that is 15 days delinquent should not have an unqualified "Active" status.

**Example Bad Records:**

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Expected Status |
|-------------|-----------|-------------|-----------------|
| `LN-2018-00089` | ACT | 15 | DLQ or ACT-DLQ |

**Business Impact:** Delinquent loans reported as "Active" in API responses mislead risk dashboards, regulatory reports (call reports, HMDA), and collection workflows. Downstream systems may skip collection actions on loans that need attention.

**Recommended Fix:** Cross-validate status and delinquency days. If `delinquency_days > 0` and status is `ACT`, flag a warning. Consider adding a derived status that accounts for delinquency.

---

## ANO-006: Date Strings Not Validated or Parsed

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | All `*_DT` columns (16 columns across 4 tables) |

**Description:** All date fields are stored as VARCHAR(10) with an expected format of `MM/DD/YYYY`. The service layer does not parse or validate these dates -- they are passed through as raw strings to the DTOs (`LoanSummaryDto.originationDate`, `PaymentDto.paymentDate`). This means:
- Invalid dates (e.g., `02/30/2025`, `13/01/2025`) pass through silently
- Different formats (e.g., `2025-01-15`, `15/01/2025`) would not be caught
- Date comparison and sorting operations on string dates produce incorrect results

**Example:** `LoanSummaryDto.originationDate` is a raw `String` set directly from `acct.getOriginationDate()` with no parsing. The `PaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc` sorts by the string value, not a true date -- string sorting of `MM/DD/YYYY` does not produce chronological order.

**Business Impact:** Incorrect date sorting produces out-of-order payment histories. Invalid dates cause failures in downstream systems that do parse them. API consumers receive unparsed legacy format strings instead of ISO-8601 dates.

**Recommended Fix:** Parse all date strings to `LocalDate` at ingestion time using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Return ISO-8601 formatted dates in API responses. Reject or flag records with unparseable dates.

---

## ANO-007: Borrower Status Code Not Translated

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_STAT_CD` |

**Description:** The `column_mappings.md` specifies that `BORR_STAT_CD` should be expanded (`ACT`->`ACTIVE`, `INA`->`INACTIVE`). However, the `LoanService.toBorrowerDto()` method does not include borrower status in the `BorrowerDto` at all. The field is read from the database but never exposed via the API.

Additionally, `LoanService.expandStatusCode()` is designed for loan status codes (`ACT`, `CLO`, `DFT`, `FRB`) and does not handle borrower-specific codes like `INA` (Inactive).

**Business Impact:** API consumers cannot determine borrower status. Inactive borrowers are indistinguishable from active ones. Any borrower filtering or lifecycle management must be done by querying the raw legacy table directly, bypassing the service layer.

**Recommended Fix:** Add a `status` field to `BorrowerDto`. Create a dedicated `expandBorrowerStatusCode()` method that handles `ACT`->`ACTIVE`, `INA`->`INACTIVE`, and other borrower-specific codes.

---

## ANO-008: Denormalized Borrower Data Drift

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** `CDW_LN_ACCT` contains denormalized copies of borrower first name, last name, and SSN last-4 from `CDW_BORR_MSTR`. Without constraints or triggers, these can drift when the master record is updated but the loan account copy is not. The service uses the denormalized values from `CDW_LN_ACCT` for the loan summary (`toLoanSummary` reads `acct.getBorrowerFirstName()`) rather than joining to the master.

**Example:** If borrower B-10002 changes their last name from "Chen" to "Chen-Williams" in `CDW_BORR_MSTR`, the loan account `LN-2020-00398` would still show "Chen", producing inconsistent API responses.

**Business Impact:** Stale denormalized data causes name mismatches between the borrower detail and loan summary endpoints, confusing API consumers and potentially causing identity verification failures.

**Recommended Fix:** At ingestion, cross-reference denormalized fields against the master table and log warnings when mismatches are detected. Prefer master table values for API responses.

---

## ANO-009: Payment Date vs Received Date Temporal Anomaly

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT` |

**Description:** Some payments have a received date significantly after the payment date, suggesting the payment date field represents the due date rather than the actual payment date, or that payments were received late.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | PMT_PROC_DT | Days Late |
|-------------|--------|-------------|-------------|-----------|
| `PMT-2025120003` | 12/01/2025 | 12/05/2025 | 12/06/2025 | 5 days |
| `PMT-2025110003` | 11/01/2025 | 11/18/2025 | 11/19/2025 | 17 days |

Both records are for loan `LN-2018-00089` (the delinquent loan), which is consistent with the 15-day delinquency in ANO-005.

**Business Impact:** If `PMT_DT` is treated as the actual payment date, late payments appear on-time. This affects delinquency calculations, late fee assessments, and regulatory reporting.

**Recommended Fix:** Validate temporal ordering: `PMT_DT <= PMT_RECV_DT <= PMT_PROC_DT`. Flag records where received date is more than 3 business days after payment date. Clarify whether `PMT_DT` represents the due date or actual payment date.

---

## ANO-010: LTV Percent Rounding Inconsistencies

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_LTV_PCT`, `LN_ORIG_AMT`, `PROP_APRS_VAL` |

**Description:** The stored LTV percentages do not match the calculated values from `original_amount / appraised_value * 100`. Rounding varies across records.

**Example Bad Records:**

| LN_ACCT_NBR | Original Amount | Appraised Value | Stored LTV | Calculated LTV | Delta |
|-------------|----------------|-----------------|-----------|----------------|-------|
| `LN-2019-00142` | 285,000 | 345,000 | 82.5 | 82.609 | -0.109 |
| `LN-2020-00398` | 420,000 | 615,000 | 68.2 | 68.293 | -0.093 |
| `LN-2021-00567` | 525,000 | 721,000 | 72.8 | 72.816 | -0.016 |
| `LN-2018-00089` | 195,000 | 260,000 | 75.0 | 75.000 | 0.000 |
| `LN-2017-00034` | 165,000 | 206,000 | 80.0 | 80.097 | -0.097 |

**Business Impact:** LTV is a key metric for mortgage insurance requirements (typically required above 80% LTV). Rounding errors could cause incorrect MI determinations. For example, `LN-2017-00034` shows 80.0% but is actually 80.097%, which crosses the 80% MI threshold.

**Recommended Fix:** Recalculate LTV at ingestion from the source amounts rather than trusting the stored value. Flag records where the stored LTV deviates more than 0.05% from the calculated value.

---

## ANO-011: All-VARCHAR Schema (Systemic Loose Typing)

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | All tables |
| **Affected Columns** | All columns |

**Description:** The entire legacy schema uses VARCHAR for every column, including dates, amounts, integers, percentages, and booleans. This is a systemic design pattern of the legacy CDW, not individual data errors.

**Business Impact:** The database provides no type safety. Any string can be inserted into any field without constraint validation. This is the root cause of many other anomalies in this report.

**Recommended Fix:** This is addressed by the migration to the modern schema, which uses proper types (DATE, DECIMAL, INTEGER, BOOLEAN). In the interim, the service layer must perform all type validation.
