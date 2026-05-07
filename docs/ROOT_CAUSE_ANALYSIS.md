# Root Cause Analysis — Top 3 Critical Anomalies

---

## RCA-001: Payment Component Amounts Do Not Sum to Total (ANM-001)

### Anomaly Summary
For loan `LN-2019-00142` (James Mitchell), both payment records show a total of `1,487.02` but the sum of components is `1,887.02` — a $400 discrepancy. For loan `LN-2018-00089` (Michael Torres), the November payment total is `1,077.05` but the sum of components is `1,124.55` — a $47.50 discrepancy equal to the late fee.

### Code Path Trace

**1. Data ingestion:** `data-legacy.sql` inserts payment records directly via `INSERT INTO CDW_PMT_HIST VALUES (...)`. No stored procedure or trigger validates that component amounts sum to the total.

**2. Schema:** `schema-legacy.sql` defines all amount columns as `VARCHAR(15)` with no CHECK constraints:
```sql
PMT_AMT         VARCHAR(15),   -- total payment as string
PMT_PRIN_AMT    VARCHAR(15),   -- principal portion
PMT_INT_AMT     VARCHAR(15),   -- interest portion
PMT_ESCROW_AMT  VARCHAR(15),   -- escrow portion
PMT_LATE_FEE    VARCHAR(15),
```

**3. Service layer:** `LoanService.toPaymentDto()` (lines 134-147) parses each component independently and places them into `PaymentDto` without any cross-field validation:
```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));        // 1,487.02
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));// 456.78
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount())); // 1,074.69
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));     // 355.55
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));               // 0.00
// No validation: 456.78 + 1074.69 + 355.55 + 0.00 = 1887.02 ≠ 1487.02
```

**4. API response:** `LoanController.getPayments()` (line 34) returns the `PaymentDto` list directly. The inconsistent amounts are served to API consumers without warning.

**5. Column mappings:** `data/mappings/column_mappings.md` specifies the transformation `Remove commas, parse → decimal` for all amount fields, but documents no cross-field validation rule.

### Root Cause
The legacy CDW system has no integrity constraint requiring `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. The VARCHAR type prevents the database from performing arithmetic checks. The Spring Boot service layer performs field-by-field parsing without cross-validation. The $400 discrepancy on LN-2019-00142 likely originates from an upstream ETL process that computed the total using a different formula (e.g., excluding escrow). The $47.50 discrepancy on LN-2018-00089 matches the late fee exactly, suggesting the total was computed before the late fee was assessed.

### Where Runtime Failure Occurs
No runtime exception occurs — this is a **silent data integrity failure**. The API returns mathematically inconsistent financial data. Any consumer that sums the components and compares to the total will see mismatches. This is arguably worse than a crash because the error propagates undetected.

---

## RCA-002: SSN Last-4 Contains Phone Number Digits (ANM-002)

### Anomaly Summary
Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` matches the last 4 digits of the corresponding borrower's phone number from `CDW_BORR_MSTR`, not their actual SSN last-4.

### Code Path Trace

**1. Data ingestion:** `data-legacy.sql` inserts loan accounts with SSN last-4 values:
```sql
-- Loan for B-10001: SSN_LST4 = '0142', Borrower phone = '217-555-0142'
INSERT INTO CDW_LN_ACCT VALUES ('LN-2019-00142', 'B-10001', 'James', 'Mitchell', '0142', ...);
```
All 5 loan records follow the same pattern: SSN_LST4 = phone last 4.

**2. Schema:** `schema-legacy.sql` defines `BORR_SSN_LST4 VARCHAR(4)` with no validation. The column comment says nothing about data source.

