# Data Anomaly Report — Legacy CDW Tables

> **Generated:** 2026-05-08
> **Scope:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`
> **Source system:** Corporate Data Warehouse (CDW) legacy loan management tables

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2     |
| High     | 4     |
| Medium   | 3     |
| Low      | 2     |
| **Total** | **11** |

---

## ANO-001: SSN Last-4 Field Contains Phone Number Suffixes

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

### Description
The `BORR_SSN_LST4` column, intended to store the last 4 digits of the borrower's Social Security Number, instead contains the last 4 digits of the borrower's phone number. Every record exhibits this corruption.

### Example Bad Records

| LN_ACCT_NBR | BORR_SSN_LST4 | BORR_PH_NBR (from CDW_BORR_MSTR) | Phone Last 4 |
|-------------|---------------|-----------------------------------|--------------|
| LN-2019-00142 | 0142 | 217-555-**0142** | 0142 |
| LN-2020-00398 | 0198 | 503-555-**0198** | 0198 |
| LN-2018-00089 | 0167 | 512-555-**0167** | 0167 |
| LN-2021-00567 | 0134 | 303-555-**0134** | 0134 |
| LN-2017-00034 | 0156 | 602-555-**0156** | 0156 |

All 5 out of 5 records (100%) have SSN last-4 equal to the phone number suffix.

### Business Impact
- **PII misrepresentation:** Downstream systems relying on SSN last-4 for identity verification will match on wrong data.
- **Compliance risk:** Regulatory reports (HMDA, TILA) that include SSN last-4 will contain incorrect PII.
- **Verification failures:** Borrower identity verification flows that cross-check SSN last-4 against bureau data will fail.

### Recommended Fix
- Flag `BORR_SSN_LST4` as corrupted; do not migrate this column to the modern schema.
- Source correct SSN last-4 from the encrypted SSN field (`BORR_SSN_ENCR` in `CDW_BORR_MSTR`) after decryption.
- Add validation: SSN last-4 must NOT match the last 4 digits of any phone number on file.

---

## ANO-002: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT` |

### Description
For loan `LN-2019-00142`, the sum of principal + interest + escrow does not equal the total payment amount. Both payment records for this loan are off by exactly $400.00.

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT | PMT_PRIN_AMT | PMT_INT_AMT | PMT_ESCROW_AMT | Computed Sum | Difference |
|-------------|---------|--------------|-------------|----------------|-------------|------------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 1,887.02 | **-400.00** |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 1,887.02 | **-400.00** |

All other 8 payment records sum correctly (components = total).

### Business Impact
- **Financial reporting errors:** General ledger reconciliation will show a $400 discrepancy per payment.
- **Incorrect amortization:** The principal/interest split is wrong, leading to incorrect remaining-balance calculations.
- **Audit failures:** Regulators examining payment breakdowns will flag the inconsistency.

