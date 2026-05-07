# Root Cause Analysis — Top 3 Critical Anomalies

---

## RCA-1: Payment Component Arithmetic Mismatch (ANO-001)

### Anomaly Summary
For loan `LN-2019-00142`, both payment records (`PMT-2025120001`, `PMT-2025110001`) have component sums that exceed the total by exactly $400.00. For `PMT-2025110003` (loan `LN-2018-00089`), the sum exceeds the total by exactly $47.50 — the late fee amount.

### Code Trace

**Entry point:** `LoanController.getPayments()` → `LoanService.getPaymentsByLoan()`

```
LoanController.java:33-35
  → LoanService.getPaymentsByLoan():90-95
    → LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()
    → LoanService.toPaymentDto():134-147
      → parseLegacyAmount() for each component field
```

**`LoanService.toPaymentDto()` (lines 134-147):**
```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));         // 1,487.02
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
// No validation that components sum to total
```

Each field is parsed independently. There is **no cross-field validation** anywhere in the pipeline — not in the entity, not in the repository, not in the service, and not in the DTO.

**`parseLegacyAmount()` (lines 152-155):**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}
```

This method faithfully parses whatever string is stored, so the incorrect values flow through to the API response verbatim.

### Root Cause
The legacy CDW data warehouse has **no check constraints** enforcing that `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE = PMT_AMT`. The data was likely loaded from a source system that:

1. **For `LN-2019-00142`:** The escrow component ($355.55) appears to have been added to the breakdown columns but the `PMT_AMT` total was not updated to include it. The pre-escrow total matches: $456.78 + $1,074.69 = $1,531.47, which also doesn't equal $1,487.02. Actually, $1,487.02 matches the loan's `LN_PMT_AMT` (monthly payment), suggesting the total was copied from the loan terms rather than calculated from the actual payment components.

2. **For `PMT-2025110003`:** The late fee ($47.50) was recorded in the component column but not added to the total, suggesting the total was captured before the late fee was assessed.

### Runtime Failure Mode
- **No crash** — the data loads and the API returns a response.
- **Silent data corruption** — API consumers receive payment breakdowns that don't reconcile. Any financial reporting or accounting system downstream will flag these as out-of-balance transactions.
- **Affected endpoints:** `GET /api/loans/{loanId}/payments`

### Where Validation Should Be Added
`LoanService.toPaymentDto()` — after parsing all components, add a reconciliation check before returning the DTO.

---

## RCA-2: SSN Last-4 Derived from Phone Number (ANO-002)

### Anomaly Summary
Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` matches the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR`, rather than the actual SSN.

### Code Trace

**Entry point:** `LoanController.getLoan()` → `LoanService.getLoanById()`

```
LoanController.java:28-31
  → LoanService.getLoanById():58-64
    → LoanService.toLoanSummary():103-118
```

**`LoanService.toLoanSummary()` (lines 103-118):**
```java
private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
    LoanSummaryDto dto = new LoanSummaryDto();
    dto.setLoanAccountNumber(acct.getLoanAccountNumber());
    dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
    // ...
}
```

The `LegacyLoanAccount` entity maps `BORR_SSN_LST4` to `borrowerSsnLast4` (line 29-30 of `LegacyLoanAccount.java`):
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```

While `toLoanSummary()` does not currently expose `borrowerSsnLast4` in the DTO, the field is present on the entity and accessible. Any future feature that uses it (e.g., borrower verification, identity matching, SSN masking display) will use phone-derived data.

**Cross-reference with `column_mappings.md` (line 51):**
```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```

The migration mapping correctly marks this field as "dropped," but until migration completes, any code accessing the entity field gets corrupted data.

### Root Cause
The legacy ETL process that populated `CDW_LN_ACCT` from the source system mapped the wrong source column. The `BORR_SSN_LST4` field was populated from a phone-number-derived field instead of the actual SSN. Evidence:

| BORR_ID | Phone Number | SSN_LST4 | Phone Last-4 |
|---|---|---|---|
| B-10001 | 217-555-0142 | 0142 | 0142 |
| B-10002 | 503-555-0198 | 0198 | 0198 |
| B-10003 | 512-555-0167 | 0167 | 0167 |
| B-10004 | 303-555-0134 | 0134 | 0134 |
| B-10005 | 602-555-0156 | 0156 | 0156 |

The probability of all 5 records coincidentally matching is astronomically low — this is a systemic ETL mapping error.

### Runtime Failure Mode
- **No crash** — the field loads correctly as a string.
- **Silent PII integrity violation** — any identity verification workflow using SSN last-4 will fail or, worse, will incorrectly match borrowers who share the same phone suffix.
- **Affected entity:** `LegacyLoanAccount.borrowerSsnLast4` — not currently exposed via API but available for programmatic use.

### Where Validation Should Be Added
`LoanService` (or a new `LegacyDataValidator`) — add a cross-table validation that detects when `BORR_SSN_LST4` matches the phone number suffix from the borrower master record, and flag those records as unreliable.

---

## RCA-3: Unguarded Numeric String Parsing (ANO-003)

### Anomaly Summary
All financial amounts, rates, scores, and counts are stored as VARCHAR strings. The service layer parses them without try-catch, meaning any unexpected character causes an unhandled `NumberFormatException`.

### Code Trace

**`LoanService.parseLegacyAmount()` (lines 152-155):**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // No try-catch
}
```

**`LoanService.parseLegacyDecimal()` (lines 157-160):**
```java
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // No try-catch
}
```

**`LoanService.parseLegacyInteger()` (lines 162-165):**
```java
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // No try-catch
}
```

**Call sites:**
- `parseLegacyAmount` is called 10 times: in `toLoanSummary` (4 calls for originalAmount, currentBalance, monthlyPayment, and via `parseLegacyDecimal` for interestRate) and in `toPaymentDto` (5 calls for totalAmount, principalAmount, interestAmount, escrowAmount, lateFee).
- `parseLegacyInteger` is called in `toBorrowerDto` for `creditScore`.

**Failure chain for `GET /api/loans`:**
```
LoanController.getAllLoans()
  → LoanService.getAllLoans()
    → loanAccountRepository.findAll()  // returns all 5 accounts
    → .map(acct -> toLoanSummary(...))  // processes each account
      → parseLegacyAmount(acct.getOriginalAmount())  // if "INVALID" → NFE
        → NumberFormatException propagates up
          → Stream processing aborts
            → Spring returns 500 Internal Server Error
```

A single malformed record causes the **entire list endpoint** to fail, not just that one record.

### Root Cause
The legacy data warehouse uses `VARCHAR` for all columns (the schema explicitly documents this as "VARCHAR for everything (loose typing)"). The Java service layer was written assuming that all string values will be well-formed numbers. This assumption holds for the current seed data but is fragile:

1. **No schema-level CHECK constraints** to enforce numeric format
2. **No application-level validation** before parsing
3. **No error isolation** — failure in one record kills the entire request

The parsing methods handle `null` and blank strings correctly but not malformed strings.

### Runtime Failure Mode
- **Hard crash** — `NumberFormatException` is unchecked and propagates as HTTP 500.
- **Blast radius** — one bad record in any table takes down the corresponding list endpoint for ALL records.
- **Affected endpoints:** `GET /api/loans`, `GET /api/loans/{id}`, `GET /api/borrowers`, `GET /api/borrowers/{id}`, `GET /api/loans/{id}/payments`

### Where Validation Should Be Added
All three parsing methods in `LoanService.java` (lines 152-165) need try-catch wrappers. Additionally, a `LegacyDataValidator` class should pre-validate records at ingestion time and collect warnings rather than failing silently or crashing.
