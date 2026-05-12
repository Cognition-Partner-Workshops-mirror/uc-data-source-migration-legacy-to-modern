# Root Cause Analysis — Top 3 Critical Anomalies

**Generated:** 2026-05-12  
**Reference:** `docs/DATA_ANOMALY_REPORT.md` (ANO-001, ANO-002, ANO-003)

---

## RCA-001: Payment Component Sum Mismatch (ANO-001)

### Anomaly Summary

Three payment records have component amounts (principal + interest + escrow + late fee) that do not sum to the stated total. Discrepancies of +$400.00 and +$47.50 were found.

### Code Path Trace

**Entry point:** `LoanController.getPayments()` → `LoanService.getPaymentsByLoan()`

1. **Repository layer** (`LegacyPaymentRepository.java:14`):
   ```java
   List<LegacyPayment> findByLoanAccountNumberOrderByPaymentDateDesc(String loanAccountNumber);
   ```
   Spring Data JPA generates a query against `CDW_PMT_HIST` with no filtering or validation. All payment records are returned regardless of data integrity.

2. **Service layer** (`LoanService.java:90-95`):
   ```java
   public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
       return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
               .stream()
               .map(this::toPaymentDto)
               .collect(Collectors.toList());
   }
   ```
   Each payment is mapped 1:1 to a DTO with no cross-field validation.

3. **Translation method** (`LoanService.java:134-147`):
   ```java
   private PaymentDto toPaymentDto(LegacyPayment pmt) {
       dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
       dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
       dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
       dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
       dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
   }
   ```
   Each component is parsed independently. **There is no check that the components sum to the total.** The mismatched amounts pass through to the API response verbatim.

4. **Column mappings** (`data/mappings/column_mappings.md:82-86`):
   The mapping specifies individual `Remove commas, parse → decimal` transformations for each amount column. **No reconciliation rule is defined** between `PMT_AMT` and its components.

### Root Cause

The legacy data warehouse loaded payment components from different source systems or ETL jobs without a reconciliation step. The service layer's `toPaymentDto()` method trusts all values at face value. There is no integrity check anywhere in the pipeline — not in the schema (no CHECK constraints), not in the repository (no validation query), and not in the service (no sum verification).

### Runtime Impact

- `GET /api/loans/{loanId}/payments` for loan `LN-2019-00142` returns payments where `totalAmount = 1487.02` but `principalAmount + interestAmount + escrowAmount + lateFee = 1887.02`.
- API consumers performing their own calculations will get different results than the stated total.
- Financial dashboards aggregating component amounts will overcount by $400 per affected payment.

### Fix Location

`LoanService.toPaymentDto()` (line 134) — add a post-parsing validation step that compares the component sum against the total and logs a warning when they diverge, attaching a `reconciled` flag to the DTO.

---

## RCA-002: SSN Last-4 Matches Phone Number Last-4 (ANO-002)

### Anomaly Summary

All 5 borrowers in `CDW_LN_ACCT` have `BORR_SSN_LST4` values that exactly match the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR`.

### Code Path Trace

**Entry point:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()`

1. **Repository layer** (`LegacyLoanAccountRepository.java:10`):
   ```java
   public interface LegacyLoanAccountRepository extends JpaRepository<LegacyLoanAccount, String> {}
   ```
   The `findAll()` query loads all columns from `CDW_LN_ACCT`, including `BORR_SSN_LST4`.

2. **Entity mapping** (`LegacyLoanAccount.java:29-30`):
   ```java
   @Column(name = "BORR_SSN_LST4")
   private String borrowerSsnLast4;
   ```
   The field is loaded from the database but **never used** in any DTO mapping. It is a dead field in the current code path.

3. **Service layer** (`LoanService.java:103-117`):
   `toLoanSummary()` uses `acct.getBorrowerFirstName()` and `acct.getBorrowerLastName()` (denormalized fields) but **never references `borrowerSsnLast4`**. The corrupted SSN data is not exposed via the current API.

