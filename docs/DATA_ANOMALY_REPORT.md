# Data Anomaly Report — Legacy CDW Data

**Generated:** 2026-05-12  
**Source:** `src/main/resources/data-legacy.sql` and `src/main/resources/schema-legacy.sql`

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3     |
| High     | 3     |
| Medium   | 3     |
| Low      | 1     |
| **Total** | **10** |

---

## ANO-001: Payment Component Sum Mismatch

**Severity:** Critical  
**Affected Table:** `CDW_PMT_HIST`  
**Affected Columns:** `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`

**Description:**  
For multiple payment records, the sum of principal + interest + escrow + late fee does not equal the total payment amount. This violates the fundamental accounting identity that a payment must be fully allocated across its components.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT (Total) | Principal | Interest | Escrow | Late Fee | Computed Sum | Discrepancy |
|-------------|-----------------|-----------|----------|--------|----------|--------------|-------------|
| `PMT-2025120001` | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | **+400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | **+400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | **+47.50** |

**Business Impact:**  
- Incorrect loan amortization calculations
- Financial reporting discrepancies (balance sheet mismatch)
- Regulatory compliance risk (loan-level audit trails won't reconcile)
- Downstream analytics relying on component breakdowns will produce wrong results

**Recommended Fix:**  
Add a validation check at ingestion: `abs(total - (principal + interest + escrow + late_fee)) < 0.01`. Flag mismatched records for manual review. Consider using the component sum as the authoritative total, or marking the record as needing reconciliation.

---

## ANO-002: SSN Last-4 Matches Phone Number Last-4

**Severity:** Critical  
**Affected Table:** `CDW_LN_ACCT`  
**Affected Columns:** `BORR_SSN_LST4`, cross-referenced with `CDW_BORR_MSTR.BORR_PH_NBR`

**Description:**  
Every borrower's `BORR_SSN_LST4` in the loan account table exactly matches the last 4 digits of their phone number in the borrower master table. This is statistically near-impossible for real data (probability ~1 in 10^20 for 5 matches) and strongly indicates the SSN last-4 field was populated from the phone number, not from the actual SSN.

**Example Bad Records:**

| BORR_ID | BORR_PH_NBR | Phone Last-4 | BORR_SSN_LST4 | Match? |
|---------|-------------|--------------|---------------|--------|
| B-10001 | 217-555-0142 | 0142 | 0142 | Yes |
| B-10002 | 503-555-0198 | 0198 | 0198 | Yes |
| B-10003 | 512-555-0167 | 0167 | 0167 | Yes |
| B-10004 | 303-555-0134 | 0134 | 0134 | Yes |
| B-10005 | 602-555-0156 | 0156 | 0156 | Yes |

**Business Impact:**  
- The SSN last-4 field is unreliable for identity verification
- Borrower matching/deduplication using SSN last-4 will produce incorrect results
- Data migration that trusts this field will propagate corrupt identity data
- Potential regulatory issue if this field is used in KYC/AML reporting

**Recommended Fix:**  
Mark `BORR_SSN_LST4` as untrusted. During migration, do not carry this field forward. Derive SSN last-4 from `BORR_SSN_ENCR` (the encrypted SSN in the borrower master) if decryptable, or flag all records for re-verification.

---

## ANO-003: Numeric Strings Without Validation Guard

**Severity:** Critical  
**Affected Tables:** All four tables (`CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST`)  
**Affected Columns:** `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_TERM_MOS`, `LN_PMT_AMT`, `LN_DLQ_DAYS`, `LN_LTV_PCT`, `LN_ESCROW_BAL`, `PROP_APRS_VAL`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`, `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT`

**Description:**  
All numeric values are stored as `VARCHAR` strings (the legacy DW "everything is a string" pattern). The current service layer parsing methods (`parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`) will throw uncaught `NumberFormatException` if any value contains unexpected characters such as currency symbols (`$`), extra spaces, letters (`N/A`, `TBD`), or double commas. No schema-level constraint prevents invalid data entry.

**Example Current Data (parseable but at risk):**
- `BORR_CRDT_SCR`: `'745'`, `'780'` — valid now but nothing prevents `'N/A'` or `'---'`
- `BORR_ANN_INCM`: `'92,500'`, `'125,000'` — commas handled, but `'$92,500'` would fail
- `LN_LTV_PCT`: `'82.5'`, `'68.2'` — valid now but `'82.5%'` would fail

**Business Impact:**  
- Any unparseable value causes an unhandled `NumberFormatException`, resulting in a 500 Internal Server Error for the entire API request
- A single bad record poisons batch queries (e.g., `GET /api/loans` fails for all loans if one record has a bad amount)
- No graceful degradation or error isolation per record

**Recommended Fix:**  
Wrap all parsing calls in try-catch with logging. Use fallback defaults (`BigDecimal.ZERO`, `null`, `0`) for unparseable values. Add a validation layer that reports parsing failures without crashing.

---

## ANO-004: Delinquency Days vs. Loan Status Inconsistency

**Severity:** High  
**Affected Table:** `CDW_LN_ACCT`  
**Affected Columns:** `LN_DLQ_DAYS`, `LN_STAT_CD`

**Description:**  
Loan `LN-2018-00089` (borrower B-10003, Michael Torres) has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'`. An active loan with 15 days of delinquency should trigger a different status or at minimum be flagged. The corresponding payment `PMT-2025110003` has a late fee of `47.50` and was received 17 days late (due 11/01, received 11/18), confirming actual delinquency.

**Example Bad Record:**

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Late Payment Evidence |
|-------------|------------|-------------|----------------------|
| LN-2018-00089 | ACT | 15 | PMT-2025110003: due 11/01, received 11/18, late_fee=$47.50 |

**Business Impact:**  
- Delinquency reporting will undercount overdue loans
- Risk models relying on status code miss this loan's risk profile
- Regulatory delinquency reporting (e.g., 30/60/90 day buckets) may be inaccurate

**Recommended Fix:**  
Add cross-field validation: if `delinquencyDays > 0`, verify the status code is appropriate (e.g., `DLQ` or at minimum not `ACT`). Log warnings for inconsistent status/delinquency combinations.

---

## ANO-005: No NULL Constraints on Required Fields

**Severity:** High  
**Affected Tables:** All four tables  
**Affected Columns:** `BORR_FST_NM`, `BORR_LST_NM`, `BORR_ID` (in CDW_LN_ACCT), `LN_ACCT_NBR` (in CDW_PMT_HIST), `PMT_AMT`, `LN_ORIG_AMT`, and other business-critical fields

**Description:**  
The legacy schema defines no `NOT NULL` constraints on any column except primary keys. This means any field, including required business fields like borrower name, loan amount, and payment amounts, can be NULL. The service layer code does not guard against null names — `borrower.getFirstName() + " " + borrower.getLastName()` produces `"null null"` for a borrower with null first/last name.

**Example Risk Scenario:**
- A borrower with `BORR_FST_NM = NULL` would produce `fullName = "null null"` in the API response
- A loan with `LN_ORIG_AMT = NULL` would return `originalAmount = 0` (due to `parseLegacyAmount` null check returning `BigDecimal.ZERO`) — hiding the fact that the data is missing

**Business Impact:**  
- API responses with `"null null"` as borrower name degrade user experience
- Missing amounts silently converted to zero distort financial calculations
- No way to distinguish "intentionally zero" from "data missing"

**Recommended Fix:**  
Add null checks at ingestion with appropriate handling: reject records with null required fields, or populate a separate "data quality issues" list. For names, use `"[Unknown]"` as a fallback marker instead of allowing string concatenation with null.

---

## ANO-006: No Foreign Key Constraints (Orphan Record Risk)

**Severity:** High  
**Affected Tables:** `CDW_LN_ACCT`, `CDW_PMT_HIST`  
**Affected Columns:** `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR`

**Description:**  
The schema explicitly has no foreign key constraints. Loan accounts reference borrower IDs and product codes without any referential integrity guarantee. Payment records reference loan account numbers without enforcement. While the current seed data has matching records, the schema allows insertion of orphaned records at any time.

**Example Risk Scenario:**
- A loan account with `BORR_ID = 'B-99999'` (non-existent borrower) would load fine into the DB
- In `LoanService.getAllLoans()`, `products.get(acct.getProductCode())` returns `null` for an unknown product code, which is handled (falls back to product code string) — but the borrower lookup in `getBorrowerById()` would return no loans for this orphaned borrower
- A payment referencing `LN_ACCT_NBR = 'LN-DELETED'` would load fine but produce orphaned payment data

**Business Impact:**  
- Orphaned records produce incomplete or misleading API responses
- Data migration that assumes referential integrity will fail or silently skip records
- Aggregate calculations (total portfolio balance, etc.) may include ghost accounts

**Recommended Fix:**  
Add referential integrity validation at ingestion: verify each `BORR_ID` exists in borrower master, each `PROD_CD` exists in product table, and each `LN_ACCT_NBR` in payments exists in loan accounts. Log and quarantine orphaned records.

---

## ANO-007: Denormalized Borrower Data Divergence Risk

**Severity:** Medium  
**Affected Tables:** `CDW_LN_ACCT` vs. `CDW_BORR_MSTR`  
**Affected Columns:** `CDW_LN_ACCT.BORR_FST_NM/BORR_LST_NM` vs. `CDW_BORR_MSTR.BORR_FST_NM/BORR_LST_NM`

**Description:**  
The loan account table embeds copies of borrower name fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`). The code uses `acct.getBorrowerFirstName()` (from the denormalized copy) when building loan summaries, but uses `borrower.getFirstName()` (from borrower master) when building borrower DTOs. If a borrower's name is updated in `CDW_BORR_MSTR` but not in `CDW_LN_ACCT`, the same person would appear with different names across different API endpoints.

**Example Current Data (consistent now, but fragile):**

| Source | First Name | Last Name |
|--------|-----------|-----------|
| CDW_BORR_MSTR (B-10001) | James | Mitchell |
| CDW_LN_ACCT (LN-2019-00142) | James | Mitchell |

**Business Impact:**  
- Inconsistent borrower names across `GET /api/loans` and `GET /api/borrowers/{id}`
- Customer-facing discrepancies in loan statements and correspondence
- Complicates name-based searches and deduplication

**Recommended Fix:**  
At ingestion, cross-check denormalized fields against the master record. Log any divergences. In the service layer, prefer the master record as the authoritative source for borrower names.

---

## ANO-008: Date Strings Passed Through Without Parsing

**Severity:** Medium  
**Affected Tables:** `CDW_LN_ACCT`, `CDW_BORR_MSTR`, `CDW_PMT_HIST`  
**Affected Columns:** All date columns (`BORR_DOB_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `PMT_DT`, etc.)

