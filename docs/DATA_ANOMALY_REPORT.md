# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## ANM-001: NULL Middle Initial in Borrower Master

| Field | Value |
|---|---|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_MID_INIT` |
| **Example Bad Records** | `B-10005` (Robert Williams) — `BORR_MID_INIT` is `NULL` |
| **Business Impact** | Minor display inconsistency when constructing full borrower names. The service layer concatenates first + middle + last; a null middle initial produces an extra space or "null" literal in the name depending on handling. |
| **Recommended Fix** | Default null middle initials to an empty string at ingestion. Guard string concatenation in `LoanService.toBorrowerDto()` to handle null gracefully (already partially done with a ternary check). |

---

## ANM-002: All Financial Amounts Stored as Comma-Formatted Strings

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Example Bad Records** | `B-10001`: `BORR_ANN_INCM = '92,500'`; `LN-2019-00142`: `LN_ORIG_AMT = '285,000'`, `LN_CURR_BAL = '271,432.56'` |
| **Business Impact** | Any code path that attempts `new BigDecimal("285,000")` without first stripping commas will throw `NumberFormatException`, crashing the API endpoint. Financial calculations (LTV ratio, amortization) are impossible without successful parsing. If a malformed or unexpected character enters these fields (e.g., `$285,000` or `285 000`), the current `replace(",", "")` approach will still fail. |
| **Recommended Fix** | Implement robust `parseLegacyAmount()` that strips all non-numeric characters except decimal points and minus signs, validates the result is a valid number, and logs a warning + returns a sentinel/default on failure rather than throwing. |

---

## ANM-003: All Dates Stored as VARCHAR in MM/DD/YYYY Format

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT` |
| **Example Bad Records** | `B-10001`: `BORR_DOB_DT = '03/15/1978'`; `LN-2019-00142`: `LN_ORIG_DT = '02/15/2019'` |
| **Business Impact** | Dates are passed through to the API as raw strings (e.g., `originationDate` in `LoanSummaryDto`) — no parsing to `LocalDate` occurs. This prevents date-range queries, sorting by date, age calculations, and term validation. If a date arrives in an unexpected format (e.g., `YYYY-MM-DD` or `15/03/1978`), there is no detection or error — it would be silently served as-is, misleading consumers. |
| **Recommended Fix** | Parse all date strings to `LocalDate` using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` at ingestion time, with fallback patterns and error logging for unparseable values. Store/return ISO-8601 format in DTOs. |

---

## ANM-004: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` → `CDW_BORR_MSTR`, `CDW_LN_ACCT` → `CDW_LN_PROD`, `CDW_PMT_HIST` → `CDW_LN_ACCT` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |
| **Example Bad Records** | Current seed data is referentially consistent, but the schema has zero `FOREIGN KEY` constraints. Any insert with a non-existent `BORR_ID`, `PROD_CD`, or `LN_ACCT_NBR` would succeed silently. |
| **Business Impact** | Orphaned loan accounts (referencing non-existent borrowers) will cause `NullPointerException` in `LoanService.getBorrowerById()` when it tries to look up borrower details. Orphaned payments referencing non-existent loans will return dangling data. Product lookups returning `null` are partially handled (`product != null ? ...`) but would produce degraded API responses. |
| **Recommended Fix** | Add referential integrity validation at ingestion time: verify that every `BORR_ID` in `CDW_LN_ACCT` exists in `CDW_BORR_MSTR`, every `PROD_CD` exists in `CDW_LN_PROD`, and every `LN_ACCT_NBR` in `CDW_PMT_HIST` exists in `CDW_LN_ACCT`. Log and quarantine orphaned records. |

---

## ANM-005: Credit Score Stored as VARCHAR — Parsing Risk

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_CRDT_SCR` |
| **Example Bad Records** | `B-10001`: `BORR_CRDT_SCR = '745'`; `B-10005`: `BORR_CRDT_SCR = '658'` |
| **Business Impact** | `LoanService.parseLegacyInteger()` calls `Integer.parseInt()` directly. A non-numeric value (e.g., `'N/A'`, `'---'`, `''`) would throw `NumberFormatException`, crashing the borrower API endpoint. Credit scores outside the valid range (300-850) would pass through unchecked, producing misleading API data used for risk assessment. |
| **Recommended Fix** | Validate that parsed credit score is within the 300-850 range. Return null with a warning log for unparseable or out-of-range values. |

---

## ANM-006: Abbreviated Status Codes Without Validation

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_STAT_CD`, `LN_STAT_CD`, `PROD_STAT_CD`, `PMT_STAT_CD` |
| **Example Bad Records** | All current records use `'ACT'` for borrower/loan/product status, `'PST'` or `'REG'` for payment status/type. These are valid, but the switch expressions in `LoanService` fall through to `default -> code`, silently passing through any unknown code. |
| **Business Impact** | An unrecognized status code (e.g., `'SUS'` for suspended, `'XYZ'` from a data entry error) would be passed raw to the API response, confusing downstream consumers. No alerting would occur. The business rules around status-dependent behavior (e.g., active loans vs. defaulted loans) cannot be reliably enforced. |
| **Recommended Fix** | Validate status codes against a known allowlist at ingestion. Log warnings for unknown codes. Return a canonical "Unknown" status with the original code preserved for investigation. |

