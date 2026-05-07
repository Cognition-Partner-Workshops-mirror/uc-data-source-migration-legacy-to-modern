# Root Cause Analysis — Top 3 Critical Anomalies

This document traces the three most critical data quality anomalies through the application code
to identify where each would cause a runtime failure or incorrect API response.

---

## RCA-001: Payment Component Sum Mismatch (ANO-001)

### Anomaly Summary
Payment records `PMT-2025120001` and `PMT-2025110001` (loan `LN-2019-00142`) have component sums
(principal + interest + escrow + late fee) totaling $1,887.02, but `PMT_AMT` is recorded as
$1,487.02 — a $400.00 discrepancy. Payment `PMT-2025110003` excludes its $47.50 late fee from
the total.

### Code Trace

**1. Data Ingestion — `LegacyPayment.java` (entity)**
```
@Column(name = "PMT_AMT")
private String totalAmount;        // "1,487.02"

@Column(name = "PMT_PRIN_AMT")
private String principalAmount;    // "456.78"

@Column(name = "PMT_INT_AMT")
private String interestAmount;     // "1,074.69"

@Column(name = "PMT_ESCROW_AMT")
private String escrowAmount;       // "355.55"

@Column(name = "PMT_LATE_FEE")
private String lateFee;            // "0.00"
```
All fields are stored as independent strings with no cross-field validation. JPA loads them
as-is from the legacy table.

**2. Translation — `LoanService.java:134-147` (`toPaymentDto`)**
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1487.02
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1074.69
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
    ...
}
```
Each field is parsed independently. There is **no cross-validation** that
`totalAmount == principalAmount + interestAmount + escrowAmount + lateFee`.

**3. API Response — `LoanController.java:33-36` (`getPayments`)**
```java
@GetMapping("/{loanId}/payments")
public List<PaymentDto> getPayments(@PathVariable String loanId) {
    return loanService.getPaymentsByLoan(loanId);
}
```
The mismatched payment is returned directly to API consumers.

### Root Cause
The `toPaymentDto` method performs field-by-field conversion without any integrity check. The
legacy data warehouse likely has a bug in its ETL pipeline that incorrectly allocates the
principal portion for loan `LN-2019-00142` — the interest amount ($1,074.69) is correctly
calculated from the balance ($271,432.56 * 4.75% / 12 = $1,074.69), but the principal amount
($456.78) is overstated. The correct principal should be approximately $56.78
($1,487.02 - $1,074.69 - $355.55).

### Runtime Impact
- **Incorrect API response:** Consumers summing payment components will get $1,887.02 instead of
  the reported $1,487.02 total.
- **Balance drift:** If downstream systems use the principal amount to track remaining balance,
  the loan balance will decrease $400/month faster than it should, eventually going negative.
- **Financial reporting:** P&I splits used for tax reporting (Form 1098) will be wrong.

### Where Fix Should Be Applied
`LoanService.toPaymentDto()` — add a post-parse validation that checks component sum against
total. Log a warning and include a `dataQualityWarning` field in the DTO when mismatches are
detected.

---

## RCA-002: Numeric String Parsing Without Error Handling (ANO-002)

### Anomaly Summary
All monetary values, rates, and integer fields are stored as VARCHAR strings. The service layer
parsing methods (`parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`) use
`new BigDecimal(...)` and `Integer.parseInt(...)` without try-catch, meaning any malformed
string causes an unhandled `NumberFormatException`.

### Code Trace

**1. Parse Methods — `LoanService.java:152-165`**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // No try-catch!
}

private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // No try-catch!
}

private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // No try-catch!
}
```
Null and blank checks exist, but non-numeric non-blank strings (e.g., `"N/A"`, `"$100"`,
`"PENDING"`) will throw `NumberFormatException`.

**2. Callers — `LoanService.java:108-111` (`toLoanSummary`)**
```java
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
```
These are called inside `getAllLoans()` which streams over ALL loan accounts:
```java
return loanAccountRepository.findAll().stream()
    .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
    .collect(Collectors.toList());
```

**3. Error Propagation — `LoanController.java:23-26`**
```java
@GetMapping
public List<LoanSummaryDto> getAllLoans() {
    return loanService.getAllLoans();
}
```
No `@ExceptionHandler` exists in the controller. The `NumberFormatException` propagates as an
unhandled exception, returning HTTP 500 to the client.

**4. Similarly in `toBorrowerDto` — `LoanService.java:129`**
```java
dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
```
Called by `getAllBorrowers()`, so one bad credit score value takes down the entire borrower list.

