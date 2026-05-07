# Root Cause Analysis — Top 3 Critical Anomalies

This document traces the three most critical data anomalies through the codebase to identify where they cause runtime failures or incorrect API responses.

---

## RCA-1: Numeric Amounts as Comma-Formatted Strings (ANM-001)

### Anomaly

All monetary values in the legacy CDW tables are stored as `VARCHAR` with embedded commas (e.g., `'285,000'`, `'1,487.02'`, `'92,500'`). The column mappings in `data/mappings/column_mappings.md` document the required transformation: "Remove commas, parse -> decimal" (lines 22, 37-38, 53-54, 57, 64, 71, 82-86).

### Code Trace

**Entry point:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()` (line 48)

1. `LoanService.getAllLoans()` (line 48-56) calls `loanAccountRepository.findAll()`, which loads `LegacyLoanAccount` entities with all amounts as raw `String` fields.

2. `toLoanSummary()` (line 103-118) converts amounts via two different parsing methods:
   - `parseLegacyAmount(acct.getOriginalAmount())` — line 108
   - `parseLegacyAmount(acct.getCurrentBalance())` — line 109
   - `parseLegacyDecimal(acct.getInterestRate())` — line 110
   - `parseLegacyAmount(acct.getMonthlyPayment())` — line 111

3. **`parseLegacyAmount()`** (line 152-155):
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   This correctly strips commas before parsing. However, it returns `BigDecimal.ZERO` for null/blank amounts — silently converting missing data into zero balances, which is **semantically incorrect** (a missing balance is not a zero balance).

4. **`parseLegacyDecimal()`** (line 157-160):
   ```java
   private BigDecimal parseLegacyDecimal(String value) {
       if (value == null || value.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(value.trim());
   }
   ```
   This does **NOT** strip commas. It is used for interest rate (`LN_INT_RT`) which currently doesn't contain commas, but if it ever received a comma-formatted value, it would throw `NumberFormatException`.

5. **`parseLegacyInteger()`** (line 162-165) is used for credit score and has **no error handling** — `Integer.parseInt()` on a non-numeric string throws `NumberFormatException` which propagates as an unhandled 500 error.

### Failure Modes

| Scenario | Method | Result |
|----------|--------|--------|
| Amount with commas (e.g., `'285,000'`) | `parseLegacyAmount()` | Works correctly |
| Amount is null or blank | `parseLegacyAmount()` | Returns `BigDecimal.ZERO` — **silent data loss** |
| Interest rate with commas | `parseLegacyDecimal()` | **`NumberFormatException` — 500 error** |
| Credit score is `'N/A'` | `parseLegacyInteger()` | **`NumberFormatException` — 500 error** |
| Amount contains `$` or spaces | `parseLegacyAmount()` | **`NumberFormatException` — 500 error** |

### Root Cause

Two separate parsing methods with inconsistent normalization. `parseLegacyAmount()` strips commas but `parseLegacyDecimal()` does not. Neither method has try-catch error handling — any unexpected character causes an unhandled exception. The null-to-zero fallback silently corrupts data.

---

## RCA-2: Dates Stored as Strings with No Parsing or Validation (ANM-002)

### Anomaly

All date fields across all four legacy tables are `VARCHAR(10)` with an assumed `MM/DD/YYYY` format. The column mappings document specifies "Parse MM/DD/YYYY -> DATE" as the required transformation (lines 12, 23-24, 40-41, 58-61, 72-73, 81, 89-92).

### Code Trace

**Entry point:** `LoanController.getLoan()` → `LoanService.getLoanById()` (line 58)

1. `toLoanSummary()` (line 113):
   ```java
   dto.setOriginationDate(acct.getOriginationDate());
   ```
   The origination date is passed **directly as a raw string** from the legacy entity to the DTO. No parsing, no validation, no format normalization.

2. `toPaymentDto()` (line 138):
   ```java
   dto.setPaymentDate(pmt.getPaymentDate());
   ```
   Same pattern — raw string pass-through.

3. **`LoanSummaryDto.originationDate`** is declared as `String` (line 18 of `LoanSummaryDto.java`), and **`PaymentDto.paymentDate`** is also `String` (line 12 of `PaymentDto.java`). The DTOs themselves don't enforce any date format.

4. **Payment sorting** in `LegacyPaymentRepository`:
   ```java
   List<LegacyPayment> findByLoanAccountNumberOrderByPaymentDateDesc(String loanAccountNumber);
   ```
   This generates a JPA `ORDER BY PMT_DT DESC` on a VARCHAR column. String-based descending sort of `MM/DD/YYYY` dates is **not chronological**:
   - `'12/01/2025'` < `'02/01/2025'` (because `'1'` < `'2'` at position 0)
   - Correct chronological order: December is after February
   - Actual sort order: `'02/...'` appears first (desc), `'12/...'` appears last

### Failure Modes

| Scenario | Location | Result |
|----------|----------|--------|
| Date in `YYYY-MM-DD` format | `toLoanSummary()` | **Inconsistent API response format** |
| Date is `null` | `dto.setOriginationDate(null)` | **`null` in JSON response** |
| Date is garbage (`'NOT_A_DATE'`) | All DTO setters | **Garbage propagated to API** |
| Payment listing sorted by date | `findBy...OrderByPaymentDateDesc` | **Wrong chronological order** |

### Root Cause

The service layer performs **zero date parsing** — it treats dates as opaque strings and passes them through verbatim. The JPA repository relies on database-level string sorting which is lexicographic, not chronological, for `MM/DD/YYYY` format. The column mappings document specifies date parsing but it was never implemented in the service layer.

---

## RCA-3: No Foreign Key Constraints — Orphaned Records (ANM-003)

### Anomaly

The legacy schema (`schema-legacy.sql`) defines no foreign key constraints between tables. `CDW_LN_ACCT.BORR_ID` has no FK to `CDW_BORR_MSTR.BORR_ID`, `CDW_LN_ACCT.PROD_CD` has no FK to `CDW_LN_PROD.PROD_CD`, and `CDW_PMT_HIST.LN_ACCT_NBR` has no FK to `CDW_LN_ACCT.LN_ACCT_NBR`. The schema header comment on line 8 explicitly states: "No foreign key constraints."

### Code Trace

**Entry point:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()` (line 48)

1. `getAllLoans()` (line 48-56):
   ```java
   Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
       .stream()
       .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
   
   return loanAccountRepository.findAll().stream()
       .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
       .collect(Collectors.toList());
   ```
   `products.get(acct.getProductCode())` returns `null` if the product code doesn't exist in the map.

2. `toLoanSummary()` (line 107):
   ```java
   dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
   ```
   Orphaned product code: falls back to the raw code string. This is a **silent degradation** — the API consumer sees a cryptic code like `'FXD30'` instead of `'30-Year Fixed Rate Mortgage'`.

3. `getBorrowerById()` (line 72-88):
   ```java
   LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
       .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
   ```
   If a loan references a non-existent borrower ID, and someone navigates from the loan to the borrower detail, this throws an unhandled `RuntimeException` → **500 error**.

4. `getLoanById()` (line 58-64):
   ```java
   LegacyLoanAccount acct = loanAccountRepository.findById(loanAccountNumber)
       .orElseThrow(() -> new RuntimeException("Loan not found: " + loanAccountNumber));
   LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
       .orElse(null);
   ```
   Product lookup uses `.orElse(null)` — orphaned product code produces `null`, handled in `toLoanSummary()` but with degraded output.

5. **Payment → Loan linkage** in `getPaymentsByLoan()` (line 90-95):
   ```java
   return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
       .stream().map(this::toPaymentDto).collect(Collectors.toList());
   ```
   If the loan account number doesn't exist, this returns an empty list — **silent data loss** (the caller doesn't know if the loan has no payments or doesn't exist).

### Failure Modes

| Scenario | Location | Result |
|----------|----------|--------|
| Loan with orphaned `PROD_CD` | `getAllLoans()` / `toLoanSummary()` | **Degraded API response** (raw code instead of description) |
| Loan with orphaned `BORR_ID` | `getBorrowerById()` | **500 RuntimeException** |
| Payment with orphaned `LN_ACCT_NBR` | `getPaymentsByLoan()` | **Empty list — silent data loss** |
| Loan with null `PROD_CD` | `products.get(null)` | **`null` product, degraded response** |

### Root Cause

The legacy schema intentionally omits FK constraints (common in data warehouses for load performance). The service layer compensates with ad-hoc null checks (`product != null ? ...`) but does so inconsistently — some paths throw exceptions, others silently degrade, and none log warnings. There is no ingestion-time validation to catch orphaned references before they reach the API layer.
