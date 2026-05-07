# Legacy Data Anomaly Report

**Generated:** 2026-05-07
**Source:** `src/main/resources/data-legacy.sql` and `src/main/resources/schema-legacy.sql`
**Database:** CDW (Corporate Data Warehouse) — H2 in-memory legacy simulation

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3     |
| High     | 3     |
| Medium   | 3     |
| Low      | 2     |
| **Total** | **11** |

---

## ANO-001: SSN Last-4 Contains Phone Number Digits Instead of SSN

**Severity:** Critical
**Affected Table:** `CDW_LN_ACCT`
**Affected Column:** `BORR_SSN_LST4`

**Description:**
The `BORR_SSN_LST4` field in every loan account record contains the last 4 digits of the borrower's phone number rather than the last 4 of their SSN. This is a systematic data-entry or ETL mapping error affecting 100% of records.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | Phone (from CDW_BORR_MSTR) | Phone Last 4 |
|-------------|---------|---------------|----------------------------|--------------|
| LN-2019-00142 | B-10001 | 0142 | 217-555-0142 | 0142 |
| LN-2020-00398 | B-10002 | 0198 | 503-555-0198 | 0198 |
| LN-2018-00089 | B-10003 | 0167 | 512-555-0167 | 0167 |
| LN-2021-00567 | B-10004 | 0134 | 303-555-0134 | 0134 |
| LN-2017-00034 | B-10005 | 0156 | 602-555-0156 | 0156 |

All 5/5 records (100%) are affected.

**Business Impact:**
- Identity verification failures when matching borrowers by SSN last 4
- Regulatory compliance risk (incorrect PII handling)
- Customer service operations using SSN last 4 for phone verification will match wrong data
- Potential fraud detection blind spots

**Recommended Fix:**
- Halt any downstream systems that rely on `BORR_SSN_LST4` for identity verification
- Re-extract correct SSN last-4 values from the encrypted SSN source (`BORR_SSN_ENCR` in `CDW_BORR_MSTR`)
- Add cross-field validation to ensure SSN last 4 does not match phone number last 4

---

## ANO-002: Payment Component Amounts Do Not Sum to Total

**Severity:** Critical
**Affected Table:** `CDW_PMT_HIST`
**Affected Columns:** `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`

**Description:**
For 3 out of 10 payment records (30%), the sum of principal + interest + escrow + late fee does not equal the stated total payment amount.

**Example Bad Records:**

| PMT_SEQ_NBR | Total (PMT_AMT) | Prin+Int+Escrow+Late | Difference | Issue |
|-------------|----------------|----------------------|------------|-------|
| PMT-2025120001 | 1,487.02 | 1,887.02 | +400.00 | Escrow (355.55) inflates sum beyond total |
| PMT-2025110001 | 1,487.02 | 1,887.02 | +400.00 | Escrow (355.55) inflates sum beyond total |
| PMT-2025110003 | 1,077.05 | 1,124.55 | +47.50 | Late fee (47.50) not reflected in total |

**Business Impact:**
- Financial reconciliation failures — ledger entries will not balance
- Regulatory audit findings (SOX, CFPB compliance)
- Incorrect interest/principal split reporting to borrowers
- Tax reporting errors (Form 1098 interest amounts)

**Recommended Fix:**
- Determine the authoritative source: is `PMT_AMT` the correct total, or are the components correct?
- For PMT-2025120001/PMT-2025110001: escrow amount (355.55) appears to be double-counted or the total should be 1,887.02
- For PMT-2025110003: total should include the late fee (correct total = 1,124.55)
- Add a CHECK constraint or application-level validation: `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`

---

## ANO-003: No Null Protection on Required Financial Fields

**Severity:** Critical
**Affected Tables:** `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_BORR_MSTR`
**Affected Columns:** All VARCHAR numeric/date fields (amounts, rates, dates, credit scores)

**Description:**
The legacy schema defines every column as nullable VARCHAR. There are no NOT NULL constraints on fields that are logically required (loan amounts, interest rates, payment amounts, borrower names). The service layer's `parseLegacyAmount()` and `parseLegacyInteger()` methods will return `BigDecimal.ZERO` or `null` for blank/null inputs without logging a warning, silently corrupting API responses.

**Example Risk Scenarios:**
- A loan with `LN_ORIG_AMT = NULL` would be parsed as `BigDecimal.ZERO` — a $0 loan appearing in API results
- A borrower with `BORR_CRDT_SCR = NULL` returns `null` credit score — NPE risk in downstream consumers
- A payment with `PMT_AMT = NULL` would be parsed as `BigDecimal.ZERO` — $0 payment in history

**Business Impact:**
- API consumers receive silently wrong financial data ($0 amounts instead of errors)
- Credit decisioning systems receive null credit scores
- Runtime `NumberFormatException` crashes if malformed strings like `"N/A"`, `"$285,000"`, or `"TBD"` appear in numeric fields

