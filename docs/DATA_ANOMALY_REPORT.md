# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql`, `data-legacy.sql`, and the service layer code.

---

## ANM-001: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Description
The sum of payment components (principal + interest + escrow + late fee) does not equal the total payment amount for multiple records.

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT (Total) | Principal + Interest + Escrow + Late Fee | Difference |
|---|---|---|---|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | -400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | -400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | -47.50 |

### Business Impact
Financial reports and borrower statements will show incorrect payment breakdowns. Downstream systems relying on component sums for reconciliation will fail audit checks. The $400 discrepancy on loan LN-2019-00142 suggests the escrow component is being double-counted or misallocated. The $47.50 discrepancy on LN-2018-00089 indicates the late fee is recorded but not reflected in the total.

### Recommended Fix
Add a validation rule at ingestion time that compares `principal + interest + escrow + lateFee` against `total`. Flag records where the absolute difference exceeds a tolerance threshold (e.g., $0.01). Log warnings and include a `componentMismatch` flag in the API response.

---

## ANM-002: SSN Last-4 Field Contains Phone Number Digits

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

### Description
The `BORR_SSN_LST4` column in the loan account table contains the last 4 digits of the borrower's phone number rather than the last 4 digits of their SSN. Every record in the seed data exhibits this pattern.

### Example Bad Records

| LN_ACCT_NBR | BORR_SSN_LST4 | Borrower Phone (CDW_BORR_MSTR) | Phone Last 4 |
|---|---|---|---|
| `LN-2019-00142` | 0142 | 217-555-**0142** | 0142 |
| `LN-2020-00398` | 0198 | 503-555-**0198** | 0198 |
| `LN-2018-00089` | 0167 | 512-555-**0167** | 0167 |
| `LN-2021-00567` | 0134 | 303-555-**0134** | 0134 |
| `LN-2017-00034` | 0156 | 602-555-**0156** | 0156 |

### Business Impact
Identity verification workflows that rely on SSN last-4 matching will accept incorrect matches or reject valid borrowers. Regulatory compliance (KYC/AML) processes are compromised. If this data migrates to a modern system unchecked, the PII integrity issue propagates.

### Recommended Fix
Flag all `BORR_SSN_LST4` values as unreliable. Cross-reference against the encrypted SSN in `CDW_BORR_MSTR.BORR_SSN_ENCR` to derive correct last-4 values. Until corrected, do not use this field for identity verification.

---

## ANM-003: Numeric String Parsing Without Error Handling

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | All tables |
| **Affected Columns** | All numeric-as-VARCHAR columns: `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_TERM_MOS`, `LN_PMT_AMT`, `PMT_AMT`, etc. |

### Description
The service layer uses `new BigDecimal(...)`, `Integer.parseInt(...)`, and string `.replace(",","")` to convert VARCHAR values into numeric types. None of these conversions have try-catch error handling. Any corrupted, non-numeric, or unexpected format in the legacy data causes an unhandled `NumberFormatException` that crashes the API request.

### Example Risky Patterns
- Credit score `"N/A"` or `""` → `Integer.parseInt` throws `NumberFormatException`
- Amount `"$285,000"` (with dollar sign) → `BigDecimal` constructor throws after comma removal
- Rate `"5.250%"` (with percent sign) → `BigDecimal` constructor throws
- Income `"92,500.00.00"` (double decimal) → `BigDecimal` constructor throws

### Business Impact
A single corrupted legacy record causes an HTTP 500 error for the entire API response (since `getAllLoans()` maps all records in a stream). One bad record makes the entire loan list endpoint unavailable.

### Recommended Fix
Wrap all parsing in try-catch blocks. Return a configurable fallback (e.g., `BigDecimal.ZERO` or `null`) on parse failure. Log the original value and record ID for data steward review.

---

## ANM-004: Null-Unsafe String Concatenation in DTO Translation

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `PROP_ADDR_LN1`, `PROP_CTY_NM`, `PROP_ST_CD`, `PROP_ZIP_CD` |

### Description
`LoanService.toLoanSummary()` concatenates borrower name fields and property address fields without null checks. If any of these denormalized fields are null (which the schema allows), a `NullPointerException` is thrown.

### Example
```java
// Line 106 — NPE if borrowerFirstName or borrowerLastName is null
dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());

// Lines 114-115 — NPE if any property field is null
dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
        + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
```

### Business Impact
A single loan record with a null borrower name or null property field causes the entire `GET /api/loans` endpoint to fail with an HTTP 500 error, blocking all loan queries.

### Recommended Fix
Use null-safe concatenation with fallback defaults (e.g., `"Unknown"` for missing names, `""` for missing address components).

---

## ANM-005: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Description
The legacy schema defines no foreign key constraints. Loan accounts can reference non-existent borrower IDs or product codes. Payments can reference non-existent loan account numbers.

### Example Scenario
- A loan account with `BORR_ID = 'B-99999'` (no matching borrower) would be accepted by the database
- `LoanService.getLoanById()` would then call `loanProductRepository.findById(acct.getProductCode())` which returns `null` — handled, but borrower lookup in `getBorrowerById` would not find associated loans
- A payment with `LN_ACCT_NBR = 'LN-INVALID'` would be stored but never appear in any loan's payment history

### Business Impact
Orphaned records lead to incomplete views of borrower portfolios and missing payment histories. Loan-to-borrower linkage failures undermine portfolio risk analysis.

