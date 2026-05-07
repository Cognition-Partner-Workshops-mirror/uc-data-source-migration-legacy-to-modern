# Root Cause Analysis — Top 3 Critical Data Anomalies

## RCA-1: Payment Component Amounts Do Not Sum to Total

### Anomaly Summary

In `CDW_PMT_HIST`, the sum of `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` does not equal `PMT_AMT` for 3 out of 10 payment records (30% failure rate).

### Code Path Trace

```
LoanController.getPayments()
  → LoanService.getPaymentsByLoan()
    → paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()
    → LoanService.toPaymentDto()
      → parseLegacyAmount(pmt.getTotalAmount())         // Line 139
      → parseLegacyAmount(pmt.getPrincipalAmount())     // Line 140
      → parseLegacyAmount(pmt.getInterestAmount())      // Line 141
      → parseLegacyAmount(pmt.getEscrowAmount())        // Line 142
      → parseLegacyAmount(pmt.getLateFee())             // Line 143
```

**File:** `LoanService.java`, lines 134-147

### Runtime Failure Mode

The service does **not** validate that component amounts sum to the total. Each field is independently parsed and returned in the `PaymentDto`. The API consumer receives inconsistent financial data:

```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```

Sum of components = 1,887.02 but `totalAmount` = 1,487.02. A frontend displaying both the total and a breakdown will show contradictory numbers.

### Column Mapping Impact

From `data/mappings/column_mappings.md`:
- `PMT_AMT` → `total_amount` (DECIMAL)
- `PMT_PRIN_AMT` → `principal_amount` (DECIMAL)
- `PMT_INT_AMT` → `interest_amount` (DECIMAL)
- `PMT_ESCROW_AMT` → `escrow_amount` (DECIMAL)
- `PMT_LATE_FEE` → `late_fee` (DECIMAL)

The mapping applies "Remove commas, parse → decimal" transformation to each field independently. No cross-field validation exists in the mapping specification.

### Root Cause

The legacy CDW stores each payment component as an independently-entered value with no database-level CHECK constraint enforcing `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. The upstream system that feeds the CDW likely has a different definition of "total" (e.g., P&I only, excluding escrow) or the escrow allocation was added after the total was calculated without updating it.

For the late fee case (`PMT-2025110003`), the late fee was recorded separately but the `PMT_AMT` was not recalculated to include it, indicating the total represents the scheduled payment amount rather than the actual amount collected.

### Fix Location

`LoanService.toPaymentDto()` (line 134) — add post-parse validation that verifies component sum matches total. If mismatch detected, either recalculate total from components or flag the record with a warning field in the DTO.

---

## RCA-2: SSN Last-4 Matches Phone Number Last-4 (Systemic Data Corruption)

### Anomaly Summary

In `CDW_LN_ACCT`, the `BORR_SSN_LST4` field for 100% of records (5/5) matches the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR.BORR_PH_NBR`. This indicates systemic corruption rather than coincidence.

### Code Path Trace

```
LoanController.getLoan()
  → LoanService.getLoanById()
    → loanAccountRepository.findById()
    → LoanService.toLoanSummary()         // Line 103
      → acct.getBorrowerFirstName()       // Line 106 (denormalized field used)
      → acct.getBorrowerLastName()        // Line 106 (denormalized field used)
      // BORR_SSN_LST4 is NOT used in the service layer
```

**File:** `LoanService.java`, line 103-118; `LegacyLoanAccount.java`, line 29-30

### Runtime Failure Mode

Currently, the `BORR_SSN_LST4` field is mapped in the entity (`LegacyLoanAccount.borrowerSsnLast4`) but is **never read** by the service layer — it's not included in any DTO. This means the corruption is **silent** in the current API but becomes critical during migration.

From `data/mappings/column_mappings.md` (line 51):
```
| `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```

The mapping marks this field as "dropped" — but if any downstream system or migration validation script uses it for identity verification before dropping it, it will produce false matches/mismatches.

### Column Mapping Impact

The field is marked as dropped in the modern schema, but:
1. Any data reconciliation report comparing denormalized SSN_LST4 against the master `BORR_SSN_ENCR` will flag 100% of records as suspect
2. If identity verification during migration decrypts `BORR_SSN_ENCR` and compares last-4 against `BORR_SSN_LST4`, all records will fail verification
3. Systems that historically used this field for phone-based identity confirmation (e.g., "please confirm the last 4 of your SSN") would have been accepting phone digits instead

### Root Cause

A prior ETL process or data entry system incorrectly mapped `BORR_PH_NBR` (last 4 digits) into the `BORR_SSN_LST4` field. This likely occurred during a system migration or bulk data load where column positions were offset. The lack of validation (the field accepts any 4-char string) allowed this to persist undetected.

### Fix Location

Add a cross-reference validation in the service layer that detects when `BORR_SSN_LST4` matches the last 4 digits of `BORR_PH_NBR` for the associated borrower. Flag such records as having suspect SSN data. During migration, this field should be dropped entirely (as the mapping specifies) and not used for any identity verification.

---

## RCA-3: Delinquency Days > 0 with Active Status (Business Rule Violation)

### Anomaly Summary

Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'`. A delinquent loan should not have an Active status — it should be flagged for collections or forbearance.

### Code Path Trace

```
LoanController.getAllLoans()
  → LoanService.getAllLoans()
    → loanAccountRepository.findAll()
    → LoanService.toLoanSummary()             // Line 103
      → expandStatusCode(acct.getStatusCode())  // Line 112
        → case "ACT" → "Active"               // Line 170
      // LN_DLQ_DAYS is NEVER read or validated
```

**File:** `LoanService.java`, lines 103-118 and 167-176; `LegacyLoanAccount.java`, line 65-66

### Runtime Failure Mode

The `LoanSummaryDto` includes `status` (expanded from status code) but does **not** include delinquency days. The API response will show:

```json
{
  "loanAccountNumber": "LN-2018-00089",
  "status": "Active",
  ...
}
```

This is technically "correct" (it faithfully translates the legacy data), but it's **semantically wrong**. The loan is reported as Active when it's actually delinquent. Additionally:
- The `delinquencyDays` field is mapped in the entity but never exposed through any DTO
- The `expandStatusCode` method has no cross-validation against delinquency

Supporting evidence: `PMT-2025110003` (for this same loan) has `PMT_LATE_FEE = '47.50'` and `PMT_RECV_DT = '11/18/2025'` vs `PMT_DT = '11/01/2025'` — payment was received 17 days late, confirming the delinquency.

### Column Mapping Impact

From `data/mappings/column_mappings.md`:
- `LN_STAT_CD` → `status` VARCHAR(15): "Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE"
- `LN_DLQ_DAYS` → `delinquency_days` INTEGER: "Parse string → integer"

These are mapped independently with no cross-field validation rule defined. The modern schema would preserve the inconsistency unless caught at migration time.

### Root Cause

The CDW status update process is likely batch-driven and out of sync with the delinquency tracking system. The delinquency counter (`LN_DLQ_DAYS`) is updated by one subsystem (possibly daily), while `LN_STAT_CD` is only updated when a manual review is triggered or a threshold is exceeded (e.g., 30+ days). This creates a window where delinquency exists but status hasn't been escalated.

### Fix Location

`LoanService.toLoanSummary()` (line 112) — after expanding the status code, cross-validate against delinquency days. If `delinquencyDays > 0` and status is `ACT`, either:
1. Override the status to reflect delinquency (e.g., "Active - Delinquent")
2. Add a warning/flag field to the DTO
3. Log a data quality warning for operational monitoring
