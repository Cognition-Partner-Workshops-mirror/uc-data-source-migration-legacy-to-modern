# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql`, `data-legacy.sql`, `LoanService.java`,
> the repository layer, and `data/mappings/column_mappings.md`.

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High | 4 |
| Medium | 3 |
| Low | 2 |
| **Total** | **12** |

---

## ANO-001: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** The sum of principal + interest + escrow + late-fee components does not equal the stated total payment amount for multiple records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN+INT+ESCROW+LATE | Difference |
|-------------|---------|----------------------|------------|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | **+$400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | **+$400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | **+$47.50** |

**Business Impact:** Financial reporting, balance reconciliation, and investor remittance calculations will be incorrect. Downstream systems that rely on payment breakdowns will show inconsistent totals. Regulatory reporting (HMDA, call reports) could contain material misstatements.

**Recommended Fix:** Add a validation check at ingestion that verifies `principal + interest + escrow + late_fee == total`. Flag mismatched records for manual review and log a warning. Do not silently propagate mismatched amounts to the API.

---

## ANO-002: SSN Last-4 Digits Contain Phone Number Suffixes Instead of Actual SSN

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

**Description:** Every loan account's `BORR_SSN_LST4` matches the last 4 digits of the corresponding borrower's phone number, not their Social Security Number.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_SSN_LST4 | Borrower Phone | Match? |
|-------------|---------------|----------------|--------|
| `LN-2019-00142` | `0142` | 217-555-**0142** | Phone suffix |
| `LN-2020-00398` | `0198` | 503-555-**0198** | Phone suffix |
| `LN-2018-00089` | `0167` | 512-555-**0167** | Phone suffix |
| `LN-2021-00567` | `0134` | 303-555-**0134** | Phone suffix |
| `LN-2017-00034` | `0156` | 602-555-**0156** | Phone suffix |

**Business Impact:** Identity verification during servicing calls would use wrong data. KYC/AML compliance checks that rely on SSN last-4 are compromised. If this field is ever exposed in an API response, it would appear to be PII but is actually incorrect, creating both a compliance risk and a false sense of security.

**Recommended Fix:** Flag this column as untrusted in the data model. Do not use it for identity verification. During migration, either re-derive from the encrypted SSN field (`BORR_SSN_ENCR`) or mark as null/unknown.

---

## ANO-003: Numeric String Parsing Has No Error Handling — Malformed Data Causes 500 Errors

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | All tables |
| **Affected Columns** | All VARCHAR columns mapped to numeric types (amounts, rates, scores, days, percentages) |

**Description:** `LoanService.parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` call `new BigDecimal(...)` or `Integer.parseInt(...)` directly. If any legacy VARCHAR field contains non-numeric characters (e.g., `"N/A"`, `"$285,000"`, `"---"`, `"TBD"`, empty whitespace strings), these methods throw an uncaught `NumberFormatException`, resulting in a 500 Internal Server Error with a stack trace leak.

**Example Vulnerable Paths:**
- `GET /api/loans` → `parseLegacyAmount(acct.getOriginalAmount())` — if `LN_ORIG_AMT` = `"$285,000"`
- `GET /api/borrowers/{id}` → `parseLegacyInteger(borrower.getCreditScore())` — if `BORR_CRDT_SCR` = `"N/A"`
- `GET /api/loans/{id}/payments` → `parseLegacyAmount(pmt.getTotalAmount())` — if `PMT_AMT` = `"PENDING"`

**Business Impact:** A single malformed record poisons the entire list endpoint (one bad row → 500 for all rows). No graceful degradation — the API becomes unavailable until the data is manually fixed. Stack traces may leak internal class names and field mappings.

**Recommended Fix:** Wrap all parsing methods in try-catch blocks. Return a sensible default (BigDecimal.ZERO / null) on parse failure and log a warning with the record identifier and raw value for investigation.

---

## ANO-004: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ID`, `PROD_CD`, `LN_ACCT_NBR` |

