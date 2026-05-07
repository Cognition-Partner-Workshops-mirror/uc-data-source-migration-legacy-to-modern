# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql`, `data-legacy.sql`, and `column_mappings.md`.

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3     |
| High     | 4     |
| Medium   | 3     |
| Low      | 2     |

---

## ANM-001: Numeric Amounts Stored as Comma-Formatted Strings

**Severity:** Critical

**Affected Tables & Columns:**
- `CDW_BORR_MSTR.BORR_ANN_INCM` — annual income (e.g., `'92,500'`, `'125,000'`)
- `CDW_LN_ACCT.LN_ORIG_AMT` — original loan amount (e.g., `'285,000'`)
- `CDW_LN_ACCT.LN_CURR_BAL` — current balance (e.g., `'271,432.56'`)
- `CDW_LN_ACCT.LN_PMT_AMT` — monthly payment (e.g., `'1,487.02'`)
- `CDW_LN_ACCT.LN_ESCROW_BAL`, `PROP_APRS_VAL`
- `CDW_LN_PROD.PROD_MIN_AMT`, `PROD_MAX_AMT`
- `CDW_PMT_HIST.PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`

**Example Bad Records:**
```sql
-- Annual income with commas
INSERT INTO CDW_BORR_MSTR ... '92,500' ...   -- B-10001
INSERT INTO CDW_BORR_MSTR ... '125,000' ...  -- B-10002

-- Loan amounts with commas and decimals
INSERT INTO CDW_LN_ACCT ... '285,000', '271,432.56' ... -- LN-2019-00142
```

**Business Impact:**
`BigDecimal("92,500")` throws `NumberFormatException` at runtime. Any API call that triggers `parseLegacyAmount()` or `parseLegacyDecimal()` without comma-stripping will crash. The current code does strip commas in `parseLegacyAmount()` but **not** in `parseLegacyDecimal()`, meaning fields routed through the wrong parser will fail. Incorrect amounts in loan servicing can cause wrong payment calculations, regulatory reporting errors, and balance misstatements.

**Recommended Fix:**
Normalize all amount strings by stripping commas, dollar signs, and whitespace before parsing to `BigDecimal`. Add input validation that rejects non-numeric residues after normalization.

---

## ANM-002: Dates Stored as Inconsistently Formatted Strings

**Severity:** Critical

**Affected Tables & Columns:**
- `CDW_BORR_MSTR.BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`
- `CDW_LN_ACCT.LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`
- `CDW_LN_PROD.PROD_EFF_DT`, `PROD_EXP_DT`
- `CDW_PMT_HIST.PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`

**Example Bad Records:**
```sql
-- All dates are stored as MM/DD/YYYY strings in VARCHAR columns
'03/15/1978'  -- BORR_DOB_DT for B-10001
'02/15/2019'  -- LN_ORIG_DT for LN-2019-00142
'12/31/2099'  -- PROD_EXP_DT for FXD30 (far-future sentinel)
```

**Business Impact:**
The schema comment says `MM/DD/YYYY` but there is no constraint enforcing this. The service layer passes date strings directly to DTOs without parsing (e.g., `dto.setOriginationDate(acct.getOriginationDate())` on line 113 of `LoanService.java`). If a record contains `YYYY-MM-DD`, `DD/MM/YYYY`, or a garbage string, it will silently propagate to API consumers. Date comparisons and sorting in the payment repository (`findByLoanAccountNumberOrderByPaymentDateDesc`) use lexicographic ordering on strings, not chronological ordering — e.g., `'12/01/2024'` sorts after `'01/15/2025'` lexicographically (`'1' > '0'`), but December 2024 is chronologically before January 2025. Within the same year, single-digit months (01-09) also sort incorrectly against double-digit months (10-12).

**Recommended Fix:**
Parse all date strings to `java.time.LocalDate` at ingestion time using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Reject or quarantine records with unparseable dates. Store parsed dates in DTOs.

---

## ANM-003: No Foreign Key Constraints — Orphaned Record Risk

**Severity:** Critical

**Affected Tables & Columns:**
- `CDW_LN_ACCT.BORR_ID` → `CDW_BORR_MSTR.BORR_ID` (no FK constraint)
- `CDW_LN_ACCT.PROD_CD` → `CDW_LN_PROD.PROD_CD` (no FK constraint)
- `CDW_PMT_HIST.LN_ACCT_NBR` → `CDW_LN_ACCT.LN_ACCT_NBR` (no FK constraint)

