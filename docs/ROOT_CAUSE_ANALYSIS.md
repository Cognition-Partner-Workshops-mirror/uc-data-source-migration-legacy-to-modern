# Root Cause Analysis: Top 3 Critical Data Anomalies

> **Service:** `loan-service` (uc-data-source-migration-legacy-to-modern)

---

## RCA-001: Payment Component Sum Mismatch (ANO-001)

### Anomaly Summary

Payment records `PMT-2025120001`, `PMT-2025110001`, and `PMT-2025110003` have component amounts (principal + interest + escrow + late fee) that do not sum to the total payment amount.

### Code Path Trace

**1. Data Ingestion:** `data-legacy.sql` inserts raw payment records into `CDW_PMT_HIST`. No CHECK constraints exist on the table to validate component sums.

**2. Repository Layer:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` retrieves payment records with no validation. The JPA entity `LegacyPayment` maps all fields as raw strings.

**3. Service Layer (`LoanService.java`, lines 134-147):**
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    PaymentDto dto = new PaymentDto();
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
    // ... no validation that components sum to total
}
```

Each component is independently parsed from its VARCHAR source via `parseLegacyAmount()`. The method converts strings to `BigDecimal` but never cross-validates that the parts equal the whole.

**4. API Response:** `LoanController.getPayments()` returns the `PaymentDto` list directly. Consumers receive inconsistent financial data with no indication of the mismatch.

### Root Cause

The legacy CDW ETL process that populates `CDW_PMT_HIST` appears to source the total payment amount from one system (the billing/payment processor) and the component breakdown from another (the loan accounting engine). When these systems disagree -- particularly around escrow and late fee allocation -- the total and components diverge. The VARCHAR-only schema and absence of CHECK constraints mean the database accepts the mismatch silently.

Specifically for the affected records:
- **PMT-2025120001 / PMT-2025110001** (loan `LN-2019-00142`): The escrow amount (355.55) appears to be double-counted or sourced from a different calculation than the total. The delta is exactly 400.00 in both months, suggesting a systematic allocation error.
- **PMT-2025110003** (loan `LN-2018-00089`): The delta (47.50) equals the late fee exactly, indicating the late fee was added to the component breakdown but not reflected in the total.

### Runtime Failure Mode

This anomaly does **not** cause a runtime exception, which makes it more dangerous -- it silently produces incorrect financial data in API responses. Any consumer that relies on component amounts for accounting, tax reporting, or escrow analysis will have incorrect figures. The `PaymentDto` is returned with inconsistent numbers and no warning.

### Recommended Code Fix

Add a `validatePaymentComponents()` check in the service layer that compares the sum of components against the total. When a mismatch exceeds a tolerance threshold (e.g., $0.01), log a warning and attach a `componentMismatch` flag to the response so consumers are aware.

---

## RCA-002: SSN Last-4 Populated from Phone Numbers (ANO-002)

### Anomaly Summary

The `BORR_SSN_LST4` column in `CDW_LN_ACCT` contains the last 4 digits of borrower phone numbers instead of SSN last-4 digits, across 100% of records.

### Code Path Trace

**1. Data Ingestion:** `data-legacy.sql` inserts loan account records with `BORR_SSN_LST4` values that systematically match phone number suffixes:
```sql
-- Borrower B-10001: phone 217-555-0142, SSN_LST4 = '0142'
INSERT INTO CDW_LN_ACCT VALUES ('LN-2019-00142', 'B-10001', 'James', 'Mitchell', '0142', ...);
```

**2. Entity Layer:** `LegacyLoanAccount.java` maps the column as a plain string field (`borrowerSsnLast4`, line 30). No validation or cross-referencing is performed at the entity level.

**3. Service Layer (`LoanService.java`):** The `toLoanSummary()` method (lines 103-118) does **not** use `borrowerSsnLast4` in the DTO construction. The field is loaded from the database but never exposed in the current API. However, it is available on the entity and could be consumed by future code or direct entity access.

**4. Column Mappings (`column_mappings.md`, line 51):** The migration plan documents this field as "Denormalized; use borrower FK" and marks it as dropped in the modern schema. This implicitly acknowledges the field is unreliable, but does not call out the specific phone-number contamination.

### Root Cause

The legacy CDW ETL process that populates `CDW_LN_ACCT` has a column mapping error in its source query. The extract query likely joins to a contact/phone table instead of the SSN table, or the column alias in the SELECT statement maps `PHONE_LST4` to the `BORR_SSN_LST4` target column. The systematic nature (100% of records) confirms this is an ETL mapping bug, not random data entry errors.