### Root Cause
The parse methods only guard against null/blank values but not against non-numeric strings. The
legacy CDW schema uses `VARCHAR` for everything (documented in the schema comments as "loose
typing"). The code assumes all non-blank VARCHAR values will be valid numbers, which is a
fragile assumption for a legacy data warehouse known to have quality issues.

### Runtime Impact
- **Total API outage per endpoint:** One malformed record in `CDW_LN_ACCT` causes `GET /api/loans`
  to return 500 for ALL consumers. Same for `GET /api/borrowers`.
- **Cascading failures:** `getBorrowerById` also calls `toLoanSummary` for the borrower's loans,
  so a bad loan record breaks the borrower detail endpoint too.
- **No error isolation:** The stream-based processing means the exception breaks the entire
  collection operation, not just the bad record.

### Where Fix Should Be Applied
`LoanService.parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` — wrap
in try-catch, return safe defaults, and log the malformed value with the entity context. Consider
adding a `DataQualityWarning` list to DTOs to surface issues without crashing.

---

## RCA-003: No Foreign Key Constraints — Orphan Records (ANO-003)

### Anomaly Summary
The legacy schema has no foreign key constraints. `CDW_LN_ACCT.BORR_ID`,
`CDW_LN_ACCT.PROD_CD`, and `CDW_PMT_HIST.LN_ACCT_NBR` are unconstrained VARCHAR references.
Orphaned records (referencing non-existent parents) can exist without detection.

### Code Trace

**1. Schema — `schema-legacy.sql:50-81`**
```sql
CREATE TABLE CDW_LN_ACCT (
    LN_ACCT_NBR     VARCHAR(20) PRIMARY KEY,
    BORR_ID         VARCHAR(20),    -- No FK to CDW_BORR_MSTR
    PROD_CD         VARCHAR(10),    -- No FK to CDW_LN_PROD
    ...
);
```
The schema header explicitly notes: "No foreign key constraints".

**2. Product Lookup — `LoanService.java:49-55` (`getAllLoans`)**
```java
Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
    .stream()
    .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));

return loanAccountRepository.findAll().stream()
    .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
    .collect(Collectors.toList());
```
`products.get(acct.getProductCode())` returns `null` if the product code doesn't match any
existing product. This null is passed to `toLoanSummary`.

**3. Null Product Handling — `LoanService.java:107`**
```java
dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
```
This handles a null product gracefully by falling back to the raw product code. However, the
API response now contains a cryptic code like `"FXD30"` instead of a human-readable description,
and the consumer has no indication that the data is degraded.

**4. Borrower Orphan — `LoanService.java:72-88` (`getBorrowerById`)**
```java
LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
    .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
...
List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
    .stream()
    .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
    .collect(Collectors.toList());
```
If a loan references a `BORR_ID` that doesn't exist in `CDW_BORR_MSTR`, the loan appears in the
listing (using denormalized names from `CDW_LN_ACCT`) but the borrower detail page would throw
`RuntimeException`.

**5. Column Mappings — `data/mappings/column_mappings.md:48`**
```
| BORR_ID | VARCHAR(20) | borrower_id | BIGINT | Lookup borrowers.id by external_id |
```
The modern schema requires resolving `BORR_ID` to a `BIGINT` FK via lookup. If the borrower
doesn't exist, this lookup fails and the loan cannot be migrated.

### Root Cause
The legacy CDW was designed as a reporting warehouse, not a transactional system. Foreign keys
were intentionally omitted to allow fast bulk loads. Over time, records were deleted from parent
tables without cascading to children, creating orphans. The application code has partial null
handling (for products) but no systematic validation of referential integrity.

### Runtime Impact
- **Migration failure:** Orphaned `BORR_ID` values in `CDW_LN_ACCT` will cause the modern schema
  migration to fail on the FK constraint `loan_accounts.borrower_id REFERENCES borrowers(id)`.
- **Inconsistent API behavior:** A loan with an orphaned `BORR_ID` appears in `GET /api/loans`
  (using denormalized names) but the borrower is missing from `GET /api/borrowers`. Clicking
  through to the borrower returns a 500 error.
- **Silent data loss:** Orphaned payments in `CDW_PMT_HIST` referencing deleted loans would be
  loaded but never associated with any active loan account.

### Where Fix Should Be Applied
Add referential integrity validation in the service layer. When loading loans, verify that each
`BORR_ID` exists in the borrower repository and each `PROD_CD` exists in the product repository.
When loading payments, verify each `LN_ACCT_NBR` exists. Log and flag orphaned records instead
of silently accepting them.
