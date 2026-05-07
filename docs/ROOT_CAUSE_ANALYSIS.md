# Root Cause Analysis — Top 3 Critical Anomalies

---

## RCA-001: Payment Component Amounts Do Not Sum to Total (ANO-001)

### Anomaly Summary

Payments for loan `LN-2019-00142` (borrower James Mitchell) have component amounts (principal + interest + escrow + late fee) that exceed the reported total by exactly $400.00. A third payment (`PMT-2025110003` for loan `LN-2018-00089`) has a $47.50 discrepancy caused by an unreflected late fee.

### Code Path Trace

1. **API entry:** `LoanController.getPayments()` (LoanController.java:33-36)
   - Calls `loanService.getPaymentsByLoan(loanId)`

2. **Service method:** `LoanService.getPaymentsByLoan()` (LoanService.java:90-95)
   - Fetches from `paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()`
   - Maps each `LegacyPayment` → `PaymentDto` via `toPaymentDto()`

3. **Translation method:** `LoanService.toPaymentDto()` (LoanService.java:134-147)
   - Each amount field is parsed independently:
     ```java
     dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
     dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
     dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
     dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
     dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
     ```
   - **No cross-field validation** is performed. The sum 456.78 + 1,074.69 + 355.55 = 1,887.02 is never compared to the total 1,487.02.

4. **Parser method:** `LoanService.parseLegacyAmount()` (LoanService.java:152-155)
   - Simply strips commas and creates BigDecimal. No range checks, no component-sum validation.

5. **API response:** The `PaymentDto` is serialized to JSON with the inconsistent values. An API consumer receives:
   ```json
   {
     "totalAmount": 1487.02,
     "principalAmount": 456.78,
     "interestAmount": 1074.69,
     "escrowAmount": 355.55,
     "lateFee": 0.00
   }
   ```
   The sum of components (1,887.02) exceeds the total by $400.00.

### Root Cause

The legacy CDW system has no CHECK constraint or trigger that enforces `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE = PMT_AMT`. The escrow amount for loan `LN-2019-00142` payments appears to have been incorrectly populated — the $355.55 escrow component may have been entered in addition to an escrow amount already embedded in the interest figure, or the total was updated without recalculating components.

For `PMT-2025110003`, the $47.50 late fee was recorded but the total was not adjusted upward, suggesting the late fee was added after the payment record was initially created without updating the total.

The service layer at `LoanService.toPaymentDto()` has no validation to detect or flag this discrepancy. The `PaymentDto` class has no mechanism to communicate data quality warnings.

### Runtime Failure Mode

- **No crash** — the API returns 200 OK with silently incorrect data.
- **Downstream impact** — any consumer that sums components for reconciliation will see a mismatch. Financial reporting tools will flag audit exceptions. The incorrect data propagates silently into the modern schema during migration.

### Where the Fix Should Go

Add a payment component validation step in `toPaymentDto()` (or a dedicated validator called from it) that computes the expected total and compares it against the reported total. If the discrepancy exceeds a tolerance threshold ($0.01), log a warning and attach a data quality flag to the DTO.

---

## RCA-002: SSN Last-4 Field Contains Phone Number Digits (ANO-002)

### Anomaly Summary

