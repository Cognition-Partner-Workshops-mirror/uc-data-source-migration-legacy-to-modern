# Data Anomaly Report — Legacy CDW Tables

## Summary

Analysis of the legacy Corporate Data Warehouse (CDW) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`) reveals **7 distinct data quality anomalies** across 4 tables. These anomalies pose risks ranging from runtime exceptions to silent data corruption during the migration to the modern schema.

| # | Title | Severity | Table |
|---|-------|----------|-------|
| 1 | Payment Component Amounts Do Not Reconcile to Total | Critical | CDW_PMT_HIST |
| 2 | SSN Last-4 Populated from Phone Number | Critical | CDW_LN_ACCT |
| 3 | Numeric Amounts Stored as Strings with Embedded Commas | High | All tables |
| 4 | No Foreign Key Constraints — Orphan Risk | High | CDW_LN_ACCT, CDW_PMT_HIST |
| 5 | Dates Stored as Unvalidated VARCHAR Strings | Medium | All tables |
| 6 | No NOT NULL Constraints on Business-Required Fields | Medium | All tables |
| 7 | Denormalized Borrower Data Drift Risk | Low | CDW_LN_ACCT |

---

## Anomaly #1: Payment Component Amounts Do Not Reconcile to Total

**Severity:** Critical

**Affected Table:** `CDW_PMT_HIST`

**Affected Columns:** `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`

**Description:**
For certain payment records, the sum of component amounts (principal + interest + escrow + late fee) does not equal the total payment amount. This indicates either incorrect component allocation or an incorrect total.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT (Total) | Principal | Interest | Escrow | Late Fee | Computed Sum | Discrepancy |
|-------------|-----------------|-----------|----------|--------|----------|--------------|-------------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110003 | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | +47.50 |

**Business Impact:**
- Financial reporting and amortization schedules will be incorrect
- Loan balance calculations drift from reality over time
- Regulatory compliance risk — payment allocation must be auditable
- API consumers receive inconsistent financial data

**Recommended Fix:**
Add a reconciliation validator that checks `principal + interest + escrow + late_fee == total` at ingestion. Flag non-reconciling records for manual review. Apply a configurable tolerance threshold (e.g., $0.01 for rounding).

---

## Anomaly #2: SSN Last-4 Populated from Phone Number

**Severity:** Critical

**Affected Table:** `CDW_LN_ACCT`

**Affected Column:** `BORR_SSN_LST4`

**Description:**
All `BORR_SSN_LST4` values in the loan accounts table exactly match the last 4 digits of the borrower's phone number rather than the actual SSN. This indicates a systematic data loading error at the ETL source.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | Phone (from CDW_BORR_MSTR) | Match? |
|-------------|---------|---------------|----------------------------|--------|
| LN-2019-00142 | B-10001 | 0142 | 217-555-**0142** | Phone last 4 |
| LN-2020-00398 | B-10002 | 0198 | 503-555-**0198** | Phone last 4 |
| LN-2018-00089 | B-10003 | 0167 | 512-555-**0167** | Phone last 4 |
| LN-2021-00567 | B-10004 | 0134 | 303-555-**0134** | Phone last 4 |
| LN-2017-00034 | B-10005 | 0156 | 602-555-**0156** | Phone last 4 |

**Business Impact:**
- Identity verification using SSN last-4 will falsely pass/fail
- KYC/AML compliance violations — incorrect PII linkage
- Cross-system identity matching will produce wrong results
- Security risk if phone-derived data is treated as SSN for authentication

**Recommended Fix:**
Flag all `BORR_SSN_LST4` values as untrusted. During migration, derive SSN last-4 from the encrypted SSN field (`BORR_SSN_ENCR`) in `CDW_BORR_MSTR` rather than trusting the denormalized value. Add validation that SSN last-4 is numeric, exactly 4 digits, and does NOT match other known fields (phone, zip suffix).

---

## Anomaly #3: Numeric Amounts Stored as Strings with Embedded Commas

**Severity:** High

**Affected Tables:** `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`

**Affected Columns:** `BORR_ANN_INCM`, `BORR_CRDT_SCR`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PROD_TERM_MOS`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_DLQ_DAYS`, `LN_ESCROW_BAL`, `LN_LTV_PCT`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`

**Description:**
All numeric values (currency amounts, percentages, integers) are stored as VARCHAR with inconsistent formatting. Currency values use comma thousands separators (e.g., `"285,000"`, `"1,487.02"`). Credit scores, term months, and delinquency days are string-encoded integers. The service layer uses `BigDecimal(amount.replace(",", ""))` and `Integer.parseInt()` which will throw `NumberFormatException` on any unexpected characters.

**Example Values at Risk:**

| Column | Example Value | Expected Parse | Risk |
|--------|--------------|----------------|------|
| BORR_ANN_INCM | "92,500" | 92500.00 | "$92,500" would throw NFE |
| LN_CURR_BAL | "271,432.56" | 271432.56 | Spaces/currency symbols fatal |
| BORR_CRDT_SCR | "745" | 745 | "N/A" or blank would throw NFE |
| LN_DLQ_DAYS | "15" | 15 | "N/A" or "none" would throw NFE |
| LN_LTV_PCT | "82.5" | 82.5 | "82.5%" would throw NFE |