The error went undetected because:
1. The VARCHAR(4) type accepts any 4-character string -- both phone and SSN last-4 are 4 digits
2. No cross-validation exists between `CDW_LN_ACCT.BORR_SSN_LST4` and `CDW_BORR_MSTR.BORR_SSN_ENCR`
3. The application code never uses this field in API responses, so no consumer has reported the issue

### Runtime Failure Mode

Currently no runtime failure occurs because `toLoanSummary()` ignores this field. However, the risk is latent:
- Any future code that uses `LegacyLoanAccount.getBorrowerSsnLast4()` for identity verification will silently match against phone digits
- The modern schema migration (`column_mappings.md`) correctly drops this field, but any intermediate migration step that copies it would propagate the bad data
- If a downstream system or report queries `CDW_LN_ACCT.BORR_SSN_LST4` directly via SQL, it receives phone numbers labeled as SSN data -- a compliance violation

### Recommended Code Fix

Add a cross-reference validation at ingestion that compares `CDW_LN_ACCT.BORR_SSN_LST4` against the last 4 digits derived from `CDW_BORR_MSTR.BORR_SSN_ENCR`. Flag all mismatches and log a critical-severity warning. Mark the field as deprecated in the entity with a `@Deprecated` annotation and a Javadoc warning.

---

## RCA-003: No Foreign Key Constraints Enabling Orphaned Records (ANO-003)

### Anomaly Summary

The legacy schema defines zero foreign key constraints across all four tables. Any referential relationship (borrower-to-loan, loan-to-payment, loan-to-product) is enforced only by convention in the ETL layer.

### Code Path Trace

**1. Schema Definition (`schema-legacy.sql`):**
```sql
CREATE TABLE CDW_LN_ACCT (
    BORR_ID VARCHAR(20),    -- no FK to CDW_BORR_MSTR
    PROD_CD VARCHAR(10),    -- no FK to CDW_LN_PROD
    ...
);
CREATE TABLE CDW_PMT_HIST (
    LN_ACCT_NBR VARCHAR(20), -- no FK to CDW_LN_ACCT
    ...
);
```

**2. Service Layer (`LoanService.java`, lines 48-56):**
```java
public List<LoanSummaryDto> getAllLoans() {
    Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
            .stream()
            .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));

    return loanAccountRepository.findAll().stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
}
```

`products.get(acct.getProductCode())` returns `null` if a loan references a non-existent product code. This null is passed to `toLoanSummary()`.

**3. Translation Method (`LoanService.java`, line 107):**
```java
dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
```

The null product is handled with a fallback to the raw product code. This prevents a `NullPointerException` but produces a degraded API response (raw code like "FXD30" instead of "30-Year Fixed Rate Mortgage").

**4. Borrower FK Path (`LoanService.java`, lines 72-88):**
```java
public BorrowerDto getBorrowerById(String borrowerId) {
    LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
            .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
    // ...
    List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
            .stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
}
```

If a loan account has an orphaned `BORR_ID` (referencing a non-existent borrower), the `findByBorrowerId()` query simply returns no results -- the orphaned loan is invisible from the borrower perspective but still appears in `getAllLoans()`.

**5. Payment FK Path (`LoanService.java`, lines 90-95):**
```java
public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
    return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
            .stream()
            .map(this::toPaymentDto)
            .collect(Collectors.toList());
}
```

Payments referencing non-existent loan account numbers are orphaned. They are never retrieved because no caller queries for them. They silently accumulate in the database.

### Root Cause

Legacy CDW systems typically avoid foreign key constraints for ETL performance reasons -- bulk loads are faster without constraint checking. Referential integrity is expected to be enforced by the ETL process itself. When the ETL has bugs or when data is loaded out of order (e.g., payments loaded before their loan accounts), orphaned records are created with no database-level safety net.

### Runtime Failure Mode

1. **Orphaned loan (bad `BORR_ID`):** Loan appears in `GET /api/loans` but not in `GET /api/borrowers/{id}` response. Inconsistent API behavior.
2. **Orphaned loan (bad `PROD_CD`):** `products.get()` returns null -> product description falls back to raw code -> degraded but functional API response.
3. **Orphaned payment (bad `LN_ACCT_NBR`):** Payment is never retrievable via the API. Silent data loss from the consumer's perspective.

### Recommended Code Fix

Add FK validation in the service layer at ingestion time. Before processing a loan account, verify that `borrowerId` exists in the borrower repository and `productCode` exists in the product repository. Before processing a payment, verify the `loanAccountNumber` exists. Log orphaned records with severity CRITICAL and exclude them from API responses with a clear error message.
