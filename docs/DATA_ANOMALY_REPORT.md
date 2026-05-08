# Data Anomaly Report — Legacy CDW Tables

> **Generated:** 2026-05-08
> **Scope:** `CDW_BORR_MSTR`, `CDW_LN_PROD`, `CDW_LN_ACCT`, `CDW_PMT_HIST`
> **Data source:** `src/main/resources/data-legacy.sql` and `src/main/resources/schema-legacy.sql`

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2     |
| High     | 3     |
| Medium   | 3     |
| Low      | 2     |
| **Total** | **10** |

---

## ANM-001: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:**
For several payment records the sum of the component columns (`PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`) does not equal the total payment amount in `PMT_AMT`. This is a fundamental accounting integrity violation.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN | INT | ESCROW | LATE_FEE | Computed Sum | Delta |
|-------------|---------|------|-----|--------|----------|-------------|-------|
| `PMT-2025120001` | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | **1,887.02** | **+400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | **1,887.02** | **+400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | **1,124.55** | **+47.50** |

**Business Impact:**
Financial reporting, loan balance reconciliation, and escrow accounting will produce incorrect results. Downstream systems consuming these amounts will carry forward the discrepancy. Audit and regulatory compliance (TILA, RESPA) require accurate payment breakdowns.

**Recommended Fix:**
- Flag records where `|PMT_AMT - (PRIN + INT + ESCROW + LATE_FEE)| > 0.01` during ingestion.
- Quarantine mismatched records for manual review rather than silently ingesting them.
- Determine the authoritative amount (total vs. components) and derive the other.

---

## ANM-002: SSN Last-4 Digits Populated from Phone Number

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_SSN_LST4` |

**Description:**
The `BORR_SSN_LST4` column in every loan account record contains the last 4 digits of the borrower's **phone number** instead of their Social Security Number. This affects all 5 loan records (100% of the dataset).

**Example Bad Records:**

| LN_ACCT_NBR | BORR_SSN_LST4 | BORR_PH_NBR (from CDW_BORR_MSTR) | Match? |
|-------------|---------------|-----------------------------------|--------|
| `LN-2019-00142` | 0142 | 217-555-**0142** | Phone last 4 |
| `LN-2020-00398` | 0198 | 503-555-**0198** | Phone last 4 |
| `LN-2018-00089` | 0167 | 512-555-**0167** | Phone last 4 |
| `LN-2021-00567` | 0134 | 303-555-**0134** | Phone last 4 |
| `LN-2017-00034` | 0156 | 602-555-**0156** | Phone last 4 |

**Business Impact:**
This is a PII data integrity issue. The SSN last-4 field is commonly used for borrower identity verification in servicing operations. Using phone digits instead means identity checks will fail or — worse — falsely pass against a wrong borrower. This could also represent a compliance violation (GLBA, SOX) if the wrong data was used for regulatory reporting.

**Recommended Fix:**
- Mark `BORR_SSN_LST4` as untrusted during migration; do not carry it to the modern schema.
- Derive the correct SSN last-4 from the encrypted SSN field (`BORR_SSN_ENCR`) in `CDW_BORR_MSTR` using the appropriate decryption key.
- Add a cross-field validation rule to detect phone-number patterns in SSN fields.

---

## ANM-003: All Numeric Values Stored as VARCHAR with Parsing Risks

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PROD_TERM_MOS`, `PROD_MIN_AMT`, `PROD_MAX_AMT`, and 10+ others |

**Description:**
The legacy schema stores every numeric value as `VARCHAR` — credit scores, monetary amounts, interest rates, term months, percentages, and delinquency days. Amounts include embedded commas (e.g., `"285,000"`, `"1,487.02"`). The service layer's `parseLegacyAmount()` and `parseLegacyInteger()` methods strip commas and parse, but have no error handling for:
- Currency symbols (`"$285,000"`)
- Text values (`"N/A"`, `"PENDING"`, `"---"`)
- Whitespace or control characters
- Overflow values exceeding `BigDecimal` or `Integer` range

**Example Fields at Risk:**

| Column | Example Value | Target Type | Risk |
|--------|--------------|-------------|------|
| `BORR_CRDT_SCR` | `"745"` | Integer | `"N/A"` → `NumberFormatException` |
| `BORR_ANN_INCM` | `"92,500"` | BigDecimal | `"$92,500"` → `NumberFormatException` |
| `LN_INT_RT` | `"4.750"` | BigDecimal | `"4.750%"` → `NumberFormatException` |
| `LN_DLQ_DAYS` | `"15"` | Integer | `""` or `"N/A"` → `NumberFormatException` |

