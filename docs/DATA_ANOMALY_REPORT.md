# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql`, `data-legacy.sql`, and the service layer code.

---

## ANO-001: All Columns Are VARCHAR — Numeric Values Stored as Strings

| Field | Detail |
|-------|--------|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_DLQ_DAYS`, `LN_ESCROW_BAL`, `LN_LTV_PCT`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`, `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT` |

**Description:** Every column in the legacy schema is `VARCHAR`. Monetary amounts, percentages, integers, and rates are all stored as strings. There is no database-level constraint preventing non-numeric values (e.g., `"N/A"`, `"TBD"`, `""`, `"$285,000"`) from being inserted.

**Example Bad Data Patterns (possible in production):**
- `BORR_CRDT_SCR` = `"N/A"` or `"PENDING"` → `Integer.parseInt()` throws `NumberFormatException`
- `LN_ORIG_AMT` = `"$285,000"` (dollar sign prefix) → `BigDecimal` constructor throws `NumberFormatException`
- `LN_INT_RT` = `""` (empty) → currently returns `BigDecimal.ZERO`, masking missing data
- `BORR_ANN_INCM` = `"92,500"` → comma format works with current parser, but `"92.500,00"` (European format) would fail

**Business Impact:** Any non-numeric value in these columns causes an unhandled `NumberFormatException` at runtime, returning a `500 Internal Server Error` to the API consumer. Financial calculations (LTV, payment amounts, balances) produce incorrect results if parsing silently falls back to zero.

**Recommended Fix:** Add validation/coercion in the service layer that catches `NumberFormatException`, logs the bad value, and either rejects the record or applies a safe sentinel value. Add `@Column` length constraints and consider CHECK constraints in the modern schema.

---

## ANO-002: Dates Stored as Strings with No Format Enforcement

| Field | Detail |
|-------|--------|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT` |

**Description:** All date columns are `VARCHAR(10)` with an implicit `MM/DD/YYYY` convention (per schema comments), but there is no enforcement. The service layer passes date strings through to DTOs without parsing them at all — `LoanSummaryDto.originationDate` and `PaymentDto.paymentDate` are raw strings from the database.

**Example Bad Data Patterns:**
- `BORR_DOB_DT` = `"1978-03-15"` (ISO format instead of MM/DD/YYYY)
- `LN_ORIG_DT` = `"02/15/19"` (2-digit year)
- `PMT_DT` = `"12/00/2025"` (invalid day)
- `LN_MAT_DT` = `NULL` or `""` (missing maturity date)

**Business Impact:** Date strings are passed directly to API consumers without validation. Downstream systems that parse these dates will break on inconsistent formats. The `column_mappings.md` specifies `MM/DD/YYYY → DATE` conversion, which will fail during migration if any row has a non-conforming format. The `findByLoanAccountNumberOrderByPaymentDateDesc` repository query sorts by string value of dates, not chronologically — `"02/01/2025"` sorts before `"11/01/2024"` lexicographically.

**Recommended Fix:** Parse all date strings to `LocalDate` in the service layer using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`, catching `DateTimeParseException`. Expose parsed dates (or ISO-8601 strings) in the API response.

---

## ANO-003: Payment Component Amounts Do Not Sum to Total

| Field | Detail |
|-------|--------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** For each payment, the total (`PMT_AMT`) should equal the sum of its components: principal + interest + escrow + late fee. Several seed data records violate this invariant.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN | INT | ESCROW | LATE_FEE | Computed Sum | Delta |
|-------------|---------|------|-----|--------|----------|--------------|-------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | **-400.00** |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | **-400.00** |
| PMT-2025120002 | 2,924.18 | 1,842.56 | 815.50 | 266.12 | 0.00 | 2,924.18 | 0.00 |
| PMT-2025110003 | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | **-47.50** |

**Business Impact:** Financial reporting and reconciliation are incorrect. The API returns these inconsistent amounts without validation, meaning downstream consumers may compute incorrect balances, generate inaccurate statements, or fail regulatory audits. For PMT-2025120001, the escrow portion (355.55) is suspiciously high for a payment that already sums to the total without it — likely a data entry error where escrow was double-counted.

