# Root Cause Analysis — Top 3 Critical Anomalies

---

## RCA-1: Numeric Strings Cause Unhandled Runtime Exceptions (ANO-001)

### Symptom

Any non-numeric value in a monetary, rate, or integer column causes a `500 Internal Server Error` — the exception propagates uncaught from the service layer through the controller to the client.

### Code Trace

**Entry point:** `GET /api/loans` → `LoanController.getAllLoans()` → `LoanService.getAllLoans()`

```
LoanController.getAllLoans()                    // controller/LoanController.java:24
  └─ LoanService.getAllLoans()                  // service/LoanService.java:48
       └─ toLoanSummary(acct, product)          // service/LoanService.java:54
            ├─ parseLegacyAmount(acct.getOriginalAmount())    // line 108
            ├─ parseLegacyAmount(acct.getCurrentBalance())    // line 109
            ├─ parseLegacyDecimal(acct.getInterestRate())     // line 110
            └─ parseLegacyAmount(acct.getMonthlyPayment())    // line 111
```

**Failure point:** `LoanService.java:154`

```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // ← THROWS HERE
}
```

If `amount` is `"N/A"`, `"$285,000"`, `"TBD"`, or any non-numeric string after comma removal, `new BigDecimal(...)` throws `NumberFormatException`.

Similarly at `LoanService.java:164`:

```java
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // ← THROWS for "N/A", "PENDING", etc.
}
```

This is called from `toBorrowerDto` (line 129) for credit score parsing.

**Propagation path:**
1. `parseLegacyAmount` throws `NumberFormatException`
2. `toLoanSummary` does not catch it
3. `getAllLoans` stream operation fails — entire list endpoint returns 500
4. No `@ControllerAdvice` or exception handler exists in the codebase
5. Spring Boot default error handling returns a generic JSON error with no useful context

**Entity-to-column mapping:**
- `LegacyLoanAccount.originalAmount` ← `CDW_LN_ACCT.LN_ORIG_AMT` (VARCHAR(15))
- `LegacyLoanAccount.interestRate` ← `CDW_LN_ACCT.LN_INT_RT` (VARCHAR(8))
- `LegacyBorrower.creditScore` ← `CDW_BORR_MSTR.BORR_CRDT_SCR` (VARCHAR(5))

All are VARCHAR with no CHECK constraints, so the database happily accepts any string.

### Root Cause

The service layer assumes all VARCHAR numeric fields contain valid numeric strings (or null/blank). The parsing methods have a null/blank guard but no catch block for `NumberFormatException`. Since legacy data warehouses commonly contain placeholder values (`"N/A"`, `"TBD"`, `"PENDING"`, `"ERR"`), this assumption is unsafe. A single bad record poisons the entire API response because the exception occurs inside a `stream().map()` operation.

### Impact on API Response

- **Runtime failure:** `GET /api/loans` returns `500 Internal Server Error` if ANY loan has a non-numeric amount
- **Blast radius:** One bad record kills the entire list endpoint (not just that record)
- **No error context:** The default Spring error response doesn't identify which record or field caused the failure
- **Silent zero substitution:** null/blank values are silently converted to `BigDecimal.ZERO`, meaning a missing $285K loan amount appears as $0 — no warning, no flag

### Migration Impact

The `column_mappings.md` specifies transformations like `"Remove commas, parse → decimal"` and `"Parse string → integer"`. These transformations will fail during bulk migration for the same reason — no error handling for non-numeric values. A single bad row could abort the entire migration batch.

---

## RCA-2: Date Strings Passed Through Without Parsing or Validation (ANO-002)

### Symptom

Date fields are passed as raw strings from the database through the service layer to the API response. No parsing, validation, or format normalization occurs. The API returns dates in whatever format the database contains, which may be inconsistent.

### Code Trace

**Entry point:** `GET /api/loans/{id}` → `LoanController.getLoan()` → `LoanService.getLoanById()`

```
LoanController.getLoan(id)                      // controller/LoanController.java:29
  └─ LoanService.getLoanById(id)                // service/LoanService.java:58
       └─ toLoanSummary(acct, product)          // service/LoanService.java:63
            └─ dto.setOriginationDate(acct.getOriginationDate())  // line 113
```

**The critical line — `LoanService.java:113`:**

```java
dto.setOriginationDate(acct.getOriginationDate());
```

This is a direct string pass-through. The `LoanSummaryDto.originationDate` field is `String` (not `LocalDate`). The same pattern applies to payment dates:

```
LoanService.toPaymentDto(pmt)                   // service/LoanService.java:134
  └─ dto.setPaymentDate(pmt.getPaymentDate())   // line 138
```

**Entity-to-column mapping:**
- `LegacyLoanAccount.originationDate` ← `CDW_LN_ACCT.LN_ORIG_DT` (VARCHAR(10))
- `LegacyPayment.paymentDate` ← `CDW_PMT_HIST.PMT_DT` (VARCHAR(10))

**Repository sort order — `LegacyPaymentRepository.java:14`:**

```java
List<LegacyPayment> findByLoanAccountNumberOrderByPaymentDateDesc(String loanAccountNumber);
```

This generates SQL: `ORDER BY PMT_DT DESC` — a lexicographic sort on a VARCHAR column. The format `MM/DD/YYYY` sorts by month first (01 < 02 < ... < 12), then day, then year. This means:
- `"12/01/2024"` sorts AFTER `"11/01/2025"` (wrong — December 2024 is before November 2025)
- Cross-year queries will return payments in incorrect chronological order

### Root Cause

The `LoanSummaryDto` and `PaymentDto` declare date fields as `String` rather than `LocalDate`. The service layer performs no date parsing — it copies the raw VARCHAR value directly. This design was presumably intentional (to avoid parsing overhead) but creates multiple downstream issues:

