# Root Cause Analysis — Top 3 Critical Data Anomalies

> Traces each anomaly through the codebase to identify where it causes runtime failures or incorrect API responses.

---

## RCA-1: Financial Amounts as Comma-Formatted Strings (ANM-002)

### Anomaly

All financial fields across four legacy tables are stored as `VARCHAR` with embedded commas (e.g., `'285,000'`, `'1,487.02'`, `'92,500'`). This affects 13+ columns spanning borrower income, loan balances, payment breakdowns, and product limits.

### Code Path Trace

1. **Entity Layer** — `LegacyLoanAccount.java`, `LegacyBorrower.java`, `LegacyPayment.java`, `LegacyLoanProduct.java`
   - All financial fields are mapped as `String` (e.g., `LegacyLoanAccount.originalAmount`, `LegacyBorrower.annualIncome`).
   - JPA loads the raw VARCHAR value with no transformation.

2. **Service Layer** — `LoanService.java:152-155`
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   - The `replace(",", "")` handles the known comma format.
   - **Failure mode 1:** If a value contains `$` (e.g., `'$285,000'`), `%`, spaces, or other locale-specific characters, `new BigDecimal(...)` throws `NumberFormatException`. This exception is **unhandled** — it propagates up through the controller and returns a 500 Internal Server Error.
   - **Failure mode 2:** An empty string `''` passes the `isBlank()` check as false in some edge cases with whitespace, but `amount.replace(",", "")` on a whitespace-only string still yields a non-numeric string.
   - **Failure mode 3:** The method returns `BigDecimal.ZERO` for null/blank amounts. This is semantically wrong — a missing loan balance of $0 is very different from an unknown balance. Downstream consumers cannot distinguish "zero balance" from "missing data."

3. **Controller Layer** — `LoanController.java:24-26`
   ```java
   @GetMapping
   public List<LoanSummaryDto> getAllLoans() {
       return loanService.getAllLoans();
   }
   ```
   - No exception handling. A single malformed amount in any record crashes the entire `/api/loans` endpoint.

4. **Column Mappings** — `column_mappings.md` lines 22, 53-57, 82-86
   - The mapping document specifies "Remove commas, parse -> decimal" for all amount fields, but the current implementation only strips commas. No validation, no range check, no error handling beyond null/blank.

### Runtime Failure Scenario

A legacy ETL job inserts a record with `LN_ORIG_AMT = '$285,000'` (dollar sign included) or `LN_ORIG_AMT = '285 000'` (space as thousands separator). The next call to `GET /api/loans` throws:

```
java.lang.NumberFormatException: Character $ is neither a decimal digit number, decimal point, nor "e" notation exponential mark.
```

The entire loan listing API returns HTTP 500. All five loans become inaccessible.

### Root Cause

The `parseLegacyAmount()` method assumes the only non-numeric character in amount strings is a comma. There is no try-catch, no input sanitization beyond comma removal, and no logging. The null-to-zero fallback masks missing data.

### Recommended Fix

Wrap parsing in try-catch, strip all non-numeric characters (except `.` and `-`), validate the result is positive (for amounts), log warnings for any value that required sanitization, and return `null` instead of `BigDecimal.ZERO` for genuinely missing values.

---

## RCA-2: Date Strings Passed Through Without Parsing (ANM-003)

### Anomaly

All 16+ date columns across all four tables are stored as `VARCHAR(10)` in `MM/DD/YYYY` format. The service layer does not parse them to `LocalDate` — they are passed through as raw strings.

### Code Path Trace

1. **Entity Layer** — `LegacyLoanAccount.java:50-51`
   ```java
   @Column(name = "LN_ORIG_DT")
   private String originationDate;
   ```
   - All date fields are `String`. No `@Temporal` annotation, no converter.

2. **Service Layer** — `LoanService.java:113`
   ```java
   dto.setOriginationDate(acct.getOriginationDate());
   ```
   - The raw string `'02/15/2019'` is copied directly to the DTO. No parsing, no format validation, no conversion.

3. **DTO Layer** — `LoanSummaryDto.java:18`
   ```java
   private String originationDate;
   ```
   - The DTO declares `originationDate` as `String`, not `LocalDate`. This means the API response contains `"originationDate": "02/15/2019"` — a US-locale date string, not ISO-8601.

4. **Payment DTO** — `PaymentDto.java:12`
   ```java
   private String paymentDate;
   ```
   - Same issue: `LoanService.toPaymentDto()` at line 138 copies `pmt.getPaymentDate()` as a raw string.

5. **Column Mappings** — `column_mappings.md` lines 12, 23-24, 58-61, 81, 89-92
   - The mapping document specifies "Parse MM/DD/YYYY -> DATE" or "Parse MM/DD/YYYY -> timestamp", but the current code does neither.

### Runtime Failure Scenario

