# Legacy Data Anomaly Report

This report documents data quality anomalies found in the legacy CDW (Corporate Data Warehouse) seed data (`data-legacy.sql`) and schema (`schema-legacy.sql`).

---

## ANO-001: Payment Component Sum Mismatch

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Description:** The total payment amount (`PMT_AMT`) does not equal the sum of its component parts (principal + interest + escrow + late fee) for multiple records.

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | Principal | Interest | Escrow | Late Fee | Component Sum | Discrepancy |
|-------------|---------|-----------|----------|--------|----------|---------------|-------------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | +400.00 |

Both records belong to loan `LN-2019-00142` (James Mitchell). The components sum to $1,887.02 while the total is $1,487.02 -- a consistent $400.00 overage.

**Business Impact:** Financial reports, balance calculations, and amortization schedules will be incorrect. Downstream systems relying on payment breakdowns for tax reporting (1098 interest statements) or escrow analysis will produce inaccurate results.

**Recommended Fix:** Add a validation check that verifies `PMT_AMT == PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` at ingestion time. Flag mismatches and either reject the record or log a warning with the discrepancy amount. Investigate whether escrow should be excluded from the total (different accounting convention) or if the component amounts are incorrect.

---

## ANO-002: Unguarded Numeric String Parsing

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | All tables (`CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD`) |
| **Affected Columns** | All numeric-as-string columns: `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `PMT_AMT`, `PMT_PRIN_AMT`, etc. |

**Description:** All numeric values are stored as VARCHAR strings (e.g., `"285,000"`, `"4.750"`, `"745"`). The service layer parses these with `BigDecimal(string)` and `Integer.parseInt()` without try-catch protection. Any malformed value (e.g., `"N/A"`, `"$285,000"`, `"TBD"`, empty string, or extra whitespace) will throw an uncaught `NumberFormatException` that propagates as a 500 Internal Server Error, taking down the entire API response -- not just the single bad record.

**Example Risky Patterns:**
- `parseLegacyAmount("$285,000")` -- dollar sign not stripped, throws `NumberFormatException`
- `parseLegacyInteger("N/A")` -- non-numeric credit score, throws `NumberFormatException`
- `parseLegacyDecimal(" ")` -- whitespace-only string passes `isBlank()` but fails parsing

**Business Impact:** A single corrupted record in the legacy warehouse will cause the entire `/api/loans` or `/api/borrowers` endpoint to fail with a 500 error, making the service unavailable for all users. This is an availability risk.

**Recommended Fix:** Wrap all parsing methods in try-catch blocks. Return a safe fallback default (e.g., `BigDecimal.ZERO` for amounts, `null` for optional integers) and log a warning with the field name, raw value, and record ID for investigation.

---

## ANO-003: SSN Last-4 Digits Match Phone Number Last-4 Digits

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` cross-referenced with `CDW_BORR_MSTR` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_SSN_LST4`, `CDW_BORR_MSTR.BORR_PH_NBR` |

**Description:** For all 5 borrowers, the SSN last-4 digits stored in the loan account table exactly match the last 4 digits of the borrower's phone number. This is statistically improbable and indicates either data corruption, improper test-data generation, or a copy-paste error during ETL.

| Borrower | BORR_SSN_LST4 | BORR_PH_NBR | Phone Last 4 |
|----------|---------------|-------------|--------------|
| B-10001 (James Mitchell) | 0142 | 217-555-0142 | 0142 |
| B-10002 (Sarah Chen) | 0198 | 503-555-0198 | 0198 |
| B-10003 (Michael Torres) | 0167 | 512-555-0167 | 0167 |
| B-10004 (Emily Johnson) | 0134 | 303-555-0134 | 0134 |
| B-10005 (Robert Williams) | 0156 | 602-555-0156 | 0156 |

**Business Impact:** If this data is used for identity verification (e.g., "confirm your last 4 SSN digits"), the verification is effectively checking phone number digits instead of actual SSN. This is a PII integrity risk and could lead to regulatory compliance issues (GLBA, FCRA).

**Recommended Fix:** Add a cross-field validation that flags records where `BORR_SSN_LST4` matches the last 4 digits of `BORR_PH_NBR`. These records should be quarantined for manual review. The SSN data should be re-sourced from the authoritative identity system.

---

## ANO-004: No Foreign Key Constraints (Orphan Risk)

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |

**Description:** The legacy schema declares no foreign key constraints. Any of the following orphan scenarios are possible:
- A loan account references a non-existent borrower (`BORR_ID` not in `CDW_BORR_MSTR`)
- A loan account references a non-existent product (`PROD_CD` not in `CDW_LN_PROD`)
- A payment references a non-existent loan (`LN_ACCT_NBR` not in `CDW_LN_ACCT`)

In the current code, `getAllLoans()` uses `products.get(acct.getProductCode())` which returns `null` for unknown product codes, and the null is passed to `toLoanSummary()` where it falls back to the raw code. However, `getLoanById()` uses `findById().orElse(null)` which can also produce null products silently.

**Business Impact:** Orphaned records produce incomplete or misleading API responses. A loan with no matching product will show a cryptic code instead of a description. A payment referencing a deleted loan will be invisible in payment history queries.

**Recommended Fix:** Add referential integrity validation at ingestion time. Before processing a loan account, verify that its `BORR_ID` exists in the borrower table and `PROD_CD` exists in the product table. Log and flag orphaned records.

---

## ANO-005: Date Fields Stored as Unvalidated Strings

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_DOB_DT`, `BORR_CRET_DT`, `BORR_UPDT_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT`, etc. |

