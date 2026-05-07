# Root Cause Analysis — Top 3 Critical Data Anomalies

> **Generated:** 2026-05-07
> **Related:** [DATA_ANOMALY_REPORT.md](DATA_ANOMALY_REPORT.md)

---

## RCA-1: Payment Component Arithmetic Mismatch (ANOM-001)

### Summary

Two payment records for loan `LN-2019-00142` have total amounts that do not equal the sum of their component parts. The discrepancy is exactly $400.00 in both records.

### Affected Records

| Payment ID | Total | Principal | Interest | Escrow | Late Fee | Sum(Components) | Delta |
|-----------|-------|-----------|----------|--------|----------|-----------------|-------|
| PMT-2025120001 | 1,487.02 | 456.78 | 1,074.69 | 355.55 | 0.00 | 1,887.02 | -400.00 |
| PMT-2025110001 | 1,487.02 | 454.97 | 1,076.50 | 355.55 | 0.00 | 1,887.02 | -400.00 |

All other payment records balance correctly (total = principal + interest when escrow = 0, or total = principal + interest + escrow when escrow > 0).

### Code Path Trace

1. **Repository layer** (`LegacyPaymentRepository.java`): `findByLoanAccountNumberOrderByPaymentDateDesc()` returns raw `LegacyPayment` entities. No validation is performed at this layer.

2. **Service layer** (`LoanService.java:134-147`, `toPaymentDto` method):
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
   ```
   Each field is independently parsed from its VARCHAR source. No cross-field validation is performed.

3. **Controller layer** (`LoanController.java:33-36`): `getPayments()` returns the list of `PaymentDto` directly — no integrity check.

4. **API consumer** receives `totalAmount: 1487.02` alongside `principalAmount: 456.78`, `interestAmount: 1074.69`, `escrowAmount: 355.55`. A consumer summing the components would get 1,887.02, contradicting the total field.

### Root Cause

The legacy CDW_PMT_HIST table for loan `LN-2019-00142` appears to have the `PMT_AMT` field reflecting only the P&I portion ($1,487.02 is the monthly payment from CDW_LN_ACCT), while the `PMT_ESCROW_AMT` ($355.55) was added separately — but the total was never recalculated. This is a classic ETL bug in legacy warehouse systems where the escrow component was added to the payment decomposition in a later batch process without updating the total.

### Runtime Failure Mode

No crash — the malformed data silently propagates. API consumers performing `total != principal + interest + escrow + lateFee` checks will flag these records. Financial reconciliation processes will report variances. If the total is used for GL posting and the components for sub-ledger allocation, the books will not balance.

### Column Mapping Impact

Per `data/mappings/column_mappings.md`, all payment amount fields map from `VARCHAR(15)` to `DECIMAL(10,2)`. The migration would faithfully copy the inconsistent values into the modern schema, perpetuating the error with proper types — making it harder to detect post-migration.

---

## RCA-2: Numeric String Parsing with No Error Handling (ANOM-002)

### Summary

All monetary amounts, interest rates, credit scores, term months, and percentages are stored as VARCHAR strings in the legacy schema. The service layer parses them to Java numeric types (`BigDecimal`, `Integer`) with no try/catch — a single malformed value crashes the entire API endpoint.

### Code Path Trace

1. **Schema** (`schema-legacy.sql`): Every column is `VARCHAR`. Examples:
   - `BORR_ANN_INCM VARCHAR(15)` — holds "92,500"
   - `LN_CURR_BAL VARCHAR(15)` — holds "271,432.56"
   - `BORR_CRDT_SCR VARCHAR(5)` — holds "745"
   - `LN_DLQ_DAYS VARCHAR(5)` — holds "15"

2. **Entity layer** (`LegacyBorrower.java`, `LegacyLoanAccount.java`, `LegacyPayment.java`): All fields are mapped as `String`. No validation annotations.

3. **Service layer** (`LoanService.java:152-165`):
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", "")); // throws NumberFormatException
   }

   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim()); // throws NumberFormatException
   }
   ```
   These methods handle `null` and blank strings, but any other non-numeric input (e.g., "N/A", "$285,000", "TBD", accidental alpha characters) throws an unhandled `NumberFormatException`.

4. **Controller layer**: No exception handler for `NumberFormatException`. Spring Boot's default error handling returns an HTTP 500 with a stack trace (or a generic error in production).

5. **Blast radius**: The `getAllLoans()` method at `LoanService.java:48-56` iterates over ALL loan accounts. If ONE record has a malformed amount, the entire endpoint fails — no partial results.

### Root Cause

