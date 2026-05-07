# Root Cause Analysis — Top 3 Critical Data Anomalies

> For each anomaly, this document traces through the code path from database → entity → service → DTO → API response to identify where the anomaly causes a runtime failure or incorrect result.

---

## RCA-1: Payment Component Amounts Do Not Sum to Total (ANO-001)

### Anomaly

Three payment records have component amounts (principal + interest + escrow + late fee) that do not equal the stated total:

| Record | Stated Total | Computed Sum | Delta |
|--------|-------------|--------------|-------|
| `PMT-2025120001` | $1,487.02 | $1,887.02 | +$400.00 |
| `PMT-2025110001` | $1,487.02 | $1,887.02 | +$400.00 |
| `PMT-2025110003` | $1,077.05 | $1,124.55 | +$47.50 |

### Code Path Trace

**1. Data Layer** — `CDW_PMT_HIST` stores all amounts as independent VARCHAR columns with no check constraint:
```sql
-- schema-legacy.sql lines 84-98
PMT_AMT         VARCHAR(15),   -- total payment as string
PMT_PRIN_AMT    VARCHAR(15),   -- principal portion
PMT_INT_AMT     VARCHAR(15),   -- interest portion
PMT_ESCROW_AMT  VARCHAR(15),   -- escrow portion
PMT_LATE_FEE    VARCHAR(15),
```
No database-level constraint validates that `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`.

**2. Entity Layer** — `LegacyPayment.java` maps each column to a `String` field. No validation at the entity level:
```java
// LegacyPayment.java lines 25-38
@Column(name = "PMT_AMT")
private String totalAmount;
@Column(name = "PMT_PRIN_AMT")
private String principalAmount;
@Column(name = "PMT_INT_AMT")
private String interestAmount;
@Column(name = "PMT_ESCROW_AMT")
private String escrowAmount;
@Column(name = "PMT_LATE_FEE")
private String lateFee;
```

**3. Service Layer** — `LoanService.toPaymentDto()` (lines 134-147) parses each amount independently using `parseLegacyAmount()` and sets them on the DTO with **no cross-validation**:
```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));        // 1,487.02
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
```

**4. API Response** — The `PaymentDto` is serialized directly to JSON. An API consumer receives:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```
The consumer has no way to know the components don't add up to the total.

### Root Cause

The root cause is **dual**:
1. **Source data error**: The legacy CDW system accepted component amounts that don't reconcile. For `PMT-2025120001` and `PMT-2025110001` (both for loan `LN-2019-00142`), the escrow portion ($355.55) appears to be double-counted or erroneously included. For `PMT-2025110003`, the late fee ($47.50) was recorded as a component but not included in the total.
2. **No validation in translation layer**: `LoanService.toPaymentDto()` blindly passes through all amounts without checking `total == sum(components)`.

### Runtime Impact

- **No runtime exception** — the code runs successfully, producing silently incorrect data
- Financial aggregations (sum of payments, balance reconciliation) will be wrong by $400 per affected payment
- If a downstream system recomputes the total from components, it will get a different number than the stated total, causing reconciliation failures

### Column Mapping Reference

Per `column_mappings.md` lines 82-86, all payment amounts map from `VARCHAR(15)` → `DECIMAL(10,2)` with "remove commas, parse → decimal". No cross-field validation is documented.

---

## RCA-2: SSN Last-4 Contains Phone Number Suffixes (ANO-002)

### Anomaly

All 5 loan accounts have `BORR_SSN_LST4` values that match the borrower's phone number last 4 digits, not their actual SSN last 4.

### Code Path Trace

**1. Data Layer** — `CDW_LN_ACCT.BORR_SSN_LST4` is `VARCHAR(4)` with no constraint:
```sql
-- schema-legacy.sql line 57
BORR_SSN_LST4   VARCHAR(4),
```

**2. Seed Data** — Cross-referencing `data-legacy.sql`:
```
-- Borrower B-10001: phone = '217-555-0142', SSN encrypted = 'ENC_XXX_001'
-- Loan LN-2019-00142: BORR_SSN_LST4 = '0142'  ← matches phone, NOT SSN
```
The pattern holds for all 5 records: the last 4 digits of the phone number were incorrectly stored as the SSN last 4.

**3. Entity Layer** — `LegacyLoanAccount.java` maps the field but it is **never used** in the service layer:
```java
// LegacyLoanAccount.java lines 29-30
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```

**4. Service Layer** — `LoanService.toLoanSummary()` (lines 103-118) does NOT include `borrowerSsnLast4` in the DTO. The field exists in the entity but is never read by any service method.

**5. Column Mapping** — Per `column_mappings.md` line 51, `BORR_SSN_LST4` is marked as `*(dropped)*` — it should not be migrated to the modern schema.

### Root Cause

The root cause is a **data entry/ETL error** in the legacy CDW system. When the denormalized loan account records were originally populated, the ETL process that extracted borrower data likely mapped the wrong source column — pulling from the phone number field instead of the SSN field. The `VARCHAR(4)` type constraint was satisfied (phone suffixes are also 4 digits), so no error was raised.

### Runtime Impact

- **No current runtime failure** — the field is mapped to the entity but never read by the service layer
- **Migration risk**: If a future developer adds SSN-last-4 verification (e.g., for phone banking authentication), they would be verifying against phone digits, creating a security vulnerability
- **Data migration risk**: If the field is accidentally included in migration despite `column_mappings.md` marking it as dropped, corrupted SSN data enters the modern system

### Why This Is Critical Despite No Current Code Path

The field is present in the JPA entity (`LegacyLoanAccount.borrowerSsnLast4`) with a getter/setter. Any developer could innocently add it to a DTO or use it in a verification flow without realizing the data is wrong. The field name (`BORR_SSN_LST4`) strongly implies it contains SSN data.

---

## RCA-3: Numeric Parsing with No Error Handling (ANO-003)

### Anomaly

All three parsing methods in `LoanService` throw uncaught exceptions on malformed input, causing 500 errors.

### Code Path Trace

**1. Service Layer — `parseLegacyAmount()`** (lines 152-155):
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // throws NumberFormatException
}
```
- Null/blank check: present
- Comma stripping: present
- Error handling for non-numeric content: **ABSENT**
- Input like `"$285,000"` → after comma strip: `"$285000"` → `new BigDecimal("$285000")` → **NumberFormatException**

