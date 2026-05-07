# Legacy CDW Data Anomaly Report

> **Generated:** 2026-05-07
> **Data Source:** `src/main/resources/data-legacy.sql` / `src/main/resources/schema-legacy.sql`
> **Scope:** All four legacy tables — `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`

---

## Summary

| # | Anomaly | Severity | Table |
|---|---------|----------|-------|
| 1 | SSN Last-4 field contains phone digits | **Critical** | CDW_LN_ACCT |
| 2 | Payment component amounts do not sum to total | **Critical** | CDW_PMT_HIST |
| 3 | No error handling on numeric/date string parsing | **Critical** | Service Layer |
| 4 | Delinquency days contradict loan status | **High** | CDW_LN_ACCT |
| 5 | No foreign key constraints — orphan risk | **High** | All |
| 6 | Null fields cause broken string concatenation in API | **High** | CDW_BORR_MSTR / CDW_LN_ACCT |
| 7 | Dates exposed as raw unparsed strings | **Medium** | All |
| 8 | Escrow balance with zero escrow payments | **Medium** | CDW_LN_ACCT / CDW_PMT_HIST |
| 9 | Denormalized borrower data drift risk | **Low** | CDW_LN_ACCT |
| 10 | Unknown status codes silently pass through | **Low** | Service Layer |

---

## Anomaly Details

### ANO-001: SSN Last-4 Field Contains Phone Number Digits

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Table** | `CDW_LN_ACCT` |
| **Column** | `BORR_SSN_LST4` |

**Description:**
The `BORR_SSN_LST4` column is documented as the last four digits of the borrower's Social Security Number. However, every record in the seed data contains the last four digits of the borrower's **phone number** instead.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | Actual Phone (CDW_BORR_MSTR) | Phone Last 4 |
|-------------|---------|---------------|-------------------------------|--------------|
| LN-2019-00142 | B-10001 | 0142 | 217-555-**0142** | 0142 |
| LN-2020-00398 | B-10002 | 0198 | 503-555-**0198** | 0198 |
| LN-2018-00089 | B-10003 | 0167 | 512-555-**0167** | 0167 |
| LN-2021-00567 | B-10004 | 0134 | 303-555-**0134** | 0134 |
| LN-2017-00034 | B-10005 | 0156 | 602-555-**0156** | 0156 |

All five records match phone number suffixes, zero match expected SSN patterns.

**Business Impact:**
- Identity verification workflows that rely on SSN last-4 will match on the wrong value, potentially allowing unauthorized access.
- Regulatory compliance (KYC/AML) audits would flag this as a PII data integrity failure.
- Any downstream system consuming this field for borrower matching will produce incorrect results.

**Recommended Fix:**
- Immediately flag `BORR_SSN_LST4` as untrusted in all consuming systems.
- Back-fill the column from the authoritative SSN source (decrypt `BORR_SSN_ENCR` from `CDW_BORR_MSTR` and extract last 4).
- Add a cross-reference validation check during ingestion.

---

### ANO-002: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Table** | `CDW_PMT_HIST` |
| **Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:**
For loan `LN-2019-00142`, the sum of payment components (principal + interest + escrow + late fee) does not equal the reported total payment amount. The discrepancy is exactly **$400.00** on both payment records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN | INT | ESCROW | LATE_FEE | Computed Sum | Difference |
|-------------|---------|------|-----|--------|----------|-------------|------------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | **+400.00** |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | **+400.00** |

**Correctly balanced records for comparison:**

| PMT_SEQ_NBR | PMT_AMT | PRIN | INT | ESCROW | LATE_FEE | Computed Sum | Difference |
|-------------|---------|------|-----|--------|----------|-------------|------------|
| PMT-2025120002 | 2,924.18 | 1,842.56 | 815.50 | 266.12 | 0.00 | 2,924.18 | 0.00 |
| PMT-2025120004 | 2,468.35 | 857.23 | 1,611.12 | 0.00 | 0.00 | 2,468.35 | 0.00 |

The principal amount appears inflated — expected ~$56.78 (total minus interest minus escrow) but recorded as $456.78, suggesting a leading-digit data entry error.

**Business Impact:**
- Financial reconciliation reports will not balance, causing audit failures.
- Amortization schedules computed from these records will show incorrect principal paydown.
- Investor reporting for securitized loans would contain material misstatements.

**Recommended Fix:**
- Add a component-sum validation rule: `|PMT_AMT - (PRIN + INT + ESCROW + LATE_FEE)| < 0.01`.
- Quarantine records that fail the check and route them for manual correction.
- For LN-2019-00142: recalculate principal as `PMT_AMT - PMT_INT_AMT - PMT_ESCROW_AMT`.

---

### ANO-003: No Error Handling on Numeric/Date String Parsing

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Table** | Service Layer (`LoanService.java`) |
| **Columns** | All VARCHAR amount, rate, integer, and date columns |