**Example Bad Records:**
```sql
-- Current data is consistent, but nothing prevents:
INSERT INTO CDW_LN_ACCT VALUES ('LN-ORPHAN', 'B-99999', ...);  -- B-99999 doesn't exist
INSERT INTO CDW_PMT_HIST VALUES ('PMT-ORPHAN', 'LN-GHOST', ...); -- LN-GHOST doesn't exist
```

**Business Impact:**
`LoanService.getLoanById()` calls `loanProductRepository.findById(acct.getProductCode())` which returns `Optional.empty()` for orphaned product codes — the code handles this with `.orElse(null)` but then builds `dto.setProductDescription(product != null ? ... : acct.getProductCode())` which silently degrades. For borrower lookups, `getBorrowerById()` fetches loans via `findByBorrowerId(borrowerId)` which would return an empty list for orphaned borrower IDs, causing silent data loss. If a payment references a non-existent loan, the API will return payment data that cannot be correlated to any loan.

**Recommended Fix:**
Add referential integrity validation at ingestion time. Verify that every `BORR_ID` in `CDW_LN_ACCT` exists in `CDW_BORR_MSTR`, every `PROD_CD` exists in `CDW_LN_PROD`, and every `LN_ACCT_NBR` in `CDW_PMT_HIST` exists in `CDW_LN_ACCT`.

---

## ANM-004: Credit Score Stored as String with No Range Validation

**Severity:** High

**Affected Table & Column:** `CDW_BORR_MSTR.BORR_CRDT_SCR`

**Example Bad Records:**
```sql
'745'  -- B-10001 (valid)
'780'  -- B-10002 (valid)
'692'  -- B-10003 (valid)
'810'  -- B-10004 (valid)
'658'  -- B-10005 (valid)
-- But nothing prevents: '', 'N/A', '-1', '9999', 'ABC'
```

**Business Impact:**
`LoanService.toBorrowerDto()` calls `parseLegacyInteger(borrower.getCreditScore())` which uses `Integer.parseInt()`. Non-numeric values like `'N/A'` or `'ABC'` will throw `NumberFormatException`, crashing the borrower API endpoint. Even if parsed, there is no range validation — credit scores outside 300-850 (FICO) are business-logic errors that would cause incorrect risk assessments and loan eligibility determinations.

**Recommended Fix:**
Parse to integer with try-catch. Validate range 300-850. Return null or a sentinel for invalid scores and log a warning.

---

## ANM-005: Null Values in Logically Required Fields

**Severity:** High

**Affected Tables & Columns:**
- `CDW_BORR_MSTR.BORR_MID_INIT` — NULL for B-10005 (Robert Williams)
- `CDW_BORR_MSTR.BORR_ADDR_LN2` — NULL for B-10002, B-10003, B-10005
- All columns are `VARCHAR` with no `NOT NULL` constraints in the legacy schema

**Example Bad Records:**
```sql
-- B-10005: middle initial is NULL
INSERT INTO CDW_BORR_MSTR VALUES ('B-10005', 'Robert', 'Williams', NULL, ...);

-- B-10002, B-10003, B-10005: address line 2 is NULL
INSERT INTO CDW_BORR_MSTR VALUES ('B-10002', 'Sarah', 'Chen', 'L', ..., NULL, 'Portland', ...);
```

**Business Impact:**
The `toBorrowerDto()` method handles null `middleInitial` correctly (line 123), but other code paths may not. If `firstName` or `lastName` were null (the schema allows it), `toBorrowerDto()` would produce `"null null"` as the full name. Similarly, `toLoanSummary()` concatenates property address fields without null checks (line 114) — a null `propertyCity` would produce `"742 Elm Street, null, IL 62701"` in the API response.

**Recommended Fix:**
Add null checks on all fields used in string concatenation. For required business fields (name, SSN, dates), reject records with nulls. For optional fields (address line 2, middle initial), use empty string defaults.

---

## ANM-006: Denormalized Borrower Data in Loan Accounts — Drift Risk

**Severity:** High

**Affected Table:** `CDW_LN_ACCT`

**Affected Columns:** `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`

**Example Bad Records:**
```sql
-- CDW_BORR_MSTR has B-10001 as 'James Mitchell'
-- CDW_LN_ACCT for LN-2019-00142 also stores 'James', 'Mitchell'
-- If the borrower updates their name, only CDW_BORR_MSTR gets updated
-- CDW_LN_ACCT retains the stale denormalized copy
```

