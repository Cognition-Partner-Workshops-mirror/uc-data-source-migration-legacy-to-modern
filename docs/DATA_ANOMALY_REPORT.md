# Legacy CDW Data Anomaly Report

> **Generated:** 2026-05-07
> **Source:** `src/main/resources/data-legacy.sql`, `src/main/resources/schema-legacy.sql`
> **Scope:** CDW_BORR_MSTR, CDW_LN_PROD, CDW_LN_ACCT, CDW_PMT_HIST

---

## ANM-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_AMT, PMT_PRIN_AMT, PMT_INT_AMT, PMT_ESCROW_AMT, PMT_LATE_FEE |

**Description:**
For loan LN-2019-00142, the sum of payment components (principal + interest + escrow + late fee) does not equal the stated total amount. The components exceed the total by exactly 400.00 in both payment records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN | INT | ESCROW | LATE | Component Sum | Delta |
|-------------|---------|------|-----|--------|------|---------------|-------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | +400.00 |

**Business Impact:**
Financial reporting based on component breakdowns will overstate interest income by ~400.00 per payment. Loan amortization schedules, escrow analysis, and regulatory reporting (TILA, RESPA) will be inaccurate. This directly impacts borrower statements and investor remittance calculations.

**Recommended Fix:**
Validate at ingestion that `PMT_AMT == PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. Flag mismatches for manual review and prevent propagation to downstream systems. The interest amount appears inflated; recalculate from the loan's amortization schedule.

---

## ANM-002: SSN Last-4 Digits Match Phone Number Last-4

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | BORR_SSN_LST4 |

**Description:**
Every borrower's `BORR_SSN_LST4` in CDW_LN_ACCT matches the last 4 digits of their phone number in CDW_BORR_MSTR, rather than their actual SSN. This indicates a systematic data-entry or ETL error where the phone suffix was copied into the SSN field.

**Example Bad Records:**

| BORR_ID | BORR_SSN_LST4 | BORR_PH_NBR (from CDW_BORR_MSTR) | Phone Last 4 |
|---------|---------------|-----------------------------------|---------------|
| B-10001 | 0142 | 217-555-0142 | 0142 |
| B-10002 | 0198 | 503-555-0198 | 0198 |
| B-10003 | 0167 | 512-555-0167 | 0167 |
| B-10004 | 0134 | 303-555-0134 | 0134 |
| B-10005 | 0156 | 602-555-0156 | 0156 |

**Business Impact:**
SSN last-4 is used for borrower identity verification (phone verification, customer service authentication, duplicate detection). Storing phone digits instead of SSN digits means identity verification is fundamentally broken. This is also a compliance risk (GLBA, FCRA) if the field is used in credit reporting or fraud detection.

**Recommended Fix:**
Flag all BORR_SSN_LST4 values as untrusted. Cross-reference against the encrypted SSN in CDW_BORR_MSTR (BORR_SSN_ENCR) to derive the correct last-4 digits. Add a validation rule that rejects records where SSN_LST4 matches phone suffix.

---

## ANM-003: No Input Validation on Numeric String Parsing

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | All tables |
| **Affected Columns** | All VARCHAR columns parsed to BigDecimal/Integer (LN_ORIG_AMT, LN_CURR_BAL, BORR_CRDT_SCR, BORR_ANN_INCM, etc.) |

**Description:**
The legacy schema stores all numeric values as VARCHAR strings (amounts with commas like "285,000", rates like "4.750", integers like "360"). The service layer (`LoanService.parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`) parses these without try-catch blocks. Any malformed value (e.g., "$285,000", "N/A", empty string with whitespace, or currency symbols) will throw an unhandled `NumberFormatException`, crashing the entire API request.

**Example Risk Scenarios:**
- Amount with currency symbol: `"$285,000"` → `NumberFormatException` in `parseLegacyAmount`
- Non-numeric placeholder: `"N/A"` or `"PENDING"` in credit score → `NumberFormatException` in `parseLegacyInteger`
- Double comma: `"285,,000"` → `NumberFormatException`
- Whitespace-only string: `"   "` passes the `isBlank()` check in some methods but not consistently

**Business Impact:**
A single malformed record in the CDW causes the entire API endpoint to return HTTP 500, making all loan or borrower data unavailable. There is no partial failure — one bad record poisons the entire result set because the stream-based mapping (`findAll().stream().map(...)`) has no error isolation.

**Recommended Fix:**
Wrap all parsing methods in try-catch blocks. Log warnings for unparseable values and return sensible defaults (BigDecimal.ZERO for amounts, null for optional integers). Consider adding a `DataQualityWarning` field to DTOs to flag records with parsing issues.

---

## ANM-004: Delinquent Loan with Active Status

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | LN_STAT_CD, LN_DLQ_DAYS |

**Description:**
Loan LN-2018-00089 has `LN_DLQ_DAYS = '15'` (15 days delinquent) but `LN_STAT_CD = 'ACT'` (Active). By standard mortgage servicing rules, loans delinquent beyond a threshold (typically 30 days) should transition to a delinquent or pre-default status. While 15 days may still be within the grace period, the presence of a non-zero delinquency with active status indicates the status field is not being synchronized with the delinquency tracking system.

**Example Bad Records:**

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS | Expected Status |
|-------------|------------|-------------|-----------------|
| LN-2018-00089 | ACT | 15 | ACT (grace period) or DLQ |

**Business Impact:**
Portfolio risk reporting will undercount delinquent loans. Collection workflows that trigger based on status code will miss this loan. Investor reporting (Fannie Mae/Freddie Mac) requires accurate delinquency status alignment.

**Recommended Fix:**
Add a cross-field validation rule: if `LN_DLQ_DAYS > 0`, flag the record for review. If `LN_DLQ_DAYS >= 30`, reject `ACT` status and require `DFT` or a delinquency-specific code.

---

## ANM-005: Null Values in Contextually Required Fields

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_BORR_MSTR, CDW_LN_ACCT |
| **Affected Columns** | BORR_MID_INIT, BORR_ADDR_LN2, all VARCHAR columns |

**Description:**
The legacy schema defines all columns as nullable VARCHAR with no NOT NULL constraints. While some nulls are legitimate (BORR_ADDR_LN2 for addresses without a second line, BORR_MID_INIT for borrowers without middle names), there is no protection against null values in fields that are effectively required for business operations (BORR_FST_NM, BORR_LST_NM, LN_ORIG_AMT, LN_CURR_BAL, etc.).

**Example Bad Records:**

| Record | Column | Value | Impact |
|--------|--------|-------|--------|
| B-10005 | BORR_MID_INIT | NULL | Handled by code null-check |
| B-10002 | BORR_ADDR_LN2 | NULL | Legitimate — no 2nd address line |
| (potential) | BORR_FST_NM | NULL | Would produce "null Mitchell" in API |
| (potential) | LN_ORIG_AMT | NULL | Would return BigDecimal.ZERO — misleading |

**Business Impact:**
Null first/last names cause "null" to appear in borrower names in the API response. Null amounts default to zero, which is misleading (a $0 loan amount vs. a missing value). The property address concatenation in `toLoanSummary` produces strings like `"null, null, null null"` when property fields are null.

**Recommended Fix:**
Add null-checks before string concatenation. For required business fields (names, amounts, dates), validate presence and reject or flag records with missing values rather than silently defaulting.

---

## ANM-006: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | BORR_ID, PROD_CD, LN_ACCT_NBR |

**Description:**
The legacy schema has zero foreign key constraints. CDW_LN_ACCT.BORR_ID is not constrained to CDW_BORR_MSTR.BORR_ID, CDW_LN_ACCT.PROD_CD is not constrained to CDW_LN_PROD.PROD_CD, and CDW_PMT_HIST.LN_ACCT_NBR is not constrained to CDW_LN_ACCT.LN_ACCT_NBR.

In the current seed data, all relationships resolve correctly. However, in production with no constraints, orphaned records are inevitable.

**Example Risk Scenarios:**
- A loan account referencing a deleted borrower → `getLoanById` returns a loan with no valid borrower
- A payment referencing a non-existent loan → `getPaymentsByLoan` returns payments for phantom loans
- A loan with an invalid product code → `products.get(acct.getProductCode())` returns null, causing `product.getDescription()` to fall through to the product code string

**Business Impact:**
The `getAllLoans()` method builds a product lookup map from all products, then does `products.get(acct.getProductCode())`. An orphaned product code returns null, which is handled (falls back to code string). But orphaned borrower IDs in `getBorrowerById` would cause mismatched loan-borrower associations.

**Recommended Fix:**
Add referential integrity validation at the service layer. Before mapping a loan, verify that `borrowerId` exists in the borrower table and `productCode` exists in the product table. Log and skip orphaned records.

---

## ANM-007: Denormalized Borrower Data Drift Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | BORR_FST_NM, BORR_LST_NM, BORR_SSN_LST4 |

**Description:**
CDW_LN_ACCT contains denormalized copies of borrower fields (first name, last name, SSN last-4). These are copies from CDW_BORR_MSTR at the time of loan origination. If the borrower master is updated (e.g., name change after marriage), the loan account retains the old values, creating a data drift.

In the current data, the denormalized names match the master table. However, the architecture guarantees eventual divergence as borrower records are updated.

**Example:**

| Source | BORR_FST_NM | BORR_LST_NM |
|--------|-------------|-------------|
| CDW_BORR_MSTR (B-10002) | Sarah | Chen |
| CDW_LN_ACCT (LN-2020-00398) | Sarah | Chen |

Currently consistent, but if B-10002's last name changes to "Chen-Wang", the loan account will still show "Chen".

**Business Impact:**
The API `toLoanSummary` uses the denormalized name from CDW_LN_ACCT (line 106), while `toBorrowerDto` uses the master name from CDW_BORR_MSTR. A borrower detail page and a loan summary could show different names for the same person.

**Recommended Fix:**
Always resolve borrower name from CDW_BORR_MSTR via the BORR_ID foreign key. Use the denormalized fields only as a fallback when the master record is unavailable.

---

## ANM-008: Late Fee Inconsistently Reflected in Payment Total

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_PMT_HIST |
| **Affected Columns** | PMT_AMT, PMT_LATE_FEE |

**Description:**
The treatment of late fees in the total payment amount is inconsistent. For PMT-2025110003, a late fee of $47.50 exists but the total amount (1,077.05) equals only principal + interest (295.82 + 781.23 = 1,077.05), excluding the late fee. It is unclear whether PMT_AMT is meant to include or exclude late fees, as there is no documented business rule.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN + INT | LATE_FEE | Sum incl. Late |
|-------------|---------|------------|----------|----------------|
| PMT-2025120003 | 1,077.05 | 1,077.05 | 0.00 | 1,077.05 |
| PMT-2025110003 | 1,077.05 | 1,077.05 | 47.50 | 1,124.55 |

**Business Impact:**
Late fee revenue tracking is unreliable. If PMT_AMT is used for cash-flow reconciliation, the late fee is "lost" — it exists in the component field but is not reflected in the total. This affects GL posting and revenue recognition.

**Recommended Fix:**
Define a clear business rule for whether PMT_AMT includes late fees. Add a validation rule that checks component consistency based on the chosen rule. Flag discrepancies for reconciliation.

---

## ANM-009: Date Strings Not Validated Before Temporal Parsing

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All `_DT` columns (BORR_DOB_DT, LN_ORIG_DT, PMT_DT, etc.) |

**Description:**
All dates are stored as VARCHAR in MM/DD/YYYY format. The current data is consistently formatted, but the schema accepts any string value. The service layer passes date strings directly to DTOs without parsing or validation — dates are exposed as raw strings in the API response (`LoanSummaryDto.originationDate`, `PaymentDto.paymentDate`).

If a date field contains a value like "00/00/0000", "TBD", "2025-01-15" (ISO format), or an empty string, it would pass through to the API response as-is. Any downstream consumer attempting to parse MM/DD/YYYY would fail.

**Example Risk Scenarios:**
- ISO format mixed in: `"2025-01-15"` instead of `"01/15/2025"`
- Placeholder value: `"00/00/0000"` or `"99/99/9999"`
- Null date passed through as string `"null"` in concatenated property address

**Business Impact:**
API consumers that parse the date strings will encounter errors. The migration to the modern schema (which uses DATE/TIMESTAMP types) will fail on any records with invalid date formats, blocking the migration.

**Recommended Fix:**
Parse and validate all date strings at ingestion time using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Replace invalid dates with null and log a warning. Return parsed `LocalDate` objects in DTOs rather than raw strings.

---

## ANM-010: Property Address Concatenation Produces Malformed Output

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | PROP_ADDR_LN1, PROP_CTY_NM, PROP_ST_CD, PROP_ZIP_CD |

**Description:**
In `LoanService.toLoanSummary()` (line 114), the property address is constructed by concatenating: `propertyAddress + ", " + propertyCity + ", " + propertyState + " " + propertyZip`. If any of these fields are null, the result includes literal "null" text (e.g., "null, null, null null").

The current seed data has no null property fields, but the schema allows it.

**Business Impact:**
API consumers would display "null, Springfield, IL 62701" to end users, which is unprofessional and indicates poor data quality in customer-facing applications.

**Recommended Fix:**
Build the address string conditionally, skipping null components. Use a helper method that filters out null parts and joins with appropriate delimiters.

---

## ANM-011: Unrecognized Status Codes Pass Through Unchanged

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | CDW_LN_ACCT, CDW_PMT_HIST |
| **Affected Columns** | LN_STAT_CD, PMT_TYP_CD, PMT_STAT_CD |

**Description:**
The `expandStatusCode`, `expandPaymentType`, and `expandPaymentStatus` methods in LoanService have a `default -> code` case that passes through unrecognized codes unchanged. The valid codes are: LN_STAT_CD (ACT, CLO, DFT, FRB), PMT_TYP_CD (REG, EXT, PRT, PRE), PMT_STAT_CD (PST, REV, NSF, PND). Any other value passes through as the raw abbreviation.

**Business Impact:**
API consumers receive inconsistent responses — some records have expanded human-readable statuses ("Active") and others have raw codes ("XYZ"). This breaks any UI or downstream logic that relies on a fixed set of status values.

**Recommended Fix:**
Log a warning for unrecognized codes. Either reject the record or map to a default "UNKNOWN" status. Maintain a strict allowlist of valid codes per field.

---

## ANM-012: LTV Percent Minor Rounding Discrepancies

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | CDW_LN_ACCT |
| **Affected Columns** | LN_LTV_PCT, LN_ORIG_AMT, PROP_APRS_VAL |

**Description:**
The stored LTV percentages show minor rounding discrepancies when compared to the calculated value (original amount / appraised value * 100).

**Example Records:**

| LN_ACCT_NBR | LN_ORIG_AMT | PROP_APRS_VAL | Stored LTV | Calculated LTV | Delta |
|-------------|-------------|---------------|------------|----------------|-------|
| LN-2019-00142 | 285,000 | 345,000 | 82.5 | 82.61 | -0.11 |
| LN-2020-00398 | 420,000 | 615,000 | 68.2 | 68.29 | -0.09 |
| LN-2017-00034 | 165,000 | 206,000 | 80.0 | 80.10 | -0.10 |

**Business Impact:**
Minor impact for most use cases. However, loans near regulatory LTV thresholds (e.g., 80% for PMI requirements) could be misclassified. LN-2017-00034 stores 80.0% but the actual LTV is 80.10%, which crosses the 80% PMI threshold.

**Recommended Fix:**
Recalculate LTV from the source fields at ingestion time rather than trusting the stored value. Use consistent rounding rules (e.g., HALF_UP to 2 decimal places).

---

## Summary

| ID | Title | Severity | Table |
|----|-------|----------|-------|
| ANM-001 | Payment Component Sum Mismatch | Critical | CDW_PMT_HIST |
| ANM-002 | SSN Last-4 Matches Phone Last-4 | Critical | CDW_LN_ACCT |
| ANM-003 | No Input Validation on Numeric Parsing | Critical | All |
| ANM-004 | Delinquent Loan with Active Status | High | CDW_LN_ACCT |
| ANM-005 | Null Values in Required Fields | High | CDW_BORR_MSTR, CDW_LN_ACCT |
| ANM-006 | No Foreign Key Constraints | High | CDW_LN_ACCT, CDW_PMT_HIST |
| ANM-007 | Denormalized Borrower Data Drift | Medium | CDW_LN_ACCT |
| ANM-008 | Late Fee Inconsistently in Total | Medium | CDW_PMT_HIST |
| ANM-009 | Date Strings Not Validated | Medium | All |
| ANM-010 | Property Address Null Concatenation | Medium | CDW_LN_ACCT |
| ANM-011 | Unrecognized Status Codes Pass Through | Low | CDW_LN_ACCT, CDW_PMT_HIST |
| ANM-012 | LTV Rounding Discrepancies | Low | CDW_LN_ACCT |
