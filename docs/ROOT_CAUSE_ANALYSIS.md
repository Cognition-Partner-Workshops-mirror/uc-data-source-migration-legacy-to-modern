# Root Cause Analysis — Top 3 Critical Data Anomalies

## Overview

This document traces the three most critical data anomalies through the application code to identify where they would cause runtime failures or incorrect API responses.

---

## RCA #1: Payment Component Amounts Do Not Reconcile to Total

### Anomaly Summary
Payment records in `CDW_PMT_HIST` have component amounts (principal + interest + escrow + late fee) that do not sum to the stated total (`PMT_AMT`). For loan `LN-2019-00142`, every payment has a $400.00 discrepancy.

### Code Trace

**1. Data enters via H2 initialization:**
```sql
-- data-legacy.sql line 27
INSERT INTO CDW_PMT_HIST VALUES ('PMT-2025120001', 'LN-2019-00142', '12/15/2025',
    '1,487.02', '456.78', '1,074.69', '355.55', '0.00', 'REG', 'PST', ...);
-- Sum: 456.78 + 1074.69 + 355.55 + 0.00 = 1,887.02 != 1,487.02
```

**2. Entity mapping (`LegacyPayment.java`):**
```java
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
All stored as raw strings — no validation at the JPA layer.

**3. Service layer (`LoanService.java` lines 134-147):**
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    PaymentDto dto = new PaymentDto();
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1487.02
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1074.69
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
    ...
}
```
Each field is independently parsed. **No reconciliation check is performed.**

**4. API response (`LoanController.java` line 34):**
```java
@GetMapping("/{loanId}/payments")
public List<PaymentDto> getPayments(@PathVariable String loanId) {
    return loanService.getPaymentsByLoan(loanId);
}
```
The inconsistent data is returned directly to the API consumer.

### Root Cause
The legacy ETL process that populated `CDW_PMT_HIST` likely computed the total amount from a different source (the scheduled monthly payment amount from the loan) rather than summing the actual component allocations. The service layer performs no cross-field validation, so the inconsistency propagates silently to API consumers.

### Impact at Runtime
- **No exception** — the code runs without error
- **Silent data corruption** — API consumers receive payment breakdowns that don't add up
- **Financial reporting errors** — any downstream system that sums components will get a different total than the stated total
- **Migration failure** — modern schema with computed/check constraints would reject these records

### Column Mapping Reference (`column_mappings.md` lines 82-86)
The mapping specifies all amount fields convert from `VARCHAR(15)` to `DECIMAL(10,2)` via "Remove commas, parse -> decimal". No reconciliation rule is documented, meaning this anomaly would be silently migrated to the modern schema.

---

## RCA #2: SSN Last-4 Populated from Phone Number

### Anomaly Summary
All `BORR_SSN_LST4` values in `CDW_LN_ACCT` exactly match the last 4 digits of the corresponding borrower's phone number, indicating a systematic ETL column-mapping error.

### Code Trace

**1. Data in CDW_LN_ACCT (`data-legacy.sql` lines 20-24):**
```sql
-- Loan account has SSN_LST4 = '0142'
INSERT INTO CDW_LN_ACCT VALUES ('LN-2019-00142', 'B-10001', 'James', 'Mitchell', '0142', ...);
```

**2. Borrower master has phone ending in same digits (`data-legacy.sql` line 6):**
```sql
-- Phone = '217-555-0142', last 4 = '0142'
INSERT INTO CDW_BORR_MSTR VALUES ('B-10001', 'James', 'Mitchell', 'R', 'ENC_XXX_001',
    ..., '217-555-0142', ...);
```

