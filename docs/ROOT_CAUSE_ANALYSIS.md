# Root Cause Analysis — Top 3 Critical Anomalies

---

## RCA-001: Payment Component Sum Mismatch (ANM-001)

### Anomaly
For loan LN-2019-00142, the sum of payment components (principal + interest + escrow) exceeds the stated total payment amount by exactly $400.00 in both payment records.

### Code Trace

**1. Data ingestion path:**
- `data-legacy.sql` line 27: `PMT-2025120001` is inserted with `PMT_AMT='1,487.02'`, `PMT_PRIN_AMT='456.78'`, `PMT_INT_AMT='1,074.69'`, `PMT_ESCROW_AMT='355.55'`
- Component sum: 456.78 + 1,074.69 + 355.55 = **1,887.02** vs stated total **1,487.02**

**2. Service layer processing (`LoanService.java` lines 134-147):**
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
}
```
Each field is parsed independently. There is **no cross-field validation** — the service trusts all values from the legacy table and passes them through to the API response without checking that components sum to the total.

**3. API response propagation (`LoanController.java` line 33-36):**
```java
@GetMapping("/{loanId}/payments")
public List<PaymentDto> getPayments(@PathVariable String loanId) {
    return loanService.getPaymentsByLoan(loanId);
}
```
The controller passes the DTO directly to the JSON serializer with no validation layer.

**4. Column mapping context (`column_mappings.md` lines 82-86):**
Each payment amount field is mapped independently: `PMT_AMT → total_amount`, `PMT_PRIN_AMT → principal_amount`, etc. The mapping documentation does not define any cross-field invariant or sum-check rule.

### Root Cause
The legacy CDW has no CHECK constraints or triggers to enforce that payment components sum to the total. The data was likely entered or ETL'd from a source system where the interest calculation was performed with a different escrow inclusion rule. The service layer blindly trusts the source data, performing field-by-field conversion without any cross-field integrity checks.

The consistent $400.00 delta suggests a systematic error in the upstream ETL — possibly the interest field includes an escrow impound component that is also separately recorded in the escrow field, resulting in double-counting of ~$400 in escrow-related interest.

### Runtime Failure Mode
- **Incorrect API response:** The `/api/loans/{loanId}/payments` endpoint returns a payment where `totalAmount` (1,487.02) does not equal `principalAmount + interestAmount + escrowAmount` (1,887.02). Any downstream consumer that validates component sums will flag this as corrupt data.
- **Financial miscalculation:** If a consumer uses the components for amortization analysis, they will overstate interest by $400/payment. Over the life of the loan, this compounds to tens of thousands of dollars in misreported interest.

### Fix Location
`LoanService.toPaymentDto()` — add post-mapping validation that checks `total == principal + interest + escrow + lateFee`. If the invariant fails, log a warning and either adjust the total to match components or flag the record.

---

## RCA-002: SSN Last-4 Matches Phone Last-4 (ANM-002)

### Anomaly
All 5 borrowers have `BORR_SSN_LST4` in CDW_LN_ACCT matching the last 4 digits of `BORR_PH_NBR` in CDW_BORR_MSTR, indicating the SSN field was populated from the wrong source column.

### Code Trace

**1. Data source (`data-legacy.sql` lines 20-24):**
```sql
-- B-10001: phone=217-555-0142, SSN_LST4=0142
INSERT INTO CDW_LN_ACCT VALUES ('LN-2019-00142', 'B-10001', 'James', 'Mitchell', '0142', ...);
-- B-10002: phone=503-555-0198, SSN_LST4=0198
INSERT INTO CDW_LN_ACCT VALUES ('LN-2020-00398', 'B-10002', 'Sarah', 'Chen', '0198', ...);
```

**2. Entity mapping (`LegacyLoanAccount.java` lines 29-30):**
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```
The field is mapped but never read by the service layer — `LoanService.toLoanSummary()` does not use `borrowerSsnLast4` in building the DTO.

**3. Column mapping definition (`column_mappings.md` line 51):**
```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```
The mapping document says this field is dropped during migration. However, the field exists in the entity and could be used by other code paths or future features.