**Recommended Fix:** Add a payment integrity check in the service layer that validates `total == principal + interest + escrow + lateFee`. Flag discrepancies in the API response or log a warning.

---

## ANO-004: No Foreign Key Constraints — Orphaned Records Possible

| Field | Detail |
|-------|--------|
| **Severity** | High |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema declares no foreign key constraints. `CDW_LN_ACCT.BORR_ID` has no FK to `CDW_BORR_MSTR.BORR_ID`; `CDW_LN_ACCT.PROD_CD` has no FK to `CDW_LN_PROD.PROD_CD`; `CDW_PMT_HIST.LN_ACCT_NBR` has no FK to `CDW_LN_ACCT.LN_ACCT_NBR`. This allows orphaned records.

**Example Bad Data Pattern:**
- A loan account with `BORR_ID = "B-99999"` (non-existent borrower)
- A payment with `LN_ACCT_NBR = "LN-DELETED"` (deleted loan)
- A loan with `PROD_CD = "LEGACY"` (discontinued product not in CDW_LN_PROD)

**Current Code Path:** In `LoanService.getAllLoans()`, the product lookup uses `products.get(acct.getProductCode())` which returns `null` for orphaned product codes. The `toLoanSummary` method handles this with a fallback: `product != null ? product.getDescription() : acct.getProductCode()`. However, `getBorrowerById` does NOT handle a missing borrower for attached loans — it will return loan summaries with `null` product descriptions silently.

**Business Impact:** Orphaned loan accounts appear in API responses with degraded data (raw product codes instead of descriptions). Orphaned payments cannot be reconciled to any loan. The `column_mappings.md` requires FK lookups (`"Lookup borrowers.id by external_id"`) which will fail for orphaned records during migration.

**Recommended Fix:** Add referential integrity validation in the service layer. When loading loan accounts, verify `BORR_ID` exists in borrower table and `PROD_CD` exists in product table. Log warnings for orphaned references.

---

## ANO-005: Denormalized Borrower Data in Loan Accounts — Inconsistency Risk

| Field | Detail |
|-------|--------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** `CDW_LN_ACCT` contains denormalized copies of borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) alongside the `BORR_ID` foreign key reference. These redundant fields can drift out of sync with `CDW_BORR_MSTR`.

**Example Bad Data Pattern:**
- `CDW_BORR_MSTR.BORR_FST_NM = "James"` but `CDW_LN_ACCT.BORR_FST_NM = "Jim"` (nickname vs. legal name)
- `CDW_BORR_MSTR.BORR_PH_NBR` last 4 = `"0142"` matches `CDW_LN_ACCT.BORR_SSN_LST4 = "0142"` — but the column claims to be SSN last 4, yet the seed data shows phone-number-derived values

**Seed Data Evidence:** For borrower B-10001 (James Mitchell), `BORR_SSN_LST4 = '0142'` in the loan account. Mitchell's phone is `'217-555-0142'` — the last 4 digits match the phone number, not an SSN. This is a data quality issue suggesting the SSN last 4 field was populated from the wrong source column.

**Business Impact:** The service uses denormalized `BORR_FST_NM`/`BORR_LST_NM` from the loan table (not the borrower master) when building `borrowerName` in `LoanSummaryDto`. If these fields diverge, the API returns inconsistent borrower names depending on which endpoint is called. The `BORR_SSN_LST4` mismatch is a potential identity verification failure.

**Recommended Fix:** Always resolve borrower details from the master table (`CDW_BORR_MSTR`) via `BORR_ID` lookup. Add a validation check that flags records where denormalized fields diverge from the master.

---

## ANO-006: NULL Values in Logically Required Fields

