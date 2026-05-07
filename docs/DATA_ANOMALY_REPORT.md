# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## ANO-001: Payment Component Arithmetic Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:**
The sum of payment components (principal + interest + escrow + late fee) does not equal the total payment amount for multiple records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN + INT + ESCROW + LATE | Difference |
|---|---|---|---|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | **+47.50** |

Both payments for loan `LN-2019-00142` are consistently off by exactly $400.00. Payment `PMT-2025110003` is off by exactly the late fee amount ($47.50), suggesting the late fee was added to components but not the total.

**Business Impact:**
Financial reconciliation will fail. Downstream systems consuming the API will compute incorrect principal/interest breakdowns. Regulatory reporting (TILA, RESPA) requires accurate payment allocations.

**Recommended Fix:**
Add a payment component validation that checks `|total - (principal + interest + escrow + late_fee)| < 0.01`. Flag mismatches with a warning and use the component sum as the authoritative total, or reject the record.

---

## ANO-002: SSN Last-4 Digits Derived from Phone Number

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

**Description:**
Every borrower's `BORR_SSN_LST4` value in the loan account table exactly matches the last 4 digits of the borrower's phone number from `CDW_BORR_MSTR`, indicating the field was populated from the wrong source column.

**Example Bad Records:**

| BORR_ID | Phone (CDW_BORR_MSTR) | SSN_LST4 (CDW_LN_ACCT) | Match? |
|---|---|---|---|
| B-10001 | 217-555-**0142** | **0142** | Phone last-4 |
| B-10002 | 503-555-**0198** | **0198** | Phone last-4 |
| B-10003 | 512-555-**0167** | **0167** | Phone last-4 |
| B-10004 | 303-555-**0134** | **0134** | Phone last-4 |
| B-10005 | 602-555-**0156** | **0156** | Phone last-4 |

100% of records exhibit this pattern.

**Business Impact:**
SSN last-4 is used for borrower identity verification. Incorrect values could cause identity verification failures, loan servicing errors, and potential compliance violations (GLBA, FCRA). Any downstream system relying on SSN last-4 for matching or deduplication will produce incorrect results.

**Recommended Fix:**
Flag all `BORR_SSN_LST4` values as unreliable. Do not use this field for identity verification until cross-referenced with the authoritative SSN source. Add validation that SSN last-4 does not match the phone number suffix.

---

