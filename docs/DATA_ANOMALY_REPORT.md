# Legacy CDW Data Anomaly Report

> **Generated:** 2026-05-07
> **Source:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`
> **Scope:** All four legacy CDW tables (`CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`)

---

## ANM-001: All Numeric and Date Fields Stored as VARCHAR (Loose Typing)

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | All four CDW tables |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_TERM_MOS`, `LN_PMT_AMT`, `LN_DLQ_DAYS`, `LN_ESCROW_BAL`, `LN_LTV_PCT`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`, all date columns |
| **Example Bad Records** | `BORR_CRDT_SCR = '745'` (should be INTEGER), `LN_ORIG_AMT = '285,000'` (should be DECIMAL), `BORR_DOB_DT = '03/15/1978'` (should be DATE) |
| **Business Impact** | Every numeric comparison, aggregation, and sort operates on string values. A credit score of `'80'` would sort above `'745'` lexicographically. Financial amounts with embedded commas (`'92,500'`) will throw `NumberFormatException` if parsed without stripping commas first. Date strings cannot be compared chronologically without parsing. |
| **Recommended Fix** | Implement type-coercion validators in the service layer that strip commas, parse amounts to `BigDecimal`, parse integers, and convert `MM/DD/YYYY` strings to `LocalDate` — with try/catch and fallback defaults for malformed values. |

---

## ANM-002: Nullable Required Fields — No NOT NULL Constraints

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_ENCR`, `BORR_DOB_DT`, `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `BORR_EMAIL_ADDR`, `BORR_STAT_CD`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_STAT_CD`, `BORR_ID` (in CDW_LN_ACCT), `PMT_AMT`, `PMT_STAT_CD` |
| **Example Bad Records** | Borrower B-10005 has `BORR_MID_INIT = NULL`. The schema allows `BORR_FST_NM`, `BORR_LST_NM`, and every other column besides the PK to be NULL. |
| **Business Impact** | A borrower with a NULL last name would cause `toBorrowerDto()` to produce `"James null"` in the `fullName` field. A NULL `LN_STAT_CD` causes `expandStatusCode()` to return `"Unknown"`, masking the loan's true status. A NULL `LN_ORIG_AMT` silently becomes `BigDecimal.ZERO`, making the loan appear as a \$0 loan in API responses. |
| **Recommended Fix** | Add NOT NULL constraints to business-critical columns in the modern schema. In the service layer, validate that required fields are non-null before processing and reject or flag records that violate these constraints. |

---

## ANM-003: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Tables** | `CDW_LN_ACCT` (references `CDW_BORR_MSTR.BORR_ID`), `CDW_LN_ACCT` (references `CDW_LN_PROD.PROD_CD`), `CDW_PMT_HIST` (references `CDW_LN_ACCT.LN_ACCT_NBR`) |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |
| **Example Bad Records** | The schema explicitly states "No foreign key constraints." Any `BORR_ID` value in `CDW_LN_ACCT` could reference a nonexistent borrower. Any `PROD_CD` could reference a nonexistent product. Any `LN_ACCT_NBR` in `CDW_PMT_HIST` could reference a nonexistent loan. |
| **Business Impact** | In `LoanService.getAllLoans()`, `products.get(acct.getProductCode())` returns `null` for an orphaned product code. This is partially handled (falls back to raw code), but `getBorrowerById()` would fail with a `RuntimeException` if the borrower exists but their loan references a deleted product. Orphaned payments would appear in query results but link to nonexistent loans. |
| **Recommended Fix** | Validate referential integrity at ingestion time: verify that every `BORR_ID` in loan accounts exists in the borrower table, every `PROD_CD` exists in the product table, and every `LN_ACCT_NBR` in payments exists in the loan account table. Log and quarantine orphaned records. |

---

## ANM-004: Date Format Inconsistency Risk — MM/DD/YYYY Stored as Strings

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Tables** | All four CDW tables |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT` |
| **Example Bad Records** | Current data uses `MM/DD/YYYY` consistently (e.g., `'03/15/1978'`), but the VARCHAR(10) column accepts any string. Nothing prevents insertion of `'2025-03-15'` (ISO format), `'15/03/1978'` (DD/MM/YYYY), or `'March 15'`. The `LoanSummaryDto.originationDate` is passed through as a raw string without any parsing or validation. |
| **Business Impact** | The service layer does not parse or validate any date fields on loan accounts or payments — `originationDate` and `paymentDate` are exposed as raw strings in API responses. If a record uses an unexpected format, downstream consumers parsing these strings will fail. The column_mappings.md specifies `MM/DD/YYYY → DATE` conversion, but this conversion is not implemented in the current code. |
| **Recommended Fix** | Parse all date strings to `LocalDate` using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` in the service layer. Catch `DateTimeParseException` and log anomalous records. Return ISO-8601 formatted dates in API responses. |