**Business Impact:**
`LoanService.toLoanSummary()` reads borrower name from the denormalized `CDW_LN_ACCT` fields (line 106: `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`), NOT from the canonical `CDW_BORR_MSTR` table. If these drift apart, the loan listing API returns a different name than the borrower detail API. This is a data consistency issue that can cause confusion in customer-facing applications and regulatory reporting discrepancies.

**Recommended Fix:**
Always resolve borrower name from the canonical `CDW_BORR_MSTR` table via the `BORR_ID` foreign key. Add a validation check that flags records where denormalized fields don't match the master record.

---

## ANM-007: Interest Rate and LTV as Strings with No Bounds Validation

**Severity:** High

**Affected Tables & Columns:**
- `CDW_LN_ACCT.LN_INT_RT` — e.g., `'4.750'`, `'3.125'`, `'5.250'`
- `CDW_LN_ACCT.LN_LTV_PCT` — e.g., `'82.5'`, `'68.2'`, `'75.0'`

**Example Bad Records:**
```sql
-- Current values are valid but nothing prevents:
-- LN_INT_RT = '-5.0' (negative rate), '999.99' (absurd rate), 'TBD'
-- LN_LTV_PCT = '150.0' (over 100%, underwater but possible), 'N/A'
```

**Business Impact:**
`parseLegacyDecimal()` in `LoanService.java` (line 157-160) does not strip commas — it only trims whitespace. If an interest rate contains a comma (unlikely but possible given the pattern of other fields), it will throw `NumberFormatException`. There is no business-rule validation: negative interest rates, rates above 100%, or LTV values outside reasonable bounds (0-200%) would propagate silently to API consumers and downstream calculations.

**Recommended Fix:**
Parse with error handling. Validate interest rate range (0-30%) and LTV range (0-200%). Log warnings for edge cases.

---

## ANM-008: Status Codes with No Enumeration Constraint

**Severity:** Medium

**Affected Tables & Columns:**
- `CDW_BORR_MSTR.BORR_STAT_CD` — expected: `ACT`, `INA`
- `CDW_LN_ACCT.LN_STAT_CD` — expected: `ACT`, `CLO`, `DFT`, `FRB`
- `CDW_PMT_HIST.PMT_STAT_CD` — expected: `PST`, `REV`, `NSF`, `PND`
- `CDW_PMT_HIST.PMT_TYP_CD` — expected: `REG`, `EXT`, `PRT`, `PRE`

**Example Bad Records:**
```sql
-- All current records use 'ACT' status which is valid
-- But VARCHAR(5) allows any value: 'XYZ', '', 'ACTIV', 'active'
```

**Business Impact:**
`LoanService.expandStatusCode()` (line 167-176) uses a switch expression that falls through to `default -> code` for unrecognized codes. This means an invalid status code like `'XYZ'` would be passed through verbatim to the API response as `"XYZ"` instead of a human-readable status. Case sensitivity is also unhandled — `'act'` would not match `"ACT"` and would pass through as-is.

**Recommended Fix:**
Validate status codes against the known enumeration at ingestion time. Normalize to uppercase before matching. Log warnings for unrecognized codes and map them to a default like `"UNKNOWN"`.

---

## ANM-009: Payment Amount Component Mismatch

**Severity:** Medium

**Affected Table:** `CDW_PMT_HIST`

**Affected Columns:** `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`

**Example Bad Records:**
```sql
-- PMT-2025120001: total=1,487.02, principal=456.78, interest=1,074.69, escrow=355.55, late_fee=0.00
-- Sum of components: 456.78 + 1,074.69 + 355.55 + 0.00 = 1,887.02
-- Total stated: 1,487.02
-- MISMATCH: components sum to $400.00 more than the stated total

-- PMT-2025110001: total=1,487.02, principal=454.97, interest=1,076.50, escrow=355.55, late_fee=0.00
-- Sum: 454.97 + 1,076.50 + 355.55 + 0.00 = 1,887.02
-- MISMATCH: same $400.00 discrepancy (systematic issue on loan LN-2019-00142)

-- PMT-2025110003: total=1,077.05, principal=295.82, interest=781.23, escrow=0.00, late_fee=47.50
-- Sum: 295.82 + 781.23 + 0.00 + 47.50 = 1,124.55
-- MISMATCH: $47.50 over — the late fee appears to be double-counted

-- PMT-2025120002: total=2,924.18, principal=1,842.56, interest=815.50, escrow=266.12, late_fee=0.00
-- Sum: 1,842.56 + 815.50 + 266.12 + 0.00 = 2,924.18 ✓ (matches)
```

