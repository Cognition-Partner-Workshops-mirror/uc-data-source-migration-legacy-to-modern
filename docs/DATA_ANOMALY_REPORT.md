# Data Anomaly Report — Legacy CDW Tables

## Summary

Analysis of legacy seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`) reveals **8 data quality anomalies** across 4 tables. The legacy CDW uses VARCHAR for all fields, has no foreign key constraints, and stores numeric/date values as formatted strings, creating multiple failure modes for downstream consumers.

---

## Anomaly #1: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

### Example Bad Records

| PMT_SEQ_NBR | PMT_AMT | PRIN + INT + ESCROW + LATE | Discrepancy |
|-------------|---------|----------------------------|-------------|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | +400.00 |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | +400.00 |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | +47.50 |

### Business Impact

Financial reporting will be inaccurate. Loan amortization schedules cannot be reconstructed from payment history. Regulatory reporting (HMDA, TILA) could contain incorrect figures, creating compliance risk.

### Recommended Fix

Validate that `PMT_AMT == PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` at ingestion. Flag mismatches and either reject the record or recalculate the total from components.

---

## Anomaly #2: SSN Last-4 Matches Phone Number Last-4 (Data Corruption)

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_SSN_LST4`, cross-referenced with `CDW_BORR_MSTR.BORR_PH_NBR` |

### Example Bad Records

| BORR_ID | BORR_SSN_LST4 | BORR_PH_NBR | Phone Last-4 |
|---------|---------------|-------------|--------------|
| B-10001 | 0142 | 217-555-0142 | 0142 |
| B-10002 | 0198 | 503-555-0198 | 0198 |
| B-10003 | 0167 | 512-555-0167 | 0167 |
| B-10004 | 0134 | 303-555-0134 | 0134 |
| B-10005 | 0156 | 602-555-0156 | 0156 |

### Business Impact

100% of records exhibit SSN last-4 matching phone last-4 — statistically impossible coincidence. Indicates systemic data corruption where SSN fields were likely populated from phone data during a prior ETL process. This is a PII integrity violation and could result in incorrect identity verification, loan-matching failures, and regulatory exposure.

### Recommended Fix

Flag all `BORR_SSN_LST4` values as suspect. Cross-reference against the encrypted SSN in `CDW_BORR_MSTR.BORR_SSN_ENCR` to verify. Do not use this field for identity matching until validated.

---

## Anomaly #3: Delinquency Days > 0 with Active Status

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

### Example Bad Records

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| LN-2018-00089 | 15 | ACT | DFT or FRB |

### Business Impact

Loans showing delinquency but marked Active will be excluded from collections workflows, early intervention programs, and regulatory delinquency reporting. This creates false portfolio health metrics and delays loss mitigation.

### Recommended Fix

Validate business rules: if `LN_DLQ_DAYS > 0`, status must not be `ACT`. Flag for manual review or auto-escalate to appropriate status based on delinquency thresholds (e.g., >30 days = DFT).

---

## Anomaly #4: Numeric String Parsing Without Error Handling

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | All amount/rate/score fields (e.g., `LN_ORIG_AMT`, `BORR_CRDT_SCR`, `LN_INT_RT`) |

### Example Risk Scenarios

| Field | Current Value | Potential Bad Value | Failure Mode |
|-------|--------------|---------------------|--------------|
| `BORR_CRDT_SCR` | "745" | "N/A", "", "7A5" | `NumberFormatException` in `parseLegacyInteger()` |
| `LN_ORIG_AMT` | "285,000" | "$285,000", "285000.00.00" | `NumberFormatException` in `parseLegacyAmount()` |
| `LN_INT_RT` | "4.750" | "4.75%" | `NumberFormatException` in `parseLegacyDecimal()` |
| `BORR_ANN_INCM` | "92,500" | "DECLINED" | `NumberFormatException` in `parseLegacyAmount()` |

### Business Impact

Any non-numeric value in these fields causes an unhandled `NumberFormatException` that propagates to the API as a 500 Internal Server Error, taking down the entire request. A single corrupt record in the database can make the `/api/loans` endpoint completely unusable since `getAllLoans()` iterates all records.

### Recommended Fix

Wrap all numeric parsing in try-catch blocks. Return sensible defaults or null for unparseable values and log warnings. Add input validation that rejects records with non-numeric values in numeric fields.

---