**Description:**  
All dates are stored as `VARCHAR(10)` strings in `MM/DD/YYYY` format. The service layer passes these through as raw strings in DTOs (`dto.setOriginationDate(acct.getOriginationDate())`). No validation confirms dates are in the expected format, dates are real (e.g., `02/30/2020`), or date ranges are logical (e.g., maturity date is after origination date).

**Example Risk:**
- The column mappings document specifies `MM/DD/YYYY → DATE` parsing for migration
- But the current code does no date parsing at all
- String-based ordering in `findByLoanAccountNumberOrderByPaymentDateDesc` produces incorrect chronological ordering across year boundaries (e.g., `"02/01/2026" < "12/31/2025"` alphabetically)

**Business Impact:**  
- API consumers must know to parse `MM/DD/YYYY` format — non-standard for REST APIs (ISO 8601 `YYYY-MM-DD` is standard)
- Date-based sorting/filtering is unreliable
- Invalid dates would pass through silently to consumers

**Recommended Fix:**  
Parse all date strings to `LocalDate` at ingestion, validate format and logical ranges, and serialize as ISO 8601 (`YYYY-MM-DD`) in API responses. Add checks: `originationDate < maturityDate`, `dateOfBirth` is in the past, etc.

---

## ANO-009: Payment Date Ordering Anomaly (Late Receipt)

