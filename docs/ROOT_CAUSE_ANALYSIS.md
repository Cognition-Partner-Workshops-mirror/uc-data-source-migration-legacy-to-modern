# Root Cause Analysis — Top 3 Critical Data Anomalies

This document traces the three most critical data anomalies through the application code
to identify where each would cause a runtime failure or incorrect API response.

---

## RCA-1: Payment Component Sum Mismatch (ANO-001)

### Anomaly Summary
`PMT_AMT` (total payment) does not equal `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`
for 3 out of 10 payment records, with discrepancies ranging from $47.50 to $400.00.

### Code Path Trace

**1. Data enters via `data-legacy.sql` → H2 database:**
```sql
-- PMT-2025120001: total=1,487.02 but components sum to 1,887.02
INSERT INTO CDW_PMT_HIST VALUES ('PMT-2025120001', 'LN-2019-00142', '12/15/2025',
  '1,487.02', '456.78', '1,074.69', '355.55', '0.00', 'REG', 'PST', ...);
```
The schema (`schema-legacy.sql`) defines all columns as `VARCHAR` with no constraints or
triggers to validate component sums.

**2. Entity maps columns 1:1 — `LegacyPayment.java`:**
```java
// LegacyPayment.java — all fields are raw strings, no validation
@Column(name = "PMT_AMT")
private String totalAmount;       // "1,487.02"

@Column(name = "PMT_PRIN_AMT")
private String principalAmount;   // "456.78"

@Column(name = "PMT_INT_AMT")
private String interestAmount;    // "1,074.69"

@Column(name = "PMT_ESCROW_AMT")
private String escrowAmount;      // "355.55"

@Column(name = "PMT_LATE_FEE")
private String lateFee;           // "0.00"
```
No validation occurs at the entity level.

**3. Service layer parses and maps — `LoanService.java:134-147`:**
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    PaymentDto dto = new PaymentDto();
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1487.02
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1074.69
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
    // NO CHECK: totalAmount vs sum of components
    return dto;
}
```
Each component is parsed independently. There is zero cross-field validation.

**4. API returns incorrect data — `LoanController.java:33-36`:**
```java
@GetMapping("/{loanId}/payments")
public List<PaymentDto> getPayments(@PathVariable String loanId) {
    return loanService.getPaymentsByLoan(loanId);
}
```
The controller returns the DTO list directly with no post-processing.

### Root Cause
The legacy CDW system stored inconsistent payment breakdowns. The service layer performs
column-by-column parsing but has **no cross-field integrity check** to verify that
`totalAmount == principalAmount + interestAmount + escrowAmount + lateFee`.

### Where Failure Manifests
- **API endpoint:** `GET /api/loans/LN-2019-00142/payments`
- **Failure type:** Silent data corruption — API returns `totalAmount: 1487.02` alongside
  components that sum to `1887.02`. No error, no warning.
- **Impact on column_mappings.md:** The mapping `PMT_AMT → total_amount (DECIMAL)` will
  carry the wrong value into the modern schema, permanently encoding the data error.

---

## RCA-2: Uncaught NumberFormatException on Malformed Numeric Strings (ANO-002)

### Anomaly Summary
All numeric fields (amounts, rates, scores) are stored as `VARCHAR` and parsed via
`BigDecimal`/`Integer.parseInt` with no exception handling. Malformed input crashes the API.

### Code Path Trace

**1. Schema allows any string in numeric columns — `schema-legacy.sql`:**
```sql
BORR_CRDT_SCR   VARCHAR(5),    -- credit score as string
BORR_ANN_INCM   VARCHAR(15),   -- annual income as string with commas
LN_ORIG_AMT     VARCHAR(15),   -- original amount as string
LN_INT_RT       VARCHAR(8),    -- interest rate as string "5.250"
```
No `CHECK` constraints. Any string value is accepted.

**2. Parsing methods in `LoanService.java:152-165` have no error handling:**
```java
// Line 152-155: parseLegacyAmount — no try-catch
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
    // FAILS on: "$285,000", "N/A", "285 000", "285,000.00 USD"
}

// Line 157-160: parseLegacyDecimal — no try-catch
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());
    // FAILS on: "5.250%", "N/A", "variable"
}

// Line 162-165: parseLegacyInteger — no try-catch
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());
    // FAILS on: "N/A", "780+", "unknown", "7.5"
}
```

**3. Called from DTO mapping methods with no protection:**
```java
// Line 108-110: toLoanSummary calls multiple parsers per loan
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));

// Line 129: toBorrowerDto parses credit score
dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
```

**4. Blast radius — `getAllLoans()` and `getAllBorrowers()` use streams:**
```java
// Line 53-55: getAllLoans maps ALL records — one failure kills the entire response
return loanAccountRepository.findAll().stream()
        .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
        .collect(Collectors.toList());
