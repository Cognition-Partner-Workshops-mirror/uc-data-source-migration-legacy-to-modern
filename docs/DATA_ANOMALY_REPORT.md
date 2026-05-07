# Legacy CDW Data Anomaly Report

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## ANO-001: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT | PRIN + INT + ESCROW + LATE | Discrepancy |
|-------------|---------|---------------------------|-------------|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | **+400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | **+47.50** |

### Business Impact

Financial reports built from this data will show incorrect payment breakdowns. Downstream accounting systems that reconcile principal, interest, and escrow against total payment will flag discrepancies. Regulatory reporting (TILA, RESPA) requires accurate payment component disclosure. A $400 per-payment error on loan `LN-2019-00142` compounds over the life of the loan.

### Recommended Fix

Add a validation check at ingestion that verifies `principal + interest + escrow + late_fee == total_amount` within a tolerance (e.g., $0.01). Flag records that fail as `NEEDS_REVIEW` and log the discrepancy. Do not silently accept mismatched records into the modern schema.

---

## ANO-002: SSN Last-4 Field Contains Phone Number Digits

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Column** | `BORR_SSN_LST4` |

### Example Bad Records

| LN_ACCT_NBR | BORR_SSN_LST4 | Borrower Phone | Phone Last 4 | Match? |
|-------------|---------------|----------------|---------------|--------|
| `LN-2019-00142` | 0142 | 217-555-**0142** | 0142 | PII ERROR |
| `LN-2020-00398` | 0198 | 503-555-**0198** | 0198 | PII ERROR |
| `LN-2018-00089` | 0167 | 512-555-**0167** | 0167 | PII ERROR |
| `LN-2021-00567` | 0134 | 303-555-**0134** | 0134 | PII ERROR |
| `LN-2017-00034` | 0156 | 602-555-**0156** | 0156 | PII ERROR |

All 5 records are affected (100% of loan accounts).

### Business Impact

The `BORR_SSN_LST4` field is used for borrower identity verification during servicing calls and document matching. Containing phone digits instead of actual SSN last-4 means: (1) identity verification is non-functional, (2) any downstream system relying on this for KYC/AML is compromised, (3) the field gives a false sense of PII presence when the actual SSN fragment was never stored. This is both a data integrity and a compliance risk.

### Recommended Fix

Do not migrate this column into the modern schema. Flag it as corrupt. If SSN last-4 is needed, derive it from `CDW_BORR_MSTR.BORR_SSN_ENCR` after decryption, or source it from the authoritative identity system. Add a cross-reference validation that checks SSN last-4 against the borrower phone number and rejects matches.

---

## ANO-003: Delinquent Loan Marked as Active

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_STAT_CD`, `LN_DLQ_DAYS` |

### Example Bad Records

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Late Payment Evidence |
|-------------|------------|-------------|----------------------|
| `LN-2018-00089` | ACT | 15 | PMT-2025110003 received 17 days late with $47.50 late fee |

### Business Impact

Risk management and regulatory reporting depend on accurate loan status. A loan with 15 delinquency days should not be reported as "Active" — it should be at minimum flagged as "Delinquent" or "Watch". This leads to underreporting of portfolio risk, incorrect delinquency ratios in investor reports, and potential regulatory violations (OCC, CFPB).

### Recommended Fix

Add a business rule that cross-validates status against delinquency days: if `delinquency_days > 0` and `status == 'ACT'`, flag for review. Consider auto-escalating: 1-29 days = "Delinquent", 30-59 = "Default Watch", 60+ = "Default".

---

## ANO-004: Numeric String Parsing With No Error Handling

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | All VARCHAR columns representing amounts, rates, scores, and counts |

### Example Risk Scenarios

| Column | Current Value | Risky Variant | Failure Mode |
|--------|--------------|---------------|--------------|
| `BORR_ANN_INCM` | `92,500` | `$92,500` or `N/A` | `NumberFormatException` in `parseLegacyAmount()` |
| `BORR_CRDT_SCR` | `745` | `N/A` or ` ` (whitespace) | `NumberFormatException` in `parseLegacyInteger()` |
| `LN_INT_RT` | `4.750` | `4.750%` | `NumberFormatException` in `parseLegacyDecimal()` |
| `LN_DLQ_DAYS` | `15` | `fifteen` or `--` | `NumberFormatException` (not currently parsed) |

### Business Impact

The current `LoanService` parsing methods (`parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`) use `new BigDecimal()` and `Integer.parseInt()` with no try-catch. Any non-standard value from the CDW will cause an unhandled `NumberFormatException`, resulting in a 500 Internal Server Error for the entire API response. Since legacy DW data is notoriously inconsistent, this is a when-not-if scenario.

### Recommended Fix

Wrap all parsing in try-catch blocks. Return a safe fallback (e.g., `BigDecimal.ZERO`, `null`, or `0`) and log a warning with the record ID, field name, and raw value. Add a `DataQualityWarning` list to DTOs so API consumers are aware of degraded data.

---

## ANO-005: Null-Unsafe String Concatenation in Address and Name Fields

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `PROP_ADDR_LN1`, `PROP_CTY_NM`, `PROP_ST_CD`, `PROP_ZIP_CD` |

### Code Location

`LoanService.java`, line 114-115:
```java
dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
        + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