**Severity:** Medium  
**Affected Table:** `CDW_PMT_HIST`  
**Affected Columns:** `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`

**Description:**  
Payment `PMT-2025120003` has `PMT_DT = '12/01/2025'` (due date), `PMT_RECV_DT = '12/05/2025'` (received 4 days late), and `PMT_PROC_DT = '12/06/2025'` (processed next day). While this represents a legitimate late payment, the data captures it without any status flag — the `PMT_STAT_CD` is still `'PST'` (Posted) with no indication of lateness. Similarly, `PMT-2025110003` was received 17 days late with a late fee but also has `PMT_STAT_CD = 'PST'`.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | Days Late | PMT_LATE_FEE | PMT_STAT_CD |
|-------------|--------|-------------|-----------|--------------|-------------|
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 4 | 0.00 | PST |
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 17 | 47.50 | PST |

**Business Impact:**  
- Late payment patterns are not easily queryable by status code
- Delinquency analytics must compute date differences rather than relying on status
- Inconsistency: late fee present but no late status indicator

**Recommended Fix:**  
Add validation: if `receivedDate > paymentDate`, flag the payment as late. Optionally add a `LATE` status code or a boolean `is_late` field in the modern schema.

---

## ANO-010: Credit Score Range Not Validated

**Severity:** Low  
**Affected Table:** `CDW_BORR_MSTR`  
**Affected Column:** `BORR_CRDT_SCR`

**Description:**  
Credit scores are stored as VARCHAR strings with no range validation. Valid FICO scores range from 300 to 850. The current data has valid scores (658–810), but nothing prevents values like `'999'`, `'0'`, `'-50'`, or `'ABC'` from being inserted.

**Example Current Data:**

| BORR_ID | BORR_CRDT_SCR | Valid Range? |
|---------|---------------|-------------|
| B-10001 | 745 | Yes (300-850) |
| B-10002 | 780 | Yes |
| B-10003 | 692 | Yes |
| B-10004 | 810 | Yes |
| B-10005 | 658 | Yes |

**Business Impact:**  
- Out-of-range scores would skew risk assessments
- Invalid scores would cause incorrect loan eligibility decisions
- Analytics and reporting on credit score distributions would be unreliable

**Recommended Fix:**  
Add range validation at ingestion: credit score must be an integer between 300 and 850 (inclusive). Reject or flag records with out-of-range values.
