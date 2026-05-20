# Data Anomaly Report — Legacy CDW Tables

This report documents data quality anomalies identified in the legacy Corporate Data Warehouse
(CDW) seed data (`src/main/resources/data-legacy.sql`) and schema (`src/main/resources/schema-legacy.sql`).

---

## Anomaly #1: Payment Component Mismatch (Sum ≠ Total)

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Description

For loan `LN-2019-00142`, the sum of payment components (principal + interest + escrow + late fee)
does not equal the stated total payment amount. The expected invariant is:
`PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`.

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT | Principal | Interest | Escrow | Late Fee | Computed Sum | Delta |
|-------------|---------|-----------|----------|--------|----------|--------------|-------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | +400.00 |

Other loans (e.g., `LN-2020-00398`) pass this check correctly:
`1,842.56 + 815.50 + 266.12 + 0.00 = 2,924.18 ✓`

### Business Impact

Financial reporting and reconciliation will be incorrect. Downstream systems consuming payment
breakdowns may display impossible allocations, leading to audit failures and incorrect
escrow/principal accounting.

### Recommended Fix

Investigate whether `PMT_AMT` (total) or the component breakdown is correct for loan
`LN-2019-00142`. The consistent +400.00 delta across both payments suggests a systematic error
in the escrow allocation during data ingestion. Validate against source-of-record and apply
correction. Add a check constraint or validation rule: `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`.

---

## Anomaly #2: SSN Last-4 Digits Match Phone Number (Not Actual SSN)

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

### Description

The `BORR_SSN_LST4` column in `CDW_LN_ACCT` is intended to store the last 4 digits of the
borrower's Social Security Number for identity verification. Instead, every record contains
the last 4 digits of the borrower's phone number from `CDW_BORR_MSTR.BORR_PH_NBR`.

### Example Bad Records

| LN_ACCT_NBR | BORR_SSN_LST4 | BORR_PH_NBR (from CDW_BORR_MSTR) | Match? |
|-------------|---------------|-----------------------------------|--------|
| LN-2019-00142 | 0142 | 217-555-**0142** | Phone last 4 |
| LN-2020-00398 | 0198 | 503-555-**0198** | Phone last 4 |
| LN-2018-00089 | 0167 | 512-555-**0167** | Phone last 4 |
| LN-2021-00567 | 0134 | 303-555-**0134** | Phone last 4 |
| LN-2017-00034 | 0156 | 602-555-**0156** | Phone last 4 |

All 5 records exhibit this pattern — 100% of the data is affected.

### Business Impact

- **Identity verification failures:** Any process using SSN last-4 for borrower identity
  verification will fail or produce false positives.
- **Compliance risk:** KYC (Know Your Customer) and identity matching processes are unreliable.
- **Data migration risk:** Migrating this column to a modern schema will propagate the error.

### Recommended Fix

Do not migrate `BORR_SSN_LST4` from `CDW_LN_ACCT`. Instead, derive SSN last-4 from
`CDW_BORR_MSTR.BORR_SSN_ENCR` (after decryption) or flag the field as untrusted.
Add a data quality flag when this field is consumed.

---

## Anomaly #3: Numeric Amounts Stored as Strings with Commas

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Description

All monetary values are stored as `VARCHAR` with embedded thousands-separator commas
(e.g., `'285,000'`, `'1,487.02'`). The service layer's `parseLegacyAmount()` removes commas
before parsing, but there is no protection against:
- Dollar signs (`$285,000`)
- Spaces or non-breaking spaces
- Negative amounts in parentheses `(1,200.00)` (accounting format)
- Empty strings or whitespace-only values
- Non-ASCII digit characters

### Example Values

| Table | Column | Example Value | Parsing Risk |
|-------|--------|---------------|--------------|
| CDW_BORR_MSTR | BORR_ANN_INCM | `'92,500'` | If `$` prefix added → NumberFormatException |
| CDW_LN_ACCT | LN_ORIG_AMT | `'285,000'` | Ambiguous: is this 285,000.00 or 285.000 (European)? |
| CDW_LN_ACCT | LN_CURR_BAL | `'271,432.56'` | Current records OK, but format not validated |
| CDW_PMT_HIST | PMT_LATE_FEE | `'0.00'` | OK, but `'N/A'` or blank would crash |

### Business Impact

Any non-conforming value will cause an unhandled `NumberFormatException` in `LoanService.parseLegacyAmount()`,
resulting in a 500 Internal Server Error for the entire API response (not just the affected record).
One bad record poisons the entire loan listing.

