# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## ANO-001: Payment Component Amounts Do Not Sum to Total

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN + INT + ESCROW + LATE | Difference |
|---|---|---|---|
| `PMT-2025120001` | 1,487.02 | 456.78 + 1,074.69 + 355.55 + 0.00 = **1,887.02** | **-400.00** |
| `PMT-2025110001` | 1,487.02 | 454.97 + 1,076.50 + 355.55 + 0.00 = **1,887.02** | **-400.00** |
| `PMT-2025110003` | 1,077.05 | 295.82 + 781.23 + 0.00 + 47.50 = **1,124.55** | **-47.50** |

**Business Impact:** Financial reporting becomes unreliable. Downstream systems that depend on component-level breakdown (escrow accounting, interest accrual reports, investor remittance) will produce incorrect totals. Auditors will flag reconciliation failures. For loan `LN-2019-00142`, the escrow portion appears to be excluded from the total, creating a persistent $400 discrepancy per payment.

**Recommended Fix:** Add a validation check at ingestion time that verifies `total == principal + interest + escrow + late_fee` within a configurable tolerance (e.g., $0.01 for rounding). Flag records that fail as `NEEDS_REVIEW` and log a warning. Provide a fallback that recalculates the total from components when a mismatch is detected.

---

## ANO-002: SSN Last-4 Digits Match Phone Number Last-4 Digits

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_SSN_LST4`, `CDW_BORR_MSTR.BORR_PH_NBR` |

**Example Bad Records:**

| BORR_ID | BORR_SSN_LST4 | BORR_PH_NBR | Phone Last-4 |
|---|---|---|---|
| B-10001 | 0142 | 217-555-**0142** | 0142 |
| B-10002 | 0198 | 503-555-**0198** | 0198 |
| B-10003 | 0167 | 512-555-**0167** | 0167 |
| B-10004 | 0134 | 303-555-**0134** | 0134 |
| B-10005 | 0156 | 602-555-**0156** | 0156 |

**Business Impact:** 100% of records exhibit this pattern, indicating a systemic data entry or ETL error where phone number digits were copied into the SSN last-4 field. This is a PII integrity violation with regulatory implications (GLBA, FCRA). Any identity verification or loan servicing process that relies on SSN last-4 for borrower authentication is using incorrect data. Fraud detection systems will not function correctly.

**Recommended Fix:** Flag all `BORR_SSN_LST4` values as untrusted. Add a cross-field validation that detects when SSN last-4 matches phone last-4 and marks the record for manual review. Do not expose SSN last-4 in API responses until data is verified against the encrypted SSN source.

---

## ANO-003: No Numeric Parsing Error Handling — Malformed Strings Cause Runtime Crashes

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | All tables (`CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_LN_PROD`) |
| **Affected Columns** | All VARCHAR columns that store numeric values: `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `PMT_AMT`, etc. |

**Example Scenario:** If legacy data contains `"$285,000"`, `"N/A"`, `"TBD"`, or empty strings in amount fields, `LoanService.parseLegacyAmount()` calls `new BigDecimal(...)` which throws an unchecked `NumberFormatException`. This propagates as an HTTP 500 to API consumers.

**Current Code (no error handling):**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // throws on "$", "N/A", etc.
}
```

**Business Impact:** A single bad record in any table causes the entire API endpoint to fail with an unhandled exception. The `/api/loans` endpoint calls `parseLegacyAmount` for every loan record — one malformed amount crashes the entire listing. There is no partial degradation or error isolation.

**Recommended Fix:** Wrap all parsing methods in try-catch blocks. Log the original value and record identifier. Return a safe default (e.g., `BigDecimal.ZERO`) or `null` with a validation warning. Strip non-numeric characters (except `.` and `-`) before parsing.

---

## ANO-004: Delinquency Days Inconsistent with Loan Status

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Example Bad Records:**

| LN_ACCT_NBR | LN_STAT_CD | LN_DLQ_DAYS |
|---|---|---|
| LN-2018-00089 | ACT | 15 |

**Business Impact:** Loan `LN-2018-00089` is marked "Active" but has 15 delinquency days. Per industry standards, loans with >0 delinquency days should be flagged with a delinquent status (e.g., 30/60/90 day buckets). Regulatory reporting (HMDA, Call Report) requires accurate delinquency status alignment. Servicers relying on status code alone will underreport delinquent loans.

**Recommended Fix:** Add cross-field validation: if `delinquencyDays > 0` and `statusCode == "ACT"`, flag the record with a warning. Consider adding a derived `isDelinquent` field to the DTO.

---

## ANO-005: Schema Allows NULL in Business-Critical Fields

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | All tables |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_ENCR`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_STAT_CD`, `PMT_AMT`, `PMT_STAT_CD` |

**Example Scenario:** The schema defines no `NOT NULL` constraints beyond primary keys. A record like `INSERT INTO CDW_BORR_MSTR VALUES ('B-99999', NULL, NULL, ...)` is valid SQL. When `LoanService.toBorrowerDto()` constructs the full name via `borrower.getFirstName() + middle + " " + borrower.getLastName()`, a null first or last name produces `"null R. null"` in the API response.

**Business Impact:** Null borrower names, null loan amounts, or null status codes would produce malformed API responses. Downstream consumers parsing JSON would encounter unexpected `null` values or literal `"null"` strings in name fields. Loan listing pages would display broken data.

**Recommended Fix:** Add null checks for all business-critical fields at the service layer. For names, substitute `"[Unknown]"` as a fallback. For amounts, default to `BigDecimal.ZERO`. For status codes, default to `"Unknown"`.

---

## ANO-006: Denormalized Borrower Data Can Diverge from Master Record

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT` vs. `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM` (present in both tables) |

