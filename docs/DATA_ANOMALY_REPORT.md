# Data Anomaly Report — Legacy CDW Tables

> **Generated:** 2026-05-07
> **Source:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`
> **Scope:** CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST

---

## ANOM-001: Payment Component Arithmetic Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE |
| **Example Bad Records** | `PMT-2025120001`: total=1,487.02 but principal(456.78) + interest(1,074.69) + escrow(355.55) = 1,887.02. `PMT-2025110001`: total=1,487.02 but 454.97 + 1,076.50 + 355.55 = 1,887.02. Both payments for loan `LN-2019-00142` are off by exactly $400.00. |
| **Business Impact** | Financial reconciliation failures. Loan-level P&I totals will not balance against GL entries. Downstream reporting (e.g., investor remittance, IRS 1098 interest reporting) will contain incorrect figures. |
| **Recommended Fix** | Add a validation rule that asserts `total_amount == principal + interest + escrow + late_fee` (or the applicable decomposition). Flag mismatched records for manual review. Do not propagate unbalanced payment records to the modern schema. |

---

## ANOM-002: Numeric Values Stored as Strings with Commas — No Parse Error Handling

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Tables** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_LN_PROD, CDW_PMT_HIST |
| **Affected Columns** | BORR_ANN_INCM ("92,500"), BORR_CRDT_SCR ("745"), LN_ORIG_AMT ("285,000"), LN_CURR_BAL ("271,432.56"), LN_INT_RT ("4.750"), LN_PMT_AMT ("1,487.02"), LN_ESCROW_BAL, LN_LTV_PCT, PROP_APRS_VAL, PROD_MIN_AMT, PROD_MAX_AMT, PROD_TERM_MOS, PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE |
| **Example Bad Records** | All records in every table. VARCHAR columns hold monetary amounts with embedded commas, percentages, and integer counts. The current `parseLegacyAmount()` method in `LoanService.java` strips commas and calls `new BigDecimal(...)` with no try/catch — any non-numeric value (e.g., "N/A", "$285,000", empty string after trim) would throw an unhandled `NumberFormatException` and crash the API endpoint with a 500 error. |
| **Business Impact** | A single malformed legacy record causes the entire `/api/loans` or `/api/borrowers` endpoint to fail with an HTTP 500 Internal Server Error. No partial results are returned. |
| **Recommended Fix** | Wrap all string-to-numeric conversions in try/catch with logging. Return a safe fallback (e.g., `BigDecimal.ZERO`, `null`) and flag the record as having a data quality issue. |

---

## ANOM-003: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | CDW_LN_ACCT.BORR_ID (no FK to CDW_BORR_MSTR), CDW_LN_ACCT.PROD_CD (no FK to CDW_LN_PROD), CDW_PMT_HIST.LN_ACCT_NBR (no FK to CDW_LN_ACCT) |
| **Example Bad Records** | No orphaned records exist in the current seed data, but the schema permits them. The `getLoanById()` method in `LoanService.java:61` uses `orElse(null)` for product lookup — a missing product silently becomes `null`, and the DTO falls back to the raw product code string. A missing borrower would cause a `RuntimeException`. |
| **Business Impact** | Orphaned loan accounts (referencing deleted borrowers) would crash the borrower-detail endpoint. Orphaned payments referencing non-existent loans would silently appear in results without context. Missing product references degrade API response quality (raw codes instead of descriptions). |
| **Recommended Fix** | Validate referential integrity at ingestion time: verify that every `BORR_ID` in CDW_LN_ACCT exists in CDW_BORR_MSTR, every `PROD_CD` exists in CDW_LN_PROD, and every `LN_ACCT_NBR` in CDW_PMT_HIST exists in CDW_LN_ACCT. Log and quarantine orphaned records. |

---

## ANOM-004: Date Strings Passed Through Without Parsing or Validation

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Tables** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | All date columns: BORR_DOB_DT, BORR_CRET_DT, BORR_UPDT_DT, LN_ORIG_DT, LN_MAT_DT, LN_1ST_PMT_DT, LN_NXT_PMT_DT, PMT_DT, PMT_RECV_DT, PMT_PROC_DT, etc. |
| **Example Bad Records** | All records. Dates are stored as `MM/DD/YYYY` strings. The service passes these raw strings directly into DTOs (`dto.setOriginationDate(acct.getOriginationDate())` at LoanService.java:113, `dto.setPaymentDate(pmt.getPaymentDate())` at LoanService.java:138) without parsing or validation. Any malformed date (e.g., "13/32/2025", "00/00/0000", empty string) would silently propagate to API consumers. |
| **Business Impact** | API consumers receive unparsed date strings in MM/DD/YYYY format instead of ISO-8601. Malformed dates silently pass through. String-based date sorting in the repository (`OrderByPaymentDateDesc`) produces incorrect ordering — e.g., "02/01/2026" sorts before "12/01/2025" lexicographically. |
| **Recommended Fix** | Parse all date strings to `LocalDate` using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` with validation. Return ISO-8601 format in API responses. Catch `DateTimeParseException` and log malformed dates. |