**Business Impact:**
- Unhandled `NumberFormatException` crashes the API for any loan containing malformed data
- A single bad record makes `getAllLoans()` return HTTP 500 for all users
- No graceful degradation — one corrupt record poisons the entire response

**Recommended Fix:**
Wrap all numeric parsing in try-catch with logging. Return a sensible default or null and flag the record. Add pre-parse validation regex: amounts must match `^-?\d{1,3}(,\d{3})*(\.\d+)?$`, integers must match `^\d+$`.

---

## Anomaly #4: No Foreign Key Constraints — Orphan Risk

**Severity:** High

**Affected Tables:** `CDW_LN_ACCT`, `CDW_PMT_HIST`

**Affected Columns:** `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR`

**Description:**
The legacy schema explicitly declares no foreign key constraints. Referential integrity is not enforced at the database level. Any `BORR_ID` in `CDW_LN_ACCT` could reference a non-existent borrower, any `PROD_CD` could be invalid, and any payment could reference a non-existent loan account.

**Current Data State:**
The seed data is currently consistent — all FK references resolve. However, in production CDW environments, orphaned records are a known issue due to:
- Batch ETL jobs that load child records before parent records
- Delete operations on parent tables without cascade
- Data warehouse refresh cycles that are not atomic

**Code Impact:**
In `LoanService.getAllLoans()`, if a `PROD_CD` doesn't exist in the products map, `products.get(acct.getProductCode())` returns null. The code handles this (`product != null ? ...`), but `getBorrowerById` would throw `RuntimeException` if a loan references a non-existent borrower.

**Business Impact:**
- NullPointerException when joining loan accounts to missing products or borrowers
- Incomplete data in API responses without any indication of data quality issues
- Migration would fail integrity checks when inserting into modern schema with real FKs

**Recommended Fix:**
Add referential integrity validation at the service layer. Before processing, verify all FK references resolve. Log warnings for orphaned records and exclude them from responses with a data quality flag.

---

## Anomaly #5: Dates Stored as Unvalidated VARCHAR Strings

**Severity:** Medium

**Affected Tables:** All tables

**Affected Columns:** `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`

**Description:**
All date fields are `VARCHAR(10)` with an expected format of `MM/DD/YYYY`. There is no database-level validation that the content is actually a valid date. The service layer passes date strings directly through to DTOs without parsing or validation.

**Risks:**
- Invalid dates like `"02/30/2020"` or `"13/01/2019"` would pass through undetected
- Alternate formats like `"2020-01-15"` (ISO) or `"15/03/1978"` (DD/MM/YYYY) would silently corrupt data during migration
- Future dates in historical fields (e.g., `BORR_DOB_DT` in the future) not caught
- The `column_mappings.md` specifies `Parse MM/DD/YYYY -> DATE` which would fail on any non-conforming value

**Business Impact:**
- Migration to modern DATE columns will fail with parse errors on malformed dates
- Date-based queries and reports produce incorrect results
- Temporal ordering (payment history) cannot be trusted

**Recommended Fix:**
Parse all date strings at ingestion time using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` with strict resolver. Log and flag records with unparseable dates. Add business rule validation (DOB must be in past, maturity date must be after origination date, etc.).

---

## Anomaly #6: No NOT NULL Constraints on Business-Required Fields

**Severity:** Medium

**Affected Tables:** All tables

**Affected Columns:** All non-PK columns

**Description:**
The legacy schema defines no `NOT NULL` constraints on any column except primary keys. Fields that are logically required for business operations (borrower name, loan amount, payment total, status codes) can be null. The service layer has limited null-handling — `parseLegacyAmount` handles null, but string concatenation in `toLoanSummary` (e.g., `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`) would produce `"null null"` for null names.

**Example Scenario:**
If `BORR_FST_NM` is null in `CDW_LN_ACCT`, the API returns `borrowerName: "null Mitchell"` — a string literal "null" concatenated with the last name.

**Business Impact:**
- API responses contain literal "null" strings confusing downstream consumers
- NullPointerExceptions in code paths that don't check for null
- Data quality degradation propagates silently through the system

**Recommended Fix:**
Add null-check validation for business-critical fields at service layer ingestion. Define required fields per entity: borrower must have first name, last name, and status; loan must have account number, borrower ID, product code, original amount, and status; payment must have loan account number, date, and total amount.

---

## Anomaly #7: Denormalized Borrower Data Drift Risk

**Severity:** Low

**Affected Table:** `CDW_LN_ACCT`

**Affected Columns:** `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`

**Description:**
The `CDW_LN_ACCT` table contains denormalized copies of borrower data (first name, last name, SSN last-4). These fields can drift from the authoritative values in `CDW_BORR_MSTR` if the borrower's name changes (e.g., marriage) but the loan account record is not updated.

**Current Data State:**
In the seed data, names are currently consistent between `CDW_LN_ACCT` and `CDW_BORR_MSTR`. However, this is a snapshot — production data commonly exhibits drift over time.

**Business Impact:**
- Conflicting name data between loan view and borrower view in the API
- Search/filter by name may miss records if only one copy is updated
- During migration, the question arises: which is the authoritative source?

**Recommended Fix:**
During migration, always prefer `CDW_BORR_MSTR` as the authoritative source for borrower attributes. Add a consistency check at ingestion that compares denormalized values against the master record and logs discrepancies.