**Recommended Fix:**
- Add NOT NULL constraints in the modern schema (already done in `modern_tables.sql`)
- Add validation in the service layer that rejects or flags null/malformed values in required fields
- Log warnings for fallback defaults so data issues are visible

---

## ANO-004: No Foreign Key Constraints — Orphaned Records Possible

**Severity:** High
**Affected Tables:** `CDW_LN_ACCT`, `CDW_PMT_HIST`
**Affected Columns:** `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR`

**Description:**
The legacy schema has zero foreign key constraints. Referential integrity is not enforced at the database level. The service layer does a soft lookup (`products.get(acct.getProductCode())`) and passes `null` to `toLoanSummary()` when a product code doesn't match, silently degrading the response.

**Example Risk Scenarios:**
- A loan with `BORR_ID = 'B-99999'` (non-existent borrower) would be loaded without error
- A loan with `PROD_CD = 'INVALID'` would result in `product = null`, and the DTO would show the raw code instead of a description
- A payment with `LN_ACCT_NBR = 'LN-DELETED'` would be orphaned — retrievable but not linked to any loan

**Business Impact:**
- Orphaned payment records inflate or deflate loan payment histories
- Orphaned loans create phantom accounts in API responses
- Data migration to modern schema with FK constraints will fail on orphaned records

**Recommended Fix:**
- Add referential integrity validation in the service layer before returning DTOs
- During migration, run orphan detection queries and remediate before inserting into the modern schema
- Modern schema already defines proper FK constraints

---

## ANO-005: Denormalized Borrower Data Drift Risk

**Severity:** High
**Affected Table:** `CDW_LN_ACCT`
**Affected Columns:** `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`

**Description:**
Borrower name and SSN last 4 are duplicated in `CDW_LN_ACCT` (denormalized from `CDW_BORR_MSTR`). If the canonical borrower record is updated (e.g., name change after marriage), the loan account copy becomes stale. The service layer reads the denormalized name from `CDW_LN_ACCT` for the loan summary DTO (`acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`), so stale data would propagate to API consumers.

**Current Data Status:** Currently consistent across all 5 records (no active drift), but the architecture guarantees eventual drift.

**Business Impact:**
- Borrower name in loan detail may differ from borrower profile
- Legal documents generated from loan data may have wrong names
- Confusion in customer service when names don't match

**Recommended Fix:**
- Service layer should join to `CDW_BORR_MSTR` for authoritative borrower data instead of using denormalized fields
- Modern schema correctly normalizes this (borrower_id FK only, no duplicated fields)

---

## ANO-006: All Dates Stored as Unvalidated VARCHAR Strings

**Severity:** High
**Affected Tables:** All tables
**Affected Columns:** All `*_DT` columns (18 total date columns across 4 tables)

**Description:**
Dates are stored as `VARCHAR(10)` with an expected format of `MM/DD/YYYY` per schema comments, but there is no format validation at the database level. The service layer passes raw date strings directly to DTOs (`dto.setOriginationDate(acct.getOriginationDate())`) without parsing or validating them.

**Risks:**
- Dates in different formats (e.g., `YYYY-MM-DD`, `DD/MM/YYYY`) would be passed through undetected
- Invalid dates (e.g., `02/30/2025`, `13/01/2025`) would not be caught
- String-based date sorting in the repository (`findByLoanAccountNumberOrderByPaymentDateDesc`) sorts lexicographically, not chronologically — `12/01/2025` sorts before `02/01/2025` with string ordering

**Business Impact:**
- Payment history returned in wrong chronological order
- Date-based business logic (maturity calculations, next payment dates) unreliable
- Migration to DATE typed columns will fail on malformed date strings

**Recommended Fix:**
- Parse all date strings through `DateTimeFormatter.ofPattern("MM/dd/yyyy")` with strict validation
- Convert dates to ISO-8601 format (`yyyy-MM-dd`) in API responses
- Log and reject unparseable dates

---

## ANO-007: LTV Percentage Rounding Inconsistencies

**Severity:** Medium
**Affected Table:** `CDW_LN_ACCT`
**Affected Columns:** `LN_LTV_PCT`, `LN_ORIG_AMT`, `PROP_APRS_VAL`

**Description:**
The stored LTV percentages do not match computed values (`LN_ORIG_AMT / PROP_APRS_VAL * 100`) for 3 out of 5 loan records.

| LN_ACCT_NBR | Stored LTV | Computed LTV | Difference |
|-------------|-----------|-------------|------------|
| LN-2019-00142 | 82.5% | 82.6% | 0.1% |
| LN-2020-00398 | 68.2% | 68.3% | 0.1% |
| LN-2017-00034 | 80.0% | 80.1% | 0.1% |

