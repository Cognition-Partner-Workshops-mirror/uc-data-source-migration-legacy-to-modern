# Legacy Data Anomaly Report

This report documents data quality anomalies found in the legacy CDW (Corporate Data Warehouse) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`).

---

## ANOM-001: Null Middle Initial in Borrower Record

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_MID_INIT` |
| **Example Bad Record** | Borrower `B-10005` (Robert Williams) has `NULL` middle initial |
| **Business Impact** | The `toBorrowerDto` method in `LoanService.java` constructs the full name by conditionally including the middle initial. A `NULL` value is handled, but inconsistency across records means display formatting varies — some names show "James R. Mitchell" while others show "Robert Williams" (no middle initial separator). Downstream consumers expecting a uniform name format may break on parsing. |
| **Recommended Fix** | Accept `NULL` as valid but normalize to empty string at ingestion time. Ensure name-formatting logic produces consistent output regardless of whether a middle initial is present. |

---

## ANOM-002: Numeric Amounts Stored as Comma-Formatted Strings

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Example Bad Records** | `'92,500'` (B-10001 annual income), `'285,000'` (LN-2019-00142 original amount), `'1,487.02'` (LN-2019-00142 monthly payment) |
| **Business Impact** | The `parseLegacyAmount` method strips commas before parsing to `BigDecimal`. If any record contains unexpected characters (dollar signs, spaces, currency symbols, or non-ASCII characters — common in legacy warehouse extracts), `new BigDecimal(...)` throws `NumberFormatException`, causing a 500 error on the API. The method returns `BigDecimal.ZERO` for null/blank but has no protection against malformed non-blank values. |
| **Recommended Fix** | Add robust parsing with regex validation before conversion. Strip all non-numeric characters except decimal point and minus sign. Log a warning for malformed values and fall back to `BigDecimal.ZERO` instead of throwing. |

---

## ANOM-003: Credit Score Stored as String with No Range Validation

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_CRDT_SCR` |
| **Example Bad Records** | `'745'`, `'780'`, `'692'`, `'810'`, `'658'` — all valid currently, but VARCHAR(5) allows values like `'99999'`, `'abc'`, `'-100'`, or empty strings |
| **Business Impact** | `parseLegacyInteger` in `LoanService.java` calls `Integer.parseInt()` directly. A non-numeric value throws `NumberFormatException` (runtime crash). No range validation means values outside the FICO range (300-850) could be silently accepted, producing misleading API responses for credit risk assessment. |
| **Recommended Fix** | Validate that credit score is a numeric string in the range 300-850. Return `null` for unparseable values and log a warning. Add range clamping or rejection for out-of-range values. |

---

## ANOM-004: Dates Stored as MM/DD/YYYY Strings with No Format Validation

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT` |
| **Example Bad Records** | `'03/15/1978'`, `'07/22/1985'`, `'02/28/1990'` — all valid MM/DD/YYYY currently, but VARCHAR columns accept any string, including `'2025-01-15'` (ISO format), `'15/03/1978'` (DD/MM/YYYY), or `'N/A'` |
| **Business Impact** | Date strings are passed through to DTOs without parsing or validation (`dto.setOriginationDate(acct.getOriginationDate())`). The API returns raw legacy date strings in MM/DD/YYYY format. When the column_mappings.md specifies conversion to `DATE` type for the modern schema, any non-MM/DD/YYYY formatted dates will fail migration. Additionally, the raw string dates in API responses are not ISO-8601 compliant, making them difficult for API consumers to parse. |
| **Recommended Fix** | Parse all date strings to `LocalDate` at ingestion time using `MM/dd/yyyy` format. Return ISO-8601 formatted dates (`yyyy-MM-dd`) in API responses. Log and reject unparseable date values with a sensible fallback. |

---

## ANOM-005: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |
| **Example Bad Records** | Current data is consistent, but the schema has **no FK constraints** (`-- No foreign key constraints` is documented in the schema header). A loan account could reference `BORR_ID = 'B-99999'` (non-existent borrower) or `PROD_CD = 'INVALID'` (non-existent product). |
| **Business Impact** | In `LoanService.toLoanSummary()`, the product lookup `products.get(acct.getProductCode())` returns `null` for orphaned product references. The code handles this (`product != null ? product.getDescription() : acct.getProductCode()`), but `getBorrowerById()` does not validate that the borrower exists before looking up their loans. An orphaned `BORR_ID` in `CDW_LN_ACCT` would cause `NullPointerException` if borrower fields are accessed. In `getAllLoans()`, a product code not in the products map silently falls back to the raw code string — this masks data integrity problems. |
| **Recommended Fix** | Validate referential integrity at ingestion time. Check that every `BORR_ID` in loan accounts exists in `CDW_BORR_MSTR` and every `PROD_CD` exists in `CDW_LN_PROD`. Log orphaned records and either skip or flag them. |

---

