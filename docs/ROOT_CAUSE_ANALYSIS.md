# Root Cause Analysis — Top 3 Critical Anomalies

> This document traces the three most critical data quality anomalies through the codebase to identify exactly where each would cause a runtime failure or incorrect API response.

---

## RCA-001: Payment Component Amounts Do Not Sum to Total (ANM-001)

### Anomaly

Payment records in `CDW_PMT_HIST` where `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE != PMT_AMT`.

Example: `PMT-2025120001` has total `1,487.02` but components sum to `1,887.02` (a $400.00 discrepancy).

### Code Trace

**1. Data enters via H2 seed script:**
- `data-legacy.sql` line 27: `INSERT INTO CDW_PMT_HIST VALUES ('PMT-2025120001', 'LN-2019-00142', '12/15/2025', '1,487.02', '456.78', '1,074.69', '355.55', '0.00', ...)`
- No integrity check at the database level — the schema (`schema-legacy.sql` line 84-99) has no CHECK constraints.

**2. Entity mapping (`LegacyPayment.java`):**
- All fields are mapped as `String` (lines 25-38):
  ```
  @Column(name = "PMT_AMT")     private String totalAmount;
  @Column(name = "PMT_PRIN_AMT") private String principalAmount;
  @Column(name = "PMT_INT_AMT")  private String interestAmount;
  @Column(name = "PMT_ESCROW_AMT") private String escrowAmount;
  @Column(name = "PMT_LATE_FEE")  private String lateFee;
  ```
- No validation at the entity level.

**3. Service translation (`LoanService.java` lines 134-147):**
  ```java
  private PaymentDto toPaymentDto(LegacyPayment pmt) {
      dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
      dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
      dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
      dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
      dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
  }
  ```
- Each field is parsed independently. No cross-field validation occurs.

**4. API response (`LoanController.java` line 33-36):**
  ```java
  @GetMapping("/{loanId}/payments")
  public List<PaymentDto> getPayments(@PathVariable String loanId) {
      return loanService.getPaymentsByLoan(loanId);
  }
  ```
- The DTO is serialized directly to JSON with inconsistent component breakdown.

**5. Column mappings (`column_mappings.md` lines 82-86):**
- Each amount field is mapped independently with "Remove commas, parse -> decimal" transformation.
- No mapping rule addresses component-to-total reconciliation.

### Root Cause

The legacy CDW system stores payment components and totals as independent fields with no database-level constraint or application-level validation. The service layer (`LoanService.toPaymentDto()`) performs field-by-field translation without any cross-field integrity check. The `column_mappings.md` defines only individual column transformations, not inter-column relationships.

### Runtime Impact

