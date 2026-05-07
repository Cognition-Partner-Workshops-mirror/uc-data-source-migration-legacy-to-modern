# Legacy CDW Data Anomaly Report

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## ANOM-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** The total payment amount (`PMT_AMT`) does not equal the sum of its component parts (principal + interest + escrow + late fee) for multiple payment records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN + INT + ESCROW + LATE | Delta |
|-------------|---------|----------------------------|-------|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | -400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | -400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | -47.50 |

**Business Impact:** Financial reporting will show incorrect payment breakdowns. Downstream systems consuming the API will calculate wrong principal/interest splits, affecting amortization schedules, tax reporting (interest deduction), and escrow analysis. Auditors would flag these discrepancies.

**Recommended Fix:** Validate that `PMT_AMT == PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` at ingestion. Log a warning when mismatches are detected and either reject the record or flag it for manual review.

---

## ANOM-002: Numeric String Parsing Without Error Handling

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, and all other numeric VARCHAR fields |

**Description:** All numeric values are stored as VARCHAR strings (e.g., `"285,000"`, `"4.750"`, `"745"`). The service layer parses these with `new BigDecimal(...)` and `Integer.parseInt(...)` without try-catch blocks. Any malformed value (e.g., `"N/A"`, `""`, `"$285,000"`, `"TBD"`) will throw an uncaught `NumberFormatException`, crashing the API request.

**Example Bad Records (potential):**

| Scenario | Input Value | Method | Result |
|----------|------------|--------|--------|
| Dollar sign in amount | `$285,000` | `parseLegacyAmount` | `NumberFormatException` |
| Text placeholder | `N/A` | `parseLegacyInteger` | `NumberFormatException` |
| Empty string | ` ` (whitespace) | `parseLegacyDecimal` | `NumberFormatException` |
| Negative with parens | `(1,200)` | `parseLegacyAmount` | `NumberFormatException` |

**Business Impact:** A single malformed record in any numeric field crashes the entire API endpoint (e.g., `/api/loans` returns HTTP 500 for all users, not just the affected record). This is a service availability risk.

**Recommended Fix:** Wrap all numeric parsing in try-catch blocks. Return a safe default (e.g., `BigDecimal.ZERO` or `null`) for unparseable values and log the error with the record identifier for investigation.

---

## ANOM-003: Delinquency Days Contradicts Loan Status

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:** Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). A loan that is 15 days past due should not have an Active status — it should be flagged or moved to a delinquent/watch status.

**Example Bad Records:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| `LN-2018-00089` | 15 | ACT | DLQ or watch status |

**Business Impact:** Delinquent loans appearing as Active will be excluded from collections workflows, risk reports, and regulatory delinquency disclosures. This affects loss-reserve calculations and regulatory compliance.

**Recommended Fix:** Cross-validate delinquency days against status code at ingestion. Flag records where `delinquencyDays > 0` and `status == 'ACT'` as data quality warnings.

---

## ANOM-004: No Foreign Key Constraints — Orphan Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema has zero foreign key constraints. Any of these relationships can be broken:
- `CDW_LN_ACCT.BORR_ID` may reference a non-existent borrower
- `CDW_LN_ACCT.PROD_CD` may reference a non-existent product
- `CDW_PMT_HIST.LN_ACCT_NBR` may reference a non-existent loan account

The current seed data happens to have consistent references, but there is no database-level enforcement preventing orphaned records from appearing.

**Example Bad Records (potential):**

| Table | Column | Value | Referenced Table | Exists? |
|-------|--------|-------|-----------------|---------|
| `CDW_LN_ACCT` | `BORR_ID` | `B-99999` | `CDW_BORR_MSTR` | No |
| `CDW_PMT_HIST` | `LN_ACCT_NBR` | `LN-DELETED` | `CDW_LN_ACCT` | No |

**Business Impact:** Orphaned loan accounts would appear without borrower information, causing NullPointerExceptions in the service layer when looking up borrower details. Orphaned payments would be invisible in loan payment histories.

**Recommended Fix:** Validate referential integrity at ingestion time. Verify that every `BORR_ID` in loan accounts exists in the borrower master, every `PROD_CD` exists in loan products, and every `LN_ACCT_NBR` in payments exists in loan accounts.

---

## ANOM-005: Date Strings Passed Through Without Parsing or Validation

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | All `*_DT` columns (e.g., `BORR_DOB_DT`, `LN_ORIG_DT`, `PMT_DT`, `PMT_RECV_DT`) |

**Description:** All date fields are stored as VARCHAR in `MM/DD/YYYY` format. The service layer passes these through as raw strings in the DTOs (`originationDate`, `paymentDate`) without ever parsing or validating them. Invalid dates like `"02/30/2025"`, `"13/01/2020"`, or `"TBD"` would be silently passed to API consumers.

**Example Bad Records (potential):**

| Scenario | Input Value | Expected Behavior |
|----------|------------|-------------------|
| Invalid month | `13/01/2020` | Should be rejected |
| Invalid day | `02/30/2025` | Should be rejected |
| Wrong format | `2025-01-15` | ISO format instead of MM/DD/YYYY |
| Placeholder | `TBD` | Should be rejected |

