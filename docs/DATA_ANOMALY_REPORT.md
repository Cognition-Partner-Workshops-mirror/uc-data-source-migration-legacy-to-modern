# Data Anomaly Report — Legacy CDW Tables

This report documents data quality anomalies found in the legacy Corporate Data Warehouse (CDW) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`). Each anomaly is a known risk for the migration to the modern schema and for the correctness of the current service-layer translation logic in `LoanService.java`.

---

## ANO-001: All Columns Are VARCHAR — Numeric Parsing Failures at Runtime

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_DLQ_DAYS`, `LN_ESCROW_BAL`, `LN_LTV_PCT`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`, `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT` |
| **Example Bad Records** | Any record where these columns contain non-numeric characters beyond commas and decimals (e.g. `"N/A"`, `""`, `"$285,000"`, `"TBD"`). The current seed data uses comma-formatted strings like `"92,500"` and `"271,432.56"` which are valid but fragile. |
| **Business Impact** | `LoanService.parseLegacyAmount()` and `parseLegacyInteger()` call `new BigDecimal(...)` and `Integer.parseInt(...)` directly. Any non-numeric string causes an unhandled `NumberFormatException` that propagates as a 500 Internal Server Error to the API consumer. A single corrupt record poisons the entire `/api/loans` listing because `getAllLoans()` has no per-record error handling. |
| **Recommended Fix** | Wrap all numeric parsing in try-catch with logging. Return a sentinel/default value or skip the record and log a warning. Add input validation at the service layer before parsing. |

---

## ANO-002: Dates Stored as Strings with No Format Validation

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT` |
| **Example Bad Records** | Schema documents format as `MM/DD/YYYY` but no constraint enforces it. Possible variations: `"2025-03-15"` (ISO), `"03-15-2025"` (dash-separated), `"3/15/2025"` (no zero-padding), `""`, `NULL`. The current seed data is consistent but production data from the CDW may not be. |
| **Business Impact** | Date strings are passed directly to DTOs without parsing (e.g. `dto.setOriginationDate(acct.getOriginationDate())`). The column_mappings.md specifies these must be parsed to `DATE` or `TIMESTAMP` during migration. Any inconsistent format will cause `DateTimeParseException` during migration and currently exposes raw legacy format strings to API consumers. The `findByLoanAccountNumberOrderByPaymentDateDesc` repository query sorts by string value, not chronological order — `"11/01/2025"` sorts before `"12/01/2025"` only by coincidence; `"9/01/2025"` would sort after `"12/01/2025"`. |
| **Recommended Fix** | Add date parsing/validation at the service layer. Accept multiple formats (MM/dd/yyyy, yyyy-MM-dd) with a fallback. Return ISO-8601 formatted strings in API responses. |

---

## ANO-003: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | `CDW_LN_ACCT` (references `CDW_BORR_MSTR.BORR_ID` and `CDW_LN_PROD.PROD_CD`), `CDW_PMT_HIST` (references `CDW_LN_ACCT.LN_ACCT_NBR`) |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |
| **Example Bad Records** | A loan account with `BORR_ID = 'B-99999'` (non-existent borrower) or `PROD_CD = 'INVALID'` (non-existent product) would be accepted by the schema. A payment with `LN_ACCT_NBR = 'LN-DELETED-001'` pointing to a removed loan would also be accepted. |
| **Business Impact** | `LoanService.toLoanSummary()` does `products.get(acct.getProductCode())` — if the product code doesn't exist in the map, `product` is `null` and the code falls back to showing the raw product code. However, `getBorrowerById()` calls `loanAccountRepository.findByBorrowerId(borrowerId)` which could return loans with dangling product references. More critically, during migration to the modern schema (which has real FKs), orphaned records will cause INSERT failures that block the entire migration batch. |
| **Recommended Fix** | Add referential integrity checks in the service layer. Validate that BORR_ID, PROD_CD, and LN_ACCT_NBR reference existing records before processing. Log and quarantine orphaned records. |

---