## ANO-003: Unguarded Numeric String Parsing

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | All legacy tables |
| **Affected Columns** | All VARCHAR columns storing numeric values: `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, etc. |

**Description:**
All numeric and financial values are stored as VARCHAR strings (e.g., `"285,000"`, `"4.750"`, `"745"`). The service layer parses these with `BigDecimal(String)` and `Integer.parseInt()` without try-catch blocks. Any unexpected character (dollar signs, spaces, letters, double commas) will cause an unhandled `NumberFormatException` that propagates as a 500 error to API consumers.

**Example Risk Scenarios:**

| Input Value | Parser | Result |
|---|---|---|
| `"$285,000"` | `parseLegacyAmount` | `NumberFormatException` — dollar sign not stripped |
| `"92 500"` | `parseLegacyAmount` | `NumberFormatException` — space not stripped |
| `"N/A"` | `parseLegacyInteger` | `NumberFormatException` — not a number |
| `"1,,487.02"` | `parseLegacyAmount` | `NumberFormatException` — double comma |
| `""` (empty) | `parseLegacyInteger` | Returns `null` (handled) |

**Business Impact:**
A single malformed record in the legacy CDW will cause the entire `/api/loans` or `/api/borrowers` endpoint to return a 500 error, taking down the API for all consumers. There is no graceful degradation.

**Recommended Fix:**
Wrap all parsing in try-catch with fallback defaults. Log warnings for unparseable values. Return `BigDecimal.ZERO` or `null` for amounts, and `null` for integers, rather than crashing.

---

## ANO-004: Null Values in Logically Required Fields

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

**Description:**
Multiple borrower records have NULL values in fields that, while technically nullable in the schema, cause issues when consumed without null-guards.

**Example Bad Records:**

| BORR_ID | BORR_MID_INIT | BORR_ADDR_LN2 |
|---|---|---|
| B-10002 | `L` | `NULL` |
| B-10003 | `A` | `NULL` |
| B-10005 | `NULL` | `NULL` |

`BORR_MID_INIT` is NULL for B-10005 (Robert Williams). While the `toBorrowerDto` method handles this with a ternary, the schema has no NOT NULL constraints on `BORR_FST_NM` or `BORR_LST_NM` either, meaning a future record with a null first/last name would produce `"null Williams"` or `"James null"` in the API response.

**Business Impact:**
Null borrower names would appear as the literal string "null" in customer-facing communications, loan documents, and reports. This is a reputational risk and potential regulatory issue.

**Recommended Fix:**
Add null-checks before string concatenation in `toBorrowerDto` and `toLoanSummary`. Use `Optional` or default values like `"[Unknown]"` for missing required name fields. Add NOT NULL validation at the service layer.

---

## ANO-005: Delinquency Days vs. Status Code Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:**
Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). A loan with 15+ days of delinquency should be flagged with a delinquent or at-risk status.

**Example Bad Records:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|---|---|---|---|
| LN-2018-00089 | 15 | ACT | DLQ or at minimum a warning flag |

Additionally, the payment history for this loan shows late receipts:
- `PMT-2025120003`: due 12/01, received 12/05 (4 days late)
- `PMT-2025110003`: due 11/01, received 11/18 (17 days late, with $47.50 late fee)

**Business Impact:**
Delinquent loans appearing as "Active" in the API response mislead loan officers and risk management systems. Collections processes may not be triggered. Regulatory reports (call reports, HMDA) would misrepresent portfolio risk.

**Recommended Fix:**
Add cross-field validation: if `delinquencyDays > 0`, status should not be plain "Active". Either auto-correct the status or append a delinquency warning to the API response.

---

## ANO-006: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:**
The legacy schema explicitly has no foreign key constraints (noted in schema comments: "No foreign key constraints"). This means:
- A loan account can reference a non-existent borrower ID
- A loan account can reference a non-existent product code
- A payment can reference a non-existent loan account number

In the current seed data, all references happen to be valid. However, the service layer performs lookups (e.g., `products.get(acct.getProductCode())`) that return `null` for missing references, which is only partially handled.

**Example Risk:**
In `LoanService.getAllLoans()`, if `acct.getProductCode()` references a non-existent product, `products.get()` returns `null`. The `toLoanSummary` method handles this by falling back to the raw product code, but `getLoanById()` uses `findById` which could also return null with only `orElse(null)`.

**Business Impact:**
Orphaned records cause silent data loss — loans without valid borrowers appear with incomplete data. Payments without valid loans are invisible to the servicing system.

**Recommended Fix:**
Add referential integrity validation at the service layer: verify `BORR_ID` exists in borrowers, `PROD_CD` exists in products, and `LN_ACCT_NBR` exists in loan accounts before processing. Log and flag orphaned records.

---

## ANO-007: Denormalized Borrower Data Drift

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM` (duplicated from `CDW_BORR_MSTR`) |

**Description:**
The loan account table contains denormalized copies of borrower first/last name. If the borrower master record is updated (e.g., name change after marriage), the loan account table retains the old name. There is no mechanism to keep them in sync.

Currently, the `toLoanSummary` method reads borrower name from the loan account table (denormalized copy), while `toBorrowerDto` reads from the borrower master. This means the same borrower could appear with different names in different API responses.

**Example:**
- `/api/borrowers/B-10001` → uses `CDW_BORR_MSTR.BORR_FST_NM` = "James"
- `/api/loans/LN-2019-00142` → uses `CDW_LN_ACCT.BORR_FST_NM` = "James" (currently matches, but will diverge on update)

**Business Impact:**
Inconsistent borrower names across API endpoints confuse downstream systems and violate single-source-of-truth principles.

**Recommended Fix:**
Always resolve borrower names from the master table (`CDW_BORR_MSTR`) rather than using denormalized copies. Add validation to detect and log name mismatches.

---

