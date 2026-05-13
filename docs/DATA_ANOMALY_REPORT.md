# Data Anomaly Report — Legacy CDW Tables

## Summary

Analysis of the legacy Corporate Data Warehouse (CDW) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`) reveals **8 data quality anomalies** ranging from Critical to Low severity. These affect financial accuracy, runtime stability, and data integrity.

---

## Anomaly #1: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |
| **Category** | Financial Integrity |

### Description
The sum of payment components (principal + interest + escrow + late fee) does not equal the total payment amount for multiple records.

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT (Total) | Component Sum | Discrepancy |
|-------------|-----------------|---------------|-------------|
| `PMT-2025120001` | 1,487.02 | 1,887.02 (456.78 + 1,074.69 + 355.55 + 0.00) | **+$400.00** |
| `PMT-2025110001` | 1,487.02 | 1,887.02 (454.97 + 1,076.50 + 355.55 + 0.00) | **+$400.00** |
| `PMT-2025110003` | 1,077.05 | 1,124.55 (295.82 + 781.23 + 0.00 + 47.50) | **+$47.50** |

### Business Impact
- Incorrect financial reporting and loan amortization schedules
- Regulatory compliance violations (TILA, RESPA disclosures)
- Customer disputes over payment allocation
- Potential misreporting to credit bureaus

### Recommended Fix
- Implement a payment component sum validation rule at ingestion time
- Flag records where `|total - (principal + interest + escrow + late_fee)| > $0.01`
- Apply a fallback strategy: recalculate total from components, or log discrepancy for manual review

---

## Anomaly #2: Numeric Strings Without Parsing Safeguards

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `BORR_CRDT_SCR`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, all `PMT_*_AMT` fields |
| **Category** | Runtime Failure Risk |

### Description
All financial amounts and numeric fields are stored as VARCHAR with embedded commas (e.g., `"285,000"`, `"1,487.02"`). The service layer uses `parseLegacyAmount()` and `parseLegacyInteger()` which throw uncaught `NumberFormatException` if the data contains currency symbols (`$`), text (`N/A`, `PENDING`), double decimals, or other non-numeric characters.

### Example Bad Records (Potential)
Current data is clean, but the VARCHAR schema accepts:
- `"$285,000"` — dollar sign causes `NumberFormatException`
- `"N/A"` or `"UNKNOWN"` — text in numeric fields
- `"1,487.02.5"` — malformed decimal
- `""` (empty string) — handled, but spaces like `"  "` are not fully covered

### Business Impact
- Unhandled `NumberFormatException` crashes the entire API request (HTTP 500)
- No partial results returned — one bad record in 10,000 poisons the whole response
- Zero observability into which record caused the failure

### Recommended Fix
- Wrap all parse operations in try-catch with per-record error logging
- Implement regex pre-validation to strip known noise characters (`$`, `%`, spaces)
- Return fallback value (e.g., `BigDecimal.ZERO`) and flag record as degraded
- Add a `DataQualityWarning` field in the DTO for transparency

---

## Anomaly #3: Null Values in Fields Used by String Concatenation

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_ID`, `PROP_ADDR_LN1`, `PROP_CTY_NM`, `PROP_ST_CD`, `PROP_ZIP_CD` |
| **Category** | Null Safety / NullPointerException |

### Description
The schema has NO `NOT NULL` constraints on any column. The service layer performs string concatenation without null checks:
- `LoanService.java:106`: `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`
- `LoanService.java:114`: `acct.getPropertyAddress() + ", " + acct.getPropertyCity() + ...`

If `BORR_FST_NM` or `PROP_ADDR_LN1` is null, the output will contain the literal string `"null"` (Java's String concatenation of null).

### Example Bad Records
- All current records have names populated, but no schema constraint prevents:
  ```sql
  INSERT INTO CDW_BORR_MSTR VALUES ('B-10099', NULL, 'Smith', ...);
  ```
  Result: `borrowerName = "null Smith"` in API response.

### Business Impact
- API returns `"null Smith"` or `"null, null, null null"` for property addresses
- Downstream systems parsing these strings may fail or produce garbage data
- Customer-facing applications display "null" text to users

### Recommended Fix
- Add null-safe concatenation with `Objects.toString(value, "")` or ternary checks
- Validate required fields at ingestion; reject or flag records missing critical identifiers
- Add `@NotNull` validation annotations on fields that must be present

---

## Anomaly #4: SSN Last-4 Field Contains Phone Number Digits

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |
| **Category** | Data Integrity / Security |

### Description
The denormalized `BORR_SSN_LST4` field in `CDW_LN_ACCT` contains the last 4 digits of the borrower's **phone number** instead of their SSN.

### Example Bad Records

| LN_ACCT_NBR | BORR_SSN_LST4 | Borrower Phone | SSN Match? |
|-------------|---------------|----------------|------------|
| `LN-2019-00142` | `0142` | `217-555-0142` | Phone last 4 |
| `LN-2020-00398` | `0198` | `503-555-0198` | Phone last 4 |
| `LN-2018-00089` | `0167` | `512-555-0167` | Phone last 4 |
| `LN-2021-00567` | `0134` | `303-555-0134` | Phone last 4 |
| `LN-2017-00034` | `0156` | `602-555-0156` | Phone last 4 |

All 5 records exhibit this pattern — this is a systematic data entry/ETL error.

### Business Impact
- Identity verification failures when SSN last-4 is used for authentication
- Regulatory/compliance risk (mishandling of PII — incorrect data linkage)
- Fraud detection systems comparing SSN fragments will produce false negatives
- Customer confusion during support calls requiring SSN verification

### Recommended Fix
- Flag `BORR_SSN_LST4` as unreliable; do not use for identity verification
- Cross-reference against encrypted SSN in `CDW_BORR_MSTR.BORR_SSN_ENCR` if decryption is possible
- Add validation rule: SSN last-4 should not match phone number last-4

---

## Anomaly #5: Delinquency Days vs. Loan Status Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |
| **Category** | Business Logic Violation |

### Description
Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). Per standard mortgage servicing rules, a loan with >0 delinquency days should have a status that reflects this (e.g., `DLQ` for delinquent, or at minimum a sub-status indicator).

