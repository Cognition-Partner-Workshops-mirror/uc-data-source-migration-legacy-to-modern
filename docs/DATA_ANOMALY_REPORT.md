# Legacy CDW Data Anomaly Report

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## Summary

| # | Anomaly | Severity | Table | Column(s) |
|---|---------|----------|-------|-----------|
| 1 | All numeric/date fields stored as VARCHAR | Critical | ALL | ALL numeric/date cols |
| 2 | No foreign key constraints (orphan risk) | Critical | CDW_LN_ACCT, CDW_PMT_HIST | BORR_ID, PROD_CD, LN_ACCT_NBR |
| 3 | NULL in borrower middle initial | Low | CDW_BORR_MSTR | BORR_MID_INIT |
| 4 | Denormalized borrower data drift risk | High | CDW_LN_ACCT | BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 |
| 5 | Comma-formatted amounts as strings | Critical | CDW_LN_ACCT, CDW_PMT_HIST, CDW_BORR_MSTR, CDW_LN_PROD | LN_ORIG_AMT, PMT_AMT, BORR_ANN_INCM, etc. |
| 6 | Date strings in MM/DD/YYYY format | High | ALL | All `*_DT` columns |
| 7 | Credit score stored as VARCHAR | Medium | CDW_BORR_MSTR | BORR_CRDT_SCR |
| 8 | Payment component sum mismatch | High | CDW_PMT_HIST | PMT_AMT vs. PMT_PRIN_AMT+PMT_INT_AMT+PMT_ESCROW_AMT+PMT_LATE_FEE |
| 9 | Late payment with zero late fee | Medium | CDW_PMT_HIST | PMT_LATE_FEE, PMT_RECV_DT |
| 10 | Delinquent loan with active status | High | CDW_LN_ACCT | LN_DLQ_DAYS, LN_STAT_CD |
| 11 | LTV percent stored as bare number string | Medium | CDW_LN_ACCT | LN_LTV_PCT |
| 12 | No NOT NULL constraints on required fields | High | ALL | BORR_FST_NM, BORR_LST_NM, LN_ACCT_NBR, etc. |

---

## Anomaly Details

### ANO-001: All Numeric and Date Fields Stored as VARCHAR

- **Severity:** Critical
- **Affected Tables:** CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST
- **Affected Columns:** Every numeric column (amounts, rates, scores, terms, delinquency days) and every date column
- **Example Bad Records:**
  - `BORR_ANN_INCM = '92,500'` (B-10001) -- numeric with commas
  - `LN_INT_RT = '4.750'` (LN-2019-00142) -- decimal as string
  - `BORR_DOB_DT = '03/15/1978'` (B-10001) -- date as string
  - `LN_DLQ_DAYS = '15'` (LN-2018-00089) -- integer as string
  - `PROD_TERM_MOS = '360'` (FXD30) -- integer as string
- **Business Impact:** Any code parsing these fields is vulnerable to `NumberFormatException` or `DateTimeParseException` at runtime. If a legacy upstream system inserts a non-numeric value (e.g., `"N/A"`, `"--"`, `"$1,500"`), the API will crash with a 500 error. No database-level type enforcement exists to prevent this.
- **Recommended Fix:** Add defensive parsing with try/catch in the service layer for every string-to-number and string-to-date conversion. Log warnings for unparseable values and return safe defaults.

---

### ANO-002: No Foreign Key Constraints (Orphaned Record Risk)

- **Severity:** Critical
- **Affected Tables:** CDW_LN_ACCT, CDW_PMT_HIST
- **Affected Columns:**
  - `CDW_LN_ACCT.BORR_ID` references `CDW_BORR_MSTR.BORR_ID` -- no FK constraint
  - `CDW_LN_ACCT.PROD_CD` references `CDW_LN_PROD.PROD_CD` -- no FK constraint
  - `CDW_PMT_HIST.LN_ACCT_NBR` references `CDW_LN_ACCT.LN_ACCT_NBR` -- no FK constraint
- **Example Bad Records:** Current seed data is consistent, but nothing prevents:
  - A loan account with `BORR_ID = 'B-99999'` (nonexistent borrower)
  - A payment with `LN_ACCT_NBR = 'LN-XXXX'` (nonexistent loan)
  - A loan with `PROD_CD = 'ZZZ'` (nonexistent product)
- **Business Impact:** Orphaned loan accounts would cause `NullPointerException` in `LoanService.toLoanSummary()` when looking up the product via `products.get(acct.getProductCode())`. Orphaned payments would silently appear in the system with no parent loan. The `getBorrowerById` method would return a borrower with missing loans if the BORR_ID link is broken.
- **Recommended Fix:** Validate referential integrity at ingestion time. Before processing a loan account, verify the borrower ID and product code exist. Before processing a payment, verify the loan account number exists.

---

### ANO-003: NULL Middle Initial in Borrower Records

- **Severity:** Low
- **Affected Table:** CDW_BORR_MSTR
- **Affected Column:** BORR_MID_INIT
- **Example Bad Records:**
  - `B-10005` (Robert Williams): `BORR_MID_INIT = NULL`
