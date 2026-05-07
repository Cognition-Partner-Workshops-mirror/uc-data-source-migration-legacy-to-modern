# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql`, `data-legacy.sql`, and `column_mappings.md`.

---

## ANM-001: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Category** | Data Integrity |

**Description:**
The sum of principal + interest + escrow + late fee does not equal the total payment amount on multiple records. This is a fundamental accounting integrity violation.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT (Total) | PRIN + INT + ESCROW + LATE | Discrepancy |
|---|---|---|---|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = 1,887.02 | +400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = 1,887.02 | +400.00 |
| `PMT-2025120002` | 2,924.18 | 1,842.56 + 815.50 + 266.12 + 0.00 = 2,924.18 | 0.00 (OK) |
| `PMT-2025120003` | 1,077.05 | 297.12 + 779.93 + 0.00 + 0.00 = 1,077.05 | 0.00 (OK) |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = 1,124.55 | +47.50 |
| `PMT-2025120004` | 2,468.35 | 857.23 + 1,611.12 + 0.00 + 0.00 = 2,468.35 | 0.00 (OK) |
| `PMT-2025120005` | 811.61 | 306.45 + 505.16 + 0.00 + 0.00 = 811.61 | 0.00 (OK) |

**Business Impact:**
Financial reporting, escrow analysis, and principal/interest breakdowns returned by the API will be inconsistent. Downstream consumers relying on component breakdowns for tax reporting or investor accounting will have incorrect data.

**Recommended Fix:**
Validate at ingestion that `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE == PMT_AMT`. Flag records that fail this check and include a `componentMismatch` warning in the API response.

---

## ANM-002: Numeric Financial Values Stored as Comma-Formatted Strings

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `BORR_CRDT_SCR`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `LN_LTV_PCT`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PROD_TERM_MOS`, `LN_TERM_MOS`, `LN_DLQ_DAYS` |
| **Category** | Type Safety / Parsing Risk |

**Description:**
All numeric values are stored as VARCHAR strings, often with embedded commas (e.g., `"285,000"`, `"1,487.02"`, `"92,500"`). The service layer uses `parseLegacyAmount()` which strips commas, but has no protection against:
- Currency symbols (e.g., `$285,000`)
- Alphabetic text (e.g., `N/A`, `PENDING`, `TBD`)
- Extra whitespace or non-breaking spaces
- European decimal notation (e.g., `285.000,00`)
- Negative values represented with parentheses (e.g., `(1,487.02)`)

**Example Data:**
```
BORR_ANN_INCM: '92,500', '125,000', '78,000', '145,000', '65,000'
LN_ORIG_AMT:   '285,000', '420,000', '195,000', '525,000', '165,000'
BORR_CRDT_SCR: '745', '780', '692', '810', '658'
```

**Business Impact:**
A single malformed value causes `NumberFormatException` in `parseLegacyAmount()` / `parseLegacyInteger()`, crashing the entire API request. For `getAllLoans()`, one bad record takes down the entire loan listing.

**Recommended Fix:**
Wrap all parsing in try-catch with structured error logging. Return null or a sentinel value for unparseable fields, and include a `dataQualityWarnings` list in the DTO.

---

## ANM-003: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |
| **Category** | Referential Integrity |

**Description:**
The legacy schema has zero foreign key constraints. Relationships are implied by column naming conventions only:
- `CDW_LN_ACCT.BORR_ID` → `CDW_BORR_MSTR.BORR_ID` (no FK)
- `CDW_LN_ACCT.PROD_CD` → `CDW_LN_PROD.PROD_CD` (no FK)
- `CDW_PMT_HIST.LN_ACCT_NBR` → `CDW_LN_ACCT.LN_ACCT_NBR` (no FK)

This means orphaned records can exist where a loan references a non-existent borrower or product, and a payment references a non-existent loan.

**Code Impact:**
In `LoanService.toLoanSummary()`, line 107: `products.get(acct.getProductCode())` returns null for an unknown product code. The code handles this with a fallback (`product != null ? product.getDescription() : acct.getProductCode()`), but other lookups are not guarded.

In `LoanService.getBorrowerById()`, `loanAccountRepository.findByBorrowerId(borrowerId)` could return loans whose `BORR_ID` points to a deleted borrower, or payments could reference deleted loans.

**Business Impact:**
Orphaned payment records are invisible — they won't appear in any loan's payment history. Orphaned loan accounts will cause incomplete borrower profiles.

**Recommended Fix:**
Validate referential integrity at ingestion time. Log warnings for orphaned records and exclude them from API responses with appropriate warnings.

---

## ANM-004: Dates Stored as Strings with No Format Validation

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | All `*_DT` columns (16 total across all tables) |
| **Category** | Type Safety / Format Inconsistency |

**Description:**
All date fields are stored as `VARCHAR(10)` with an expected format of `MM/DD/YYYY`. The schema comments document this convention, but there is no enforcement. The service layer passes date strings through to the DTO without parsing or validation (`dto.setOriginationDate(acct.getOriginationDate())`, `dto.setPaymentDate(pmt.getPaymentDate())`).

Potential format variations that would go undetected:
- `YYYY-MM-DD` (ISO format)
- `DD/MM/YYYY` (European format — ambiguous for days 1-12)
- `12-01-2025` (dash separator)
- Empty string or `NULL`
- Invalid dates like `02/30/2025` or `13/01/2025`

**Example Data:**
All current seed data uses consistent `MM/DD/YYYY`, but there is nothing preventing inconsistent data from entering the system.

**Business Impact:**
API consumers receive raw date strings with no guarantee of format consistency. Date comparison, sorting, and range queries on VARCHAR dates produce incorrect results (e.g., `'12/01/2025' < '02/01/2026'` is lexicographically false).

**Recommended Fix:**
Parse all date strings into `LocalDate` at the service layer. Validate format and reject/flag invalid dates. Return ISO-8601 format (`YYYY-MM-DD`) in API responses.

---

## ANM-005: Null/Missing Values in Semantically Required Fields

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2`, all nullable VARCHAR columns |
| **Category** | Null Handling |

