# Legacy CDW Data Anomaly Report

## Summary

Analysis of the legacy CDW (Corporate Data Warehouse) seed data in `data-legacy.sql` and schema in `schema-legacy.sql` identified **10 data quality anomalies** across all four legacy tables. These anomalies fall into categories: arithmetic integrity failures, data corruption, type-safety risks, referential integrity gaps, and logical inconsistencies.

| Severity | Count |
|----------|-------|
| Critical | 3     |
| High     | 3     |
| Medium   | 3     |
| Low      | 1     |

---

## ANO-001: Payment Component Sum Mismatch

**Severity:** Critical

**Affected Table/Column:** `CDW_PMT_HIST` — `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`

**Description:** For several payment records, the sum of component amounts (principal + interest + escrow + late fee) does not equal the stated total payment amount.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT (Total) | PRIN + INT + ESCROW + LATE | Discrepancy |
|---|---|---|---|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | +400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | +400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | +47.50 |

**Business Impact:** Financial reporting will produce incorrect totals. Audit reconciliation will fail. Downstream systems relying on payment breakdowns (escrow analysis, principal amortization schedules) will be inconsistent with stated totals.

**Recommended Fix:** Validate at ingestion that `principal + interest + escrow + late_fee == total_amount`. When a mismatch is detected, flag the record for review and log the discrepancy. For PMT-2025120001/PMT-2025110001, the total appears to exclude escrow (1,487.02 = 456.78 + 1,074.69 - 44.45 rounding, approximately principal + interest). For PMT-2025110003, the total excludes the late fee.

---

## ANO-002: SSN Last-4 Populated with Phone Number Digits

**Severity:** Critical

**Affected Table/Column:** `CDW_LN_ACCT` — `BORR_SSN_LST4`

**Description:** The `BORR_SSN_LST4` field in all loan account records contains the last 4 digits of the borrower's phone number instead of the actual last 4 digits of their SSN.

**Example Bad Records:**

| LN_ACCT_NBR | BORR_ID | BORR_SSN_LST4 | BORR_PH_NBR (from BORR_MSTR) | Match? |
|---|---|---|---|---|
| LN-2019-00142 | B-10001 | 0142 | 217-555-**0142** | Phone last 4 |
| LN-2020-00398 | B-10002 | 0198 | 503-555-**0198** | Phone last 4 |
| LN-2018-00089 | B-10003 | 0167 | 512-555-**0167** | Phone last 4 |
| LN-2021-00567 | B-10004 | 0134 | 303-555-**0134** | Phone last 4 |
| LN-2017-00034 | B-10005 | 0156 | 602-555-**0156** | Phone last 4 |

**Business Impact:** This is a **PII/security issue**. Any identity verification workflow that uses SSN last-4 for authentication is comparing against phone digits, making verification useless. Compliance and audit failures are likely.

**Recommended Fix:** Cross-reference `BORR_SSN_LST4` against the encrypted SSN (`BORR_SSN_ENCR`) in `CDW_BORR_MSTR` to derive the correct last 4 digits. Flag all existing records as requiring re-validation. Do not expose `BORR_SSN_LST4` in API responses until corrected.

---

## ANO-003: Numeric Fields Stored as Strings with Parsing Risks

**Severity:** Critical

**Affected Table/Column:** All tables — all amount, rate, score, term, and day-count columns

**Description:** The legacy schema stores all numeric values as `VARCHAR` strings, many with embedded commas (e.g., `'285,000'`, `'1,487.02'`, `'92,500'`). The service layer's `parseLegacyAmount()` and `parseLegacyInteger()` methods perform basic string-to-number conversion but have no error handling for malformed inputs. An unexpected character (e.g., `'$285,000'`, `'N/A'`, `'TBD'`, or an empty string with whitespace) will throw an uncaught `NumberFormatException` that propagates as an HTTP 500 to API consumers.

**Example At-Risk Fields:**

