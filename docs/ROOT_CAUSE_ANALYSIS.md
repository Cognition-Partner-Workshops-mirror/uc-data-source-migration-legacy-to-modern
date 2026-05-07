# Root Cause Analysis: Top 3 Critical Data Anomalies

This document traces the three most critical data anomalies through the application code to identify where each would cause a runtime failure or incorrect API response.

---

## RCA-001: Payment Component Amounts Do Not Sum to Total (ANO-001)

### The Anomaly

Three payment records have component amounts (principal + interest + escrow + late fee) that do not equal the stated total:

```
PMT-2025120001: 456.78 + 1,074.69 + 355.55 + 0.00 = 1,887.02  (total says 1,487.02, Δ = +400.00)
PMT-2025110001: 454.97 + 1,076.50 + 355.55 + 0.00 = 1,887.02  (total says 1,487.02, Δ = +400.00)
PMT-2025110003: 295.82 + 781.23 + 0.00 + 47.50 = 1,124.55     (total says 1,077.05, Δ = +47.50)
```

### Code Path Trace

**1. Data enters via `data-legacy.sql` → H2 database**

The INSERT statements load all payment fields as VARCHAR strings. No database-level CHECK constraint validates that components sum to the total.

**2. Repository layer: `LegacyPaymentRepository.java`**

```java
List<LegacyPayment> findByLoanAccountNumberOrderByPaymentDateDesc(String loanAccountNumber);
```

The repository reads all fields from `CDW_PMT_HIST` and maps them to `LegacyPayment` entity. No validation occurs here — all fields are strings.

**3. Service layer: `LoanService.java`, lines 134-147 (`toPaymentDto` method)**

```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    PaymentDto dto = new PaymentDto();
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
    // ... no validation that components sum to total
    return dto;
}
```

Each amount is parsed independently. The method never checks `principal + interest + escrow + lateFee == total`.

**4. API response: `GET /api/loans/{loanId}/payments`**

The `PaymentDto` is serialized to JSON and returned to the client. The client receives:

```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```

An API consumer summing the components gets 1,887.02 but the `totalAmount` says 1,487.02.

### Root Cause

**Source:** The legacy data warehouse seed data contains inconsistent payment breakdowns. For loan LN-2019-00142, the escrow amount (355.55) appears to have been added to the component breakdown without adjusting the total. For PMT-2025110003, the late fee (47.50) was added without adjusting the total.

**Code gap:** `LoanService.toPaymentDto()` (line 134) performs no cross-field validation. Each field is parsed and mapped independently.

**Column mapping gap:** `column_mappings.md` (lines 82-86) maps each payment amount field independently with "Remove commas, parse → decimal" — it does not specify any cross-field integrity check.

### Impact at Runtime

- **No crash** — the data parses successfully as individual BigDecimal values.
- **Silent data corruption** — the API serves mathematically inconsistent financial data.
- **Downstream failures** — any client computing `total - principal - interest` to derive escrow gets a negative number for LN-2019-00142 payments.

---

## RCA-002: SSN Last-4 Field Contains Phone Number Digits (ANO-002)

