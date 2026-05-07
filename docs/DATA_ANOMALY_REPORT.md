# Data Anomaly Report — Legacy CDW Tables

> Generated from analysis of `schema-legacy.sql` and `data-legacy.sql`

---

## ANM-001: Payment Component Amounts Exceed Total Payment

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_AMT`, `PMT_PRIN_AMT`, `PMT_INT_AMT`, `PMT_ESCROW_AMT`, `PMT_LATE_FEE` |

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_AMT | PRIN | INT | ESCROW | LATE_FEE | Computed Sum |
|-------------|---------|------|------|--------|----------|--------------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 |
| PMT-2025120002 | 2,924.18 | 1,842.56 | 815.50 | 266.12 | 0.00 | 2,924.18 |

Payments PMT-2025120001 and PMT-2025110001 have component sums ($1,887.02) that exceed the stated total ($1,487.02) by $400.00. This is a $400 discrepancy per payment.

**Business Impact:** Financial reconciliation failures. API consumers relying on component amounts for accounting will have balances that do not tie out. Regulatory reporting could be inaccurate.

**Recommended Fix:** Add a validation check that `principal + interest + escrow + late_fee == total_amount` (within a small rounding tolerance). Flag records that fail and fall back to reporting the total as authoritative while logging the discrepancy.

---

## ANM-002: Delinquent Loan Marked as Active

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `LN_DLQ_DAYS`, `LN_STAT_CD` |

**Example Bad Records:**

| LN_ACCT_NBR | LN_DLQ_DAYS | LN_STAT_CD | Expected Status |
|-------------|-------------|------------|-----------------|
| LN-2018-00089 | 15 | ACT | DFT or FRB |

Loan LN-2018-00089 (borrower B-10003, Michael Torres) has 15 delinquency days but is marked as `ACT` (Active). Industry standards typically flag loans as delinquent after 30 days, but any non-zero delinquency with an active status is a data consistency issue.

**Business Impact:** Risk management dashboards will undercount delinquent loans. Servicing workflows that trigger based on status code will not initiate collection actions. Regulatory reports (e.g., call reports) will misclassify the loan.

**Recommended Fix:** Validate that `LN_DLQ_DAYS > 0` implies `LN_STAT_CD` is not `ACT`. Log a warning when this invariant is violated, and include the delinquency days in the API response so consumers can make their own determination.

---

## ANM-003: Numeric Values Stored as Strings — No Schema-Level Type Safety

| Field | Value |
|-------|-------|
| **Severity** | Critical |
| **Affected Table** | All tables (`CDW_BORR_MSTR`, `CDW_LN_ACCT`, `CDW_LN_PROD`, `CDW_PMT_HIST`) |
| **Affected Columns** | `BORR_CRDT_SCR`, `BORR_ANN_INCM`, `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, `LN_PMT_AMT`, `PMT_AMT`, all amount/rate/score columns |

**Example Data:**

| Column | Stored Value | Target Type | Parsing Risk |
|--------|-------------|-------------|--------------|
| `BORR_CRDT_SCR` | `"745"` | Integer | Non-numeric strings cause `NumberFormatException` |
| `BORR_ANN_INCM` | `"92,500"` | BigDecimal | Commas must be stripped; currency symbols would fail |
| `LN_CURR_BAL` | `"271,432.56"` | BigDecimal | Commas must be stripped |
| `LN_INT_RT` | `"4.750"` | BigDecimal | Leading/trailing whitespace would fail |
| `LN_LTV_PCT` | `"82.5"` | BigDecimal | Percentage stored without `%` sign — inconsistent convention possible |

All numeric fields in the legacy schema are `VARCHAR`. The service layer's `parseLegacyAmount`, `parseLegacyDecimal`, and `parseLegacyInteger` methods perform conversion but throw unchecked exceptions (`NumberFormatException`) on malformed data with no error handling.

**Business Impact:** A single malformed record (e.g., credit score of `"N/A"`, amount of `"$285,000"`, or an empty string) causes an unhandled `NumberFormatException` that crashes the entire API request — not just the single bad record.

**Recommended Fix:** Wrap all parse methods in try-catch blocks. Return sensible defaults or null and log warnings. Ensure one bad record cannot take down an entire list endpoint.

---