**Description:** The legacy schema declares no foreign key constraints between tables:
- `CDW_LN_ACCT.BORR_ID` → no FK to `CDW_BORR_MSTR.BORR_ID`
- `CDW_LN_ACCT.PROD_CD` → no FK to `CDW_LN_PROD.PROD_CD`
- `CDW_PMT_HIST.LN_ACCT_NBR` → no FK to `CDW_LN_ACCT.LN_ACCT_NBR`

**Example Risk Scenario:** A loan account could reference `BORR_ID = 'B-99999'` which doesn't exist in `CDW_BORR_MSTR`. In `LoanService.getAllLoans()`, `products.get(acct.getProductCode())` would return `null` for an invalid product code — currently handled by falling back to the raw code, but `getBorrowerById()` would fail silently with missing loan data.

**Business Impact:** Orphaned loan accounts would appear in API responses but lack borrower details. Orphaned payments could inflate or deflate loan payment history. Data integrity issues would be invisible until a downstream consumer fails.

**Recommended Fix:** Add referential integrity checks at ingestion time. Validate that every `BORR_ID`, `PROD_CD`, and `LN_ACCT_NBR` reference resolves to an existing parent record before processing.

---

## ANO-005: Delinquency Status Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:** Loan `LN-2018-00089` (Michael Torres) has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'`. A loan 15 days past due should not be in "Active" status — it should be flagged as delinquent or at minimum have a warning indicator.

**Example Bad Record:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| `LN-2018-00089` | 15 | ACT | DLQ or flagged |

**Business Impact:** Delinquent loans reported as "Active" in the API misrepresent portfolio risk. Collection workflows would not be triggered. Regulatory delinquency reporting (30/60/90 day buckets) could be understated.

**Recommended Fix:** Add cross-field validation: if `delinquencyDays > 0`, the status should not be "ACT" without a flag. Log a warning and include a `delinquencyWarning` field in the API response.

---

## ANO-006: Denormalized Borrower Data May Diverge from Master

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** `CDW_LN_ACCT` contains denormalized copies of borrower first name, last name, and SSN last-4. Without FK constraints, these can drift from `CDW_BORR_MSTR`. The service uses the denormalized copies (line 106: `acct.getBorrowerFirstName()`) for the loan summary rather than joining to the master.

**Current Data Status:** In the seed data, names match between tables. However, the architecture allows silent divergence.

**Business Impact:** If a borrower updates their name (e.g., marriage), the loan summary would show the old name while the borrower profile shows the new name. Customer-facing statements and correspondence would be inconsistent.

**Recommended Fix:** In the service layer, prefer the master table (`CDW_BORR_MSTR`) for borrower identity fields. Add a validation check comparing denormalized fields to master on ingestion and flag divergences.

---

## ANO-007: Payment Date Sorting on VARCHAR Produces Wrong Order Across Years

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Column** | `PMT_DT` |

**Description:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` sorts by `PMT_DT` which is a `VARCHAR(10)` in `MM/DD/YYYY` format. Lexicographic string sorting of this format is incorrect across year boundaries:
- `"01/15/2026"` < `"12/01/2025"` lexicographically (because `"0" < "1"`)
- But chronologically `01/15/2026` is AFTER `12/01/2025`

**Example:** If a loan has payments in both Dec 2025 and Jan 2026, the API would return them in the wrong chronological order.

**Business Impact:** Payment history displayed out of order. Amortization schedule calculations based on "most recent payment" would pick the wrong record. Running balance computations would be incorrect.

**Recommended Fix:** Parse dates to a proper `DATE`/`LocalDate` type in the service layer and sort in-memory, or use a native SQL query with `CAST`/`STR_TO_DATE` to sort correctly.

---

## ANO-008: Date Strings Not Validated or Parsed — Invalid Dates Pass Through Silently

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All `*_DT` columns (`BORR_DOB_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.) |