### The Anomaly

Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` matches the last 4 digits of the corresponding borrower's phone number, not their SSN:

```
B-10001: SSN_LST4=0142, Phone=217-555-0142 → phone last 4 = 0142 ✓
B-10002: SSN_LST4=0198, Phone=503-555-0198 → phone last 4 = 0198 ✓
B-10003: SSN_LST4=0167, Phone=512-555-0167 → phone last 4 = 0167 ✓
B-10004: SSN_LST4=0134, Phone=303-555-0134 → phone last 4 = 0134 ✓
B-10005: SSN_LST4=0156, Phone=602-555-0156 → phone last 4 = 0156 ✓
```

### Code Path Trace

**1. Data enters via `data-legacy.sql`**

The INSERT into `CDW_LN_ACCT` places phone-derived digits into the `BORR_SSN_LST4` column position:

```sql
INSERT INTO CDW_LN_ACCT VALUES ('LN-2019-00142', 'B-10001', 'James', 'Mitchell', '0142', ...);
--                                                                                  ^^^^ phone last 4, NOT SSN
```

**2. Entity layer: `LegacyLoanAccount.java`, line 29-30**

```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```

The entity maps the column and names the field `borrowerSsnLast4`, reinforcing the assumption that it contains SSN data.

**3. Service layer: `LoanService.java`, lines 103-118 (`toLoanSummary` method)**

The `toLoanSummary` method does NOT use `borrowerSsnLast4` in the current DTO mapping — it is not exposed in the API response. However, the field IS available on the entity and would be used by any code that accesses `acct.getBorrowerSsnLast4()` for identity verification.

**4. Column mapping: `column_mappings.md`, line 51**

```
| `BORR_SSN_LST4` | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```

The mapping document marks this field as "dropped" for migration — which is correct. But it does not flag that the current data is wrong.

### Root Cause

**Source:** The legacy ETL process that populated `CDW_LN_ACCT` had a column mapping error in its extraction query. The query likely selected from a borrower view where the phone number field was adjacent to (or aliased similarly to) the SSN last-4 field, and the wrong column was mapped.

**Code gap:** No validation exists in the service layer to cross-reference `BORR_SSN_LST4` against the encrypted SSN in `CDW_BORR_MSTR`. The field is silently accepted.

### Impact at Runtime

- **No crash** — the field is not currently used in API responses.
- **Data migration risk** — if any migration code copies `BORR_SSN_LST4` into a modern `ssn_last_four` column, it propagates phone digits as SSN data.
- **Identity verification failure** — any future feature that uses this field for customer verification (e.g., "please confirm the last 4 of your SSN") will fail 100% of the time.
- **Compliance risk** — misrepresenting phone digits as SSN data could trigger regulatory findings.

---

## RCA-003: Numeric String Parsing Has No Error Handling (ANO-003)

### The Anomaly

All numeric values in the legacy schema are stored as VARCHAR. The service layer parses them with `BigDecimal(String)` and `Integer.parseInt(String)` with no try-catch. Any non-numeric value causes an unhandled exception.

### Code Path Trace

**1. Schema: `schema-legacy.sql`**

Every numeric column is declared as VARCHAR:

```sql
BORR_CRDT_SCR   VARCHAR(5),         -- credit score as string
BORR_ANN_INCM   VARCHAR(15),        -- annual income as string with commas
LN_ORIG_AMT     VARCHAR(15),        -- original amount as string
LN_INT_RT       VARCHAR(8),         -- interest rate as string "5.250"
PMT_AMT         VARCHAR(15),        -- total payment as string
```

**2. Service layer parsing methods: `LoanService.java`, lines 152-165**

```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // ← throws NumberFormatException
}

private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // ← throws NumberFormatException
}

private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // ← throws NumberFormatException
}
```

All three methods:
- ✅ Handle null and blank strings
- ❌ Do NOT handle non-numeric strings
- ❌ Do NOT handle currency symbols (`$285,000`)
- ❌ Do NOT handle percentage signs (`4.750%`)
- ❌ Do NOT handle text values (`N/A`, `TBD`, `PENDING`)
- ❌ Do NOT handle locale-specific formats (`285.000,00`)

**3. Call sites in `toLoanSummary` (line 103) and `toBorrowerDto` (line 120):**

```java
// toLoanSummary — called by getAllLoans() and getLoanById()
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));

// toBorrowerDto — called by getAllBorrowers() and getBorrowerById()
dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
```

**4. Controller layer: `LoanController.java` and `BorrowerController.java`**

Neither controller has exception handling. The `RuntimeException` / `NumberFormatException` propagates to Spring's default error handler, which returns a generic 500 response.

### Root Cause

**Source:** The parsing methods were written assuming well-formed legacy data. While the current seed data IS well-formed, the legacy DW is an external system — the application has no control over what values appear in future loads.

**Code gap:** The three parsing methods in `LoanService.java` (lines 152-165) lack try-catch blocks. There is also no global exception handler for `NumberFormatException`.

**Column mapping gap:** `column_mappings.md` specifies transformations like "Remove commas, parse → decimal" but does not address error cases or fallback behavior.

### Impact at Runtime

- **API crash:** A single bad numeric value in ANY loan account, borrower, or payment record causes the corresponding `GET` endpoint to return HTTP 500.
- **Cascading failure on list endpoints:** `GET /api/loans` calls `parseLegacyAmount()` for every loan. One bad record kills the entire list response — not just that one record.
- **No error isolation:** Because `getAllLoans()` uses `stream().map(...)`, the `NumberFormatException` aborts the entire stream. There is no skip-bad-record logic.
- **No observability:** The exception is not caught or logged with context (which record, which field), making it difficult to diagnose in production.
