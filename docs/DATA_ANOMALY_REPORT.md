# Legacy Data Anomaly Report

This report documents data quality anomalies found in the legacy CDW (Corporate Data Warehouse) tables used by the loan-service application.

**Analysis scope:** `schema-legacy.sql`, `data-legacy.sql`, `LoanService.java`, repository layer, and `column_mappings.md`.

---

## Anomaly #1: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** For multiple payment records, the sum of component amounts (principal + interest + escrow + late fee) does not equal the stated total payment amount.

**Example Bad Records:**

| Payment ID | Total | Principal | Interest | Escrow | Late Fee | Component Sum | Discrepancy |
|-----------|-------|-----------|----------|--------|----------|---------------|-------------|
| `PMT-2025120001` | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | +47.50 |

**Business Impact:** Financial reporting and reconciliation produce incorrect totals. Downstream systems consuming payment data via the API receive internally inconsistent records. Audit and regulatory compliance are at risk if payments cannot be verified.

**Recommended Fix:** Add a validation check in the service layer that compares component sums to the total. Flag discrepancies and either reject the record or annotate the API response with a warning. Investigate whether escrow and late fees should be excluded from the total in certain payment types.

---

## Anomaly #2: SSN Last-4 Field Contains Phone Number Digits

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

**Description:** The `BORR_SSN_LST4` column, which should contain the last 4 digits of the borrower's SSN, instead contains the last 4 digits of the borrower's phone number.

**Example Bad Records:**

| Loan Account | BORR_SSN_LST4 | Borrower Phone | Phone Last 4 | Match? |
|-------------|---------------|----------------|-------------|--------|
| `LN-2019-00142` | 0142 | 217-555-0142 | 0142 | Phone matches, not SSN |
| `LN-2020-00398` | 0198 | 503-555-0198 | 0198 | Phone matches, not SSN |
| `LN-2018-00089` | 0167 | 512-555-0167 | 0167 | Phone matches, not SSN |
| `LN-2021-00567` | 0134 | 303-555-0134 | 0134 | Phone matches, not SSN |
| `LN-2017-00034` | 0156 | 602-555-0156 | 0156 | Phone matches, not SSN |

**Business Impact:** This is a PII/compliance violation. Any system using this field for identity verification (e.g., customer support SSN verification, fraud detection) is operating on incorrect data. This affects all 5 loan accounts (100% of records).

**Recommended Fix:** Flag this field as unreliable. Do not use `BORR_SSN_LST4` for identity verification during or after migration. The `column_mappings.md` already marks this as `*(dropped)*` in the modern schema, which is correct. Add a validation warning when this field is accessed.

---

## Anomaly #3: Numeric Amounts Stored as Comma-Formatted Strings

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** All monetary values are stored as VARCHAR with embedded commas (e.g., `'285,000'`, `'1,487.02'`). The `parseLegacyAmount()` method strips commas and converts to `BigDecimal`, but has no error handling for unexpected formats (dollar signs, spaces, currency symbols, empty strings with whitespace).

**Example Data:**
```
BORR_ANN_INCM: '92,500', '125,000', '78,000', '145,000', '65,000'
LN_ORIG_AMT:   '285,000', '420,000', '195,000', '525,000', '165,000'
LN_CURR_BAL:   '271,432.56', '312,876.43', '178,234.12', '498,123.78', '142,567.90'
```

**Business Impact:** Any malformed value causes an uncaught `NumberFormatException` in `LoanService.parseLegacyAmount()`, which propagates as an HTTP 500 error. A single bad record prevents the entire loan list endpoint from returning data since `getAllLoans()` streams all records through this parser.

**Recommended Fix:** Wrap parsing in try-catch, log the malformed value, and return a safe default or throw a domain-specific exception. Add input sanitization that strips dollar signs, whitespace, and other non-numeric characters before parsing.

---

## Anomaly #4: Credit Score Stored as String with No Validation

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_CRDT_SCR` |

**Description:** Credit scores are stored as VARCHAR(5) and parsed to `Integer` via `Integer.parseInt()` without validation. No range check ensures the value is within the valid FICO range (300-850). Non-numeric values would cause `NumberFormatException`.

**Example Data:**
```
B-10001: '745', B-10002: '780', B-10003: '692', B-10004: '810', B-10005: '658'
```

**Business Impact:** A non-numeric credit score (e.g., `'N/A'`, `'---'`, or `''`) crashes the borrower endpoint. Even numeric but out-of-range values (e.g., `'0'`, `'999'`) would silently pass through and could produce incorrect risk assessments.

**Recommended Fix:** Add range validation (300-850) and graceful error handling. Return `null` for unparseable scores and log a warning.

---

## Anomaly #5: Dates Stored as MM/DD/YYYY Strings — No Validation, Incorrect Sorting

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT` |