## ANO-004: Denormalized Borrower Data in Loan Accounts — Data Drift Risk

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` (redundant with `CDW_BORR_MSTR`) |
| **Example Bad Records** | Borrower B-10001 is "James Mitchell" in `CDW_BORR_MSTR` and also "James Mitchell" in `CDW_LN_ACCT`. If the borrower updates their name in the master table but the loan account is not updated, the embedded values drift. The SSN last-4 field `BORR_SSN_LST4` in the loan account is `'0142'` for B-10001, but this appears to match the phone number suffix, not the actual SSN — the master table only has `BORR_SSN_ENCR` (encrypted full SSN), making cross-validation impossible. |
| **Business Impact** | `LoanService.toLoanSummary()` uses the denormalized `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()` for the borrower name, while `toBorrowerDto()` uses the master table. The same borrower can appear with different names in different API responses. During migration, the column_mappings.md correctly marks these columns as `*(dropped)*`, but any drift means the master table may also have stale data. |
| **Recommended Fix** | Always resolve borrower name from `CDW_BORR_MSTR` by joining on `BORR_ID` instead of using the denormalized fields. Add a validation check that flags records where the denormalized values diverge from the master. |

---

## ANO-005: Amounts Stored as Comma-Formatted Strings

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM` (e.g. `"92,500"`), `LN_ORIG_AMT` (e.g. `"285,000"`), `LN_CURR_BAL` (e.g. `"271,432.56"`), `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Example Bad Records** | Current seed data: `'92,500'`, `'285,000'`, `'271,432.56'`, `'1,487.02'`. These are valid for `parseLegacyAmount()` which strips commas. Risks: currency symbols (`"$285,000"`), locale-specific formats (`"285.000,00"` European), whitespace (`" 285,000 "`), or empty strings. The `PROD_MIN_AMT` for VA30 is `'0'` (no commas) which works but is inconsistent. |
| **Business Impact** | `parseLegacyAmount()` strips commas and calls `new BigDecimal()`. Any unexpected formatting causes `NumberFormatException` → 500 error. No range validation means negative amounts or astronomically large values pass through silently. |
| **Recommended Fix** | Normalize amount strings: strip currency symbols, whitespace, and handle locale variations. Add range validation (e.g., loan amounts between $0 and $10M, interest rates between 0% and 30%). |

---

## ANO-006: Credit Score Stored as String — No Range Validation

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_CRDT_SCR` |
| **Example Bad Records** | Current seed data values: `'745'`, `'780'`, `'692'`, `'810'`, `'658'`. These are valid FICO scores (300–850). Risks: values like `'0'`, `'-1'`, `'999'`, `'N/A'`, or `''` would pass the VARCHAR schema but fail or produce incorrect results. |
| **Business Impact** | `parseLegacyInteger()` converts to `Integer` but performs no range check. A credit score of `0` or `999` would be returned to API consumers without validation, potentially triggering incorrect loan eligibility decisions downstream. |
| **Recommended Fix** | Validate credit score is within 300–850 range after parsing. Log a warning and set to `null` if out of range. |

---

## ANO-007: Payment Component Amounts Don't Sum to Total

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Example Bad Records** | PMT-2025120001: total=`1,487.02`, principal=`456.78`, interest=`1,074.69`, escrow=`355.55`, late_fee=`0.00`. Sum of components: 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02**, but total is **1,487.02**. Discrepancy: **$400.00**. This pattern exists across multiple payment records — the escrow amount appears to be double-counted or the total excludes escrow. |
| **Business Impact** | API consumers receiving payment breakdowns will see component amounts that don't reconcile with the total. Financial reporting and audit trails will be incorrect. The `toPaymentDto()` method copies all amounts verbatim without any reconciliation check. |
| **Recommended Fix** | Add a reconciliation validation that checks `principal + interest + escrow + lateFee == total`. Flag discrepancies with a warning in the response or a separate data quality field. |

---

## ANO-008: Loan Account LTV Exceeds 100% — Invalid Business Data

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `LN_LTV_PCT` |
| **Example Bad Records** | LN-2019-00142: `LN_LTV_PCT = '82.5'`, `LN_ORIG_AMT = '285,000'`, `PROP_APRS_VAL = '345,000'`. Actual LTV: 285000/345000 = 82.6% (close but not exact). LN-2017-00034: `LTV = '80.0'`, amount=165000, appraisal=206000. Actual: 80.1%. These are minor rounding differences but the field accepts any string, including values like `'150.0'` which would be invalid (>100% LTV without documentation). |
| **Business Impact** | LTV is a critical underwriting metric. Inconsistency between stored LTV and computed LTV undermines trust in the data. Values over 100% without FHA/VA mortgage insurance documentation indicate data entry errors. |
| **Recommended Fix** | Validate LTV is between 0 and 150 (some programs allow >100%). Cross-validate against `LN_ORIG_AMT / PROP_APRS_VAL`. Flag mismatches. |

---

