# Root Cause Analysis - Top 3 Critical Anomalies

> **Generated:** 2026-05-07
> **Scope:** ANO-001 (Payment Sum Mismatch), ANO-002 (Numeric Parse Failures), ANO-003 (Date Format Failures)

---

## RCA-001: Payment Component Sum Mismatch (ANO-001)

### Failure Path

**Entry point:** `GET /api/loans/{loanId}/payments`
**Controller:** `LoanController.getPayments()` (LoanController.java:34)
**Service method:** `LoanService.getPaymentsByLoan()` (LoanService.java:90-95)
**Translation method:** `LoanService.toPaymentDto()` (LoanService.java:134-147)

### Code Trace

```
LoanController.getPayments(loanId)
  -> LoanService.getPaymentsByLoan(loanAccountNumber)
    -> paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
    -> for each LegacyPayment:
         toPaymentDto(pmt)
           -> dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()))
           -> dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()))
           -> dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()))
           -> dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()))
           -> dto.setLateFee(parseLegacyAmount(pmt.getLateFee()))
```

### Root Cause

The `toPaymentDto()` method at LoanService.java:134-147 performs a **field-by-field copy** from the legacy entity to the DTO without any cross-field validation. Each amount is independently parsed via `parseLegacyAmount()`, but there is no check that:

```
totalAmount == principalAmount + interestAmount + escrowAmount + lateFee
```

**Specific failures in the seed data:**

1. **PMT-2025120001 and PMT-2025110001** (Loan LN-2019-00142, James Mitchell):
   - These are payments for a 30-Year Fixed mortgage (`FXD30`).
   - The monthly payment is `1,487.02`, which matches `PMT_AMT`.
   - However, `PMT_ESCROW_AMT = 355.55` is recorded, and `456.78 + 1,074.69 + 355.55 = 1,887.02`.
   - The escrow balance on this loan is `3,245.80`, suggesting escrow is actively tracked.
   - **Root cause:** The escrow amount was added to the payment components but was **not included** in the original total when the legacy system computed `PMT_AMT`. The legacy CDW likely computed `PMT_AMT = principal + interest` only, then a separate process appended escrow data to the breakdown columns without updating the total.

2. **PMT-2025110003** (Loan LN-2018-00089, Michael Torres):
   - `PMT_LATE_FEE = 47.50` but `PMT_AMT = 1,077.05` equals only `principal + interest` (295.82 + 781.23 = 1,077.05).
   - **Root cause:** The late fee was assessed after the payment was recorded. The legacy system updated `PMT_LATE_FEE` but did not recalculate `PMT_AMT`. This is consistent with the 17-day late receipt date (ANO-007).

### Where This Causes Incorrect API Responses

The `PaymentDto` exposes all five fields independently to API consumers. A consumer that sums the components will get a different number than `totalAmount`. There is **no validation, no warning, and no reconciliation** in the current code path.

### Column Mapping Impact

Per `data/mappings/column_mappings.md` (lines 82-86), all five amount fields are mapped to `DECIMAL(10,2)` in the modern schema. The mismatch will be faithfully migrated, embedding the error permanently in the modern database.

---

## RCA-002: Numeric String Parsing with No Error Handling (ANO-002)

### Failure Path

**Entry points:** `GET /api/loans`, `GET /api/loans/{id}`, `GET /api/borrowers`, `GET /api/borrowers/{id}`, `GET /api/loans/{loanId}/payments`
**Service methods:** All translation methods in LoanService.java
**Critical methods:**
- `parseLegacyAmount()` (LoanService.java:152-155)
- `parseLegacyDecimal()` (LoanService.java:157-160)
- `parseLegacyInteger()` (LoanService.java:162-165)

### Code Trace

```java
// LoanService.java:152-155
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // <-- THROWS on non-numeric
}

// LoanService.java:157-160
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // <-- THROWS on non-numeric
}

// LoanService.java:162-165
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // <-- THROWS on non-numeric
}
```

### Root Cause

The parse methods implement only a **null/blank guard** but have **no try-catch** for `NumberFormatException`. The VARCHAR schema allows any string to be stored in numeric columns. The methods assume all non-blank values are well-formed numbers (with at most commas for thousands separators).

**Call sites that would fail:**

| Method | Called From | Line | Fields Parsed |
|--------|------------|------|---------------|
| `parseLegacyAmount` | `toLoanSummary` | 108-111 | originalAmount, currentBalance, monthlyPayment |
| `parseLegacyDecimal` | `toLoanSummary` | 110 | interestRate |
| `parseLegacyInteger` | `toBorrowerDto` | 129 | creditScore |
| `parseLegacyAmount` | `toPaymentDto` | 139-143 | totalAmount, principalAmount, interestAmount, escrowAmount, lateFee |

