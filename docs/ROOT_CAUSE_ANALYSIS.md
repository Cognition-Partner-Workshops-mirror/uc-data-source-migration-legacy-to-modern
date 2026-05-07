# Root Cause Analysis — Top 3 Critical Data Anomalies

> **Generated:** 2026-05-07
> **Scope:** Tracing anomalies ANO-001, ANO-002, ANO-003 through the service layer, repository layer, and column mappings to identify runtime failure points.

---

## RCA-001: SSN Last-4 Field Contains Phone Number Digits

### Anomaly Recap
`CDW_LN_ACCT.BORR_SSN_LST4` stores the last 4 digits of the borrower's phone number rather than their SSN for all 5 records.

### Code Path Trace

**1. Entity Layer — `LegacyLoanAccount.java:29-30`**
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```
The field is mapped as a plain `String` with no validation. The column name implies SSN data, but no assertion checks its content.

**2. Service Layer — `LoanService.java:103-118`**
The `toLoanSummary()` method does **not** use `borrowerSsnLast4` in the DTO output. The field is loaded into memory by JPA but never surfaced through the current API endpoints. This means the anomaly is **latent** — it does not cause a visible runtime failure today.

**3. Column Mappings — `data/mappings/column_mappings.md:51`**
```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```
The migration plan marks this column as "dropped." However, if any migration validation step cross-checks SSN last-4 from loan accounts against the master borrower table (by decrypting `BORR_SSN_ENCR` and extracting the last 4 digits), **every single record would fail validation** because the values are phone suffixes, not SSN suffixes.

**4. Repository Layer — `LegacyLoanAccountRepository.java`**
No custom queries reference `BORR_SSN_LST4`, so no repository-level breakage occurs.

### Root Cause
The legacy ETL process that populates `CDW_LN_ACCT` extracted digits from the wrong source column. The phone number (`BORR_PH_NBR`) last-4 digits were loaded into `BORR_SSN_LST4` instead of the actual SSN last-4 from `BORR_SSN_ENCR`. Since both fields produce 4-digit strings, no format-level check caught the error.

### Where It Would Cause a Runtime Failure
- **During migration:** A validation step cross-referencing `BORR_SSN_LST4` against decrypted `BORR_SSN_ENCR` would reject 100% of loan account records.
- **If exposed in API:** Any future endpoint that returns SSN last-4 for identity verification would serve phone digits, enabling identity verification bypass.
- **Downstream consumers:** Any system that joined on SSN last-4 + last name for borrower matching would produce zero matches (or worse, false matches against a different borrower whose SSN last-4 happens to equal someone's phone suffix).

### Recommended Code-Level Fix
Add a validation check in the service layer that flags records where `BORR_SSN_LST4` matches the last 4 digits of the borrower's phone number:
```java
String phoneLast4 = borrower.getPhoneNumber().replaceAll("[^0-9]", "");
phoneLast4 = phoneLast4.substring(phoneLast4.length() - 4);
if (phoneLast4.equals(account.getBorrowerSsnLast4())) {
    log.warn("SSN last-4 matches phone suffix for borrower {}", account.getBorrowerId());
}
```

---

## RCA-002: Payment Component Amounts Do Not Sum to Total

### Anomaly Recap
For loan `LN-2019-00142`, both payment records have `principal + interest + escrow + late_fee = $1,887.02` but `total = $1,487.02` — a $400.00 discrepancy.

### Code Path Trace

**1. Entity Layer — `LegacyPayment.java:25-37`**
All five amount fields are stored as `String`:
```java
private String totalAmount;      // PMT_AMT
private String principalAmount;  // PMT_PRIN_AMT
private String interestAmount;   // PMT_INT_AMT
private String escrowAmount;     // PMT_ESCROW_AMT
private String lateFee;          // PMT_LATE_FEE
```
No structural relationship between these fields is enforced at the entity level.

**2. Service Layer — `LoanService.java:134-147`**
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
    ...
}
```
Each field is parsed independently. **There is no check that the components sum to the total.** The incorrect data flows directly into the `PaymentDto` and out through the API at `GET /api/loans/{loanId}/payments`.

**3. Column Mappings — `data/mappings/column_mappings.md:82-86`**
All five fields map to `DECIMAL(10,2)` in the modern schema. The mapping documentation specifies "Remove commas, parse to decimal" but does **not** specify any cross-field validation or sum-check.

