# Data Anomaly Report

> **Generated from:** Legacy CDW schema analysis  
> **Scope:** All tables in `schema-legacy.sql` and seed data in `data-legacy.sql`  
> **Date:** 2025-12-15

---

## Anomaly 1 — SSN Last-4 Contains Phone Last-4

| Field | Detail |
|-------|--------|
| **Severity** | Critical |
| **Affected Table/Column** | `CDW_LN_ACCT.BORR_SSN_LST4` |
| **Example Bad Records** | All 5 records are affected. B-10001: phone=`217-555-0142`, SSN_LST4=`0142`. B-10002: phone=`503-555-0198`, SSN_LST4=`0198`. B-10003: phone=`512-555-0167`, SSN_LST4=`0167`. B-10004: phone=`303-555-0134`, SSN_LST4=`0134`. B-10005: phone=`602-555-0156`, SSN_LST4=`0156`. |
| **Business Impact** | PII/compliance violation. Identity verification failures if this field is used for borrower authentication. Audit exposure under GLBA and state privacy laws. |
| **Recommended Fix** | Cross-reference with actual SSN source system. Re-populate `BORR_SSN_LST4` from the authoritative SSN record. Flag field as "dropped" in migration (per `column_mappings.md` line 51) and ensure it is never used for identity verification. |

---

## Anomaly 2 — Payment Component Sum Mismatch

| Field | Detail |
|-------|--------|
| **Severity** | Critical |
| **Affected Table/Column** | `CDW_PMT_HIST`: `PMT_AMT` vs `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` |
| **Example Bad Records** | `LN-2019-00142` payments: components for PMT-2025120001 sum to `456.78 + 1074.69 + 355.55 + 0.00 = 1,887.02` but `PMT_AMT = 1,487.02` ($400 discrepancy). PMT-2025110003 (`LN-2018-00089`): late fee `$47.50` not reflected in total (`1,077.05` vs components `295.82 + 781.23 + 0.00 + 47.50 = 1,124.55`). |
| **Business Impact** | Incorrect financial reporting. Regulatory risk under SOX/GAAP. Downstream reconciliation failures for any system consuming payment data. |
| **Recommended Fix** | Add component-sum validation at ingestion time. Reconcile mismatched records with source general ledger. Implement `LegacyDataValidator.validatePaymentComponents()` in service layer. |

---

## Anomaly 3 — Unguarded Numeric Parsing

| Field | Detail |
|-------|--------|
| **Severity** | High |
| **Affected Table/Column** | Service layer: `LoanService.java` methods `parseLegacyAmount` (line 152), `parseLegacyDecimal` (line 157), `parseLegacyInteger` (line 162) |
| **Example Bad Records** | Any malformed value (e.g., `"N/A"`, `"$285,000"`, `"PENDING"`, empty string with whitespace) throws `NumberFormatException` resulting in HTTP 500. |
| **Business Impact** | Service outage on bad data. A single malformed record in any legacy table can take down the entire API. |
| **Recommended Fix** | Add try-catch with fallback defaults (`BigDecimal.ZERO` for amounts, `null` for integers) and structured logging for parse failures. See `LegacyDataValidator` class. |

---

## Anomaly 4 — Denormalized Borrower Name Drift

| Field | Detail |
|-------|--------|
| **Severity** | High |
| **Affected Table/Column** | `CDW_LN_ACCT` (`BORR_FST_NM`, `BORR_LST_NM`) vs `CDW_BORR_MSTR` (`BORR_FST_NM`, `BORR_LST_NM`) |
| **Example Bad Records** | `toLoanSummary` (line 106) uses denormalized names from `CDW_LN_ACCT`. `toBorrowerDto` (line 124) uses master names from `CDW_BORR_MSTR`. If a borrower's name is updated in the master table but not in the loan account table, the two endpoints return different names. |
| **Business Impact** | Inconsistent borrower names across API endpoints (`/api/loans` vs `/api/borrowers/{id}`). Confusing for consumers and potentially problematic for compliance reporting. |
| **Recommended Fix** | Always resolve borrower name from `CDW_BORR_MSTR` via `borrowerId` lookup. Mark denormalized name fields as informational only. |

---

## Anomaly 5 — Dates as Unvalidated Strings

| Field | Detail |
|-------|--------|
| **Severity** | Medium |
| **Affected Table/Column** | All tables, all date columns (`VARCHAR(10)`) |
| **Example Bad Records** | All date columns store raw `MM/DD/YYYY` strings with no parsing or validation. Values like `"13/32/2025"` or `"00/00/0000"` would pass through silently. Current code passes dates through as-is to DTOs (e.g., `dto.setOriginationDate(acct.getOriginationDate())` at line 113). |
| **Business Impact** | Invalid dates silently propagate to API consumers. Migration to `DATE` type in modern schema will fail on malformed values. |
| **Recommended Fix** | Parse and validate all dates using `DateTimeFormatter` with `MM/dd/yyyy` pattern. Use `LegacyDataValidator.validateDateFormat()` for pass-through fields and `LegacyDataValidator.parseDate()` for typed conversions. |

---

## Anomaly 6 — No Foreign Key Constraints

| Field | Detail |
|-------|--------|
| **Severity** | Medium |
| **Affected Table/Column** | `CDW_LN_ACCT.BORR_ID`, `CDW_LN_ACCT.PROD_CD`, `CDW_PMT_HIST.LN_ACCT_NBR` |
| **Example Bad Records** | No FK constraints in `schema-legacy.sql` (line 8 comment: "No foreign key constraints"). A payment could reference a non-existent loan account number, or a loan could reference a non-existent borrower ID or product code. |
| **Business Impact** | Orphaned records cause null lookups and silent degradation. `LoanService.toLoanSummary()` handles null product with a fallback (line 107), but other lookups would NPE. |
| **Recommended Fix** | Validate referential integrity at service layer. Log warnings for missing references. Add pre-migration integrity checks before loading into modern schema with actual FK constraints. |

---

## Anomaly 7 — Delinquency/Status Inconsistency

| Field | Detail |
|-------|--------|
| **Severity** | Medium |
| **Affected Table/Column** | `CDW_LN_ACCT`: `LN_DLQ_DAYS`, `LN_STAT_CD` |
| **Example Bad Records** | `LN-2018-00089` has `LN_DLQ_DAYS = 15` but `LN_STAT_CD = ACT`. Payment history confirms late payments (PMT-2025110003 has a $47.50 late fee and was received 17 days after due date). |
| **Business Impact** | Incorrect risk reporting. Loan appears "Active" in good standing while actually delinquent. Affects portfolio risk calculations and regulatory reporting. |
| **Recommended Fix** | Add business rule validation: if `DLQ_DAYS > 0`, status should not be `ACT`. Implement `LegacyDataValidator.validateLoanStatusConsistency()` and surface warnings in API responses. |

---

## Anomaly 8 — NULL Middle Initial

| Field | Detail |
|-------|--------|
| **Severity** | Low |
| **Affected Table/Column** | `CDW_BORR_MSTR.BORR_MID_INIT` |
| **Example Bad Records** | `B-10005` (Robert Williams) has `NULL` middle initial. Currently handled in `toBorrowerDto` (line 123) with a ternary check. |
| **Business Impact** | Minor — currently handled in code. However, no broader null-safety pattern exists for other optional fields. |
| **Recommended Fix** | Add null checks for all optional fields in translation methods. Use `LegacyDataValidator.isPresent()` for required fields. |
