# Legacy CDW Data Anomaly Report

This report documents data quality anomalies discovered in the legacy Corporate Data Warehouse
(CDW) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`).

---

## ANO-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** The sum of payment components (principal + interest + escrow + late fee) does
not equal the recorded total payment amount for certain records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN+INT+ESC+LATE | Difference |
|-------------|---------|-------------------|------------|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | **+47.50** |

**Business Impact:** Incorrect payment allocations lead to erroneous principal balance tracking,
wrong interest accrual calculations, and inaccurate escrow accounting. Financial statements and
regulatory reports will contain incorrect figures. For loan `LN-2019-00142`, the $400 discrepancy
per payment compounds over time, resulting in significant balance misstatement.

**Recommended Fix:** Validate at ingestion that `PMT_AMT == PMT_PRIN_AMT + PMT_INT_AMT +
PMT_ESCROW_AMT + PMT_LATE_FEE`. When a mismatch is detected, flag the record for review and
log the discrepancy. Do not silently accept mismatched records into the modern schema.

---

## ANO-002: Numeric Strings Without Error Handling

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `BORR_CRDT_SCR`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, all `PMT_*_AMT` columns |

**Description:** All monetary, rate, and numeric values are stored as `VARCHAR` strings with
embedded formatting (commas, decimals). The service layer parses these with `BigDecimal` and
`Integer.parseInt()` but has no try-catch error handling. Any malformed value (e.g., `"$285,000"`,
`"N/A"`, `"TBD"`, empty string with whitespace) causes an unhandled `NumberFormatException` that
crashes the entire API request.

**Example Risk Scenarios:**

| Column | Valid Value | Potential Bad Value | Failure |
|--------|------------|---------------------|---------|
| `BORR_CRDT_SCR` | `"745"` | `"N/A"` or `"PENDING"` | `NumberFormatException` in `parseLegacyInteger` |
| `BORR_ANN_INCM` | `"92,500"` | `"$92,500.00"` or `"UNKNOWN"` | `NumberFormatException` in `parseLegacyAmount` |
| `LN_INT_RT` | `"4.750"` | `"4.750%"` or `"VARIABLE"` | `NumberFormatException` in `parseLegacyDecimal` |
| `LN_DLQ_DAYS` | `"15"` | `""` or `"N/A"` | Not currently parsed, but will fail at migration |

**Business Impact:** A single malformed record in any legacy table causes the entire API endpoint
to return a 500 error. All borrowers or all loans become inaccessible because `getAllLoans()` and
`getAllBorrowers()` iterate over every record. One bad record poisons the entire dataset.

**Recommended Fix:** Wrap all parse operations in try-catch blocks. Return sensible defaults
(e.g., `BigDecimal.ZERO` for amounts, `null` for credit scores) and log warnings with the
record ID and malformed value for investigation.

---

## ANO-003: No Foreign Key Constraints (Orphan Risk)

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema explicitly has no foreign key constraints. Any record can
reference a non-existent parent. The service layer does `products.get(acct.getProductCode())`
which returns `null` for orphaned product references, and the code handles this with a fallback.
However, orphaned `BORR_ID` references in loan accounts are never validated.

**Example Risk:** If a `CDW_LN_ACCT` record references `BORR_ID = 'B-99999'` (non-existent),
the `toLoanSummary` method still succeeds using denormalized borrower fields, but
`getBorrowerById` would fail to find the borrower, and the loan-to-borrower relationship is
broken. Payment records referencing deleted loan accounts would silently exist without a parent.

**Business Impact:** Orphaned records cause data integrity failures during migration. Loan
accounts without valid borrowers cannot be migrated to the normalized modern schema (which
requires a valid `borrower_id` FK). Orphaned payments inflate or deflate loan payment histories.

**Recommended Fix:** Validate referential integrity at ingestion time. Check that every
`BORR_ID` in `CDW_LN_ACCT` exists in `CDW_BORR_MSTR`, every `PROD_CD` exists in `CDW_LN_PROD`,
and every `LN_ACCT_NBR` in `CDW_PMT_HIST` exists in `CDW_LN_ACCT`. Log and quarantine orphans.

---

## ANO-004: Delinquency Days vs Loan Status Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:** Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but
`LN_STAT_CD = 'ACT'` (Active). A loan with delinquency should have a status reflecting this
condition (e.g., `DLQ` for delinquent, or at minimum a warning flag).

**Example Bad Record:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| `LN-2018-00089` | `15` | `ACT` | `DLQ` or flagged |

**Business Impact:** Regulatory reports and portfolio risk assessments rely on status codes to
identify troubled assets. A loan showing as "Active" while being delinquent understates portfolio
risk and may violate reporting requirements. Downstream systems that filter on status code will
miss this delinquent loan entirely.

**Recommended Fix:** Cross-validate delinquency days against status code at ingestion. If
`LN_DLQ_DAYS > 0` and `LN_STAT_CD = 'ACT'`, flag as a data quality warning. Consider adding
a derived `isDelinquent` field to the DTO.

---

## ANO-005: Denormalized Borrower Name Drift

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM` (in `CDW_LN_ACCT` vs `CDW_BORR_MSTR`) |

