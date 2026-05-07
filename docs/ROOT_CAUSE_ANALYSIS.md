# Root Cause Analysis — Top 3 Critical Anomalies

---

## RCA-1: Payment Component Amounts Exceed Total Payment (ANM-001)

### Anomaly Summary

Payments PMT-2025120001 and PMT-2025110001 (loan LN-2019-00142) have component sums of $1,887.02 (principal + interest + escrow + late fee) but a stated total of $1,487.02 — a $400.00 overage.

### Code Path Trace

**1. Data enters via `data-legacy.sql`:**
```sql
INSERT INTO CDW_PMT_HIST VALUES ('PMT-2025120001', 'LN-2019-00142', '12/15/2025',
  '1,487.02', '456.78', '1,074.69', '355.55', '0.00', 'REG', 'PST', ...);
--  total=1487.02  prin=456.78  int=1074.69  escrow=355.55  late=0.00
--  sum of components = 456.78 + 1074.69 + 355.55 + 0.00 = 1887.02  ≠  1487.02
```

**2. Entity mapping (`LegacyPayment.java`):**
Each component is mapped to a separate String field via JPA `@Column` annotations (lines 25-37). No validation occurs at the entity level — the values are stored exactly as they appear in the database.

**3. Service translation (`LoanService.java`, lines 134-147 — `toPaymentDto`):**
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
    ...
}
```
Each amount is parsed independently. The service **never cross-validates** that the components sum to the total. The contradictory data flows directly into the API response.

**4. API exposure (`LoanController.java`, line 33-36):**
```java
@GetMapping("/{loanId}/payments")
public List<PaymentDto> getPayments(@PathVariable String loanId) {
    return loanService.getPaymentsByLoan(loanId);
}
```
The controller returns the unvalidated DTO directly. An API consumer calling `GET /api/loans/LN-2019-00142/payments` receives contradictory financial data.

**5. Column mappings (`column_mappings.md`, lines 82-86):**
The mapping doc specifies `PMT_AMT → total_amount (DECIMAL)`, `PMT_PRIN_AMT → principal_amount (DECIMAL)`, etc. All are marked as "Remove commas, parse → decimal" with no cross-field validation requirement documented.

### Root Cause

The legacy CDW system has no check constraint enforcing `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE = PMT_AMT`. The Spring service layer performs type conversion but no business-rule validation. There is no layer in the system that validates cross-field consistency.

### Runtime Impact

- **API response:** Returns $1,887.02 in components against a $1,487.02 total — any consumer that sums components (e.g., for reconciliation or display breakdown) will show a different number than the total.
- **Financial reporting:** A downstream system that uses component amounts for GL entries will book $400 more than the actual payment amount.
- **No error signal:** The issue is completely silent — no exception, no log message, no warning.

---

## RCA-2: Delinquent Loan Marked as Active (ANM-002)

### Anomaly Summary

Loan LN-2018-00089 has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'`. A loan with non-zero delinquency days should not have an active status.

### Code Path Trace

**1. Data enters via `data-legacy.sql`:**
```sql
INSERT INTO CDW_LN_ACCT VALUES ('LN-2018-00089', 'B-10003', 'Michael', 'Torres', '0167',
  'ARM51', '195,000', '178,234.12', '5.250', '360', '1,077.05',
  '07/01/2018', '07/01/2048', '08/01/2018', '01/01/2026',
  'ACT', '15', ...);
--  status=ACT but delinquency_days=15
```

**2. Entity mapping (`LegacyLoanAccount.java`):**
`statusCode` (line 62-63) and `delinquencyDays` (line 65-66) are independent String fields with no relationship validation.

**3. Service translation (`LoanService.java`, lines 103-118 — `toLoanSummary`):**
```java
dto.setStatus(expandStatusCode(acct.getStatusCode()));  // "ACT" → "Active"
```
The status code is expanded to "Active" (line 112). The delinquency days field (`LN_DLQ_DAYS`) is **never read** in `toLoanSummary` — it is completely ignored. The `LoanSummaryDto` has no field for delinquency days.

**4. Status expansion (`LoanService.java`, lines 167-176):**
```java
private String expandStatusCode(String code) {
    return switch (code) {
        case "ACT" -> "Active";
        case "CLO" -> "Closed";
        case "DFT" -> "Default";
        case "FRB" -> "Forbearance";
        default -> code;
    };
}
```
The method maps `ACT → Active` with no consideration of delinquency context.