## ANO-009: Status Codes Not Validated Against Allowed Values

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_STAT_CD`, `LN_STAT_CD`, `PROD_STAT_CD`, `PMT_TYP_CD`, `PMT_STAT_CD`, `PROP_TYP_CD` |
| **Example Bad Records** | Current seed data uses valid codes: `'ACT'`, `'SFR'`, `'CND'`, `'TWN'`, `'REG'`, `'PST'`. However, the VARCHAR columns accept any string. Unrecognized codes fall through to the `default -> code` branch in `expandStatusCode()`, `expandPropertyType()`, etc., returning the raw abbreviation to the API consumer. |
| **Business Impact** | API responses mix expanded labels ("Active", "Single Family Residence") with raw codes for any unrecognized value. Consumer applications parsing these responses may break on unexpected values. The `BORR_STAT_CD` uses `'ACT'` but `expandStatusCode()` only handles loan status codes (ACT, CLO, DFT, FRB) — borrower status codes could differ. |
| **Recommended Fix** | Define and validate against explicit allowed-value sets for each status column. Log unrecognized codes as warnings. Return a consistent "Unknown" label or throw a validation error. |

---

## ANO-010: Delinquency Days Inconsistent with Loan Status

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |
| **Example Bad Records** | LN-2018-00089 (Michael Torres): `LN_STAT_CD = 'ACT'` but `LN_DLQ_DAYS = '15'`. An active loan with 15 days delinquency may be correct (grace period not yet expired) but could also indicate the status should be 'DFT' (default) if delinquency exceeds the grace period. The late fee on PMT-2025110003 ($47.50) confirms this borrower has payment issues. |
| **Business Impact** | Loan status and delinquency days are both used for risk assessment. Contradictions between these fields lead to incorrect risk categorization and potentially missed collection actions. |
| **Recommended Fix** | Add cross-field validation: if `LN_DLQ_DAYS > 0` and `LN_STAT_CD = 'ACT'`, flag for review. If `LN_DLQ_DAYS > 90`, status should likely be 'DFT'. |

---

## ANO-011: NULL Values in Optional Fields Without Explicit Defaults

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |
| **Example Bad Records** | B-10005 (Robert Williams): `BORR_MID_INIT = NULL`. B-10002 (Sarah Chen): `BORR_ADDR_LN2 = NULL`. These are expected for optional fields, but the service layer handles them inconsistently. |
| **Business Impact** | `toBorrowerDto()` checks `borrower.getMiddleInitial() != null` before building the full name, which is correct. However, the property address in `toLoanSummary()` concatenates `propertyAddress + ", " + propertyCity + ", " + propertyState + " " + propertyZip` without null checks — if any of these are NULL, the address becomes `"null, null, null null"` in the API response. |
| **Recommended Fix** | Add null-safe string concatenation. Use `Optional` or empty-string defaults for all nullable fields before building composite strings. |

---

## ANO-012: Payment Sorting by String Date — Incorrect Chronological Order

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Column** | `PMT_DT` |
| **Example Bad Records** | Current data uses `MM/DD/YYYY` format consistently, and the repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts by `PMT_DT` descending. String sorting of `"12/01/2025"` vs `"11/01/2025"` happens to work, but `"9/01/2025"` would sort after `"12/01/2025"` alphabetically (9 > 1). Similarly, cross-year sorting: `"01/15/2026"` sorts before `"12/15/2025"` alphabetically (0 < 1). |
| **Business Impact** | Payment history displayed to users could be in wrong order, showing newer payments before older ones or vice versa. Financial calculations that depend on payment ordering (e.g., running balance, amortization) would produce incorrect results. |
| **Recommended Fix** | Parse date strings to proper `LocalDate` objects in the service layer and sort programmatically. Alternatively, store as ISO-8601 (`yyyy-MM-dd`) which sorts correctly as strings. |

---

## Summary Table

| ID | Title | Severity | Effort to Fix |
|---|---|---|---|
| ANO-001 | VARCHAR numeric fields — parsing failures | Critical | Medium |
| ANO-002 | String dates — no format validation | Critical | Medium |
| ANO-003 | No FK constraints — orphaned records | Critical | Large |
| ANO-004 | Denormalized borrower data — drift risk | High | Medium |
| ANO-005 | Comma-formatted amount strings | High | Small |
| ANO-006 | Credit score — no range validation | High | Small |
| ANO-007 | Payment components don't sum to total | High | Medium |
| ANO-008 | LTV percentage — invalid values possible | Medium | Small |
| ANO-009 | Status codes — no allowed-value validation | Medium | Small |
| ANO-010 | Delinquency vs status inconsistency | Medium | Small |
| ANO-011 | NULL fields — inconsistent null handling | Medium | Small |
| ANO-012 | String date sorting — incorrect order | Medium | Medium |