### Recommended Fix

Add defensive parsing with try-catch in `parseLegacyAmount()`. Strip `$`, whitespace, and handle
parenthesized negatives. Return a fallback value (zero) with logging for unparseable records rather
than crashing the entire request.

---

## Anomaly #4: Date Fields Stored as Strings Without Validation

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | All four tables |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT` |

### Description

All date fields are stored as `VARCHAR(10)` with expected format `MM/DD/YYYY`. The schema
imposes no format constraint — any string up to 10 characters is accepted. The service layer
passes dates through to the API response as raw strings without parsing or validation.

Potential failure modes:
- Invalid dates (e.g., `02/30/2020`, `13/01/2020`)
- Alternative formats (e.g., `2020-01-15`, `15/01/2020`)
- Partial dates (e.g., `01/2020`, `2020`)
- Placeholder values (e.g., `00/00/0000`, `99/99/9999`)

### Example Values (Current Data)

All current seed data uses consistent `MM/DD/YYYY` format, but there is no enforcement
preventing future inserts with inconsistent formats.

### Business Impact

- API consumers cannot reliably parse date strings returned in responses
- Date-based sorting/filtering on `PMT_DT` uses lexicographic VARCHAR ordering (12/01 < 12/15 works, but 01/01 < 12/01 also works by accident — `02/...` < `11/...` ✓ only because month is zero-padded)
- Migration to typed DATE columns will fail for any non-conforming records

### Recommended Fix

Parse all dates through `DateTimeFormatter.ofPattern("MM/dd/yyyy")` in the service layer.
Return standardized ISO-8601 format (`yyyy-MM-dd`) in API responses. Log and handle
`DateTimeParseException` gracefully.

---

## Anomaly #5: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Description

The legacy schema defines no foreign key constraints between tables. Referential integrity
is not enforced at the database level:
- `CDW_LN_ACCT.BORR_ID` may reference a non-existent borrower
- `CDW_LN_ACCT.PROD_CD` may reference a non-existent product
- `CDW_PMT_HIST.LN_ACCT_NBR` may reference a non-existent loan account

### Example Failure Scenario

If a payment record references `LN_ACCT_NBR = 'LN-DELETED-001'` (a loan that was purged from
`CDW_LN_ACCT`), the service layer's `getPaymentsByLoan()` would return payment records for
a loan that doesn't exist, while `getLoanById('LN-DELETED-001')` throws RuntimeException.

In the current service code (`getAllLoans()` at line 54), `products.get(acct.getProductCode())`
returns `null` for an invalid product code, which is handled by falling back to the raw code
string — but silently degrades the API response.

### Business Impact

- API consumers receive incomplete or inconsistent data
- Loan summaries may show raw product codes instead of descriptions
- Payment data may exist for loans that have been removed, causing reconciliation issues

### Recommended Fix

Validate referential integrity at the service layer: confirm that referenced entities exist
before constructing DTOs. Log warnings for orphaned references and include a data quality
indicator in the API response.

---

## Anomaly #6: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

### Description

Borrower first name, last name, and SSN last-4 are stored redundantly in `CDW_LN_ACCT`
alongside the `BORR_ID` reference. The service uses the denormalized loan-account copy
(line 106: `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`) for the
loan summary, NOT the authoritative borrower master record.

If a borrower updates their name (e.g., after marriage), the `CDW_BORR_MSTR` record may
be updated while `CDW_LN_ACCT` retains the old name.

### Example (Hypothetical)

| Source | First Name | Last Name |
|--------|-----------|-----------|
| CDW_BORR_MSTR (B-10002) | Sarah | Chen-Williams |
| CDW_LN_ACCT (LN-2020-00398) | Sarah | Chen |

### Business Impact

- Customer-facing loan statements may display outdated names
- Search by name in the borrower table won't find loans displayed under the old name
- Compliance reporting shows inconsistent borrower identity

### Recommended Fix

Always source borrower display data from `CDW_BORR_MSTR` (the authoritative record).
Use `BORR_ID` to join rather than relying on denormalized copies. Add a validation check
that flags discrepancies between the master and denormalized copies.

---

## Anomaly #7: Delinquency Days Inconsistent with Payment Timing

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `LN_DLQ_DAYS`, `PMT_DT`, `PMT_RECV_DT` |

### Description

Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'`, but the most recent late payment
(`PMT-2025110003`) was received on `11/18/2025` for a payment due `11/01/2025` —
that is 17 days late, not 15. The delinquency days field appears to be a stale snapshot
that is not updated in sync with payment receipt dates.

