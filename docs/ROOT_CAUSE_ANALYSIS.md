# Root Cause Analysis — Top 3 Critical Anomalies

> **Service:** uc-data-source-migration-legacy-to-modern (Loan Service)
> **Analysis Date:** 2026-05-07

---

## RCA-1: SSN Last-4 Populated from Phone Numbers (ANO-001)

### Anomaly

Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` is identical to the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR.BORR_PH_NBR`.

### Code Path Trace

1. **Entity:** `LegacyLoanAccount.java` maps `BORR_SSN_LST4` to `borrowerSsnLast4` (line 29-30).
2. **Service:** `LoanService.toLoanSummary()` (line 103-118) does **not** use `borrowerSsnLast4` in the DTO — it is silently ignored in the current API response.
3. **Column Mapping:** `column_mappings.md` line 51 marks `BORR_SSN_LST4` as `*(dropped)*` in the modern schema, noting: "Denormalized; use borrower FK."
4. **Repository:** `LegacyLoanAccountRepository` provides `findByBorrowerId()` but no query involves `BORR_SSN_LST4`.

### Where It Would Cause Failure

- **Migration script (Task 2):** If a migration script were to validate SSN consistency between `CDW_BORR_MSTR.BORR_SSN_ENCR` and `CDW_LN_ACCT.BORR_SSN_LST4`, it would find no correlation because the last-4 field contains phone digits, not SSN digits.
- **Identity verification:** Any downstream service that uses the SSN last-4 from the loan account table for borrower identity verification (e.g., phone-based KYC, IVR authentication) would be matching against phone numbers, creating false positive identity confirmations.
- **Deduplication:** If SSN last-4 is used as part of a composite key for borrower deduplication during migration, records would be incorrectly matched or missed.

### Root Cause

The legacy ETL process that populates `CDW_LN_ACCT` appears to have a column mapping error: the pipeline sourced `BORR_SSN_LST4` from the phone number field instead of the encrypted SSN field. Since the schema uses VARCHAR for everything and has no cross-table constraints, this went undetected. The fact that the mapping document marks this field as "dropped" suggests awareness that the denormalized SSN data is unreliable.

### Recommended Action

1. Do **not** migrate `BORR_SSN_LST4` to the modern schema (already planned per column_mappings.md).
2. Add a data quality validation that cross-references `BORR_SSN_LST4` against `BORR_PH_NBR` to detect and flag this pattern.
3. Audit any downstream systems that may have consumed this field historically.

---

## RCA-2: Payment Component Amounts Do Not Sum to Total (ANO-002)

### Anomaly

For 2 out of 10 payment records (loan LN-2019-00142), the sum of `principal + interest + escrow + late_fee` exceeds the stated `total` by exactly $400.00. For 1 record (PMT-2025110003), the late fee of $47.50 is excluded from the total.

### Code Path Trace