**Business Impact:**
A single malformed numeric string in any record will cause an unhandled `NumberFormatException` that crashes the entire API response (not just the bad record). This makes the service fragile and unable to gracefully degrade.

**Recommended Fix:**
- Wrap all numeric parsing in try-catch with logging and fallback defaults.
- Validate numeric ranges (credit score 300–850, interest rate 0–100, amounts >= 0).
- Strip known non-numeric prefixes/suffixes (`$`, `%`, whitespace) before parsing.

---

## ANM-004: Dates Stored as Unvalidated Strings

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `LN_1ST_PMT_DT`, `LN_NXT_PMT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, `PROD_EFF_DT`, `PROD_EXP_DT`, and others |

**Description:**
All date fields are `VARCHAR(10)` with an expected `MM/DD/YYYY` format, but there is no validation. The service layer passes date strings directly to DTOs without parsing them into `LocalDate`. The column mappings document specifies `Parse MM/DD/YYYY → DATE` as the migration transformation, but no parsing or validation exists in the current code.

**Example Current Behavior:**
```
LoanSummaryDto.originationDate = "02/15/2019"  // raw string, not validated
PaymentDto.paymentDate = "12/15/2025"           // raw string, not validated
```

Possible malformed values that would silently pass through:
- `"13/45/2020"` (invalid month/day)
- `"2020-01-15"` (ISO format instead of MM/DD/YYYY)
- `""` (empty string)
- `"TBD"` or `"N/A"`

**Business Impact:**
Date strings cannot be sorted, compared, or used in date arithmetic without parsing. API consumers receiving raw date strings in mixed formats cannot reliably process them. Migration to the modern schema will fail on the first malformed date.

**Recommended Fix:**
- Parse all date strings into `java.time.LocalDate` at ingestion time using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`.
- Reject or flag records with unparseable dates.
- Return ISO-8601 format (`yyyy-MM-dd`) in API responses for interoperability.

---

## ANM-005: Delinquent Loan Marked as Active

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_STAT_CD`, `LN_DLQ_DAYS` |

**Description:**
Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` (15 days past due) but `LN_STAT_CD = 'ACT'` (Active). A loan that is 15 days delinquent should either have a delinquency-related status or the delinquency days should trigger a status review. This cross-field inconsistency suggests the status is not being updated when delinquency occurs.

**Example Bad Record:**

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Expected Status |
|-------------|-----------|-------------|-----------------|
| `LN-2018-00089` | ACT | 15 | DLQ or at minimum flagged |

**Business Impact:**
Reporting will undercount delinquent loans. Collections workflows that trigger on status codes will miss this loan. Regulatory reporting (call reports, HMDA) requires accurate delinquency classification.

**Recommended Fix:**
- Add cross-field validation: if `LN_DLQ_DAYS > 0` and `LN_STAT_CD = 'ACT'`, flag as inconsistent.
- Define business rules for automatic status transitions (e.g., >30 days → DLQ, >90 days → DFT).

---

## ANM-006: Denormalized Borrower Data Consistency Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` (duplicated from `CDW_BORR_MSTR`) |

**Description:**
The loan account table denormalizes borrower first name, last name, and SSN last-4 from the borrower master table. While the current seed data is consistent between the two tables, the schema has no constraints to enforce this. Over time in production, updates to `CDW_BORR_MSTR` (e.g., name change after marriage) may not propagate to `CDW_LN_ACCT`, resulting in stale data.

**Example (currently consistent, but at risk):**

| Source | First Name | Last Name |
|--------|-----------|-----------|
| `CDW_BORR_MSTR` (B-10001) | James | Mitchell |
| `CDW_LN_ACCT` (LN-2019-00142) | James | Mitchell |

**Business Impact:**
API responses that use the denormalized name from loan accounts may show outdated borrower information. Search and matching operations could fail to associate records correctly.

**Recommended Fix:**
- During migration, use `CDW_BORR_MSTR` as the authoritative source for borrower data.
- Drop denormalized borrower columns from loan accounts in the modern schema (already planned in column mappings).
- Add a validation check that compares denormalized values against the master record.

---

## ANM-007: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:**
The legacy schema explicitly has **no foreign key constraints** (noted in schema comments). This means:
- A loan account can reference a `BORR_ID` that does not exist in `CDW_BORR_MSTR`.
- A loan account can reference a `PROD_CD` that does not exist in `CDW_LN_PROD`.
- A payment can reference an `LN_ACCT_NBR` that does not exist in `CDW_LN_ACCT`.

The current seed data has valid references, but production data may contain orphaned records.

