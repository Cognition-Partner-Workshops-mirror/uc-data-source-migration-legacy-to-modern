# Root Cause Analysis — Top 3 Critical Data Anomalies

---

## 1. ANO-001: Payment Component Amounts Do Not Sum to Total

### Symptom
Three payment records have `PMT_AMT` values that do not equal the sum of
`PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`.

### Code Path Trace

**Entry point:** `LoanController.getPayments()` → `LoanService.getPaymentsByLoan()`

```
LoanService.java:90-95
  → paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
  → .map(this::toPaymentDto)
```

**Translation layer:** `LoanService.toPaymentDto()` (line 134-147)

```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // "1,487.02" → 1487.02
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // "456.78" → 456.78
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // "1,074.69" → 1074.69
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // "355.55" → 355.55
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // "0.00" → 0.00
```

Each field is parsed independently via `parseLegacyAmount()` (line 152-155). There is
**no cross-field validation** — the method never checks whether the components add up
to the total.

**Repository layer:** `LegacyPaymentRepository` (Spring Data JPA) does a simple `SELECT *`
with no computed columns or validation. The entity `LegacyPayment` maps all fields as raw
`String` — the mismatch is invisible at the JPA level.

**Column mappings:** `column_mappings.md` (lines 82-86) specifies each amount maps
independently to a `DECIMAL(10,2)` column in the modern schema. There is no documented
constraint requiring the sum to match the total.

### Root Cause

The legacy ETL process that populated `CDW_PMT_HIST` applied the payment total and
component amounts from different source systems or calculation points without a
reconciliation step. For payments PMT-2025120001 and PMT-2025110001, the escrow amount
of $355.55 appears to have been added to the components but not reflected in the total
(discrepancy is exactly $400.00 — suggesting the total was calculated without escrow, then
escrow was added as a separate component). For PMT-2025110003, the late fee of $47.50 was
appended to the components after the total was computed.

### Runtime Failure Mode

- **No crash** — the code parses each field successfully.
- **Silent data corruption** — the API returns a `PaymentDto` where `totalAmount` ≠
  `principalAmount + interestAmount + escrowAmount + lateFee`. Any downstream consumer
  performing reconciliation (e.g., accounting system, borrower statement generator) will
  encounter a discrepancy.
- **Incorrect API response:** The API faithfully returns the bad data without any warning,
  giving consumers no indication that the payment record is inconsistent.

### Fix Location

`LoanService.toPaymentDto()` — add a post-mapping validation that compares the sum of
components to the total, logging a warning and flagging the record if they differ.

---

## 2. ANO-002: SSN Last-4 Digits Systematically Match Phone Number Last-4

### Symptom
100% of `BORR_SSN_LST4` values in `CDW_LN_ACCT` match the last 4 digits of the
corresponding borrower's phone number in `CDW_BORR_MSTR`.

### Code Path Trace

**Entity mapping:** `LegacyLoanAccount.java` (line 29-30)

```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```

**Service usage:** `LoanService.toLoanSummary()` (line 103-117) does **not** use
`borrowerSsnLast4` in the DTO output — the field is loaded by JPA but never surfaced.
However, it exists in the entity and could be accessed by any future code or direct
database queries.

**Repository layer:** `LegacyLoanAccountRepository` does not query by `BORR_SSN_LST4`,
so the corrupted field is not used for lookups today.

**Column mappings:** `column_mappings.md` (line 51) marks `BORR_SSN_LST4` as `*(dropped)*`
in the modern schema — meaning the migration plan already intends to discard this field.
However, if migration validation uses this field to cross-check identity before dropping it,
the corruption would propagate.

**Cross-table verification:**

| CDW_LN_ACCT.BORR_SSN_LST4 | CDW_BORR_MSTR.BORR_PH_NBR | Phone Last-4 | Match? |
|----------------------------|----------------------------|--------------|--------|
| 0142                       | 217-555-0142               | 0142         | Yes    |
| 0198                       | 503-555-0198               | 0198         | Yes    |
| 0167                       | 512-555-0167               | 0167         | Yes    |
| 0134                       | 303-555-0134               | 0134         | Yes    |
| 0156                       | 602-555-0156               | 0156         | Yes    |

