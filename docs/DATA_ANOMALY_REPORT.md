# Data Quality Anomaly Report

This report documents data quality anomalies found in the legacy CDW (Corporate Data Warehouse) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`) used by the loan-service application.

---

## ANM-001: All Columns Are VARCHAR — Numeric Parsing Failures

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_ESCROW_BAL`, `LN_LTV_PCT`, `LN_DLQ_DAYS`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE`, `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT` |

**Description:** Every column in the legacy schema is typed as `VARCHAR`. Numeric fields like credit scores, loan amounts, interest rates, and payment amounts are stored as strings — often with embedded commas (e.g., `"285,000"`, `"92,500"`, `"1,487.02"`). The service layer parses these with `new BigDecimal(amount.replace(",", ""))` and `Integer.parseInt(value.trim())`, which will throw `NumberFormatException` if the data contains any non-numeric characters beyond commas (e.g., currency symbols like `$`, letters, extra spaces, or empty strings that pass the blank check).

**Example Bad Records:**
- `BORR_ANN_INCM = '92,500'` — contains comma, requires stripping before parse
- `LN_ORIG_AMT = '285,000'` — contains comma
- `BORR_CRDT_SCR = '745'` — parsed via `Integer.parseInt()`, any non-digit causes crash
- `LN_LTV_PCT = '82.5'` — parsed as decimal, but no validation on range (0–100)

**Business Impact:** A single malformed numeric value in any legacy record will cause a `NumberFormatException` at runtime, crashing the entire API request (not just the bad record). Since `LoanService.getAllLoans()` maps all records in a stream, one bad record poisons the entire loan listing endpoint.

**Recommended Fix:** Wrap all numeric parsing in try-catch with fallback defaults. Validate ranges (credit score 300–850, LTV 0–200%, amounts >= 0). Log warnings for unparseable values instead of crashing.

---

## ANM-002: Date Strings with No Format Validation

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `LN_CRET_DT`, `LN_UPDT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PMT_CRET_DT`, `PMT_UPDT_DT`, `PROD_EFF_DT`, `PROD_EXP_DT` |

**Description:** All date fields are stored as `VARCHAR(10)` with an expected format of `MM/DD/YYYY`. The schema comment documents this format, but there is no database-level or application-level validation. The service layer passes date strings through to DTOs without parsing or validating them. The column mappings document requires these to be parsed as `DATE` or `TIMESTAMP` types during migration, but the current code treats them as opaque strings.

Legacy data warehouses commonly have mixed date formats (e.g., `YYYY-MM-DD`, `DD/MM/YYYY`, `M/D/YYYY` without zero-padding). Since no parsing occurs, invalid dates like `02/30/2020` or `13/01/2020` would silently pass through to API consumers.

**Example Bad Records:**
- `BORR_DOB_DT = '03/15/1978'` — valid format, but never validated
- `LN_ORIG_DT = '02/15/2019'` — passed as raw string to `LoanSummaryDto.originationDate`
- `PMT_DT = '12/15/2025'` — passed as raw string to `PaymentDto.paymentDate`

**Business Impact:** API consumers receive unvalidated date strings. If a legacy record contains `02/30/2025` or `MM/DD/YYYY` (literal placeholder), it will silently appear in API responses, causing downstream parsing failures in consuming applications. During migration to the modern schema (which uses `DATE` type), any non-conforming date string will cause `DateTimeParseException` and block the migration.

**Recommended Fix:** Parse all date strings through `DateTimeFormatter.ofPattern("MM/dd/yyyy")` at ingestion time. Return `null` or a sentinel value for unparseable dates. Log warnings for format violations.

---

## ANM-003: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|---|---|
| **Severity** | Critical |
| **Affected Tables** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema has **zero foreign key constraints**. `CDW_LN_ACCT.BORR_ID` references `CDW_BORR_MSTR.BORR_ID`, `CDW_LN_ACCT.PROD_CD` references `CDW_LN_PROD.PROD_CD`, and `CDW_PMT_HIST.LN_ACCT_NBR` references `CDW_LN_ACCT.LN_ACCT_NBR` — but none of these are enforced. Any record can reference a non-existent parent.

In the current seed data, all references happen to be valid. However, in production CDW systems, orphaned records are common due to:
- Asynchronous ETL pipelines loading tables independently
- Soft-deleted parent records
- Data corrections that update IDs without cascading

**Example Risk Scenarios:**
- A `CDW_LN_ACCT` row with `BORR_ID = 'B-99999'` (no matching borrower) would cause `LoanService.getBorrowerById()` to succeed for the borrower lookup but silently include a loan with no borrower context
- A `CDW_LN_ACCT` row with `PROD_CD = 'INVALID'` would result in `products.get(acct.getProductCode())` returning `null`, which is handled by falling back to the raw product code — but this masks a data integrity issue
- A `CDW_PMT_HIST` row with `LN_ACCT_NBR = 'LN-DELETED'` would be returned by `findByLoanAccountNumber()` but would reference a non-existent loan

**Business Impact:** Orphaned loan accounts produce API responses with missing product descriptions (falling back to cryptic codes like `FXD30`). Orphaned payments are silently served for non-existent loans. During migration, orphaned records will fail FK constraint insertion into the modern schema, blocking the migration.

**Recommended Fix:** Validate referential integrity at ingestion time. Check that every `BORR_ID` exists in the borrower table, every `PROD_CD` exists in products, and every `LN_ACCT_NBR` exists in loan accounts. Log and quarantine orphaned records.

---

## ANM-004: Denormalized Borrower Data in Loan Accounts — Inconsistency Risk

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** The `CDW_LN_ACCT` table embeds borrower first name, last name, and SSN last-4 digits — duplicating data already in `CDW_BORR_MSTR`. The service layer reads these denormalized fields directly (`acct.getBorrowerFirstName()`, `acct.getBorrowerLastName()`) in `toLoanSummary()` rather than joining to the canonical borrower record.

In the current seed data, the denormalized names match the master records. However, in production:
- Borrower name changes (marriage, legal name change) update `CDW_BORR_MSTR` but not `CDW_LN_ACCT`
- ETL timing differences can cause temporary mismatches
- Manual corrections may update one table but not the other

**Example Records (current data — consistent but fragile):**
| CDW_LN_ACCT | CDW_BORR_MSTR |
|---|---|
| `BORR_FST_NM='James', BORR_LST_NM='Mitchell'` (LN-2019-00142) | `BORR_FST_NM='James', BORR_LST_NM='Mitchell'` (B-10001) |
| `BORR_SSN_LST4='0142'` (LN-2019-00142) | `BORR_PH_NBR='217-555-0142'` (B-10001) |

Note: `BORR_SSN_LST4` in the loan account is `0142` which matches the last 4 digits of the **phone number**, not necessarily the SSN. The SSN is stored encrypted (`ENC_XXX_001`) so this cannot be verified — a data integrity concern.

**Business Impact:** If borrower names diverge, the loan listing API returns stale names while the borrower detail API returns current names, creating inconsistent user experiences. The SSN last-4 mismatch could cause identity verification failures.

**Recommended Fix:** In `toLoanSummary()`, resolve borrower names from `CDW_BORR_MSTR` via `BORR_ID` rather than using the denormalized fields. Flag records where denormalized fields disagree with the master as data quality warnings.

---

## ANM-005: Payment Component Amounts Don't Sum to Total

| Field | Value |
|---|---|
| **Severity** | High |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** Payment records have a total amount and component breakdown (principal, interest, escrow, late fee). The component amounts should sum to the total, but this is not validated.

**Example Records:**
| Payment | Total | Principal | Interest | Escrow | Late Fee | Sum of Components | Delta |
|---|---|---|---|---|---|---|---|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | **+400.00** |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | **+400.00** |
| PMT-2025120002 | 2,924.18 | 1,842.56 | 815.50 | 266.12 | 0.00 | 2,924.18 | 0.00 |
| PMT-2025110002 | 2,924.18 | 1,837.76 | 820.30 | 266.12 | 0.00 | 2,924.18 | 0.00 |
| PMT-2025120003 | 1,077.05 | 297.12 | 779.93 | 0.00 | 0.00 | 1,077.05 | 0.00 |
| PMT-2025110003 | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | **+47.50** |
| PMT-2025120004 | 2,468.35 | 857.23 | 1,611.12 | 0.00 | 0.00 | 2,468.35 | 0.00 |
| PMT-2025110004 | 2,468.35 | 854.46 | 1,613.89 | 0.00 | 0.00 | 2,468.35 | 0.00 |
| PMT-2025120005 | 811.61 | 306.45 | 505.16 | 0.00 | 0.00 | 811.61 | 0.00 |
| PMT-2025110005 | 811.61 | 305.37 | 506.24 | 0.00 | 0.00 | 811.61 | 0.00 |

**Records with mismatches:**
- **PMT-2025120001** and **PMT-2025110001** (loan LN-2019-00142): Components sum to $1,887.02 but total is $1,487.02 — a $400.00 discrepancy. The escrow component ($355.55) may be double-counted or the total excludes escrow.
- **PMT-2025110003** (loan LN-2018-00089): Components sum to $1,124.55 but total is $1,077.05 — a $47.50 discrepancy matching the late fee amount, suggesting the total excludes the late fee.

**Business Impact:** Financial reporting based on component breakdowns will not reconcile with total amounts. This affects amortization schedules, escrow accounting, and regulatory reporting. API consumers relying on `totalAmount` get different figures than summing `principalAmount + interestAmount + escrowAmount + lateFee`.

**Recommended Fix:** Validate at ingestion that `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE == PMT_AMT` (within a small tolerance for rounding). Flag mismatches with a warning and decide on a reconciliation strategy (trust total vs. trust components).

---

## ANM-006: Null Values in Contextually Required Fields

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2`, various |