**Failure cascade for `GET /api/loans`:**

```
LoanController.getAllLoans()
  -> LoanService.getAllLoans()
    -> loanAccountRepository.findAll()          // returns all 5 loans
    -> .stream().map(acct -> toLoanSummary(...)) // if ANY loan has bad data
      -> parseLegacyAmount("$285,000")           // NumberFormatException!
      -> UNCAUGHT -> propagates up stream pipeline
      -> UNCAUGHT -> propagates to controller
      -> Spring returns HTTP 500 Internal Server Error
```

A single corrupt record in any of the 5 loans causes the **entire list endpoint** to fail. There is no per-record error isolation.

### Column Mapping Impact

Per `data/mappings/column_mappings.md`, 17+ columns require numeric parsing (lines 22, 37-38, 53-57, 63-65, 71, 82-86). Each is a potential failure point during migration.

---

## RCA-003: Date String Fields with No Parse Validation (ANO-003)

### Failure Path

**Entry points:** All API endpoints
**Service methods:** `toLoanSummary()`, `toBorrowerDto()`, `toPaymentDto()`
**Current behavior:** Date strings are passed through without parsing
**Migration target:** Parse `MM/DD/YYYY` -> `DATE` / `TIMESTAMP`

### Code Trace

```java
// LoanService.java:113 - date passed through as raw string
dto.setOriginationDate(acct.getOriginationDate());

// LoanService.java:138 - date passed through as raw string
dto.setPaymentDate(pmt.getPaymentDate());
```

The DTOs declare dates as `String`:
```java
// LoanSummaryDto.java:18
private String originationDate;

// PaymentDto.java:12
private String paymentDate;
```

### Root Cause

The current service layer performs **no date parsing at all**. Date fields flow from the VARCHAR legacy column straight through the entity to the DTO as raw strings. This works today because the API contract exposes dates as strings, but it creates two problems:

1. **No validation at any layer:** A date value of `"13/45/2025"` or `"UNKNOWN"` would pass through to the API response unchallenged. There is no point in the code that verifies the format.

2. **Migration time bomb:** The column mappings document (lines 12, 23-24, 40-41, 58-61, 72-73, 81, 89-92) specifies `Parse MM/DD/YYYY -> DATE` for 15 date columns across all 4 tables. When migration code is written, it will call `LocalDate.parse(value, DateTimeFormatter.ofPattern("MM/dd/yyyy"))`. Any non-conforming date will throw `DateTimeParseException` and halt the migration.

**Fields at risk (15 total):**

| Table | Columns |
|-------|---------|
| CDW_BORR_MSTR | BORR_DOB_DT, BORR_CRET_DT, BORR_UPDT_DT |
| CDW_LN_PROD | PROD_EFF_DT, PROD_EXP_DT |
| CDW_LN_ACCT | LN_ORIG_DT, LN_MAT_DT, LN_1ST_PMT_DT, LN_NXT_PMT_DT, LN_CRET_DT, LN_UPDT_DT |
| CDW_PMT_HIST | PMT_DT, PMT_RECV_DT, PMT_PROC_DT, PMT_CRET_DT, PMT_UPDT_DT |

### Where This Would Cause Runtime Failure

When migration Task 2 (from `docs/MIGRATION_TASKS.md`) is implemented, the migration service will need to parse every date field. With the current data, the seed data dates are well-formed. But in a production CDW with thousands of records, any single malformed date halts the entire migration batch. There is no validation step to identify problematic records beforehand.

### Recommended Architecture

Add a `LegacyDataValidator` service that pre-validates all records before translation. For dates, attempt parsing and collect errors per record. For the current API layer, add date parsing to the translation methods with try-catch to ensure consistent format in responses.

---

## Summary: Interconnection of Root Causes

All three critical anomalies share a common architectural root cause: **the service layer trusts the legacy data implicitly**. There is no validation layer between the repository (which reads raw VARCHAR data) and the translation methods (which assume specific formats).

```
Repository (raw strings) --> Translation (assumes format) --> DTO (exposes to API)
                         ^                                ^
                     No validation                   No error handling
```

The fix is to insert a validation layer:

```
Repository --> Validator (checks format, logs anomalies) --> Translation (safe parsing) --> DTO
```

This validator should:
1. Check numeric fields are parseable before calling `BigDecimal` / `Integer.parseInt`
2. Check date fields match `MM/DD/YYYY` before passing through or parsing
3. Check payment component sums match totals
4. Check referential integrity (BORR_ID, PROD_CD, LN_ACCT_NBR exist)
5. Log all anomalies with record ID, field name, raw value, and expected format
