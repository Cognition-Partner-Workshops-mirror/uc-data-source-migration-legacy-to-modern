# Root Cause Analysis — Top 3 Critical Anomalies

## RCA #1: Payment Component Sum Mismatch

### Anomaly
Payment records `PMT-2025120001`, `PMT-2025110001`, and `PMT-2025110003` have component
amounts (principal + interest + escrow + late fee) that do not sum to the stated total.

### Code Path Trace

**Entry point:** `LoanController.getPayments()` → `LoanService.getPaymentsByLoan()`

```
LoanService.java:90-95
    paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
        .stream()
        .map(this::toPaymentDto)
        .collect(Collectors.toList());
```

**Translation:** `LoanService.toPaymentDto()` (lines 134-147)

```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // "1,487.02"
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // "456.78"
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // "1,074.69"
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // "355.55"
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // "0.00"
```

Each field is parsed independently with no cross-validation.

**Mapping reference:** `column_mappings.md` lines 82-86 confirm that each component maps to
a separate `DECIMAL(10,2)` column in the modern schema — the modern schema inherits the
inconsistency if not caught.

### Root Cause
The `toPaymentDto()` method performs blind field-by-field translation without any
**invariant check**. The business rule `total = principal + interest + escrow + late_fee`
is never asserted. The legacy CDW likely has an ETL bug in the upstream feed that populates
escrow amounts incorrectly for loan `LN-2019-00142` (both its payment records have the same
+$400 discrepancy, suggesting a systematic escrow calculation error).

For `PMT-2025110003`, the late fee of $47.50 was recorded but the total was not adjusted to
include it — indicating the late fee was added retroactively without recalculating the total.

### Runtime Failure Mode
- **API response**: Returns inconsistent financial data — a consumer summing the components
  will get a different total than the `totalAmount` field states
- **No exception thrown**: The code silently propagates the inconsistency
- **Migration impact**: Modern schema will store the broken values permanently unless
  validation catches them at ingestion

### Fix Location
`LoanService.toPaymentDto()` — add sum validation after parsing all components.

---

## RCA #2: SSN Last-4 Contains Phone Number Digits

### Anomaly
All 5 loan account records have `BORR_SSN_LST4` populated with the last 4 digits of the
borrower's phone number instead of their SSN.

### Code Path Trace

**Entry point:** `LoanController.getLoan()` → `LoanService.getLoanById()`

```
LoanService.java:103-118 (toLoanSummary)
    dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
```

The `BORR_SSN_LST4` field is mapped in the entity (`LegacyLoanAccount.java:29-30`):
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```

**Currently unused in service layer**: The `toLoanSummary()` method does NOT expose
`borrowerSsnLast4` in the DTO. However, the field is:
1. Present in the entity and loaded on every query
2. Available via `getBorrowerSsnLast4()` for any future consumer
3. Referenced in `column_mappings.md` line 51 as "dropped" in modern schema

**Mapping reference:** `column_mappings.md` line 51 marks this as `*(dropped)*` — the
migration plan correctly identifies this as denormalized data to remove.

### Root Cause
The legacy ETL process that populates `CDW_LN_ACCT` has a **column mapping error** in its
source extraction. The feed likely reads from a flat file or mainframe extract where the
phone number field is adjacent to the SSN field, and the extraction script reads the wrong
positional offset. This is a classic fixed-width file parsing bug in legacy COBOL/mainframe
ETL pipelines.

Evidence: 100% of records are affected identically (phone last-4 in SSN field), ruling out
random corruption — this is a systematic mapping error.

### Runtime Failure Mode
- **Current code**: No runtime failure because the field is not used in DTOs
- **Future risk**: If any code uses `getBorrowerSsnLast4()` for identity verification,
  it will produce **false negatives** (SSN won't match) or **false positives** (phone digits
  could coincidentally match another borrower's SSN last-4)
- **Compliance risk**: If this field is exposed in any API or log, it's misrepresented as
  SSN data — a potential GLBA/PII classification error

### Fix Location
- Mark `borrowerSsnLast4` as untrusted in entity documentation
- Add validation that flags this field as unreliable
- Service layer should never use this field for identity purposes

---

## RCA #3: Numeric String Parsing Without Error Handling

### Anomaly
All monetary amounts, rates, scores, and counts are stored as VARCHAR with commas. The
parsing methods (`parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`) have no
try-catch — any malformed value causes an unhandled `NumberFormatException` that crashes
the entire API request.

### Code Path Trace

**Entry point:** Any controller method → `LoanService.getAllLoans()`, `getLoanById()`, etc.

**Parsing methods** (`LoanService.java:152-165`):

```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // THROWS if non-numeric chars remain
}

private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // THROWS on any non-numeric input
}

private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // THROWS on non-integer input
}
```

**Call sites (all paths to failure):**
- `toLoanSummary()` calls `parseLegacyAmount()` 3 times and `parseLegacyDecimal()` 1 time
- `toBorrowerDto()` calls `parseLegacyInteger()` for credit score
- `toPaymentDto()` calls `parseLegacyAmount()` 5 times

**Mapping reference:** `column_mappings.md` lines 20-22 document the expected
transformations: "Remove commas, parse → decimal" and "Parse string → integer". But the
actual code only handles the comma case — it does not handle:
- Dollar signs (`$285,000`)
- Spaces (`285, 000`)
- Percentage signs (`82.5%`)
- European decimal format (`1.487,02`)
- Text values (`N/A`, `PENDING`, `TBD`)

### Root Cause
The parsing implementation assumes a single, consistent format across all legacy data. The
legacy DW stores VARCHAR with no CHECK constraints or triggers enforcing format consistency.
Over time, different source systems feeding into the CDW use different number formatting
conventions. The service layer has a **brittle parsing assumption** with no defensive coding.

### Runtime Failure Mode
- **Single bad record kills entire request**: `getAllLoans()` iterates all loan accounts
  in a stream — if any one record has `LN_CURR_BAL = '$271,432.56'` or `LN_CURR_BAL = 'N/A'`,
  the entire stream mapping fails with an uncaught `NumberFormatException`
- **No partial results**: The exception propagates up, returning HTTP 500 to the client
  with no indication of which record caused the failure
- **No logging**: The exception is not caught or logged — debugging requires reproducing
  the issue with breakpoints

### Fix Location
- `LoanService.parseLegacyAmount()` — wrap in try-catch, log malformed values, return
  fallback default
- `LoanService.parseLegacyDecimal()` — same pattern
- `LoanService.parseLegacyInteger()` — same pattern
- Add input sanitization (strip `$`, `%`, spaces) before parsing
- Consider a `DataValidationService` class to centralize validation logic

---

## Cross-Cutting Observations

| Factor | Impact |
|--------|--------|
| No global exception handler | Parsing failures return raw 500 errors with stack traces |
| No validation annotations on entities | JPA loads any garbage from the database without complaint |
| Stream-based processing | One bad record in a `findAll()` result kills the entire response |
| No circuit breaker / fallback | Service has no degraded mode — it's all-or-nothing |

## Recommended Architecture Change

Introduce a `LegacyDataValidator` service class that:
1. Validates each entity after retrieval from the repository
2. Applies type coercion with try-catch and fallback defaults
3. Logs data quality issues as structured warnings (not exceptions)
4. Flags records with anomalies so API consumers can filter them
5. Provides cross-field validation (payment sum check, status consistency)