---

## ANM-007: Denormalized Borrower Data in Loan Accounts — Drift Risk

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |
| **Example Bad Records** | `LN-2019-00142` has `BORR_FST_NM='James'`, `BORR_LST_NM='Mitchell'` — matches `CDW_BORR_MSTR.B-10001`. Currently consistent, but no mechanism prevents these from drifting apart. |
| **Business Impact** | If borrower data is updated in `CDW_BORR_MSTR` but not in `CDW_LN_ACCT`, the API would return different names depending on whether you query the loan endpoint (uses denormalized name from `CDW_LN_ACCT`) or the borrower endpoint (uses `CDW_BORR_MSTR`). This would confuse consumers and potentially cause compliance issues in official correspondence. |
| **Recommended Fix** | At ingestion, cross-reference denormalized borrower fields in `CDW_LN_ACCT` against the canonical `CDW_BORR_MSTR` record. Log any mismatches as warnings. In the modern schema, eliminate denormalization and use foreign key joins. |

---

## ANM-008: Numeric Delinquency Days Stored as VARCHAR

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `LN_DLQ_DAYS` |
| **Example Bad Records** | `LN-2018-00089`: `LN_DLQ_DAYS = '15'`; all others: `LN_DLQ_DAYS = '0'` |
| **Business Impact** | Currently not parsed or exposed in the DTO, but any future logic using delinquency days for risk assessment would need to parse this string. A non-numeric value (e.g., `'N/A'`) would cause `NumberFormatException`. Negative values or unreasonable values (e.g., `'9999'`) would go undetected. |
| **Recommended Fix** | Parse to integer with range validation (0-999) at ingestion. Log and default to 0 for unparseable values. |

---

## ANM-009: LTV Percent Stored as VARCHAR Without Validation

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `LN_LTV_PCT` |
| **Example Bad Records** | `LN-2019-00142`: `LN_LTV_PCT = '82.5'`; `LN-2020-00398`: `LN_LTV_PCT = '68.2'` |
| **Business Impact** | LTV is a key risk metric. Stored as a string, it cannot be used for range-based queries or threshold alerts. Values outside the valid range (0-200%) or non-numeric values would pass through silently. An LTV > 100% is unusual and may indicate negative equity — this should be flagged, not silently accepted. |
| **Recommended Fix** | Parse to `BigDecimal`, validate range 0-200, flag values > 100 as warnings. |

---

## ANM-010: Payment Amount Component Mismatch Risk

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Example Bad Records** | `PMT-2025120001`: total=`1,487.02`, principal=`456.78`, interest=`1,074.69`, escrow=`355.55`, late_fee=`0.00`. Sum of components = 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** which does **NOT** equal total of **1,487.02**. Difference: **400.00**. This pattern repeats across multiple payment records. |
| **Business Impact** | Financial reconciliation is impossible. The payment breakdown does not add up to the total, meaning either the total is wrong, a component is wrong, or there is a missing component not captured. This directly impacts financial reporting, tax calculations, and regulatory compliance. Auditors would flag this as a material discrepancy. |
| **Recommended Fix** | Validate at ingestion that `principal + interest + escrow + late_fee == total_amount` (within a small rounding tolerance, e.g., $0.01). Log all mismatches with the exact discrepancy. Quarantine records that exceed tolerance for manual review. |

---

## ANM-011: Loan Term Stored as VARCHAR

| Field | Value |
|---|---|
| **Severity** | Low |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_LN_PROD` |
| **Affected Columns** | `LN_TERM_MOS`, `PROD_TERM_MOS` |
| **Example Bad Records** | `LN-2019-00142`: `LN_TERM_MOS = '360'`; `FXD30` product: `PROD_TERM_MOS = '360'` |
| **Business Impact** | Term values are consistent in current data but stored as strings. Non-numeric values would cause parsing failures. The term on the loan account should match the term on the product; no validation currently enforces this. |
| **Recommended Fix** | Parse to integer at ingestion. Cross-validate loan term against product term. |

---

## ANM-012: Interest Rate Stored as VARCHAR

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `LN_INT_RT` |
| **Example Bad Records** | `LN-2019-00142`: `LN_INT_RT = '4.750'`; `LN-2018-00089`: `LN_INT_RT = '5.250'` |
| **Business Impact** | Parsed via `parseLegacyDecimal()` which trims whitespace but does not validate range. A rate of `'99.9'` or `'-1.5'` or `'N/A'` would either pass through silently or crash. Interest rates should be in range 0-30% for residential mortgages. |
| **Recommended Fix** | Validate parsed rate is within a reasonable range (0.0 - 30.0). Flag outliers. |

---

## Summary

| Severity | Count | Anomaly IDs |
|---|---|---|
| **Critical** | 2 | ANM-002, ANM-003 |
| **High** | 3 | ANM-004, ANM-005, ANM-010 |
| **Medium** | 4 | ANM-006, ANM-007, ANM-008, ANM-009, ANM-012 |
| **Low** | 2 | ANM-001, ANM-011 |
| **Total** | **12** | |
