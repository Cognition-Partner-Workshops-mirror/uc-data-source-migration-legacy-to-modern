# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## ANM-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** The sum of payment components (principal + interest + escrow + late fee) does not equal the total payment amount for multiple records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT (total) | Principal | Interest | Escrow | Late Fee | Computed Sum | Delta |
|-------------|-----------------|-----------|----------|--------|----------|-------------|-------|
| `PMT-2025120001` | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | **1,887.02** | **+400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | **1,887.02** | **+400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | **1,124.55** | **+47.50** |

**Business Impact:** Financial reporting and accounting are incorrect. Loan amortization schedules, P&L calculations, and regulatory reports (e.g., TILA disclosures) will contain inaccurate figures. Could trigger audit findings or compliance violations.

**Recommended Fix:** Add a validation rule at ingestion that asserts `principal + interest + escrow + late_fee == total`. Flag records that fail with a `DATA_QUALITY_WARNING` and log the discrepancy. Do not silently pass through mismatched totals to API consumers.

---

## ANM-002: Numeric Strings Without Type Safety

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_TERM_MOS`, `LN_PMT_AMT`, `LN_DLQ_DAYS`, `LN_LTV_PCT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`, `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT` |

**Description:** All numeric values (amounts, rates, scores, counts) are stored as `VARCHAR` strings. Amounts include commas (e.g., `"285,000"`, `"1,487.02"`). The schema imposes zero constraints on content, meaning non-numeric garbage (e.g., `"N/A"`, `"TBD"`, `""`, `"$100"`) can be inserted without error. The service layer's `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` will throw `NumberFormatException` on any malformed input.

**Example Bad Records (potential, given schema allows):**

| Scenario | Column | Value | Result |
|----------|--------|-------|--------|
| Dollar sign prefix | `LN_ORIG_AMT` | `$285,000` | `NumberFormatException` |
| Placeholder text | `BORR_CRDT_SCR` | `N/A` | `NumberFormatException` |
| Empty string | `LN_INT_RT` | `` | Returns `BigDecimal.ZERO` (silent data loss) |
| Whitespace-padded | `LN_DLQ_DAYS` | ` 15 ` | Works for `parseLegacyDecimal` (trims) but not `parseLegacyAmount` |

**Business Impact:** A single malformed record crashes the entire API endpoint (500 Internal Server Error). No partial results are returned — one bad row poisons the full response for `/api/loans`, `/api/borrowers`, or `/api/payments/loan/{id}`.

**Recommended Fix:** Wrap all parse operations with try-catch for `NumberFormatException`. Return sensible fallback defaults (e.g., `BigDecimal.ZERO` for amounts, `null` for credit scores) and log warnings. Add pre-parse validation (regex or pattern check) before conversion.

---

## ANM-003: Missing NOT NULL Constraints on Required Fields

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | All tables (`CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD`) |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_EMAIL_ADDR`, `BORR_STAT_CD`, `LN_STAT_CD`, `PROD_CD`, `BORR_ID` (in `CDW_LN_ACCT`), `LN_ACCT_NBR` (in `CDW_PMT_HIST`), etc. |

**Description:** Only primary key columns have implicit NOT NULL. All other columns — including business-critical fields like borrower name, loan status, and foreign key references — allow NULL. The code concatenates names without null checks: `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()` would produce `"null null"` if either field is NULL.

**Example Bad Records:**

| Record | Column | Value | Effect |
|--------|--------|-------|--------|
| `B-10005` | `BORR_MID_INIT` | `NULL` | Handled — code checks for null |
| (hypothetical) | `BORR_FST_NM` | `NULL` | `borrowerName` = `"null Mitchell"` |
| (hypothetical) | `LN_STAT_CD` | `NULL` | Status = `"Unknown"` (handled) |
| (hypothetical) | `BORR_ID` in `CDW_LN_ACCT` | `NULL` | Orphaned loan record, no borrower link |

**Business Impact:** NULL names produce garbled API output (`"null R. null"`). NULL foreign keys create orphaned records that cannot be joined. NULL status codes bypass business rules. NULL amounts default to zero, silently understating financial positions.

**Recommended Fix:** Validate that required fields are non-null at the service layer before mapping to DTOs. Reject or flag records with NULL in critical fields. Log data quality warnings for nullable-but-expected fields.

