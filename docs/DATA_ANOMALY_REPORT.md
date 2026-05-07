# Data Quality Anomaly Report — Legacy CDW Tables

> **Generated:** 2026-05-07
> **Scope:** `src/main/resources/schema-legacy.sql`, `src/main/resources/data-legacy.sql`
> **Tables analyzed:** CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3     |
| High     | 4     |
| Medium   | 3     |
| Low      | 2     |

---

## ANOM-001: Payment Component Mismatch (principal + interest + escrow != total)

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT |

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PMT_PRIN_AMT | PMT_INT_AMT | PMT_ESCROW_AMT | Computed Sum | Delta |
|-------------|---------|-------------|-------------|----------------|--------------|-------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 1,887.02 | +400.00 |

Both payments for loan LN-2019-00142 have component sums that exceed the total by exactly $400.00. The interest portion appears inflated.

**Business Impact:** Financial reporting and accounting reconciliation will be incorrect. Downstream systems consuming this data via the API will compute wrong amortization schedules, and regulatory reports (e.g., TILA disclosures) could be inaccurate.

**Recommended Fix:** Flag records where `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT != PMT_AMT` during ingestion. Quarantine mismatched payments for manual review rather than silently serving incorrect data.

---

## ANOM-002: No NOT NULL Constraints on Required Fields

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | BORR_FST_NM, BORR_LST_NM, LN_ORIG_AMT, LN_CURR_BAL, PMT_AMT, and all others |

**Example Bad Records:**

The schema defines every column (except primary keys) as nullable VARCHAR:
```sql
BORR_FST_NM     VARCHAR(50),   -- nullable, but required for display
BORR_LST_NM     VARCHAR(50),   -- nullable, but required for display
LN_ORIG_AMT     VARCHAR(15),   -- nullable, but required for financial calculations
```

Current seed data does contain a NULL: borrower B-10005 has `NULL` for `BORR_MID_INIT`. While middle initial is optional, the schema permits NULL for every field including first name, last name, loan amounts, and payment totals.

**Business Impact:** A null first/last name causes the API to return `"null Mitchell"` or `"James null"` in borrower names. A null loan amount causes `parseLegacyAmount()` to silently return `BigDecimal.ZERO`, misrepresenting a missing value as a zero-dollar loan. A null property field causes NullPointerException in address concatenation, crashing the entire `/api/loans` endpoint.

**Recommended Fix:** Validate NOT NULL on business-critical fields (names, amounts, dates, status codes) at the service layer during ingestion. Return meaningful error messages identifying the specific record and field.

---

## ANOM-003: Numeric Fields Stored as Strings With No Parse Error Handling

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_LN_PROD, CDW_PMT_HIST |
| **Affected Columns** | BORR_CRDT_SCR, BORR_ANN_INCM, LN_ORIG_AMT, LN_CURR_BAL, LN_INT_RT, LN_PMT_AMT, PMT_AMT, PMT_PRIN_AMT, etc. |

**Example Risky Patterns:**

| Column | Current Value | Risk Scenario |
|--------|--------------|---------------|
| BORR_CRDT_SCR | "745" | "N/A", "PENDING", or "" would throw `NumberFormatException` |
| BORR_ANN_INCM | "92,500" | "$92,500" or "92500.00" would throw `NumberFormatException` |
| LN_ORIG_AMT | "285,000" | "285 000" (space separator) would throw `NumberFormatException` |
| LN_INT_RT | "4.750" | "4.750%" would throw `NumberFormatException` |
| LN_DLQ_DAYS | "15" | "15 days" or "NONE" would throw `NumberFormatException` |

The `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` methods only handle comma removal. Any other non-numeric content causes an unhandled `NumberFormatException` that propagates as an HTTP 500.

**Business Impact:** A single malformed record in the legacy warehouse crashes the entire API endpoint. `GET /api/loans` iterates all records — one bad value means zero loans returned, only a 500 error. No partial results, no identification of which record is bad.

**Recommended Fix:** Wrap all parse operations in try-catch. Log the specific record and field that failed parsing. Return a fallback value or exclude the record with a warning, rather than crashing the entire request.

---

## ANOM-004: No Foreign Key Constraints — Orphaned Records Possible

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | CDW_LN_ACCT.BORR_ID, CDW_LN_ACCT.PROD_CD, CDW_PMT_HIST.LN_ACCT_NBR |

**Example:**

The schema has no FK constraints:
```sql
CREATE TABLE CDW_LN_ACCT (
    BORR_ID VARCHAR(20),    -- references CDW_BORR_MSTR.BORR_ID, but no FK
    PROD_CD VARCHAR(10),    -- references CDW_LN_PROD.PROD_CD, but no FK
    ...
);
CREATE TABLE CDW_PMT_HIST (
    LN_ACCT_NBR VARCHAR(20), -- references CDW_LN_ACCT.LN_ACCT_NBR, but no FK
    ...
);
```

