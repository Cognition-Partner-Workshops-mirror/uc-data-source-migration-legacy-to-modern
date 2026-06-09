# Root Cause Analysis — Top 3 Critical Data Anomalies

## RCA-1: Payment Component Amounts Do Not Sum to Total (ANO-001)

### Symptom

For loan `LN-2019-00142`, the payment breakdown fields sum to $1,887.02 but `PMT_AMT` records
$1,487.02 — a consistent $400 discrepancy across both payment records for this loan.

### Code Path Trace

```
LoanController.getPayments(loanId)
  → LoanService.getPaymentsByLoan(loanAccountNumber)    [line 90-95]
    → paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(...)
    → toPaymentDto(pmt)                                 [line 134-147]
      → parseLegacyAmount(pmt.getTotalAmount())         → 1487.02
      → parseLegacyAmount(pmt.getPrincipalAmount())     → 456.78
      → parseLegacyAmount(pmt.getInterestAmount())      → 1074.69
      → parseLegacyAmount(pmt.getEscrowAmount())        → 355.55
      → parseLegacyAmount(pmt.getLateFee())             → 0.00
```

### Where It Fails

`LoanService.toPaymentDto()` (line 134-147) performs no reconciliation check. Each component
is parsed independently and placed into the `PaymentDto` without verifying that
`principal + interest + escrow + lateFee == total`. The `PaymentDto` (lines 1-41) exposes
all fields directly with no computed/validated total.

The `parseLegacyAmount()` method (line 152-155) correctly parses each individual value but has
no cross-field validation. The caller blindly trusts that the source data is internally
consistent.

### Root Cause

The legacy CDW system has no database-level CHECK constraint enforcing that payment component
amounts sum to the total payment amount. The ETL process that loads data into `CDW_PMT_HIST`
appears to have a bug specific to loan `LN-2019-00142` where the escrow portion ($355.55) is
recorded but not properly reflected in the total — possibly because this loan's escrow was
added after the initial payment record was created, and the total was never recalculated.

### Runtime Impact

- **API Response:** `/api/loans/LN-2019-00142/payments` returns a `PaymentDto` where the sum of
  `principalAmount + interestAmount + escrowAmount + lateFee` ($1,887.02) ≠ `totalAmount`
  ($1,487.02). Any client that recalculates or validates will see a $400 discrepancy.
- **No exception is thrown** — the incorrect data passes through silently.
- **Financial reporting** built on this API will either double-count escrow or under-report total
  payments depending on which field they trust.

### Column Mapping Reference

From `data/mappings/column_mappings.md`:
- `PMT_AMT → total_amount` (DECIMAL 10,2) — "Remove commas, parse → decimal"
- `PMT_PRIN_AMT → principal_amount`, `PMT_INT_AMT → interest_amount`, etc.

The mapping document specifies no cross-field validation, meaning this bug will persist through
migration unless explicitly addressed.

---

## RCA-2: SSN Last-4 Field Contains Phone Number Last-4 (ANO-002)

### Symptom

Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` exactly matches the last 4 digits of the
corresponding borrower's phone number in `CDW_BORR_MSTR.BORR_PH_NBR`.

### Code Path Trace

```
LegacyLoanAccount entity [LegacyLoanAccount.java line 29-30]
  → @Column(name = "BORR_SSN_LST4")
  → private String borrowerSsnLast4;

LoanService.toLoanSummary(acct, product)               [line 103-118]
  → Does NOT use acct.getBorrowerSsnLast4()
  → Only uses: acct.getBorrowerFirstName(), acct.getBorrowerLastName()

Column Mappings (column_mappings.md line 51):
  → BORR_SSN_LST4 → *(dropped)* — "Denormalized; use borrower FK"
