# Data Anomaly Report — Legacy CDW Tables

## Summary

Analysis of the legacy Corporate Data Warehouse (CDW) seed data (`data-legacy.sql`) and schema
(`schema-legacy.sql`) identified **8 distinct anomaly categories** affecting data quality,
type safety, and referential integrity across all 4 legacy tables.

---

## Anomaly #1: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Description
Payment component amounts (principal + interest + escrow + late fee) do not sum to the
stated total payment amount for multiple records.

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT (Total) | Principal + Interest + Escrow + Late Fee | Difference |
|---|---|---|---|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | +400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | +400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | +47.50 |

### Business Impact
- Financial reporting will show incorrect payment breakdowns
- Balance reconciliation between principal/interest/escrow allocations will fail
- Audit trails become unreliable; regulatory compliance risk for loan servicing

### Recommended Fix
- Add a validation rule that asserts: `total_amount == principal + interest + escrow + late_fee`
- Flag records where the sum deviates beyond a rounding tolerance (e.g., $0.01)
- Quarantine mismatched records for manual reconciliation

---

## Anomaly #2: SSN Last-4 Populated from Phone Number

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

### Description
The denormalized `BORR_SSN_LST4` field in the loan accounts table contains the last 4 digits
of the borrower's **phone number**, not their Social Security Number. This affects 100% of
records.

### Example Bad Records

| LN_ACCT_NBR | BORR_SSN_LST4 | Borrower Phone (CDW_BORR_MSTR) | Phone Last 4 |
|---|---|---|---|
| `LN-2019-00142` | 0142 | 217-555-**0142** | 0142 |
| `LN-2020-00398` | 0198 | 503-555-**0198** | 0198 |
| `LN-2018-00089` | 0167 | 512-555-**0167** | 0167 |
| `LN-2021-00567` | 0134 | 303-555-**0134** | 0134 |
| `LN-2017-00034` | 0156 | 602-555-**0156** | 0156 |

### Business Impact
- Identity verification processes using SSN last-4 will fail or produce false matches
- Regulatory compliance violation (GLBA, SOX) — incorrect PII handling
- Downstream KYC/AML checks based on this field are unreliable

### Recommended Fix
- Flag this column as **untrusted** — do not use for identity verification
- Cross-reference against the encrypted SSN in `CDW_BORR_MSTR.BORR_SSN_ENCR` for validation
- Mark the field as deprecated in migration; derive correct value from source of truth

---

## Anomaly #3: Numeric Values Stored as Formatted Strings

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `BORR_CRDT_SCR`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, all amount fields |

### Description
All numeric values (monetary amounts, rates, scores, counts) are stored as VARCHAR with
embedded formatting (commas as thousand separators). Any non-standard character (e.g., `$`,
spaces, letters) will cause `NumberFormatException` at parse time.

### Example Bad Records (format risk patterns)

| Table | Column | Example Value | Parse Risk |
|---|---|---|---|
| `CDW_BORR_MSTR` | `BORR_ANN_INCM` | `92,500` | Comma must be stripped before parsing |
| `CDW_BORR_MSTR` | `BORR_CRDT_SCR` | `745` | Safe if always numeric, but no constraint enforces this |
| `CDW_LN_ACCT` | `LN_CURR_BAL` | `271,432.56` | Comma + decimal; parsing works if only commas present |
| `CDW_LN_ACCT` | `LN_LTV_PCT` | `82.5` | Parseable, but no validation prevents `82.5%` format |
| `CDW_LN_PROD` | `PROD_MIN_AMT` | `0` | Edge case — VA loan min amount is "0" |

### Business Impact
- Runtime `NumberFormatException` crashes the API for any record with unexpected formatting
- No input validation exists — a single malformed record takes down the entire query
- Silent data corruption if amounts are parsed incorrectly (e.g., European format `1.487,02`)

### Recommended Fix
- Wrap all string-to-numeric parsing in try-catch with logging
- Validate format patterns before conversion (regex: `^-?\d{1,3}(,\d{3})*(\.\d+)?$`)
- Add fallback defaults and quarantine records that fail parsing

---

## Anomaly #4: No Foreign Key Constraints (Orphan Record Risk)

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Description
The legacy schema defines zero foreign key constraints. Any record can reference a
non-existent borrower, product, or loan account without database-level enforcement.

### Example Scenarios
- A loan account could have `BORR_ID = 'B-99999'` with no matching borrower record
- A payment could reference `LN_ACCT_NBR = 'LN-DELETED-001'` with no loan account
- A loan could reference `PROD_CD = 'EXPIRED01'` with no matching product

### Current Data State
The current seed data has valid references, but the **lack of constraints means**:
- `LoanService.getLoanById()` does `products.get(acct.getProductCode())` which returns null for orphaned product codes → NPE or "Unknown" product name
- `LoanService.getBorrowerById()` could succeed for a borrower but `findByBorrowerId()` might return loans referencing deleted borrowers

### Business Impact
- API returns incomplete or null data for orphaned records
- Data integrity cannot be guaranteed as the legacy DW evolves
- Migration to modern schema with FK constraints will reject orphaned records

### Recommended Fix
- Validate referential integrity at the service layer before DTO construction
- Log warnings for orphaned references and use defensive null checks
- Pre-migration: run integrity checks and resolve orphans before cutover