- **Business Impact:** The `toBorrowerDto()` method handles this with a null check for name formatting, so no crash occurs. However, downstream consumers expecting a non-null middle initial could break.
- **Recommended Fix:** Already handled in code. No action needed beyond ensuring consistent null-safe handling.

---

### ANO-004: Denormalized Borrower Data Drift Risk

- **Severity:** High
- **Affected Table:** CDW_LN_ACCT
- **Affected Columns:** BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4
- **Example Bad Records:** Current data is consistent, but the schema allows:
  - `CDW_BORR_MSTR.BORR_FST_NM = 'James'` while `CDW_LN_ACCT.BORR_FST_NM = 'Jim'` for the same BORR_ID
  - `CDW_LN_ACCT.BORR_SSN_LST4 = '0142'` while `CDW_BORR_MSTR` has a different SSN encrypted value
- **Business Impact:** The `toLoanSummary()` method reads borrower name from `CDW_LN_ACCT` (denormalized), not from `CDW_BORR_MSTR` (source of truth). If the borrower updates their name in the master table but the loan account record isn't updated, the API returns stale/incorrect borrower names on loan summaries. This violates single-source-of-truth principles and can cause legal/compliance issues.
- **Recommended Fix:** Cross-validate denormalized fields against the master table at ingestion. Log warnings when mismatches are detected.

---

### ANO-005: Comma-Formatted Financial Amounts as Strings

- **Severity:** Critical
- **Affected Tables:** CDW_LN_ACCT, CDW_PMT_HIST, CDW_BORR_MSTR, CDW_LN_PROD
- **Affected Columns:** LN_ORIG_AMT, LN_CURR_BAL, LN_PMT_AMT, LN_ESCROW_BAL, PROP_APRS_VAL, PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE, BORR_ANN_INCM, PROD_MIN_AMT, PROD_MAX_AMT
- **Example Bad Records:**
  - `LN_ORIG_AMT = '285,000'` (LN-2019-00142)
  - `LN_CURR_BAL = '271,432.56'` (LN-2019-00142)
  - `BORR_ANN_INCM = '92,500'` (B-10001)
  - `PROD_MAX_AMT = '1,500,000'` (FXD30)
- **Business Impact:** The `parseLegacyAmount()` method strips commas before parsing, but will fail on values containing dollar signs (`$285,000`), spaces, or other non-numeric characters that may appear in legacy data. A single malformed amount crashes the entire API response for that record. Financial calculations on incorrectly parsed amounts could lead to regulatory violations.
- **Recommended Fix:** Implement robust amount parsing that strips all non-numeric characters except decimal points and minus signs. Add validation that the result is non-negative for amounts that should be positive.

---

### ANO-006: Date Strings in MM/DD/YYYY Format

- **Severity:** High
- **Affected Tables:** ALL
- **Affected Columns:** BORR_DOB_DT, BORR_CRET_DT, BORR_UPDT_DT, PROD_EFF_DT, PROD_EXP_DT, LN_ORIG_DT, LN_MAT_DT, LN_1ST_PMT_DT, LN_NXT_PMT_DT, LN_CRET_DT, LN_UPDT_DT, PMT_DT, PMT_RECV_DT, PMT_PROC_DT, PMT_CRET_DT, PMT_UPDT_DT
- **Example Bad Records:**
  - `BORR_DOB_DT = '03/15/1978'` (B-10001)
  - `LN_ORIG_DT = '02/15/2019'` (LN-2019-00142)
  - `PMT_DT = '12/15/2025'` (PMT-2025120001)
- **Business Impact:** Date strings are passed through to the API response as-is (e.g., `LoanSummaryDto.originationDate` and `PaymentDto.paymentDate`). No parsing or validation occurs. If a legacy system inserts a date in a different format (e.g., `YYYY-MM-DD`, `DD/MM/YYYY`, or `2025-12-01`), the API will return inconsistent date formats to consumers. Sorting by date in the `findByLoanAccountNumberOrderByPaymentDateDesc` repository method uses string ordering, which produces incorrect chronological order for MM/DD/YYYY strings.
- **Recommended Fix:** Parse all date strings to `LocalDate` at ingestion time using `MM/dd/yyyy` formatter with fallback patterns. Return ISO-8601 format (`yyyy-MM-dd`) from the API.

---

### ANO-007: Credit Score Stored as VARCHAR

- **Severity:** Medium
- **Affected Table:** CDW_BORR_MSTR
- **Affected Column:** BORR_CRDT_SCR
- **Example Bad Records:**
  - `BORR_CRDT_SCR = '745'` (B-10001)
  - `BORR_CRDT_SCR = '658'` (B-10005)
- **Business Impact:** `parseLegacyInteger()` will throw `NumberFormatException` if the value is non-numeric (e.g., `"N/A"`, `"---"`, `"PEND"`). Credit scores outside valid range (300-850) would be accepted without complaint. The API would return `null` for blank scores but crash on malformed ones.
- **Recommended Fix:** Add range validation (300-850) after parsing. Return null for out-of-range values with a warning log.

---

