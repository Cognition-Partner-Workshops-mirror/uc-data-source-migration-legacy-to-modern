# Root Cause Analysis — Top 3 Critical Anomalies

> **Generated:** 2026-05-07
> **References:** `DATA_ANOMALY_REPORT.md`, `LoanService.java`, repository layer, `data/mappings/column_mappings.md`

---

## RCA-001: Numeric Financial Amounts Stored as VARCHAR with Embedded Commas (ANO-001)

### Anomaly Summary

All financial amounts across four legacy tables are stored as `VARCHAR` with embedded commas (e.g., `"285,000"`, `"1,487.02"`, `"1,500,000"`). The service layer must parse every amount on every request.

### Code Path Trace

#### 1. Entity Layer — No Type Safety

```
LegacyLoanAccount.java:36    private String originalAmount;    // VARCHAR → String
LegacyLoanAccount.java:39    private String currentBalance;
LegacyLoanAccount.java:48    private String monthlyPayment;
LegacyBorrower.java:63       private String annualIncome;
LegacyPayment.java:26        private String totalAmount;
```

All JPA entities map financial columns as `String`. There is no `@Convert` annotation or `AttributeConverter` to handle type conversion at the persistence layer. This means raw VARCHAR strings propagate all the way to the service layer.

#### 2. Service Layer — Fragile Parsing

```java
// LoanService.java:152-155
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // ← ONLY strips commas
}
```

**Failure modes:**
- `"$285,000"` → `NumberFormatException` (dollar sign not stripped)
- `"285 000"` → `NumberFormatException` (space as thousands separator)
- `"N/A"` → `NumberFormatException` (sentinel value)
- `""` (empty) → Returns `BigDecimal.ZERO` (silent data loss — zero balance looks like a paid-off loan)
- `"-1,000"` → `-1000` (negative amounts accepted without validation)

#### 3. API Response — Unhandled Exception Propagates

```java
// LoanService.java:108-111
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
```

When `parseLegacyAmount()` throws, the exception propagates through:
1. `toLoanSummary()` (line 103)
2. `getAllLoans()` (line 53, inside `.map()`)
3. `LoanController.getAllLoans()` (line 24)
4. Spring MVC error handler → **HTTP 500 Internal Server Error**

A **single bad record** in any of the ~13 financial columns across ~4 tables causes the **entire list endpoint** to fail. There is no per-record error isolation.

#### 4. Column Mapping Expectations

From `data/mappings/column_mappings.md`:
```
| LN_ORIG_AMT  | VARCHAR(15) | original_amount | DECIMAL(12,2) | Remove commas, parse → decimal |
| LN_CURR_BAL  | VARCHAR(15) | current_balance | DECIMAL(12,2) | Remove commas, parse → decimal |
```

The mapping doc specifies "Remove commas, parse → decimal" but doesn't document handling of currency symbols, whitespace separators, or non-numeric sentinel values. The implementation follows the doc literally, leaving edge cases unhandled.

### Root Cause

The legacy CDW was designed as a reporting warehouse where human-readable formatting (commas in numbers) was prioritized over machine-processability. The Spring Boot service inherited this data as-is without a robust ETL/validation layer. The `parseLegacyAmount()` method is a minimal implementation that handles the happy path but has no error recovery for the known data quality issues in the CDW.

### Runtime Failure Scenario

1. CDW ETL job loads a loan with `LN_ORIG_AMT = "$525,000"` (operator added dollar sign).
2. `GET /api/loans` is called.
3. `parseLegacyAmount("$525,000")` → `new BigDecimal("$525000")` → **NumberFormatException**.
4. Stream processing in `getAllLoans()` fails → **500 error for ALL loans**, not just the bad one.
5. No error is logged with the offending record ID — stack trace shows only the parse failure.

### Fix Applied

See `LegacyDataValidator.java` — the new validation service:
- Strips `$`, whitespace, and other non-numeric characters before parsing.
- Catches `NumberFormatException` and returns `BigDecimal.ZERO` with a structured warning log including the record ID and column name.
- Validates that financial amounts are non-negative.
- Provides per-record error isolation so one bad record doesn't crash the entire endpoint.