---

## ANM-005: Financial Amounts with Embedded Commas — Parsing Risk

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Example Bad Records** | `BORR_ANN_INCM = '92,500'`, `LN_ORIG_AMT = '285,000'`, `LN_CURR_BAL = '271,432.56'`, `PMT_AMT = '1,487.02'` |
| **Business Impact** | `parseLegacyAmount()` handles comma removal correctly today, but the VARCHAR column accepts any string — including `'$285,000'`, `'285000.00.00'`, or empty strings. The current implementation would throw `NumberFormatException` on dollar signs, currency symbols, or double decimal points. `parseLegacyDecimal()` does NOT strip commas, so if an interest rate were entered as `'5,250'` it would throw an exception. |
| **Recommended Fix** | Sanitize all financial strings by stripping commas, dollar signs, and whitespace before parsing. Wrap all `BigDecimal` construction in try/catch with logging for unparseable values. Use `BigDecimal.ZERO` as fallback and flag the record. |

---

## ANM-006: Payment Component Amounts Don't Sum to Total

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Tables** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Example Bad Records** | `PMT-2025120001`: total=`1,487.02` but principal(`456.78`) + interest(`1,074.69`) + escrow(`355.55`) + late_fee(`0.00`) = `1,887.02` (overstated by \$400). `PMT-2025120002`: total=`2,924.18` but components sum to `2,924.18` (correct). `PMT-2025110003`: total=`1,077.05` but components sum to `1,124.55` (includes `47.50` late fee). |
| **Business Impact** | Financial reconciliation will fail. API consumers relying on the total amount will report different figures than those summing the components. This creates audit discrepancies and potential regulatory compliance issues for loan servicing. |
| **Recommended Fix** | Add a cross-field validation that checks `PMT_AMT == PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. Flag mismatches with a warning. Consider recalculating the total from components or logging the discrepancy for manual review. |

---

## ANM-007: Denormalized Borrower Data in Loan Accounts — Drift Risk

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_LN_ACCT` vs `CDW_BORR_MSTR` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_FST_NM`, `CDW_LN_ACCT.BORR_LST_NM`, `CDW_LN_ACCT.BORR_SSN_LST4` |
| **Example Bad Records** | In the current seed data, names are consistent (e.g., `BORR_FST_NM='James'` in both tables for B-10001). However, the SSN last-4 in `CDW_LN_ACCT` (`0142`) does not match any derivable value from `BORR_SSN_ENCR` (`ENC_XXX_001`) since the SSN is encrypted. Without constraints, these can drift independently. |
| **Business Impact** | If borrower B-10001's name is updated in `CDW_BORR_MSTR` but not in `CDW_LN_ACCT`, the API would return different names depending on which endpoint is called — `getBorrowerById` uses the master table, but `getLoanById` uses the denormalized copy in the loan account. This causes confusion for loan officers and potential compliance issues. |
| **Recommended Fix** | In the service layer, always resolve borrower data from `CDW_BORR_MSTR` via the `BORR_ID` foreign key rather than using the denormalized copies. Flag records where the denormalized name differs from the master record. |

---

## ANM-008: Delinquency Days Inconsistent with Status Code

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |
| **Example Bad Records** | Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'` (Active). Typically, 15 days delinquent should flag at least an early-stage delinquency status, not Active. All other loans show `LN_DLQ_DAYS = '0'` with `LN_STAT_CD = 'ACT'`, which is consistent. |
| **Business Impact** | Loan officers relying on the status code alone would miss that this loan is 15 days past due. Conversely, delinquency reports filtering by status code would exclude this delinquent loan. This undermines both the delinquency tracking and the status-based loan reporting. |
| **Recommended Fix** | Add cross-field validation: if `LN_DLQ_DAYS > 0` and `LN_STAT_CD = 'ACT'`, flag as a potential anomaly. Consider auto-escalating the status or at minimum logging a warning. |

---