**Description:** All date fields are VARCHAR(10) storing dates in `MM/DD/YYYY` format. The service layer passes these strings through to DTOs without parsing or validation. The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts on a VARCHAR column, producing lexicographic ordering (not chronological).

**Example:** Lexicographic sort of `'01/15/2026'` vs `'12/15/2025'` would place January 2026 before December 2025 because `'0' < '1'`.

**Business Impact:** Payment history is returned in incorrect order for cross-year or cross-month queries. Invalid dates (e.g., `'02/30/2025'`, `'13/01/2025'`) would silently pass through. The `column_mappings.md` specifies parsing to `DATE`/`TIMESTAMP` during migration, but the current service performs no validation.

**Recommended Fix:** Parse dates to `LocalDate` in the service layer using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Catch `DateTimeParseException` for malformed dates. Sort payments in Java after retrieval if database-level sorting is unreliable.

---

## Anomaly #6: Active Loan Status with Non-Zero Delinquency Days

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_STAT_CD`, `LN_DLQ_DAYS` |

**Description:** Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). A loan 15 days past due should have a delinquency-related status.

**Example Bad Record:**
```
LN-2018-00089: status='ACT', delinquency_days='15'
Payment PMT-2025110003: due 11/01/2025, received 11/18/2025 (17 days late, $47.50 late fee)
```

**Business Impact:** Risk reporting and collections workflows that filter by status code miss delinquent loans. The API reports this loan as "Active" despite being past due, masking credit risk.

**Recommended Fix:** Add cross-field validation: if `delinquency_days > 0`, status should not be `ACT`. Flag inconsistent records in the API response or apply a corrective status mapping.

---

## Anomaly #7: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema defines no foreign key constraints. `CDW_LN_ACCT.BORR_ID` is not constrained to `CDW_BORR_MSTR.BORR_ID`, `CDW_LN_ACCT.PROD_CD` is not constrained to `CDW_LN_PROD.PROD_CD`, and `CDW_PMT_HIST.LN_ACCT_NBR` is not constrained to `CDW_LN_ACCT.LN_ACCT_NBR`.

**Business Impact:** Orphaned records can exist silently. In `LoanService.getAllLoans()`, `products.get(acct.getProductCode())` returns `null` for orphaned product codes, which is handled (falls back to code string), but `getLoanById()` calls `loanProductRepository.findById()` which also returns `null`. For borrower references, `getBorrowerById()` fetches loans by borrower ID — if the borrower ID in the loan doesn't match any borrower, the loan simply wouldn't appear in the borrower's loan list.

**Recommended Fix:** Add referential integrity checks in the service layer. Validate that referenced entities exist before building DTOs. Log warnings for orphaned references.

---

## Anomaly #8: Denormalized Borrower Data in Loan Accounts — Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** `CDW_LN_ACCT` contains denormalized copies of borrower first name, last name, and SSN last 4 from `CDW_BORR_MSTR`. These can drift if the borrower master is updated without updating all loan records.

**Current Data Status:** Currently, names are consistent across tables. However, there is no constraint or trigger to enforce synchronization.

**Business Impact:** `LoanService.toLoanSummary()` uses the denormalized `borrowerFirstName` and `borrowerLastName` from the loan account (not from the borrower master), so name changes in the borrower master would not be reflected in loan summaries.

**Recommended Fix:** In the service layer, prefer the borrower master table as the source of truth for borrower names. Cross-reference and validate denormalized fields against the master during migration.

---

## Anomaly #9: Null Middle Initial

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_MID_INIT` |

**Description:** Borrower `B-10005` (Robert Williams) has a NULL `BORR_MID_INIT`. While the service handles this in `toBorrowerDto()`, any downstream code that concatenates this field without a null check would produce `"Robert null Williams"`.

**Example Bad Record:**
```sql
INSERT INTO CDW_BORR_MSTR VALUES ('B-10005', 'Robert', 'Williams', NULL, ...)
```

**Business Impact:** Low — currently handled in `LoanService.toBorrowerDto()`. Risk is in future code that accesses this field without null checking.

**Recommended Fix:** Ensure all name-formatting code handles null middle initials. Consider defaulting to empty string at the validation layer.

---

## Anomaly #10: Null Address Line 2

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_ADDR_LN2` |

**Description:** Borrowers `B-10002`, `B-10003`, and `B-10005` have NULL `BORR_ADDR_LN2`. This is a legitimate data scenario (not all addresses have a second line), but any string concatenation without null checks would produce incorrect output.

**Business Impact:** Low — address line 2 is optional and NULLs are expected. Risk is in migration or formatting code that doesn't handle NULLs.

**Recommended Fix:** Default NULL address line 2 to empty string during validation/migration.

---

## Summary

| Severity | Count | Anomaly IDs |
|----------|-------|-------------|
| Critical | 2 | #1, #2 |
| High | 4 | #3, #4, #5, #6 |
| Medium | 2 | #7, #8 |
| Low | 2 | #9, #10 |

**Total anomalies identified:** 10