| Table | Column | Example Value | Target Type |
|---|---|---|---|
| CDW_BORR_MSTR | BORR_CRDT_SCR | '745' | Integer |
| CDW_BORR_MSTR | BORR_ANN_INCM | '92,500' | BigDecimal |
| CDW_LN_ACCT | LN_ORIG_AMT | '285,000' | BigDecimal |
| CDW_LN_ACCT | LN_INT_RT | '4.750' | BigDecimal |
| CDW_LN_ACCT | LN_DLQ_DAYS | '15' | Integer |
| CDW_PMT_HIST | PMT_AMT | '1,487.02' | BigDecimal |

**Business Impact:** Any single malformed numeric value in the legacy data will crash the entire API request, returning a 500 error. This is a runtime availability risk.

**Recommended Fix:** Wrap all parsing in try-catch with structured error logging. Return safe defaults (zero for amounts, null for optional fields) and include a validation warning in the response or an internal anomaly log.

---

## ANO-004: Active Loan with Non-Zero Delinquency Days

**Severity:** High

**Affected Table/Column:** `CDW_LN_ACCT` — `LN_STAT_CD`, `LN_DLQ_DAYS`

**Description:** Loan `LN-2018-00089` has `LN_STAT_CD = 'ACT'` (Active) but `LN_DLQ_DAYS = '15'`. A loan that is 15 days delinquent should not have an unqualified "Active" status — it should be flagged as delinquent or at minimum carry a sub-status.

**Example Bad Records:**

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Expected |
|---|---|---|---|
| LN-2018-00089 | ACT | 15 | DLQ or ACT with delinquency flag |

**Business Impact:** Loan portfolio risk reporting will undercount delinquent loans. Regulatory reporting (e.g., call reports) requires accurate delinquency classification. Collections workflows will not trigger for this loan.

**Recommended Fix:** Validate that if `LN_DLQ_DAYS > 0`, the status reflects delinquency. Add a derived `isDelinquent` flag in the service layer when `delinquencyDays > 0` regardless of status code.

---

## ANO-005: No Foreign Key Constraints — Orphan Risk

**Severity:** High

**Affected Table/Column:** `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR`

**Description:** The legacy schema declares no foreign key constraints. `CDW_LN_ACCT.BORR_ID` references `CDW_BORR_MSTR.BORR_ID` only by convention, and `CDW_PMT_HIST.LN_ACCT_NBR` references `CDW_LN_ACCT.LN_ACCT_NBR` only by convention. Nothing prevents orphaned records.

**Example Risk:** If a borrower record is deleted or a loan account ID is mistyped, the system will:
- Return `null` for the product lookup (handled with a fallback on line 107 of `LoanService.java`)
- Throw `RuntimeException("Loan not found")` for direct loan lookups
- Silently return empty payment lists for non-existent loan IDs

**Business Impact:** Data integrity cannot be guaranteed. Orphaned payments or loans with invalid borrower references will produce incomplete or incorrect API responses.

**Recommended Fix:** Add referential integrity validation at the service layer. Before returning loan data, verify that the referenced borrower and product exist. Log warnings for any broken references.

---

## ANO-006: Denormalized Borrower Data Drift Risk

**Severity:** High

**Affected Table/Column:** `CDW_LN_ACCT` — `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`