**Incorrect API Response:** `GET /api/loans/LN-2019-00142/payments` returns:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```
A consumer summing the components gets $1,887.02 while the total field says $1,487.02. No error, no warning — just silently wrong data.

---

## RCA-002: Numeric String Parsing with No Error Handling (ANM-002)

### Anomaly

All financial values, credit scores, term months, and percentages are stored as VARCHAR strings with embedded commas. The parsing code has no error handling for malformed values.

### Code Trace

**1. Schema definition (`schema-legacy.sql`):**
- Line 27: `BORR_CRDT_SCR VARCHAR(5)` — credit score as string
- Line 29: `BORR_ANN_INCM VARCHAR(15)` — annual income with commas
- Lines 60-72: All loan amounts, rates, and terms as VARCHAR

**2. Entity layer (`LegacyBorrower.java`, `LegacyLoanAccount.java`):**
- All fields typed as `String` — no type safety at the JPA level.

**3. Parsing methods (`LoanService.java` lines 152-165):**

  ```java
  private BigDecimal parseLegacyAmount(String amount) {
      if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
      return new BigDecimal(amount.replace(",", ""));  // LINE 154
  }

  private BigDecimal parseLegacyDecimal(String value) {
      if (value == null || value.isBlank()) return BigDecimal.ZERO;
      return new BigDecimal(value.trim());  // LINE 159
  }

  private Integer parseLegacyInteger(String value) {
      if (value == null || value.isBlank()) return null;
      return Integer.parseInt(value.trim());  // LINE 164
  }
  ```

  **Failure scenarios for `parseLegacyAmount` (line 154):**
  - Input `"$285,000"` → after replace: `"$285000"` → `NumberFormatException`
  - Input `"N/A"` → after replace: `"N/A"` → `NumberFormatException`
  - Input `"285 000"` (space separator) → after replace: `"285 000"` → `NumberFormatException`

  **Failure scenarios for `parseLegacyInteger` (line 164):**
  - Input `"745.0"` (credit score with decimal) → `NumberFormatException`
  - Input `"N/A"` → `NumberFormatException`

**4. Call sites where parsing failures cascade:**

  - `toLoanSummary()` (line 108): `parseLegacyAmount(acct.getOriginalAmount())` — if this throws, the entire `getAllLoans()` call (line 48-56) fails because it streams all accounts
  - `toBorrowerDto()` (line 129): `parseLegacyInteger(borrower.getCreditScore())` — if this throws, `getAllBorrowers()` fails completely
  - `toPaymentDto()` (line 139-143): Five `parseLegacyAmount` calls — any one failure kills the entire payment list

**5. Column mappings (`column_mappings.md`):**
  - Line 20: `BORR_CRDT_SCR` → `credit_score INTEGER` — "Parse string -> integer"
  - Line 22: `BORR_ANN_INCM` → `annual_income DECIMAL(12,2)` — "Remove commas, parse -> decimal"
  - Mappings specify the transformation but not error handling for invalid inputs.

### Root Cause

The legacy CDW uses VARCHAR for everything as a deliberate design choice (loose typing). The service layer parsing methods (`parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`) handle only the happy path (null/blank check, comma removal) but delegate to `BigDecimal(String)` and `Integer.parseInt()` without try-catch. These constructors throw unchecked `NumberFormatException` on any non-numeric input.

Because the service uses Java Streams (`stream().map()`) for bulk operations, a single bad record's `NumberFormatException` propagates up and aborts the entire collection, returning an HTTP 500 to the caller.

### Runtime Impact

**Complete API Failure:** If any single record in `CDW_BORR_MSTR` has a non-numeric `BORR_CRDT_SCR`, then `GET /api/borrowers` returns HTTP 500 with a stack trace. The same applies to `GET /api/loans` and `GET /api/loans/{id}/payments`.

---

## RCA-003: No Foreign Key Constraints — Orphaned Records (ANM-003)

### Anomaly

The legacy schema has no foreign key constraints. Loan accounts can reference non-existent borrowers or products, and payments can reference non-existent loans.

### Code Trace

**1. Schema (`schema-legacy.sql`):**
  - Line 53: `BORR_ID VARCHAR(20)` — no FK to CDW_BORR_MSTR
  - Line 59: `PROD_CD VARCHAR(10)` — no FK to CDW_LN_PROD
  - Line 86: `LN_ACCT_NBR VARCHAR(20)` — no FK to CDW_LN_ACCT
  - Line 8 comment: "No foreign key constraints" (intentional legacy DW pattern)

**2. Product lookup (`LoanService.java` lines 49-55):**
  ```java
  Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
      .stream()
      .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));

  return loanAccountRepository.findAll().stream()
      .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
      .collect(Collectors.toList());
  ```
  If `acct.getProductCode()` is `"INVALID"`, then `products.get("INVALID")` returns `null`.

**3. Null product handling (`LoanService.java` line 107):**
  ```java
  dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
  ```
  This line safely handles null product — it falls back to the raw product code. **This specific case is handled.**

**4. Borrower lookup (`LoanService.java` lines 72-87):**
  ```java
  LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
      .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
  ```
  If a `BORR_ID` in `CDW_LN_ACCT` doesn't exist in `CDW_BORR_MSTR`, and a consumer calls `GET /api/borrowers/{id}` with that orphaned ID, the `findById` on the borrower table won't find it. However, if an orphaned loan has a `BORR_ID` that doesn't match any borrower, `findByBorrowerId()` (line 81) would return those loans but the borrower lookup on line 73 would have already succeeded (since the caller passed a valid borrower ID). The real risk is in the reverse direction.

**5. Payment-to-loan linkage (`LoanService.java` lines 90-95):**
  ```java
  public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
      return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
          .stream()
          .map(this::toPaymentDto)
          .collect(Collectors.toList());
  }
  ```
  If `CDW_PMT_HIST` contains payments for a loan account that doesn't exist in `CDW_LN_ACCT`, those payments are invisible — they can never be retrieved via the API because the only access path is through a loan ID.

**6. Column mappings (`column_mappings.md` lines 48, 52, 80):**
  - `BORR_ID` → `borrower_id BIGINT` — "Lookup borrowers.id by external_id"
  - `PROD_CD` → `product_id BIGINT` — "Lookup loan_products.id by code"
  - `LN_ACCT_NBR` → `loan_account_id BIGINT` — "Lookup loan_accounts.id by account_number"
  
  The modern schema migration plan requires FK lookups, but the legacy layer has no validation of these relationships.

### Root Cause

The legacy CDW was designed as a denormalized data warehouse optimized for bulk reads, not transactional integrity. The absence of FK constraints is a deliberate design choice documented in the schema header (line 8). The Spring Data JPA repository layer queries tables independently with no join validation. The service layer performs map lookups (`products.get()`) that return null for missing references, and the code inconsistently handles nulls — product lookups have fallback logic (line 107) but borrower lookups throw RuntimeException (line 74).

### Runtime Impact

1. **Orphaned loan with invalid product code:** `GET /api/loans` returns loan with raw product code instead of description — degraded but functional.
2. **Orphaned payment with invalid loan account:** Payment is permanently invisible — data loss from API perspective.
3. **Orphaned loan with invalid borrower ID:** `GET /api/borrowers/{orphanedBorrowerId}` returns HTTP 500 `RuntimeException("Borrower not found")`. If the borrower was deleted but loans remain, `GET /api/loans` still works (uses denormalized name), but the loan-to-borrower relationship is broken.