---

## RCA-002: Dates Stored as VARCHAR with No Format Validation (ANO-002)

### Anomaly Summary

All date fields (16+ columns across 4 tables) are stored as `VARCHAR(10)` strings in `MM/DD/YYYY` format. No parsing or format validation occurs in the service layer — raw date strings are passed directly to API responses.

### Code Path Trace

#### 1. Entity Layer — Raw Strings

```
LegacyLoanAccount.java:51    private String originationDate;   // "02/15/2019"
LegacyLoanAccount.java:54    private String maturityDate;       // "02/15/2049"
LegacyPayment.java:23        private String paymentDate;        // "12/15/2025"
LegacyBorrower.java:33       private String dateOfBirth;        // "03/15/1978"
```

#### 2. Service Layer — No Date Parsing

```java
// LoanService.java:113
dto.setOriginationDate(acct.getOriginationDate());  // Raw string passthrough!

// LoanService.java:138
dto.setPaymentDate(pmt.getPaymentDate());            // Raw string passthrough!
```

The `LoanSummaryDto.originationDate` and `PaymentDto.paymentDate` fields are declared as `String`, and the service layer passes the raw legacy string through **without any parsing or reformatting**.

#### 3. DTO Layer — String Types

```java
// LoanSummaryDto.java:18
private String originationDate;    // Should be LocalDate or ISO string

// PaymentDto.java:12
private String paymentDate;        // Should be LocalDate or ISO string
```

#### 4. Column Mapping Expectations

From `data/mappings/column_mappings.md`:
```
| LN_ORIG_DT  | VARCHAR(10) | origination_date | DATE | Parse MM/DD/YYYY → DATE |
| PMT_DT      | VARCHAR(10) | payment_date     | DATE | Parse MM/DD/YYYY → DATE |
```

The mapping doc explicitly calls for `DATE` type in the modern schema, but the current code does not perform this conversion.

### Root Cause

The service layer was implemented as a "read and relay" layer that translates field names (cryptic → readable) but does not perform type conversion for dates. This was likely a deliberate shortcut during initial development — amounts were parsed to `BigDecimal` for calculations, but dates were not parsed because no date arithmetic was needed in the current API surface. However, this creates two problems:

1. **Format inconsistency:** The API contract implicitly assumes `MM/DD/YYYY` format, but there is no enforcement. When the CDW contains dates in other formats (`YYYY-MM-DD`, `DD-MMM-YY`), the API returns mixed formats.
2. **No validation:** Invalid dates like `13/32/2020` or `00/00/0000` (sentinel for unknown date) pass through to the API response without error.

### Runtime Failure Scenario

1. Downstream consumer receives loan list via `GET /api/loans`.
2. Consumer parses `originationDate` field using `MM/DD/YYYY` format.
3. CDW data contains a record with `LN_ORIG_DT = "2019-02-15"` (ISO format from a system migration).
4. Consumer's date parser fails → **data processing error on consumer side**.
5. Since the error is in the consumer, no error appears in the loan service logs — the issue is invisible from the service perspective.

### Fix Applied

See `LegacyDataValidator.java`:
- Parses date strings using `MM/dd/yyyy` format first, falling back to `yyyy-MM-dd` and `dd-MMM-yy`.
- Returns `null` with a warning log for unparseable dates.
- Validates date boundaries (not before 1900, not after 2100).
- API responses now return dates in ISO-8601 format (`yyyy-MM-dd`).

---

## RCA-003: No Foreign Key Constraints — Orphaned Record Risk (ANO-003)

### Anomaly Summary

The legacy schema has **zero foreign key constraints**. The three critical relationships (`CDW_LN_ACCT.BORR_ID → CDW_BORR_MSTR`, `CDW_LN_ACCT.PROD_CD → CDW_LN_PROD`, `CDW_PMT_HIST.LN_ACCT_NBR → CDW_LN_ACCT`) are enforced only by application convention.

