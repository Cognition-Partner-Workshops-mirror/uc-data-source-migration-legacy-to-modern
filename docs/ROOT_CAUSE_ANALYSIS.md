# Root Cause Analysis — Top 3 Critical Data Anomalies

This document traces the three most critical data anomalies from `DATA_ANOMALY_REPORT.md` through the application code to identify exactly where each anomaly causes a runtime failure or incorrect API response.

---

## RCA #1: Payment Component Totals Do Not Match Sum of Parts

**Anomaly**: In `data-legacy.sql`, records `PMT-2025120001`, `PMT-2025110001`, and `PMT-2025110003` have `PMT_AMT` values that do not equal `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`.

### Code Trace

**1. Data enters through JPA entity `LegacyPayment.java`**

All payment fields are mapped as raw strings from the `CDW_PMT_HIST` table:
```java
// LegacyPayment.java
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

No validation occurs at the entity level.

**2. `LoanService.toPaymentDto()` (line 134–147) converts each field independently**

```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    PaymentDto dto = new PaymentDto();
    // ...
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1487.02
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1074.69
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
    // ...
}
```

Each field is parsed independently via `parseLegacyAmount()` (line 152–155). There is **no cross-field validation** — the method never checks that `totalAmount == principalAmount + interestAmount + escrowAmount + lateFee`.

**3. `PaymentDto` exposes contradictory data to API consumers**

The `PaymentDto` (returned by `GET /api/loans/{loanId}/payments`) contains:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```

A client summing the components gets 1887.02, but `totalAmount` says 1487.02 — a $400 discrepancy.

**4. `column_mappings.md` specifies direct field-by-field migration**

The column mappings document (lines 82–86) maps each payment amount field independently with "Remove commas, parse → decimal" — no validation step is defined. The anomaly would be migrated directly to the modern schema.

### Root Cause

The service layer performs **field-level type conversion** but no **record-level business rule validation**. The `parseLegacyAmount()` method is a pure string-to-BigDecimal converter with no awareness of the semantic relationship between payment fields. There is no validation layer between the repository and the DTO conversion.

### Runtime Impact

- **Incorrect API response**: `GET /api/loans/LN-2019-00142/payments` returns payments with internally contradictory amounts for `PMT-2025120001` and `PMT-2025110001`.
- **No error or warning**: The mismatch is completely silent — no exception, no log entry.
- **Data migration propagation**: The anomaly will be copied verbatim to the modern schema.

---

## RCA #2: SSN Last-4 Field Contains Phone Number Digits

**Anomaly**: In `data-legacy.sql`, every `CDW_LN_ACCT.BORR_SSN_LST4` value matches the last 4 digits of the borrower's phone number, not their SSN.

### Code Trace

**1. Data enters through JPA entity `LegacyLoanAccount.java`**

```java
// LegacyLoanAccount.java (line 29-30)
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;    // "0142" — actually phone suffix
```

The field is loaded without any validation or cross-reference check.

**2. `LoanService.toLoanSummary()` (line 103–118) does NOT use this field**

The `toLoanSummary()` method constructs a `LoanSummaryDto` but only uses:
- `acct.getBorrowerFirstName()` + `acct.getBorrowerLastName()` for the name
- `acct.getProductCode()` for product lookup
- Various amount and date fields

`borrowerSsnLast4` is **not mapped to any DTO field** — it sits unused in the entity. This means the current API does not expose the corrupt data, but the field is still loaded into memory and available for future use.

**3. `column_mappings.md` (line 51) marks this field as dropped**

```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```

The migration plan correctly drops this field. However, this was a design decision to remove denormalization — the mapping document does **not** note that the data is actually incorrect.

**4. No cross-validation between `CDW_LN_ACCT` and `CDW_BORR_MSTR`**

`LoanService` loads borrower and loan account data independently. `getBorrowerById()` (line 72–88) fetches the borrower from `CDW_BORR_MSTR` and loans from `CDW_LN_ACCT`, but never compares the denormalized `BORR_SSN_LST4` against the borrower's actual SSN data (`BORR_SSN_ENCR`).

### Root Cause

The data corruption occurred at the source (the legacy CDW ETL process) — the SSN last-4 extraction logic appears to have been accidentally pointed at the phone number field instead of the encrypted SSN field. The application code has no validation to detect this because:
1. The entity blindly maps the column value.
2. The service layer doesn't use the field (masking the problem).
3. No cross-field or cross-table validation exists.

### Runtime Impact