A loan with `BORR_ID = 'B-99999'` (non-existent borrower) or a payment with `LN_ACCT_NBR = 'LN-DELETED'` would be accepted without error.

**Business Impact:** `LoanService.getBorrowerById()` calls `loanAccountRepository.findByBorrowerId()` which would return accounts pointing to non-existent products. `products.get(acct.getProductCode())` returns null, causing the product description to fall back to the raw product code — incorrect but not a crash. However, orphaned payments for deleted loans would appear in query results with no parent context.

**Recommended Fix:** Validate referential integrity at the service layer: verify that BORR_ID exists in the borrower table and PROD_CD exists in the product table before processing. Log and quarantine orphaned records.

---

## ANOM-005: SSN Last-4 Digits Match Phone Number Last-4 Digits

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT (cross-referenced with CDW_BORR_MSTR) |
| **Affected Columns** | CDW_LN_ACCT.BORR_SSN_LST4, CDW_BORR_MSTR.BORR_PH_NBR |

**Example Bad Records:**

| BORR_ID | BORR_SSN_LST4 | BORR_PH_NBR | Phone Last 4 | Match? |
|---------|---------------|-------------|-------------|--------|
| B-10001 | 0142 | 217-555-0142 | 0142 | YES |
| B-10002 | 0198 | 503-555-0198 | 0198 | YES |
| B-10003 | 0167 | 512-555-0167 | 0167 | YES |
| B-10004 | 0134 | 303-555-0134 | 0134 | YES |
| B-10005 | 0156 | 602-555-0156 | 0156 | YES |

100% of records have SSN last-4 matching phone last-4. This is statistically impossible in real data (expected: ~0.01% match rate) and indicates data contamination — likely a copy-paste error in the ETL pipeline.

**Business Impact:** PII integrity is compromised. The SSN last-4 field is used for identity verification; if it actually contains phone digits, identity checks will fail or produce false matches. Regulatory compliance (GLBA, FCRA) requires accurate SSN handling.

**Recommended Fix:** Flag records where SSN last-4 correlates with other fields. This data cannot be corrected programmatically — it requires a source system audit to obtain true SSN values.

---

## ANOM-006: Payment Date Before Received Date (Temporal Impossibility)

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_DT, PMT_RECV_DT |

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | Gap |
|-------------|--------|-------------|-----|
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | Payment date 4 days before received |
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | Payment date 17 days before received |

Both payments are for loan LN-2018-00089 (borrower B-10003, Michael Torres). The payment date should logically be on or after the received date, since a payment cannot be dated before it was received. This suggests the `PMT_DT` field represents the scheduled due date rather than the actual payment date, but the field naming is ambiguous.

**Business Impact:** Delinquency calculations will be incorrect. If PMT_DT is used to determine whether a payment was on time, these records appear current. But the actual receipt (PMT_RECV_DT) shows the payment was late — 4 and 17 days respectively. This same loan has `LN_DLQ_DAYS = '15'`, consistent with late payments.

**Recommended Fix:** Validate that `PMT_RECV_DT <= PMT_DT` or clarify field semantics. For delinquency tracking, use PMT_RECV_DT as the authoritative date.

---

## ANOM-007: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 |

**Example:**

CDW_LN_ACCT duplicates borrower fields from CDW_BORR_MSTR:
```
CDW_LN_ACCT.BORR_FST_NM = 'James'    vs  CDW_BORR_MSTR.BORR_FST_NM = 'James'
CDW_LN_ACCT.BORR_LST_NM = 'Mitchell' vs  CDW_BORR_MSTR.BORR_LST_NM = 'Mitchell'
```

Currently consistent, but there is no mechanism to keep them in sync. If a borrower updates their name (e.g., marriage), the master record would be updated but the denormalized copies in loan accounts would remain stale.

**Business Impact:** The API's `/api/loans` endpoint reads borrower names from CDW_LN_ACCT (via `acct.getBorrowerFirstName()`), while `/api/borrowers` reads from CDW_BORR_MSTR. A name change would cause the same person to appear with different names across endpoints, confusing consumers and breaking search/matching logic.

**Recommended Fix:** The service layer should read borrower names from the master table (CDW_BORR_MSTR) rather than the denormalized copy. This is already planned in the modern schema migration (column_mappings.md marks these fields as "dropped").

---

## ANOM-008: Dates Stored as Strings — Format Not Enforced

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | BORR_DOB_DT, BORR_CRET_DT, BORR_UPDT_DT, LN_ORIG_DT, LN_MAT_DT, PMT_DT, PMT_RECV_DT, etc. |

