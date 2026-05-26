# Data Anomaly Report — Legacy CDW Data Source

**Date:** 2026-05-26
**Source:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`
**Scope:** CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST

---

## ANM-001: SSN Last-4 Digits Populated from Phone Numbers

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Column** | BORR_SSN_LST4 |

**Description:**
The `BORR_SSN_LST4` column in every loan account record contains the last 4 digits of the borrower's *phone number* instead of their SSN. This represents systematic data corruption, likely caused by an ETL mapping error.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | Borrower Phone (CDW_BORR_MSTR) | Phone Last 4 |
|-------------|---------|---------------|-------------------------------|--------------|
| LN-2019-00142 | B-10001 | 0142 | 217-555-0142 | 0142 |
| LN-2020-00398 | B-10002 | 0198 | 503-555-0198 | 0198 |
| LN-2018-00089 | B-10003 | 0167 | 512-555-0167 | 0167 |
| LN-2021-00567 | B-10004 | 0134 | 303-555-0134 | 0134 |
| LN-2017-00034 | B-10005 | 0156 | 602-555-0156 | 0156 |

100% of records are affected (5/5). The correlation is exact in all cases.

**Business Impact:**
- Identity verification using SSN last-4 will fail or produce false positives
- Regulatory compliance risk (storing phone data in an SSN-designated field)
- Any downstream system relying on this field for borrower matching will produce incorrect results
- Migration to modern schema would propagate the corruption if not caught

**Recommended Fix:**
- Flag `BORR_SSN_LST4` as untrusted in the migration pipeline — do not migrate this column
- Derive the correct SSN last-4 from `BORR_SSN_ENCR` (decrypted) in the source CDW system
- Add cross-field validation: SSN last-4 must NOT match phone number last-4 digits

---

## ANM-002: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE |

**Description:**
For multiple payment records, the sum of component amounts (principal + interest + escrow + late fee) does not equal the stated total payment amount.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT (Total) | Principal | Interest | Escrow | Late Fee | Computed Sum | Discrepancy |
|-------------|-----------------|-----------|----------|--------|----------|-------------|-------------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110003 | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | +47.50 |

- PMT-2025120001 and PMT-2025110001: Component sum exceeds total by exactly $400.00. The principal + interest alone (1,531.47 / 1,531.47) already exceeds the total. Escrow appears to have been double-counted or the total was not updated after an escrow adjustment.
- PMT-2025110003: The late fee ($47.50) is not included in the total amount. The total equals principal + interest only.

3 out of 10 payment records are affected (30%).

**Business Impact:**
- Financial reporting will be inaccurate — balance calculations, P&I breakdowns, escrow accounting
- Reconciliation with general ledger will fail
- API consumers performing their own component summation will see conflicting numbers
- Regulatory reporting (TILA, RESPA) requires accurate payment breakdowns

**Recommended Fix:**
- Add a validation rule: `|PMT_AMT - (PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE)| < 0.01`
- Flag records that fail and quarantine them for manual review
- For the service layer: validate at ingestion and return a warning in the API response

---

## ANM-003: No NOT NULL Constraints on Business-Critical Fields

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables (CDW_BORR_MSTR, CDW_LN_ACCT, CDW_LN_PROD, CDW_PMT_HIST) |
| **Affected Columns** | All columns except primary keys |

**Description:**
The legacy schema defines every non-PK column as nullable VARCHAR. Critical business fields such as borrower names, loan amounts, interest rates, payment amounts, and status codes can all be NULL. The application code does not consistently check for nulls before string operations.

**Example Risk Scenarios:**
- `BORR_FST_NM = NULL` → `LoanService.toBorrowerDto()` line 124 produces `"null R. null"` in the full name
- `LN_ORIG_AMT = NULL` → `parseLegacyAmount(null)` returns `BigDecimal.ZERO`, masking missing data as zero-dollar loans
- `LN_STAT_CD = NULL` → `expandStatusCode(null)` returns `"Unknown"`, hiding missing status data
- `PROP_ADDR_LN1 = NULL` → `toLoanSummary()` line 114 produces `"null, null, null null"` in property address

**Business Impact:**
- NullPointerException at runtime for any future record with null names
- Zero-dollar amounts silently mask missing financial data
- API responses with "null" literal strings confuse consumers
- Downstream analytics on "Unknown" status records produce misleading metrics

**Recommended Fix:**
- Add NOT NULL validation in the service layer for required fields before DTO conversion
- Use explicit sentinel values or throw validation exceptions rather than silent defaults
- Add null-safe string handling with fallback labels (e.g., "[Missing]")

---

## ANM-004: All Numeric Values Stored as VARCHAR with Parsing Risks

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | BORR_CRDT_SCR, BORR_ANN_INCM, LN_ORIG_AMT, LN_CURR_BAL, LN_INT_RT, LN_TERM_MOS, LN_PMT_AMT, LN_DLQ_DAYS, LN_ESCROW_BAL, LN_LTV_PCT, PROP_APRS_VAL, PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE, PROD_TERM_MOS, PROD_MIN_AMT, PROD_MAX_AMT |

**Description:**
All numeric values are stored as VARCHAR strings. Amounts include commas (e.g., `"285,000"`, `"1,487.02"`). The service layer uses `parseLegacyAmount()` and `parseLegacyInteger()` which strip commas and parse, but any non-numeric content (e.g., `"N/A"`, `"TBD"`, `"$285,000"`, or extra whitespace) would cause an uncaught `NumberFormatException`.

**Example Fields at Risk:**
- `BORR_CRDT_SCR = "N/A"` → `Integer.parseInt("N/A")` throws NumberFormatException
- `LN_ORIG_AMT = "$285,000"` → `new BigDecimal("$285000")` throws NumberFormatException
- `BORR_ANN_INCM = "92,500"` → Works currently, but `"92,500.00.00"` would fail

**Business Impact:**
- Unhandled NumberFormatException crashes the API for all loans if even one record has bad data
- No graceful degradation — a single bad record takes down the entire `/api/loans` endpoint
- Silent conversion of blank/null amounts to zero hides missing financial data

**Recommended Fix:**
- Wrap all parse operations in try-catch with logging and fallback
- Add pre-parse validation: strip whitespace, reject non-numeric characters (except commas and decimal points)
- Return structured validation errors alongside data when anomalies are detected

---

## ANM-005: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | CDW_LN_ACCT.BORR_ID, CDW_LN_ACCT.PROD_CD, CDW_PMT_HIST.LN_ACCT_NBR |

**Description:**
The legacy schema has zero foreign key constraints. Loan accounts reference borrower IDs and product codes with no enforced referential integrity. Payment records reference loan account numbers without constraints.

**Current Data:**
All current records have valid references. However, without constraints, any future insert or ETL job can create orphaned records.

**Example Risk Scenarios:**
- A loan account with `BORR_ID = "B-99999"` (non-existent borrower) would be silently accepted
- `LoanService.getLoanById()` calls `loanProductRepository.findById(acct.getProductCode())` which returns `Optional.empty()` for invalid product codes — handled gracefully (falls back to raw code)
- `LoanService.getBorrowerById()` calls `loanAccountRepository.findByBorrowerId()` — orphaned loans for a deleted borrower would still appear

**Business Impact:**
- Loans without valid borrowers can't be serviced or reported correctly
- Payments against non-existent loans create phantom transactions
- Migration to the modern schema (which has FKs) will fail on orphaned records

**Recommended Fix:**
- Add referential integrity validation in the service layer before DTO conversion
- Verify BORR_ID exists in CDW_BORR_MSTR for each loan account
- Verify LN_ACCT_NBR exists in CDW_LN_ACCT for each payment
- Log and flag orphaned records during migration

---

## ANM-006: Delinquency Days Inconsistent with Loan Status

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | LN_DLQ_DAYS, LN_STAT_CD |

**Description:**
Loan account LN-2018-00089 has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). A loan with non-zero delinquency should typically be in a warning or delinquent status, not active.

**Example Bad Records:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| LN-2018-00089 | 15 | ACT | DLQ or at minimum flagged |

Corroborating evidence: Payment PMT-2025110003 for this loan was received on 11/18/2025 (17 days after the 11/01/2025 due date) and incurred a $47.50 late fee.

**Business Impact:**
- Delinquent loans reported as active distort portfolio health metrics
- Collections processes may not be triggered for loans that need attention
- Regulatory reporting on delinquency rates will undercount

**Recommended Fix:**
- Add cross-field validation: if `LN_DLQ_DAYS > 0` then `LN_STAT_CD` should not be `ACT`
- Business rule: delinquency > 0 days → status should be DLQ or at minimum flagged in the API response

---

## ANM-007: Dates Stored as MM/DD/YYYY Strings — Sorting and Parsing Risks

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All date columns (BORR_DOB_DT, BORR_CRET_DT, BORR_UPDT_DT, LN_ORIG_DT, LN_MAT_DT, PMT_DT, PMT_RECV_DT, etc.) |

**Description:**
All dates are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. This creates two problems:
1. **Incorrect sort order:** `ORDER BY PMT_DT DESC` uses lexicographic comparison. `"01/01/2026"` sorts *before* `"12/01/2025"` because `'0' < '1'`, producing incorrect chronological ordering across year boundaries.
2. **No format validation:** Nothing prevents entries like `"13/32/2025"`, `"00/00/0000"`, or `"TBD"`.

**Example:**
The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts payment dates as strings. Currently all data is within 2025, so this happens to produce correct results. Any cross-year data would break the ordering.

**Business Impact:**
- Payment history displayed in wrong order to API consumers
- Date-based queries and reports produce incorrect results
- Invalid date strings cause `DateTimeParseException` if parsed without validation

**Recommended Fix:**
- Parse date strings to `LocalDate` in the service layer with format validation
- Sort on parsed dates rather than raw strings
- Add date format validation at ingestion: reject or flag records with unparseable dates

---

## ANM-008: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 |

**Description:**
Loan account records duplicate borrower fields (first name, last name, SSN last-4) that also exist in CDW_BORR_MSTR. Without triggers or application-level consistency checks, these denormalized copies can drift out of sync with the master record.

**Current Data:**
All current records are consistent between CDW_LN_ACCT and CDW_BORR_MSTR for names. However, the SSN last-4 field is already known to be corrupt (see ANM-001).

**Business Impact:**
- Name changes (marriage, legal name change) in CDW_BORR_MSTR won't propagate to loan records
- API responses may show different names depending on which endpoint is called
- Migration scripts that rely on denormalized fields may produce inconsistent data

**Recommended Fix:**
- In the service layer, always resolve borrower data from CDW_BORR_MSTR via BORR_ID rather than using denormalized fields in CDW_LN_ACCT
- Add validation comparing denormalized fields against master records
- Flag discrepancies for manual review

---

## ANM-009: Unvalidated Status Codes — Silent Pass-Through of Invalid Values

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT, CDW_PMT_HIST, CDW_BORR_MSTR |
| **Affected Columns** | LN_STAT_CD, PMT_TYP_CD, PMT_STAT_CD, BORR_STAT_CD |

**Description:**
The `expandStatusCode()`, `expandPaymentType()`, and `expandPaymentStatus()` methods in `LoanService.java` have a `default -> code` branch that silently passes through any unrecognized status code. Invalid or corrupted codes would appear in API responses as raw abbreviations without any warning.

**Valid Code Sets:**
- `LN_STAT_CD`: ACT, CLO, DFT, FRB
- `PMT_TYP_CD`: REG, EXT, PRT, PRE
- `PMT_STAT_CD`: PST, REV, NSF, PND
- `BORR_STAT_CD`: ACT, INA

**Business Impact:**
- Unknown status codes in API responses confuse consumers
- Analytics and filtering on status fields may miss records with invalid codes
- No alerting mechanism for data quality degradation

**Recommended Fix:**
- Add validation against known code sets
- Log warnings for unrecognized codes
- Return a structured indicator (e.g., `"UNKNOWN(XYZ)"`) rather than the raw code

---

## ANM-010: Inconsistent Decimal Precision in Numeric String Fields

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | LN_LTV_PCT, LN_INT_RT |

**Description:**
LTV percentage values have inconsistent decimal precision: `82.5`, `68.2`, `75.0`, `72.8`, `80.0`. Interest rates similarly vary: `4.750`, `3.125`, `5.250`, `3.875`, `4.250`. While `parseLegacyDecimal()` handles these correctly, the inconsistency suggests no standardized input format.

**Business Impact:**
- Minor: no functional impact in current code
- Could cause display inconsistencies if the raw values are ever shown without formatting
- Indicates lack of data entry standards in the source system

**Recommended Fix:**
- Normalize precision after parsing (e.g., always use 3 decimal places for rates, 2 for percentages)
- Apply consistent formatting in DTO responses

---

## Summary

| ID | Title | Severity | Tables Affected | Records Affected |
|----|-------|----------|-----------------|------------------|
| ANM-001 | SSN Last-4 from Phone Numbers | Critical | CDW_LN_ACCT | 5/5 (100%) |
| ANM-002 | Payment Components Don't Sum to Total | Critical | CDW_PMT_HIST | 3/10 (30%) |
| ANM-003 | No NOT NULL on Critical Fields | High | All | Schema-wide |
| ANM-004 | Numerics as VARCHAR with Parse Risks | High | All | Schema-wide |
| ANM-005 | No Foreign Key Constraints | High | CDW_LN_ACCT, CDW_PMT_HIST | Schema-wide |
| ANM-006 | Delinquency vs Status Inconsistency | High | CDW_LN_ACCT | 1/5 (20%) |
| ANM-007 | Dates as Strings — Sort/Parse Risks | Medium | All | Schema-wide |
| ANM-008 | Denormalized Data Drift Risk | Medium | CDW_LN_ACCT | Potential |
| ANM-009 | Unvalidated Status Codes | Medium | Multiple | Potential |
| ANM-010 | Inconsistent Decimal Precision | Low | CDW_LN_ACCT | 5/5 (100%) |