**Business Impact:** API consumers receive unparsed date strings that may be in inconsistent formats. Downstream systems that attempt to parse these dates will fail unpredictably. The `column_mappings.md` specifies these should be converted to `DATE` or `TIMESTAMP` types.

**Recommended Fix:** Parse all date strings to `LocalDate` at the service layer using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` with error handling. Return dates in ISO 8601 format in API responses.

---

## ANOM-006: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** Borrower first name, last name, and SSN last-4 are duplicated in the loan account table. The service layer reads borrower name from the denormalized loan account fields (`acct.getBorrowerFirstName()`) rather than from the borrower master table. If a borrower's name is updated in `CDW_BORR_MSTR` but not in `CDW_LN_ACCT`, the API will return stale data.

**Example Bad Records (potential):**

| LN_ACCT_NBR | BORR_FST_NM (CDW_LN_ACCT) | BORR_FST_NM (CDW_BORR_MSTR) | Consistent? |
|-------------|----------------------------|------------------------------|-------------|
| `LN-2019-00142` | James | James | Yes (currently) |
| *(future)* | James | Jim | No — name change not propagated |

**Business Impact:** Loan summaries may show outdated borrower names, causing confusion in customer-facing systems and potential compliance issues with name-based identity verification.

**Recommended Fix:** Cross-reference denormalized borrower fields against the master record at ingestion time. Log warnings when mismatches are detected. Prefer the master record as the source of truth.

---

## ANOM-007: String-Based Date Sorting in Repository

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT` |

**Description:** The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts by `PMT_DT` (a VARCHAR column) using lexicographic ordering. The `MM/DD/YYYY` format does not sort chronologically as strings. For example, `"02/01/2026"` would sort before `"12/01/2025"` because `"02"` < `"12"`, even though February 2026 is after December 2025.

**Example Bad Records:**

| Date String | Lexicographic Order | Chronological Order |
|-------------|--------------------|--------------------|
| `12/01/2025` | 2nd | 1st |
| `02/01/2026` | 1st | 2nd |

**Business Impact:** Payment history returned by the API will be in incorrect order when payments span year boundaries, showing older payments before newer ones.

**Recommended Fix:** Parse date strings before sorting in the service layer, or add a computed/indexed date column for proper ordering.

---

## ANOM-008: Late Payment Received-Date Anomalies

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT` |

**Description:** Some payment records have `PMT_RECV_DT` (received date) significantly after `PMT_DT` (due date), indicating late receipt without corresponding late-fee or status adjustments.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | Days Late | PMT_LATE_FEE | PMT_STAT_CD |
|-------------|--------|-------------|-----------|--------------|-------------|
| `PMT-2025120003` | 12/01/2025 | 12/05/2025 | 4 | 0.00 | PST |
| `PMT-2025110003` | 11/01/2025 | 11/18/2025 | 17 | 47.50 | PST |

Note: `PMT-2025120003` was received 4 days late but has no late fee, while `PMT-2025110003` (17 days late) correctly has a $47.50 late fee. The inconsistency in late-fee application is a data quality issue.

**Business Impact:** Inconsistent late-fee application may indicate misconfigured grace period logic or manual overrides that were not documented. This affects revenue reconciliation and borrower fairness.

**Recommended Fix:** Validate that late fees are consistently applied based on days-late thresholds. Flag records where `receivedDate > paymentDate + gracePeriod` but `lateFee == 0`.

---

## ANOM-009: NULL Values in Optional-but-Important Fields

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

**Description:** Several borrower records have NULL values for middle initial and address line 2. While these fields are technically optional, the middle initial is used in full-name construction in the service layer and NULL handling must be explicit.

**Example Bad Records:**

| BORR_ID | BORR_MID_INIT | BORR_ADDR_LN2 |
|---------|---------------|----------------|
| `B-10005` | NULL | NULL |
| `B-10002` | `L` | NULL |
| `B-10003` | `A` | NULL |

**Business Impact:** Low — the service layer already handles NULL middle initials with a ternary check. However, if other code paths assume non-null values, NullPointerExceptions could occur.

**Recommended Fix:** Ensure all code paths that access nullable fields have explicit null checks. Consider defaulting middle initial to empty string for consistent formatting.

---

## ANOM-010: Annual Income Not Exposed in API

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_ANN_INCM` |

**Description:** The `column_mappings.md` specifies that `BORR_ANN_INCM` (e.g., `"92,500"`) should be parsed to `DECIMAL(12,2)` and mapped to `annual_income`. However, the `BorrowerDto` does not include an annual income field, and the service layer does not parse or expose this data.

**Example Records:**

| BORR_ID | BORR_ANN_INCM | Expected Modern Value |
|---------|---------------|----------------------|
| `B-10001` | `92,500` | 92500.00 |
| `B-10002` | `125,000` | 125000.00 |

**Business Impact:** Annual income data is lost in the API transformation, reducing the utility of the borrower endpoint for underwriting or financial analysis consumers.

**Recommended Fix:** Add `annualIncome` field to `BorrowerDto` and parse it using the existing `parseLegacyAmount` method.
