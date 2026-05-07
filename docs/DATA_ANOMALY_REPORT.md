# Legacy CDW Data Anomaly Report

This report documents data quality anomalies found in the legacy Corporate Data Warehouse (CDW) seed data (`src/main/resources/data-legacy.sql`) and schema (`src/main/resources/schema-legacy.sql`).

---

## ANO-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** The sum of payment components (principal + interest + escrow + late fee) does not equal the stated total payment amount for multiple records.

**Example Bad Records:**

| Payment ID | Total | Principal | Interest | Escrow | Late Fee | Component Sum | Delta |
|-----------|-------|-----------|----------|--------|----------|---------------|-------|
| `PMT-2025120001` | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | **1,887.02** | +400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | **1,887.02** | +400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | **1,124.55** | +47.50 |

**Business Impact:** Financial reports and account reconciliation will show incorrect totals. Downstream systems consuming payment data via the API will compute wrong principal/interest splits. Regulatory reporting (TILA, RESPA) requires accurate payment breakdowns.

**Recommended Fix:** Add a validation rule in the service layer that checks `principal + interest + escrow + late_fee == total`. Log a warning when components do not reconcile and flag the payment record. For PMT-2025110003, the delta exactly equals the late fee (47.50), suggesting late fees are excluded from the total inconsistently.

---

## ANO-002: Numeric String Parsing Without Error Handling

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | All tables (`CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST`) |
| **Affected Columns** | All VARCHAR columns that store numeric values: `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, etc. |

**Description:** All numeric values (amounts, rates, scores, counts) are stored as VARCHAR strings. The service layer's `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` methods only strip commas before parsing. They will throw uncaught `NumberFormatException` on values containing currency symbols (`$285,000`), text (`N/A`, `PENDING`), extra whitespace, or other non-numeric characters that are common in legacy warehouse data.

**Example Risky Patterns:**
- Amount with currency symbol: `$285,000` -> `NumberFormatException` after comma strip yields `$285000`
- Text placeholder: `N/A` or `TBD` in a numeric field -> `NumberFormatException`
- Double decimal: `271,432..56` (data entry error) -> `NumberFormatException`
- Negative with parens: `(1,487.02)` (accounting notation) -> `NumberFormatException`

**Business Impact:** A single malformed numeric value in any legacy record causes an unhandled `NumberFormatException` that propagates as an HTTP 500 error. This crashes the entire API response for list endpoints (`/api/loans`, `/api/borrowers`) since one bad record poisons the full result set.

**Recommended Fix:** Wrap all parse methods in try-catch blocks. Return a safe default (e.g., `BigDecimal.ZERO`) and log the original value along with the record identifier for data steward review. Add pre-parse sanitization to strip currency symbols, handle accounting negative notation, and trim whitespace.

---

## ANO-003: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema defines no foreign key constraints. A loan account can reference a non-existent borrower ID or product code, and a payment can reference a non-existent loan account. The code in `LoanService.getAllLoans()` does `products.get(acct.getProductCode())` which silently returns `null` for missing products, and `toLoanSummary()` falls back to showing the raw product code. However, `getLoanById()` calls `loanProductRepository.findById(acct.getProductCode()).orElse(null)`, which also silently continues with a null product.

**Example Scenarios:**
- A loan with `PROD_CD = 'JUMBO'` (not in `CDW_LN_PROD`) -> product description falls back to raw code `"JUMBO"` in the API response
- A loan with `BORR_ID = 'B-99999'` (not in `CDW_BORR_MSTR`) -> `getBorrowerById` throws RuntimeException; `getAllBorrowers` does not include the orphan but `getAllLoans` still shows the loan with denormalized borrower name
- A payment with `LN_ACCT_NBR = 'LN-DELETED'` -> returned by `findAll()` but the payment's loan context is lost

**Business Impact:** Orphaned records lead to incomplete API responses, misleading borrower-loan relationships, and inaccurate portfolio-level reporting. In a migration context, orphaned records will fail FK insertion into the modern normalized schema.

**Recommended Fix:** Add referential integrity validation in the service layer before building DTOs. Log orphaned records. For the migration, implement a pre-migration audit query that identifies all FK violations.

---

## ANO-004: SSN Last-4 Matches Phone Last-4 (Data Contamination)

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

**Description:** For all 5 borrowers, the last 4 digits of the SSN (stored in `CDW_LN_ACCT.BORR_SSN_LST4`) are identical to the last 4 digits of the phone number (from `CDW_BORR_MSTR.BORR_PH_NBR`). This is statistically near-impossible (1 in 10^20 probability for 5 records) and indicates a systematic data loading error where the phone suffix was copied into the SSN field.

| Borrower | SSN Last 4 | Phone | Phone Last 4 |
|----------|-----------|-------|--------------|
| B-10001 | 0142 | 217-555-**0142** | 0142 |
| B-10002 | 0198 | 503-555-**0198** | 0198 |
| B-10003 | 0167 | 512-555-**0167** | 0167 |
| B-10004 | 0134 | 303-555-**0134** | 0134 |
| B-10005 | 0156 | 602-555-**0156** | 0156 |

**Business Impact:** SSN data is incorrect for all borrowers, affecting identity verification, credit bureau reporting, and compliance (FCRA, Reg B). Any downstream system relying on SSN last-4 for borrower matching will produce incorrect linkages.

**Recommended Fix:** Flag all `BORR_SSN_LST4` values as unreliable. Cross-reference against the encrypted SSN in `CDW_BORR_MSTR.BORR_SSN_ENCR` to derive the correct last-4. Add a validation check that SSN last-4 does not match phone last-4.

---

## ANO-005: Escrow Balance Without Escrow Collection

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.LN_ESCROW_BAL`, `CDW_PMT_HIST.PMT_ESCROW_AMT` |

