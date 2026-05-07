# Legacy CDW Data Anomaly Report

This report documents data quality anomalies found in the legacy Corporate Data Warehouse (CDW) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`). Each anomaly is classified by severity and includes affected records, business impact, and recommended fixes.

---

## Anomaly #1: Payment Component Totals Do Not Match Sum of Parts

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Description

The `PMT_AMT` (total payment) field does not equal the sum of its component fields (`PMT_PRIN_AMT` + `PMT_INT_AMT` + `PMT_ESCROW_AMT` + `PMT_LATE_FEE`) for multiple payment records. This indicates either incorrect data entry or a misunderstanding of the component breakdown semantics.

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT (Total) | PRIN + INT + ESCROW + LATE_FEE (Computed Sum) | Discrepancy |
|---|---|---|---|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | **+$400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | **+$400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | **+$47.50** |

Records that pass validation:

| PMT_SEQ_NBR | PMT_AMT | Computed Sum | Match |
|---|---|---|---|
| `PMT-2025120002` | 2,924.18 | 2,924.18 | ✓ |
| `PMT-2025110002` | 2,924.18 | 2,924.18 | ✓ |
| `PMT-2025120003` | 1,077.05 | 1,077.05 | ✓ |
| `PMT-2025120004` | 2,468.35 | 2,468.35 | ✓ |
| `PMT-2025110004` | 2,468.35 | 2,468.35 | ✓ |
| `PMT-2025120005` | 811.61 | 811.61 | ✓ |
| `PMT-2025110005` | 811.61 | 811.61 | ✓ |

### Business Impact

- **Financial reporting errors**: Downstream systems consuming payment data will report incorrect principal/interest/escrow allocations.
- **Regulatory compliance risk**: Loan servicing is subject to TILA/RESPA disclosure requirements; misallocated payment components produce incorrect borrower statements.
- **API consumers receive contradictory data**: The `PaymentDto` exposes both `totalAmount` and individual components — clients performing their own validation will detect the inconsistency.

### Recommended Fix

- Validate at ingestion: reject or flag payments where `total ≠ principal + interest + escrow + lateFee`.
- For records with a mismatch, recompute the total from components (treat components as the source of truth) and log a warning.

---

## Anomaly #2: SSN Last-4 Field Contains Phone Number Digits

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

### Description

The `BORR_SSN_LST4` column in `CDW_LN_ACCT` is documented as storing the last 4 digits of the borrower's Social Security Number. However, every record contains the last 4 digits of the borrower's **phone number** instead.

### Example Bad Records

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | Borrower Phone (CDW_BORR_MSTR) | Phone Last 4 |
|---|---|---|---|---|
| `LN-2019-00142` | B-10001 | `0142` | 217-555-**0142** | `0142` ← match |
| `LN-2020-00398` | B-10002 | `0198` | 503-555-**0198** | `0198` ← match |
| `LN-2018-00089` | B-10003 | `0167` | 512-555-**0167** | `0167` ← match |
| `LN-2021-00567` | B-10004 | `0134` | 303-555-**0134** | `0134` ← match |
| `LN-2017-00034` | B-10005 | `0156` | 602-555-**0156** | `0156` ← match |

The actual SSN data is stored encrypted in `CDW_BORR_MSTR.BORR_SSN_ENCR` (values like `ENC_XXX_001`), making it impossible to derive the correct last 4 from the available data.

### Business Impact

- **Identity verification failures**: If any downstream process uses `BORR_SSN_LST4` for borrower identity verification (e.g., phone-based account access), it would accept phone digits as SSN confirmation — a security and compliance issue.
- **PII data corruption**: This field is labeled as containing SSN data but actually contains phone-derived data. Any PII audit or data masking process would treat these as SSN fragments when they are not.
- **Migration data integrity**: The `column_mappings.md` marks this field as "dropped" during migration; however, if any interim process relies on it, results will be incorrect.

### Recommended Fix

- Flag `BORR_SSN_LST4` as unreliable at ingestion; do not use for identity verification.
- Log a warning when this field is accessed.
- During migration, drop this field (as already planned in column_mappings.md) rather than migrating corrupt data.

---

## Anomaly #3: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Description

The legacy schema defines no foreign key constraints between any tables. The relationships `CDW_LN_ACCT.BORR_ID → CDW_BORR_MSTR.BORR_ID`, `CDW_LN_ACCT.PROD_CD → CDW_LN_PROD.PROD_CD`, and `CDW_PMT_HIST.LN_ACCT_NBR → CDW_LN_ACCT.LN_ACCT_NBR` are implied but unenforced.

While the current seed data has valid references, there is no protection against orphaned records being inserted.

### Example Scenario

A loan account could reference `BORR_ID = 'B-99999'` (non-existent borrower) or `PROD_CD = 'INVALID'` (non-existent product), and the database would accept it without error.

### Business Impact

- **NullPointerException in service layer**: `LoanService.getAllLoans()` calls `products.get(acct.getProductCode())` — if the product code doesn't exist in the map, it returns `null`, which is passed to `toLoanSummary()`. The null-safe check at line 107 prevents an NPE for product, but there's no similar protection for missing borrowers.
- **Silent data corruption**: Orphaned records would produce incomplete or misleading API responses (e.g., a loan with no borrower info).
- **Migration failures**: The modern schema uses proper FK constraints; orphaned legacy records will cause constraint violations during migration.

### Recommended Fix

- Validate referential integrity at ingestion: verify that every `BORR_ID` in loan accounts exists in the borrower table, every `PROD_CD` exists in products, and every `LN_ACCT_NBR` in payments exists in loan accounts.
- Reject or quarantine records that fail FK validation.

---

## Anomaly #4: All-VARCHAR Schema — Numeric Strings with Comma Formatting

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | All amount, rate, score, and integer columns |

### Description

Every column in the legacy schema is `VARCHAR`, including fields that represent numeric values. Monetary amounts include embedded comma formatting (e.g., `'285,000'`, `'1,487.02'`), and integer fields like credit scores and term months are stored as strings.

### Example Bad Records

| Table | Column | Value | Expected Type |
|---|---|---|---|
| `CDW_BORR_MSTR` | `BORR_CRDT_SCR` | `'745'` | INTEGER |
| `CDW_BORR_MSTR` | `BORR_ANN_INCM` | `'92,500'` | DECIMAL |
| `CDW_LN_ACCT` | `LN_ORIG_AMT` | `'285,000'` | DECIMAL |
| `CDW_LN_ACCT` | `LN_CURR_BAL` | `'271,432.56'` | DECIMAL |
| `CDW_LN_ACCT` | `LN_INT_RT` | `'4.750'` | DECIMAL(5,3) |
| `CDW_LN_ACCT` | `LN_DLQ_DAYS` | `'15'` | INTEGER |
| `CDW_LN_PROD` | `PROD_TERM_MOS` | `'360'` | INTEGER |
| `CDW_LN_PROD` | `PROD_MIN_AMT` | `'50,000'` | DECIMAL |
| `CDW_PMT_HIST` | `PMT_AMT` | `'1,487.02'` | DECIMAL |

### Business Impact

- **NumberFormatException risk**: `parseLegacyAmount()` strips commas, but malformed values (e.g., `'N/A'`, `'$285,000'`, `'285,,000'`) would throw an uncaught `NumberFormatException`, crashing the API endpoint.
- **parseLegacyInteger()` for credit scores throws `NumberFormatException`** on non-numeric values with no try-catch.
- **No range validation**: A credit score of `'9999'` or a negative amount like `'-500'` would be accepted without question.
- **Precision loss risk**: String-to-BigDecimal conversion could introduce floating point issues if dollar signs or other characters sneak in.