## Anomaly #5: Orphaned Record Risk — No Foreign Key Constraints

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

### Example Risk Scenarios

| Parent Table | FK Column | Risk |
|--------------|-----------|------|
| `CDW_BORR_MSTR` | `CDW_LN_ACCT.BORR_ID` | Loan references non-existent borrower |
| `CDW_LN_PROD` | `CDW_LN_ACCT.PROD_CD` | Loan references non-existent product |
| `CDW_LN_ACCT` | `CDW_PMT_HIST.LN_ACCT_NBR` | Payment references non-existent loan |

### Business Impact

Orphaned loan accounts would cause `NullPointerException` in `LoanService.toLoanSummary()` if the product lookup returns null (line 107 handles partially but line 54 in `getAllLoans()` calls `products.get(acct.getProductCode())` which returns null from the map, then `product.getDescription()` would NPE if fallback logic fails). Orphaned payments create phantom transactions in financial reports.

### Recommended Fix

Validate referential integrity at ingestion. Verify `BORR_ID` exists in borrower table, `PROD_CD` exists in product table, and `LN_ACCT_NBR` exists in loan account table before processing.

---

## Anomaly #6: Escrow Balance Inconsistency Between Loan and Payments

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` + `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.LN_ESCROW_BAL`, `CDW_PMT_HIST.PMT_ESCROW_AMT` |

### Example Bad Records

| LN_ACCT_NBR | LN_ESCROW_BAL | PMT_ESCROW_AMT (Recent) | Inconsistency |
|-------------|---------------|-------------------------|---------------|
| LN-2018-00089 | 2,100.00 | 0.00 (both payments) | Escrow balance exists but no escrow collected |
| LN-2021-00567 | 6,750.00 | 0.00 (both payments) | Escrow balance exists but no escrow collected |
| LN-2017-00034 | 1,890.45 | 0.00 (both payments) | Escrow balance exists but no escrow collected |

### Business Impact

If a loan has a non-zero escrow balance but payments show zero escrow collection, the escrow account will be depleted over time without replenishment. Tax and insurance payments drawn from escrow will eventually fail, resulting in lapsed coverage and tax delinquency notices.

### Recommended Fix

Validate that loans with non-zero `LN_ESCROW_BAL` have non-zero `PMT_ESCROW_AMT` in recent payments. Flag records where escrow balance exists but collection is zero.

---

## Anomaly #7: Date Format Stored as String — No Format Validation

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All `*_DT` columns (e.g., `BORR_DOB_DT`, `LN_ORIG_DT`, `PMT_DT`) |

### Example Risk Scenarios

| Column | Expected Format | Potential Bad Values |
|--------|-----------------|---------------------|
| `BORR_DOB_DT` | MM/DD/YYYY | "1978-03-15" (ISO), "15/03/1978" (DD/MM), "03-15-1978" (dashes) |
| `LN_ORIG_DT` | MM/DD/YYYY | "02/29/2019" (invalid date), "00/00/0000" (placeholder) |
| `PMT_DT` | MM/DD/YYYY | "" (empty), NULL |

### Business Impact

The column mappings document specifies transformation from `MM/DD/YYYY` string to proper `DATE` type. If any record uses a different format, the migration transformation will fail silently or produce incorrect dates. The service layer currently passes dates through as raw strings, so format inconsistencies are invisible until migration time.

### Recommended Fix

Validate all date strings match `MM/DD/YYYY` pattern at ingestion. Parse and verify date validity (e.g., no Feb 30, proper leap year handling). Reject or flag records with non-conforming dates.

---

## Anomaly #8: Credit Score String with No Range Validation

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_CRDT_SCR` |

### Example Records

| BORR_ID | BORR_CRDT_SCR | Valid Range (300-850) |
|---------|---------------|----------------------|
| B-10001 | 745 | Valid |
| B-10002 | 780 | Valid |
| B-10003 | 692 | Valid |
| B-10005 | 658 | Valid |

### Business Impact

While current seed data is within valid range, the VARCHAR(5) column accepts any string up to 5 chars. Values like "99", "999", or "ABC" would parse but represent invalid credit scores, leading to incorrect risk assessments and potentially improper loan pricing or approval decisions.

### Recommended Fix

After parsing to integer, validate that credit score falls within 300-850 range (FICO). Flag or reject out-of-range values. Consider also validating that scores align with the associated loan products (e.g., FHA loans typically require >= 580).