**Description:** Three of five loans have non-zero escrow balances on the account but zero escrow amounts in all their payment records. This is logically inconsistent — if escrow isn't being collected in payments, the escrow balance should be zero (or declining).

| Loan Account | Escrow Balance | Payment Escrow Amounts |
|-------------|---------------|----------------------|
| LN-2019-00142 | 3,245.80 | 355.55, 355.55 (consistent) |
| LN-2020-00398 | 4,890.12 | 266.12, 266.12 (consistent) |
| LN-2018-00089 | **2,100.00** | **0.00, 0.00** (inconsistent) |
| LN-2021-00567 | **6,750.00** | **0.00, 0.00** (inconsistent) |
| LN-2017-00034 | **1,890.45** | **0.00, 0.00** (inconsistent) |

**Business Impact:** Escrow account reporting will be inaccurate. Tax and insurance disbursements depend on escrow balances. Borrower annual escrow statements (required by RESPA) will be incorrect.

**Recommended Fix:** Add cross-table validation that flags loans with non-zero escrow balances but zero escrow collection in recent payments. Investigate whether escrow was previously collected but stopped, or if the escrow balance is stale.

---

## ANO-006: Delinquent Loan with Active Status

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:** Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). Industry standard typically requires status changes at 30, 60, and 90+ day delinquency thresholds, but a loan with any delinquency days should at minimum be flagged, and the combination is a data quality concern given the service layer's `expandStatusCode()` will report it as "Active" without any delinquency context.

**Example Bad Record:**
```
LN-2018-00089: status=ACT, delinquency_days=15, late_fee on Nov payment=47.50
```

**Business Impact:** Delinquent loans reported as "Active" without qualification will mislead portfolio risk assessments. The API response shows status "Active" with no indication of delinquency since `delinquencyDays` is not included in `LoanSummaryDto`.

**Recommended Fix:** Add validation that cross-checks delinquency days against status code. Include delinquency information in the DTO. Flag records where `delinquency_days > 0` but `status = ACT` for review.

---

## ANO-007: Denormalized Borrower Data Drift

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** `CDW_LN_ACCT` contains denormalized copies of borrower fields (first name, last name, SSN last-4) alongside the `BORR_ID` foreign key. These fields can drift out of sync with the source record in `CDW_BORR_MSTR`. The service layer uses the denormalized names from `CDW_LN_ACCT` in `toLoanSummary()` (line 106) but the canonical names from `CDW_BORR_MSTR` in `toBorrowerDto()` (line 124). If a borrower's name is updated in the master table but not in the loan account table, the API will return different names depending on which endpoint is called.

**Current Data Status:** All 5 records are currently in sync. However, no mechanism prevents future drift.

**Business Impact:** Borrower name inconsistencies across API endpoints. Legal name changes (marriage, court order) may not propagate to loan records, causing compliance issues with ECOA and fair lending reporting.