### Example Bad Record

| Field | Value |
|-------|-------|
| Loan | LN-2018-00089 |
| LN_DLQ_DAYS | 15 |
| PMT-2025110003 due date | 11/01/2025 |
| PMT-2025110003 received | 11/18/2025 |
| Actual days late | 17 |

Additionally, `PMT-2025110003` has a late fee of `$47.50`, confirming the payment was late.

### Business Impact

- Delinquency reporting is inaccurate
- Risk scoring models using `LN_DLQ_DAYS` receive stale data
- Regulatory reporting (e.g., to credit bureaus) may understate delinquency

### Recommended Fix

Compute delinquency days dynamically from payment history rather than relying on the static
`LN_DLQ_DAYS` field. Flag records where stated delinquency does not match computed value.

---

## Anomaly #8: Credit Score Stored as String (Integer Parsing Risk)

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_CRDT_SCR` |

### Description

Credit scores are stored as `VARCHAR(5)`. The service layer parses them via
`Integer.parseInt(value.trim())`. This will throw `NumberFormatException` for:
- Non-numeric values (e.g., `'N/A'`, `'---'`, `'PEND'`)
- Decimal values (e.g., `'745.5'`)
- Out-of-range values (e.g., `'9999'`, `'-1'`)

Credit scores have a valid range of 300–850 (FICO). The current data contains values
like `658`, `692`, `745`, `780`, `810` — all valid. But there is no range validation.

### Example Risk

If a record has `BORR_CRDT_SCR = 'N/A'` (common placeholder for unknown credit):
- `parseLegacyInteger("N/A")` → `NumberFormatException` → 500 error
- The entire `/api/borrowers` endpoint crashes (not just the bad record)

### Business Impact

One borrower with a non-numeric credit score takes down the entire borrower listing API.

### Recommended Fix

Validate credit score is numeric and within FICO range (300–850). Return null for
unparseable values with a warning log. Do not let one bad record crash the full listing.

---

## Anomaly #9: NULL Middle Initial Handling

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_MID_INIT` |

### Description

Borrower `B-10005` (Robert Williams) has a NULL middle initial. The service layer handles this
correctly (line 123: conditional inclusion), but the API response format is inconsistent —
some borrowers get `"James R. Mitchell"` while others get `"Robert Williams"` (no period or
space for the missing initial).

### Business Impact

Minor cosmetic inconsistency in API responses. Not a functional issue but may confuse
downstream name-matching logic.

### Recommended Fix

Document that middle initial is optional and the full name format varies accordingly.
This is low severity and acceptable behavior.

---

## Anomaly #10: Property Address Concatenation with Potential NULLs

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `PROP_ADDR_LN1`, `PROP_CTY_NM`, `PROP_ST_CD`, `PROP_ZIP_CD` |

### Description

The service concatenates property address fields (line 114):
```java
acct.getPropertyAddress() + ", " + acct.getPropertyCity() + ", " + acct.getPropertyState() + " " + acct.getPropertyZip()
```

If any of these fields are NULL, the result would be `"null, null, null null"` which appears
in API responses as literal "null" text.

### Example (Hypothetical)

If a loan has no property city: `"742 Elm Street, null, IL 62701"`

### Business Impact

API consumers may display literal "null" text to end users. Property address lookups
and geocoding will fail.

### Recommended Fix

Add null-safe concatenation that skips null/empty components. Use a dedicated address
formatting utility.

---

## Summary

| # | Anomaly | Severity | Tables Affected |
|---|---------|----------|----------------|
| 1 | Payment component sum ≠ total | Critical | CDW_PMT_HIST |
| 2 | SSN last-4 matches phone, not SSN | Critical | CDW_LN_ACCT |
| 3 | Numeric amounts as comma-strings | High | All tables |
| 4 | Date strings without validation | High | All tables |
| 5 | No FK constraints (orphan risk) | High | CDW_LN_ACCT, CDW_PMT_HIST |
| 6 | Denormalized borrower data drift | Medium | CDW_LN_ACCT |
| 7 | Delinquency days stale/inconsistent | Medium | CDW_LN_ACCT |
| 8 | Credit score string parsing risk | Medium | CDW_BORR_MSTR |
| 9 | NULL middle initial formatting | Low | CDW_BORR_MSTR |
| 10 | Address concatenation with NULLs | Low | CDW_LN_ACCT |