**3. Entity mapping:** `LegacyLoanAccount.java` (line 29-30) maps the column:
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```

**4. Service layer:** `LoanService.toLoanSummary()` (lines 103-118) does **not** use `borrowerSsnLast4` in the DTO. The field is present in the entity but never exposed via the API. However, `LoanService.toBorrowerDto()` also doesn't cross-reference or validate it.

**5. Column mappings:** `data/mappings/column_mappings.md` (line 51) marks `BORR_SSN_LST4` as `*(dropped)*` in the modern schema, recognizing it as denormalized data. But the mapping doc doesn't flag that the current values are incorrect.

### Root Cause
The legacy ETL process that populated `CDW_LN_ACCT` extracted the wrong source field. Instead of deriving the SSN last-4 from `CDW_BORR_MSTR.BORR_SSN_ENCR` (which would require decryption), the ETL likely used a simpler extraction from the phone number field. This is a classic legacy ETL mapping error where similarly structured 4-digit fields were confused.

### Where Runtime Failure Occurs
No runtime crash occurs because `LoanService` does not currently use `BORR_SSN_LST4`. However:
- Any future code that uses this field for identity verification will produce **false positive matches** (phone number match ≠ SSN match).
- Migration to the modern schema would carry this corrupted data forward if not caught.
- Regulatory compliance audits that check SSN-based identity verification would find incorrect data.

---

## RCA-003: Numeric String Parsing Without Error Handling (ANM-003)

### Anomaly Summary
All numeric conversions in the service layer use unchecked parsing methods that throw unhandled exceptions on malformed input.

### Code Path Trace

**1. Entry point:** A request to `GET /api/loans` hits `LoanController.getAllLoans()` → `LoanService.getAllLoans()`.

**2. Stream processing:** `LoanService.getAllLoans()` (lines 48-56) loads ALL loan accounts and maps them in a stream:
```java
return loanAccountRepository.findAll().stream()
        .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
        .collect(Collectors.toList());
```

**3. Parsing calls in `toLoanSummary()`** (lines 103-118):
```java
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));   // line 108
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));   // line 109
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));      // line 110
dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));   // line 111
```

**4. The vulnerable parsing methods** (lines 152-165):
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", "")); // NumberFormatException if not numeric
}

private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim()); // NumberFormatException if not numeric
}
```

**5. No exception handling:** There is no try-catch in `parseLegacyAmount`, `parseLegacyDecimal`, or `parseLegacyInteger`. There is no `@ExceptionHandler` or `@ControllerAdvice` in the application. An unhandled `NumberFormatException` propagates up the call stack and results in an HTTP 500 with a generic Whitelabel error page.

**6. Blast radius:** Because `getAllLoans()` uses `.stream().map()`, a single bad record causes the entire stream to fail. The API returns zero results, not partial results with the bad record excluded.

**7. Same pattern in `toBorrowerDto()`** (line 129):
```java
dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore())); // crashes on "N/A"
```
This means `GET /api/borrowers` has the same vulnerability.

### Root Cause
The parsing methods were written assuming the legacy data always conforms to the expected numeric format. This assumption is fragile because:
1. The VARCHAR schema provides no type enforcement at the database level.
2. Upstream ETL processes may insert sentinel values (`"N/A"`, `"PENDING"`, `"TBD"`).
3. Manual data corrections may introduce format errors (e.g., `"$285,000"` with dollar sign).
4. The legacy CDW likely has thousands of records accumulated over decades — format drift is inevitable.

### Where Runtime Failure Occurs
- `LoanService.parseLegacyAmount()` at line 154: `new BigDecimal(amount.replace(",", ""))` throws `NumberFormatException`
- `LoanService.parseLegacyInteger()` at line 164: `Integer.parseInt(value.trim())` throws `NumberFormatException`
- The exception propagates uncaught through the stream pipeline, through the controller, to Spring's default error handler → HTTP 500

### Incorrect API Response
Instead of a meaningful error, the consumer receives:
```json
{
  "timestamp": "...",
  "status": 500,
  "error": "Internal Server Error",
  "path": "/api/loans"
}
```
No indication of which record or field caused the failure.