```

### Where It Fails

Currently, the code does NOT expose `BORR_SSN_LST4` through the API — `toLoanSummary()` doesn't
include it in the `LoanSummaryDto`. So there is no immediate runtime failure in the current
codebase. However:

1. The data is **wrong at the source** — the legacy ETL that populates `CDW_LN_ACCT` extracted
   `SUBSTR(BORR_PH_NBR, -4)` instead of `SUBSTR(BORR_SSN_ENCR, -4)` (or the decrypted last 4).
2. Any future code that references `borrowerSsnLast4` for identity verification will use
   incorrect data.
3. The `LegacyLoanAccount` entity maps this field (line 29-30), making it accessible to any
   service that injects the repository.

### Root Cause

The legacy ETL job that denormalizes borrower data into `CDW_LN_ACCT` has a column-mapping
error. The source query likely joined `CDW_BORR_MSTR` and extracted `RIGHT(BORR_PH_NBR, 4)`
instead of the actual SSN last-4. This is a classic ETL bug where similarly-structured columns
(both 4-digit numeric strings) were swapped.

### Runtime Impact

- **Current:** No API-visible impact because `LoanSummaryDto` doesn't include SSN last-4.
- **Migration risk:** If migration code trusts this field for record matching or identity
  verification, it will silently match on phone digits instead of SSN digits.
- **Compliance risk:** This column is labeled as SSN data (PII) but contains non-PII phone data.
  Data governance processes may apply unnecessary PII restrictions or, worse, fail to protect
  actual SSN data elsewhere because they believe it's already captured here.

### Column Mapping Reference

From `data/mappings/column_mappings.md` (line 51):
> `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK

The mapping correctly drops this field. The fix is to ensure no pre-migration logic relies on it.

---

## RCA-3: Delinquent Loan Marked as Active (ANO-003)

### Symptom

Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'`. The API reports
this loan as "Active" with no indication of delinquency.

### Code Path Trace

```
LoanController.getAllLoans() / getLoan(id)
  → LoanService.getAllLoans() / getLoanById(loanAccountNumber)  [line 48-63]
    → toLoanSummary(acct, product)                              [line 103-118]
      → expandStatusCode(acct.getStatusCode())                  [line 112]
        → "ACT" → "Active"                                     [line 169-170]
      → acct.getDelinquencyDays() is NEVER CALLED               ← *** gap ***

LoanSummaryDto fields:
  → status: "Active"
  → (no delinquencyDays field exists in the DTO)
```

### Where It Fails

1. **`LoanService.toLoanSummary()`** (line 103-118) calls `expandStatusCode()` but never reads
   `acct.getDelinquencyDays()`. Delinquency information is completely ignored during DTO
   construction.

2. **`LoanSummaryDto`** (LoanSummaryDto.java) has no `delinquencyDays` field, so even if the
   service read it, there's no place to put it.

3. **`expandStatusCode()`** (line 167-175) maps codes mechanically without cross-referencing
   other fields. It cannot detect the inconsistency between `ACT` status and non-zero
   delinquency days.

4. The repository layer (`LegacyLoanAccountRepository.findByStatusCode()`) allows querying by
   status, but there's no query for delinquent loans — no `findByDelinquencyDaysGreaterThan()`
   exists.

### Root Cause

The legacy CDW system updates `LN_DLQ_DAYS` via a nightly batch process that counts days since
last payment. However, `LN_STAT_CD` is only updated by a separate business workflow that requires
manual review or a threshold trigger (e.g., 30 or 60 days). The two fields are maintained by
different processes with different update frequencies and thresholds, causing them to be
inconsistent during the gap between delinquency detection and status change.

### Runtime Impact

- **API Response:** `GET /api/loans` returns this loan with `status: "Active"` — a consumer
  cannot distinguish it from a loan in good standing.
- **Risk management:** Automated dashboards or alerts that filter by status "Active" will include
  this delinquent loan in the healthy portfolio.
- **Regulatory reporting:** Delinquent loans must be reported separately; this loan would be
  misclassified.
- **Payment processing:** The November payment for this loan (PMT-2025110003) was received 17
  days late with a $47.50 late fee, corroborating the delinquency. But the loan status does
  not reflect this history.

### Column Mapping Reference

From `data/mappings/column_mappings.md`:
- `LN_STAT_CD → status` (VARCHAR 15) — "Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE"
- `LN_DLQ_DAYS → delinquency_days` (INTEGER) — "Parse string → integer"

Both fields are mapped to the modern schema. The fix should validate consistency between them
before and after migration.
