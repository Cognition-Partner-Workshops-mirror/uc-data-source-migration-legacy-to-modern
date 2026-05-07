# Data Anomaly Report: Legacy CDW Tables

This report documents data quality anomalies found in the legacy Corporate Data Warehouse (CDW) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`).

---

## Summary

| # | Anomaly | Severity | Affected Table |
|---|---------|----------|----------------|
| 1 | Payment component amounts do not sum to total | Critical | CDW_PMT_HIST |
| 2 | SSN last-4 field contains phone number digits | Critical | CDW_LN_ACCT |
| 3 | Numeric string parsing has no error handling | Critical | All tables |
| 4 | String-based date sorting produces wrong order | High | CDW_PMT_HIST |
| 5 | No foreign key constraints — orphaned record risk | High | CDW_LN_ACCT, CDW_PMT_HIST |
| 6 | Delinquency days inconsistent with loan status | High | CDW_LN_ACCT |
| 7 | Null values in borrower fields | Medium | CDW_BORR_MSTR |
| 8 | Denormalized borrower data can drift from master | Medium | CDW_LN_ACCT |
| 9 | Status codes have no constraint validation | Medium | All tables |
| 10 | All dates stored as VARCHAR with no format validation | Low | All tables |

---

## ANO-001: Payment Component Amounts Do Not Sum to Total

**Severity:** Critical

**Affected Table/Columns:** `CDW_PMT_HIST` — `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`

**Description:** For several payment records, the sum of component amounts (principal + interest + escrow + late fee) does not equal the stated total payment amount.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT (Total) | Principal | Interest | Escrow | Late Fee | Computed Sum | Discrepancy |
|-------------|-----------------|-----------|----------|--------|----------|-------------|-------------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110003 | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | +47.50 |

**Business Impact:** Financial reporting and reconciliation will produce incorrect totals. Downstream systems that rely on component breakdown for tax reporting (interest vs. principal) or escrow analysis will have inconsistent data. Audit failures are likely.

**Recommended Fix:** Add a validation check at ingestion that verifies `principal + interest + escrow + late_fee == total`. Flag records that fail with a `NEEDS_REVIEW` status. For the existing bad records, determine which value is authoritative (the total or the components) and correct the other.

---

## ANO-002: SSN Last-4 Field Contains Phone Number Digits

**Severity:** Critical

**Affected Table/Columns:** `CDW_LN_ACCT` — `BORR_SSN_LST4`

**Description:** The `BORR_SSN_LST4` column, intended to hold the last 4 digits of the borrower's Social Security Number, instead contains the last 4 digits of the borrower's phone number. This affects all 5 loan account records.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | Borrower Phone (from CDW_BORR_MSTR) | Phone Last 4 |
|-------------|---------|---------------|--------------------------------------|--------------|
| LN-2019-00142 | B-10001 | 0142 | 217-555-0142 | 0142 |
| LN-2020-00398 | B-10002 | 0198 | 503-555-0198 | 0198 |
| LN-2018-00089 | B-10003 | 0167 | 512-555-0167 | 0167 |
| LN-2021-00567 | B-10004 | 0134 | 303-555-0134 | 0134 |
| LN-2017-00034 | B-10005 | 0156 | 602-555-0156 | 0156 |

All 5 records show a 100% match to phone last-4 and 0% match to any plausible SSN derivation.

**Business Impact:** Identity verification workflows that use SSN last-4 for customer authentication will match against wrong data. This is a potential compliance violation (data integrity for PII fields). Any migration that copies this field as SSN data propagates the error into the modern system.

**Recommended Fix:** Do not migrate `BORR_SSN_LST4` as-is. Flag it as unreliable. In the modern schema, derive SSN last-4 from `BORR_SSN_ENCR` (decrypted) in `CDW_BORR_MSTR` instead of trusting the denormalized copy. Add a cross-reference validation that checks this field against the master borrower record.

---

## ANO-003: Numeric String Parsing Has No Error Handling

**Severity:** Critical

**Affected Table/Columns:** All tables — every numeric column (`BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, etc.)

**Description:** All numeric values are stored as VARCHAR strings (e.g., `"285,000"`, `"4.750"`, `"745"`). The service layer parses these with `new BigDecimal(...)` and `Integer.parseInt(...)` without try-catch blocks. Any non-numeric value (e.g., `"N/A"`, `"$285,000"`, `"TBD"`, empty string with spaces, or locale-specific formatting like `"285.000,00"`) will cause an unhandled `NumberFormatException` that crashes the API endpoint.

**Example Risk Scenarios:**

| Field | Current Value | Risky Value That Could Appear | Result |
|-------|--------------|-------------------------------|--------|
| `BORR_CRDT_SCR` | `"745"` | `"N/A"` or `"PEND"` | `NumberFormatException` in `parseLegacyInteger()` |
| `LN_ORIG_AMT` | `"285,000"` | `"$285,000"` or `"285.000,00"` | `NumberFormatException` in `parseLegacyAmount()` |
| `LN_INT_RT` | `"4.750"` | `"4.750%"` or `"variable"` | `NumberFormatException` in `parseLegacyDecimal()` |
| `BORR_ANN_INCM` | `"92,500"` | `"SELF-REPORTED"` | `NumberFormatException` in `parseLegacyAmount()` |