---

## Anomaly #5: Date Strings with No Format Validation

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | All tables |
| **Affected Columns** | All `*_DT` columns (`BORR_DOB_DT`, `BORR_CRET_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.) |

### Description
All date values are stored as VARCHAR(10) with an expected format of `MM/DD/YYYY`, but no
schema constraint enforces this format. The service layer passes date strings through to the
API response without parsing or validation.

### Example Risk Patterns

| Scenario | Value | Impact |
|---|---|---|
| ISO format mixed in | `2025-12-01` | Would not match MM/DD/YYYY parser |
| Invalid date | `02/30/2020` | Feb 30 doesn't exist; silent corruption |
| Empty string | `` (blank) | NullPointerException in downstream date math |
| Partial date | `12/2025` | Parse failure |

### Current Data State
All seed records use consistent `MM/DD/YYYY` format, but with no enforcement, any future
insert could break the expected pattern.

### Business Impact
- Migration date parsing (`MM/DD/YYYY → DATE`) will fail on inconsistent records
- Age calculations, maturity date checks, and delinquency calculations break silently
- API consumers cannot trust date field formatting

### Recommended Fix
- Parse and validate all date strings at ingestion using `DateTimeFormatter` with strict mode
- Return standardized ISO-8601 format (`yyyy-MM-dd`) in API responses
- Reject or quarantine records with unparseable dates

---

## Anomaly #6: Denormalized Data Inconsistency Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` (redundant with `CDW_BORR_MSTR`) |

### Description
Borrower first name, last name, and SSN last-4 are denormalized into the loan accounts table.
These can drift from the authoritative values in `CDW_BORR_MSTR` without any reconciliation.

### Example Bad Records (potential drift)
Current seed data is consistent, but in production:
- If borrower `B-10002` changes last name (marriage), `CDW_BORR_MSTR.BORR_LST_NM` updates
  but `CDW_LN_ACCT.BORR_LST_NM` remains stale
- The service uses `acct.getBorrowerFirstName()` from the loan table, not from the borrower
  master → stale name appears in API responses

### Business Impact
- Customer-facing documents may show outdated names
- Search/matching by name could miss records if master vs. denormalized data disagrees
- Compliance risk for correspondence with incorrect PII

### Recommended Fix
- Service layer should prefer borrower master data over denormalized loan account data
- Add reconciliation validation comparing denormalized fields against their master source
- In modern schema: remove denormalized columns, use FK relationship

---

## Anomaly #7: Delinquency Status Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

### Description
Loan status code does not reflect the delinquency state indicated by `LN_DLQ_DAYS`.

### Example Bad Records

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Expected Status |
|---|---|---|---|
| `LN-2018-00089` | ACT (Active) | 15 | Should be DLQ or at minimum flagged |

### Business Impact
- Collections workflows relying on status code will miss delinquent loans
- Regulatory reporting (CCAR, DFAST stress testing) uses status codes — delinquent loans
  reported as "Active" understates risk
- Portfolio risk metrics will be incorrect

### Recommended Fix
- Add cross-field validation: if `delinquency_days > 0`, status should not be plain "Active"
- Flag inconsistencies and apply business rule: `days > 30` → DLQ, `days > 90` → DFT
- Log warnings for borderline cases (1-29 days) where status is still "Active"

---

## Anomaly #8: Null Values in Contextually Required Fields

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

### Description
Several fields that are optional at the schema level may be contextually required for
downstream processes. `BORR_MID_INIT` is NULL for borrower `B-10005`, and `BORR_ADDR_LN2`
is NULL for 3 of 5 borrowers.

### Example Bad Records

| BORR_ID | BORR_MID_INIT | BORR_ADDR_LN2 |
|---|---|---|
| `B-10002` | L | NULL |
| `B-10003` | A | NULL |
| `B-10005` | NULL | NULL |

### Business Impact
- Name formatting produces inconsistent results (some with middle initial, some without)
- Address matching/deduplication may fail without standardized null handling
- Minor impact — these fields are legitimately optional in most business contexts

### Recommended Fix
- Use empty string or explicit placeholder for null address lines
- Handle null middle initial gracefully in name formatting (already done in service layer)
- Document which fields are truly optional vs. expected-but-missing

---

## Summary Table

| # | Anomaly | Severity | Tables | Runtime Risk |
|---|---|---|---|---|
| 1 | Payment component sum mismatch | Critical | CDW_PMT_HIST | Incorrect financial data in API |
| 2 | SSN last-4 contains phone digits | Critical | CDW_LN_ACCT | Identity verification failures |
| 3 | Numeric values as formatted strings | High | All | NumberFormatException crashes |
| 4 | No foreign key constraints | High | CDW_LN_ACCT, CDW_PMT_HIST | Null/missing data in API |
| 5 | Date strings without format validation | High | All | Parse failures on migration |
| 6 | Denormalized data drift risk | Medium | CDW_LN_ACCT | Stale borrower info in responses |
| 7 | Delinquency/status inconsistency | Medium | CDW_LN_ACCT | Incorrect risk reporting |
| 8 | Null values in contextual fields | Low | CDW_BORR_MSTR | Minor formatting issues |