**Description:** The legacy schema allows `NULL` in every column (no `NOT NULL` constraints). While some fields are genuinely optional (e.g., `BORR_ADDR_LN2` for apartment number, `BORR_MID_INIT`), other fields that are business-critical have no null protection.

**Example Records:**
- `B-10005` (Robert Williams): `BORR_MID_INIT = NULL` — acceptable for optional field, but `toBorrowerDto()` handles it with a conditional: `borrower.getMiddleInitial() != null ? " " + ... : ""`
- `B-10002`, `B-10003`, `B-10005`: `BORR_ADDR_LN2 = NULL` — acceptable
- All borrower records have `BORR_FST_NM` and `BORR_LST_NM` populated, but a future record with `NULL` first name would cause `toBorrowerDto()` to produce `"null R. Mitchell"` in the fullName field due to string concatenation with `null`

**Fields at risk if null appears in production:**
- `BORR_FST_NM` / `BORR_LST_NM` → NullPointerException or "null" string in name concatenation
- `LN_ACCT_NBR` (PK) → would be rejected by JPA
- `BORR_ID` in `CDW_LN_ACCT` → loan with no borrower linkage
- `PROD_CD` in `CDW_LN_ACCT` → `products.get(null)` returns null, falls back to null product code
- `LN_STAT_CD` → `expandStatusCode(null)` returns "Unknown", masking missing data

