# Root Cause Analysis — Top 3 Critical Data Anomalies

This document traces the top 3 most critical anomalies through the codebase to identify
where they would cause runtime failures or incorrect API responses.

---

## 1. Payment Component Mismatch (Anomaly #1)

### Symptom

For loan `LN-2019-00142`, payment records have `PMT_AMT = 1,487.02` but the breakdown
sums to `1,887.02` (principal 456.78 + interest 1,074.69 + escrow 355.55 = 1,887.02).
The delta is exactly +400.00 on both affected records.

### Code Trace

1. **Data Ingestion** (`data-legacy.sql`, lines 27-28):
   ```sql
   INSERT INTO CDW_PMT_HIST VALUES ('PMT-2025120001', 'LN-2019-00142', '12/15/2025',
     '1,487.02', '456.78', '1,074.69', '355.55', '0.00', ...);
   ```
   The data enters the system with the inconsistency already present.

2. **Entity Layer** (`LegacyPayment.java`):
   All fields are stored as raw strings. No validation occurs at the JPA entity level.
   The entity simply maps columns to String fields without any integrity checks.

3. **Service Layer** (`LoanService.java`, lines 134-146, `toPaymentDto()`):
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
   ```
   Each component is parsed independently. **No cross-field validation** checks that
   `total = principal + interest + escrow + lateFee`.

4. **API Response** (`LoanController.java`, line 34):
   ```java
   return loanService.getPaymentsByLoan(loanId);
   ```
   The inconsistent data is returned directly to API consumers.

### Root Cause

The legacy CDW has no check constraint enforcing `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. The service layer performs no cross-field validation.
The consistent +400.00 error suggests the escrow amount was double-counted during the
original ETL load into the CDW — likely the total was set to the base payment amount
(principal + interest = ~1,131 + 356 = 1,487) while the breakdown correctly includes
escrow as a separate line item that makes the true total 1,887.02.

### Runtime Failure Mode

- **Incorrect API response:** Consumers who compute `total - (principal + interest + escrow)`
  to check "remaining fees" will get a negative number (-400.00).
- **Reconciliation failures:** Accounting systems that validate payment breakdowns will
  flag these records, requiring manual investigation.
- **No crash**, but silently wrong financial data — arguably worse than a crash since it
  may go undetected until audit.

### Fix Location

`LoanService.toPaymentDto()` — add a validation check after parsing all components:
```java
BigDecimal computedTotal = principal.add(interest).add(escrow).add(lateFee);
if (computedTotal.compareTo(total) != 0) {
    log.warn("Payment {} component mismatch: stated={}, computed={}",
             pmt.getPaymentSequenceNumber(), total, computedTotal);
    // Use computed total as the authoritative value
}
```

---

## 2. SSN Last-4 Populated with Phone Number Digits (Anomaly #2)

### Symptom

Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` matches the last 4 digits of the borrower's
phone number, not their SSN.

### Code Trace

1. **Data Ingestion** (`data-legacy.sql`, line 20):
   ```sql
   INSERT INTO CDW_LN_ACCT VALUES ('LN-2019-00142', 'B-10001', 'James', 'Mitchell',
     '0142', 'FXD30', ...);
   ```
   Borrower B-10001's phone is `217-555-0142`. The SSN last-4 field has `0142`.

2. **Entity Layer** (`LegacyLoanAccount.java`, line 30):
   ```java
   @Column(name = "BORR_SSN_LST4")
   private String borrowerSsnLast4;
   ```
   The field is treated as an opaque string — no validation that it represents SSN digits.

3. **Service Layer** (`LoanService.java`):
   The `BORR_SSN_LST4` field is **not currently used** in any DTO mapping. It is not
   exposed in `toLoanSummary()` or any other translation method. However, the field exists
   on the entity and would be used if:
   - A future feature adds identity verification
   - The modern schema migration maps this field (per `column_mappings.md`, it's marked
     as "dropped" — but only because the modern design uses borrower FK instead)

4. **Column Mappings** (`data/mappings/column_mappings.md`, line 51):
   ```markdown
   | `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
   ```
   The migration plan correctly drops this field, but doesn't flag the data quality issue.

### Root Cause

The ETL process that originally populated `CDW_LN_ACCT` extracted the wrong field from the
source system. Instead of:
```
SSN_FULL → last 4 digits → BORR_SSN_LST4
```
It performed:
```
PHONE_NUMBER → last 4 digits → BORR_SSN_LST4
```

This is likely a column-index offset error in the original ETL mapping — the phone column
was adjacent to or near the SSN column in the source extract.

