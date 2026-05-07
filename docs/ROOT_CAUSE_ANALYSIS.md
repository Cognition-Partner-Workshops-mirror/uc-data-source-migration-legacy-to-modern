# Root Cause Analysis -- Top 3 Critical Anomalies

> **Generated:** 2026-05-07
> **Scope:** Code trace through LoanService.java, repository layer, and column_mappings.md

---

## RCA-001: Payment Component Sum Mismatch (ANM-001)

### Anomaly Summary

Payment records for loan LN-2019-00142 and one payment for LN-2018-00089 have component breakdowns (principal + interest + escrow + late fee) that do not sum to the total payment amount.

### Code Path Trace

1. **Entry point:** `LoanController.getPayments()` calls `LoanService.getPaymentsByLoan(loanAccountNumber)`
2. **Repository:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` returns raw `LegacyPayment` entities with all fields as Strings
3. **Translation:** `LoanService.toPaymentDto()` (line 134-147) converts each payment:
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // "1,487.02" -> 1487.02
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // "456.78" -> 456.78
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // "1,074.69" -> 1074.69
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // "355.55" -> 355.55
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // "0.00" -> 0.00
   ```
4. **No validation:** The service faithfully parses and forwards every field independently. There is zero cross-field validation checking that components sum to the total.

### Root Cause

The legacy CDW warehouse likely has two independent data pipelines feeding the payment table:
- **Pipeline A** writes the total payment amount (PMT_AMT) from the payment processing system
- **Pipeline B** writes the component breakdown from the loan accounting system

For LN-2019-00142, the escrow component (355.55) appears to have been double-counted or sourced from a different calculation period. The total (1,487.02) matches the loan's scheduled monthly payment exactly, but principal (456.78) + interest (1,074.69) alone already exceeds it (1,531.47). This suggests the interest allocation is inflated -- possibly using the wrong amortization schedule or rate.

For PMT-2025110003 (LN-2018-00089), the late fee (47.50) was recorded but not included in the total, indicating the late fee was assessed after the total was finalized.

### Runtime Impact

- `PaymentDto` is returned to API consumers with internally inconsistent data
- Any client computing `total - principal - interest` to derive escrow would get a negative number
- Financial reconciliation reports would not balance
- The service layer (`LoanService.java:134-147`) has no mechanism to detect or flag this

### Where It Would Fail

The failure is **silent data corruption** rather than a runtime exception. The API returns HTTP 200 with financially incorrect data. This is worse than a crash because it propagates bad data without any warning.

### Column Mapping Reference

Per `data/mappings/column_mappings.md` (line 82-86):
- `PMT_AMT` -> `total_amount` (DECIMAL): "Remove commas, parse -> decimal"
- `PMT_PRIN_AMT` -> `principal_amount` (DECIMAL): "Remove commas, parse -> decimal"
- Each field is mapped independently with no cross-field validation specified

---

## RCA-002: SSN Last-4 Populated from Phone Numbers (ANM-002)

### Anomaly Summary

All 5 loan accounts have `BORR_SSN_LST4` values that exactly match the last 4 digits of the corresponding borrower's phone number, not their SSN.

### Code Path Trace

1. **Entity mapping:** `LegacyLoanAccount.java` (line 29-30) maps the column:
   ```java
   @Column(name = "BORR_SSN_LST4")
   private String borrowerSsnLast4;
   ```
2. **Service usage:** `LoanService.toLoanSummary()` (line 103-118) does NOT use `borrowerSsnLast4` in the DTO -- the field is loaded by JPA but not exposed in the current API.
3. **Column mapping spec:** `column_mappings.md` (line 51) specifies:
   > `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | -- | Denormalized; use borrower FK
4. **However**, the field IS loaded into the entity and available via `getBorrowerSsnLast4()`. Any future code or reporting that references this field would use phone digits as SSN verification.

### Root Cause

The legacy ETL job that populates `CDW_LN_ACCT` from the source system has a column mapping error. The source query likely has adjacent columns for phone and SSN-last-4 in the SELECT list, and they were mapped to the wrong target columns during the initial ETL development. Evidence:

| Borrower | Phone Last 4 | BORR_SSN_LST4 |
|----------|-------------|---------------|
| B-10001 | 0142 | 0142 |
| B-10002 | 0198 | 0198 |
| B-10003 | 0167 | 0167 |
| B-10004 | 0134 | 0134 |
| B-10005 | 0156 | 0156 |

A 100% correlation across all records rules out coincidence. This is a systematic ETL mapping error.

### Runtime Impact

- **Current code:** No immediate runtime failure. The field is mapped but not used in DTOs.
- **Migration risk:** `column_mappings.md` marks this field as "dropped," so it won't migrate. But if any interim code, report, or audit references `BORR_SSN_LST4` for identity verification, it would be checking phone digits.
- **Compliance risk:** If this data was ever used for KYC/AML verification, the institution was unknowingly using phone numbers as SSN fragments -- a regulatory violation.

### Where It Would Fail

The failure occurs in **any downstream system** that trusts `BORR_SSN_LST4` for identity verification. In the current codebase, the field is loaded but unused. The risk is that:
1. A developer adds SSN-last-4 verification to a new endpoint
2. A report queries CDW_LN_ACCT.BORR_SSN_LST4 directly
3. The migration process inadvertently copies this field despite it being marked "dropped"

### Column Mapping Reference

Per `data/mappings/column_mappings.md` (line 51):
> `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | -- | Denormalized; use borrower FK