**Scenario A (Silent corruption):** A legacy record contains `BORR_DOB_DT = '15/03/1978'` (DD/MM/YYYY instead of MM/DD/YYYY). The service passes it through unchanged. An API consumer interprets it as March 15 instead of the intended date, or their date parser fails.

**Scenario B (Sorting failure):** A consumer tries to sort loans by origination date. String sorting produces `02/15/2019, 03/01/2017, 04/01/2020, 07/01/2018, 10/01/2021` — chronologically incorrect. The legacy `findByLoanAccountNumberOrderByPaymentDateDesc` repository method does string-based ordering, which is incorrect for `MM/DD/YYYY` format (e.g., `12/01/2025` sorts before `11/01/2025` alphabetically but after it chronologically... actually `12` > `11` so it works for month, but `01/15/2026` would sort before `12/01/2025`).

**Scenario C (Missing validation):** A null or empty date string in a required field (e.g., origination date) passes through silently, producing `"originationDate": null` in the API with no warning.

### Root Cause

The service layer was designed as a translation layer (per the class Javadoc) but translation of dates was never implemented. All date fields remain as raw legacy strings. The DTOs use `String` types for dates instead of `LocalDate`, which prevents the compiler from enforcing proper handling.

### Recommended Fix

Parse all date strings to `LocalDate` using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Add try-catch with fallback patterns for alternate formats. Change DTO date fields to `LocalDate` so Jackson serializes them as ISO-8601. Log warnings for unparseable dates.

---

## RCA-3: Payment Component Totals Do Not Reconcile (ANM-010)

### Anomaly

In `CDW_PMT_HIST`, the sum of payment components (`PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`) does not equal `PMT_AMT` (total payment amount) for multiple records.

### Detailed Verification

| Payment ID | Total | Principal | Interest | Escrow | Late Fee | Component Sum | Delta |
|---|---|---|---|---|---|---|---|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | **-400.00** |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | **-400.00** |
| PMT-2025120002 | 2,924.18 | 1,842.56 | 815.50 | 266.12 | 0.00 | 2,924.18 | 0.00 |
| PMT-2025110002 | 2,924.18 | 1,837.76 | 820.30 | 266.12 | 0.00 | 2,924.18 | 0.00 |
| PMT-2025120003 | 1,077.05 | 297.12 | 779.93 | 0.00 | 0.00 | 1,077.05 | 0.00 |
| PMT-2025110003 | 1,077.05 | 295.82 | 781.23 | 0.00 | 47.50 | 1,124.55 | **-47.50** |
| PMT-2025120004 | 2,468.35 | 857.23 | 1,611.12 | 0.00 | 0.00 | 2,468.35 | 0.00 |
| PMT-2025110004 | 2,468.35 | 854.46 | 1,613.89 | 0.00 | 0.00 | 2,468.35 | 0.00 |
| PMT-2025120005 | 811.61 | 306.45 | 505.16 | 0.00 | 0.00 | 811.61 | 0.00 |
| PMT-2025110005 | 811.61 | 305.37 | 506.24 | 0.00 | 0.00 | 811.61 | 0.00 |

**3 out of 10 payment records have mismatched totals.** The pattern suggests:
- Records for loan `LN-2019-00142` (James Mitchell) are consistently off by $400.00 — likely the escrow amount is being double-counted or the total excludes escrow.
- Record `PMT-2025110003` for loan `LN-2018-00089` (Michael Torres) is off by $47.50 — exactly the late fee amount, suggesting late fees may not be included in the total.

### Code Path Trace

1. **Service Layer** — `LoanService.java:134-147`
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
   - Each component is parsed independently. **No reconciliation check** is performed. The mismatched totals are served directly to API consumers.

2. **Controller Layer** — `LoanController.java:33-36`
   ```java
   @GetMapping("/{loanId}/payments")
   public List<PaymentDto> getPayments(@PathVariable String loanId) {
       return loanService.getPaymentsByLoan(loanId);
   }
   ```
   - Returns unvalidated payment data. A consumer relying on `totalAmount` for accounting would get a different number than if they sum the components.

### Runtime Failure Scenario

A downstream accounting system calls `GET /api/loans/LN-2019-00142/payments` and sums the component amounts for reconciliation. It finds a $400 discrepancy per payment and flags the entire account for manual review. Over time, these discrepancies accumulate and trigger regulatory audit findings.

### Root Cause

The legacy CDW source system has an inconsistency in how payment totals are calculated — the total appears to sometimes exclude escrow and/or late fees while the components include them. The service layer performs no cross-field validation, passing the inconsistency directly to consumers.

### Recommended Fix

At ingestion, compute `expectedTotal = principal + interest + escrow + lateFee` and compare against the stated total. If they differ by more than $0.01, log a warning with the payment ID and discrepancy amount. Optionally, add a `reconciled` boolean flag to the `PaymentDto` so consumers know whether the payment data is internally consistent. For the Delta Lake migration, store both the original total and the computed total as separate columns for audit purposes.