**Description:**
The schema declares no `NOT NULL` constraints on any non-PK column. In the seed data:
- `BORR_MID_INIT` is `NULL` for borrower B-10005 (Robert Williams)
- `BORR_ADDR_LN2` is `NULL` for borrowers B-10002, B-10003, B-10005

The service layer handles middle initial nulls in `toBorrowerDto()`:
```java
String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
```
But critical fields like `BORR_FST_NM`, `BORR_LST_NM`, `LN_ACCT_NBR`, `BORR_ID`, `LN_STAT_CD` could also be null — there is no schema-level or code-level enforcement.

**Business Impact:**
A null `BORR_FST_NM` or `BORR_LST_NM` would produce names like `"null Williams"` or `"James null"` in API responses. A null `LN_STAT_CD` would return `"Unknown"` status, masking a data quality issue.

**Recommended Fix:**
Define which fields are required for each entity. Validate non-null constraints at ingestion time and reject records missing required fields.

---

## ANM-006: Denormalized Borrower Data Can Drift from Master Record

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |
| **Category** | Denormalization Inconsistency |

**Description:**
`CDW_LN_ACCT` contains denormalized copies of borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) alongside the `BORR_ID` foreign key. These can diverge from the master `CDW_BORR_MSTR` record if the borrower's name changes (e.g., marriage, legal name change) but the loan record is not updated.

The code uses **both sources inconsistently**:
- `toLoanSummary()` uses denormalized `acct.getBorrowerFirstName()` + `acct.getBorrowerLastName()`
- `toBorrowerDto()` uses master `borrower.getFirstName()` + `borrower.getLastName()`

**Example — Current data is consistent:**
| Source | First | Last |
|---|---|---|
| CDW_BORR_MSTR B-10001 | James | Mitchell |
| CDW_LN_ACCT LN-2019-00142 | James | Mitchell |

But if the master record is updated and the loan record is not, the API would show different names for the same person depending on which endpoint is called.

**Business Impact:**
Regulatory and compliance reports could show different borrower names for the same loan. Customer-facing portals would display inconsistent information.

**Recommended Fix:**
Cross-validate denormalized fields against master records at ingestion. Log warnings for mismatches. Prefer master record as the source of truth.

---

## ANM-007: Silent Null-to-Zero Coercion for Financial Amounts

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Tables** | All tables with financial amounts |
| **Affected Columns** | All amount/balance columns |
| **Category** | Semantic Data Loss |

**Description:**
`parseLegacyAmount()` returns `BigDecimal.ZERO` when the input is null or blank:
```java
if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
```
This silently converts "missing data" into "$0.00", which is a valid financial value. A missing escrow balance is not the same as a zero escrow balance.

**Business Impact:**
- A null `LN_CURR_BAL` would show as $0.00 balance (loan appears paid off)
- A null `PROP_APRS_VAL` would show as $0.00 appraised value (LTV calculation breaks)
- A null `PMT_AMT` would show as a $0.00 payment (appears as a zero-dollar transaction)

Financial reports would include false zero values, potentially causing incorrect aggregate calculations and misleading business decisions.

**Recommended Fix:**
Return `null` instead of `BigDecimal.ZERO` for missing amounts. Let the DTO carry nulls for missing data and document the distinction between "zero" and "not available" in the API contract.

---