1. **No format validation:** The API may return `"03/15/1978"`, `"1978-03-15"`, or `"15-03-1978"` depending on what's in the database
2. **No chronological sorting:** Repository `ORDER BY` sorts alphabetically, not chronologically
3. **Migration blocker:** The `column_mappings.md` specifies `"Parse MM/DD/YYYY → DATE"` — but there is no parsing logic anywhere in the codebase to validate that the assumed format is actually present

### Impact on API Response

- **Inconsistent date formats:** API consumers cannot reliably parse the date strings without knowing the (undocumented) format convention
- **Wrong sort order:** `GET /api/loans/{id}/payments` returns payments in wrong chronological order for multi-year histories
- **Migration risk:** Bulk migration will fail or produce incorrect dates if any row contains a non-`MM/DD/YYYY` date string

---

## RCA-3: Payment Component Amounts Don't Sum to Total (ANO-003)

### Symptom

Payment records have `PMT_AMT` (total) that does not equal `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. The API returns these inconsistent values without any validation or warning.

### Code Trace

**Entry point:** `GET /api/loans/{loanId}/payments` → `LoanController.getPayments()` → `LoanService.getPaymentsByLoan()`

```
LoanController.getPayments(loanId)              // controller/LoanController.java:34
  └─ LoanService.getPaymentsByLoan(loanId)      // service/LoanService.java:90
       └─ toPaymentDto(pmt)                     // service/LoanService.java:93
            ├─ dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()))        // line 139
            ├─ dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())) // line 140
            ├─ dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()))   // line 141
            ├─ dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()))       // line 142
            └─ dto.setLateFee(parseLegacyAmount(pmt.getLateFee()))                 // line 143
```

**The missing validation — `LoanService.java:134-147`:**

```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    PaymentDto dto = new PaymentDto();
    // ... sets all fields individually ...
    // NO validation that total == principal + interest + escrow + lateFee
    return dto;
}
```

Each amount is parsed independently. No cross-field validation occurs.

**Entity-to-column mapping:**
- `LegacyPayment.totalAmount` ← `CDW_PMT_HIST.PMT_AMT` (VARCHAR(15))
- `LegacyPayment.principalAmount` ← `CDW_PMT_HIST.PMT_PRIN_AMT` (VARCHAR(15))
- `LegacyPayment.interestAmount` ← `CDW_PMT_HIST.PMT_INT_AMT` (VARCHAR(15))
- `LegacyPayment.escrowAmount` ← `CDW_PMT_HIST.PMT_ESCROW_AMT` (VARCHAR(15))
- `LegacyPayment.lateFee` ← `CDW_PMT_HIST.PMT_LATE_FEE` (VARCHAR(15))

**Detailed breakdown of bad records:**

```
PMT-2025120001 (LN-2019-00142, Dec 2025):
  Total:    1,487.02
  Prin:       456.78
  Int:      1,074.69
  Escrow:     355.55
  Late:         0.00
  Sum:      1,887.02  ← exceeds total by $400.00

PMT-2025110001 (LN-2019-00142, Nov 2025):
  Total:    1,487.02
  Prin:       454.97
  Int:      1,076.50
  Escrow:     355.55
  Late:         0.00
  Sum:      1,887.02  ← exceeds total by $400.00

PMT-2025110003 (LN-2018-00089, Nov 2025):
  Total:    1,077.05
  Prin:       295.82
  Int:        781.23
  Escrow:       0.00
  Late:        47.50
  Sum:      1,124.55  ← exceeds total by $47.50 (exactly the late fee)
```

### Root Cause

The payment data has two distinct integrity issues:

1. **LN-2019-00142 payments (PMT-2025120001, PMT-2025110001):** The escrow amount ($355.55) appears to be erroneously added on top of an already-complete payment. The monthly payment for this loan is $1,487.02 (per `CDW_LN_ACCT.LN_PMT_AMT`), and `principal + interest = $1,531.47/$1,531.47` — suggesting the escrow may have been double-counted or applied to a different payment component.

2. **LN-2018-00089 payment (PMT-2025110003):** The total equals `principal + interest` ($1,077.05) but the late fee ($47.50) is not included in the total. This suggests the late fee was assessed separately but the total was not recalculated — or the fee was added after the record was created.

The service layer has no cross-field validation logic. It parses each amount independently and trusts the data warehouse values. Without a CHECK constraint or application-level validation, these inconsistencies flow silently to the API consumer.

### Impact on API Response

- **Financial misrepresentation:** The `GET /api/loans/{loanId}/payments` endpoint returns payment breakdowns that don't add up. A consumer who sums the components gets a different number than the stated total.
- **Reconciliation failure:** Accounting systems that reconcile payment components against totals will flag these records as errors.
- **Regulatory risk:** Inaccurate payment breakdowns on loan statements (principal/interest split) violate TILA (Truth in Lending Act) disclosure requirements.
- **Cascading errors:** If downstream systems use the component amounts to calculate remaining balance, the running balance will diverge from the stated `LN_CURR_BAL`.

---

## Summary

| RCA | Anomaly | Root Cause | Primary Code Location | Failure Mode |
|-----|---------|------------|----------------------|--------------|
| RCA-1 | ANO-001 | No try/catch around `BigDecimal`/`Integer` parsing | `LoanService.java:152-165` | `500 Internal Server Error` for entire endpoint |
| RCA-2 | ANO-002 | Date strings passed through without parsing | `LoanService.java:113,138` | Wrong sort order, inconsistent API formats, migration blocker |
| RCA-3 | ANO-003 | No cross-field validation on payment components | `LoanService.java:134-147` | Silent financial data inconsistency in API responses |
