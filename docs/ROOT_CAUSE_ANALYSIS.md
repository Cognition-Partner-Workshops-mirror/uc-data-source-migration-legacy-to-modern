# Root Cause Analysis — Top 3 Critical Data Anomalies

> **Generated:** 2026-05-08
> **Scope:** Runtime failure paths traced through `LoanService.java`, repository layer, and `data/mappings/column_mappings.md`

---

## RCA-001: Payment Component Sum Mismatch (ANM-001)

### Anomaly Recap
In `CDW_PMT_HIST`, the sum of `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` does not equal `PMT_AMT` for 3 out of 10 payment records (30% error rate).

### Code Path Trace

**1. Data enters via `LegacyPaymentRepository`**
- `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` loads all payment records for a loan as `LegacyPayment` entities.
- All amount fields are loaded as raw `String` values — no validation occurs at the JPA layer.

**2. Service layer converts in `LoanService.toPaymentDto()` (line 134–147)**
```java
// LoanService.java:134-147
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    PaymentDto dto = new PaymentDto();
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // "1,487.02" → 1487.02
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // "456.78"   → 456.78
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // "1,074.69" → 1074.69
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // "355.55"   → 355.55
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // "0.00"     → 0.00
    // ... no sum validation performed
}
```
Each component is independently parsed and placed into the DTO. **No cross-field validation** verifies that the components sum to the total.

**3. API response via `LoanController.getPayments()` (line 33–36)**
```java
// LoanController.java:33-36
@GetMapping("/{loanId}/payments")
public List<PaymentDto> getPayments(@PathVariable String loanId) {
    return loanService.getPaymentsByLoan(loanId);
}
```
The controller returns the DTO list directly — the inconsistent amounts reach the API consumer.

**4. Impact on column mapping / migration**
Per `column_mappings.md`, each payment amount maps independently:
- `PMT_AMT` → `total_amount` (DECIMAL)
- `PMT_PRIN_AMT` → `principal_amount` (DECIMAL)
- etc.

The mappings document **does not specify** a sum-validation step. If these records are migrated as-is, the modern schema will contain the same inconsistencies, now with proper DECIMAL types that make the discrepancy harder to dismiss as a "legacy string issue."

### Root Cause
The legacy ETL or data entry process that populates `CDW_PMT_HIST` does not enforce an accounting identity constraint (`total = principal + interest + escrow + late_fee`). The application's service layer parses each field independently and has no cross-field validation. The column mappings specify per-field transformations but no integrity checks.

### Runtime Failure Mode
- **No crash** — the data flows through silently.
- **Incorrect API response** — consumers that sum the component amounts will get a different total than the `totalAmount` field, leading to reconciliation failures in downstream accounting systems.
- **Financial reporting errors** — any aggregation on principal vs. interest breakdowns will be wrong.

### Recommended Fix Location
Add a `validatePaymentAmounts()` method in the service layer (or a new `LegacyDataValidator` class) that is called within `toPaymentDto()`. If the sum deviates from the total by more than a configurable tolerance (e.g., $0.01), log a warning and flag the record.

---

## RCA-002: SSN Last-4 Populated from Phone Number (ANM-002)

### Anomaly Recap
All 5 records in `CDW_LN_ACCT` have `BORR_SSN_LST4` values that match the last 4 digits of the borrower's phone number in `CDW_BORR_MSTR`, not their SSN.

### Code Path Trace

**1. Data enters via `LegacyLoanAccountRepository`**
- `LegacyLoanAccountRepository.findAll()` and `findByBorrowerId()` load `LegacyLoanAccount` entities including the `borrowerSsnLast4` field.
- The field is loaded as a plain `String` — no validation against the borrower master.

**2. Service layer in `LoanService.toLoanSummary()` (line 103–118)**
```java
// LoanService.java:103-118
private LoanSummaryDto toLoanSummary(LegacyLoanAccount acct, LegacyLoanProduct product) {
    LoanSummaryDto dto = new LoanSummaryDto();
    dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
    // ... BORR_SSN_LST4 is NOT used in the DTO, but IS present in the entity
}
```
The current `LoanSummaryDto` does not expose SSN last-4 in the API response. However, the field **is loaded into the entity** and is available for any future code that references `acct.getBorrowerSsnLast4()`.

**3. Column mapping migration path**
Per `column_mappings.md` (line 51):
```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```
The mapping correctly marks this field as "dropped" during migration. However, if any migration validation step or audit process uses `BORR_SSN_LST4` for identity verification during the migration, it will be checking phone digits — not SSN digits.