**2. Service Layer — `parseLegacyDecimal()`** (lines 157-160):
```java
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // throws NumberFormatException
}
```
- No comma stripping (assumes clean decimal like "5.250")
- Input like `"5.250%"` → `new BigDecimal("5.250%")` → **NumberFormatException**

**3. Service Layer — `parseLegacyInteger()`** (lines 162-165):
```java
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // throws NumberFormatException
}
```
- Input like `"N/A"` or `"---"` → `Integer.parseInt("N/A")` → **NumberFormatException**

**4. Call Sites** — These methods are called from within stream operations:

```java
// getAllLoans() line 53-55
return loanAccountRepository.findAll().stream()
    .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
    .collect(Collectors.toList());
```

If ANY single record has a malformed numeric field, the entire stream operation fails. The exception propagates up through the controller to the default Spring error handler, returning a 500 with a stack trace.

**5. Controller Layer** — `LoanController` and `BorrowerController` have **no exception handlers** (`@ExceptionHandler` or `@ControllerAdvice`). The raw `NumberFormatException` becomes an unhandled 500:

```json
{
  "timestamp": "2025-12-01T...",
  "status": 500,
  "error": "Internal Server Error",
  "path": "/api/loans",
  "message": "Character $ is neither a decimal digit number..."
}
```

### Root Cause

The root cause is **defensive coding omission**. The service layer was written assuming all VARCHAR values conform to the expected format (pure numeric with optional commas). Legacy data warehouses commonly contain:
- Placeholder values: `"N/A"`, `"TBD"`, `"---"`, `"PENDING"`
- Currency symbols: `"$285,000"`, `"$0.00"`
- Percentage signs: `"5.250%"`, `"82.5%"`
- Overflow markers: `"*****"`, `"ERR"`
- Mixed formats from different source systems feeding the DW

### Runtime Impact

- **Single-record poison**: One malformed record in any table causes the corresponding list endpoint to return 500 for ALL records
- **Stack trace leak**: Default Spring error handling exposes internal class names (`LoanService`), method names (`parseLegacyAmount`), and field context
- **No graceful degradation**: The API provides no partial results — it's all-or-nothing
- **Cascading failure**: `getBorrowerById()` calls both borrower parsing AND loan parsing, so a bad record in either table can fail the borrower endpoint

### Column Mapping Reference

Per `column_mappings.md` lines 94-98 (Common Transformation Patterns):
- "Amount conversion: Remove commas from string, parse to DECIMAL"
- No mention of error handling for non-conforming values — the mapping document assumes clean data