3 of 10 payments (30%) have component mismatches in the seed data.

**Business Impact:**
When payment components don't sum to the total, it creates an accounting discrepancy. Downstream systems that rely on component breakdowns for tax reporting (interest is tax-deductible for mortgages), escrow analysis, or amortization schedules will produce incorrect results. The service layer passes these amounts through without any reconciliation check.

**Recommended Fix:**
Add a validation check that verifies `principal + interest + escrow + late_fee == total_amount` (within a small tolerance for rounding). Flag mismatched records for review.

---

## ANM-010: Payment Date Ordering Anomaly (Late Payments)

**Severity:** Medium

**Affected Table:** `CDW_PMT_HIST`

**Affected Columns:** `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`

**Example Bad Records:**
```sql
-- PMT-2025120003 (LN-2018-00089, Torres):
--   PMT_DT=12/01/2025, PMT_RECV_DT=12/05/2025, PMT_PROC_DT=12/06/2025
--   Payment due date is BEFORE received date — late payment
--   Also has LN_DLQ_DAYS='15' on the loan account

-- PMT-2025110003 (same loan):
--   PMT_DT=11/01/2025, PMT_RECV_DT=11/18/2025, PMT_PROC_DT=11/19/2025
--   17 days late, with PMT_LATE_FEE='47.50'
```

**Business Impact:**
The repository sorts payments by `PaymentDate DESC` (string comparison), but `'12/01/2025'` < `'02/01/2025'` lexicographically since `'0'` < `'1'`. This means December payments sort BEFORE February payments, producing incorrect chronological ordering in the API response. Additionally, the pattern of `received_date > payment_date` indicates late payments, but the service layer does not flag or validate this.

**Recommended Fix:**
Parse dates to `LocalDate` before sorting. Add validation that flags `received_date > payment_date` as late payments. Cross-reference with delinquency days on the loan account.

---

## ANM-011: Loan Term Stored as String with No Consistency Check

**Severity:** Low

**Affected Tables & Columns:**
- `CDW_LN_PROD.PROD_TERM_MOS` — e.g., `'360'`, `'180'`
- `CDW_LN_ACCT.LN_TERM_MOS` — e.g., `'360'`, `'180'`

**Example Bad Records:**
```sql
-- Product FXD15 has PROD_TERM_MOS='180'
-- Loan LN-2020-00398 uses product FXD15 and has LN_TERM_MOS='180' ✓
-- But no constraint prevents a loan with FXD15 having LN_TERM_MOS='360'
```

**Business Impact:**
If the loan term doesn't match the product term, amortization calculations will be incorrect. The service layer doesn't cross-reference these values. `parseLegacyInteger()` would throw `NumberFormatException` for non-numeric term values.

**Recommended Fix:**
Validate that loan term matches the associated product term. Parse with error handling.

---

## ANM-012: SSN Last-4 Mismatch Between Tables

**Severity:** Low

**Affected Tables & Columns:**
- `CDW_BORR_MSTR.BORR_SSN_ENCR` — full encrypted SSN
- `CDW_LN_ACCT.BORR_SSN_LST4` — last 4 of SSN

**Example Bad Records:**
```sql
-- B-10001 has BORR_SSN_ENCR='ENC_XXX_001', and LN-2019-00142 has BORR_SSN_LST4='0142'
-- B-10002 has BORR_SSN_ENCR='ENC_XXX_002', and LN-2020-00398 has BORR_SSN_LST4='0198'
-- The SSN_LST4 values don't correlate to the encrypted SSNs (expected since encryption is opaque)
-- But there's no validation that SSN_LST4 is actually 4 digits
```

**Business Impact:**
The last-4 SSN is used for identity verification. If it doesn't match the actual SSN (which can't be verified since the master is encrypted), customer service representatives may deny legitimate borrowers access. The denormalized `BORR_SSN_LST4` in `CDW_LN_ACCT` could drift from the source of truth.

**Recommended Fix:**
Validate that `BORR_SSN_LST4` is exactly 4 digits. In the modern schema, drop this denormalized field and derive it from the canonical SSN record.