## ANM-004: Date Strings Passed Through Without Validation or Parsing

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST`, `CDW_BORR_MSTR` |
| **Affected Columns** | `LN_ORIG_DT`, `LN_MAT_DT`, `PMT_DT`, `PMT_RECV_DT`, `BORR_DOB_DT`, all `*_DT` columns |

**Example Data:**

| Column | Stored Value | Expected Format |
|--------|-------------|-----------------|
| `BORR_DOB_DT` | `"03/15/1978"` | MM/DD/YYYY |
| `LN_ORIG_DT` | `"02/15/2019"` | MM/DD/YYYY |
| `PMT_DT` | `"12/15/2025"` | MM/DD/YYYY |

The column mapping document specifies `MM/DD/YYYY → DATE` conversion, but the service layer passes date strings directly to DTOs (`dto.setOriginationDate(acct.getOriginationDate())`) without parsing or validation. Invalid dates like `"13/32/2025"` or `"00/00/0000"` would flow through to the API response undetected.

**Business Impact:** API consumers receive unparsed date strings in an undocumented format. Downstream systems attempting to parse these dates may fail. Date calculations (e.g., loan age, payment schedule) cannot be performed reliably.

**Recommended Fix:** Parse all date strings to `LocalDate` using `DateTimeFormatter.ofPattern("MM/dd/yyyy")` with error handling. Return ISO-8601 format (`yyyy-MM-dd`) in API responses.

---

## ANM-005: No Foreign Key Constraints — Orphaned Record Risk

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `BORR_ID`, `LN_ACCT_NBR`, `PROD_CD` |

**Relationships Without FK Constraints:**

| Child Table | Child Column | Parent Table | Parent Column |
|-------------|-------------|--------------|---------------|
| `CDW_LN_ACCT` | `BORR_ID` | `CDW_BORR_MSTR` | `BORR_ID` |
| `CDW_LN_ACCT` | `PROD_CD` | `CDW_LN_PROD` | `PROD_CD` |
| `CDW_PMT_HIST` | `LN_ACCT_NBR` | `CDW_LN_ACCT` | `LN_ACCT_NBR` |

The schema comment explicitly states "No foreign key constraints." While the current seed data has valid references, the schema permits:
- Loan accounts referencing non-existent borrowers
- Payments referencing non-existent loan accounts
- Loans referencing non-existent product codes

The service code does handle a missing product gracefully (`product != null ? product.getDescription() : acct.getProductCode()` in `toLoanSummary`), but a missing borrower in `getBorrowerById` triggers a `RuntimeException`.

**Business Impact:** Orphaned records cause `NullPointerException` in the service layer when looking up related data. API responses would be incomplete or crash entirely for orphaned records.

**Recommended Fix:** Add existence checks before FK lookups. When a referenced entity is missing, log a warning and return a degraded response rather than crashing. Validate referential integrity at ingestion time.

---

## ANM-006: Null Values in Business-Critical Fields

| Field | Value |
|-------|-------|
| **Severity** | High |
| **Affected Table** | `CDW_BORR_MSTR` |
| **Affected Columns** | `BORR_MID_INIT`, `BORR_ADDR_LN2` (and potentially any VARCHAR column) |

**Example Bad Records:**

| BORR_ID | BORR_MID_INIT | BORR_ADDR_LN2 |
|---------|---------------|----------------|
| B-10002 | `L` | `NULL` |
| B-10003 | `A` | `NULL` |
| B-10005 | `NULL` | `NULL` |

The schema defines no `NOT NULL` constraints on any column except primary keys. While `BORR_MID_INIT` and `BORR_ADDR_LN2` being null is arguably acceptable, the schema also allows null for `BORR_FST_NM`, `BORR_LST_NM`, `LN_CURR_BAL`, `LN_STAT_CD`, and other fields that should never be null.

The service's `toBorrowerDto` handles null middle initial with a ternary check, but `toLoanSummary` concatenates `borrowerFirstName + " " + borrowerLastName` without null checks — a null first or last name would produce `"null Mitchell"` in the API.

**Business Impact:** Null names produce corrupted display strings. Null status codes cause the `expandStatusCode` switch to return "Unknown". Null amounts cause `parseLegacyAmount` to return `BigDecimal.ZERO`, which silently misrepresents the data.

**Recommended Fix:** Add null checks for all business-critical fields at ingestion time. For required fields (name, balance, status), reject or flag the record. For optional fields, use explicit defaults.

---

## ANM-007: Denormalized Borrower Data Drift

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT` |
| **Affected Columns** | `BORR_FST_NM`, `BORR_LST_NM`, `BORR_SSN_LST4` |

**Current Data (consistent):**

| Source | BORR_ID | First Name | Last Name |
|--------|---------|------------|-----------|
| `CDW_BORR_MSTR` | B-10001 | James | Mitchell |
| `CDW_LN_ACCT` (LN-2019-00142) | B-10001 | James | Mitchell |

The loan account table embeds borrower first name, last name, and SSN last 4 — duplicating data from `CDW_BORR_MSTR`. While currently consistent, there is no mechanism to keep these in sync. The service uses the denormalized copies from `CDW_LN_ACCT` for `toLoanSummary` (line 106), meaning a stale loan record will show outdated borrower info.

