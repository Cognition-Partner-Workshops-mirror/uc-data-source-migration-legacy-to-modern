# Root Cause Analysis — Top 3 Critical Anomalies

---

## RCA-001: Payment Component Sum Mismatch (ANOM-001)

### Anomaly Summary

Three payment records have `PMT_AMT` values that do not equal the sum of `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. The deltas are -400.00 (twice) and -47.50.

### Code Path Trace

1. **Controller:** `LoanController.getPayments()` (`LoanController.java:33-36`) calls `LoanService.getPaymentsByLoan(loanId)`.

2. **Repository:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` (`LegacyPaymentRepository.java:14`) fetches all `CDW_PMT_HIST` rows for the loan. No validation occurs at the repository layer — all rows are returned as-is.

3. **Service — `toPaymentDto()`** (`LoanService.java:134-147`):
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
   ```
   Each component is parsed independently. There is **no cross-field validation** that verifies the total equals the sum of parts.

4. **Column Mappings:** `column_mappings.md` (lines 82-86) defines the mapping from `PMT_AMT` → `total_amount` and each component → its modern equivalent, all using "Remove commas, parse -> decimal". No integrity constraint is specified.

### Root Cause

The legacy CDW system stores payment components independently with no database-level check constraint. The service layer (`toPaymentDto`) faithfully transcribes each field without verifying arithmetic consistency. For loan `LN-2019-00142`, both payment records show a -400.00 delta, which exactly matches the escrow amount (355.55 rounded to a systematic offset), suggesting the escrow component was added to the breakdown after the total was recorded, or the total represents only principal + interest while escrow is tracked separately.

For `PMT-2025110003`, the -47.50 delta exactly matches the late fee, indicating the late fee was appended to the component breakdown but not added to the total.

### Runtime Failure Mode

- **Incorrect API response:** The API returns `totalAmount: 1487.02` alongside components that sum to `1887.02`. Any consumer that recalculates the total from components will get a different number than the `totalAmount` field.
- **Financial reconciliation failures:** Downstream accounting systems will flag these as out-of-balance transactions.
- **No runtime exception** — the data silently passes through, making this a **silent data corruption** issue (worse than a crash).

### Recommended Code Fix Location

`LoanService.toPaymentDto()` (line 134) — add post-parse validation that compares the parsed total against the sum of parsed components. Log a warning and attach a `dataQualityWarning` flag to the DTO.

---

## RCA-002: Numeric String Parsing Without Error Handling (ANOM-002)

### Anomaly Summary

All numeric fields are VARCHAR strings parsed via `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()`. None of these methods catch `NumberFormatException`.

### Code Path Trace

1. **`parseLegacyAmount()`** (`LoanService.java:152-155`):
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   Only checks for null/blank. Values like `"$285,000"`, `"N/A"`, or `"(1,200)"` will throw `NumberFormatException` from `new BigDecimal(...)`.

2. **`parseLegacyInteger()`** (`LoanService.java:162-165`):
   ```java
   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```
   Called for credit score parsing in `toBorrowerDto()` (line 129). Any non-numeric credit score crashes the borrower endpoint.

3. **`parseLegacyDecimal()`** (`LoanService.java:157-160`): Same pattern — no try-catch.

4. **Call sites in `toLoanSummary()`** (`LoanService.java:108-111`): Four calls to `parseLegacyAmount` and one to `parseLegacyDecimal`. A single malformed field in any loan account crashes `GET /api/loans` for ALL users (because `getAllLoans()` maps over all accounts).

5. **Column Mappings:** `column_mappings.md` specifies transformations like "Remove commas, parse -> decimal" (lines 22, 37-38, 53-57, 82-86) but does not prescribe error handling for unparseable values.

### Root Cause

The service layer assumes all VARCHAR numeric fields contain well-formed numbers after comma removal. The legacy CDW system has no input validation or type constraints (all columns are VARCHAR), so any upstream process can insert arbitrary strings. The parsing methods were written for the happy path with no defensive error handling.

### Runtime Failure Mode

- **HTTP 500 on `GET /api/loans`:** If any single loan account has a malformed amount field, `getAllLoans()` throws `NumberFormatException` (uncaught). Spring Boot's default exception handler returns HTTP 500 with a stack trace. This takes down the entire endpoint, not just the affected record.
- **HTTP 500 on `GET /api/borrowers`:** Same failure mode via `parseLegacyInteger` for credit scores.
- **HTTP 500 on `GET /api/loans/{id}/payments`:** Same failure mode for payment amounts.
- This is a **total service outage** from a single bad record.

### Recommended Code Fix Location

All three parsing methods in `LoanService.java` (lines 152-165) — wrap the parse operations in try-catch blocks. Additionally, create a centralized `LegacyDataValidator` that can be reused across all transformation methods.

---

## RCA-003: Delinquency Days / Status Code Contradiction (ANOM-003)

### Anomaly Summary

Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` with `LN_STAT_CD = 'ACT'`. A 15-day delinquent loan should not be in Active status.

### Code Path Trace

1. **Controller:** `LoanController.getLoan()` (`LoanController.java:28-31`) calls `LoanService.getLoanById()`.

2. **Service — `toLoanSummary()`** (`LoanService.java:103-118`):
   ```java
   dto.setStatus(expandStatusCode(acct.getStatusCode()));
   ```
   The status code is expanded from `"ACT"` to `"Active"` (line 170). The delinquency days field (`LN_DLQ_DAYS`) is **never read or included in the DTO**. The `LoanSummaryDto` has no `delinquencyDays` field.

3. **`expandStatusCode()`** (`LoanService.java:167-176`): Maps `ACT` → `Active` with no cross-validation against delinquency. The mapping is purely syntactic — it expands the code without considering business rules.

4. **Column Mappings:** `column_mappings.md` (lines 62-63) maps `LN_DLQ_DAYS` → `delinquency_days` (INTEGER) and `LN_STAT_CD` → `status` (VARCHAR) as independent fields. No cross-field validation rule is documented.

5. **Corroborating evidence in payment data:**
   - `PMT-2025110003` for this loan: received 17 days late (`PMT_DT=11/01/2025`, `PMT_RECV_DT=11/18/2025`) with a $47.50 late fee.
   - `PMT-2025120003` for this loan: received 4 days late (`PMT_DT=12/01/2025`, `PMT_RECV_DT=12/05/2025`) with no late fee.
   - This confirms the borrower has a pattern of late payments, yet the loan remains `ACT`.

### Root Cause

The legacy CDW updates `LN_DLQ_DAYS` and `LN_STAT_CD` independently — likely via different batch processes. The delinquency-days counter is updated by a daily batch that counts days since last payment, while the status code is only updated by a separate collections workflow that triggers at higher thresholds (e.g., 30/60/90 days). The 15-day gap falls between the delinquency counter update and the status transition trigger.

The service layer compounds this by only exposing the status code and ignoring the delinquency days entirely, meaning API consumers see `"Active"` with no indication that the loan is 15 days past due.

### Runtime Failure Mode

- **Silent misrepresentation:** The API returns `"status": "Active"` for a delinquent loan. No exception is thrown — the data is technically valid, just misleading.
- **Business logic errors:** Any consumer filtering by `status == "Active"` to find current, healthy loans will incorrectly include this delinquent loan.
- **Regulatory risk:** Delinquency reporting that relies on status codes alone will undercount delinquent loans.

### Recommended Code Fix Location

`LoanService.toLoanSummary()` (line 112) — add cross-validation between delinquency days and status code. When `delinquencyDays > 0` and `status == ACT`, either override the status to a warning state or include a data quality flag in the response.