| Field | Detail |
|-------|--------|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2`, plus all nullable VARCHAR columns |

**Description:** The legacy schema defines only the `PRIMARY KEY` column as `NOT NULL`. All other columns are implicitly nullable — including fields that are logically required for business operations (e.g., `BORR_FST_NM`, `BORR_LST_NM`, `LN_ORIG_AMT`, `LN_STAT_CD`).

**Example Bad Records in Seed Data:**
- B-10005 (Robert Williams): `BORR_MID_INIT = NULL` — handled correctly by service layer
- B-10002, B-10003, B-10005: `BORR_ADDR_LN2 = NULL` — acceptable (address line 2 is optional)

**Potential Bad Data (allowed by schema):**
- `BORR_FST_NM = NULL` → `toBorrowerDto` builds name as `"null null"` (string concatenation of nulls)
- `LN_ORIG_AMT = NULL` → `parseLegacyAmount` returns `BigDecimal.ZERO`, silently masking a missing $285K loan amount as $0
- `LN_STAT_CD = NULL` → `expandStatusCode` returns `"Unknown"`, hiding the fact that status is missing

**Business Impact:** NULL first/last names produce garbled API responses. NULL amounts silently become zero, making loan balances and payment amounts incorrect. NULL status codes are expanded to "Unknown" without any error signal.

**Recommended Fix:** Define required fields and validate non-null at ingestion. For the current seed data, `BORR_MID_INIT` and `BORR_ADDR_LN2` NULLs are acceptable. For truly required fields (names, amounts, status), reject or flag records with NULL values.

---

## ANO-007: Monetary Amounts Contain Commas — Parsing Fragility

| Field | Detail |
|-------|--------|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`, `PROD_MIN_AMT`, `PROD_MAX_AMT` |

**Description:** Monetary values are stored as strings with US-locale comma thousands separators (e.g., `"285,000"`, `"1,487.02"`, `"92,500"`). The service layer strips commas with `amount.replace(",", "")` before parsing.

**Example Data:**
```
LN_ORIG_AMT = "285,000"      → parsed as 285000    (correct)
LN_CURR_BAL = "271,432.56"   → parsed as 271432.56 (correct)
BORR_ANN_INCM = "92,500"     → parsed as 92500     (correct)
```