---

## ANM-004: Denormalized Borrower SSN Last-4 Matches Phone Last-4

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

**Description:** Every loan account's `BORR_SSN_LST4` is identical to the last 4 digits of the corresponding borrower's phone number. This is statistically impossible for real data (probability < 1 in 10^20 for all 5 records).

**Example Bad Records:**

| LN_ACCT_NBR | BORR_SSN_LST4 | Borrower Phone | Phone Last 4 |
|-------------|---------------|----------------|--------------|
| `LN-2019-00142` | `0142` | `217-555-0142` | `0142` |
| `LN-2020-00398` | `0198` | `503-555-0198` | `0198` |
| `LN-2018-00089` | `0167` | `512-555-0167` | `0167` |
| `LN-2021-00567` | `0134` | `303-555-0134` | `0134` |
| `LN-2017-00034` | `0156` | `602-555-0156` | `0156` |

**Business Impact:** If this pattern exists in production data, it indicates the SSN last-4 field was populated from phone number data during a data migration or ETL error. This is a PII integrity issue — the field labeled "SSN" does not contain SSN data. Downstream systems relying on SSN last-4 for identity verification, fraud checks, or compliance reporting would use incorrect data.

**Recommended Fix:** Add a cross-field validation that flags when SSN last-4 digits match phone last-4 digits. Implement an audit alert for this pattern. In the migration, consider dropping the denormalized SSN field entirely and referencing the encrypted SSN from the borrower master.

---

## ANM-005: Delinquency Days Inconsistent with Loan Status

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:** Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'` (Active). A loan with 15 days of delinquency should typically have a different status (e.g., past-due or watch). The corresponding payment `PMT-2025110003` confirms late payment: received 17 days after the due date with a $47.50 late fee.

**Example Bad Records:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| `LN-2018-00089` | `15` | `ACT` | Should be flagged/watch-listed |

**Business Impact:** Risk management systems relying on status codes would not flag this loan for collections or watchlist review. Delinquency reporting would undercount past-due loans. Regulatory reports (e.g., call reports, HMDA) could misclassify loan performance.

**Recommended Fix:** Add validation that cross-checks delinquency days against status code. If `delinquencyDays > 0` and status is `ACT`, flag as a data quality warning. Consider auto-adjusting status or at minimum surfacing the inconsistency in the API response.

---