### Recommended Fix
Add referential integrity validation at the service layer: verify that `BORR_ID` exists in `CDW_BORR_MSTR`, `PROD_CD` exists in `CDW_LN_PROD`, and `LN_ACCT_NBR` exists in `CDW_LN_ACCT` before processing records.

---

## ANM-006: All Columns VARCHAR — No Database-Level Type Enforcement

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All columns |

### Description
Every column in every legacy table is defined as `VARCHAR`. Dates, amounts, percentages, credit scores, term lengths — all are stored as free-text strings. The database provides zero type enforcement.

### Example
```sql
BORR_CRDT_SCR   VARCHAR(5)    -- should be INTEGER, range 300-850
BORR_ANN_INCM   VARCHAR(15)   -- should be DECIMAL(12,2)
LN_INT_RT       VARCHAR(8)    -- should be DECIMAL(5,3)
BORR_DOB_DT     VARCHAR(10)   -- should be DATE
```

### Business Impact
Any upstream system or manual data entry can insert invalid values (e.g., a date of `"UNKNOWN"`, an amount of `"TBD"`) without the database rejecting it. This shifts all validation burden to the application layer.

### Recommended Fix
Implement strict type validation in the service layer during ingestion. During migration, convert to proper typed columns in the modern schema (already planned per `column_mappings.md`).

---

## ANM-007: Date Strings Not Validated — Format Corruption Risk

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All `*_DT` columns (`BORR_DOB_DT`, `BORR_CRET_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.) |

### Description
Dates are stored as `VARCHAR(10)` in `MM/DD/YYYY` format but the service layer never parses or validates them. Date values are passed through as raw strings to DTOs. Any format deviation (e.g., `YYYY-MM-DD`, `DD/MM/YYYY`, `"N/A"`) would silently propagate to API consumers.

### Example
The current data uses `MM/DD/YYYY` consistently, but the schema and code provide no guarantee. The column mappings document specifies the expected `MM/DD/YYYY → DATE` transformation, but the current service skips this conversion entirely.

### Business Impact
API consumers cannot rely on a consistent date format. Date-based queries or sorting by date strings produces incorrect results (e.g., `"02/01/2025"` sorts before `"12/01/2024"` in lexicographic order).

### Recommended Fix
Parse all date strings into `java.time.LocalDate` at ingestion time using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Reject or flag records with unparseable dates. Return ISO-8601 format (`yyyy-MM-dd`) in API responses.

---

## ANM-008: String-Based Date Ordering Produces Incorrect Sort

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Column** | `PMT_DT` |

### Description
`LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc` generates an `ORDER BY PMT_DT DESC` SQL clause. Since `PMT_DT` is a `VARCHAR`, this performs lexicographic sorting, not chronological sorting. The `MM/DD/YYYY` format means month is compared first, so February (`02/...`) sorts before December (`12/...`) of the previous year.

### Example
Lexicographic order of `"12/01/2025"` vs `"02/01/2026"`:
- String comparison: `"02/01/2026" < "12/01/2025"` (because `'0' < '1'`)
- Chronological: `02/01/2026` is **after** `12/01/2025`
- Result: January/February payments incorrectly sort before December payments

### Business Impact
Payment history displayed to users or fed to downstream systems appears out of order, particularly across year boundaries.

### Recommended Fix
Parse date strings before sorting in the service layer, or convert to `yyyy-MM-dd` format for correct lexicographic ordering.

---

## ANM-009: Denormalized Borrower Data Can Drift from Master

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

### Description
The loan account table embeds borrower first name, last name, and SSN last-4 as denormalized copies from the borrower master table. Without triggers or application-level sync, these copies can diverge from the master record when a borrower's name is updated.

### Example
If borrower B-10002 (Sarah Chen) changes their last name, `CDW_BORR_MSTR.BORR_LST_NM` would be updated, but `CDW_LN_ACCT.BORR_LST_NM` for loan `LN-2020-00398` would still show `"Chen"`. The service uses the loan table's copy (`acct.getBorrowerFirstName()`) for the API, not the master record.

### Business Impact
Borrower name in loan listings may not match borrower name in borrower details, creating confusion for users and audit discrepancies.

### Recommended Fix
Prefer the master record (`CDW_BORR_MSTR`) for borrower identity fields. Add a validation check that flags records where denormalized values diverge from the master.

---

## ANM-010: Delinquent Loan Missing Late Fee on Subsequent Payment

| Field | Value |
|---|---|
| **Severity** | Low |
| **Affected Table** | `CDW_PMT_HIST`, `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `PMT_LATE_FEE`, `PMT_RECV_DT` |

### Description
Loan `LN-2018-00089` (Michael Torres) has `LN_DLQ_DAYS = '15'` indicating delinquency. The November 2025 payment correctly shows a `PMT_LATE_FEE` of `47.50` and was received late (`PMT_RECV_DT = '11/18/2025'` vs `PMT_DT = '11/01/2025'`). However, the December 2025 payment was also received late (`PMT_RECV_DT = '12/05/2025'` vs `PMT_DT = '12/01/2025'`) but has a `PMT_LATE_FEE` of `0.00`.

### Business Impact
Inconsistent late fee application may indicate either a grace period (not documented) or a data entry error. Revenue from late fees may be under-reported.

### Recommended Fix
Add a validation rule that flags payments received more than N days after the due date that have a zero late fee. Log as a warning for manual review.