**Business Impact:** Null first/last names would produce garbled borrower names in API responses. Null product codes or borrower IDs would silently degrade data quality in responses. The modern schema has `NOT NULL` constraints on critical fields, so null values would block migration.

**Recommended Fix:** Validate non-null on business-critical fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_ID`, `PROD_CD`, `LN_ACCT_NBR`). Use `Objects.toString()` with defaults for name concatenation. Reject or quarantine records with null required fields.

---

## ANM-007: Unvalidated Status Codes — Silent Fallthrough

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Tables** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD` |
| **Affected Columns** | `BORR_STAT_CD`, `LN_STAT_CD`, `PMT_STAT_CD`, `PMT_TYP_CD`, `PROD_STAT_CD` |

**Description:** Status code fields accept any VARCHAR value. The service layer's `expandStatusCode()`, `expandPaymentType()`, and `expandPaymentStatus()` methods use switch expressions with a `default -> code` branch that returns the raw code for any unrecognized value. This means invalid codes like `"XYZ"`, `""`, or `"ACTIVE"` (full word instead of abbreviation) silently pass through as-is.

Additionally, the borrower status code (`BORR_STAT_CD`) is never expanded or validated — it is not referenced in `toBorrowerDto()` at all, meaning the borrower status is silently dropped from the API response.

**Example Records:**
- All current loan records have `LN_STAT_CD = 'ACT'` — valid
- All current payments have `PMT_STAT_CD = 'PST'` and `PMT_TYP_CD = 'REG'` — valid
- Borrower records have `BORR_STAT_CD = 'ACT'` — valid but **never used** in the API response

**Potential invalid values in production:**
- `LN_STAT_CD = 'ACTIVE'` (full word) → returned as-is: "ACTIVE" instead of "Active"
- `LN_STAT_CD = ''` (empty) → returned as empty string
- `PMT_STAT_CD = 'DEL'` (deleted, not in enum) → returned as "DEL"

**Business Impact:** Inconsistent status values in API responses confuse consumers. The dropped borrower status means inactive or suspended borrowers are indistinguishable from active ones. Downstream systems filtering on status values may miss records with non-standard codes.

**Recommended Fix:** Define an explicit set of valid status codes per table. Reject or map unknown codes to a canonical "UNKNOWN" value with a warning log. Include borrower status in the API response.

---

## ANM-008: Duplicate/Near-Duplicate Detection Risk in CDW_LN_ACCT