**Failure Scenarios:**
- `"285.000,00"` (European format) → `replace(",","")` produces `"285.000.00"` → `NumberFormatException`
- `"$285,000"` (currency symbol) → `replace(",","")` produces `"$285000"` → `NumberFormatException`
- `"285,000.00 "` (trailing space) → `replace(",","")` + `BigDecimal` works for `parseLegacyAmount` but NOT for `parseLegacyDecimal` (which only trims, doesn't strip commas)

**Business Impact:** The current parsing works for the seed data but is fragile against real-world data warehouse content. The `parseLegacyDecimal` method (used for interest rate) does NOT strip commas — inconsistent with `parseLegacyAmount`. If an interest rate were stored as `"5,250"` (meaning 5.250% with a misplaced comma), it would be parsed as 5250%.

**Recommended Fix:** Normalize all numeric string parsing through a single robust method that handles commas, currency symbols, whitespace, and locale variations. Apply consistently to both `parseLegacyAmount` and `parseLegacyDecimal`.

---

## ANO-008: Inconsistent Parsing Between parseLegacyAmount and parseLegacyDecimal

| Field | Detail |
|-------|--------|
| **Severity** | Medium |
| **Affected Table** | Service layer (`LoanService.java`) |
| **Affected Columns** | `LN_INT_RT`, `LN_LTV_PCT` (via `parseLegacyDecimal`); all monetary columns (via `parseLegacyAmount`) |

**Description:** Two different parsing methods are used for numeric strings:
- `parseLegacyAmount(String)` — strips commas, then parses with `BigDecimal`
- `parseLegacyDecimal(String)` — trims whitespace only, does NOT strip commas

Yet `LN_INT_RT` and `LN_LTV_PCT` use the same `VARCHAR` type and could contain commas.

**Code Evidence:**
```java
// LoanService.java:152-155
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}

// LoanService.java:157-160
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());
}
```

**Business Impact:** If `LN_LTV_PCT` or `LN_INT_RT` ever contains a comma (e.g., `"1,000"` basis points), the parse will fail. The inconsistency also means the two methods return `BigDecimal.ZERO` for null/blank but via different paths — no logging or flagging occurs in either case.

**Recommended Fix:** Consolidate into a single parsing method that handles all numeric string variations.

---

## ANO-009: Credit Score Not Range-Validated

| Field | Detail |
|-------|--------|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_CRDT_SCR` |

**Description:** Credit scores are stored as `VARCHAR(5)` and parsed to `Integer` without range validation. Valid FICO scores range from 300–850, but the schema allows any string value.

**Example Seed Data:**
```
B-10001: "745" (valid)
B-10002: "780" (valid)
B-10003: "692" (valid)
B-10004: "810" (valid)
B-10005: "658" (valid)
```

**Potential Bad Data:**
- `"0"` or `"-1"` → parses successfully but is an invalid credit score
- `"9999"` → parses successfully, absurd value
- `"N/A"` → `NumberFormatException`

**Business Impact:** Invalid credit scores could affect downstream risk assessments, loan eligibility decisions, and regulatory reporting. The API currently returns the parsed integer without any validation.

**Recommended Fix:** Validate that parsed credit score falls within 300–850 range. Log a warning for out-of-range values and flag them in the API response.

---

## ANO-010: Status Codes Not Validated Against Known Values

| Field | Detail |
|-------|--------|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_STAT_CD`, `LN_STAT_CD`, `PMT_STAT_CD`, `PMT_TYP_CD`, `PROD_STAT_CD` |

**Description:** Status codes are abbreviations stored in `VARCHAR` columns. The service layer expands known codes via `switch` expressions but passes through unknown codes unchanged via the `default` branch. No warning is logged for unrecognized codes.

**Known Valid Codes:**
- Loan status: `ACT`, `CLO`, `DFT`, `FRB`
- Payment status: `PST`, `REV`, `NSF`, `PND`
- Payment type: `REG`, `EXT`, `PRT`, `PRE`

**Potential Bad Data:**
- `LN_STAT_CD = "XYZ"` → passed through as `"XYZ"` in the API response
- `PMT_STAT_CD = ""` → treated as non-null, falls through to `default`, returned as empty string
- `BORR_STAT_CD = "ACT"` → the borrower status code is never expanded anywhere in the code

**Business Impact:** Unknown status codes pass through silently, potentially confusing API consumers. The borrower status code (`BORR_STAT_CD`) is read into the entity but never used or exposed in the API, meaning borrower active/inactive status is lost.

**Recommended Fix:** Validate status codes against an enum of known values. Log warnings for unknown codes. Expose borrower status in the BorrowerDto.

---

## ANO-011: Delinquency Days Active on Apparently Current Loan

| Field | Detail |
|-------|--------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:** Loan account `LN-2018-00089` (borrower Torres) has `LN_DLQ_DAYS = "15"` but `LN_STAT_CD = "ACT"` (Active). Additionally, payment `PMT-2025110003` for this loan has a late fee of `$47.50` and was received 17 days after the payment due date (received 11/18 vs. due 11/01).

**Seed Data Evidence:**
```
LN-2018-00089: STAT_CD = "ACT", DLQ_DAYS = "15"
PMT-2025110003: PMT_DT = "11/01/2025", PMT_RECV_DT = "11/18/2025", PMT_LATE_FEE = "47.50"
```

**Business Impact:** A loan with 15 delinquency days that remains "Active" may be misrepresented in reporting. Depending on business rules, 15+ days delinquent should trigger a status change or at minimum a flag. The late fee on the November payment confirms the delinquency but this correlation is not validated in code.

**Recommended Fix:** Add business rule validation that checks consistency between delinquency days and loan status. Loans with `DLQ_DAYS > 0` and status `ACT` should be flagged.

---

## ANO-012: Loan-to-Value (LTV) Exceeds Reasonable Bounds

| Field | Detail |
|-------|--------|
| **Severity** | Low |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_LTV_PCT`, `LN_ORIG_AMT`, `PROP_APRS_VAL` |

**Description:** LTV percentages are stored as strings and not validated against the computed ratio of `LN_ORIG_AMT / PROP_APRS_VAL`.

**Seed Data Analysis:**

| Loan | Orig Amt | Appraised | Stated LTV | Computed LTV | Match? |
|------|----------|-----------|------------|--------------|--------|
| LN-2019-00142 | 285,000 | 345,000 | 82.5% | 82.6% | ~OK |
| LN-2020-00398 | 420,000 | 615,000 | 68.2% | 68.3% | ~OK |
| LN-2018-00089 | 195,000 | 260,000 | 75.0% | 75.0% | OK |
| LN-2021-00567 | 525,000 | 721,000 | 72.8% | 72.8% | OK |
| LN-2017-00034 | 165,000 | 206,000 | 80.0% | 80.1% | ~OK |

**Business Impact:** Current seed data is approximately correct (rounding differences only). However, without validation, a data entry error like `LTV = "825"` (missing decimal) would pass through as 825% — a nonsensical value that could affect risk calculations.

**Recommended Fix:** Validate LTV is within 0–200% range. Cross-check against computed `originalAmount / appraisedValue` ratio.

---

## ANO-013: Payment Date Sort Order Is Lexicographic, Not Chronological

| Field | Detail |
|-------|--------|
| **Severity** | Low |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Column** | `PMT_DT` |

**Description:** The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts `PMT_DT` as a string (VARCHAR), not as a date. MM/DD/YYYY format sorts lexicographically by month first, not chronologically.

**Example:** Sorting these dates descending as strings:
```
"12/01/2025" → comes first  (correct — December)
"11/01/2025" → comes second (correct — November)
"02/01/2025" → comes third
"01/15/2024" → comes fourth (WRONG — January 2024 should come after Feb 2025)
```

**Business Impact:** For the current seed data (all payments in Nov-Dec 2025), sorting happens to be correct. With a broader date range, the payment history API would return payments in wrong order, breaking chronological display.

**Recommended Fix:** Parse dates to `LocalDate` in the service layer and sort in Java, or migrate to proper `DATE` column types.

---

## ANO-014: Annual Income Not Exposed in API

| Field | Detail |
|-------|--------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_ANN_INCM` |

**Description:** The `BORR_ANN_INCM` field is read into the entity (`LegacyBorrower.annualIncome`) but never mapped to `BorrowerDto`. The income data exists in the database but is silently dropped during DTO conversion.

**Seed Data:**
```
B-10001: "92,500"
B-10002: "125,000"
B-10003: "78,000"
B-10004: "145,000"
B-10005: "65,000"
```

**Business Impact:** Annual income is critical for debt-to-income ratio calculations, loan eligibility assessments, and regulatory compliance. The API does not expose this field, so downstream consumers cannot access it.

**Recommended Fix:** Add `annualIncome` (as `BigDecimal`) to `BorrowerDto` and parse it in `toBorrowerDto` using `parseLegacyAmount`.

---

## ANO-015: SSN Last 4 Values Appear Derived from Phone Numbers

| Field | Detail |
|-------|--------|
| **Severity** | Low |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

**Description:** The `BORR_SSN_LST4` column in `CDW_LN_ACCT` claims to store the last 4 digits of the borrower's SSN. However, the seed data values match the last 4 digits of the borrower's phone number instead.

**Evidence:**

| Borrower | Phone | SSN Last 4 | Match? |
|----------|-------|------------|--------|
| B-10001 | 217-555-**0142** | **0142** | Phone match |
| B-10002 | 503-555-**0198** | **0198** | Phone match |
| B-10003 | 512-555-**0167** | **0167** | Phone match |
| B-10004 | 303-555-**0134** | **0134** | Phone match |
| B-10005 | 602-555-**0156** | **0156** | Phone match |

**Business Impact:** If production data has the same issue, this is a data integrity failure — identity verification using "SSN last 4" would actually be using phone number digits, providing no security value. This could be a PII mapping error in the original ETL process.

**Recommended Fix:** Investigate the ETL pipeline that populates `BORR_SSN_LST4`. Cross-reference against the encrypted SSN in `CDW_BORR_MSTR.BORR_SSN_ENCR` to verify correctness. The `column_mappings.md` correctly marks this field as "dropped" in the modern schema.

---

## Summary

| Severity | Count | Anomaly IDs |
|----------|-------|-------------|
| Critical | 3 | ANO-001, ANO-002, ANO-003 |
| High | 3 | ANO-004, ANO-005, ANO-006 |
| Medium | 5 | ANO-007, ANO-008, ANO-009, ANO-010, ANO-011 |
| Low | 4 | ANO-012, ANO-013, ANO-014, ANO-015 |
| **Total** | **15** | |