---

## ANOM-005: Delinquent Loan with Active Status — Inconsistent Status/Delinquency

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | LN_DLQ_DAYS, LN_STAT_CD |
| **Example Bad Records** | `LN-2018-00089` (Michael Torres): `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'`. A loan 15 days delinquent should typically have a status reflecting its delinquency (e.g., DLQ or at minimum a sub-status). The service expands this to "Active" status hiding the delinquency from API consumers. |
| **Business Impact** | Risk management systems relying on the API will miss delinquent loans. Regulatory reporting (HMDA, Call Report) may undercount delinquencies. The loan appears current when it is not. |
| **Recommended Fix** | Add cross-field validation: if `delinquency_days > 0` and `status == ACT`, flag the record and either correct the status or add a delinquency indicator to the API response. |

---

## ANOM-006: Late Payment Missing Late Fee

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_RECV_DT, PMT_DT, PMT_LATE_FEE |
| **Example Bad Records** | `PMT-2025120003` for loan `LN-2018-00089`: due date 12/01/2025, received 12/05/2025 (4 days late), but `PMT_LATE_FEE = '0.00'`. Compare with `PMT-2025110003` on the same loan: received 11/18/2025 (17 days late), `PMT_LATE_FEE = '47.50'` — correctly assessed. |
| **Business Impact** | Lost revenue from unassessed late fees. Inconsistent fee application may raise fair lending compliance concerns. |
| **Recommended Fix** | Add validation that flags payments where `received_date > payment_due_date + grace_period` but `late_fee == 0`. Surface these for manual review; do not auto-correct fees. |

---

## ANOM-007: Denormalized Borrower Data in Loan Accounts — Staleness Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 |
| **Example Bad Records** | All 5 loan account records contain borrower first/last name and SSN last-4 copied from CDW_BORR_MSTR. Currently consistent, but the schema has no constraint enforcing synchronization. The service uses the denormalized loan-account name for display (`LoanService.java:106`: `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`), which may diverge from the borrower master record after name changes. |
| **Business Impact** | A borrower who updates their name (e.g., after marriage) would see their old name on loan records. SSN last-4 mismatch would cause identity verification failures. |
| **Recommended Fix** | At ingestion time, cross-check denormalized fields against the borrower master. Log any mismatches. In the service layer, prefer borrower master as the source of truth for name display. |

---

## ANOM-008: Null Middle Initial

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | CDW_BORR_MSTR |
| **Affected Column** | BORR_MID_INIT |
| **Example Bad Records** | `B-10005` (Robert Williams): `BORR_MID_INIT = NULL`. All other borrowers have a middle initial. |
| **Business Impact** | Minor — name formatting inconsistency. The service handles this with a null check (`LoanService.java:123`), but downstream systems expecting a non-null middle initial could fail. Name-matching algorithms may produce false negatives. |
| **Recommended Fix** | Accept NULL as valid. Ensure all consumers handle the nullable field. Consider defaulting to empty string in the DTO for consistent formatting. |

---

## ANOM-009: VA Loan Product with Zero Minimum Amount

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | CDW_LN_PROD |
| **Affected Column** | PROD_MIN_AMT |
| **Example Bad Records** | `VA30`: `PROD_MIN_AMT = '0'`. While VA loans allow $0 down payment, a $0 minimum loan amount is unusual — most lenders have a practical minimum (e.g., $10,000). |
| **Business Impact** | A $0 loan amount could pass validation and create a zero-balance loan account, corrupting portfolio metrics (average loan size, weighted averages). |
| **Recommended Fix** | Add a business rule validation: minimum loan amount should be > 0 (or a configurable threshold). Flag products with zero minimums for review. |

---

## ANOM-010: String-Based Date Sorting Produces Incorrect Order

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Column** | PMT_DT |
| **Example Bad Records** | The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts VARCHAR date strings lexicographically. In MM/DD/YYYY format, "02/01/2026" < "12/01/2025" alphabetically, so a February 2026 payment would appear after a December 2025 payment — wrong chronological order. |
| **Business Impact** | Payment history displayed in incorrect order. Most-recent-payment logic returns wrong record. |
| **Recommended Fix** | Parse date strings to `LocalDate` and sort in the service layer, or convert date columns during migration. |

---

## Summary

| Severity | Count | Anomaly IDs |
|----------|-------|-------------|
| Critical | 2 | ANOM-001, ANOM-002 |
| High | 3 | ANOM-003, ANOM-004, ANOM-005 |
| Medium | 3 | ANOM-006, ANOM-007, ANOM-010 |
| Low | 2 | ANOM-008, ANOM-009 |
| **Total** | **10** | |