**Business Impact:** A single bad record in any numeric field will cause a 500 Internal Server Error on the API, making the entire loan listing or borrower detail endpoint unavailable. Since legacy DW data is not controlled by this application, malformed values are a real risk.

**Recommended Fix:** Wrap all parsing methods with try-catch, log the parsing failure with the record ID and field name, and return a safe default (e.g., `BigDecimal.ZERO` or `null`) with a validation warning. Add a `DataValidationResult` that collects all anomalies found during ingestion.

---

## ANO-004: String-Based Date Sorting Produces Wrong Chronological Order

**Severity:** High

**Affected Table/Columns:** `CDW_PMT_HIST` — `PMT_DT` (and all date columns across tables)

**Description:** Dates are stored as `VARCHAR` in `MM/DD/YYYY` format. The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` applies a lexicographic sort on these strings. This sort works correctly only when comparing dates within the same month and year. Cross-month and cross-year comparisons produce incorrect ordering.

**Example:**
- `"12/01/2024"` sorts AFTER `"01/01/2025"` lexicographically (because `'1' > '0'`)
- Chronologically, January 2025 is AFTER December 2024
- Result: December 2024 payment appears before January 2025 in "most recent first" results

The current seed data happens to avoid this because all payments are from Nov-Dec 2025, but any historical data spanning year boundaries will be misordered.

**Business Impact:** Payment history displayed to customers or used for delinquency calculations will be in the wrong order. Automated systems that pick the "most recent payment" will select the wrong record.

**Recommended Fix:** Add a date-parsing step in the service layer that converts `MM/DD/YYYY` strings to `java.time.LocalDate` before any comparison or sorting. Alternatively, sort in-memory after parsing. For the modern schema migration, store dates as proper `DATE` type.

---

## ANO-005: No Foreign Key Constraints — Orphaned Record Risk

**Severity:** High

**Affected Table/Columns:**
- `CDW_LN_ACCT.BORR_ID` — no FK to `CDW_BORR_MSTR.BORR_ID`
- `CDW_LN_ACCT.PROD_CD` — no FK to `CDW_LN_PROD.PROD_CD`
- `CDW_PMT_HIST.LN_ACCT_NBR` — no FK to `CDW_LN_ACCT.LN_ACCT_NBR`

**Description:** The legacy schema explicitly has no foreign key constraints (noted in schema comments). This means:
- A loan account can reference a non-existent borrower ID
- A loan account can reference a non-existent product code
- A payment can reference a non-existent loan account

**Example Risk:** If borrower `B-10003` were deleted from `CDW_BORR_MSTR`, loan `LN-2018-00089` would still reference it. The `getBorrowerById` method would throw `RuntimeException("Borrower not found")` while the loan record still appears in `getAllLoans()` with stale borrower name data.

**Business Impact:** Data integrity cannot be guaranteed at the database level. The application code in `LoanService.getAllLoans()` silently handles missing products (`product != null ? ... : acct.getProductCode()`) but would produce confusing results. Orphaned payments would never appear in any loan's payment history.

**Recommended Fix:** Add referential integrity checks at the service layer during ingestion. Validate that every `BORR_ID` in `CDW_LN_ACCT` exists in `CDW_BORR_MSTR`, every `PROD_CD` exists in `CDW_LN_PROD`, and every `LN_ACCT_NBR` in `CDW_PMT_HIST` exists in `CDW_LN_ACCT`. Log orphaned records.

---

## ANO-006: Delinquency Days Inconsistent with Loan Status

**Severity:** High

**Affected Table/Columns:** `CDW_LN_ACCT` — `LN_DLQ_DAYS`, `LN_STAT_CD`

**Description:** Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). A loan that is 15 days past due should either have its status reflect the delinquency or the delinquency days should be zero for an active-in-good-standing loan.

**Example Bad Records:**

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Expected Behavior |
|-------------|-----------|-------------|-------------------|
| LN-2018-00089 | ACT | 15 | Status should be DLQ or DFT, or days should be 0 |

Additionally, the late payment for this loan (PMT-2025110003, received 11/18 for 11/01 due date, 17 days late) has a late fee of $47.50 — confirming actual delinquency despite the "Active" status.

**Business Impact:** Delinquency reporting and collection workflows will miss this loan. Regulatory reporting (e.g., HMDA, call reports) that uses status codes will undercount delinquent loans.

**Recommended Fix:** Add a cross-field validation rule: if `LN_DLQ_DAYS > 0`, flag a warning if `LN_STAT_CD` is `ACT`. Define business rules for automatic status transitions based on delinquency thresholds.

---

## ANO-007: Null Values in Borrower Fields

**Severity:** Medium

**Affected Table/Columns:** `CDW_BORR_MSTR` — `BORR_MID_INIT`, `BORR_ADDR_LN2`

**Description:** Several borrower records have NULL values in optional-but-important fields:

| BORR_ID | Field | Value |
|---------|-------|-------|
| B-10005 | BORR_MID_INIT | NULL |
| B-10002 | BORR_ADDR_LN2 | NULL |
| B-10003 | BORR_ADDR_LN2 | NULL |
| B-10005 | BORR_ADDR_LN2 | NULL |

While `BORR_ADDR_LN2` (apartment/suite number) is genuinely optional, `BORR_MID_INIT` being NULL affects the name formatting logic in `LoanService.toBorrowerDto()`, which uses a ternary to handle it. The schema declares no NOT NULL constraints on any column except the primary key.

**Business Impact:** Name formatting inconsistencies in customer-facing displays. More critically, NULL values in fields that downstream consumers expect to be populated (e.g., for name matching, identity verification) can cause matching failures. The service layer handles NULL middle initial correctly, but address line 2 NULL is not checked when building property addresses.

**Recommended Fix:** Define which fields are business-required vs. truly optional. Add NOT NULL validation for required fields during ingestion. For optional fields, ensure all downstream code handles NULL gracefully (the current `toBorrowerDto` does handle middle initial, but `toLoanSummary` concatenates property address without null checks).

---

## ANO-008: Denormalized Borrower Data Can Drift from Master

**Severity:** Medium

**Affected Table/Columns:** `CDW_LN_ACCT` — `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`

**Description:** The loan account table contains denormalized copies of borrower first name, last name, and SSN last-4. These are redundant with `CDW_BORR_MSTR` and can become stale if the master record is updated without propagating changes to the loan table.

**Example:**

| Source | BORR_ID | First Name | Last Name |
|--------|---------|------------|-----------|
| CDW_BORR_MSTR | B-10001 | James | Mitchell |
| CDW_LN_ACCT (LN-2019-00142) | B-10001 | James | Mitchell |

Currently the data is consistent, but with no trigger or application logic to sync updates, any name change (e.g., legal name change, typo correction) in the master would not reflect in loan records.

**Business Impact:** The API currently uses the denormalized name from `CDW_LN_ACCT` for loan summaries (via `acct.getBorrowerFirstName()`) rather than joining to the master. If names drift, the loan listing shows a different name than the borrower detail page.

**Recommended Fix:** In the service layer, always use the master `CDW_BORR_MSTR` name for display. Add a cross-reference validation that compares denormalized values against the master and flags discrepancies.

---

## ANO-009: Status Codes Have No Constraint Validation

**Severity:** Medium

**Affected Table/Columns:** All tables — `BORR_STAT_CD`, `LN_STAT_CD`, `PROD_STAT_CD`, `PMT_TYP_CD`, `PMT_STAT_CD`

**Description:** Status code columns are VARCHAR with no CHECK constraints or enum validation. The service layer's `expandStatusCode()`, `expandPropertyType()`, `expandPaymentType()`, and `expandPaymentStatus()` methods handle known codes but pass unknown codes through raw.

**Known Valid Codes:**
- Loan status: ACT, CLO, DFT, FRB
- Property type: SFR, CND, MFR, TWN
- Payment type: REG, EXT, PRT, PRE
- Payment status: PST, REV, NSF, PND
- Borrower status: ACT (only one observed)

Any unexpected code (e.g., `"XYZ"`, `"DEL"`, `""`) passes through unmodified to the API response.

**Business Impact:** API consumers receive inconsistent status values — sometimes expanded ("Active"), sometimes raw codes ("XYZ"). This breaks client-side logic that parses status strings.

**Recommended Fix:** Add validation at ingestion that checks status codes against an allowed set. Unknown codes should be flagged and mapped to a default or rejected.

---

## ANO-010: All Dates Stored as VARCHAR with No Format Validation

**Severity:** Low

**Affected Table/Columns:** All tables — every date column (`BORR_DOB_DT`, `BORR_CRET_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.)

**Description:** All date fields are `VARCHAR(10)` with an expected format of `MM/DD/YYYY`. There is no database-level validation that the stored value is actually a valid date. Values like `"02/30/2020"` (February 30th), `"13/01/2020"` (month 13), or `"PENDING"` would be accepted by the database.

The current seed data contains valid dates, but there is no guard against future inserts with invalid values.

**Business Impact:** Low immediate impact since current data is valid, but any invalid date would cause a parsing failure during migration to the modern `DATE`-typed schema. The application currently passes date strings through to the API without parsing, so bad dates would not cause runtime errors today — but would cause failures during migration.

**Recommended Fix:** Add date format validation during ingestion that attempts to parse each date string with `MM/DD/YYYY` format. Flag unparseable dates. Consider adding a database-level CHECK constraint or trigger if modifying the legacy schema is permitted.