**Recommended Fix:** During migration, drop denormalized fields from loan accounts and use FK joins. In the interim, add validation that compares denormalized fields against the master record and logs discrepancies.

---

## ANO-008: Date Fields Returned as Unparsed Strings

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All `*_DT` columns: `BORR_DOB_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `PMT_DT`, `PMT_RECV_DT`, etc. |

**Description:** All date fields are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. The service layer passes these strings directly to DTOs without parsing or validating them (`dto.setOriginationDate(acct.getOriginationDate())`, `dto.setPaymentDate(pmt.getPaymentDate())`). Invalid dates like `13/32/2025`, `00/00/0000`, or different formats like `2025-01-15` would pass through silently.

**Example Risky Patterns:**
- Invalid month: `13/01/2025`
- Invalid day: `02/30/2025` (Feb 30 doesn't exist)
- Mixed formats: `2025-01-15` (ISO) vs `01/15/2025` (US)
- Empty string `""` instead of NULL

**Business Impact:** API consumers receive unparsed date strings and must guess the format. Date sorting/comparison on VARCHAR fields produces incorrect ordering (e.g., `12/01/2024` < `01/01/2025` lexicographically fails). Migration to typed DATE columns will fail on any malformed date.

**Recommended Fix:** Parse all date strings to `LocalDate` in the service layer with explicit `MM/dd/yyyy` format. Return ISO-8601 (`yyyy-MM-dd`) in API responses. Log and handle parse failures gracefully.

---

## ANO-009: No NOT NULL Constraints on Required Business Fields

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_ENCR`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `PMT_AMT`, etc. |

**Description:** The legacy schema defines no `NOT NULL` constraints on any column except implicit PK constraints. Business-critical fields like borrower name, loan amounts, and payment totals can be NULL. The service layer does not check for NULL on fields it concatenates (e.g., `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()` at line 106), which would produce `"null null"` as the borrower name.

**Example:** If `BORR_FST_NM` is NULL for a loan account record, the API returns:
```json
{ "borrowerName": "null Mitchell", ... }
```

**Business Impact:** NULL values in required fields produce malformed API responses ("null null" names, null amounts). Downstream consumers may crash or display meaningless data to end users.

**Recommended Fix:** Add null checks before string concatenation and numeric parsing. Use fallback defaults (e.g., "Unknown" for names, `BigDecimal.ZERO` for amounts) and log records with missing required fields.

---

## ANO-010: Late Payment Received Date After Payment Due Date

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT` |

**Description:** Payment `PMT-2025110003` for loan `LN-2018-00089` has a payment date of `11/01/2025` but was not received until `11/18/2025` (17 days late), with a corresponding late fee of `$47.50`. While not necessarily a data error (this reflects a genuinely late payment), the service layer does not surface the received date, processed date, or late payment context in the API response.

**Example Record:**
```
PMT-2025110003: pmt_date=11/01/2025, recv_date=11/18/2025, late_fee=47.50
```

**Business Impact:** API consumers cannot distinguish between on-time and late payments since only the payment date and type are returned. Late payment patterns are invisible to the API.

**Recommended Fix:** Include `receivedDate` and `processedDate` in `PaymentDto`. Add validation that flags significant gaps between payment date and received date.

---

## Summary

| ID | Title | Severity | Table(s) |
|----|-------|----------|----------|
| ANO-001 | Payment Component Sum Mismatch | Critical | CDW_PMT_HIST |
| ANO-002 | Numeric String Parsing Without Error Handling | Critical | All |
| ANO-003 | No FK Constraints — Orphaned Record Risk | Critical | CDW_LN_ACCT, CDW_PMT_HIST |
| ANO-004 | SSN Last-4 Matches Phone Last-4 | High | CDW_LN_ACCT |
| ANO-005 | Escrow Balance Without Collection | High | CDW_LN_ACCT, CDW_PMT_HIST |
| ANO-006 | Delinquent Loan with Active Status | High | CDW_LN_ACCT |
| ANO-007 | Denormalized Borrower Data Drift | Medium | CDW_LN_ACCT |
| ANO-008 | Date Fields Returned as Unparsed Strings | Medium | All |
| ANO-009 | No NOT NULL on Required Fields | Medium | All |
| ANO-010 | Late Payment Date Context Missing | Low | CDW_PMT_HIST |