## ANM-008: Unvalidated Status Codes with Silent Pass-Through

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_STAT_CD`, `LN_STAT_CD`, `PMT_STAT_CD`, `PMT_TYP_CD`, `PROD_STAT_CD` |
| **Category** | Invalid Codes |

**Description:**
Status code expansion methods (`expandStatusCode`, `expandPaymentType`, `expandPaymentStatus`) have a `default -> code` branch that silently passes through unrecognized codes. This means invalid/typo codes (e.g., `"ACTT"`, `"XYZ"`, `""`) would appear verbatim in API responses.

Valid codes per table:
- Loan status: `ACT`, `CLO`, `DFT`, `FRB`
- Payment status: `PST`, `REV`, `NSF`, `PND`
- Payment type: `REG`, `EXT`, `PRT`, `PRE`
- Borrower status: `ACT`, `INA` (per column_mappings.md, but no expansion code exists)
- Product status: `ACT`, `INA` (per column_mappings.md, but no expansion code exists)

Note: `BORR_STAT_CD` and `PROD_STAT_CD` have no expansion logic in the service layer at all — they are never read or translated.

**Business Impact:**
API consumers may receive raw legacy codes instead of human-readable values. Unknown codes could break client-side parsing or UI rendering.

**Recommended Fix:**
Validate status codes against an allowlist at ingestion time. Log warnings for unrecognized codes. Return a structured error or a clearly marked "UNKNOWN" value.

---

## ANM-009: Payment Date Ordering Anomaly (Received After Processed)

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT` |
| **Category** | Temporal Inconsistency |

**Description:**
Some payment records show `PMT_RECV_DT` (received date) after the scheduled `PMT_DT` (payment due date), indicating late payments. While this can be legitimate, the data also shows cases where `PMT_RECV_DT` is after `PMT_PROC_DT`, which is logically impossible (a payment cannot be processed before it is received).

**Example:**
| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | PMT_PROC_DT | Late Fee |
|---|---|---|---|---|
| `PMT-2025120003` | 12/01/2025 | 12/05/2025 | 12/06/2025 | 0.00 |
| `PMT-2025110003` | 11/01/2025 | 11/18/2025 | 11/19/2025 | 47.50 |

PMT-2025120003 was received 4 days late but has no late fee, while PMT-2025110003 was received 17 days late and has a $47.50 late fee. The inconsistency in late fee application (late but no fee vs. late with fee) suggests either business rule complexity or data quality issues.

**Business Impact:**
Late fee calculations and delinquency reporting may be inconsistent. Borrower disputes about late fees would be difficult to adjudicate.

**Recommended Fix:**
Validate temporal ordering: `PMT_RECV_DT <= PMT_PROC_DT`. Cross-validate late fees against late receipt dates. Flag records with temporal anomalies.

---

## ANM-010: Delinquency Days Inconsistent with Payment History

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `LN_DLQ_DAYS` |
| **Category** | Cross-Table Inconsistency |

**Description:**
Loan account `LN-2018-00089` (borrower B-10003, Michael Torres) shows `LN_DLQ_DAYS = '15'`, but both of its payment records show `PMT_STAT_CD = 'PST'` (Posted). A loan with 15 delinquency days should have at least one missed or pending payment, but all payments are marked as successfully posted.

**Example:**
| LN_ACCT_NBR | LN_DLQ_DAYS | Payment Records |
|---|---|---|
| LN-2018-00089 | 15 | PMT-2025120003 (PST), PMT-2025110003 (PST) |

**Business Impact:**
Delinquency reporting would flag this loan as delinquent while payment history shows all payments made. This creates conflicting signals for collections teams, credit reporting, and risk assessment.

**Recommended Fix:**
Cross-validate delinquency days against payment history. Flag inconsistencies where a loan shows delinquency days > 0 but all recent payments are posted.

---

## Summary

| ID | Title | Severity | Tables |
|---|---|---|---|
| ANM-001 | Payment components don't sum to total | Critical | CDW_PMT_HIST |
| ANM-002 | Numeric values as comma-formatted strings | Critical | All tables |
| ANM-003 | No FK constraints — orphaned records | Critical | CDW_LN_ACCT, CDW_PMT_HIST |
| ANM-004 | Dates as unvalidated strings | High | All tables |
| ANM-005 | Null values in required fields | High | CDW_BORR_MSTR, CDW_LN_ACCT |
| ANM-006 | Denormalized data can drift | High | CDW_LN_ACCT |
| ANM-007 | Null-to-zero coercion for amounts | High | All tables |
| ANM-008 | Unvalidated status codes | Medium | All tables |
| ANM-009 | Temporal ordering anomalies in payments | Medium | CDW_PMT_HIST |
| ANM-010 | Delinquency days vs. payment history mismatch | Medium | CDW_LN_ACCT, CDW_PMT_HIST |