**Description:** The `CDW_LN_ACCT` table contains denormalized copies of borrower first and last
names. The service uses these denormalized copies (`acct.getBorrowerFirstName()`) in
`toLoanSummary()` rather than looking up the canonical name from `CDW_BORR_MSTR`. If a
borrower's name is updated in the master table but not in the loan account table, the API returns
inconsistent names depending on whether you query loans vs borrowers.

**Example Risk:** If borrower `B-10002` changes last name from `Chen` to `Chen-Smith` in
`CDW_BORR_MSTR`, the borrower API returns "Sarah L. Chen-Smith" but the loan API still returns
"Sarah Chen" from the denormalized copy.

**Business Impact:** Inconsistent borrower names across API endpoints erode consumer trust and
can cause compliance issues (e.g., name on correspondence doesn't match legal records). During
migration, conflicting names require manual resolution.

**Recommended Fix:** At ingestion, cross-reference denormalized names against the master borrower
table. Log a warning when discrepancies are found. In the service layer, prefer the master record
name over the denormalized copy.

---

## ANO-006: Late Fee Inconsistency on Late Payments

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_LATE_FEE`, `PMT_RECV_DT`, `PMT_DT` |

**Description:** Payment `PMT-2025120003` was received on `12/05/2025` for a `12/01/2025` due
date (4 days late) but has `PMT_LATE_FEE = '0.00'`. Meanwhile, `PMT-2025110003` was received
`11/18/2025` for a `11/01/2025` due date (17 days late) and correctly has a `$47.50` late fee.
The inconsistent application of late fees suggests either a grace period that is not documented
or a data entry error.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | Days Late | PMT_LATE_FEE | Expected |
|-------------|--------|-------------|-----------|--------------|----------|
| `PMT-2025120003` | 12/01/2025 | 12/05/2025 | 4 | 0.00 | >= 0 (grace period?) |
| `PMT-2025110003` | 11/01/2025 | 11/18/2025 | 17 | 47.50 | 47.50 |

**Business Impact:** Inconsistent late fee application affects revenue recognition and borrower
account accuracy. If a grace period exists (e.g., 15 days), it should be documented and
enforced systematically.

**Recommended Fix:** Validate late fee consistency at ingestion. If `PMT_RECV_DT` is more than
the grace period after `PMT_DT` and `PMT_LATE_FEE = 0`, flag as a potential anomaly.

---

## ANO-007: Stale LTV (Loan-to-Value) Percentages

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_LTV_PCT`, `LN_CURR_BAL`, `PROP_APRS_VAL` |

**Description:** The `LN_LTV_PCT` values appear to be calculated from the original loan amount
rather than the current balance, making them stale and misleading.

**Example Bad Records:**

| LN_ACCT_NBR | LN_CURR_BAL | PROP_APRS_VAL | LTV (current) | LTV (recorded) | LTV (original) |
|-------------|-------------|---------------|----------------|-----------------|-----------------|
| `LN-2019-00142` | 271,432.56 | 345,000 | **78.7%** | **82.5%** | 82.6% (285K/345K) |
| `LN-2020-00398` | 312,876.43 | 615,000 | **50.9%** | **68.2%** | 68.3% (420K/615K) |
| `LN-2018-00089` | 178,234.12 | 260,000 | **68.6%** | **75.0%** | 75.0% (195K/260K) |
| `LN-2021-00567` | 498,123.78 | 721,000 | **69.1%** | **72.8%** | 72.8% (525K/721K) |
| `LN-2017-00034` | 142,567.90 | 206,000 | **69.2%** | **80.0%** | 80.1% (165K/206K) |

**Business Impact:** Stale LTV values affect risk assessment, PMI (Private Mortgage Insurance)
decisions, and regulatory capital calculations. A borrower who has paid down to 78.7% LTV should
be eligible to drop PMI, but the stale 82.5% value keeps them paying it unnecessarily.

**Recommended Fix:** Recalculate LTV at ingestion as `(LN_CURR_BAL / PROP_APRS_VAL) * 100`.
Store both original and current LTV in the modern schema. Log warnings when the stored LTV
deviates from the calculated value by more than 1%.

---

## ANO-008: Date Strings Never Parsed to Typed Dates

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | All tables |
| **Affected Columns** | All `*_DT` columns (`BORR_DOB_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.) |

**Description:** All date fields are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. The service
layer passes these raw strings directly to DTOs without parsing to `java.time.LocalDate`. This
means invalid dates (e.g., `02/30/2020`, `13/15/2025`, `00/00/0000`) would be accepted silently
and returned verbatim through the API. The `column_mappings.md` specifies these should be
converted to `DATE` or `TIMESTAMP` types, but the code does not perform this conversion.

**Example Risk:** A record with `BORR_DOB_DT = '02/30/1985'` (February 30 does not exist) would
pass through the system undetected and be returned to API consumers as-is.

**Business Impact:** API consumers cannot reliably sort, filter, or compute date ranges on
string-formatted dates. Invalid dates cause failures in downstream date-aware systems. The
`MM/DD/YYYY` format is US-specific and ambiguous for international consumers.

**Recommended Fix:** Parse all date strings to `LocalDate` at ingestion using
`DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Catch `DateTimeParseException` and log invalid
dates with the record ID. Return dates in ISO-8601 format (`yyyy-MM-dd`) in API responses.

---

## ANO-009: NULL Values in Optional-but-Expected Fields

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

**Description:** Borrower `B-10005` (Robert Williams) has `NULL` for `BORR_MID_INIT`. While the
code handles this in `toBorrowerDto`, the NULL propagates to full name construction. Additionally,
multiple borrowers have `NULL` for `BORR_ADDR_LN2` which is expected (not all addresses have a
second line) but is not validated for consistency.

**Example Bad Records:**

| BORR_ID | BORR_MID_INIT | Impact |
|---------|---------------|--------|
| `B-10005` | `NULL` | Full name constructed as "Robert Williams" (no middle initial) |
| `B-10002` | `L` | Full name constructed as "Sarah L. Chen" (with middle initial) |

**Business Impact:** Inconsistent name formatting across records. While individually not critical,
NULL handling in string concatenation is a frequent source of `NullPointerException` in Java code
paths that don't anticipate it.

**Recommended Fix:** Define explicit handling for NULL optional fields. Use empty string defaults
where appropriate. Document which fields are truly optional vs required.

---

## ANO-010: Escrow Balance vs Payment Escrow Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `LN_ESCROW_BAL`, `PMT_ESCROW_AMT` |

**Description:** Several loans show non-zero escrow balances in `CDW_LN_ACCT` but have `$0.00`
escrow amounts in their payment records in `CDW_PMT_HIST`.

**Example Bad Records:**

| LN_ACCT_NBR | LN_ESCROW_BAL | PMT_ESCROW_AMT (Dec) | PMT_ESCROW_AMT (Nov) |
|-------------|---------------|----------------------|----------------------|
| `LN-2018-00089` | 2,100.00 | 0.00 | 0.00 |
| `LN-2021-00567` | 6,750.00 | 0.00 | 0.00 |
| `LN-2017-00034` | 1,890.45 | 0.00 | 0.00 |

Meanwhile, loans that DO have escrow payments show consistent balances:

| LN_ACCT_NBR | LN_ESCROW_BAL | PMT_ESCROW_AMT |
|-------------|---------------|----------------|
| `LN-2019-00142` | 3,245.80 | 355.55 |
| `LN-2020-00398` | 4,890.12 | 266.12 |

**Business Impact:** Unclear how escrow balances accumulated if no escrow is being collected in
payments. This could indicate a separate escrow collection mechanism not captured in payment
history, or stale/incorrect escrow balance data.

**Recommended Fix:** Cross-validate escrow balances against payment history at ingestion. Flag
records where escrow balance is non-zero but recent payment escrow amounts are consistently zero.

---

## Summary

| ID | Title | Severity | Table(s) |
|----|-------|----------|----------|
| ANO-001 | Payment Component Sum Mismatch | Critical | `CDW_PMT_HIST` |
| ANO-002 | Numeric Strings Without Error Handling | Critical | All tables |
| ANO-003 | No Foreign Key Constraints (Orphan Risk) | Critical | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| ANO-004 | Delinquency Days vs Loan Status Inconsistency | High | `CDW_LN_ACCT` |
| ANO-005 | Denormalized Borrower Name Drift | High | `CDW_LN_ACCT` |
| ANO-006 | Late Fee Inconsistency on Late Payments | High | `CDW_PMT_HIST` |
| ANO-007 | Stale LTV Percentages | High | `CDW_LN_ACCT` |
| ANO-008 | Date Strings Never Parsed to Typed Dates | Medium | All tables |
| ANO-009 | NULL Values in Optional-but-Expected Fields | Medium | `CDW_BORR_MSTR` |
| ANO-010 | Escrow Balance vs Payment Escrow Mismatch | Medium | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
