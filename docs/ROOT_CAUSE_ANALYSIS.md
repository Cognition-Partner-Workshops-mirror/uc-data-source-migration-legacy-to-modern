# Root Cause Analysis — Top 3 Critical Anomalies

This document traces the three most critical data anomalies through the application code to identify where each would cause a runtime failure or incorrect API response.

---

## RCA-1: Payment Component Sum Mismatch (ANO-001)

### Anomaly Recap

For loan `LN-2019-00142`, both December and November payments have component sums (principal + interest + escrow + late fee) that exceed the stated total by exactly $400.00. For `LN-2018-00089`'s November payment, the component sum exceeds the total by $47.50 (the late fee amount).

### Code Trace

**1. Data enters via `LegacyPayment` entity** (`entity/LegacyPayment.java`):
All payment fields are stored as raw strings. No integrity check exists at the entity level.

**2. `LoanService.toPaymentDto()` parses each field independently** (`service/LoanService.java:134-147`):
```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // "1,487.02" -> 1487.02
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // "456.78"  -> 456.78
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // "1,074.69" -> 1074.69
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // "355.55"  -> 355.55
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // "0.00"    -> 0.00
```
Each field is parsed in isolation. No cross-field validation occurs.

**3. `PaymentDto` is returned directly to the API** (`controller/LoanController.java:33-36`):
```java
@GetMapping("/{loanId}/payments")
public List<PaymentDto> getPayments(@PathVariable String loanId) {
    return loanService.getPaymentsByLoan(loanId);
}
```
The DTO is serialized to JSON with inconsistent numbers. An API consumer would see:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```
The consumer has no way to know that 456.78 + 1074.69 + 355.55 = 1887.02, not 1487.02.

### Root Cause

The service layer acts as a pure pass-through for payment amounts with no reconciliation logic. The `toPaymentDto()` method at `LoanService.java:134-147` blindly trusts the legacy data without validating that component amounts sum to the total. The legacy warehouse likely has an ETL defect where escrow amounts were double-counted or the total was computed from a different source than the component fields.

### Runtime Impact

- **Incorrect API Response:** Every call to `GET /api/loans/{loanId}/payments` for `LN-2019-00142` returns payment data where components don't reconcile. API consumers performing balance calculations will produce wrong results.
- **No Failure Signal:** The error is silent — no exception, no log, no warning. The incorrect data is served with HTTP 200.
- **Migration Failure:** When migrating to the modern schema with proper DECIMAL types, the mathematical inconsistency will persist unless caught during migration validation.

### Affected Code Path

```
LoanController.getPayments()
  -> LoanService.getPaymentsByLoan()
    -> paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()
    -> toPaymentDto()    <-- no sum validation here
      -> parseLegacyAmount() x5 (each field independently)
  -> PaymentDto serialized as JSON with inconsistent values
```

---

## RCA-2: Numeric String Parsing Without Error Handling (ANO-002)

### Anomaly Recap

All numeric values (amounts, rates, scores) are stored as VARCHAR strings and parsed at runtime. The parsing methods throw uncaught `NumberFormatException` on any non-numeric input.

### Code Trace

**1. Parse methods in `LoanService.java:152-165`:**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // line 154
}

private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // line 159
}

private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // line 164
}
```

**2. These methods are called during DTO construction:**
- `toLoanSummary()` (line 103-118): calls `parseLegacyAmount()` 4 times and `parseLegacyDecimal()` once per loan account
- `toBorrowerDto()` (line 120-132): calls `parseLegacyInteger()` once per borrower
- `toPaymentDto()` (line 134-147): calls `parseLegacyAmount()` 5 times per payment

**3. Exception propagation path:**
- `parseLegacyAmount("$285,000")` -> strips commas -> `new BigDecimal("$285000")` -> `NumberFormatException`
- Exception is uncaught in `toLoanSummary()`, `toBorrowerDto()`, or `toPaymentDto()`
- Exception propagates through `getAllLoans()` / `getAllBorrowers()` / `getPaymentsByLoan()`
- Spring Boot's default error handler returns HTTP 500 with stack trace

**4. List endpoints are especially vulnerable** (`LoanService.java:48-56`):
```java
public List<LoanSummaryDto> getAllLoans() {
    return loanAccountRepository.findAll().stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
}
```
The `.stream().map()` chain means one bad record causes the entire stream to fail. If record 3 of 5 has a malformed amount, all 5 records are lost — the API returns a 500 error instead of the 4 valid records.

### Root Cause

The parsing methods at `LoanService.java:152-165` implement a null/blank check but no try-catch for `NumberFormatException`. This is the direct root cause. The broader root cause is that the legacy schema uses `VARCHAR` for all columns (as documented in `schema-legacy.sql` lines 4-9), and the Java code assumes all non-blank VARCHAR values are well-formed numbers.

The column mappings document (`data/mappings/column_mappings.md`) specifies transformations like "Remove commas, parse -> decimal" (lines 22, 37, 53, etc.) but does not address error handling for malformed values.

### Runtime Impact