| Field | Value |
|---|---|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_ID`, `PROD_CD`, `LN_ORIG_AMT`, `LN_ORIG_DT` |

**Description:** There is no unique constraint beyond the primary key (`LN_ACCT_NBR`) to prevent logical duplicates — i.e., two loan account records for the same borrower, same product, same amount, and same origination date that represent the same real-world loan accidentally inserted twice with different account numbers.

In the current seed data (5 records), there are no duplicates. However, in a production CDW with millions of records loaded by batch ETL:
- Retry logic can insert the same loan twice with different generated account numbers
- Multiple source systems can feed the same loan
- Manual corrections can create near-duplicate records

**Example Risk:** Two records like:
- `LN-2019-00142`: B-10001, FXD30, $285,000, 02/15/2019
- `LN-2019-00143`: B-10001, FXD30, $285,000, 02/15/2019

Would both appear in the `getAllLoans()` response and in `getBorrowerById("B-10001")`, inflating the borrower's loan count and total exposure.

**Business Impact:** Duplicate loans inflate portfolio metrics, borrower debt-to-income ratios, and regulatory reporting. Duplicate payments would inflate cash flow reporting.

**Recommended Fix:** At ingestion time, check for logical duplicates on the composite of (borrower_id, product_code, original_amount, origination_date). Flag potential duplicates for manual review rather than silently loading them.

---

## ANM-009: Payment Date Ordering — Received After Processed

| Field | Value |
|---|---|
| **Severity** | Low |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT` |

**Description:** Payment records have three date fields: payment due date (`PMT_DT`), received date (`PMT_RECV_DT`), and processed date (`PMT_PROC_DT`). Business logic expects `received <= processed` and ideally `received <= payment_date + grace_period`.

**Example Records:**
| Payment | Due Date | Received | Processed | Late? |
|---|---|---|---|---|
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 12/06/2025 | Yes (5 days) |
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 11/19/2025 | Yes (18 days) |

Both payments for loan LN-2018-00089 (Michael Torres) were received late, consistent with the loan's `LN_DLQ_DAYS = '15'`. However:
- PMT-2025110003 has `PMT_LATE_FEE = '47.50'` (late fee assessed)
- PMT-2025120003 has `PMT_LATE_FEE = '0.00'` despite being 5 days late

This inconsistency in late fee application is not validated.

**Business Impact:** Inconsistent late fee application may indicate fee calculation errors. Late payments without late fees represent lost revenue. Date ordering violations (e.g., processed before received) would indicate data corruption.

**Recommended Fix:** Validate that `received_date <= processed_date` for all payments. Flag payments received after the due date that have zero late fee for review.

---

## ANM-010: Credit Score Range Not Validated

| Field | Value |
|---|---|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_CRDT_SCR` |

**Description:** Credit scores are stored as VARCHAR and parsed to Integer via `Integer.parseInt()`. Valid FICO scores range from 300 to 850. The current data has valid scores (658, 692, 745, 780, 810), but there is no range validation.

**Example Records:**
- B-10001: 745 (valid)
- B-10005: 658 (valid, lowest in dataset)
- Potential bad data: `'0'`, `'-1'`, `'999'`, `'N/A'`

**Business Impact:** Out-of-range credit scores would produce misleading risk assessments. Non-numeric values would crash the API.

**Recommended Fix:** Validate parsed credit scores are in range [300, 850]. Return null for out-of-range values with a warning log.

---

## Summary Table

| ID | Anomaly | Severity | Tables Affected | Current Data Impact | Production Risk |
|---|---|---|---|---|---|
| ANM-001 | VARCHAR numeric parsing | Critical | All 4 tables | Works with current clean data | Any malformed value crashes entire endpoint |
| ANM-002 | Unvalidated date strings | Critical | All 4 tables | Passes through unvalidated | Blocks migration; corrupts downstream |
| ANM-003 | No FK constraints | Critical | CDW_LN_ACCT, CDW_PMT_HIST | References valid in seed data | Orphaned records break joins and migration |
| ANM-004 | Denormalized borrower data | High | CDW_LN_ACCT | Consistent in seed data | Name changes cause stale data |
| ANM-005 | Payment amounts don't sum | High | CDW_PMT_HIST | 3 of 10 records mismatch | Financial reporting errors |
| ANM-006 | Nulls in required fields | Medium | CDW_BORR_MSTR, CDW_LN_ACCT | No nulls in critical fields | "null" strings in names; blocks migration |
| ANM-007 | Unvalidated status codes | Medium | All 4 tables | All codes valid | Unknown codes pass through; borrower status dropped |
| ANM-008 | No duplicate detection | Medium | CDW_LN_ACCT | No duplicates in seed data | Inflated portfolio metrics |
| ANM-009 | Payment date ordering | Low | CDW_PMT_HIST | Late payments exist | Inconsistent late fee application |
| ANM-010 | Credit score range | Low | CDW_BORR_MSTR | All scores valid | Out-of-range or non-numeric crashes API |
