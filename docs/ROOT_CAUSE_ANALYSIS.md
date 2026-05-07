# Root Cause Analysis: Top 3 Critical Data Anomalies

This document traces the three most critical anomalies from the legacy data through the application code to identify where they cause runtime failures or incorrect API responses.

---

## RCA-001: Payment Component Sum Mismatch (ANO-001)

### Anomaly Summary
Payments for loan `LN-2019-00142` have component amounts (principal + interest + escrow + late fee) that sum to $1,887.02 while `PMT_AMT` is $1,487.02 -- a $400.00 discrepancy.

### Code Trace

**1. Data Ingestion (schema-legacy.sql:84-98)**
The `CDW_PMT_HIST` table stores all monetary values as `VARCHAR(15)` with no CHECK constraints. There is nothing at the schema level to enforce that `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`.

**2. Entity Mapping (LegacyPayment.java:25-37)**
The entity maps each column to a `String` field. No validation occurs during JPA hydration:
```java
@Column(name = "PMT_AMT")
private String totalAmount;       // "1,487.02"

@Column(name = "PMT_PRIN_AMT")
private String principalAmount;   // "456.78"

@Column(name = "PMT_INT_AMT")
private String interestAmount;    // "1,074.69"

@Column(name = "PMT_ESCROW_AMT")
private String escrowAmount;      // "355.55"
```

**3. Service Translation (LoanService.java:134-147)**
`toPaymentDto()` parses each component independently without cross-validation:
```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1487.02
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1074.69
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
```
Each field is parsed in isolation. There is no check that the components sum to the total.

**4. API Response (LoanController.java:33-36)**
The `getPayments()` endpoint returns the `PaymentDto` list directly. API consumers receive:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```
A consumer computing `principal + interest + escrow + lateFee` gets 1887.02, contradicting the `totalAmount` of 1487.02.

**5. Column Mappings (column_mappings.md:82-86)**
The mappings document each field's transformation individually but does not specify any cross-field integrity rule.

### Root Cause
There is no cross-field validation anywhere in the pipeline -- not in the schema (no CHECK constraint), not in the entity layer, not in the service translation, and not in the DTO. The service layer performs only per-field type conversion (string to BigDecimal) without any semantic validation of the financial relationship between fields.

### Runtime Impact
- **Incorrect API responses**: Consumers see contradictory financial data.
- **Silent corruption**: No error, warning, or log entry is produced. The mismatch propagates invisibly.
- **Downstream calculation errors**: Any system that recomputes totals from components (or vice versa) will get different results depending on which fields it uses.

### Recommended Fix Location
Add a `validatePaymentComponents()` method in the service layer that runs after parsing all payment fields. Compare `totalAmount` against the sum of components and log a warning if the discrepancy exceeds a tolerance threshold (e.g., $0.01).

---

## RCA-002: Unguarded Numeric String Parsing (ANO-002)

### Anomaly Summary
All numeric parsing methods (`parseLegacyAmount`, `parseLegacyInteger`, `parseLegacyDecimal`) throw uncaught exceptions on malformed input, which propagates as a 500 error for the entire API response.

### Code Trace

**1. Legacy Schema (schema-legacy.sql)**
Every numeric column is `VARCHAR`:
```sql
BORR_CRDT_SCR   VARCHAR(5),    -- credit score as string
BORR_ANN_INCM   VARCHAR(15),   -- annual income as string with commas
LN_ORIG_AMT     VARCHAR(15),   -- original amount as string
LN_INT_RT       VARCHAR(8),    -- interest rate as string "5.250"
```
No CHECK constraint validates that these contain numeric data.

**2. Parsing Methods (LoanService.java:152-165)**

```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", "")); // throws on "$285,000", "N/A", etc.
}

private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim()); // throws on "N/A", "seven-forty-five", etc.
}
```

The null/blank check is the only guard. Any non-numeric content that passes this check causes an unhandled `NumberFormatException`.

**3. Call Sites**

`parseLegacyAmount` is called 9 times across three methods:
- `toLoanSummary()` (lines 108-111): originalAmount, currentBalance, interestRate, monthlyPayment
- `toPaymentDto()` (lines 139-143): totalAmount, principalAmount, interestAmount, escrowAmount, lateFee

`parseLegacyInteger` is called once:
- `toBorrowerDto()` (line 129): creditScore

**4. Exception Propagation Path**

```
LoanController.getAllLoans()
  -> LoanService.getAllLoans()
    -> toLoanSummary() for EACH loan
      -> parseLegacyAmount(acct.getOriginalAmount())
        -> new BigDecimal("INVALID")
          -> NumberFormatException (UNCAUGHT)
            -> Spring translates to HTTP 500