The legacy schema uses VARCHAR for all columns (a common CDW pattern for flexibility). The service layer was written assuming all data conforms to the expected numeric format. No defensive parsing was implemented because the seed data happens to be clean. In production, legacy warehouse data commonly contains sentinel values ("N/A", "-1", "PENDING"), currency symbols ("$285,000"), or whitespace artifacts from mainframe export.

### Runtime Failure Mode

`NumberFormatException` → HTTP 500 Internal Server Error. Stack trace:
```
java.lang.NumberFormatException: Character N is neither a decimal digit number...
    at java.base/java.math.BigDecimal.<init>
    at com.workshop.loanservice.service.LoanService.parseLegacyAmount
    at com.workshop.loanservice.service.LoanService.toLoanSummary
    at com.workshop.loanservice.service.LoanService.getAllLoans
```

### Column Mapping Impact

Per `data/mappings/column_mappings.md`, the transformation requires "Remove commas, parse to decimal" for amounts and "Parse string to integer" for counts. These transformations are precisely the operations that fail without error handling. The mapping document assumes clean input but does not define fallback behavior.

---

## RCA-3: Delinquent Loan Masked by Active Status (ANOM-005)

### Summary

Loan `LN-2018-00089` has 15 delinquency days but an "ACT" (Active) status code. The service layer expands the status to "Active" without cross-checking the delinquency field, masking a delinquent loan from API consumers.

### Affected Record

| Loan | Borrower | Delinquency Days | Status Code | Expanded Status |
|------|----------|-----------------|-------------|-----------------|
| LN-2018-00089 | Michael Torres (B-10003) | 15 | ACT | "Active" |

Corroborating evidence: This loan's payments (`PMT-2025120003`, `PMT-2025110003`) show late received dates (Dec payment received 12/05, Nov payment received 11/18), consistent with a borrower who pays late.

### Code Path Trace

1. **Data layer** (`data-legacy.sql:22`): The loan record has `LN_DLQ_DAYS = '15'` and `LN_STAT_CD = 'ACT'`.

2. **Service layer** (`LoanService.java:103-118`, `toLoanSummary` method):
   ```java
   dto.setStatus(expandStatusCode(acct.getStatusCode())); // "ACT" → "Active"
   ```
   The method only reads `statusCode`. It does not read `delinquencyDays`. The delinquency field is never mapped to the `LoanSummaryDto` at all — it is silently dropped.

3. **DTO** (`LoanSummaryDto.java`): Has no `delinquencyDays` field. Even if the service wanted to expose it, the DTO has no place for it.

4. **Status expansion** (`LoanService.java:167-176`):
   ```java
   private String expandStatusCode(String code) {
       if (code == null) return "Unknown";
       return switch (code) {
           case "ACT" -> "Active";
           // ...
       };
   }
   ```
   Pure code-to-label expansion with no business logic. No cross-field validation.

5. **API response**: Consumer sees `"status": "Active"` with no delinquency indicator. The loan appears current.

### Root Cause

The legacy CDW system maintains `LN_DLQ_DAYS` and `LN_STAT_CD` as independent fields — delinquency days are updated by an automated batch process, while the status code is manually managed or updated by a different process. These two fields drifted out of sync. The service layer trusts both fields independently and does not cross-validate them.

### Runtime Failure Mode

No crash — silent data quality issue. The loan is reported as "Active" to API consumers while being 15 days delinquent. This masks risk from:
- Portfolio risk dashboards
- Regulatory reports (HMDA, Call Report delinquency buckets)
- Investor reporting (30/60/90 day delinquency classifications)
- Automated collection triggers

### Column Mapping Impact

Per `data/mappings/column_mappings.md`:
- `LN_STAT_CD` → `status` (Expand: ACT→ACTIVE, CLO→CLOSED, DFT→DEFAULT, FRB→FORBEARANCE)
- `LN_DLQ_DAYS` → `delinquency_days` (Parse string → integer)

The mapping treats them as independent fields with no cross-validation rule. Both values would be faithfully migrated to the modern schema, preserving the inconsistency.

---

## Summary of Recommended Validations

| RCA | Validation Rule | Implementation Location |
|-----|----------------|------------------------|
| RCA-1 | `total == principal + interest + escrow + lateFee` | `LegacyDataValidator.validatePaymentArithmetic()` |
| RCA-2 | Wrap all numeric parsing in try/catch with fallback | `LegacyDataValidator.safeParseAmount()`, `safeParseInteger()` |
| RCA-3 | If `delinquencyDays > 0` and `status == ACT`, flag | `LegacyDataValidator.validateLoanStatusConsistency()` |