The mapping correctly flags this for removal, but does not note that the current data is corrupt.

---

## RCA-003: Delinquency Days vs. Loan Status Inconsistency (ANM-003)

### Anomaly Summary

Loan LN-2018-00089 (Michael Torres, ARM 5/1) shows 15 delinquent days with an "ACT" (Active) status. Corroborating evidence: a $47.50 late fee on payment PMT-2025110003 and late payment receipt dates.

### Code Path Trace

1. **Entry point:** `LoanController.getLoan()` calls `LoanService.getLoanById()`
2. **Status translation:** `LoanService.toLoanSummary()` (line 112) expands the status code:
   ```java
   dto.setStatus(expandStatusCode(acct.getStatusCode()));
   ```
3. **Status expansion:** `expandStatusCode()` (line 167-176):
   ```java
   case "ACT" -> "Active";
   case "CLO" -> "Closed";
   case "DFT" -> "Default";
   case "FRB" -> "Forbearance";
   ```
4. **Delinquency days:** The `LN_DLQ_DAYS` field is mapped in `LegacyLoanAccount.java` (line 65-66) but **never read or used** in `LoanService.toLoanSummary()`. The DTO (`LoanSummaryDto`) does not have a delinquency field.
5. **No cross-validation:** The service blindly expands the status code without checking whether delinquency days contradict it.

### Root Cause

Two independent update processes maintain loan status:

1. **Status update process:** A batch job (likely nightly) evaluates loan conditions and sets `LN_STAT_CD`. The threshold for changing from ACT to DFT is typically 90+ days. At 15 days, the batch job leaves the status as ACT per its business rules.
2. **Delinquency tracker:** A separate process counts days since the last on-time payment and writes to `LN_DLQ_DAYS`. This runs independently.
3. **Missing intermediate status:** The status code vocabulary (ACT, CLO, DFT, FRB) has no "DELINQUENT" or "WATCH" state for loans between 1-89 days past due. This gap means the status field cannot accurately represent the loan's true condition.

The corroborating evidence from payment PMT-2025110003:
- Payment date: 11/01/2025 (the due date)
- Received date: 11/18/2025 (17 days late)
- Late fee: $47.50 (confirming the payment was late)

### Runtime Impact

- `LoanSummaryDto.status` returns "Active" for a delinquent loan
- API consumers (risk dashboards, portfolio managers) see a clean "Active" status with no indication of delinquency
- The delinquency days field is available in the entity but never surfaced to the API
- `expandStatusCode()` has no "delinquent" mapping because the legacy system has no such code

### Where It Would Fail

1. **Portfolio risk reporting:** Active loan counts are inflated; delinquent counts are understated
2. **Regulatory reporting:** HMDA and Call Report submissions would misclassify this loan
3. **Customer communications:** Auto-generated statements would show "Active" status to a borrower who is actually delinquent
4. **Migration:** The modern schema maps `LN_STAT_CD` to a `status` field (column_mappings.md line 62). Without adding delinquency validation, the modern schema inherits the same blind spot

### Column Mapping Reference

Per `data/mappings/column_mappings.md` (lines 62-63):
- `LN_STAT_CD` -> `status` (VARCHAR(15)): "Expand: ACT->ACTIVE, CLO->CLOSED, DFT->DEFAULT, FRB->FORBEARANCE"
- `LN_DLQ_DAYS` -> `delinquency_days` (INTEGER): "Parse string -> integer"

Both fields migrate independently with no cross-validation rule specified.
