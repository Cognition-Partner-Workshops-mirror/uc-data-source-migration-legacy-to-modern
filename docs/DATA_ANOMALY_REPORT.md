# Legacy CDW Data Anomaly Report

> **Generated:** 2026-05-07
> **Source:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`
> **Scope:** CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST, CDW_LN_PROD

---

## ANM-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE |

**Description:** The sum of payment components (principal + interest + escrow + late fee) does not equal the total payment amount for several records. Financial data integrity is violated.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN+INT+ESCROW+LATE | Difference |
|-------------|---------|----------------------|------------|
| PMT-2025120001 | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = 1,887.02 | +400.00 |
| PMT-2025110003 | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = 1,124.55 | +47.50 |

**Business Impact:** Incorrect payment breakdowns cause misstated principal/interest allocations, wrong escrow accounting, and inaccurate amortization schedules. Downstream reporting (1098 tax forms, investor remittances) would contain errors.

**Recommended Fix:** Validate that `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE == PMT_AMT` at ingestion time. Flag mismatches for manual reconciliation. Do not propagate unbalanced payments to API consumers.

---

## ANM-002: SSN Last-4 Populated from Phone Numbers

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | BORR_SSN_LST4 |

**Description:** The denormalized `BORR_SSN_LST4` field in loan accounts matches the last 4 digits of the borrower's phone number rather than their actual SSN, across all records.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_SSN_LST4 | Borrower Phone (CDW_BORR_MSTR) | Phone Last 4 |
|-------------|---------------|-------------------------------|---------------|
| LN-2019-00142 | 0142 | 217-555-0142 | 0142 |
| LN-2020-00398 | 0198 | 503-555-0198 | 0198 |
| LN-2018-00089 | 0167 | 512-555-0167 | 0167 |
| LN-2021-00567 | 0134 | 303-555-0134 | 0134 |
| LN-2017-00034 | 0156 | 602-555-0156 | 0156 |

**Business Impact:** PII integrity is compromised. Identity verification using SSN last-4 would actually be checking phone digits. KYC/AML compliance is undermined. This is a regulatory risk (GLBA, FCRA).

**Recommended Fix:** Flag all BORR_SSN_LST4 values as untrusted. Cross-reference against the encrypted SSN in CDW_BORR_MSTR during migration. Do not use this field for identity verification until corrected.

---

## ANM-003: Delinquency Days vs. Loan Status Inconsistency

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | LN_DLQ_DAYS, LN_STAT_CD |

**Description:** Loan LN-2018-00089 shows 15 delinquent days but retains "ACT" (Active) status. Industry standard requires status change at 30+ days, but any non-zero delinquency on an "Active" loan should trigger review. The associated late payment (PMT-2025110003 with a $47.50 late fee) confirms the delinquency is real, not a data entry error.

**Example Bad Records:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Late Fee Evidence |
|-------------|-------------|------------|-------------------|
| LN-2018-00089 | 15 | ACT | PMT-2025110003: $47.50 late fee |

**Business Impact:** Risk exposure is understated. Delinquent loans appearing as active skew portfolio health metrics, reserve calculations, and regulatory reporting (Call Reports, HMDA).

**Recommended Fix:** Validate that delinquency days are consistent with loan status. Flag loans where `LN_DLQ_DAYS > 0` and `LN_STAT_CD = 'ACT'` for review. Consider adding a "DELINQUENT" or "WATCH" status.

---

## ANM-004: Payment Date Ordering Violations

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_DT, PMT_RECV_DT, PMT_PROC_DT |

**Description:** Some payment records have a payment date that precedes the received date, violating the expected temporal ordering (received >= payment date, processed >= received date).

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | PMT_PROC_DT | Issue |
|-------------|--------|-------------|-------------|-------|
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 12/06/2025 | Received 4 days after payment date |
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 11/19/2025 | Received 17 days after payment date |

**Business Impact:** Back-dated payments distort cash flow timing, delinquency calculations, and grace period enforcement. The 17-day gap on PMT-2025110003 corresponds to the delinquent loan (LN-2018-00089), suggesting the payment was late but the payment date was set to the due date rather than actual receipt.

**Recommended Fix:** Validate that `PMT_RECV_DT >= PMT_DT` and `PMT_PROC_DT >= PMT_RECV_DT`. Use received date for delinquency calculations rather than payment date.

---

## ANM-005: All Numeric Fields Stored as VARCHAR with Parsing Risks

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST, CDW_LN_PROD |
| **Affected Columns** | All amount, rate, score, and days columns |

**Description:** Every numeric value (amounts, rates, credit scores, term months, delinquency days) is stored as VARCHAR. The current `parseLegacyAmount()` method strips commas but has no error handling for malformed inputs (e.g., `"$285,000"`, `"N/A"`, `"--"`, `"TBD"`). A single corrupt record causes an unhandled `NumberFormatException` that crashes the entire API call.

**Example Risky Patterns:**
- `BORR_CRDT_SCR`: VARCHAR(5) parsed via `Integer.parseInt()` -- would fail on "N/A", "", or "780+"
- `LN_ORIG_AMT`: VARCHAR(15) parsed via `BigDecimal` -- would fail on "$285,000" or "285 000"
- `LN_DLQ_DAYS`: VARCHAR(5) -- never parsed in current code, but needed for validation
- `BORR_ANN_INCM`: Contains commas ("92,500") -- not currently parsed by the service

**Business Impact:** Any malformed numeric value in the legacy warehouse causes a 500 Internal Server Error on the API, taking down all loan/borrower queries. There is zero graceful degradation.

**Recommended Fix:** Wrap all parse operations in try-catch. Return fallback defaults or flag records as invalid. Log warnings for unparseable values rather than crashing.

---

## ANM-006: No Foreign Key Constraints -- Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | BORR_ID, PROD_CD, LN_ACCT_NBR |

**Description:** The legacy schema has zero foreign key constraints. `CDW_LN_ACCT.BORR_ID` is not enforced against `CDW_BORR_MSTR`, `PROD_CD` is not enforced against `CDW_LN_PROD`, and `CDW_PMT_HIST.LN_ACCT_NBR` is not enforced against `CDW_LN_ACCT`. An orphaned loan or payment would cause a NullPointerException in the service layer.

**Example Risk Path:**
- `getLoanById()` looks up product via `loanProductRepository.findById(acct.getProductCode())` which returns `Optional.empty()` for invalid product codes. The `orElse(null)` means `product` is null.
- `toLoanSummary()` handles null product with a ternary fallback to product code.
- But `getAllLoans()` builds a product map and calls `products.get(acct.getProductCode())` which returns null for unknown codes -- same null product path.
- An orphaned payment (invalid `LN_ACCT_NBR`) would silently return data referencing a non-existent loan.

**Business Impact:** Orphaned records produce partial or misleading API responses. Null product lookups degrade the product description to a raw code without warning.

**Recommended Fix:** Validate referential integrity at ingestion: verify BORR_ID exists in CDW_BORR_MSTR, PROD_CD exists in CDW_LN_PROD, and LN_ACCT_NBR exists in CDW_LN_ACCT. Log violations.

---

## ANM-007: LTV Percent Rounding Inconsistencies

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | LN_LTV_PCT, LN_ORIG_AMT, PROP_APRS_VAL |

**Description:** The stored LTV percentage does not match the calculated value (original amount / appraised value * 100) for some loans, suggesting inconsistent rounding or stale values.

**Example Records:**

| LN_ACCT_NBR | LN_ORIG_AMT | PROP_APRS_VAL | Stored LTV | Calculated LTV |
|-------------|-------------|---------------|------------|----------------|
| LN-2019-00142 | 285,000 | 345,000 | 82.5 | 82.61 |
| LN-2020-00398 | 420,000 | 615,000 | 68.2 | 68.29 |
| LN-2017-00034 | 165,000 | 206,000 | 80.0 | 80.10 |

**Business Impact:** LTV is a critical risk metric. Rounding errors near regulatory thresholds (80% for PMI requirements) could cause incorrect PMI determinations. LN-2017-00034 stored as 80.0% but calculates to 80.1% -- this crosses the 80% PMI threshold.

**Recommended Fix:** Recalculate LTV from source values at ingestion time rather than trusting the stored value. Apply consistent rounding (HALF_UP, 2 decimal places).

---

## ANM-008: Date Strings Not Validated Against MM/DD/YYYY Format

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Tables** | All tables |
| **Affected Columns** | All `*_DT` columns |

**Description:** All date fields are stored as VARCHAR(10) with an expected MM/DD/YYYY format, but no validation occurs. The service layer passes date strings directly to DTOs (`originationDate`, `paymentDate`) without parsing to `LocalDate`. Any malformed date (e.g., "2025-12-01", "13/32/2025", "TBD") would be silently passed through to API consumers as an invalid string.

**Business Impact:** API consumers receiving unparseable date strings would fail on their end. Inconsistent date formats between records make client-side sorting and filtering unreliable.

**Recommended Fix:** Parse all date strings to `LocalDate` at ingestion. Reject or flag records with unparseable dates. Return ISO-8601 format (yyyy-MM-dd) in API responses.

---

## ANM-009: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 |

**Description:** Borrower name fields are duplicated in CDW_LN_ACCT alongside CDW_BORR_MSTR. If the master record is updated (e.g., name change after marriage), the denormalized copy in the loan account becomes stale. The service uses the denormalized copy (`acct.getBorrowerFirstName()`) for `borrowerName` in `LoanSummaryDto`, which would show outdated data.

**Current Data:** All 5 loan records have names matching their master records, but this is only because the seed data is a snapshot. In production, drift is inevitable.

**Business Impact:** Incorrect borrower names on loan summaries. Customer complaints. Legal documents referencing wrong names.

**Recommended Fix:** Use the master borrower record (CDW_BORR_MSTR) as the authoritative source for borrower names. Join through BORR_ID rather than using denormalized fields.

---

## ANM-010: Null Middle Initial Handling

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | CDW_BORR_MSTR |
| **Affected Column** | BORR_MID_INIT |

**Description:** Borrower B-10005 (Robert Williams) has a NULL middle initial. The service handles this with a null check in `toBorrowerDto()`, producing "Robert Williams" instead of "Robert null Williams". However, the null is not validated or flagged -- it's unclear whether it's intentionally absent or a data entry omission.

**Business Impact:** Minor. Name formatting works correctly. Could cause issues if middle initial is required for identity matching downstream.

**Recommended Fix:** Accept null middle initials as valid. Document as optional field. No runtime fix needed.

---

## Summary

| Severity | Count | Anomaly IDs |
|----------|-------|-------------|
| Critical | 2 | ANM-001, ANM-002 |
| High | 3 | ANM-003, ANM-004, ANM-005 |
| Medium | 4 | ANM-006, ANM-007, ANM-008, ANM-009 |
| Low | 1 | ANM-010 |
| **Total** | **10** | |