### Root Cause
The SSN last-4 was populated by an ETL process that extracted digits from the wrong column. The phone number format `XXX-555-XXXX` has 4 digits at the end, and an ETL script likely used a `RIGHT(phone, 4)` extraction intended for SSN but applied to the phone column instead. Since both fields are VARCHAR with no semantic validation, the error was not caught.

The fact that the `column_mappings.md` explicitly drops this field during migration suggests the team may already be aware that the field is unreliable.

### Runtime Failure Mode
- **No current runtime failure:** The field is mapped in `LegacyLoanAccount` but not used by any service method or DTO. There is no immediate API impact.
- **Migration risk:** If the modern schema migration uses `BORR_SSN_LST4` for any verification step (e.g., matching borrower records between systems), it will match on phone suffixes rather than SSN suffixes, causing incorrect identity linkage.
- **Future feature risk:** Any future feature that adds SSN-based identity verification using this field (e.g., duplicate borrower detection, fraud screening) will be fundamentally broken.

### Fix Location
Add a validation check at the service layer that cross-references `BORR_SSN_LST4` against `BORR_PH_NBR`. If they match, flag the SSN field as suspect and exclude it from any identity verification logic. During migration, derive SSN last-4 from the encrypted SSN field (`BORR_SSN_ENCR`) rather than trusting the denormalized value.

---

## RCA-003: Unhandled NumberFormatException on Malformed Numeric Strings (ANM-003)

### Anomaly
All numeric values in the legacy schema are stored as VARCHAR strings. The service layer parses them without error handling, making every API endpoint vulnerable to a single malformed record crashing the entire response.

### Code Trace

**1. Parsing methods (`LoanService.java` lines 152-165):**
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

**2. Call sites with no error isolation:**

In `getAllLoans()` (line 48-56):
```java
return loanAccountRepository.findAll().stream()
    .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
    .collect(Collectors.toList());
```
The `stream().map()` pipeline has no try-catch. If `toLoanSummary` throws for ANY record, the entire stream fails and the API returns 500.

In `toLoanSummary()` (lines 108-111):
```java
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));   // can throw
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));   // can throw
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));      // can throw
dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));   // can throw
```
Four consecutive parsing calls, each of which can throw `NumberFormatException`.

In `toBorrowerDto()` (line 129):
```java
dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));  // can throw
```
A non-numeric credit score (e.g., "N/A") crashes the borrower endpoint.

**3. Controller layer (`LoanController.java`, `BorrowerController.java`):**
No `@ExceptionHandler` or global exception handler exists. Spring Boot's default error handling will return a generic HTTP 500 with a stack trace in development mode.

### Root Cause
The service layer was written assuming the legacy data always contains well-formed numeric strings. This is a reasonable assumption for the current seed data, but the legacy CDW schema accepts any VARCHAR value. The lack of defensive parsing means the code has zero tolerance for data quality issues — a single bad record in a table of millions would make the entire API endpoint unavailable.

The architecture compounds this: the `findAll().stream().map()` pattern processes all records in a single pipeline with no error boundary. There is no mechanism to skip bad records and return partial results.

### Runtime Failure Mode
1. A CDW load inserts a record with `LN_CURR_BAL = '$271,432.56'` (note the `$` prefix)
2. `GET /api/loans` calls `getAllLoans()` which streams all loan accounts
3. `parseLegacyAmount("$271,432.56")` strips commas → `"$271432.56"` → `new BigDecimal("$271432.56")` → **NumberFormatException**
4. The uncaught exception propagates up through the stream, the service, and the controller
5. Spring returns HTTP 500 for ALL loans, not just the bad record
6. The `/api/loans` endpoint is completely down until the bad record is fixed in the CDW

### Fix Location
1. Wrap `parseLegacyAmount`, `parseLegacyDecimal`, and `parseLegacyInteger` in try-catch blocks that log warnings and return defaults.
2. Add error isolation in the stream pipeline: wrap the `map()` lambda in a try-catch, log the error, and either skip or return a flagged DTO for records that fail parsing.
3. Strip additional non-numeric characters (currency symbols, spaces) before parsing.