**Description:** `CDW_LN_ACCT` duplicates borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`) from `CDW_BORR_MSTR`. The `toLoanSummary()` method in `LoanService.java` (line 106) uses the **denormalized copy** from `CDW_LN_ACCT` to build `borrowerName`, while `toBorrowerDto()` uses the canonical data from `CDW_BORR_MSTR`. If these drift apart (e.g., a name change is applied to `CDW_BORR_MSTR` but not to `CDW_LN_ACCT`), the API will return different names for the same borrower depending on which endpoint is called.

**Example Risk:**
- `GET /api/loans` → borrowerName from `CDW_LN_ACCT.BORR_FST_NM + BORR_LST_NM`
- `GET /api/borrowers/{id}` → fullName from `CDW_BORR_MSTR.BORR_FST_NM + BORR_LST_NM`

**Business Impact:** Inconsistent borrower names across API responses. Customer-facing applications may display conflicting information.

**Recommended Fix:** Always resolve borrower name from the canonical `CDW_BORR_MSTR` table via `BORR_ID` lookup, not from denormalized fields. Add a validation check that compares denormalized fields against the master record and logs discrepancies.

---

## ANO-007: Null Middle Initial Not Consistently Handled

**Severity:** Medium

**Affected Table/Column:** `CDW_BORR_MSTR` — `BORR_MID_INIT`

**Description:** Borrower `B-10005` (Robert Williams) has `BORR_MID_INIT = NULL`. The `toBorrowerDto()` method handles this with a null check (line 123), but the column is not marked as NOT NULL in the schema, and no other code path validates this field.

**Example Bad Records:**

| BORR_ID | BORR_FST_NM | BORR_MID_INIT | BORR_LST_NM |
|---|---|---|---|
| B-10005 | Robert | NULL | Williams |

**Business Impact:** Low direct impact since the service layer handles this case. However, downstream consumers that expect a non-null middle initial will fail.

**Recommended Fix:** Treat null middle initial as an empty string at the validation layer. Document that this field is optional.

---

## ANO-008: Dates Stored as Strings with No Format Validation

**Severity:** Medium

**Affected Table/Column:** All tables — all `*_DT` columns (19 date columns total)

**Description:** All dates are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. The service layer passes date strings directly to DTOs without parsing or validating them. There is no guarantee that the strings are valid dates (e.g., `'02/30/2020'` or `'13/01/2020'` would be accepted by the schema).

**Example Fields:** `BORR_DOB_DT`, `BORR_CRET_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `PMT_DT`, `PMT_RECV_DT`, etc.

**Business Impact:** Invalid date strings will cause failures during migration to the modern schema (which uses `DATE` and `TIMESTAMP` types). Date-based business logic (maturity calculations, payment scheduling) could produce incorrect results.

**Recommended Fix:** Parse all date strings into `LocalDate` at the service layer using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Catch `DateTimeParseException` and log invalid dates with fallback behavior.

---

## ANO-009: Late Payment Dates Not Reflected in Status

**Severity:** Medium

**Affected Table/Column:** `CDW_PMT_HIST` — `PMT_DT`, `PMT_RECV_DT`

**Description:** Several payments have `PMT_RECV_DT` (received date) significantly after `PMT_DT` (payment due date), indicating late payments, but neither the payment status nor the loan status reflects this.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | Days Late | PMT_STAT_CD |
|---|---|---|---|---|
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 4 | PST |
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 17 | PST |

**Business Impact:** Late payment patterns are not captured in the payment status, making it harder to identify at-risk loans. The 17-day late payment for PMT-2025110003 correlates with the 15-day delinquency on loan LN-2018-00089 but isn't flagged at the payment level.

**Recommended Fix:** Add a derived `isLate` flag and `daysLate` calculation when `receivedDate > paymentDate`. Include this in the payment DTO for transparency.

---

## ANO-010: Borrower Annual Income Not Exposed in API

**Severity:** Low

**Affected Table/Column:** `CDW_BORR_MSTR` — `BORR_ANN_INCM`

**Description:** The `BORR_ANN_INCM` field contains annual income as a comma-formatted string (e.g., `'92,500'`), but `BorrowerDto` does not include this field. The data exists in the entity but is never exposed or validated.

**Example Values:** `'92,500'`, `'125,000'`, `'78,000'`, `'145,000'`, `'65,000'`

**Business Impact:** Income data is available but inaccessible via the API. Loan-to-income ratio calculations and affordability assessments cannot be performed by API consumers.

**Recommended Fix:** Add `annualIncome` (as `BigDecimal`) to `BorrowerDto` and parse it using the existing `parseLegacyAmount()` method with proper validation.