**5. Column mappings (`column_mappings.md`, line 62-63):**
- `LN_STAT_CD → status`: "Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE"
- `LN_DLQ_DAYS → delinquency_days`: "Parse string → integer"

The mappings document treats these as independent fields with no cross-validation rule.

### Root Cause

Two-fold:
1. **Legacy data issue:** The CDW source system allowed `LN_STAT_CD` and `LN_DLQ_DAYS` to be set independently. A batch job likely updated delinquency days without triggering a corresponding status code update.
2. **Service layer gap:** `toLoanSummary` reads `LN_STAT_CD` but ignores `LN_DLQ_DAYS` entirely. The delinquency days are not exposed anywhere in the API, so the conflicting data is invisible to consumers.

### Runtime Impact

- **API response:** `GET /api/loans/LN-2018-00089` returns `"status": "Active"` with no indication the loan is delinquent. API consumers have no way to know the loan has 15 delinquency days.
- **Risk dashboards:** Any system relying on this API for delinquency reporting will miss this loan entirely.
- **Incorrect filtering:** `LegacyLoanAccountRepository.findByStatusCode("ACT")` includes this delinquent loan in "active" results.

---

## RCA-3: Numeric Strings Without Parse Error Handling (ANM-003)

### Anomaly Summary

All financial amounts, rates, scores, and term values are stored as VARCHAR in the legacy schema. The service layer parses them to Java numeric types but has no error handling — a single malformed value crashes the entire request.

### Code Path Trace

**1. Schema definition (`schema-legacy.sql`):**
```sql
BORR_CRDT_SCR   VARCHAR(5),      -- credit score as string
BORR_ANN_INCM   VARCHAR(15),     -- annual income as string with commas
LN_ORIG_AMT     VARCHAR(15),     -- original amount as string
LN_INT_RT       VARCHAR(8),      -- interest rate as string "5.250"
```
Every numeric column is VARCHAR with no CHECK constraints on format.

**2. Service parsing methods (`LoanService.java`, lines 152-165):**

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

All three methods:
- Handle `null` and blank strings correctly (returning zero or null)
- **Throw unchecked `NumberFormatException`** for any other non-numeric input
- Have **no try-catch block**

**3. Call sites in `toLoanSummary` (lines 108-111):**
```java
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
```

**4. Call site in `toBorrowerDto` (line 129):**
```java
dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
```

**5. Call sites in `toPaymentDto` (lines 139-143):**
```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
...
```

**6. Blast radius — `getAllLoans` (lines 48-56):**
```java
public List<LoanSummaryDto> getAllLoans() {
    return loanAccountRepository.findAll().stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
}
```
A `NumberFormatException` in **any single loan record** during `.map()` terminates the entire stream. The API returns a 500 error instead of the list of loans.

**7. Column mappings (`column_mappings.md`):**
The mappings specify transformations like "Remove commas, parse → decimal" and "Parse string → integer" but do not specify error-handling behavior for malformed data.

### Root Cause

The legacy CDW schema uses VARCHAR for all fields (a common data warehouse anti-pattern for flexibility). The service layer assumes all string values are well-formed numbers after null/blank checking. There is no defensive parsing, no try-catch, and no per-record error isolation. The `Stream.map()` pipeline propagates any exception to the caller, making the blast radius the entire API response.

### Runtime Impact

- **Single bad record → total API failure:** If any record in `CDW_LN_ACCT`, `CDW_BORR_MSTR`, or `CDW_PMT_HIST` has a malformed numeric value (e.g., `"N/A"`, `"$285,000"`, `"TBD"`, or a value with extra whitespace/characters), the corresponding list endpoint returns HTTP 500.
- **Credit score parsing:** `parseLegacyInteger("N/A")` → `NumberFormatException` → `GET /api/borrowers` returns 500.
- **Amount parsing:** `parseLegacyAmount("$285,000")` → the `$` is not stripped → `NumberFormatException`.
- **No partial results:** Due to the stream pipeline, it's all-or-nothing. Even 1 bad record out of 10,000 kills the response.
- **No logging:** The exception is not caught or logged by the service layer — Spring Boot returns a generic 500 with a stack trace (if `server.error.include-stacktrace` is enabled).
