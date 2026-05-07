# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## ANM-001: SSN Last-4 Field Contains Phone Number Digits

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Table** | `CDW_LN_ACCT` |
| **Column** | `BORR_SSN_LST4` |

**Description:**
The `BORR_SSN_LST4` column is documented as the last four digits of the borrower's SSN but is actually populated with the last four digits of the borrower's phone number.

**Example Bad Records:**

| Loan Account | BORR_SSN_LST4 | Borrower Phone | Phone Last-4 |
|---|---|---|---|
| `LN-2019-00142` | `0142` | `217-555-0142` | `0142` |
| `LN-2020-00398` | `0198` | `503-555-0198` | `0198` |
| `LN-2018-00089` | `0167` | `512-555-0167` | `0167` |
| `LN-2021-00567` | `0134` | `303-555-0134` | `0134` |
| `LN-2017-00034` | `0156` | `602-555-0156` | `0156` |

All five records match the phone last-4, not the SSN. The encrypted SSN values (`ENC_XXX_001` etc.) cannot be used to verify because they are opaque.

**Business Impact:**
Identity verification processes that rely on SSN last-4 matching will produce false negatives. Regulatory compliance checks (KYC/AML) that cross-reference SSN fragments will fail. Borrower identity disputes could result in incorrect account access.

**Recommended Fix:**
Flag all `BORR_SSN_LST4` values as untrusted. Re-derive from the authoritative SSN source (decrypt `BORR_SSN_ENCR` from `CDW_BORR_MSTR` and extract last 4). Add a validation rule that SSN last-4 must not match phone last-4.

---

## ANM-002: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Table** | `CDW_PMT_HIST` |
| **Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:**
For multiple payment records, the sum of component amounts (principal + interest + escrow + late fee) does not equal the total payment amount.

**Example Bad Records:**

| Payment ID | Total | Principal | Interest | Escrow | Late Fee | Component Sum | Discrepancy |
|---|---|---|---|---|---|---|---|
| `PMT-2025120001` | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | +47.50 |

For `PMT-2025120001` and `PMT-2025110001`, the expected principal for loan `LN-2019-00142` (current balance ~$271K at 4.75%) should be ~$56.78, not $456.78 — a likely data entry error adding an extra leading digit.

For `PMT-2025110003`, the late fee of $47.50 is excluded from the total, creating an inconsistency in how totals are computed.

**Business Impact:**
Financial reporting will show incorrect principal/interest splits. Amortization schedules will be wrong. Regulatory reports (HMDA, call reports) will contain inaccurate data. Escrow analysis will be incorrect.

**Recommended Fix:**
Add a validation rule: `|total - (principal + interest + escrow + late_fee)| < 0.01`. Flag records that fail. For `PMT-202512/110001`, correct principal from 456.78/454.97 to 56.78/54.97. Standardize whether late fees are included in the total.

---

## ANM-003: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Table** | All tables |
| **Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:**
The legacy schema defines no foreign key constraints. Referential integrity is unenforced at the database level.

- `CDW_LN_ACCT.BORR_ID` → `CDW_BORR_MSTR.BORR_ID` (no FK)
- `CDW_LN_ACCT.PROD_CD` → `CDW_LN_PROD.PROD_CD` (no FK)
- `CDW_PMT_HIST.LN_ACCT_NBR` → `CDW_LN_ACCT.LN_ACCT_NBR` (no FK)

The application code in `LoanService.getLoanById()` silently handles a missing product (`orElse(null)`) but would produce an incorrect API response with just the raw product code instead of a description.

**Business Impact:**
Orphaned loan accounts could reference non-existent borrowers, causing NPEs or incomplete data in API responses. Payments for deleted/non-existent loans would be invisible to the system. Data migration to a modern schema with proper FKs would fail on orphaned records.

**Recommended Fix:**
Add referential integrity validation at the service layer before migration. Validate all FK relationships on data ingestion. Add a pre-migration audit query to detect orphaned records.

---