### Runtime Failure Mode

- **No immediate crash** — the field isn't currently consumed by the API.
- **Silent data corruption risk:** If any downstream system (fraud detection, identity
  matching, regulatory reporting) consumes `BORR_SSN_LST4` directly from the database
  (bypassing the API), they will get phone digits instead of SSN digits.
- **Migration risk:** If someone copies this data to a modern system without noting the
  anomaly, the error propagates permanently.

### Fix Location

Mark the field as unreliable in the entity with a documentation comment. Add a validation
warning in `LoanService` if the field is ever accessed. Ensure the migration plan
explicitly flags this as corrupt data that must NOT be migrated.

---

## 3. Numeric String Parsing Without Error Handling (Anomaly #3)

### Symptom

All monetary amounts and numeric values are `VARCHAR` with embedded commas. The parsing
methods have no error handling for malformed input.

### Code Trace

1. **Data Format** (`data-legacy.sql`):
   ```sql
   '285,000'    -- original amount (commas, no decimals)
   '271,432.56' -- current balance (commas + decimals)
   '4.750'      -- interest rate (no commas, but trailing zero)
   '92,500'     -- annual income (commas, no decimals)
   '745'        -- credit score (no commas, integer as string)
   ```

2. **Parsing Methods** (`LoanService.java`, lines 152-165):
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));  // LINE 154
   }

   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());  // LINE 164
   }
   ```

   **Line 154** throws `NumberFormatException` if:
   - `amount` = `"$285,000"` → after replace: `"$285000"` → NFE
   - `amount` = `"285 000"` (space separator) → after replace: `"285 000"` → NFE
   - `amount` = `"N/A"` → after replace: `"N/A"` → NFE
   - `amount` = `"(1,200.00)"` (accounting negative) → NFE

   **Line 164** throws `NumberFormatException` if:
   - `value` = `"N/A"` or `"PENDING"` or `"---"`

3. **Call Sites** (`LoanService.java`):
   - `getAllLoans()` (line 48-55): Iterates ALL loans, calls `parseLegacyAmount` for each.
     One bad record → entire list fails with 500 error.
   - `getAllBorrowers()` (line 66-69): Calls `parseLegacyInteger` for credit score of each
     borrower. One bad credit score → entire borrower list fails.
   - `getPaymentsByLoan()` (line 90-94): Parses 5 amount fields per payment. Any bad value
     crashes the entire payment history for that loan.

4. **Controller Layer** (`LoanController.java`):
   No exception handler. Spring's default error handling returns a generic 500 with stack trace
   (if `server.error.include-stacktrace=always`) or a generic error JSON.

### Root Cause

The service layer was written assuming the legacy data will always conform to the expected
format. There is no defensive parsing, no try-catch around numeric conversions, and no
per-record error isolation. The architecture treats parsing as infallible.

This is a classic "happy path only" implementation that works with curated seed data but
will fail in production where CDW data comes from multiple upstream systems with varying
data quality.

### Runtime Failure Mode

- **Complete API outage for affected endpoints:** A single malformed numeric value in any
  record causes an unhandled `NumberFormatException` that propagates up through the stream
  operation, aborting the entire collection transformation.
- **Cascading failure:** `getAllLoans()` processes all records in a single stream. One bad
  record means zero records are returned — the API returns 500 instead of the 4 good records.
- **No error isolation:** The failure gives no indication which record or field caused the error.
  Debugging requires manual inspection of all records.

### Fix Location

Wrap all parsing methods in try-catch blocks:
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    try {
        String cleaned = amount.replace(",", "").replace("$", "").trim();
        return new BigDecimal(cleaned);
    } catch (NumberFormatException e) {
        log.warn("Failed to parse amount '{}': {}", amount, e.getMessage());
        return BigDecimal.ZERO; // fallback default
    }
}
```

Add the same pattern to `parseLegacyInteger` and `parseLegacyDecimal`. This ensures
one bad record doesn't crash the entire API response.

---

## Summary of Fix Priorities

| Priority | Anomaly | Fix Type | Effort |
|----------|---------|----------|--------|
| P0 | #3 — Numeric parsing | Add try-catch + logging | Low |
| P0 | #1 — Payment mismatch | Add cross-field validation + warning | Low |
| P1 | #2 — SSN/phone confusion | Mark field untrusted + document | Low |
| P1 | #4 — Date validation | Parse dates + standardize output | Medium |
| P2 | #5 — FK validation | Add existence checks | Medium |
