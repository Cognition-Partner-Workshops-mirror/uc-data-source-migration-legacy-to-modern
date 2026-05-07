# Root Cause Analysis — Top 3 Critical Data Anomalies

This document traces the three most critical data anomalies through the application code to identify where they cause runtime failures or incorrect API responses.

---

## RCA-1: Payment Component Amounts Do Not Sum to Total

### Anomaly Summary

In `data-legacy.sql`, three payment records have component amounts (principal + interest + escrow + late fee) that do not equal the stated total:

| Payment ID | Total | Component Sum | Discrepancy |
|-----------|-------|---------------|-------------|
| PMT-2025120001 | 1,487.02 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 1,887.02 | +400.00 |
| PMT-2025110003 | 1,077.05 | 1,124.55 | +47.50 |

### Code Trace

**Entry point:** `LoanController.getPayments()` → `LoanService.getPaymentsByLoan()`

```
LoanService.java:90-95
public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
    return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
            .stream()
            .map(this::toPaymentDto)
            .collect(Collectors.toList());
}
```

**Translation method:** `LoanService.toPaymentDto()` (lines 134-147)

Each amount field is independently parsed from the legacy string:
```
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
```

**Root cause:** `toPaymentDto()` performs no cross-field validation. It trusts that the legacy data is internally consistent and blindly converts each field independently. There is no check that `principal + interest + escrow + lateFee == total`.

### Runtime Impact

- **API response:** `GET /api/loans/{loanId}/payments` returns a JSON object where `totalAmount` is 1,487.02 but the visible components sum to 1,887.02.
- **Consumer impact:** Any frontend or downstream service that calculates a running total from components will get a different number than the `totalAmount` field, causing reconciliation failures.
- **Silent corruption:** This does not cause a runtime exception — the data is silently wrong, which is worse than a crash.

### Column Mappings Reference

From `column_mappings.md`, all payment amount fields map from `VARCHAR(15)` → `DECIMAL(10,2)` with "Remove commas, parse → decimal". The mapping specifies no cross-field validation, meaning this anomaly would be carried forward into the modern schema unchanged.

### Fix Location

`LoanService.toPaymentDto()` — add post-parse validation comparing the sum of components to the total. If mismatched, log a warning and either flag the record or adjust the total to match the component sum.

---

## RCA-2: SSN Last-4 Field Contains Phone Number Digits

### Anomaly Summary

In `data-legacy.sql`, every `BORR_SSN_LST4` value in `CDW_LN_ACCT` matches the last 4 digits of the borrower's phone number, not their SSN:

| Borrower | Phone | SSN_LST4 | Phone Last 4 |
|----------|-------|----------|-------------|
| B-10001 | 217-555-0142 | 0142 | 0142 |
| B-10002 | 503-555-0198 | 0198 | 0198 |
| B-10003 | 512-555-0167 | 0167 | 0167 |
| B-10004 | 303-555-0134 | 0134 | 0134 |
| B-10005 | 602-555-0156 | 0156 | 0156 |

### Code Trace

**Entity mapping:** `LegacyLoanAccount.java` (lines 29-30)
```
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```

**Service layer usage:** `LoanService.toLoanSummary()` (lines 103-118) does NOT use `borrowerSsnLast4` in the DTO construction. The `LoanSummaryDto` has no SSN field.

**However:** The field is accessible via `LegacyLoanAccount.getBorrowerSsnLast4()` and could be used by:
1. Any future code that extends the API
2. The data migration process (column_mappings.md marks this as `*(dropped)*`)
3. Direct database queries for identity verification

**Repository layer:** `LegacyLoanAccountRepository.java` has no query method that filters by `borrowerSsnLast4`, so no existing query would return incorrect results based on this field.

### Root Cause

The root cause is upstream — in the legacy ETL that populated the CDW. The data load process likely mapped the wrong source column (phone number) to the `BORR_SSN_LST4` target. Since the schema has no validation constraints (all VARCHAR, no FK, no check constraints), this data corruption went undetected.

### Runtime Impact