```
Because `findAll()` returns all records and maps them in a stream, a single malformed
record throws a `NumberFormatException` that propagates uncaught, resulting in an
HTTP 500 for the entire endpoint.

### Root Cause
The service layer trusts that all `VARCHAR` values in the legacy CDW are well-formed
numbers. There are **null/blank checks** but **no format validation or try-catch blocks**
around the `BigDecimal` and `Integer.parseInt` calls.

### Where Failure Manifests
- **API endpoints:** All — `GET /api/loans`, `GET /api/loans/{id}`, `GET /api/borrowers`, `GET /api/borrowers/{id}`, `GET /api/loans/{id}/payments`
- **Failure type:** Unhandled `NumberFormatException` → HTTP 500 Internal Server Error
- **Stack trace:** `LoanService.parseLegacyAmount()` → `BigDecimal.<init>()` → `NumberFormatException`
- **Impact on column_mappings.md:** The transformation "Remove commas, parse → decimal"
  documented in column_mappings.md is incomplete — it only accounts for commas, not
  currency symbols, whitespace, or non-numeric characters.

---

## RCA-3: Delinquent Loan Reported as Active (ANO-003)

### Anomaly Summary
Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'`, meaning
the API reports it as "Active" while it is actually delinquent.

### Code Path Trace

**1. Seed data has conflicting status — `data-legacy.sql`:**
```sql
-- LN-2018-00089: 15 delinquency days but Active status
INSERT INTO CDW_LN_ACCT VALUES ('LN-2018-00089', 'B-10003', 'Michael', 'Torres',
  '0167', 'ARM51', '195,000', '178,234.12', '5.250', '360', '1,077.05',
  '07/01/2018', '07/01/2048', '08/01/2018', '01/01/2026',
  'ACT',   -- Status: Active
  '15',    -- Delinquency: 15 days!
  ...);
```

**2. Status expansion in `LoanService.java:167-176` only translates the code:**
```java
private String expandStatusCode(String code) {
    if (code == null) return "Unknown";
    return switch (code) {
        case "ACT" -> "Active";      // LN-2018-00089 hits this case
        case "CLO" -> "Closed";
        case "DFT" -> "Default";
        case "FRB" -> "Forbearance";
        default -> code;
    };
}
```
The method only performs a 1:1 code-to-label translation. It does **not** cross-reference
`LN_DLQ_DAYS` to validate that the status is consistent with the delinquency state.

**3. Delinquency days are not included in the DTO at all:**
```java
// toLoanSummary (line 103-118) maps these fields:
dto.setStatus(expandStatusCode(acct.getStatusCode()));  // "Active"
// delinquencyDays is NEVER mapped to the DTO
// acct.getDelinquencyDays() is available but ignored
```
The `LoanSummaryDto` does not have a `delinquencyDays` field, so even though the entity
reads the value from the database, it is silently discarded.

**4. Corroborating evidence from payment history:**
```sql
-- PMT-2025110003 for this loan was received 17 days late (11/18 vs 11/01)
-- and has a $47.50 late fee, confirming the delinquency
INSERT INTO CDW_PMT_HIST VALUES ('PMT-2025110003', 'LN-2018-00089', '11/01/2025',
  '1,077.05', '295.82', '781.23', '0.00', '47.50', 'REG', 'PST',
  '11/18/2025', ...);
```
The payment history confirms the borrower is paying late, but the loan status
does not reflect this.

### Root Cause
The legacy CDW system allows `LN_STAT_CD` and `LN_DLQ_DAYS` to be independently set
with no business rule enforcement. The service layer's `expandStatusCode()` performs a
simple code-to-label mapping with **no cross-field validation** against delinquency days.
Additionally, `LoanSummaryDto` omits `delinquencyDays` entirely, so the delinquency
information is lost even though the entity reads it.

### Where Failure Manifests
- **API endpoint:** `GET /api/loans` and `GET /api/loans/LN-2018-00089`
- **Failure type:** Silent incorrect data — API returns `"status": "Active"` for a
  delinquent loan
- **Impact:** Risk teams, collections workflows, and regulatory reports under-count
  delinquencies. The column_mappings.md transformation `LN_STAT_CD → status (Expand: ACT→ACTIVE)`
  will carry the incorrect status into the modern schema without correction.

---

## Summary of Root Causes

| RCA | Anomaly | Root Cause Category | Code Location | Fix Priority |
|-----|---------|---------------------|---------------|--------------|
| RCA-1 | Payment sum mismatch | Missing cross-field validation | `LoanService.toPaymentDto()` (line 134) | P0 — Financial data integrity |
| RCA-2 | NumberFormatException | Missing error handling on type coercion | `LoanService.parseLegacy*()` (lines 152-165) | P0 — Service availability |
| RCA-3 | Delinquent = Active | Missing business rule validation + incomplete DTO mapping | `LoanService.expandStatusCode()` (line 167), `toLoanSummary()` (line 103) | P1 — Regulatory compliance |