```

### Example Bad Output

If any property field is `null`, the API returns addresses like:
- `"null, Springfield, IL 62701"`
- `"742 Elm Street, null, null null"`

Similarly, `toBorrowerDto` on line 106:
```java
dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
```
A null first or last name produces `"null Mitchell"` or `"James null"`.

### Business Impact

API consumers displaying borrower names or property addresses will show the literal text "null" to end users. This is a UI/UX defect that erodes trust and could cause issues with document generation (e.g., mailing addresses, loan statements).

### Recommended Fix

Use null-safe concatenation helpers. Replace direct `+` concatenation with a utility that coalesces nulls to empty strings and trims extra separators.

---

## ANO-006: Date Strings With No Format Validation

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All `*_DT` columns (`BORR_DOB_DT`, `LN_ORIG_DT`, `PMT_DT`, etc.) |

### Description

All date columns are `VARCHAR(10)` with an expected format of `MM/DD/YYYY`. The current code passes these strings through to DTOs without parsing or validating. The `column_mappings.md` specifies conversion to `DATE` or `TIMESTAMP`, but the service layer performs no such conversion.

### Example Values

| Column | Value | Risk |
|--------|-------|------|
| `BORR_DOB_DT` | `03/15/1978` | Valid format but not validated |
| `LN_ORIG_DT` | `02/15/2019` | Valid format but not validated |
| Any date field | `2019-02-15` or `15/02/2019` | Would silently pass through as incorrect format |

### Business Impact

Date format inconsistencies would silently propagate to API responses and downstream systems. Sorting, filtering, or date arithmetic on these string values will produce incorrect results. Migration to the modern typed schema would fail if any date doesn't match `MM/DD/YYYY`.

### Recommended Fix

Parse all date strings using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` at ingestion. Reject or flag records with unparseable dates. Return dates in ISO-8601 format (`yyyy-MM-dd`) in API responses.

---

## ANO-007: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Description

The legacy schema declares no foreign key constraints. `CDW_LN_ACCT.BORR_ID` is not enforced to reference `CDW_BORR_MSTR.BORR_ID`, and `CDW_PMT_HIST.LN_ACCT_NBR` is not enforced to reference `CDW_LN_ACCT.LN_ACCT_NBR`. Any record with a non-existent reference would be silently accepted.

### Current Seed Data Status

All current references are valid in the seed data. However, the lack of constraints means production data loads could introduce orphans at any time.

### Business Impact

An orphaned loan account (invalid `BORR_ID`) would cause `getBorrowerById()` to return incomplete loan lists. An orphaned payment (invalid `LN_ACCT_NBR`) would be invisible in payment history queries. The code at `LoanService.java:61-62` does `findById(acct.getProductCode()).orElse(null)` which handles missing products gracefully, but a null product code would produce a less informative API response.

### Recommended Fix

Add reference validation at ingestion. Before accepting a loan account, verify borrower and product exist. Before accepting a payment, verify the loan account exists. Log orphaned records and route them to a dead-letter queue for manual review.

---

## ANO-008: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` (denormalized from `CDW_BORR_MSTR`) |

### Description

`CDW_LN_ACCT` embeds borrower first name, last name, and SSN last-4 alongside the `BORR_ID` foreign key. These denormalized copies can drift from the authoritative `CDW_BORR_MSTR` record if borrower data is updated without propagating to loan accounts.

### Current Seed Data Status

Current data is consistent — names in `CDW_LN_ACCT` match `CDW_BORR_MSTR`. However, the SSN last-4 is already known to be corrupt (see ANO-002).

### Business Impact

The API uses `CDW_LN_ACCT.BORR_FST_NM` / `BORR_LST_NM` (via `toLoanSummary()` line 106) rather than joining to the borrower master. If a borrower's name changes (marriage, legal name change), loan summaries would show stale names while borrower detail would show the current name, creating inconsistency in the API.

### Recommended Fix

In the service layer, prefer the authoritative `CDW_BORR_MSTR` data over denormalized copies. Add a cross-reference check during ingestion that compares embedded fields against the master record and flags discrepancies.

---

## ANO-009: Currency-Formatted Strings Fragile to Format Variations

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `PMT_AMT`, etc. |

### Description

All monetary values are stored as `VARCHAR` with comma-formatted strings (e.g., `"285,000"`, `"1,487.02"`). The parser (`parseLegacyAmount`) only strips commas. It does not handle:
- Dollar signs: `"$285,000"`
- Parentheses for negatives: `"(1,487.02)"`
- Spaces: `" 285,000 "`
- Currency codes: `"USD 285,000"`

### Business Impact

Any format variation from the CDW source system that doesn't match the exact `[digits],[digits].[digits]` pattern will cause a `NumberFormatException` and a 500 error on the entire API endpoint.

### Recommended Fix

Implement a robust currency parser that strips `$`, `()`, spaces, and currency codes before parsing. Add unit tests with edge-case formats. Consider using a regex-based sanitizer: `value.replaceAll("[^\\d.\\-]", "")`.

---

## ANO-010: Null Middle Initial Handling

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Column** | `BORR_MID_INIT` |

### Example Bad Records

| BORR_ID | BORR_FST_NM | BORR_MID_INIT | BORR_LST_NM |
|---------|-------------|---------------|-------------|
| `B-10005` | Robert | NULL | Williams |

### Business Impact

Minor. The `toBorrowerDto()` method at line 123 already handles this with a null check. However, `CDW_LN_ACCT` does not carry `BORR_MID_INIT`, so loan-level borrower name construction (line 106) never includes middle initial regardless. This creates inconsistent name formatting between borrower detail ("Robert Williams") and loan summary ("Robert Williams") vs. other borrowers where detail shows "James R. Mitchell" but loan shows "James Mitchell".

### Recommended Fix

Standardize name construction: either always include middle initial from the borrower master, or never include it. Add a shared name-formatting utility used by both `toLoanSummary()` and `toBorrowerDto()`.