## ANM-006: Date Strings Passed Through Without Parsing or Validation

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | All tables |
| **Affected Columns** | All `*_DT` columns (`BORR_DOB_DT`, `BORR_CRET_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.) |

**Description:** All dates are stored as `VARCHAR(10)` strings in `MM/DD/YYYY` format. The service layer passes date strings directly to DTOs without parsing or validating them (e.g., `dto.setOriginationDate(acct.getOriginationDate())`). Invalid dates like `"13/32/2025"` or `"00/00/0000"` would pass through to API consumers silently. The schema enforces no format constraint.

**Example Bad Records (potential, given schema allows):**

| Column | Value | Problem |
|--------|-------|---------|
| `BORR_DOB_DT` | `02/29/1978` | 1978 is not a leap year |
| `LN_ORIG_DT` | `2019-02-15` | Wrong format (ISO vs MM/DD/YYYY) |
| `PMT_DT` | `NULL` | No date at all |

**Business Impact:** Date-dependent business logic (age calculations, loan maturity, payment scheduling) would silently produce wrong results. API consumers expecting parseable date strings would fail downstream. Sorting by date would be lexicographic rather than chronological (e.g., `12/01/2025` sorts before `02/01/2026`).

**Recommended Fix:** Parse all date strings to `java.time.LocalDate` at the service layer using a strict `DateTimeFormatter` for `MM/dd/yyyy`. Catch `DateTimeParseException` and log warnings. Return ISO 8601 format (`yyyy-MM-dd`) in API responses.

---

## ANM-007: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema declares zero foreign key constraints. `CDW_LN_ACCT.BORR_ID` is not constrained to reference `CDW_BORR_MSTR.BORR_ID`. Similarly, `PROD_CD` and `LN_ACCT_NBR` have no referential integrity. Orphaned records (loans pointing to non-existent borrowers, payments pointing to non-existent loans) can exist without any database error.

**Example Bad Records (potential):**

| Table | Column | Value | Problem |
|-------|--------|-------|---------|
| `CDW_LN_ACCT` | `BORR_ID` | `B-99999` | No matching borrower |
| `CDW_LN_ACCT` | `PROD_CD` | `JUMBO` | No matching product |
| `CDW_PMT_HIST` | `LN_ACCT_NBR` | `LN-0000-00000` | No matching loan |

**Business Impact:** `LoanService.getAllLoans()` would produce a `NullPointerException` if a loan references a non-existent product code and the null-safe check were removed. Orphaned payments would not appear in loan payment histories. Orphaned loans would not appear in borrower detail views. Data migration to the modern schema (which uses actual FK constraints) would fail on these records.

**Recommended Fix:** Add referential integrity checks at the service layer. Before mapping a loan, verify the borrower and product exist. Before mapping a payment, verify the loan exists. Log orphaned records and exclude them from API responses with a warning.

---

## ANM-008: Denormalized Borrower Data Divergence Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** `CDW_LN_ACCT` embeds copies of borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) that are also present in `CDW_BORR_MSTR`. There is no mechanism to keep these synchronized. If a borrower's name is updated in the master table but not in the loan table, the two sources will diverge. The API uses the loan table's copy for `borrowerName` in `LoanSummaryDto` but the master table's copy for `BorrowerDto`.

**Example Bad Records (current data is consistent but risk exists):**

| LN_ACCT_NBR | BORR_FST_NM (loan) | BORR_FST_NM (master) | Match? |
|-------------|--------------------|--------------------|--------|
| `LN-2019-00142` | James | James | Yes |

**Business Impact:** A borrower name change (e.g., legal name change after marriage) would show different names in different API endpoints. Loan listings would show the old name while borrower detail would show the new name, confusing users and potentially causing compliance issues.

**Recommended Fix:** In the service layer, prefer the master borrower record's name over the denormalized copy. Add a validation check that flags when denormalized fields diverge from the master. In the modern schema migration, drop the denormalized fields entirely.

---

## ANM-009: Annual Income Not Exposed but Parsing Would Fail on Commas

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_ANN_INCM` |

**Description:** Annual income values contain commas (e.g., `"92,500"`, `"125,000"`). While `BorrowerDto` does not currently expose annual income, the column mappings specify this field should be migrated as `DECIMAL(12,2)`. Using `Integer.parseInt()` or `new BigDecimal()` directly on these values would fail. The existing `parseLegacyAmount()` handles commas, but `parseLegacyInteger()` does not — using the wrong parser would cause a crash.

**Example Bad Records:**

| BORR_ID | BORR_ANN_INCM | parseInt Result |
|---------|---------------|-----------------|
| `B-10001` | `92,500` | `NumberFormatException` |
| `B-10002` | `125,000` | `NumberFormatException` |

**Business Impact:** If annual income is added to the API or used in loan qualification calculations in the future, using the wrong parsing method would crash the endpoint. The comma-formatted string pattern is not obvious and easy to miss.

**Recommended Fix:** Ensure `parseLegacyAmount()` (which strips commas) is used for annual income rather than `parseLegacyInteger()`. Add a comment documenting the comma format. Add validation tests for comma-containing numeric strings.

---

## Summary

| ID | Title | Severity | Table(s) |
|----|-------|----------|----------|
| ANM-001 | Payment Component Sum Mismatch | Critical | `CDW_PMT_HIST` |
| ANM-002 | Numeric Strings Without Type Safety | Critical | All |
| ANM-003 | Missing NOT NULL Constraints on Required Fields | High | All |
| ANM-004 | Denormalized SSN Last-4 Matches Phone Last-4 | High | `CDW_LN_ACCT` |
| ANM-005 | Delinquency Days Inconsistent with Loan Status | High | `CDW_LN_ACCT` |
| ANM-006 | Date Strings Without Parsing or Validation | Medium | All |
| ANM-007 | No Foreign Key Constraints — Orphaned Record Risk | Medium | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| ANM-008 | Denormalized Borrower Data Divergence Risk | Medium | `CDW_LN_ACCT` |
| ANM-009 | Annual Income Comma Format Parsing Risk | Low | `CDW_BORR_MSTR` |