## ANM-009: Credit Score as String — Range Validation Missing

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_CRDT_SCR` |
| **Example Bad Records** | Current values: `'745'`, `'780'`, `'692'`, `'810'`, `'658'` — all valid FICO range (300-850). But the VARCHAR(5) column would accept `'0'`, `'-1'`, `'9999'`, `'N/A'`, or empty string. `parseLegacyInteger()` returns `null` for blank/null values but throws `NumberFormatException` for non-numeric strings. |
| **Business Impact** | An out-of-range credit score (e.g., 0 or 9999) would pass parsing but produce incorrect risk assessments. A non-numeric value would crash the `getBorrowerById` endpoint with an unhandled `NumberFormatException`. |
| **Recommended Fix** | After parsing, validate that the credit score falls within 300-850 (standard FICO range). For out-of-range values, log a warning and set to `null` to indicate unknown. Wrap parsing in try/catch to handle non-numeric strings gracefully. |

---

## ANM-010: Annual Income Stored with Commas — Inconsistent with Other Numeric Fields

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_ANN_INCM` |
| **Example Bad Records** | `'92,500'`, `'125,000'`, `'78,000'`, `'145,000'`, `'65,000'` — all whole numbers with commas. Note that `BORR_ANN_INCM` is never parsed in the current `toBorrowerDto()` method. The field is read from the entity but never exposed in the `BorrowerDto`. |
| **Business Impact** | The annual income data is loaded but silently dropped — it never appears in any API response. If a future feature requires income data (e.g., debt-to-income ratio calculation), the comma-formatted string would need parsing. The `BorrowerDto` has no income field, so this data is effectively invisible to API consumers. |
| **Recommended Fix** | If income is needed for business logic, parse it via `parseLegacyAmount()` and add it to the DTO. If not needed, document the intentional exclusion. Either way, validate that the value is parseable at ingestion time. |

---

## ANM-011: LTV Percent Without Validation Against Appraised Value

| Field | Value |
|---|---|
| **Severity** | Low |
| **Affected Tables** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_LTV_PCT`, `LN_ORIG_AMT`, `PROP_APRS_VAL` |
| **Example Bad Records** | Loan `LN-2019-00142`: `LN_LTV_PCT = '82.5'`, `LN_ORIG_AMT = '285,000'`, `PROP_APRS_VAL = '345,000'`. Calculated LTV = 285000/345000 = 82.6% (stored as 82.5 — minor rounding difference). Loan `LN-2020-00398`: stored LTV = `68.2%`, calculated = 420000/615000 = 68.3%. |
| **Business Impact** | Small rounding discrepancies in LTV can affect mortgage insurance requirements (PMI is typically required above 80% LTV). The stored LTV values are not verified against the actual ratio of original amount to appraised value. |
| **Recommended Fix** | Cross-validate stored LTV against `LN_ORIG_AMT / PROP_APRS_VAL * 100`. Flag records where the discrepancy exceeds a threshold (e.g., 0.5%). |

---

## ANM-012: Payment Date Ordering Issue — Received After Processed

| Field | Value |
|---|---|
| **Severity** | Low |
| **Affected Tables** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT` |
| **Example Bad Records** | `PMT-2025120003`: `PMT_DT = '12/01/2025'`, `PMT_RECV_DT = '12/05/2025'`, `PMT_PROC_DT = '12/06/2025'`. The payment date is 12/01 but it wasn't received until 12/05 — suggesting the payment was backdated or the dates are inconsistent. `PMT-2025110003`: `PMT_DT = '11/01/2025'`, `PMT_RECV_DT = '11/18/2025'` — 17-day gap between payment date and receipt. |
| **Business Impact** | Backdated payments may indicate data entry errors or policy violations. A 17-day gap between payment date and receipt date raises questions about whether the payment was actually late (and whether the `47.50` late fee on this payment is correctly applied). |
| **Recommended Fix** | Validate that `PMT_RECV_DT >= PMT_DT` or flag when the gap exceeds a configurable threshold (e.g., 5 business days). Cross-reference late fees with the date gap. |

---

## Summary

| Severity | Count | Anomaly IDs |
|---|---|---|
| Critical | 2 | ANM-001, ANM-002 |
| High | 4 | ANM-003, ANM-004, ANM-005, ANM-006 |
| Medium | 4 | ANM-007, ANM-008, ANM-009, ANM-010 |
| Low | 2 | ANM-011, ANM-012 |
| **Total** | **12** | |