All 5 `BORR_SSN_LST4` values in `CDW_LN_ACCT` are identical to the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR`, indicating the field was populated from the wrong source column during an ETL process.

### Code Path Trace

1. **Entity mapping:** `LegacyLoanAccount.java` (lines 29-30)
   ```java
   @Column(name = "BORR_SSN_LST4")
   private String borrowerSsnLast4;
   ```
   The field is mapped and loaded from the database on every loan account query.

2. **Service method:** `LoanService.toLoanSummary()` (LoanService.java:103-118)
   - This method does **not** use `borrowerSsnLast4`. It constructs the DTO from borrower name, amounts, dates, and property info.
   - The SSN last-4 is loaded into memory but never exposed in the current API response.

3. **Column mapping spec:** `column_mappings.md` (line 51)
   ```
   | BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
   ```
   The migration spec correctly marks this column as "dropped" — it should not be migrated.

4. **Cross-reference validation (manual):**
   | BORR_ID | Phone (CDW_BORR_MSTR) | SSN_LST4 (CDW_LN_ACCT) |
   |---------|----------------------|------------------------|
   | B-10001 | 217-555-**0142** | **0142** |
   | B-10002 | 503-555-**0198** | **0198** |
   | B-10003 | 512-555-**0167** | **0167** |
   | B-10004 | 303-555-**0134** | **0134** |
   | B-10005 | 602-555-**0156** | **0156** |

   100% correlation. The ETL source column was `BORR_PH_NBR` (substring last 4) instead of the SSN decryption output.

### Root Cause

The legacy ETL pipeline that populates `CDW_LN_ACCT` from `CDW_BORR_MSTR` used the wrong source column. Instead of decrypting `BORR_SSN_ENCR` and extracting the last 4 digits, it extracted the last 4 digits of `BORR_PH_NBR`. This is an ETL mapping error. The lack of foreign key constraints and data validation in the CDW schema allowed this to persist undetected.

### Runtime Failure Mode

- **Current code:** No immediate runtime failure. The field is loaded but not used in any DTO or API response.
- **Migration risk:** If a developer were to add SSN last-4 to the API (e.g., for identity verification), they would expose phone digits as SSN fragments — a compliance violation (GLBA, FCRA).
- **Data migration risk:** If the migration script does not correctly drop this column (as specified in `column_mappings.md`), corrupt data would flow into the modern schema.

### Where the Fix Should Go

Add a validation rule during ingestion that cross-references `BORR_SSN_LST4` against the last 4 digits of the borrower's phone number. If they match, flag the record as having a suspected SSN/phone data swap. The field should be excluded from any DTO mapping, and the migration script must drop it as specified.

---

## RCA-003: Delinquent Loan Marked as Active (ANO-003)

### Anomaly Summary

Loan `LN-2018-00089` (borrower Michael Torres) has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'`. The payment history confirms delinquency: `PMT-2025110003` was received 17 days late with a $47.50 late fee.

### Code Path Trace

1. **API entry:** `LoanController.getLoan()` (LoanController.java:28-31)
   - Calls `loanService.getLoanById("LN-2018-00089")`

2. **Service method:** `LoanService.getLoanById()` (LoanService.java:58-64)
   - Fetches the `LegacyLoanAccount` entity
   - Calls `toLoanSummary(acct, product)`

3. **Translation method:** `LoanService.toLoanSummary()` (LoanService.java:103-118)
   - Line 112: `dto.setStatus(expandStatusCode(acct.getStatusCode()));`
   - Passes `"ACT"` to `expandStatusCode()`

4. **Status expansion:** `LoanService.expandStatusCode()` (LoanService.java:167-176)
   ```java
   private String expandStatusCode(String code) {
       if (code == null) return "Unknown";
       return switch (code) {
           case "ACT" -> "Active";
           case "CLO" -> "Closed";
           case "DFT" -> "Default";
           case "FRB" -> "Forbearance";
           default -> code;
       };
   }
   ```
   - Returns `"Active"` — no cross-validation against delinquency days.

5. **Missing fields in DTO:** `LoanSummaryDto` does **not** include a `delinquencyDays` field. The entity has `delinquencyDays = "15"` but this data is never surfaced to the API consumer. The delinquency information is silently dropped.

6. **Payment corroboration:** `PMT-2025110003` for this loan:
   - `PMT_DT = '11/01/2025'` (due date)
   - `PMT_RECV_DT = '11/18/2025'` (received date — 17 days late)
   - `PMT_LATE_FEE = '47.50'` (late fee charged)
   - This confirms the loan is delinquent, yet the status remains `ACT`.

### Root Cause

The legacy CDW system updates `LN_DLQ_DAYS` via an automated batch process that counts days since the last payment due date, but `LN_STAT_CD` is only updated manually or by a separate process with different triggering criteria. The two fields are maintained by independent systems with no cross-validation, leading to inconsistent state. The service layer's `expandStatusCode()` trusts the status code without checking delinquency days.

### Runtime Failure Mode

- **Incorrect API response:** The API returns `"status": "Active"` for a loan that is 15 days past due. No indication of delinquency is provided since `delinquencyDays` is not in the DTO.
- **Business impact:** Risk dashboards, portfolio reports, and regulatory filings that consume this API will underreport delinquency. An investor or regulator relying on the "Active" status would not know the loan is past due.
- **Cascading effect:** If loan status drives business logic downstream (e.g., eligibility for refinancing, forbearance offers), a delinquent loan incorrectly marked as active could qualify for products it shouldn't.

### Where the Fix Should Go

Add a status cross-validation step in `toLoanSummary()` that checks: if `delinquencyDays > 0` and `statusCode == "ACT"`, override the expanded status to include a delinquency indicator (e.g., `"Active - Delinquent"`) or log a warning. Also add `delinquencyDays` to `LoanSummaryDto` so API consumers have full visibility. Implement a `validateLoanStatus()` method in the validator that enforces business rules between status and delinquency.