### ANO-008: Payment Component Sum Mismatch

- **Severity:** High
- **Affected Table:** CDW_PMT_HIST
- **Affected Columns:** PMT_AMT vs. PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE
- **Example Bad Records:**
  - PMT-2025120001: total=`1,487.02`, principal=`456.78` + interest=`1,074.69` + escrow=`355.55` + late_fee=`0.00` = **1,887.02** (sum exceeds total by $400.00)
  - PMT-2025120002: total=`2,924.18`, principal=`1,842.56` + interest=`815.50` + escrow=`266.12` + late_fee=`0.00` = **2,924.18** (matches)
  - PMT-2025110001: total=`1,487.02`, principal=`454.97` + interest=`1,076.50` + escrow=`355.55` + late_fee=`0.00` = **1,887.02** (sum exceeds total by $400.00)
- **Business Impact:** Financial reporting based on payment breakdowns will not reconcile with the total amount. This indicates either incorrect component recording or a data entry error in the legacy system. Downstream accounting systems that rely on component-level detail will produce incorrect reports.
- **Recommended Fix:** Validate that payment components sum to the total amount (within a small tolerance for rounding). Flag mismatches with a warning and record the discrepancy.

---

### ANO-009: Late Payment with Zero Late Fee

- **Severity:** Medium
- **Affected Table:** CDW_PMT_HIST
- **Affected Columns:** PMT_LATE_FEE, PMT_RECV_DT vs. PMT_DT
- **Example Bad Records:**
  - PMT-2025120003 (LN-2018-00089): Payment due `12/01/2025`, received `12/05/2025` (4 days late), late_fee = `0.00`
  - PMT-2025110003 (LN-2018-00089): Payment due `11/01/2025`, received `11/18/2025` (17 days late), late_fee = `47.50` (correctly assessed)
- **Business Impact:** Inconsistent late fee application. The December payment for loan LN-2018-00089 was received 4 days late but no late fee was charged, while the November payment (17 days late) correctly had a $47.50 late fee. This could indicate a grace period (typically 15 days for mortgages), but the inconsistency should be flagged for review.
- **Recommended Fix:** Add validation that flags late payments (received date > payment date + grace period) with zero late fees as potential anomalies.

---

### ANO-010: Delinquent Loan with Active Status

- **Severity:** High
- **Affected Table:** CDW_LN_ACCT
- **Affected Columns:** LN_DLQ_DAYS, LN_STAT_CD
- **Example Bad Records:**
  - LN-2018-00089 (Michael Torres): `LN_DLQ_DAYS = '15'`, `LN_STAT_CD = 'ACT'`
  - All other loans: `LN_DLQ_DAYS = '0'`, `LN_STAT_CD = 'ACT'`
- **Business Impact:** A loan with 15 delinquency days should potentially be flagged or have its status updated. The API reports this loan as "Active" with no indication of delinquency in the `LoanSummaryDto` (delinquency days are not included in the DTO). Consumers have no visibility into payment delinquency risk. Regulatory reporting that relies on status codes alone would miss this delinquent loan.
- **Recommended Fix:** Add cross-field validation: loans with delinquency days > 0 should either have an appropriate status or be flagged. Include delinquency information in the API response.

---

### ANO-011: LTV Percent as Bare Number String

- **Severity:** Medium
- **Affected Table:** CDW_LN_ACCT
- **Affected Column:** LN_LTV_PCT
- **Example Bad Records:**
  - `LN_LTV_PCT = '82.5'` (LN-2019-00142)
  - `LN_LTV_PCT = '68.2'` (LN-2020-00398)
  - `LN_LTV_PCT = '75.0'` (LN-2018-00089)
- **Business Impact:** LTV is not validated against computed value (current_balance / appraised_value * 100). For LN-2019-00142: 271,432.56 / 345,000 * 100 = 78.7% but stored as 82.5%. This discrepancy could indicate the LTV was calculated at origination and never updated, or there's a data error. LTV > 80% triggers PMI requirements, so incorrect LTV can have regulatory implications.
- **Recommended Fix:** Validate LTV against computed value from current balance and appraised value. Flag significant discrepancies (> 5% difference).

---

### ANO-012: No NOT NULL Constraints on Required Fields

- **Severity:** High
- **Affected Tables:** ALL
- **Affected Columns:** All columns except primary keys
- **Example:** The schema allows:
  - `CDW_BORR_MSTR` with `BORR_FST_NM = NULL` (a borrower with no first name)
  - `CDW_LN_ACCT` with `LN_CURR_BAL = NULL` (a loan with unknown balance)
  - `CDW_PMT_HIST` with `PMT_AMT = NULL` (a payment with no amount)
- **Business Impact:** `parseLegacyAmount(null)` returns `BigDecimal.ZERO`, silently treating missing financial data as zero. A null current balance would show as $0.00 in the API, which is misleading and potentially harmful for financial decisions. The `toBorrowerDto()` method would produce `"null null"` for a borrower name if both first and last names are null.
- **Recommended Fix:** Add null checks for required fields at ingestion. Reject or flag records where critical business fields (name, balance, amount, dates) are null.