**3. Entity mapping (`LegacyLoanAccount.java` lines 29-30):**
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;  // "0142" — actually phone last 4!
```

**4. Service layer usage (`LoanService.java`):**
The current `toLoanSummary` method does NOT expose `BORR_SSN_LST4` in the DTO — it's only used for the borrower name. However, this field exists in the entity and is available for any code that accesses it directly.

**5. Column mapping (`column_mappings.md` line 51):**
```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```
The mapping correctly marks this field as "dropped" during migration, which prevents the bad data from propagating. However, any pre-migration code that uses this field for identity verification is using phone digits as SSN.

### Root Cause
The legacy ETL job that denormalized borrower data into `CDW_LN_ACCT` mapped the wrong source column. Instead of extracting the last 4 digits from the SSN field, it extracted the last 4 digits from the phone number field. This is a classic ETL column-offset bug in positional file processing.

### Impact at Runtime
- **No runtime exception** in current code — the field is mapped but not exposed via API
- **Identity verification failure** — any system using `BORR_SSN_LST4` for caller authentication will accept callers who know the phone number
- **Security/compliance violation** — PII field contains wrong data, violating data accuracy requirements under GLBA/FCRA
- **Cross-reference failure** — matching records across systems using SSN last-4 will produce false negatives

---

## RCA #3: Unguarded Numeric Parsing Causes Full API Failure

### Anomaly Summary
All numeric fields are stored as VARCHAR strings. The service layer uses `BigDecimal(string)` and `Integer.parseInt()` without try-catch. Any single malformed record (containing "$", "%", "N/A", spaces, or unexpected characters) will throw an uncaught `NumberFormatException` that crashes the entire API endpoint.

### Code Trace

**1. Schema allows any string (`schema-legacy.sql`):**
```sql
BORR_CRDT_SCR   VARCHAR(5),         -- credit score as string
BORR_ANN_INCM   VARCHAR(15),        -- annual income as string with commas
LN_ORIG_AMT     VARCHAR(15),        -- original amount as string
LN_DLQ_DAYS     VARCHAR(5),
LN_LTV_PCT      VARCHAR(8),         -- loan-to-value as string
```
No CHECK constraints, no format validation. Any string up to the VARCHAR length is accepted.

**2. Service layer parsing (`LoanService.java` lines 152-165):**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", "")); // throws NFE on "$285,000"
}

private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim()); // throws NFE on "N/A"
}
```
Only null/blank is handled. Any other malformed input throws an uncaught exception.

**3. Called from list endpoint (`LoanService.java` lines 48-56):**
```java
public List<LoanSummaryDto> getAllLoans() {
    return loanAccountRepository.findAll().stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
}
```
The stream `map()` operation will throw on the first malformed record, aborting the entire list operation.

**4. No global exception handler:**
There is no `@ControllerAdvice` or `@ExceptionHandler` in the codebase. The raw exception propagates as an HTTP 500 with a stack trace.

### Root Cause
The service layer assumes legacy data always conforms to expected numeric patterns. This assumption is invalid for production CDW data where:
- Manual data entry introduces "$" prefixes or "%" suffixes
- Null/missing values are represented as "N/A", "-", or empty strings differently per source system
- Batch loads from CSV can shift columns, placing text in numeric fields
- Legacy COBOL systems may use signed numeric formats (e.g., "1234-" for negative)

### Impact at Runtime
- **`NumberFormatException`** propagates as HTTP 500 Internal Server Error
- **Full endpoint failure** — `GET /api/loans` returns 500 for ALL users if ANY single loan record has malformed data
- **No partial results** — the stream-based processing provides no fallback for individual record failures
- **No observability** — no logging of which record or field caused the failure
- **Cascade effect** — `GET /api/borrowers/{id}` also calls `toLoanSummary` for attached loans, so a bad loan record also breaks the borrower endpoint

### Column Mapping Reference (`column_mappings.md` lines 20-22)
```
| BORR_CRDT_SCR | VARCHAR(5) | credit_score | INTEGER | Parse string -> integer |
| BORR_ANN_INCM | VARCHAR(15) | annual_income | DECIMAL(12,2) | Remove commas, parse -> decimal |
```
The mapping documents the transformation but not the error handling strategy, confirming that the migration would also fail on malformed data without additional validation.
