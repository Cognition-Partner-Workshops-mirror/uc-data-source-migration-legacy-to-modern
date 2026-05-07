# Data Anomaly Report — Legacy CDW Tables

## Summary

Analysis of the legacy Corporate Data Warehouse (CDW) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`) revealed **8 anomalies** spanning data integrity, type safety, referential integrity, and compliance concerns.

---

## Anomaly #1: Payment Component Amounts Exceed Total Payment

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT` |

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT (Total) | Principal + Interest + Escrow | Discrepancy |
|-------------|-----------------|-------------------------------|-------------|
| PMT-2025120001 | 1,487.02 | 456.78 + 1,074.69 + 355.55 = 1,887.02 | +$400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 + 1,076.50 + 355.55 = 1,887.02 | +$400.00 |
| PMT-2025110003 | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 (late fee) = 1,124.55 | +$47.50 |

### Business Impact

Financial reporting will be inaccurate. Downstream systems relying on the total payment amount for reconciliation will produce incorrect balances. Regulatory filings (TILA, RESPA) require accurate payment breakdowns.

### Recommended Fix

Add a validation rule that asserts `principal + interest + escrow + late_fee == total` (within a tolerance of $0.01). Flag records that fail this check and route them to a reconciliation queue.

---

## Anomaly #2: SSN Last-4 Field Contains Phone Number Suffixes

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

### Example Bad Records

| LN_ACCT_NBR | BORR_SSN_LST4 | BORR_PH_NBR (from CDW_BORR_MSTR) | Match? |
|-------------|---------------|-----------------------------------|--------|
| LN-2019-00142 | 0142 | 217-555-**0142** | Phone suffix |
| LN-2020-00398 | 0198 | 503-555-**0198** | Phone suffix |
| LN-2018-00089 | 0167 | 512-555-**0167** | Phone suffix |
| LN-2021-00567 | 0134 | 303-555-**0134** | Phone suffix |
| LN-2017-00034 | 0156 | 602-555-**0156** | Phone suffix |

All 5 records (100%) have SSN last-4 values that exactly match the phone number suffix.

### Business Impact

This is a PII compliance violation. The field purported to contain partial SSN data actually contains phone number fragments. Any system or report relying on SSN last-4 for identity verification (KYC, fraud detection, IRS reporting) is using incorrect data. Potential regulatory exposure under GLBA and FCRA.

### Recommended Fix

Flag all `BORR_SSN_LST4` values as unreliable. Cross-reference with the encrypted SSN field (`BORR_SSN_ENCR` in `CDW_BORR_MSTR`) to derive correct values. Until corrected, prevent downstream systems from using this field for identity verification.

---

## Anomaly #3: Numeric Values Stored as Strings With Parsing Risks

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_DLQ_DAYS`, `LN_LTV_PCT`, `LN_ESCROW_BAL`, `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Example Bad Record Patterns (Potential)

The schema allows ANY string in these VARCHAR columns. Known risky patterns in CDW systems:
- Dollar signs: `"$285,000"` → `NumberFormatException` in `parseLegacyAmount()`
- Text markers: `"N/A"`, `"PENDING"`, `""` → `NumberFormatException`
- Whitespace: `" 745 "` (handled by trim) vs `"7 45"` (not handled)
- Locale issues: `"285.000,00"` (European format) → incorrect parse

Current seed data uses clean formats (`"285,000"`, `"745"`), but the VARCHAR schema imposes no constraint preventing corrupt values from entering production.

### Business Impact

Any malformed numeric string causes an unhandled `NumberFormatException` at runtime, resulting in HTTP 500 errors from the API. The entire loan summary or borrower detail response fails — not just the one bad field.

### Recommended Fix

Wrap all `parseLegacyAmount`, `parseLegacyDecimal`, and `parseLegacyInteger` calls in validation that catches `NumberFormatException`, logs the bad value, and returns a safe default (zero for amounts, null for optional fields).

---

## Anomaly #4: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Example Bad Record Patterns (Potential)

The schema has zero foreign key constraints:
- A loan account could reference `BORR_ID = 'B-99999'` (non-existent borrower)
- A loan could reference `PROD_CD = 'INVALID'` (non-existent product)
- A payment could reference `LN_ACCT_NBR = 'LN-DELETED'` (non-existent loan)

### Business Impact

- `LoanService.getAllLoans()`: `products.get(acct.getProductCode())` returns `null` for orphaned product codes → product description falls back to raw code (graceful degradation)
- `LoanService.getBorrowerById()`: Borrower found but `loanAccountRepository.findByBorrowerId()` could return loans with orphaned product refs
- No way to detect orphaned payments — they simply appear in query results with invalid loan references