1. **Entity:** `LegacyPayment.java` maps all payment component fields as individual strings (lines 25-38).
2. **Service:** `LoanService.toPaymentDto()` (lines 134-147) parses each component independently:
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));        // line 139
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // line 140
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // line 141
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // line 142
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // line 143
   ```
   There is **no cross-field validation** — each field is parsed in isolation and passed directly to the DTO.
3. **Controller:** `LoanController.getPayments()` (line 33-36) returns the DTO list directly. The imbalanced data reaches the API consumer without any warning.
4. **DTO:** `PaymentDto.java` stores all amounts as `BigDecimal` but has no computed field or validation for sum consistency.

### Where It Would Cause Runtime Failure or Incorrect API Response

- **Incorrect API response (current):** The `/api/loans/LN-2019-00142/payments` endpoint returns payments where `principalAmount + interestAmount + escrowAmount + lateFee != totalAmount`. Any API consumer that recalculates totals from components will get a different number than the `totalAmount` field, causing reconciliation failures.
- **Financial reporting:** Aggregating payment components across all loans will produce a different total than aggregating `totalAmount`, leading to an unexplained $847.50 variance ($400 x 2 + $47.50) in financial reports.
- **Migration integrity check:** If the migration script validates that component sums match totals (as recommended in MIGRATION_TASKS.md Task 2), it will reject these 3 records, causing a partial migration failure.

### Root Cause

Two distinct issues in the legacy source data:

1. **Loan LN-2019-00142 ($400 discrepancy):** The `PMT_AMT` (total) appears to represent only the base P&I payment ($1,487.02 matches `LN_PMT_AMT` from the loan account), while the individual components include the escrow allocation ($355.55). The escrow is correctly allocated to the component breakdown but the total was sourced from the loan's scheduled payment amount rather than the actual disbursement. This is a systematic issue: the CDW likely has two different source systems — one for payment totals (from the servicing system's scheduled amount) and one for component breakdowns (from the actual allocation engine).

2. **PMT-2025110003 ($47.50 discrepancy):** The late fee was assessed and recorded in the component breakdown but not added to the payment total. This suggests the late fee was assessed after the payment total was calculated, a classic race condition in batch processing systems.

### Recommended Action

1. Add a `PaymentBalanceValidator` that checks component sum vs. total at ingestion.
2. Flag imbalanced records with a `dataQualityWarning` field in the `PaymentDto`.
3. Decide on a source-of-truth policy: either the total is authoritative (and components need adjustment) or the components are authoritative (and the total should be recalculated).

---

## RCA-3: Unhandled NumberFormatException in Amount/Integer Parsing (ANO-003)

### Anomaly

All numeric parsing methods in `LoanService` (`parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`) throw unhandled exceptions on malformed input. Since every numeric field in the legacy schema is VARCHAR, any non-numeric value will crash the API.

### Code Path Trace

1. **`parseLegacyAmount(String amount)`** (LoanService.java lines 152-155):
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   Only handles null/blank. Any other non-numeric string (e.g., `"$285,000"`, `"N/A"`, `"PENDING"`) throws `NumberFormatException`.

2. **`parseLegacyInteger(String value)`** (lines 162-165):
   ```java
   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```
   Same issue — no error handling for non-integer strings.

3. **Call sites in `toLoanSummary()`** (lines 108-111): This method calls `parseLegacyAmount` 3 times and `parseLegacyDecimal` once for every loan account. A single bad value in any of these fields crashes the entire `getAllLoans()` response.

4. **Call sites in `toPaymentDto()`** (lines 139-143): Calls `parseLegacyAmount` 5 times per payment. One bad value in any payment crashes the entire payment history for a loan.

5. **Call site in `toBorrowerDto()`** (line 129): Calls `parseLegacyInteger` for credit score. A non-numeric credit score crashes the borrower lookup.

### Where It Would Cause Runtime Failure

- **`GET /api/loans`:** If any single loan account has a malformed amount in `LN_ORIG_AMT`, `LN_CURR_BAL`, `LN_INT_RT`, or `LN_PMT_AMT`, the entire loan listing endpoint returns a 500 error. The exception propagates up through the Spring controller as an unhandled `RuntimeException`, and the default error handler returns a generic error with no indication of which record or field caused the failure.
- **`GET /api/borrowers`:** A malformed credit score for any borrower crashes the entire borrower listing.
- **`GET /api/loans/{id}/payments`:** A malformed amount in any payment component crashes the payment history for that loan.
- **Cascading failure:** Since `getAllLoans()` loads all loans in a single stream operation, one bad record poisons the entire response. There is no record-level error isolation.

### Root Cause

The parsing methods were written for the "happy path" where all VARCHAR values happen to contain well-formatted numbers. The legacy data warehouse schema provides no type-level guarantees (everything is VARCHAR), but the parsing code assumes type-level correctness. This is a classic impedance mismatch: the code trusts the data more than the schema warrants.

### Recommended Action

1. Wrap all parsing methods in try-catch blocks that log the error and return a safe default or null.
2. Add a `List<String> dataQualityWarnings` field to DTOs to surface parsing issues to API consumers without crashing.
3. Add range validation after parsing (e.g., amounts >= 0, credit scores 300-850, rates 0-100).
4. Consider record-level error isolation: if one record fails to parse, skip it with a warning rather than failing the entire list.