- **Service Crash on Bad Data:** A single malformed numeric value in any legacy record causes `NumberFormatException` -> HTTP 500.
- **Total List Failure:** The stream-based list endpoints (`getAllLoans`, `getAllBorrowers`) fail entirely on one bad record.
- **No Graceful Degradation:** No fallback, no partial results, no error logging identifying the bad record.
- **Attack Surface:** Malicious or accidental data warehouse entries can denial-of-service the API.

### Affected Code Path

```
LoanController.getAllLoans() / BorrowerController.getAllBorrowers()
  -> LoanService.getAllLoans() / getAllBorrowers()
    -> stream().map(this::toLoanSummary / this::toBorrowerDto)
      -> parseLegacyAmount() / parseLegacyDecimal() / parseLegacyInteger()
        -> new BigDecimal(value) / Integer.parseInt(value)
          -> NumberFormatException (UNCAUGHT)
  -> HTTP 500 Internal Server Error
```

---

## RCA-3: No Foreign Key Constraints — Orphaned Record Risk (ANO-003)

### Anomaly Recap

The legacy schema has no foreign key constraints. Loan accounts can reference non-existent borrowers or products, and payments can reference non-existent loan accounts.

### Code Trace

**1. Schema definition** (`schema-legacy.sql`):
```sql
CREATE TABLE CDW_LN_ACCT (
    BORR_ID         VARCHAR(20),    -- no FK to CDW_BORR_MSTR
    PROD_CD         VARCHAR(10),    -- no FK to CDW_LN_PROD
    ...
);
CREATE TABLE CDW_PMT_HIST (
    LN_ACCT_NBR     VARCHAR(20),    -- no FK to CDW_LN_ACCT
    ...
);
```

**2. Product lookup in `getAllLoans()`** (`LoanService.java:48-56`):
```java
Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
        .stream()
        .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));

return loanAccountRepository.findAll().stream()
        .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))  // line 54
        .collect(Collectors.toList());
```
If `acct.getProductCode()` returns a code not in the products map, `products.get()` returns `null`.

**3. Null product handling in `toLoanSummary()`** (`LoanService.java:103-118`):
```java
dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
```
Line 107 has a null check and falls back to the raw product code. This is a **silent degradation** — the API returns the cryptic legacy code (e.g., `"JUMBO"`) instead of a human-readable description, with no indication that data is missing.

**4. Borrower lookup in `getBorrowerById()`** (`LoanService.java:72-88`):
```java
LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
        .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
```
Line 73-74 throws a `RuntimeException` for a missing borrower. But if a loan's `BORR_ID` references a non-existent borrower, this only surfaces when someone calls the borrower endpoint directly — the loan endpoints use denormalized data and never validate the FK.

**5. Payment-to-loan orphan** (`LoanService.java:90-95`):
```java
public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
    return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
            .stream()
            .map(this::toPaymentDto)
            .collect(Collectors.toList());
}
```
If a payment references a non-existent loan, it can still be retrieved via `findAll()` on the payment repository but never via this method (since no one would query for a non-existent loan number). The orphan payments are invisible but consume storage and could be returned by future aggregate queries.

### Root Cause

The legacy schema at `schema-legacy.sql` explicitly documents "No foreign key constraints" (line 8). The repository layer (`LegacyLoanAccountRepository`, `LegacyPaymentRepository`) uses Spring Data JPA which issues simple SELECT queries without join validation. The service layer has partial null handling (product fallback at line 107) but no systematic FK validation.

The column mappings document (`data/mappings/column_mappings.md`) specifies transformations like "Lookup borrowers.id by external_id" (line 48) and "Lookup loan_accounts.id by account_number" (line 80) for the modern schema, confirming that FK resolution is a known migration requirement — but no validation exists in the current code.

### Runtime Impact

- **Silent Data Degradation:** Missing products result in cryptic codes in API responses instead of descriptions.
- **Inconsistent Error Behavior:** Missing borrower = RuntimeException (500), but missing product = silent fallback. No consistent error strategy.
- **Migration Blocker:** Orphaned records will cause INSERT failures in the modern schema which has proper FK constraints. Every orphan must be identified and resolved before migration.
- **Phantom Data:** Orphaned payments are invisible to the API but exist in the database, potentially skewing aggregate queries or batch reports.

### Affected Code Path

```
LoanController.getAllLoans()
  -> LoanService.getAllLoans()
    -> products.get(acct.getProductCode())  <-- returns null for orphan
    -> toLoanSummary(acct, null)
      -> product != null ? description : rawCode  <-- silent degradation

BorrowerController.getBorrower()
  -> LoanService.getBorrowerById()
    -> borrowerRepository.findById()
      -> orElseThrow(RuntimeException)  <-- hard failure for orphan FK
```

---

## Summary

| RCA | Anomaly | Failure Mode | Code Location | Severity |
|-----|---------|-------------|---------------|----------|
| RCA-1 | Payment sum mismatch | Silent incorrect API data | `LoanService.toPaymentDto()` (line 134-147) | Critical — financial data integrity |
| RCA-2 | Numeric parse failure | Uncaught `NumberFormatException` -> HTTP 500 | `LoanService.parseLegacyAmount/Decimal/Integer()` (line 152-165) | Critical — service availability |
| RCA-3 | Orphaned FK records | Silent degradation or RuntimeException | `LoanService.toLoanSummary()` (line 107), `getBorrowerById()` (line 73) | Critical — data completeness |