- **Currently silent**: The API does not expose `borrowerSsnLast4`, so no API consumer sees the wrong data today.
- **Future risk**: Any feature that adds SSN last-4 verification (e.g., borrower authentication, call center verification) would use phone digits as SSN — a **security vulnerability**.
- **Audit/compliance risk**: A PII inventory would catalog this as SSN data, triggering SSN-specific handling requirements for data that is actually phone-derived.

---

## RCA #3: All-VARCHAR Numeric Strings Cause Uncaught NumberFormatException

**Anomaly**: All monetary amounts, rates, scores, and integer fields are stored as `VARCHAR` with embedded comma formatting. The parsing methods in `LoanService` have no error handling for malformed values.

### Code Trace

**1. Entity fields are all `String` type**

Every entity (`LegacyBorrower`, `LegacyLoanAccount`, `LegacyPayment`, `LegacyLoanProduct`) maps numeric columns as `String`:
```java
// LegacyBorrower.java
@Column(name = "BORR_CRDT_SCR")
private String creditScore;          // "745"

@Column(name = "BORR_ANN_INCM")
private String annualIncome;         // "92,500"
```

**2. `LoanService.parseLegacyAmount()` (line 152–155) — no error handling**

```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}
```

The null/blank check is good, but `new BigDecimal(...)` throws `NumberFormatException` for any non-numeric input. Possible problematic inputs from legacy data:
- `"N/A"` or `"NONE"` (sentinel values common in CDW systems)
- `"$285,000"` (dollar sign prefix)
- `"285,,000"` (double comma typo)
- `" "` (whitespace-only — passes `isBlank()` check but `BigDecimal` would fail after comma removal... actually `isBlank()` catches this)

**3. `LoanService.parseLegacyInteger()` (line 162–165) — same problem**

```java
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());
}
```

`Integer.parseInt()` throws `NumberFormatException` for non-numeric strings. This is called for `creditScore` in `toBorrowerDto()` (line 129). A credit score value of `"N/A"` or `"PENDING"` would crash the borrower endpoint.

**4. `LoanService.parseLegacyDecimal()` (line 157–160) — same problem**

```java
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());
}
```

Used for interest rates. A value like `"VARIABLE"` or `"TBD"` would crash.

**5. No global exception handler**

The controllers (`LoanController`, `BorrowerController`) have no `@ExceptionHandler` or `@ControllerAdvice`. An uncaught `NumberFormatException` propagates up the stack and returns an HTTP 500 with a Spring Boot default error page — exposing internal stack trace details.

**6. `column_mappings.md` documents the transformation but not the failure mode**

The mappings document (lines 20, 22, 35, etc.) specifies transformations like "Parse string → integer" and "Remove commas, parse → decimal" but does not address what happens when the string is not parseable.

### Root Cause

The parsing methods implement the **happy-path conversion** only. They handle the two most common edge cases (null and blank) but assume all non-blank values are well-formed numeric strings. In a legacy CDW system where data has been accumulated over years from multiple source systems, malformed numeric values are common. The lack of try-catch blocks around `new BigDecimal()` and `Integer.parseInt()` means a single bad record crashes the entire API endpoint.

### Runtime Impact

- **API crash**: A single malformed numeric value in any record causes `GET /api/loans`, `GET /api/borrowers`, or `GET /api/loans/{id}/payments` to return HTTP 500.
- **Cascading failure**: `getAllLoans()` iterates all loan accounts — one bad record crashes the entire list endpoint, not just that record.
- **No error isolation**: The stream-based processing (`stream().map(...).collect()`) means any exception in the map function terminates the entire stream.
- **No logging**: The failure produces a stack trace but no business-context log entry (which loan, which field, what value).

---

## Summary

| RCA | Anomaly | Where It Breaks | Failure Mode |
|-----|---------|-----------------|--------------|
| #1 | Payment totals ≠ sum of parts | `LoanService.toPaymentDto()` line 134–147 | Silent — contradictory data in API response |
| #2 | SSN last-4 = phone digits | `LegacyLoanAccount.borrowerSsnLast4` | Silent now — future security risk if field is used |
| #3 | VARCHAR numerics with no error handling | `parseLegacyAmount()` line 152, `parseLegacyInteger()` line 162, `parseLegacyDecimal()` line 157 | Crash — `NumberFormatException` → HTTP 500 |

### Common Thread

All three root causes share the same architectural gap: **the service layer performs type conversion but no data validation**. There is no validation layer between the JPA entity (raw legacy data) and the DTO (clean API output). The `LoanService` translation methods assume the legacy data is well-formed and internally consistent — an assumption that does not hold for CDW data.