- **Current impact:** Minimal — `toLoanSummary()` doesn't expose this field via the API.
- **Migration impact:** Critical — if `column_mappings.md` had not already marked this as `*(dropped)*`, the corrupted phone digits would be migrated as SSN data into the modern `borrowers` table, creating a compliance liability.
- **Compliance risk:** If any reporting or audit process queries `BORR_SSN_LST4` directly from the database, it would return phone data labeled as SSN, violating PII handling requirements.

### Fix Location

Add a validation layer that detects the phone-number correlation and flags `BORR_SSN_LST4` as untrusted. During migration, ensure this field is dropped (as the mapping already specifies) and never used for identity verification.

---

## RCA-3: Uncaught NumberFormatException in Amount Parsing

### Anomaly Summary

All monetary values in the legacy schema are stored as VARCHAR with embedded commas. The `parseLegacyAmount()` method strips commas but has no error handling for unexpected formats.

### Code Trace

**Parser method:** `LoanService.parseLegacyAmount()` (lines 152-155)
```
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}
```

**Call sites** (every amount conversion in the service):
- `toLoanSummary()` line 108: `parseLegacyAmount(acct.getOriginalAmount())`
- `toLoanSummary()` line 109: `parseLegacyAmount(acct.getCurrentBalance())`
- `toLoanSummary()` line 111: `parseLegacyAmount(acct.getMonthlyPayment())`
- `toPaymentDto()` lines 139-143: all five payment amount fields

**Similarly vulnerable:** `parseLegacyDecimal()` (lines 157-160) and `parseLegacyInteger()` (lines 162-165) both parse without try-catch.

**Controller propagation:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()` which calls `toLoanSummary()` for every record in a stream. A single malformed amount in any record causes the entire stream to fail.

```
LoanService.java:48-56
public List<LoanSummaryDto> getAllLoans() {
    Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
            .stream()
            .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
    return loanAccountRepository.findAll().stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
}
```

### Root Cause

`parseLegacyAmount()` only handles two cases: null/blank (returns `BigDecimal.ZERO`) and valid comma-formatted numbers. It does not handle:
- Dollar signs: `"$285,000"` → `NumberFormatException` (the `$` is not stripped)
- Spaces: `" 285,000 "` → works (BigDecimal trims), but `"285, 000"` → `NumberFormatException`
- Currency words: `"285,000 USD"` → `NumberFormatException`
- Negative with parentheses: `"(1,487.02)"` → `NumberFormatException` (accounting format)
- Empty but not blank: values with non-breaking spaces or special whitespace

The same issue affects `parseLegacyInteger()` for credit scores — `"N/A"` or `"---"` would throw.

### Runtime Impact

- **Single record failure = total endpoint failure:** Because `getAllLoans()` uses `stream().map()`, one `NumberFormatException` aborts the entire collection. The API returns HTTP 500 with a stack trace instead of the 4 good records.
- **No error isolation:** There's no try-catch at the record level, so one bad record poisons the response for all records.
- **Cascading failure:** `getBorrowerById()` also calls `toLoanSummary()` for each of a borrower's loans, so a malformed amount in any loan record would crash the borrower detail endpoint too.

### Column Mappings Reference

From `column_mappings.md`:
- `BORR_ANN_INCM` → `annual_income DECIMAL(12,2)`: "Remove commas, parse → decimal"
- `LN_ORIG_AMT` → `original_amount DECIMAL(12,2)`: "Remove commas, parse → decimal"

The mapping acknowledges the transformation is needed but doesn't specify error handling for malformed source data.

### Fix Location

1. Wrap `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` in try-catch blocks
2. Log warnings for malformed values with the record identifier
3. Return safe defaults (`BigDecimal.ZERO` for amounts, `null` for integers)
4. Add record-level error isolation in `getAllLoans()` and `getAllBorrowers()` so one bad record doesn't crash the entire endpoint

---

## Summary of Root Causes

| RCA | Root Cause | Failure Mode | Detection Difficulty |
|-----|-----------|--------------|---------------------|
| RCA-1 | No cross-field validation in `toPaymentDto()` | Silent data corruption in API responses | High — no runtime error, data looks plausible |
| RCA-2 | Upstream ETL mapped wrong source column | Mislabeled PII in database | Medium — requires cross-table correlation analysis |
| RCA-3 | No error handling in `parseLegacyAmount()` | HTTP 500 on any malformed record | Low — immediate crash on bad data, but only for formats not yet encountered |