**Example Relationships (currently valid):**

| Child Table | FK Column | Parent Table | Valid? |
|------------|-----------|-------------|--------|
| `CDW_LN_ACCT` | `BORR_ID = 'B-10001'` | `CDW_BORR_MSTR` | Yes |
| `CDW_LN_ACCT` | `PROD_CD = 'FXD30'` | `CDW_LN_PROD` | Yes |
| `CDW_PMT_HIST` | `LN_ACCT_NBR = 'LN-2019-00142'` | `CDW_LN_ACCT` | Yes |

**Business Impact:**
Orphaned loan accounts (no borrower) will cause `NullPointerException` in `LoanService.getBorrowerById()` when it tries to look up borrower details. Orphaned payments will appear in listings but cannot be associated with a loan for balance reconciliation. The `getAllLoans()` method will produce `null` for the product lookup, leading to degraded display (product code shown instead of description).

**Recommended Fix:**
- Validate referential integrity at ingestion time before inserting into the modern schema.
- Log and quarantine orphaned records.
- The modern schema should enforce FK constraints.

---

## ANM-008: LTV Percentage Calculation Discrepancies

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_LTV_PCT`, `LN_ORIG_AMT`, `PROP_APRS_VAL` |

**Description:**
The Loan-to-Value (LTV) percentage stored in `LN_LTV_PCT` does not always match the computed ratio of `LN_ORIG_AMT / PROP_APRS_VAL * 100`. Small rounding discrepancies exist in multiple records.

**Example Bad Records:**

| LN_ACCT_NBR | LN_ORIG_AMT | PROP_APRS_VAL | Stored LTV | Computed LTV | Delta |
|-------------|-------------|---------------|-----------|-------------|-------|
| `LN-2019-00142` | 285,000 | 345,000 | 82.5 | 82.61 | -0.11 |
| `LN-2020-00398` | 420,000 | 615,000 | 68.2 | 68.29 | -0.09 |
| `LN-2017-00034` | 165,000 | 206,000 | 80.0 | 80.10 | -0.10 |

**Business Impact:**
LTV is a key risk metric used for PMI requirements, pricing, and regulatory capital calculations. Small discrepancies could push a loan over or under a critical threshold (e.g., 80% LTV for PMI waiver).

**Recommended Fix:**
- Recompute LTV from source amounts during migration rather than carrying forward the stored value.
- Add a tolerance check (e.g., ±0.5%) and flag records that exceed it.

---

## ANM-009: NULL Values in Borrower Optional Fields

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

**Description:**
Several borrower records have `NULL` in optional fields. While NULLs are expected for optional data, the service layer must handle them consistently to avoid `NullPointerException` in string operations.

**Example Records:**

| BORR_ID | BORR_MID_INIT | BORR_ADDR_LN2 |
|---------|--------------|---------------|
| B-10002 | L | NULL |
| B-10003 | A | NULL |
| B-10005 | NULL | NULL |

**Business Impact:**
The `toBorrowerDto()` method correctly handles null middle initial, but other code paths that concatenate address fields may produce `"null"` strings in output if not handled. The property address concatenation in `toLoanSummary()` could produce similar issues if property fields were null.

**Recommended Fix:**
- Add null-safe string handling for all concatenation operations.
- Use `Optional` or ternary operators consistently.
- Define default values (empty string) for optional fields in DTOs.

---

## ANM-010: Payment Received After Due Date Not Reflected in Late Fees

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_LATE_FEE` |

**Description:**
Payment `PMT-2025120003` for loan `LN-2018-00089` was received on `12/05/2025` (5 days after the `12/01/2025` due date) and processed on `12/06/2025`, but has a late fee of `0.00`. The prior month's payment (`PMT-2025110003`) for the same loan was received on `11/18/2025` (18 days late) and does have a late fee of `47.50`. The inconsistent application of late fees suggests business rule gaps.

**Example Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | Days Late | PMT_LATE_FEE |
|-------------|--------|------------|-----------|-------------|
| `PMT-2025110003` | 11/01/2025 | 11/18/2025 | 18 | 47.50 |
| `PMT-2025120003` | 12/01/2025 | 12/05/2025 | 5 | 0.00 |

**Business Impact:**
Inconsistent late fee assessment affects revenue recognition and borrower statements. Borrowers may dispute charges if the rules appear arbitrary. Grace period logic should be documented and consistently applied.

**Recommended Fix:**
- Validate that late fees are applied consistently based on a defined grace period (typically 15 days for mortgages).
- Flag records where `PMT_RECV_DT - PMT_DT > grace_period` and `PMT_LATE_FEE = 0`.