**4. API Response Impact — `LoanController.java:33-36`**
```java
@GetMapping("/{loanId}/payments")
public List<PaymentDto> getPayments(@PathVariable String loanId) {
    return loanService.getPaymentsByLoan(loanId);
}
```
The endpoint returns the raw parsed values with no post-processing. An API consumer calling `GET /api/loans/LN-2019-00142/payments` receives:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```
Any consumer that adds up the components will get $1,887.02 — not the $1,487.02 reported as the total. This is a **silent data integrity failure** in every API response for this loan's payments.

### Root Cause
The principal amount appears to have a leading-digit insertion error: expected value ~$56.78 (`1487.02 - 1074.69 - 355.55 = 56.78`) but recorded as `$456.78`. The `4` prefix on `56.78` suggests a data entry or ETL concatenation bug in the legacy system. The consistent $400.00 discrepancy across both months reinforces that this is a systematic error in the principal calculation for this specific loan, not a one-time typo.

### Where It Would Cause a Runtime Failure
- **Financial reporting:** Amortization schedules would show $456.78/month going to principal instead of ~$56.78, dramatically overstating principal paydown.
- **Balance reconciliation:** Current balance computed from payment history would diverge from the stated `LN_CURR_BAL`.
- **Investor reporting:** For securitized loans, misstated principal allocations could constitute a material misstatement.
- **API consumers:** Any client that validates `total == sum(components)` would flag these records as corrupt.

### Recommended Code-Level Fix
Add a post-parse validation in `toPaymentDto()`:
```java
BigDecimal computedTotal = dto.getPrincipalAmount()
    .add(dto.getInterestAmount())
    .add(dto.getEscrowAmount())
    .add(dto.getLateFee());
if (computedTotal.compareTo(dto.getTotalAmount()) != 0) {
    log.warn("Payment {} component sum {} != total {}",
        pmt.getPaymentSequenceNumber(), computedTotal, dto.getTotalAmount());
}
```

---

## RCA-003: No Error Handling on Numeric/Date String Parsing

### Anomaly Recap
`parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` use `new BigDecimal(...)` and `Integer.parseInt(...)` without try-catch, causing unhandled `NumberFormatException` on any non-numeric input.

### Code Path Trace

**1. Parse Methods — `LoanService.java:152-165`**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // throws on "$", "N/A", etc.
}
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // throws on non-numeric
}
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // throws on "N/A", "750+", etc.
}
```
The null/blank check is present, but any other non-numeric content triggers an uncaught exception.

**2. Call Sites in `toLoanSummary()` — `LoanService.java:108-111`**
```java
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
```
These are called inside `getAllLoans()` which iterates **all** loan accounts. A `NumberFormatException` on any single record aborts the entire stream and propagates up through the controller as an HTTP 500.

**3. Call Sites in `toBorrowerDto()` — `LoanService.java:129`**
```java
dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
```
A non-numeric credit score (e.g., `"N/A"`, `"PENDING"`) would crash the entire `GET /api/borrowers` endpoint.

**4. Call Sites in `toPaymentDto()` — `LoanService.java:139-143`**
Six separate `parseLegacyAmount()` calls for payment amounts. Any one failure kills the entire `GET /api/loans/{id}/payments` response.

**5. Controller Layer — `LoanController.java` / `BorrowerController.java`**
Neither controller has exception handling (`@ExceptionHandler` or `@ControllerAdvice`). The raw `NumberFormatException` propagates as a Spring Boot default error response:
```json
{
  "status": 500,
  "error": "Internal Server Error",
  "message": "For input string: \"N/A\""
}
```

**6. Column Mappings — `data/mappings/column_mappings.md`**
The mappings document transformations like "Remove commas, parse to decimal" but do not specify fallback behavior for unparseable values. The mappings assume clean input.

### Root Cause
The service layer was written for the "happy path" where legacy data conforms to expected formats. Legacy CDW systems commonly accumulate data quality issues over years — sentinel values (`"N/A"`, `"TBD"`, `"999"`), currency symbols (`"$285,000"`), overflow markers (`"750+"`), and encoding artifacts. The parse methods handle only null/blank but not the broader set of malformed values that legacy systems produce.

### Where It Would Cause a Runtime Failure
- **Single bad record → full endpoint failure:** `GET /api/loans` returns 500 if any of the ~5 loan records has a malformed amount. As the dataset grows to production scale (thousands of records), the probability of at least one bad value approaches 100%.
- **No partial degradation:** The stream-based processing in `getAllLoans()` provides no mechanism to skip bad records and return the valid ones.
- **Silent failures on dates:** Date fields are passed through as raw strings, so malformed dates don't crash — but they produce incorrect API responses that are harder to detect than a 500 error.
- **Cascading impact:** Since `getBorrowerById()` also calls `toLoanSummary()` for the borrower's loans, a bad loan record also breaks the borrower detail endpoint.

### Recommended Code-Level Fix
Wrap each parse method with proper error handling:
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    try {
        return new BigDecimal(amount.replaceAll("[^0-9.\\-]", ""));
    } catch (NumberFormatException e) {
        log.warn("Unparseable amount '{}', defaulting to ZERO", amount);
        return BigDecimal.ZERO;
    }
}
```
Add a `@ControllerAdvice` for global exception handling as a safety net.