```

A single bad record causes the entire list endpoint to fail. The `stream().map()` pattern in `getAllLoans()` (line 53) means the exception occurs mid-stream with no per-record error handling:
```java
return loanAccountRepository.findAll().stream()
    .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
    .collect(Collectors.toList());
```

### Root Cause
The parsing methods assume all non-null, non-blank strings are valid numeric values. There is no try-catch, no fallback, and no per-record error isolation. The `stream().map().collect()` pattern has no error boundary, so one bad record poisons the entire response.

### Runtime Impact
- **Total service outage for the endpoint**: One bad record = zero results returned.
- **No diagnostics**: The `NumberFormatException` stack trace doesn't include the record ID or field name, making it hard to identify the offending record.
- **Cascading failure**: If `getAllLoans()` is called by a health check or monitoring system, the 500 error could trigger false alarms or circuit breakers.

### Recommended Fix Location
1. Wrap each parsing method in try-catch, returning a fallback default and logging the raw value + record context.
2. In the stream processing, use a filter or flatMap pattern to skip/log bad records instead of failing the entire stream.

---

## RCA-003: SSN Last-4 Matches Phone Last-4 (ANO-003)

### Anomaly Summary
All 5 borrowers have `BORR_SSN_LST4` values in `CDW_LN_ACCT` that exactly match the last 4 digits of `BORR_PH_NBR` in `CDW_BORR_MSTR`, indicating corrupted or fabricated SSN data.

### Code Trace

**1. Data Source (data-legacy.sql:6-10 and 20-24)**

Borrower master:
```sql
-- B-10001: phone = '217-555-0142'
INSERT INTO CDW_BORR_MSTR VALUES ('B-10001', 'James', 'Mitchell', ... '217-555-0142', ...);
```

Loan account (denormalized):
```sql
-- BORR_SSN_LST4 = '0142' (matches phone last 4)
INSERT INTO CDW_LN_ACCT VALUES ('LN-2019-00142', 'B-10001', 'James', 'Mitchell', '0142', ...);
```

**2. Entity Mapping (LegacyLoanAccount.java:29-30)**
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```
The field is mapped but never validated against any authoritative source.

**3. Service Layer Usage (LoanService.java:103-118)**
`toLoanSummary()` does NOT use `BORR_SSN_LST4` in the DTO output. The field is loaded by JPA but currently unused in API responses. However:
- The field IS available on the entity and could be used by future code.
- The field IS loaded into memory on every `findAll()` call.
- The column_mappings.md marks it as "*(dropped)*" for modern schema, meaning it's intentionally excluded from migration -- but the data quality issue in the legacy system persists.

**4. Cross-Table Correlation**
The service layer does not cross-reference `CDW_LN_ACCT.BORR_SSN_LST4` against `CDW_BORR_MSTR.BORR_PH_NBR`. There is no validation that would detect this correlation. The borrower phone number is exposed via `toBorrowerDto()` (line 126):
```java
dto.setPhone(borrower.getPhoneNumber());  // "217-555-0142"
```

If a downstream consumer also had access to SSN last-4 from another source, they could inadvertently correlate it with phone numbers, leaking PII.

### Root Cause
The legacy ETL process that populated `CDW_LN_ACCT.BORR_SSN_LST4` likely used the phone number's last 4 digits as a placeholder or had a mapping error in the source extraction. The lack of cross-field validation in the entire pipeline (ETL, schema, application) means this corruption was never detected.

### Runtime Impact
- **PII integrity risk**: SSN data is unreliable. Any identity verification relying on SSN last-4 is actually checking phone number digits.
- **Regulatory exposure**: Under GLBA and FCRA, financial institutions must maintain accurate customer records. Corrupted SSN data could trigger compliance findings during audits.
- **Silent**: No runtime error occurs. The bad data sits in the system indefinitely unless specifically audited.

### Recommended Fix Location
1. Add a cross-field validation in the service layer that compares `BORR_SSN_LST4` against the last 4 digits of `BORR_PH_NBR` for each loan-borrower pair.
2. Flag matching records as suspect and log a high-severity warning.
3. Exclude `BORR_SSN_LST4` from any identity verification workflows until the data is re-sourced.