**Description:**
The `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` methods in `LoanService.java` convert legacy VARCHAR fields to `BigDecimal`/`Integer` using `new BigDecimal(...)` and `Integer.parseInt(...)` with no try-catch. Any non-numeric content (e.g., `"N/A"`, `"$285,000"`, `"TBD"`, or empty-but-not-blank strings) will throw an unhandled `NumberFormatException`, resulting in a 500 Internal Server Error for the entire API response — even if only one record in the dataset is corrupt.

**Affected Parse Points:**
- `parseLegacyAmount()` — used for 12+ financial columns across 3 tables
- `parseLegacyDecimal()` — used for interest rate, LTV percent
- `parseLegacyInteger()` — used for credit score, term months, delinquency days

**Business Impact:**
- A single malformed record causes the entire `/api/loans` or `/api/borrowers` endpoint to return HTTP 500.
- No partial results — all valid records are lost alongside the bad one.
- No logging or alerting on which record/field caused the failure.

**Recommended Fix:**
- Wrap all parse methods in try-catch blocks with logging of the problematic value.
- Return a safe fallback (e.g., `BigDecimal.ZERO`, `null`, or a sentinel) for unparseable values.
- Add a `ValidationResult` structure to accumulate warnings per record.

---

### ANO-004: Delinquency Days Contradict Loan Status

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Table** | `CDW_LN_ACCT` |
| **Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:**
Loan `LN-2018-00089` (borrower Michael Torres) has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'` (Active). A loan with 15 days of delinquency should have a status reflecting that condition (e.g., delinquent or at minimum flagged). All other loans show 0 delinquency days with Active status.

Additionally, the payment history for this loan shows late payments:
- PMT-2025110003: due 11/01, received 11/18 (17 days late, $47.50 late fee charged)
- PMT-2025120003: due 12/01, received 12/05 (4 days late, no late fee)

**Example Bad Record:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| LN-2018-00089 | 15 | ACT | DLQ or FRB |

**Business Impact:**
- Risk dashboards that filter on status code will undercount delinquent loans.
- Regulatory delinquency reporting (e.g., HMDA, call reports) would be inaccurate.
- Collections workflows triggered by status code would miss this borrower.

**Recommended Fix:**
- Add a cross-field validation: if `LN_DLQ_DAYS > 0` then `LN_STAT_CD` must not be `ACT`.
- Define delinquency-status thresholds (e.g., 1-29 days → `DLQ`, 30-89 → `DFT`, 90+ → `FRB`).

---

### ANO-005: No Foreign Key Constraints — Orphan Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Table** | All tables |
| **Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:**
The legacy schema declares zero foreign key constraints. The following logical relationships are entirely unenforced:

| Child Table | Child Column | Parent Table | Parent Column |
|-------------|-------------|--------------|---------------|
| CDW_LN_ACCT | BORR_ID | CDW_BORR_MSTR | BORR_ID |
| CDW_LN_ACCT | PROD_CD | CDW_LN_PROD | PROD_CD |
| CDW_PMT_HIST | LN_ACCT_NBR | CDW_LN_ACCT | LN_ACCT_NBR |

In the current seed data, all references are valid. However, nothing prevents:
- A loan account referencing a non-existent borrower.
- A payment referencing a non-existent loan.
- A loan using a product code that doesn't exist in `CDW_LN_PROD`.

In `LoanService.getAllLoans()`, an invalid `PROD_CD` would cause `products.get(acct.getProductCode())` to return `null`, which is handled with a fallback — but `getLoanById()` uses `orElse(null)` for the product lookup and passes `null` into `toLoanSummary()`, where it is also handled. The borrower FK, however, has no validation at all.

**Business Impact:**
- Orphaned payments would be invisible in loan-level queries, causing incorrect balance calculations.
- A loan with a missing borrower would produce a broken API response with null borrower data.

**Recommended Fix:**
- Add referential integrity checks at the service layer during ingestion.
- Validate that every `BORR_ID` in loan accounts exists in the borrower table.
- Validate that every `LN_ACCT_NBR` in payments exists in the loan accounts table.

---