**4. Cross-table verification gap**
The `LoanService.getBorrowerById()` method (line 72–88) loads borrower data from `CDW_BORR_MSTR` and loan data from `CDW_LN_ACCT` separately. There is no cross-reference check that compares the denormalized fields in the loan record against the master borrower record.

### Root Cause
The legacy data warehouse ETL process that populates `CDW_LN_ACCT.BORR_SSN_LST4` appears to have a column mapping error — it sources from `BORR_PH_NBR` (phone number) instead of `BORR_SSN_ENCR` (encrypted SSN). Since the schema has no constraints and the field is a generic `VARCHAR(4)`, the database accepted the wrong data silently. The 100% error rate (all 5 records affected) confirms this is a systematic ETL bug, not sporadic data entry error.

### Runtime Failure Mode
- **No crash** — the field is loaded but not currently exposed in the API.
- **Silent data corruption** — if any code path uses `getBorrowerSsnLast4()` for identity verification, it will use the wrong value.
- **Migration risk** — although the column mappings mark this field as "dropped," any pre-migration data quality report or audit that checks SSN last-4 consistency will flag ALL records.

### Recommended Fix Location
Add a validation in the service layer that cross-references denormalized fields against the borrower master. Specifically, flag `BORR_SSN_LST4` values that match the phone number pattern. During migration, do not carry this field forward; derive it from the decrypted SSN source if needed.

---

## RCA-003: Numeric String Parsing Without Error Handling (ANM-003)

### Anomaly Recap
All numeric fields across all 4 legacy tables are `VARCHAR`. The service layer parses them with `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()`, none of which handle malformed input beyond null/blank checks.

### Code Path Trace

**1. Parsing methods in `LoanService.java` (lines 152–165)**

```java
// LoanService.java:152-155
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
    // No try-catch — throws NumberFormatException on "$285,000" or "N/A"
}

// LoanService.java:157-160
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());
    // No try-catch — throws NumberFormatException on "4.750%"
}

// LoanService.java:162-165
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());
    // No try-catch — throws NumberFormatException on "N/A"
}
```

**2. Call sites where failure propagates**

| Method | Field Parsed | Parser Used | Failure Effect |
|--------|-------------|-------------|----------------|
| `toLoanSummary()` line 108 | `acct.getOriginalAmount()` | `parseLegacyAmount` | Crashes `GET /api/loans` |
| `toLoanSummary()` line 109 | `acct.getCurrentBalance()` | `parseLegacyAmount` | Crashes `GET /api/loans` |
| `toLoanSummary()` line 110 | `acct.getInterestRate()` | `parseLegacyDecimal` | Crashes `GET /api/loans` |
| `toBorrowerDto()` line 129 | `borrower.getCreditScore()` | `parseLegacyInteger` | Crashes `GET /api/borrowers` |
| `toPaymentDto()` line 139 | `pmt.getTotalAmount()` | `parseLegacyAmount` | Crashes `GET /api/loans/{id}/payments` |

**3. Error propagation**
The controllers have no exception handlers. A `NumberFormatException` from any parsing method will propagate up through the Spring MVC stack and return a raw 500 Internal Server Error with a stack trace (in dev mode) or an empty error body (in prod mode).

**4. Column mapping confirms the risk**
`column_mappings.md` documents 20+ fields requiring "Remove commas, parse → decimal" or "Parse string → integer" transformations. Each of these is a potential failure point if the legacy data contains any non-numeric value.

### Root Cause
The service layer assumes all VARCHAR numeric fields contain well-formed values. The legacy schema's use of VARCHAR for everything provides no type-safety guarantee at the database level. The parsing methods check for null/blank but do not catch `NumberFormatException`, `ArithmeticException`, or other parsing failures. There is no input sanitization (stripping `$`, `%`, currency codes) before parsing.

### Runtime Failure Mode
- **Hard crash** — a single malformed numeric value in ANY record causes the ENTIRE list endpoint to fail with HTTP 500.
- **No graceful degradation** — the service cannot skip the bad record and return the valid ones.
- **No observability** — the exception is not caught or logged with context about which field/record caused the failure.

### Recommended Fix Location
1. Create a `LegacyDataValidator` utility class with safe parsing methods that wrap `BigDecimal`/`Integer` construction in try-catch blocks.
2. Return a fallback value (e.g., `BigDecimal.ZERO`, `null`) on parse failure and log the field name, raw value, and record ID.
3. Add input sanitization: strip `$`, `%`, whitespace, and other common non-numeric characters before parsing.
4. Add range validation after successful parsing (credit score 300–850, interest rate 0–100, amounts ≥ 0).
5. Integrate the validator into `LoanService` to replace the existing unprotected parsing methods.