### Recommended Fix

- Wrap all parsing methods in try-catch blocks with logging and fallback defaults.
- Add range validation (e.g., credit score 300–850, amounts ≥ 0, interest rates 0–100).
- Reject records with unparseable numeric fields.

---

## Anomaly #5: String-Based Date Fields Break Sort Ordering

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | All date columns (`*_DT` suffix) |

### Description

All date fields are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. This format is not lexicographically sortable — string sorting produces incorrect chronological ordering.

### Example

Alphabetical sort of `MM/DD/YYYY` dates:
```
02/01/2025  ← should be earliest
11/01/2025
12/01/2025
12/15/2025  ← should be latest
```

Alphabetical: `02/01/2025` < `11/01/2025` < `12/01/2025` < `12/15/2025` (happens to be correct for these samples)

But consider: `02/01/2025` vs `11/01/2024`:
- Alphabetically: `02/01/2025` < `11/01/2024` (WRONG — 2025 should come after 2024)

### Business Impact

- **Incorrect payment history ordering**: `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` generates a JPA `ORDER BY PMT_DT DESC` clause, which sorts as a string. For cross-month or cross-year ranges, payments will appear in wrong order.
- **Date validation impossible**: No way to enforce that `LN_ORIG_DT` < `LN_MAT_DT` or that `PMT_DT` falls within the loan's term.
- **Format inconsistency risk**: Nothing prevents a date like `2025-03-15` (ISO format) or `03-15-2025` from being inserted, which would silently break all date parsing.