**Description:** All date fields are `VARCHAR(10)` storing `MM/DD/YYYY` strings. The service layer passes these strings directly to DTOs without parsing or validation. Values like `"02/30/2020"` (Feb 30), `"13/01/2020"` (month 13), `"00/00/0000"`, or `"TBD"` would be accepted and returned to API consumers as-is.

The `column_mappings.md` documents that all date fields must be parsed to `DATE` or `TIMESTAMP` during migration, but the current service performs no date validation.

**Business Impact:** Invalid dates corrupt downstream date-based calculations (age computation, loan maturity, payment schedules). API consumers that parse dates would fail on their end.

**Recommended Fix:** Parse all date strings to `LocalDate` using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` with error handling. Return null/default for unparseable dates and log warnings.

---

## ANO-009: Annual Income Strings with Commas — Inconsistent Format Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_ANN_INCM` |

**Description:** Annual income values contain commas (`"92,500"`, `"125,000"`, etc.). While `parseLegacyAmount()` strips commas, the method is currently only used for loan/payment amounts — annual income is **never parsed** in the service layer (it's not included in `BorrowerDto`). During migration, this field needs comma-stripping per `column_mappings.md`, but there's no validation that values are purely numeric after comma removal.

**Example Risk Values:** `"$92,500"`, `"92.5K"`, `"N/A"`, `"not disclosed"` would all be plausible legacy entries that would fail numeric parsing.

**Business Impact:** Debt-to-income ratio calculations during migration would fail on malformed income values. Underwriting decisions based on this field could be wrong.

**Recommended Fix:** Include annual income in the borrower DTO with proper parsing and validation. Apply the same defensive parsing used for amounts.

---

## ANO-010: Late Fee Not Reflected in Payment Total

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_LATE_FEE` |

**Description:** Payment `PMT-2025110003` has a late fee of `$47.50`, but the total `PMT_AMT` = `$1,077.05` equals only principal + interest (295.82 + 781.23 = 1,077.05). The late fee is recorded separately but not reflected in the total. This is either a data entry error or an undocumented business rule that late fees are billed separately.

**Business Impact:** If late fees are meant to be part of the total, revenue reporting understates collections by $47.50 per occurrence. If late fees are separate, API consumers have no way to know this from the data alone.

**Recommended Fix:** Document the business rule for late fee inclusion. Add a `computedTotal` field to the payment DTO that always sums components, alongside the legacy `statedTotal` for comparison.

---

## ANO-011: Credit Score Stored as VARCHAR — No Range Validation

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_CRDT_SCR` |

**Description:** Credit scores are stored as `VARCHAR(5)`. Current values (`"745"`, `"780"`, `"692"`, `"810"`, `"658"`) are valid FICO range (300-850), but there's no constraint preventing values like `"999"`, `"-1"`, `"ABC"`, or `"0"`. The `parseLegacyInteger()` method would return these as integers without range checking.

**Business Impact:** Out-of-range credit scores would distort risk analytics and pricing models. A credit score of `0` or `999` passed through to downstream systems could trigger incorrect loan pricing.

**Recommended Fix:** After parsing to integer, validate that the score falls within 300–850 (FICO range). Flag out-of-range values.

---

## ANO-012: Null Middle Initial Handled but Other Nullable Fields Are Not Guarded

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2`, and potentially any column |

**Description:** The service handles null `middleInitial` (line 123) but does not guard against null values in other fields used in string concatenation. For example, `toBorrowerDto()` calls `borrower.getFirstName()` and `borrower.getLastName()` without null checks. If either is null, the full name would contain `"null"` as a literal string.

Similarly, `toLoanSummary()` concatenates property address fields (line 114) without null checks — a null city or state would produce `"742 Elm Street, null, null 62701"`.

**Business Impact:** API responses would contain literal `"null"` strings in customer-facing name and address fields. While not a data loss issue, it degrades API quality and customer experience.

**Recommended Fix:** Add null-safe string handling for all fields used in concatenation. Use empty string defaults for null values.
