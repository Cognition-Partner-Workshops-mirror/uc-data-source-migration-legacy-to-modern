# Data Anomaly Report — Legacy CDW Tables

## Summary

Analysis of `src/main/resources/schema-legacy.sql` and `src/main/resources/data-legacy.sql` revealed **8 distinct anomalies** across 4 legacy tables. The legacy CDW schema stores all values as VARCHAR with no foreign key constraints, creating systemic risks around type coercion, referential integrity, and data consistency.

---

## ANM-001: SSN Last-4 Populated with Phone Number Suffixes

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

### Description

The `BORR_SSN_LST4` column, intended to store the last 4 digits of the borrower's Social Security Number, is instead populated with the last 4 digits of the borrower's phone number from `CDW_BORR_MSTR.BORR_PH_NBR`.

### Example Bad Records

| LN_ACCT_NBR | BORR_SSN_LST4 | Borrower Phone (CDW_BORR_MSTR) | Phone Last 4 |
|-------------|---------------|-------------------------------|--------------|
| LN-2019-00142 | 0142 | 217-555-**0142** | 0142 |
| LN-2020-00398 | 0198 | 503-555-**0198** | 0198 |
| LN-2018-00089 | 0167 | 512-555-**0167** | 0167 |
| LN-2021-00567 | 0134 | 303-555-**0134** | 0134 |
| LN-2017-00034 | 0156 | 602-555-**0156** | 0156 |

All 5 records (100%) exhibit this pattern — zero have valid SSN last-4 data.

### Business Impact

- **Regulatory compliance failure**: SSN-based identity verification returns incorrect results
- **Fraud risk**: Borrower identity cannot be validated against SSN
- **Downstream migration corruption**: Modern schema `ssn_hash` field would be populated with phone-derived data

### Recommended Fix

- Flag all `BORR_SSN_LST4` values as untrusted
- Cross-reference with encrypted SSN in `CDW_BORR_MSTR.BORR_SSN_ENCR` to derive correct last-4
- Add validation that `BORR_SSN_LST4` is exactly 4 numeric digits and does NOT match the phone suffix

---

## ANM-002: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Description

For loan `LN-2019-00142` (borrower Mitchell), the sum of payment components (principal + interest + escrow + late fee) does not equal the stated total payment amount.

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT (Total) | Components Sum | Difference |
|-------------|-----------------|----------------|------------|
| PMT-2025120001 | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | +400.00 |

Payments for other loans (LN-2020-00398, LN-2021-00567, LN-2017-00034) sum correctly.

### Business Impact

- **Financial reporting errors**: Balance calculations and amortization schedules will be incorrect
- **Audit failures**: Payment reconciliation will not balance
- **API response inaccuracy**: Consumers receive mathematically inconsistent payment data

### Recommended Fix

- Validate at ingestion that `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE = PMT_AMT`
- Flag records that fail validation for manual review
- Determine if the total or components are authoritative and recalculate the other

---

## ANM-003: Numeric Fields Stored as Strings with No Parse Validation

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_DLQ_DAYS`, `LN_LTV_PCT`, `PROD_TERM_MOS`, all `PMT_*_AMT` columns |

### Description

All numeric values are stored as VARCHAR strings. The service layer parses these with `Integer.parseInt()` and `new BigDecimal()` with no try-catch or format validation. Any non-numeric content (e.g., "N/A", "$285,000", "TBD", empty strings with whitespace) will cause unhandled `NumberFormatException` at runtime.

### Example Risk Scenarios

| Column | Valid Value | Potential Bad Value | Result |
|--------|------------|--------------------|---------| 
| `BORR_CRDT_SCR` | "745" | "N/A" or "---" | `NumberFormatException` in `parseLegacyInteger()` |
| `BORR_ANN_INCM` | "92,500" | "$92,500" or "92500.00" | `NumberFormatException` in `parseLegacyAmount()` |
| `LN_INT_RT` | "4.750" | "4.75%" | `NumberFormatException` in `parseLegacyDecimal()` |
| `LN_DLQ_DAYS` | "15" | "" (empty) or "N/A" | `NumberFormatException` |

### Business Impact

- **Runtime crashes**: Unhandled exceptions propagate as HTTP 500 errors
- **Service unavailability**: A single bad record can break the entire `/api/loans` endpoint
- **Silent data loss**: `BigDecimal.ZERO` fallback for blank values hides missing data

### Recommended Fix

- Wrap all parsing in try-catch with structured error logging
- Implement type coercion with fallback defaults
- Add pre-parse validation (regex or pattern matching) before conversion

---

## ANM-004: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Description

The legacy schema explicitly has **no foreign key constraints**. Loan accounts can reference non-existent borrowers or products, and payments can reference non-existent loans. The service code at `LoanService.java:54` performs `products.get(acct.getProductCode())` which returns `null` for unknown product codes, and the code at line 107 falls back to using the raw product code string — masking the data integrity issue.

### Example Risk Scenarios

| Relationship | Parent Table | Child Reference | Current Handling |
|---|---|---|---|
| Loan → Borrower | `CDW_BORR_MSTR` | `CDW_LN_ACCT.BORR_ID` | No validation; would produce "null null" in borrower name |
| Loan → Product | `CDW_LN_PROD` | `CDW_LN_ACCT.PROD_CD` | Falls back to raw code string silently |
| Payment → Loan | `CDW_LN_ACCT` | `CDW_PMT_HIST.LN_ACCT_NBR` | No validation at query time |

### Business Impact

- **Incomplete API responses**: Orphaned loans return raw codes instead of descriptions
- **NullPointerException risk**: If borrower lookup fails, name concatenation produces "null null"
- **Data migration failures**: Modern schema with real FKs will reject orphaned records

### Recommended Fix

- Validate referential integrity at ingestion time
- Log warnings for orphaned references
- Provide fallback values with clear indication that data is missing

---

## ANM-005: Delinquent Loan with Inconsistent Status Code

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

### Description

Loan `LN-2018-00089` (borrower Torres) has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'` (Active). A loan 15 days delinquent should typically be flagged with a warning status. Additionally, the corresponding payment `PMT-2025110003` has a late fee of $47.50, confirming delinquency, yet the loan status remains unchanged.