### Recommended Fix

Add referential integrity validation at the service layer. Before processing, verify that referenced entities exist. Log and quarantine orphaned records.

---

## Anomaly #5: Date Strings Without Format Validation

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | All tables |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT` |

### Example Bad Record Patterns (Potential)

Schema specifies `VARCHAR(10)` for all dates with comment "stored as MM/DD/YYYY". No enforcement exists for:
- Invalid dates: `"02/30/2020"`, `"13/15/2025"`, `"00/00/0000"`
- Wrong format: `"2020-03-15"` (ISO), `"15/03/2020"` (DD/MM/YYYY)
- Partial dates: `"03/2020"`, `"2020"`
- Null/blank: empty string `""` vs SQL `NULL`

The service layer passes date strings directly to DTOs without any parsing or validation (e.g., `dto.setOriginationDate(acct.getOriginationDate())`).

### Business Impact

Downstream consumers receiving raw date strings cannot reliably parse them. The column_mappings.md specifies conversion to DATE type, but no code validates or converts dates. Any report needing date-based filtering or sorting will malfunction.

### Recommended Fix

Parse all date strings using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` with strict parsing. Catch `DateTimeParseException` and log invalid dates. Return ISO-8601 format (`yyyy-MM-dd`) in API responses.

---

## Anomaly #6: Denormalized Borrower Data Inconsistency Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM` (vs. `CDW_BORR_MSTR.BORR_FST_NM`, `BORR_LST_NM`) |

### Example Bad Record Patterns

The loan account table embeds borrower name fields that duplicate the borrower master:
- `GET /api/loans` → Uses `CDW_LN_ACCT.BORR_FST_NM` + `CDW_LN_ACCT.BORR_LST_NM`
- `GET /api/borrowers/{id}` → Uses `CDW_BORR_MSTR.BORR_FST_NM` + `CDW_BORR_MSTR.BORR_LST_NM`

If a borrower's name changes in the master table but the loan account table is not updated, the API returns different names for the same person depending on which endpoint is called.

### Business Impact

Inconsistent customer names across API responses undermines system trustworthiness. Could cause customer service confusion and compliance issues with name-matching processes.

### Recommended Fix

During ingestion, validate that denormalized fields match their source in the master table. Log discrepancies and prefer the master table as the source of truth.

---

## Anomaly #7: No NOT NULL Constraints on Required Business Fields

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | All tables |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `LN_ACCT_NBR.BORR_ID`, `LN_ORIG_AMT`, `LN_STAT_CD`, `PMT_AMT`, `PMT_STAT_CD` |

### Example Bad Record Patterns (Potential)

The schema allows NULL in every non-PK column. Business-critical fields that should never be null:
- Borrower first/last name → `toBorrowerDto()` would produce `"null null"` as full name
- Loan original amount → `parseLegacyAmount(null)` returns `BigDecimal.ZERO` (misleading)
- Loan status code → `expandStatusCode(null)` returns `"Unknown"` (data loss)
- Payment total amount → appears as $0.00 (incorrect)

### Business Impact

Null values in required fields silently produce incorrect API responses (zero amounts, "Unknown" statuses, "null" in names) rather than failing fast. This masks data quality issues from consumers.

### Recommended Fix

Add null-checks for required fields at ingestion time. Reject records with null required fields and route them to an error queue for remediation.

---

## Anomaly #8: Unvalidated Status Codes

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_BORR_MSTR`, `CDW_LN_PROD` |
| **Affected Columns** | `LN_STAT_CD`, `PMT_STAT_CD`, `PMT_TYP_CD`, `BORR_STAT_CD`, `PROD_STAT_CD`, `PROP_TYP_CD` |

### Example Bad Record Patterns (Potential)

Valid codes per the service layer:
- Loan status: ACT, CLO, DFT, FRB
- Payment status: PST, REV, NSF, PND
- Payment type: REG, EXT, PRT, PRE
- Property type: SFR, CND, MFR, TWN

The schema has no CHECK constraints. Invalid codes like `"XXX"`, `"   "`, or `"ACTIVE"` (full word instead of abbreviation) would pass through `expandStatusCode()` and be returned as-is in the API response.

### Business Impact

API consumers expecting a known set of status values will encounter unexpected values. Any UI or reporting system with hardcoded status handling will break or display raw codes to end users.

### Recommended Fix

Validate status codes against an allowed set at ingestion time. Reject or map unknown codes to a safe default with logging.