### Recommended Fix
- Quarantine affected payment records for manual review.
- Add validation: `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT` must equal `PMT_AMT` (within a small tolerance, e.g., $0.01).
- Investigate whether the escrow amount ($355.55) was incorrectly added (the loan's monthly payment of $1,487.02 matches P+I if escrow were excluded differently).

---

## ANO-003: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Description
The legacy schema defines no foreign key constraints. `CDW_LN_ACCT.BORR_ID` is not constrained to reference `CDW_BORR_MSTR.BORR_ID`, `CDW_LN_ACCT.PROD_CD` is not constrained to `CDW_LN_PROD.PROD_CD`, and `CDW_PMT_HIST.LN_ACCT_NBR` is not constrained to `CDW_LN_ACCT.LN_ACCT_NBR`. Any insert with a non-existent ID will succeed silently.

### Example Bad Records
Current seed data has no actual orphans, but the schema permits:
```sql
-- This would succeed despite 'BOGUS' not existing in CDW_BORR_MSTR
INSERT INTO CDW_LN_ACCT VALUES ('LN-FAKE', 'BOGUS', ...);
```

### Business Impact
- **Silent data corruption:** Orphaned loan accounts or payments can accumulate over time without detection.
- **Runtime NullPointerException:** `LoanService.getLoanById()` calls `loanProductRepository.findById(acct.getProductCode()).orElse(null)`, then passes the result to `toLoanSummary()` — a null product is handled but an orphaned borrower ID would cause missing data in the API response.

### Recommended Fix
- Validate referential integrity at ingestion: every `BORR_ID` in `CDW_LN_ACCT` must exist in `CDW_BORR_MSTR`, every `PROD_CD` must exist in `CDW_LN_PROD`, and every `LN_ACCT_NBR` in `CDW_PMT_HIST` must exist in `CDW_LN_ACCT`.
- Modern schema already has proper FK constraints — ensure migration validates before insert.

---

## ANO-004: Numeric Values Stored as Strings with Comma Formatting

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `BORR_CRDT_SCR`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PROD_TERM_MOS`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Description
All numeric values (monetary amounts, percentages, integers) are stored as `VARCHAR` strings. Monetary amounts include comma formatting (e.g., `'285,000'`, `'1,487.02'`). This creates parsing risks: `new BigDecimal("285,000")` throws `NumberFormatException`; comma stripping is required before parsing.

### Example Bad Records

| Table | Column | Value | Parse Risk |
|-------|--------|-------|-----------|
| CDW_BORR_MSTR | BORR_ANN_INCM | `'92,500'` | `NumberFormatException` without comma removal |
| CDW_LN_PROD | PROD_MAX_AMT | `'1,500,000'` | `NumberFormatException` without comma removal |
| CDW_LN_ACCT | LN_ORIG_AMT | `'285,000'` | `NumberFormatException` without comma removal |
| CDW_PMT_HIST | PMT_AMT | `'1,487.02'` | `NumberFormatException` without comma removal |

### Business Impact
- **Runtime failures:** Any code path that parses these values without first removing commas will throw `NumberFormatException`.
- **Silent data loss:** `parseLegacyAmount()` in `LoanService.java` returns `BigDecimal.ZERO` for null/blank values — if a malformed string bypasses the null check but still fails parsing, the exception is unhandled.

### Recommended Fix
- Implement robust parsing: strip commas, trim whitespace, validate numeric format before conversion.
- Add fallback defaults with logging so bad values are surfaced rather than silently zeroed.

---

## ANO-005: String-Based Date Sorting Produces Incorrect Order

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Column** | `PMT_DT` |

### Description
`LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` sorts `PMT_DT` as a string. Since dates are stored as `MM/DD/YYYY`, string comparison works by coincidence for the current data (all months are 10-12) but will fail for months 01-09 vs 10-12 (e.g., `'09/15/2025' > '11/15/2025'` evaluates to `false` in string sorting because `'0' < '1'`).

### Example Bad Records
Current data does not exhibit incorrect sorting (all payments are in Nov/Dec 2025), but the pattern is structurally broken for any data spanning months with different leading digits.

### Business Impact
- **Incorrect payment history display:** API consumers will see payments in wrong chronological order.
- **Business logic errors:** Any code that depends on "most recent payment first" (e.g., for delinquency calculation) will use stale data.

### Recommended Fix
- Parse `MM/DD/YYYY` strings to `LocalDate` before comparison, or sort in the service layer post-retrieval.
- Add validation that date strings conform to `MM/DD/YYYY` format before processing.

---

## ANO-006: Delinquency Days Inconsistent with Loan Status

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

### Description
Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). A loan with non-zero delinquency days should typically have a status reflecting the delinquency (e.g., `DFT` for default or at minimum a warning flag). The corresponding payment `PMT-2025110003` confirms the late pattern: received 17 days after the due date, with a $47.50 late fee.

### Example Bad Records

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| LN-2018-00089 | 15 | ACT | Should be flagged (e.g., DLQ or at minimum noted) |

### Business Impact
- **Regulatory non-compliance:** Loans reported as Active with delinquency days may violate reporting standards.
- **Risk underestimation:** Portfolio risk metrics will undercount delinquent loans.

### Recommended Fix
- Add cross-field validation: if `LN_DLQ_DAYS > 0`, status must not be `ACT` without an explicit override reason.
- Define delinquency thresholds (e.g., 30+ days = DLQ, 90+ days = DFT).

---

## ANO-007: NULL Middle Initial in Required-Adjacent Field

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_MID_INIT` |

### Description
Borrower `B-10005` (Robert Williams) has a NULL `BORR_MID_INIT`. While middle initials can legitimately be absent, the service layer's `toBorrowerDto()` uses a ternary that handles NULL by omitting the middle initial from the full name. However, null handling is inconsistent — no explicit validation is performed.

### Example Bad Records

| BORR_ID | BORR_FST_NM | BORR_MID_INIT | BORR_LST_NM |
|---------|-------------|---------------|-------------|
| B-10005 | Robert | NULL | Williams |

All other 4 borrowers have non-null middle initials.

### Business Impact
- **Display inconsistency:** Full name format varies (`"James R. Mitchell"` vs `"Robert Williams"`) depending on null state.
- **Search/match failures:** Name-matching logic that expects a middle initial will miss this borrower.

### Recommended Fix
- Treat null middle initial as valid but normalize display format.
- Add explicit null checks in all code paths that access this field.

---

## ANO-008: Denormalized Borrower Data Divergence Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM` (duplicated from `CDW_BORR_MSTR`) |

### Description
`CDW_LN_ACCT` duplicates borrower first name and last name from `CDW_BORR_MSTR`. Currently both copies are consistent, but without constraints, updates to `CDW_BORR_MSTR` (e.g., name change after marriage) will NOT propagate to `CDW_LN_ACCT`, creating divergent records.

### Example Bad Records
No divergence in current data, but the structural risk is present:
```
CDW_BORR_MSTR: B-10002 -> Sarah Chen
CDW_LN_ACCT:   LN-2020-00398 -> Sarah Chen  (currently matches)
-- After a name change in CDW_BORR_MSTR only, these would diverge
```

### Business Impact
- **Inconsistent API responses:** `toLoanSummary()` uses the loan account's copy of the name, while `toBorrowerDto()` uses the borrower master. A divergence produces different names for the same person across endpoints.

### Recommended Fix
- Always read borrower name from `CDW_BORR_MSTR` (canonical source), not from `CDW_LN_ACCT`.
- Add validation that denormalized fields match the master record.

---

## ANO-009: LTV Percent Calculation Discrepancy

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_LTV_PCT`, `LN_ORIG_AMT`, `PROP_APRS_VAL` |

### Description
The stored LTV percentage does not match the computed value (`LN_ORIG_AMT / PROP_APRS_VAL * 100`) for some loans. Discrepancies are small (0.1%) but indicate either rounding errors or stale recalculations.

### Example Bad Records

| LN_ACCT_NBR | LN_ORIG_AMT | PROP_APRS_VAL | Stored LTV | Computed LTV | Delta |
|-------------|-------------|---------------|-----------|-------------|-------|
| LN-2019-00142 | 285,000 | 345,000 | 82.5 | 82.61 | 0.11 |
| LN-2020-00398 | 420,000 | 615,000 | 68.2 | 68.29 | 0.09 |
| LN-2021-00567 | 525,000 | 721,000 | 72.8 | 72.82 | 0.02 |

### Business Impact
- **Risk miscalculation:** LTV is a key metric for PMI (Private Mortgage Insurance) requirements. A borrower at 80.1% vs 79.9% LTV determines whether PMI is required.

### Recommended Fix
- Recompute LTV from source values during ingestion rather than trusting the stored value.
- Add validation: `abs(stored_LTV - computed_LTV) < 0.5%`.

---

## ANO-010: Date Format Stored as VARCHAR — No Format Enforcement

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | All tables |
| **Affected Columns** | All date columns (`BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `PMT_DT`, etc.) |