**Description:** All date columns are VARCHAR(10) with an expected format of `MM/DD/YYYY`. However, no validation is performed. The service layer passes date strings directly to DTOs (`dto.setOriginationDate(acct.getOriginationDate())`) without parsing or validating them. Values like `"13/45/2020"`, `"2020-01-15"` (ISO format), or `"TBD"` would be passed through to API consumers without any error.

**Business Impact:** API consumers receiving dates in unpredictable formats may fail to parse them, leading to downstream errors. Invalid dates (e.g., February 30) would propagate silently. Mixed date formats would break sorting and comparison logic.

**Recommended Fix:** Parse all date strings through `DateTimeFormatter.ofPattern("MM/dd/yyyy")` at ingestion time. Invalid dates should be logged and replaced with null or a sentinel value. Consider converting to ISO 8601 format in API responses.

---

## ANO-006: Denormalized Borrower Data Staleness Risk

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Description:** The loan account table contains denormalized copies of borrower first name, last name, and SSN last-4. These duplicated fields can become stale if the master borrower record in `CDW_BORR_MSTR` is updated without propagating changes to `CDW_LN_ACCT`. The service layer uses the denormalized copy in `toLoanSummary()` (line 106: `acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName()`) rather than looking up the authoritative borrower record.

**Example Risk:** If borrower B-10002 (Sarah Chen) changes her last name, the master record in `CDW_BORR_MSTR` would be updated but the loan account `LN-2020-00398` would still show "Chen" as the last name.

**Business Impact:** Customer-facing documents (statements, correspondence) could display outdated names. This creates compliance issues for identity verification and legal documents.

**Recommended Fix:** Add a cross-reference validation that compares denormalized fields against the master borrower record. Flag discrepancies. In the service layer, prefer the master record over the denormalized copy.

---

## ANO-007: Unknown Status Codes Silently Passed Through

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_BORR_MSTR` |
| **Affected Columns** | `LN_STAT_CD`, `PMT_STAT_CD`, `PMT_TYP_CD`, `BORR_STAT_CD` |

**Description:** The `expandStatusCode()`, `expandPaymentType()`, and `expandPaymentStatus()` methods use switch expressions with a `default -> code` fallback that silently passes through unrecognized codes. If a legacy record contains an unexpected code (e.g., `"XYZ"` for loan status), the API returns the raw cryptic code instead of a meaningful value or error.

**Valid Loan Status Codes:** ACT, CLO, DFT, FRB
**Valid Payment Types:** REG, EXT, PRT, PRE
**Valid Payment Statuses:** PST, REV, NSF, PND

**Business Impact:** API consumers expecting a defined set of status values may mishandle unknown codes. Reporting dashboards grouping by status will have an "other" bucket that masks data quality problems.

**Recommended Fix:** Replace the silent pass-through default with a logged warning and a standardized "UNKNOWN" value. Add validation at ingestion time that flags records with unrecognized status codes.

---

## ANO-008: Credit Score Not Range-Validated

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_CRDT_SCR` |

**Description:** Credit scores are stored as VARCHAR and parsed to integers without range validation. Valid FICO scores range from 300 to 850. Values outside this range (e.g., `"0"`, `"999"`, `"-1"`, `"85"`) would be accepted and returned in API responses without any flag.

**Current Scores in Data:**
| Borrower | Credit Score | Valid? |
|----------|-------------|--------|
| B-10001 | 745 | Yes |
| B-10002 | 780 | Yes |
| B-10003 | 692 | Yes |
| B-10004 | 810 | Yes |
| B-10005 | 658 | Yes |

While current data is valid, the absence of range validation means future corrupted data would silently propagate.

**Business Impact:** Invalid credit scores could affect loan eligibility calculations, risk assessments, and regulatory reporting.

**Recommended Fix:** Add range validation (300-850) when parsing credit scores. Flag out-of-range values as warnings and set to null.

---

## ANO-009: Null Values in Conditionally Required Fields

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` |

**Description:** Some fields that may be expected by downstream consumers are NULL. Borrower B-10005 (Robert Williams) has a NULL middle initial. Borrowers B-10002, B-10003, and B-10005 have NULL address line 2.

The service layer handles the null middle initial gracefully (line 123: conditional concatenation), but does not validate whether truly required fields (like first name or last name) might also be null in future data loads.

**Business Impact:** Low for current data as the code handles these cases. However, a NULL first name or last name would cause `toBorrowerDto()` to produce "null null" as the full name.

**Recommended Fix:** Add null checks for fields that the modern schema marks as NOT NULL (`first_name`, `last_name`, `original_amount`, `current_balance`, etc.). Reject records missing required fields.

---

## ANO-010: Annual Income Not Exposed in API

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_ANN_INCM` |

**Description:** The column mappings document (`column_mappings.md`) specifies that `BORR_ANN_INCM` should be parsed by removing commas and converting to `DECIMAL(12,2)`. However, `BorrowerDto` does not include an annual income field, and `toBorrowerDto()` does not process this column. The data contains comma-formatted values like `"92,500"` and `"125,000"` that would need the same `parseLegacyAmount()` treatment if exposed.

**Business Impact:** Income data is available in the legacy system but not accessible through the API. Any downstream system needing income data for debt-to-income calculations or underwriting cannot use this service.

**Recommended Fix:** Add `annualIncome` (BigDecimal) to `BorrowerDto` and parse `BORR_ANN_INCM` in `toBorrowerDto()` using `parseLegacyAmount()`.