**Business Impact:**
- Minor risk: LTV thresholds that trigger PMI (Private Mortgage Insurance) requirements (typically 80% LTV) could be misclassified — LN-2017-00034 at stated 80.0% vs actual 80.1% crosses the 80% threshold
- Inconsistent reporting to regulators

**Recommended Fix:**
- Recompute LTV from original amount and appraised value at query time rather than trusting stored values
- If storing pre-computed LTV, use consistent rounding rules (HALF_UP to 1 decimal place)

---

## ANO-008: Numeric Strings With Commas — Parsing Fragility

**Severity:** Medium
**Affected Tables:** `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST`
**Affected Columns:** All amount/income fields (15+ columns)

**Description:**
Financial amounts are stored as comma-formatted strings (e.g., `"285,000"`, `"1,487.02"`, `"92,500"`). The service layer strips commas via `amount.replace(",", "")` before parsing to `BigDecimal`. This approach fails silently for:
- Currency symbols: `"$285,000"` → `"$285000"` → `NumberFormatException`
- European format: `"285.000,00"` → `"285.00000"` → Wrong value
- Whitespace: `" 285,000 "` → parse failure (no trim before replace)
- Negative values: `"(285,000)"` accounting format → parse failure

**Current Data Status:** All current seed data uses consistent US comma formatting and parses correctly.

**Business Impact:**
- Any variation in upstream CDW formatting will crash the service with unhandled `NumberFormatException`
- Silent data corruption if European-formatted numbers enter the system

**Recommended Fix:**
- Implement robust parsing: trim whitespace, strip currency symbols, handle parenthetical negatives
- Wrap parsing in try-catch with meaningful error logging and fallback behavior
- Validate parsed amounts are within expected ranges

---

## ANO-009: Delinquency Days Inconsistent With Payment History

**Severity:** Medium
**Affected Table:** `CDW_LN_ACCT`, `CDW_PMT_HIST`
**Affected Columns:** `LN_DLQ_DAYS`, `PMT_DT`, `PMT_RECV_DT`

**Description:**
Loan LN-2018-00089 has `LN_DLQ_DAYS = '15'`, but its payment history shows the November 2025 payment was received 17 days late (payment date 11/01, received 11/18). The delinquency days value appears stale or incorrectly computed.

| Loan | DLQ_DAYS | Payment | PMT_DT | RECV_DT | Actual Days Late |
|------|----------|---------|--------|---------|-----------------|
| LN-2018-00089 | 15 | PMT-2025110003 | 11/01/2025 | 11/18/2025 | 17 |
| LN-2018-00089 | 15 | PMT-2025120003 | 12/01/2025 | 12/05/2025 | 4 |

**Business Impact:**
- Incorrect delinquency reporting to credit bureaus
- Risk scoring models use wrong delinquency data
- Regulatory reporting inaccuracies

**Recommended Fix:**
- Compute delinquency days dynamically from payment history rather than trusting stored value
- Add validation that flags discrepancies between stored DLQ_DAYS and actual payment lateness

---

## ANO-010: Status Codes Not Validated Against Known Values

**Severity:** Low
**Affected Tables:** All tables with `*_STAT_CD` columns
**Affected Columns:** `BORR_STAT_CD`, `LN_STAT_CD`, `PMT_STAT_CD`, `PROD_STAT_CD`

**Description:**
Status codes are stored as unconstrained VARCHAR. The service layer's `expandStatusCode()` methods have a `default -> code` fallback that passes unknown codes directly to the API response. If the CDW introduces a new status code or a typo occurs (e.g., `"ACTV"` instead of `"ACT"`), it leaks internal codes to API consumers.

**Current Data Status:** All current records use valid known codes.

**Business Impact:**
- Internal system codes leak to API consumers
- Frontend applications may not handle unknown status values gracefully
- Inconsistent display across different API consumers

**Recommended Fix:**
- Validate status codes against an allowed set at ingestion time
- Map unknown codes to a standard "UNKNOWN" status with warning logging
- Return a structured error or flag rather than passing through raw codes

---

## ANO-011: Record Type Field Has No Business Purpose Documentation

**Severity:** Low
**Affected Table:** `CDW_BORR_MSTR`
**Affected Column:** `BORR_REC_TYP`

**Description:**
All borrower records have `BORR_REC_TYP = 'PRI'`. The column mappings document says this field is "dropped" in the modern schema. However, if other values exist in production (e.g., `'SEC'` for secondary borrowers, `'CO'` for co-borrowers), dropping the field could lose information.

**Business Impact:**
- Low immediate risk since all current values are 'PRI'
- Potential data loss if the field carries meaning not represented elsewhere

**Recommended Fix:**
- Audit production CDW for all distinct `BORR_REC_TYP` values before dropping
- If other values exist, map them to a `borrower_type` field in the modern schema