## ANM-004: Numeric Fields Stored as VARCHAR Without Validation

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Table** | All tables |
| **Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `LN_DLQ_DAYS`, `LN_ESCROW_BAL`, `LN_LTV_PCT`, `PROP_APRS_VAL`, `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:**
All numeric values (amounts, rates, scores, counts) are stored as VARCHAR strings with embedded commas and no type enforcement. The service layer methods `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` perform conversion but have no error handling — a malformed value (e.g., `"N/A"`, `"$285,000"`, `"TBD"`) will throw an uncaught `NumberFormatException` that propagates as an HTTP 500.

**Example Bad Records:**
Current seed data is well-formed, but the schema permits any string. Examples of plausible bad data that would cause runtime failures:
- Credit score: `"N/A"`, `"PENDING"`, `""` (empty)
- Annual income: `"$92,500"`, `"92500.00.00"`, `"unknown"`
- Loan amount: `"285,000.00 USD"`, `"-285,000"`

**Business Impact:**
A single malformed record causes the entire API endpoint to fail with a 500 error. The `getAllLoans()` endpoint would become completely unavailable if any loan has a bad numeric field. No partial results are returned.

**Recommended Fix:**
Wrap all parsing methods in try-catch blocks with fallback defaults. Log warnings for unparseable values. Return partial results with error flags rather than failing the entire request.

---

## ANM-005: Delinquent Loan Flagged as Active

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Table** | `CDW_LN_ACCT` |
| **Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Description:**
Loan `LN-2018-00089` has `LN_DLQ_DAYS = 15` but `LN_STAT_CD = ACT`. A loan with 15 days of delinquency should either have a delinquency status or the status field should reflect the delinquency state.

**Example Bad Records:**

| Loan Account | Delinquency Days | Status | Expected Status |
|---|---|---|---|
| `LN-2018-00089` | 15 | ACT (Active) | DLQ or at minimum ACT with delinquency flag |

Cross-referencing with payment history: `PMT-2025110003` for this loan shows `PMT_RECV_DT = 11/18/2025` for a `PMT_DT = 11/01/2025` — received 17 days late, with a $47.50 late fee. This confirms the delinquency.

**Business Impact:**
Regulatory reporting will undercount delinquent loans. Portfolio risk metrics will be understated. Collection workflows will not be triggered. Investor reporting for securitized loans will be inaccurate.

**Recommended Fix:**
Add a cross-validation rule: if `LN_DLQ_DAYS > 0`, status should not be `ACT` without a delinquency indicator. At minimum, the DTO should expose delinquency days alongside status so API consumers can assess.

---

## ANM-006: Denormalized Borrower Data Can Drift from Master

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Table** | `CDW_LN_ACCT` |
| **Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:**
`CDW_LN_ACCT` contains denormalized copies of borrower fields (`BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4`). These can drift from `CDW_BORR_MSTR` if the master record is updated but the loan account is not. No mechanism detects or prevents this inconsistency.

The current service code uses the denormalized name from `CDW_LN_ACCT` for `LoanSummaryDto.borrowerName` (line 106) but uses `CDW_BORR_MSTR` for `BorrowerDto`. A borrower who changes their name would show different names depending on which API endpoint is called.

**Example Bad Records:**
Current seed data is consistent, but a name change scenario would cause:
- `GET /api/loans/LN-2019-00142` → `borrowerName: "James Mitchell"` (from loan account)
- `GET /api/borrowers/B-10001` → `fullName: "James R. Mitchell"` (from borrower master)

**Business Impact:**
Inconsistent borrower names across API responses confuse downstream consumers. Legal documents generated from different endpoints could have different names. Audit trails become unreliable.

**Recommended Fix:**
Always resolve borrower name from `CDW_BORR_MSTR` via the `BORR_ID` FK. Add a reconciliation check that flags drift between denormalized and master records.

---

## ANM-007: Date Fields Stored as Strings with No Format Validation

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Table** | All tables |
| **Columns** | All `*_DT` columns |

**Description:**
All date fields are VARCHAR(10) with an expected `MM/DD/YYYY` format. The schema enforces no format constraint. The service layer passes dates through as raw strings without parsing or validating them.

The column mappings document (`column_mappings.md`) specifies `MM/DD/YYYY → DATE` transformation, but the current service layer does not perform this conversion. Dates like `"13/01/2025"` (invalid month), `"02/30/2025"` (invalid day), or `"2025-01-15"` (ISO format) would pass through silently.

**Example Bad Records:**
Current seed data uses consistent `MM/DD/YYYY` format, but the schema permits any 10-character string.

**Business Impact:**
Downstream date parsing will fail unpredictably. Date comparisons and sorting on string-typed dates produce incorrect results (e.g., `"12/01/2025" < "02/01/2026"` is true lexicographically but `"12/15/2025" > "02/01/2025"` is also true for the wrong reason). Payment ordering by `PMT_DT` using string comparison may be incorrect.

**Recommended Fix:**
Parse all date strings to `LocalDate` at the service layer. Validate format. Return ISO-8601 dates in API responses.

---

## ANM-008: NULL Middle Initial Causes Inconsistent Name Formatting

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Table** | `CDW_BORR_MSTR` |
| **Column** | `BORR_MID_INIT` |

**Description:**
Borrower `B-10005` (Robert Williams) has `NULL` for `BORR_MID_INIT`. The `toBorrowerDto()` method handles this with a ternary, producing `"Robert Williams"` vs `"James R. Mitchell"` for others. This creates inconsistent name formats across borrowers.

**Example Bad Records:**

| Borrower | Middle Initial | Formatted Name |
|---|---|---|
| B-10001 | R | James R. Mitchell |
| B-10005 | NULL | Robert Williams |

**Business Impact:**
Name matching algorithms that expect a consistent format will produce false negatives. Document generation may look inconsistent. Search functionality that splits on spaces will handle these differently.

**Recommended Fix:**
The current handling is acceptable but should be documented. Consider standardizing the output format or adding a separate `middleInitial` field to the DTO.

---

## ANM-009: LTV Percentage Rounding Inconsistencies

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Table** | `CDW_LN_ACCT` |
| **Columns** | `LN_LTV_PCT`, `LN_ORIG_AMT`, `PROP_APRS_VAL` |

**Description:**
The stored LTV percentage does not always match the computed value from `LN_ORIG_AMT / PROP_APRS_VAL`.

**Example Bad Records:**

| Loan | Original Amount | Appraised Value | Stored LTV | Computed LTV | Difference |
|---|---|---|---|---|---|
| LN-2019-00142 | 285,000 | 345,000 | 82.5% | 82.61% | 0.11% |
| LN-2020-00398 | 420,000 | 615,000 | 68.2% | 68.29% | 0.09% |
| LN-2017-00034 | 165,000 | 206,000 | 80.0% | 80.10% | 0.10% |

**Business Impact:**
Minor impact for most purposes, but regulatory reporting that requires precise LTV calculations (e.g., PMI thresholds at exactly 80%) could be affected. A loan at computed 80.10% LTV would require PMI but shows as 80.0%.

**Recommended Fix:**
Recompute LTV from source fields at the service layer rather than trusting the stored value. Apply consistent rounding rules (e.g., HALF_UP to 2 decimal places).

---

## ANM-010: No NOT NULL Constraints on Business-Required Fields

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Table** | All tables |
| **Columns** | All columns except PKs |

**Description:**
Only primary key columns have implicit NOT NULL constraints. Business-critical fields like `BORR_FST_NM`, `BORR_LST_NM`, `LN_ORIG_AMT`, `LN_STAT_CD`, `PMT_AMT`, etc. are all nullable. A NULL in any of these would cause NullPointerException in the service layer.

For example, `LoanService.toLoanSummary()` line 106 concatenates `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()` — a NULL in either would produce `"null Mitchell"` or `"James null"` in the API response.

**Business Impact:**
API responses could contain `"null"` string literals in names, addresses, and other fields. Financial calculations using null amounts would produce incorrect results or exceptions.

**Recommended Fix:**
Add null-checks for all business-required fields in the service layer. Return meaningful defaults or flag records as incomplete.

---

## ANM-011: Payment Received After Due Date Without Consistent Late Fee

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Table** | `CDW_PMT_HIST` |
| **Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_LATE_FEE` |