### Example Bad Records

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Late Fee in Payment |
|-------------|-------------|------------|---------------------|
| LN-2018-00089 | 15 | ACT | $47.50 (PMT-2025110003) |

### Business Impact

- **Incorrect risk reporting**: Delinquent loans not flagged in portfolio risk dashboards
- **Regulatory non-compliance**: Delinquency reporting thresholds may be missed
- **Customer communication gaps**: Borrower not notified of delinquent status

### Recommended Fix

- Add business rule validation: if `LN_DLQ_DAYS > 0` and status is `ACT`, flag as anomaly
- Consider auto-escalation rules (e.g., >30 days → DFT status)

---

## ANM-006: Late Fee Inclusion Inconsistency in Payment Totals

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_LATE_FEE` |

### Description

The treatment of late fees in payment totals is inconsistent across records. For `PMT-2025110003`, the total is `1,077.05` which equals principal + interest (`295.82 + 781.23 = 1,077.05`) but the late fee of `47.50` is NOT included in the total. This contrasts with escrow amounts which ARE included in totals for other loans.

### Example Records

| PMT_SEQ_NBR | PMT_AMT | prin + int | + escrow | + late_fee | Expected Total |
|-------------|---------|-----------|----------|------------|----------------|
| PMT-2025120002 | 2,924.18 | 2,658.06 | +266.12 = 2,924.18 | +0 = 2,924.18 | Consistent |
| PMT-2025110003 | 1,077.05 | 1,077.05 | +0 = 1,077.05 | +47.50 = 1,124.55 | **Inconsistent** |

### Business Impact

- **Accounting discrepancies**: Total amount field meaning varies by record
- **Collection tracking errors**: Late fee revenue may be under-reported
- **API consumer confusion**: No way to determine what "total" includes

### Recommended Fix

- Establish consistent rule: total should ALWAYS equal sum of all components
- Validate component sum equals total at ingestion; flag discrepancies

---

## ANM-007: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

### Description

`CDW_LN_ACCT` contains denormalized copies of borrower data (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) alongside the `BORR_ID` foreign key reference. These fields can drift from the source of truth in `CDW_BORR_MSTR` if borrower records are updated (e.g., name change after marriage) without cascading to loan accounts.

### Current Data (No Drift Yet)

| LN_ACCT_NBR | BORR_FST_NM (Loan) | BORR_FST_NM (Master) | Match? |
|-------------|--------------------|-----------------------|--------|
| LN-2019-00142 | James | James | Yes |
| LN-2020-00398 | Sarah | Sarah | Yes |

While current seed data shows no drift, the architecture guarantees eventual inconsistency at scale.

### Business Impact

- **Identity confusion**: API could return different names for same borrower depending on endpoint
- **Legal liability**: Incorrect borrower name on loan documents

### Recommended Fix

- At ingestion, cross-validate denormalized fields against master table
- Log warnings when drift is detected
- Prefer master table as source of truth in service layer

---

## ANM-008: Date Strings with No Format Validation

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Tables** | All tables |
| **Affected Columns** | All `*_DT` columns (`BORR_DOB_DT`, `BORR_CRET_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.) |

### Description

All date fields are stored as VARCHAR(10) with an expected format of `MM/DD/YYYY`. The service layer passes these strings directly to DTOs without parsing or validating the format. Legacy systems commonly produce dates in alternate formats (`YYYY-MM-DD`, `DD/MM/YYYY`, `M/D/YYYY`) that would pass through silently.

### Example Risk Scenarios

| Column | Expected | Potential Bad Values |
|--------|----------|---------------------|
| `BORR_DOB_DT` | "03/15/1978" | "1978-03-15", "15/03/1978", "3/15/78" |
| `LN_ORIG_DT` | "02/15/2019" | "2019-02-15", "02-15-2019" |

### Business Impact

- **Date comparison failures**: String-based sorting of dates produces wrong order
- **Migration parsing errors**: `MM/DD/YYYY → DATE` conversion will fail on unexpected formats
- **API inconsistency**: Consumers receive dates in unpredictable formats

### Recommended Fix

- Validate date strings match `MM/DD/YYYY` pattern at ingestion
- Parse and re-format dates to ensure consistency
- Return ISO-8601 format (`YYYY-MM-DD`) in API responses