### ANO-006: Null Fields Cause Broken String Concatenation in API

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT` |
| **Columns** | `BORR_MID_INIT`, `BORR_FST_NM`, `BORR_LST_NM`, `PROP_ADDR_LN1`, `PROP_CTY_NM`, `PROP_ST_CD`, `PROP_ZIP_CD` |

**Description:**
`LoanService.toLoanSummary()` concatenates property address fields directly:
```java
acct.getPropertyAddress() + ", " + acct.getPropertyCity() + ", " + acct.getPropertyState() + " " + acct.getPropertyZip()
```
If any of these fields are null (allowed by the schema since no NOT NULL constraints exist), the API would return strings like `"null, Springfield, IL 62701"`.

Similarly, `borrowerName` is built from `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()` — a null first or last name would produce `"null Mitchell"`.

The `toBorrowerDto()` method handles `middleInitial` null correctly with a ternary check, but this pattern is not applied to other nullable fields.

**Example Risk Scenario:**
A borrower record with `BORR_FST_NM = NULL` would produce:
```json
{ "borrowerName": "null Mitchell", ... }
```

**Business Impact:**
- API consumers would display literal "null" strings to end users.
- Downstream systems parsing the address string would break on unexpected format.

**Recommended Fix:**
- Use null-safe concatenation with `Optional` or a helper method.
- Add NOT NULL validation at ingestion for required fields (first name, last name, address).

---

### ANO-007: Dates Exposed as Raw Unparsed Strings

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Table** | All tables |
| **Columns** | All `*_DT` columns |

**Description:**
All date columns are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. The service layer passes `originationDate` and `paymentDate` through to the DTO as raw strings without any parsing or format validation. The `column_mappings.md` documents that these should be converted to `DATE` types.

If any record contains a date in a different format (e.g., `2025-12-01`, `12-01-2025`, `31/12/2025`), the API response would contain mixed date formats with no indication of which format each value uses.

**Business Impact:**
- API consumers cannot reliably parse dates without format sniffing.
- Invalid dates (e.g., `02/30/2025`) would pass through undetected.
- Sorting by date string would produce incorrect ordering (`02/15/2019` sorts before `12/01/2025` alphabetically but after it chronologically).

**Recommended Fix:**
- Parse all date strings to `LocalDate` during translation with `DateTimeFormatter.ofPattern("MM/dd/yyyy")`.
- Return ISO-8601 format (`yyyy-MM-dd`) in API responses.
- Reject or flag records with unparseable dates.

---

### ANO-008: Escrow Balance Present but Zero Escrow in Payments

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Table** | `CDW_LN_ACCT` / `CDW_PMT_HIST` |
| **Columns** | `LN_ESCROW_BAL`, `PMT_ESCROW_AMT` |

**Description:**
Loan `LN-2018-00089` has an escrow balance of `$2,100.00`, yet both of its payment records show `PMT_ESCROW_AMT = '0.00'`. If no escrow is being collected in current payments, the escrow balance should be decreasing (disbursements) or static — not $2,100.

**Example:**

| LN_ACCT_NBR | LN_ESCROW_BAL | PMT (Dec) ESCROW | PMT (Nov) ESCROW |
|-------------|--------------|-----------------|-----------------|
| LN-2018-00089 | 2,100.00 | 0.00 | 0.00 |
| LN-2019-00142 | 3,245.80 | 355.55 | 355.55 |

**Business Impact:**
- Escrow analysis reports would show stale or incorrect balances.
- Borrower escrow statements would be inaccurate.

**Recommended Fix:**
- Add a consistency check: if `LN_ESCROW_BAL > 0`, recent payments should include non-zero escrow amounts (or an escrow disbursement record should exist).

---

### ANO-009: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Table** | `CDW_LN_ACCT` |
| **Columns** | `BORR_FST_NM`, `BORR_LST_NM` (denormalized copies) |

**Description:**
`CDW_LN_ACCT` carries denormalized copies of borrower first and last name. In the current seed data, these match the master records in `CDW_BORR_MSTR`. However, since there are no triggers or constraints synchronizing these copies, name changes in the master table (e.g., after a legal name change) would not propagate to the loan account records.

**Business Impact:**
- Loan documents could display stale borrower names.
- Search-by-name across loan accounts would miss renamed borrowers.

**Recommended Fix:**
- During migration, drop denormalized columns and use the borrower FK.
- Until migration: add a periodic reconciliation job comparing the denormalized fields to the master.

---

### ANO-010: Unknown Status Codes Silently Pass Through

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Table** | Service Layer |
| **Columns** | `LN_STAT_CD`, `PMT_STAT_CD`, `PMT_TYP_CD`, `PROP_TYP_CD` |

**Description:**
The `expandStatusCode()`, `expandPaymentType()`, `expandPaymentStatus()`, and `expandPropertyType()` methods all have a `default -> code` branch that silently returns the raw code for any unrecognized value. There is no logging, alerting, or validation.

If the legacy system introduces a new status code (e.g., `"BKR"` for bankruptcy), the API would return the raw abbreviation instead of a human-readable expansion, with no indication that an unmapped code was encountered.

**Business Impact:**
- API consumers would see cryptic codes without explanation.
- New codes added to the legacy system would go undetected until a user reports a problem.

**Recommended Fix:**
- Log a warning when an unknown code is encountered.
- Maintain an allow-list of valid codes and reject records with codes outside the list.
