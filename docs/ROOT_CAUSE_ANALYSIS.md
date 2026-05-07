# Root Cause Analysis — Top 3 Critical Anomalies

---

## RCA 1: Payment Component Sum Mismatch

### Trace

```
LoanController.getPayments()
  → LoanService.getPaymentsByLoan(loanAccountNumber)  [line 90]
    → toPaymentDto(pmt)  [line 134]
      → parseLegacyAmount(pmt.getTotalAmount())       [line 139]
      → parseLegacyAmount(pmt.getPrincipalAmount())    [line 140]
      → parseLegacyAmount(pmt.getInterestAmount())     [line 141]
      → parseLegacyAmount(pmt.getEscrowAmount())       [line 142]
      → parseLegacyAmount(pmt.getLateFee())            [line 143]
```

### Analysis

The service parses each payment component independently and sets them on `PaymentDto`. There is **no validation** that:

```
totalAmount == principalAmount + interestAmount + escrowAmount + lateFee
```

Each field is parsed in isolation via `parseLegacyAmount()` (line 152-155), which strips commas and converts to `BigDecimal`. The resulting `PaymentDto` is returned directly to API consumers.

### Root Cause

The legacy ETL process likely had a bug where:
- **Escrow was double-counted** in the component breakdown but not in the total, OR
- **The total was calculated before escrow/late fees were added** to the component fields.

The service layer **blindly trusts** the data from `CDW_PMT_HIST` without any cross-validation.

### Evidence

- **PMT-2025120001** (LN-2019-00142): Components sum to `456.78 + 1,074.69 + 355.55 + 0.00 = 1,887.02`, but `PMT_AMT = 1,487.02`. Difference: **$400.00**.
- **PMT-2025110001** (LN-2019-00142): Components sum to `454.97 + 1,076.50 + 355.55 + 0.00 = 1,887.02`, but `PMT_AMT = 1,487.02`. Difference: **$400.00** (same pattern — escrow of $355.55 appears to be the excess plus rounding).
- **PMT-2025110003** (LN-2018-00089): Late fee `$47.50` present in components but not reflected in total (`1,077.05` vs `1,124.55`). Difference: **$47.50**.

### Runtime Impact

API returns `PaymentDto` where `totalAmount != sum of components`. Any downstream consumer performing reconciliation will flag discrepancies. Column mappings (`data/mappings/column_mappings.md` lines 82-86) show all these fields map to `DECIMAL` — **the mismatch will persist into the modern schema** unless caught at ingestion time.

### Recommended Remediation

1. Add `LegacyDataValidator.validatePaymentComponents()` call in `toPaymentDto()`.
2. Surface warnings in `PaymentDto.warnings` field.
3. Reconcile with source general ledger before migration.

---

## RCA 2: Unguarded Numeric Parsing

### Trace

```
BorrowerController.getBorrower(id)
  → LoanService.getBorrowerById(borrowerId)  [line 72]
    → toBorrowerDto(borrower)  [line 120]
      → parseLegacyInteger(borrower.getCreditScore())  [line 129]
        → Integer.parseInt(value.trim())  [line 164]
```

### Analysis

`parseLegacyInteger` (lines 162-165) calls `Integer.parseInt()` with **no try-catch**:

```java
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // throws on non-numeric input
}
```

If `BORR_CRDT_SCR` contains `"N/A"`, `""` (non-blank whitespace), or a comma-formatted number like `"1,200"`, it throws `NumberFormatException`.

Similarly, `parseLegacyAmount` (lines 152-155) would fail on values like `"$285,000"` (dollar sign) or `"PENDING"`:

```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // only strips commas
}
```

### Root Cause

The service **assumes all legacy string data is well-formed**. The schema uses `VARCHAR` for everything (`schema-legacy.sql` line 27: `"credit score as string"`), so there is **no DB-level type enforcement**. Any upstream system or manual data entry can insert arbitrary strings into numeric fields.

### Evidence

- Current seed data happens to contain clean numeric strings, but the schema places no constraints.
- `parseLegacyAmount` only strips commas — not dollar signs, spaces, or other formatting characters.
- `parseLegacyDecimal` (lines 157-160) doesn't strip commas at all — only trims whitespace.

### Runtime Impact

Unhandled `NumberFormatException` propagates as **HTTP 500 Internal Server Error**. There is no global exception handler to catch this gracefully. A single malformed record can make an entire endpoint unusable (e.g., `getAllLoans()` would fail if any loan has a bad amount).

### Recommended Remediation

1. Replace all three parse methods with `LegacyDataValidator` equivalents that use try-catch.
2. Return fallback values (`BigDecimal.ZERO`, `null`) on parse failure.
3. Log warnings with field name and raw value for monitoring.

---

## RCA 3: SSN Last-4 Contains Phone Last-4

### Trace

```
LegacyLoanAccount.java:
  @Column(name = "BORR_SSN_LST4")
  private String borrowerSsnLast4;  [lines 29-31]

LoanService.java:
  // Field is mapped but NEVER read in any service method.
  // toLoanSummary() does not reference borrowerSsnLast4.

column_mappings.md:
  BORR_SSN_LST4 → *(dropped)* [line 51]
```

### Analysis

The `BORR_SSN_LST4` field in `CDW_LN_ACCT` is mapped in the JPA entity (`LegacyLoanAccount.java` lines 29-31) but is **never read by any service method** in `LoanService.java`. The field is marked as "dropped" in the migration column mappings (`column_mappings.md` line 51).

### Root Cause

The legacy ETL or data entry process **populated `BORR_SSN_LST4` from the wrong source field** (phone number instead of SSN). Evidence:

| Borrower | Phone Number | SSN_LST4 | Match? |
|----------|-------------|----------|--------|
| B-10001 | 217-555-**0142** | **0142** | Phone last 4 |
| B-10002 | 503-555-**0198** | **0198** | Phone last 4 |
| B-10003 | 512-555-**0167** | **0167** | Phone last 4 |
| B-10004 | 303-555-**0134** | **0134** | Phone last 4 |
| B-10005 | 602-555-**0156** | **0156** | Phone last 4 |

All 5 records are affected — this is a **systematic error**, not a one-off. The ETL likely had a column mapping bug pointing to `BORR_PH_NBR` instead of the SSN source field.

### Runtime Impact

- **Currently low**: The field is not used by any service method and is marked for dropping in migration.
- **Potential high**: If any future code, report, or audit process uses this field for identity verification, it will produce incorrect results.
- **Compliance concern**: If the field is assumed to contain SSN data in audit logs or data lineage documentation, it represents a PII classification error.

### Recommended Remediation

1. Confirm field is excluded from all reports and audit trails.
2. Do not migrate this field to the modern schema (already marked "dropped").
3. Document the systematic error for compliance team review.
4. If SSN last-4 is needed in modern schema, source it from the authoritative SSN system — not from `CDW_LN_ACCT`.