**Description:**
Payment `PMT-2025120003` has `PMT_RECV_DT = 12/05/2025` which is 4 days after `PMT_DT = 12/01/2025`, but `PMT_LATE_FEE = 0.00`. Meanwhile `PMT-2025110003` has a 17-day delay and a $47.50 late fee. The late fee policy is inconsistently applied.

**Example Bad Records:**

| Payment ID | Payment Date | Received Date | Days Late | Late Fee |
|---|---|---|---|---|
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 4 | $0.00 |
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 17 | $47.50 |

**Business Impact:**
Revenue leakage from inconsistent late fee application. Borrower disputes if late fees are applied inconsistently. Audit findings for inconsistent fee practices.

**Recommended Fix:**
Add validation that late fees are applied consistently based on a grace period threshold. If received_date - payment_date > grace_period and late_fee = 0, flag the record.

---

## ANM-012: Escrow Balance Present but No Escrow Payments

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Table** | `CDW_LN_ACCT` + `CDW_PMT_HIST` |
| **Columns** | `LN_ESCROW_BAL`, `PMT_ESCROW_AMT` |

**Description:**
Loans `LN-2021-00567` and `LN-2017-00034` have non-zero escrow balances ($6,750.00 and $1,890.45 respectively) but all their payment records show `PMT_ESCROW_AMT = 0.00`.

**Example Bad Records:**

| Loan Account | Escrow Balance | Payment Escrow Amounts |
|---|---|---|
| LN-2021-00567 | $6,750.00 | $0.00, $0.00 |
| LN-2017-00034 | $1,890.45 | $0.00, $0.00 |

**Business Impact:**
Escrow analysis and reconciliation will be incorrect. Property tax and insurance payment projections will be unreliable. Escrow shortage/surplus calculations will be wrong.

**Recommended Fix:**
Cross-validate escrow balances against cumulative escrow payments. Flag loans where escrow balance > 0 but recent payments have zero escrow component.