### Example Bad Records

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| `LN-2018-00089` | `15` | `ACT` | `DLQ` or `ACT` with delinquency flag |

### Business Impact
- Collections team may not be alerted to delinquent loans
- Reporting to regulators/investors understates portfolio delinquency
- Automated workflow triggers (late notices, fee assessment) may not fire
- Loss mitigation processes delayed

### Recommended Fix
- Implement cross-field validation: if `delinquencyDays > 0`, status must not be plain `ACT`
- Either update status to reflect delinquency or add a delinquency flag field
- Log warning when inconsistency detected

---

## Anomaly #6: Date Strings Not Validated or Parsed

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `PMT_DT`, etc. |
| **Category** | Data Type Safety |

### Description
All date fields are VARCHAR(10) expected to contain `MM/DD/YYYY` format. The service layer passes dates through as raw strings without parsing or validation (e.g., `LoanService.java:113`). Invalid dates like `02/30/2020`, `13/01/2020`, or `2020-01-15` (ISO format) would pass through silently.

### Example Bad Records (Potential)
Current data is well-formatted, but the VARCHAR schema accepts:
- `"02/30/2020"` — February 30th doesn't exist
- `"13/01/2020"` — month 13 invalid
- `"2020-01-15"` — ISO format instead of MM/DD/YYYY
- `"01/15/20"` — 2-digit year ambiguity
- `"N/A"` or `""` — non-date strings

### Business Impact
- Incorrect maturity date calculations
- Loan aging reports produce wrong delinquency windows
- Payment scheduling errors
- Downstream modern schema migration fails on date type conversion

### Recommended Fix
- Parse all date strings to `LocalDate` at ingestion with `MM/dd/yyyy` format
- Reject or flag records with unparseable dates
- Validate logical date constraints (DOB < today, origination < maturity, etc.)

---

## Anomaly #7: Orphaned Records Due to Missing FK Constraints

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |
| **Category** | Referential Integrity |

### Description
The legacy schema has NO foreign key constraints. This means:
- `CDW_LN_ACCT.BORR_ID` can reference a non-existent borrower
- `CDW_LN_ACCT.PROD_CD` can reference a non-existent product
- `CDW_PMT_HIST.LN_ACCT_NBR` can reference a non-existent loan

In `LoanService.getAllLoans()` (line 54), the product lookup `products.get(acct.getProductCode())` returns null for orphaned product codes, which is handled with a null-safe fallback. However, no warning is raised.

### Example Bad Records (Potential)
A payment with `LN_ACCT_NBR = 'LN-DELETED-001'` referencing a loan that was purged would:
- Return empty results from `getPaymentsByLoan()` — silently losing data
- Never surface the orphaned payment to API consumers

### Business Impact
- Silent data loss — payments without valid loans are invisible
- Product lookups return null, degrading loan summary data quality
- Borrower-to-loan relationships may be broken without detection
- Data migration to modern schema with actual FK constraints will fail

### Recommended Fix
- Validate referential integrity at ingestion time
- Check that `BORR_ID` exists in borrower table before accepting loan records
- Check that `LN_ACCT_NBR` exists in loan table before accepting payment records
- Log and quarantine orphaned records

---

## Anomaly #8: Denormalized Data Drift Between Tables

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_LN_ACCT` vs `CDW_BORR_MSTR` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_FST_NM`, `CDW_LN_ACCT.BORR_LST_NM` vs `CDW_BORR_MSTR.BORR_FST_NM`, `CDW_BORR_MSTR.BORR_LST_NM` |
| **Category** | Data Consistency |

### Description
Borrower names are stored redundantly in both `CDW_BORR_MSTR` and `CDW_LN_ACCT`. Without synchronization constraints, name changes in the master table may not propagate to the loan account table (or vice versa).

### Example Bad Records (Potential)
If borrower B-10002 changes last name from "Chen" to "Chen-Smith":
- `CDW_BORR_MSTR.BORR_LST_NM` = "Chen-Smith"
- `CDW_LN_ACCT.BORR_LST_NM` = "Chen" (stale)

The `toLoanSummary()` method uses the denormalized name from `CDW_LN_ACCT`, while `toBorrowerDto()` uses the master. This produces different names for the same person across API endpoints.

### Business Impact
- Inconsistent borrower names across `/api/loans` and `/api/borrowers` responses
- Customer confusion when loan documents show outdated names
- Legal/compliance issues if name on loan doesn't match current identity

### Recommended Fix
- Always source borrower name from the master table (`CDW_BORR_MSTR`)
- Add validation at ingestion comparing denormalized fields to master
- Log discrepancies and prefer master table as source of truth