**Business Impact:** If a borrower's name changes (e.g., marriage), loan summaries will show the old name while borrower details show the new name. This is a data consistency issue that erodes trust in the API.

**Recommended Fix:** Validate that denormalized fields match the master record at ingestion time. Log warnings on mismatches. In the service layer, prefer the master record (`CDW_BORR_MSTR`) over denormalized copies.

---

## ANM-008: Late Payment Without Proper Status Tracking

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_LATE_FEE`, `PMT_RECV_DT`, `PMT_DT`, `PMT_STAT_CD` |

**Example Bad Records:**

| PMT_SEQ_NBR | PMT_DT | PMT_RECV_DT | Days Late | LATE_FEE | PMT_STAT_CD |
|-------------|--------|-------------|-----------|----------|-------------|
| PMT-2025110003 | 11/01/2025 | 11/18/2025 | 17 | 47.50 | PST |
| PMT-2025120003 | 12/01/2025 | 12/05/2025 | 4 | 0.00 | PST |

Payment PMT-2025110003 was received 17 days after the due date and incurred a $47.50 late fee, but has the same `PST` (Posted) status as on-time payments. There is no status code to distinguish late-but-posted payments from on-time payments.

**Business Impact:** Late payment patterns cannot be identified from status codes alone. Reporting on payment timeliness requires manual date comparison rather than status-based filtering.

**Recommended Fix:** Track late payment status in the validation layer. Add a computed `daysLate` field to the payment DTO and flag payments received after the due date.

---

## ANM-009: Escrow Balance Inconsistency Between Loan and Payment Records

| Field | Value |
|-------|-------|
| **Severity** | Medium |
| **Affected Table** | `CDW_LN_ACCT`, `CDW_PMT_HIST` |
| **Affected Columns** | `LN_ESCROW_BAL`, `PMT_ESCROW_AMT` |

**Example:**

| LN_ACCT_NBR | LN_ESCROW_BAL | Recent PMT_ESCROW_AMT values |
|-------------|---------------|------------------------------|
| LN-2018-00089 | 2,100.00 | 0.00, 0.00 |
| LN-2021-00567 | 6,750.00 | 0.00, 0.00 |
| LN-2019-00142 | 3,245.80 | 355.55, 355.55 |

Loans LN-2018-00089 and LN-2021-00567 have non-zero escrow balances ($2,100 and $6,750 respectively) but all their payment records show $0.00 escrow contributions. This suggests the escrow balance was either pre-funded or the payment breakdown is incorrect.

**Business Impact:** Escrow analysis and tax/insurance payment projections will be inaccurate. Borrower statements showing zero escrow collection alongside a non-zero escrow balance are confusing.

**Recommended Fix:** Flag loans where escrow balance is positive but recent payment escrow amounts are zero. Include this as a warning in API responses.

---

## ANM-010: String Ordering on Date Fields Produces Incorrect Sort Order

| Field | Value |
|-------|-------|
| **Severity** | Low |
| **Affected Table** | `CDW_PMT_HIST` |
| **Affected Columns** | `PMT_DT` |

The repository method `findByLoanAccountNumberOrderByPaymentDateDesc` sorts by `PMT_DT` — a VARCHAR column. String-based sorting on `MM/DD/YYYY` format produces incorrect chronological order because the month is the leading component. For example, `"12/01/2025"` sorts after `"11/01/2025"` (correct within the same year), but `"02/01/2026"` would sort before `"11/01/2025"` (incorrect).

**Business Impact:** Payment history displayed to users may not be in chronological order, especially across year boundaries.

**Recommended Fix:** Parse dates to `LocalDate` in the service layer and sort there, or use a computed date column for proper ordering.

---

## Summary

| ID | Title | Severity | Table |
|----|-------|----------|-------|
| ANM-001 | Payment Component Amounts Exceed Total | Critical | CDW_PMT_HIST |
| ANM-002 | Delinquent Loan Marked as Active | Critical | CDW_LN_ACCT |
| ANM-003 | Numeric Values Stored as Strings | Critical | All |
| ANM-004 | Dates Passed Through Without Validation | High | All |
| ANM-005 | No FK Constraints — Orphaned Record Risk | High | CDW_LN_ACCT, CDW_PMT_HIST |
| ANM-006 | Null Values in Business-Critical Fields | High | CDW_BORR_MSTR |
| ANM-007 | Denormalized Borrower Data Drift | Medium | CDW_LN_ACCT |
| ANM-008 | Late Payment Without Status Tracking | Medium | CDW_PMT_HIST |
| ANM-009 | Escrow Balance Inconsistency | Medium | CDW_LN_ACCT, CDW_PMT_HIST |
| ANM-010 | String Sort on Date Fields | Low | CDW_PMT_HIST |