**Example:**

All date fields are VARCHAR(10) with expected format MM/DD/YYYY:
```sql
BORR_DOB_DT VARCHAR(10),  -- stored as '03/15/1978'
LN_ORIG_DT  VARCHAR(10),  -- stored as '02/15/2019'
```

The schema has no CHECK constraint enforcing the format. Legacy systems commonly produce date variants: `3/15/1978`, `1978-03-15`, `03-15-1978`, `15/03/1978` (DD/MM/YYYY). The current code passes date strings through to the DTO without parsing, meaning format inconsistencies would be silently propagated to API consumers.

**Business Impact:** Date sorting/comparison in the API layer would be lexicographic (string-based), not chronological. The column_mappings.md requires `MM/DD/YYYY -> DATE` conversion during migration — any non-conforming format will cause migration failures.

**Recommended Fix:** Parse and validate date strings at ingestion time. Use `DateTimeFormatter` with strict parsing to catch format deviations early.

---

## ANOM-009: Status Codes Not Validated Against Allowed Values

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | BORR_STAT_CD, LN_STAT_CD, PMT_STAT_CD, PMT_TYP_CD |

**Example:**

The `expandStatusCode()` method in LoanService handles: ACT, CLO, DFT, FRB. The `default` case returns the raw code:
```java
default -> code;  // unknown status passed through as-is
```

Valid codes per column_mappings.md:
- BORR_STAT_CD: ACT, INA
- LN_STAT_CD: ACT, CLO, DFT, FRB
- PMT_STAT_CD: PST, REV, NSF, PND
- PMT_TYP_CD: REG, EXT, PRT, PRE

Any other value (e.g., "XXX", "DEL", "TST") would be silently passed through to the API response.

**Business Impact:** Downstream consumers that switch on status values will encounter unrecognized codes. Business logic that filters by status (e.g., "show active loans") could miss records with invalid status codes or include test records.

**Recommended Fix:** Validate status codes against a whitelist at ingestion. Log unknown codes as warnings and map to a safe default (e.g., "UNKNOWN") rather than passing through raw values.

---

## ANOM-010: Comma-Formatted Amounts Require Special Parsing

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_BORR_MSTR, CDW_LN_ACCT, CDW_LN_PROD, CDW_PMT_HIST |
| **Affected Columns** | BORR_ANN_INCM, LN_ORIG_AMT, LN_CURR_BAL, LN_PMT_AMT, PROD_MIN_AMT, PROD_MAX_AMT, PMT_AMT, etc. |

**Example:**

```
BORR_ANN_INCM = '92,500'      -- comma as thousands separator
LN_ORIG_AMT   = '285,000'     -- comma as thousands separator
LN_CURR_BAL   = '271,432.56'  -- comma + decimal
PROD_MIN_AMT  = '0'           -- no comma
```

The `parseLegacyAmount()` method handles commas via `amount.replace(",", "")`, but locale-specific variations (e.g., `285.000,00` European format, `285 000` space separator) would fail.

**Business Impact:** Amounts parsed correctly for current data, but future data loads from different regional offices could introduce locale-specific formatting. The parsing would produce incorrect values or throw exceptions.

**Recommended Fix:** Use `DecimalFormat` with explicit locale configuration for robust amount parsing. Validate that parsed amounts are non-negative for fields like loan balances and payment amounts.

---

## ANOM-011: All-VARCHAR Schema Prevents Database-Level Type Safety

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | All tables |
| **Affected Columns** | All columns |

The entire legacy schema uses VARCHAR for every column — dates, amounts, integers, booleans. This is a common pattern in legacy data warehouses but prevents the database from enforcing any type constraints.

**Business Impact:** The database cannot reject invalid data at insert time. All validation burden falls on the application layer, which currently has none. This is a design-level issue addressed by the migration to the modern schema.

**Recommended Fix:** Already addressed by the modern schema migration plan (`data/modern-schema/modern_tables.sql`). In the interim, add application-layer validation.

---

## ANOM-012: Cryptic Column Names Increase Maintenance Risk

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | All tables |
| **Affected Columns** | All columns |

Column names use legacy abbreviation conventions: `BORR_FST_NM`, `LN_CURR_BAL`, `PMT_ESCROW_AMT`. These require institutional knowledge to interpret and increase the risk of mapping errors.

**Business Impact:** Not a runtime issue, but increases the probability of developer errors when writing queries or modifying the service layer. The column_mappings.md mitigates this by documenting the translations.

**Recommended Fix:** Already addressed by the modern schema migration. The mapping document (`data/mappings/column_mappings.md`) serves as the interim reference.