## ANO-008: Date Strings Passed Through Without Validation

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All `VARCHAR(10)` date columns: `BORR_DOB_DT`, `LN_ORIG_DT`, `PMT_DT`, etc. |

**Description:**
All dates are stored as `MM/DD/YYYY` VARCHAR strings. The service layer passes date strings directly to DTOs without parsing or validating them (e.g., `dto.setOriginationDate(acct.getOriginationDate())`). If a record contains a differently formatted date (e.g., `2025-01-15`, `15/01/2025`, or `01-15-2025`), it passes through undetected.

Additionally, the `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc` relies on string-based sorting of `PMT_DT`, which produces incorrect chronological ordering for `MM/DD/YYYY` format (e.g., `12/01/2025` sorts after `11/15/2025` by luck, but `02/01/2026` would sort before `11/15/2025`).

**Business Impact:**
API consumers receive inconsistently formatted dates. String-based date sorting produces incorrect payment history ordering. Date comparisons and calculations downstream will fail silently.

**Recommended Fix:**
Parse all date strings into `LocalDate` using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` at ingestion time. Return ISO-8601 formatted dates (`yyyy-MM-dd`) in API responses. Catch and log `DateTimeParseException` for malformed dates.

---

## ANO-009: LTV Percentage Calculation Discrepancies

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_LTV_PCT`, `LN_ORIG_AMT`, `PROP_APRS_VAL` |

**Description:**
The Loan-to-Value (LTV) percentage stored in the data does not always match the calculated value from `LN_ORIG_AMT / PROP_APRS_VAL * 100`.

| LN_ACCT_NBR | Stored LTV | Calculated LTV | Difference |
|---|---|---|---|
| LN-2019-00142 | 82.5 | 82.61% (285000/345000) | -0.11% |
| LN-2020-00398 | 68.2 | 68.29% (420000/615000) | -0.09% |
| LN-2017-00034 | 80.0 | 80.10% (165000/206000) | -0.10% |

**Business Impact:**
LTV is a critical underwriting metric. Inaccurate LTV values could affect risk classification, mortgage insurance requirements (LTV > 80% typically requires PMI), and investor reporting.

**Recommended Fix:**
Add validation that recalculates LTV from the source values and flags discrepancies exceeding a threshold (e.g., 0.5%). Log warnings for minor rounding differences.

---

## ANO-010: Null-Unsafe String Concatenation in Property Address

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `PROP_ADDR_LN1`, `PROP_CTY_NM`, `PROP_ST_CD`, `PROP_ZIP_CD` |

**Description:**
The `toLoanSummary` method concatenates property address fields without null checks:
```java
dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
    + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
```
If any field is NULL, the API returns a string like `"null, Springfield, IL 62701"`.

While current seed data has all property fields populated, the schema allows NULLs in all columns.

**Business Impact:**
The literal string "null" appearing in property addresses in customer-facing applications is unprofessional and could cause issues with address verification, mailing, and property lookup systems.

**Recommended Fix:**
Add null-coalescing logic before concatenation. Use empty string defaults for null address components. Validate that at minimum `PROP_ADDR_LN1` and `PROP_ST_CD` are present.

---

## Summary

| ID | Title | Severity | Table |
|----|-------|----------|-------|
| ANO-001 | Payment Component Arithmetic Mismatch | Critical | CDW_PMT_HIST |
| ANO-002 | SSN Last-4 Derived from Phone Number | Critical | CDW_LN_ACCT |
| ANO-003 | Unguarded Numeric String Parsing | Critical | All |
| ANO-004 | Null Values in Logically Required Fields | High | CDW_BORR_MSTR |
| ANO-005 | Delinquency vs. Status Inconsistency | High | CDW_LN_ACCT |
| ANO-006 | No FK Constraints — Orphaned Record Risk | High | All |
| ANO-007 | Denormalized Borrower Data Drift | Medium | CDW_LN_ACCT |
| ANO-008 | Date Strings Without Validation | Medium | All |
| ANO-009 | LTV Percentage Calculation Discrepancies | Medium | CDW_LN_ACCT |
| ANO-010 | Null-Unsafe String Concatenation | Medium | CDW_LN_ACCT |