### Recommended Fix

- Parse date strings to `LocalDate` at ingestion time and validate format.
- For sorting, convert to proper date types before returning results.
- Reject records with unparseable or illogical dates (e.g., maturity before origination).

---

## Anomaly #6: Delinquent Loan with Active Status

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

### Description

Loan `LN-2018-00089` (borrower Michael Torres) has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). A loan that is 15+ days delinquent should typically have a distinct status indicator (e.g., `DLQ` for Delinquent) rather than appearing as fully active.

### Example Bad Records

| LN_ACCT_NBR | BORR_ID | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|---|---|---|---|---|
| `LN-2018-00089` | B-10003 | `15` | `ACT` | Should be `DLQ` or at minimum flagged |

Supporting evidence: Payment `PMT-2025110003` for this loan shows:
- `PMT_RECV_DT = '11/18/2025'` (received 17 days after the `PMT_DT = '11/01/2025'` due date)
- `PMT_LATE_FEE = '47.50'` (late fee was charged)

### Business Impact

- **Incorrect risk reporting**: Active loans with delinquency are not flagged in status-based queries, understating portfolio delinquency rates.
- **The `expandStatusCode()` method in LoanService has no mapping for delinquent status**, so even if a `DLQ` code existed, it would fall through to the default case and return the raw code.

### Recommended Fix

- Cross-validate `LN_DLQ_DAYS` and `LN_STAT_CD` at ingestion — flag when delinquency days > 0 but status is `ACT`.
- Add `DLQ` (Delinquent) to the status code expansion map.

---

## Anomaly #7: Denormalized Borrower Data Drift Risk

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM` |

### Description

`CDW_LN_ACCT` contains denormalized copies of borrower name fields (`BORR_FST_NM`, `BORR_LST_NM`). In the current seed data, these match the corresponding `CDW_BORR_MSTR` records. However, there is no mechanism to keep them in sync — if a borrower's name is updated in the master table, the loan account table retains the old values.

### Example

| LN_ACCT_NBR | CDW_LN_ACCT.BORR_FST_NM | CDW_BORR_MSTR.BORR_FST_NM | Match |
|---|---|---|---|
| `LN-2019-00142` | James | James | ✓ |
| `LN-2020-00398` | Sarah | Sarah | ✓ |

Currently consistent, but one update to `CDW_BORR_MSTR` without a corresponding update to `CDW_LN_ACCT` would create a mismatch.

### Business Impact

- **Conflicting borrower names across endpoints**: `GET /api/loans` uses `CDW_LN_ACCT.BORR_FST_NM` (via `toLoanSummary`), while `GET /api/borrowers` uses `CDW_BORR_MSTR.BORR_FST_NM` (via `toBorrowerDto`). A name change in only one table would produce different names in different API responses.
- **Legal/compliance issues**: Loan documents must reflect the correct borrower name.

### Recommended Fix

- At ingestion, cross-validate denormalized name fields against the borrower master table.
- Log warnings when mismatches are detected.
- During migration, drop the denormalized fields (as planned in column_mappings.md).

---

## Anomaly #8: No NOT NULL Constraints on Required Business Fields

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_ENCR`, `LN_ORIG_AMT`, `LN_STAT_CD`, etc. |