4. **Column mappings** (`data/mappings/column_mappings.md:51`):
   ```
   | BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
   ```
   The migration plan correctly marks this field as dropped. However, **no validation or data quality check is defined** to detect that the data is corrupt before migration.

### Root Cause

The legacy ETL process that populated `CDW_LN_ACCT` likely had a bug in the data extraction: the `BORR_SSN_LST4` column was populated from the borrower's phone number last 4 digits instead of the actual SSN. This is a classic ETL column-mapping error — adjacent columns in the source extract were shifted, or the wrong source column name was used in the mapping.

### Runtime Impact

- **Current code:** No direct runtime failure — the field is loaded but never used in API responses.
- **Migration risk:** If a future migration or code change uses `BORR_SSN_LST4` for borrower matching, identity verification, or deduplication, it will produce incorrect results.
- **Security concern:** The field gives a false sense of PII validation — anyone relying on it for KYC verification is comparing phone digits, not SSN digits.

### Fix Location

`LoanService.toLoanSummary()` — no current fix needed since the field is unused. However, the `LegacyDataValidator` should flag this cross-table inconsistency during ingestion. The column_mappings.md should note the data quality issue alongside the "dropped" status.

---

## RCA-003: Numeric String Parsing Without Error Handling (ANO-003)

### Anomaly Summary

All numeric values in the legacy schema are stored as VARCHAR strings. The service layer parsing methods (`parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`) throw uncaught `NumberFormatException` for any non-numeric input.

### Code Path Trace

**Entry point:** Any API endpoint → `LoanService.getAllLoans()`, `getBorrowerById()`, `getPaymentsByLoan()`

1. **Parsing methods** (`LoanService.java:152-165`):
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));  // throws NumberFormatException
   }

   private BigDecimal parseLegacyDecimal(String value) {
       if (value == null || value.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(value.trim());  // throws NumberFormatException
   }

   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());  // throws NumberFormatException
   }
   ```
   Each method has a null/blank guard, but **no try-catch** for malformed strings.

2. **Call sites** (`LoanService.java:108-111, 129, 139-143`):
   These parsing methods are called during `stream().map()` operations that process ALL records in a single request:
   ```java
   return loanAccountRepository.findAll().stream()
       .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
       .collect(Collectors.toList());
   ```
   A `NumberFormatException` in ANY record's parsing will abort the entire stream, causing a 500 error for the whole API request.

3. **No global exception handler:**
   The controllers have no `@ExceptionHandler` or `@ControllerAdvice`. Spring Boot's default error handling will return a generic 500 response with a stack trace (in dev mode) or a bare error JSON.

4. **Column mappings** (`data/mappings/column_mappings.md:20-22, 37, 53-57`):
   Multiple transformation rules say `Remove commas, parse → decimal` or `Parse string → integer`. None mention error handling for unparseable values.

### Root Cause

The legacy DW "everything is VARCHAR" pattern means the application layer is the only enforcement of data types. The service layer was written assuming the current seed data is representative — it handles null/blank but not malformed strings. This is a "happy path only" implementation that will fail on real-world legacy data, which commonly contains values like `'N/A'`, `'$100,000'`, `'TBD'`, `' '` (non-breaking space), or `'100.00.00'` (double decimal point).

### Runtime Impact

- **Current seed data:** No failure — all values are well-formed.
- **Real legacy data:** A single malformed value in ANY numeric field causes `NumberFormatException`, which propagates up as an unhandled 500 Internal Server Error.
- **Batch endpoint failure:** `GET /api/loans` returns ALL loans in one request. One bad record among thousands causes the entire endpoint to fail.
- **No error isolation:** There is no per-record error handling. The service cannot skip bad records and return the rest.

### Fix Location

`LoanService.java` parsing methods (lines 152-165) — wrap each `new BigDecimal()` / `Integer.parseInt()` call in try-catch. Return a safe default (`BigDecimal.ZERO` / `null` / `0`) and log the parsing failure with the field name and raw value. Consider adding a `DataValidationResult` that collects all parsing issues encountered during a request.