### Description
All date values are stored as `VARCHAR(10)` strings with an expected format of `MM/DD/YYYY`. However, the schema has no CHECK constraint enforcing this format. Current seed data is consistent, but nothing prevents future inserts with formats like `YYYY-MM-DD`, `DD-MM-YYYY`, `2025/12/01`, or even non-date strings like `'N/A'` or `'TBD'`.

### Example Bad Records
No format violations in current data, but the schema permits:
```sql
INSERT INTO CDW_BORR_MSTR VALUES (..., 'not-a-date', ...);  -- Would succeed
```

### Business Impact
- **Parse failures at runtime:** `DateTimeFormatter.ofPattern("MM/dd/yyyy")` will throw `DateTimeParseException` for any non-conforming values.

### Recommended Fix
- Add date format validation at ingestion: verify string matches `MM/DD/YYYY` and parses to a valid date.
- Reject or quarantine records with unparseable date strings.

---

## ANO-011: VA Loan Product Has Zero Minimum Amount

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_LN_PROD` |
| **Affected Column** | `PROD_MIN_AMT` |

### Description
The VA30 loan product has `PROD_MIN_AMT = '0'`. While VA loans can have $0 down payment, a $0 minimum loan amount is unusual and may be a data entry error (intended to represent no minimum restriction vs. a literal zero-dollar loan).

### Example Bad Records

| PROD_CD | PROD_DESC_TXT | PROD_MIN_AMT |
|---------|---------------|-------------|
| VA30 | VA 30-Year Fixed | 0 |

All other products have minimum amounts of $25,000+.

### Business Impact
- **Edge case in validation:** Loan origination logic that checks `loanAmount >= minAmount` would allow $0 loans.
- **Parsing edge case:** The string `'0'` parses correctly to `BigDecimal.ZERO` but `parseLegacyAmount` should be tested with this edge case.

### Recommended Fix
- Confirm with business stakeholders whether $0 minimum is intentional for VA loans.
- Add a floor validation (e.g., minimum loan amount >= $1,000 for any product).

---

## Appendix: Anomaly Cross-Reference by Table

| Table | Anomaly IDs |
|-------|-------------|
| `CDW_BORR_MSTR` | ANO-004, ANO-007, ANO-010 |
| `CDW_LN_PROD` | ANO-004, ANO-010, ANO-011 |
| `CDW_LN_ACCT` | ANO-001, ANO-003, ANO-004, ANO-005, ANO-006, ANO-008, ANO-009, ANO-010 |
| `CDW_PMT_HIST` | ANO-002, ANO-003, ANO-004, ANO-005, ANO-010 |