### Description

The schema defines no `NOT NULL` constraints on any column except the primary keys. Business-critical fields like borrower name, SSN, loan amounts, and status codes can all be NULL.

### Example Scenario

A borrower record with `BORR_FST_NM = NULL` and `BORR_LST_NM = NULL` would be accepted. The `toBorrowerDto()` method in `LoanService` would produce `fullName = "null null"` (Java string concatenation of null values), which would be returned in the API response.

### Business Impact

- **Garbled API responses**: Null first/last names produce `"null R. null"` style strings in API output.
- **NPE in string operations**: `parseLegacyAmount(null)` is null-safe (returns `BigDecimal.ZERO`), but `expandStatusCode(null)` returns `"Unknown"` which may not be a valid status for downstream consumers.
- **Silent data loss**: Records with null critical fields provide no useful information but are still counted in queries.

### Recommended Fix

- Validate required fields at ingestion: reject records missing `firstName`, `lastName`, `loanAccountNumber`, `originalAmount`, `statusCode`, etc.
- Use sensible defaults only for truly optional fields.

---

## Anomaly #9: Payment Late Fee Included Inconsistently in Total

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_LATE_FEE` |

### Description

The relationship between `PMT_AMT` and `PMT_LATE_FEE` is inconsistent. In some records, the late fee appears to be excluded from the total; in others, it is unclear. This is a sub-pattern of Anomaly #1 but warrants separate attention because it suggests an ambiguous business rule.

### Example

| PMT_SEQ_NBR | PMT_AMT | Components (no late fee) | Late Fee | Sum w/ Late Fee | Sum w/o Late Fee |
|---|---|---|---|---|---|
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 = 1,077.05 | 47.50 | 1,124.55 | 1,077.05 |

For `PMT-2025110003`, `PMT_AMT` equals the sum **without** late fee — suggesting late fees are tracked separately. But this contradicts `PMT-2025120001` where neither interpretation produces a match.

### Business Impact

- **Ambiguous semantics**: API consumers cannot determine whether `totalAmount` includes or excludes late fees.
- **Inconsistent financial calculations**: Reconciliation processes that assume a consistent formula will fail.

### Recommended Fix

- Define and enforce a clear business rule: `total = principal + interest + escrow` (late fee separate) OR `total = principal + interest + escrow + lateFee`.
- Validate the chosen formula at ingestion and flag violations.

---

## Summary Table

| # | Anomaly | Severity | Table(s) | Impact |
|---|---------|----------|----------|--------|
| 1 | Payment component totals mismatch | **Critical** | CDW_PMT_HIST | Financial reporting errors, regulatory risk |
| 2 | SSN last-4 contains phone digits | **Critical** | CDW_LN_ACCT | PII corruption, identity verification failure |
| 3 | No foreign key constraints | **High** | CDW_LN_ACCT, CDW_PMT_HIST | Orphaned records, NPE, migration failures |
| 4 | All-VARCHAR numeric strings | **High** | All | NumberFormatException, no range validation |
| 5 | String dates break sort ordering | **High** | All | Incorrect chronological ordering in API |
| 6 | Delinquent loan with active status | **Medium** | CDW_LN_ACCT | Understated delinquency reporting |
| 7 | Denormalized borrower data drift | **Medium** | CDW_LN_ACCT | Conflicting names across endpoints |
| 8 | No NOT NULL on required fields | **Medium** | All | Garbled API responses, silent data loss |
| 9 | Late fee inclusion ambiguity | **Medium** | CDW_PMT_HIST | Ambiguous financial semantics |