### Code Path Trace

#### 1. Schema Layer — No Constraints

```sql
-- schema-legacy.sql:52-53
CREATE TABLE CDW_LN_ACCT (
    LN_ACCT_NBR     VARCHAR(20) PRIMARY KEY,
    BORR_ID         VARCHAR(20),          -- No FK to CDW_BORR_MSTR
    ...
    PROD_CD         VARCHAR(10),          -- No FK to CDW_LN_PROD
```

```sql
-- schema-legacy.sql:84-86
CREATE TABLE CDW_PMT_HIST (
    PMT_SEQ_NBR     VARCHAR(20) PRIMARY KEY,
    LN_ACCT_NBR     VARCHAR(20),          -- No FK to CDW_LN_ACCT
```

#### 2. Service Layer — Silent Null Handling for Products

```java
// LoanService.java:49-51 (getAllLoans)
Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
        .stream()
        .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));

// LoanService.java:54
.map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
```

When `acct.getProductCode()` returns a code not in the products map (orphaned reference), `products.get()` returns `null`. This `null` is passed to `toLoanSummary()`:

```java
// LoanService.java:107
dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
```

The fallback silently uses the raw product code (e.g., `"FXD30_OLD"`) as the description. **No warning is logged. No error is raised. The data quality issue is invisible.**

#### 3. Service Layer — Borrower Lookup Fails Hard for Missing Borrowers

```java
// LoanService.java:73-74 (getBorrowerById)
LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
        .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
```

If a loan references a `BORR_ID` that doesn't exist in `CDW_BORR_MSTR`, and a user navigates to that borrower's detail page:
1. `getBorrowerById("B-99999")` → `RuntimeException` → **HTTP 500**.
2. There's no indication from the loan list that the borrower link is broken.

But in `getAllLoans()`, the borrower data comes from the **denormalized fields in CDW_LN_ACCT** (line 106), so it doesn't fail — it just shows stale/orphaned borrower data.

#### 4. Service Layer — Payment-Loan Orphans Are Silent

```java
// LoanService.java:91-94 (getPaymentsByLoan)
return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
        .stream()
        .map(this::toPaymentDto)
        .collect(Collectors.toList());
```

If `CDW_PMT_HIST` contains payments referencing a non-existent `LN_ACCT_NBR`, this method simply returns an empty list for the valid loan (missing payments) and the orphaned payments are never surfaced. Payment reconciliation will show discrepancies.

### Root Cause

The legacy CDW was a **read-only reporting warehouse** that received data from multiple upstream OLTP systems via batch ETL jobs. Foreign keys were deliberately omitted to:
1. Allow out-of-order ETL loads (e.g., load payments before loans).
2. Avoid constraint violation errors during bulk inserts.
3. Accommodate data from retired systems where master records were purged but transaction history was retained.

The Spring Boot service was built atop this warehouse without adding a validation layer, inheriting all the referential integrity risks.

### Runtime Failure Scenario

1. Upstream ETL job purges borrower `B-10003` from `CDW_BORR_MSTR` (account closed per data retention policy).
2. Loan `LN-2018-00089` still references `BORR_ID = 'B-10003'`.
3. `GET /api/loans` succeeds — it uses denormalized name from `CDW_LN_ACCT` (stale data, but doesn't crash).
4. User clicks borrower link → `GET /api/borrowers/B-10003` → **500 error: "Borrower not found"**.
5. 10 payments for this loan still exist in `CDW_PMT_HIST` but can't be attributed to the correct customer.
6. Monthly payment reconciliation report shows $12,924.60 in "unattributed payments."

### Fix Applied

See `LegacyDataValidator.java`:
- Validates `BORR_ID` exists in borrower repository before processing loan accounts.
- Validates `PROD_CD` exists in product repository before processing loan accounts.
- Validates `LN_ACCT_NBR` exists in loan account repository before processing payments.
- Logs orphaned records with full context (which record references which missing parent).
- Returns structured validation results so callers can decide whether to skip or include orphaned records with warnings.