### Root Cause

The legacy ETL or data entry process that populated the denormalized `BORR_SSN_LST4`
column in `CDW_LN_ACCT` used the wrong source column. Instead of extracting the last 4
digits from the borrower's SSN (stored encrypted in `BORR_SSN_ENCR`), it extracted the
last 4 digits from `BORR_PH_NBR`. This is likely a column-mapping error in the original
ETL job — the phone number field was adjacent to or similarly named as the SSN field in
the source system.

### Runtime Failure Mode

- **No crash** — the field is loaded but not currently surfaced in API responses.
- **Security risk** — if any future code uses `borrowerSsnLast4` for identity verification
  (a common pattern in banking), it would accept phone number digits as valid SSN
  verification, completely defeating the security check.
- **Migration risk** — if pre-migration validation uses this field to cross-check borrower
  identity, it will produce false confidence in data that is actually phone number data.

### Fix Location

`LegacyDataValidator` — add validation that cross-checks `BORR_SSN_LST4` against
`BORR_PH_NBR`. If they match, flag the SSN field as untrusted and log a critical warning.
The denormalized field should never be used for identity verification.

---

## 3. ANO-003: Delinquency Days > 0 with Active Loan Status

### Symptom
Loan `LN-2018-00089` has `LN_DLQ_DAYS = '15'` but `LN_STAT_CD = 'ACT'`, with
corroborating late payment evidence.

### Code Path Trace

**Entry point:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()`

**Translation layer:** `LoanService.toLoanSummary()` (line 103-117)

```java
dto.setStatus(expandStatusCode(acct.getStatusCode()));  // "ACT" → "Active"
```

The `expandStatusCode()` method (line 167-176) maps `"ACT"` → `"Active"` without checking
any other fields. The `LN_DLQ_DAYS` field is loaded into the entity but **never read** in
`toLoanSummary()` — it is completely ignored. The `LoanSummaryDto` has no delinquency-related
field.

**Delinquency evidence in payments:**

```
PMT-2025110003 (for LN-2018-00089):
  PMT_DT = '11/01/2025'        (due date)
  PMT_RECV_DT = '11/18/2025'   (received 17 days late)
  PMT_LATE_FEE = '47.50'       (late fee charged)
```

The payment record corroborates the 15-day delinquency. The service layer reads this
payment via `toPaymentDto()` and includes the late fee, but there is no logic connecting
payment lateness back to loan status.

**Column mappings:** `column_mappings.md` (line 63) maps `LN_DLQ_DAYS` →
`delinquency_days` as `INTEGER`. The status mapping (line 62) expands
`ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE` — there is no intermediate
delinquent-but-active state defined.

### Root Cause

The loan status and delinquency days are maintained by separate processes in the legacy
system. The delinquency days counter is updated by a nightly batch job that calculates
days past due, while the loan status code is only updated when delinquency crosses a
major threshold (typically 90+ days for "DFT"/Default). The 15-day delinquency falls below
the threshold for a status change, so the loan remains "ACT" despite being delinquent.
The schema and service layer have no concept of a "delinquent but active" state.

### Runtime Failure Mode

- **No crash** — the status code parses correctly.
- **Incorrect API response** — the loan appears as "Active" with no delinquency indicator.
  An API consumer checking loan health would see a clean status and have no visibility
  into the 15-day delinquency.
- **Regulatory risk** — portfolio risk reports that aggregate by status would classify this
  loan as performing, understating delinquency exposure.

### Fix Location

`LoanService.toLoanSummary()` — parse `LN_DLQ_DAYS` and validate against status code.
Add delinquency information to the DTO. If delinquency > 0 and status is "ACT", log a
warning and consider enriching the status to indicate the delinquency condition.