## ANOM-006: Denormalized Borrower Data May Diverge from Master Record

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` (duplicated from `CDW_BORR_MSTR`) |
| **Example Bad Records** | Loan `LN-2019-00142` has `BORR_FST_NM='James'`, `BORR_LST_NM='Mitchell'` which matches borrower `B-10001`. However, if the borrower master record is updated (e.g., name change after marriage) without updating the loan account table, the denormalized copies diverge. |
| **Business Impact** | `toLoanSummary()` uses `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()` from the **loan account** table, while `toBorrowerDto()` uses `borrower.getFirstName()` from the **borrower master** table. If these diverge, the same person's name appears differently in loan listings vs. borrower details — a data consistency issue visible in API responses. |
| **Recommended Fix** | At ingestion time, cross-reference denormalized borrower fields in `CDW_LN_ACCT` against `CDW_BORR_MSTR`. Log mismatches as warnings. In the service layer, prefer the borrower master as the source of truth for borrower name. |

---

## ANOM-007: Delinquency Days as String with Inconsistent Values

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `LN_DLQ_DAYS` |
| **Example Bad Records** | Most loans have `'0'`, but loan `LN-2018-00089` (Michael Torres) has `'15'` — indicating 15 days delinquent. As a VARCHAR(5), this column could contain `'N/A'`, empty string, negative numbers, or non-numeric values. |
| **Business Impact** | The delinquency days field is not exposed in the current `LoanSummaryDto`, so it is not validated or used in the API layer. However, any future use would require integer parsing, and malformed values would throw `NumberFormatException`. The loan `LN-2018-00089` has `LN_DLQ_DAYS='15'` but `LN_STAT_CD='ACT'` — a 15-day delinquent loan should arguably not have an "Active" status; it may warrant a "Delinquent" or "Late" status. |
| **Recommended Fix** | Parse delinquency days to integer at ingestion time with fallback to 0. Cross-validate against status code: if delinquency days > 0, verify status is appropriate (not plain "Active"). |

---

## ANOM-008: Payment Component Amounts Don't Sum to Total

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Example Bad Records** | Payment `PMT-2025120001` for loan `LN-2019-00142`: Total = `1,487.02`, Principal = `456.78`, Interest = `1,074.69`, Escrow = `355.55`, Late Fee = `0.00`. Sum of components = 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02**, which does NOT equal the total of 1,487.02 (difference of $400.00). Similarly, payment `PMT-2025110001`: Total = `1,487.02`, components sum = 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** (same $400 discrepancy). |
| **Business Impact** | The API returns all component amounts and the total separately via `PaymentDto`. API consumers performing reconciliation will find that principal + interest + escrow + late fee != total amount. This breaks accounting integrity and could cause issues in financial reporting, audits, and downstream system reconciliation. |
| **Recommended Fix** | Add a validation check at ingestion time that verifies component amounts sum to the total (within a small tolerance for rounding). Log discrepancies as warnings. Consider either adjusting the total or flagging the record as requiring manual review. |

---

## ANOM-009: Late Payment Detection — Received Date After Due Date

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT` |
| **Example Bad Records** | Payment `PMT-2025120003` (loan `LN-2018-00089`): Due date `12/01/2025`, received `12/05/2025` (4 days late). Payment `PMT-2025110003`: Due date `11/01/2025`, received `11/18/2025` (17 days late) with a late fee of `47.50`. |
| **Business Impact** | Late payments are not flagged in the API response. The `PaymentDto` does not indicate whether a payment was late. Payment `PMT-2025120003` was received 4 days late but has **no late fee** (`0.00`), while `PMT-2025110003` was 17 days late and **does** have a late fee. This inconsistency in late fee application could indicate a data entry error or policy exception that is not documented. |
| **Recommended Fix** | At ingestion time, compare received date to payment date. If received after due date, verify that a late fee is present (or document the exemption). Add a `lateIndicator` field to the payment DTO. |

---

## ANOM-010: All-VARCHAR Schema Creates Universal String Parsing Risk

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | All tables (`CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST`) |
| **Affected Columns** | Every column that semantically represents a non-string type |
| **Example Bad Records** | `LN_INT_RT` (interest rate) is VARCHAR(8) — could contain `'5.250'` or `'N/A'` or `'TBD'`. `LN_TERM_MOS` is VARCHAR(5) — could contain `'360'` or `'OPEN'`. `PROD_TERM_MOS` is VARCHAR(5) — same risk. `LN_LTV_PCT` is VARCHAR(8) — could contain `'82.5'` or `'unknown'`. |
| **Business Impact** | The service layer's `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` methods all throw unchecked exceptions (`NumberFormatException`) for malformed input. A single bad record in any of these fields crashes the entire API request (e.g., `getAllLoans()` fails completely if any one loan has a bad interest rate). There is no per-record error isolation. |
| **Recommended Fix** | Wrap all parsing methods in try-catch blocks. Return sensible defaults or null for unparseable values. Log warnings with the record ID and field name. Consider a validation pass that pre-screens all records before serving API responses. |

---

## Summary

| Severity | Count | Anomaly IDs |
|---|---|---|
| Critical | 3 | ANOM-002, ANOM-005, ANOM-010 |
| High | 3 | ANOM-003, ANOM-006, ANOM-008 |
| Medium | 3 | ANOM-001, ANOM-007, ANOM-009 |
| Low | 0 | — |

### Top 3 Critical Anomalies for Root Cause Analysis

1. **ANOM-010**: All-VARCHAR schema — universal parsing risk causing runtime crashes
2. **ANOM-002**: Comma-formatted numeric strings — `NumberFormatException` on malformed data
3. **ANOM-005**: No FK constraints — orphaned records causing `NullPointerException`