**Example Records:**

| Source | BORR_ID | First Name | Last Name |
|---|---|---|---|
| CDW_BORR_MSTR | B-10001 | James | Mitchell |
| CDW_LN_ACCT (LN-2019-00142) | B-10001 | James | Mitchell |

Currently the seed data is consistent, but the schema has no mechanism to enforce this. If a borrower's name is updated in `CDW_BORR_MSTR` but not in `CDW_LN_ACCT`, the API will return different names depending on which endpoint is called (`/api/loans` uses the denormalized copy, `/api/borrowers` uses the master).

**Business Impact:** Regulatory correspondence (e.g., loss mitigation letters) may use the wrong borrower name. Customer complaints about incorrect information. Reconciliation failures between systems.

**Recommended Fix:** Always prefer the master record (`CDW_BORR_MSTR`) for borrower details. Add a validation that detects and logs divergence between the denormalized and master copies. In the DTO mapping, join to the master rather than using denormalized fields.

---

## ANO-007: Date Fields Stored as Unparsed Strings — No Format Validation

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | All tables |
| **Affected Columns** | All `*_DT` columns: `BORR_DOB_DT`, `LN_ORIG_DT`, `LN_MAT_DT`, `PMT_DT`, etc. |

**Example:** All current seed data uses `MM/DD/YYYY` format consistently. However, the schema accepts any VARCHAR(10) value. The `LoanService` passes date strings directly to DTOs without parsing (e.g., `dto.setOriginationDate(acct.getOriginationDate())` on line 113).

The column_mappings.md specifies: `Parse MM/DD/YYYY -> DATE`. But the current code performs no parsing — it just passes the raw string through to the API response.

**Business Impact:** API consumers receive date strings in an unpredictable format. If legacy data contains dates like `"2025-01-15"` (ISO), `"01-15-2025"` (dashes), or `"01/15/25"` (2-digit year), the API returns them as-is with no normalization. Frontend clients that parse `MM/DD/YYYY` will break.

**Recommended Fix:** Parse all date strings using `DateTimeFormatter` with the expected `MM/dd/yyyy` pattern. Return ISO-8601 (`yyyy-MM-dd`) in API responses. Log warnings for unparseable dates and substitute `null` with an explicit `"dateParseError"` flag.

---

## ANO-008: LTV Percent Has Rounding Discrepancies vs. Computed Value

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_LTV_PCT`, `LN_ORIG_AMT`, `PROP_APRS_VAL` |

**Example Bad Records:**

| LN_ACCT_NBR | LN_ORIG_AMT | PROP_APRS_VAL | Stored LTV | Computed LTV |
|---|---|---|---|---|
| LN-2019-00142 | 285,000 | 345,000 | 82.5 | 82.61 |
| LN-2020-00398 | 420,000 | 615,000 | 68.2 | 68.29 |
| LN-2017-00034 | 165,000 | 206,000 | 80.0 | 80.10 |

**Business Impact:** LTV is a critical metric for mortgage risk assessment. Rounding discrepancies, while small, can affect risk bucket classification (e.g., 80.0% vs. 80.1% determines whether PMI is required). Inconsistent rounding rules make it unclear whether the stored value or computed value is authoritative.

**Recommended Fix:** Add a validation check comparing stored LTV against computed `(originalAmount / appraisedValue * 100)`. Flag discrepancies exceeding 0.5%. Consider always computing LTV from the source values rather than trusting the stored value.

---

## ANO-009: Payment Late Fee Recorded but Not Reflected in Status

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_LATE_FEE`, `PMT_STAT_CD` |

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_LATE_FEE | PMT_STAT_CD | Expected Status |
|---|---|---|---|
| PMT-2025110003 | 47.50 | PST (Posted) | Should indicate late payment |

**Business Impact:** Payment `PMT-2025110003` has a $47.50 late fee but is marked as "Posted" (normal). There is no status code or flag to indicate the payment was late. Consumer-facing statements and reporting systems have no way to distinguish on-time from late payments except by examining the late fee amount, which requires extra business logic.

**Recommended Fix:** Add validation that checks for `lateFee > 0` and ensures the payment is flagged appropriately. Consider adding a `wasLate` boolean to the `PaymentDto`.

---

## ANO-010: Payment Received After Due Date — Late Payment Detection Gap

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT`, `PMT_RECV_DT`, `PMT_PROC_DT` |

**Example Records:**

| PMT_SEQ_NBR | PMT_DT (Due) | PMT_RECV_DT | Days Late |
|---|---|---|---|
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 4 |
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 17 |

**Business Impact:** These payments were received well after the due date (correlating with the late fee on PMT-2025110003 and the 15-day delinquency on loan LN-2018-00089). The system does not automatically detect or flag this pattern. Combined with ANO-004, this borrower shows a pattern of late payment that should trigger servicing alerts.

**Recommended Fix:** Add a validation that computes `receivedDate - paymentDate` and flags payments received more than a configurable grace period (typically 15 days) after the due date.
