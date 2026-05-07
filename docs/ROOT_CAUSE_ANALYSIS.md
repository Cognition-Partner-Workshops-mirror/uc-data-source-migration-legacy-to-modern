# Root Cause Analysis — Top 3 Critical Data Anomalies

> **Generated:** 2026-05-07
> **Scope:** Tracing ANM-001, ANM-002, and ANM-006 through the code to identify runtime failure points.

---

## RCA-1: Loose Typing — All Numeric/Date Fields as VARCHAR (ANM-001)

### Anomaly Summary

Every numeric and date value in all four CDW tables is stored as `VARCHAR`. The service layer must parse these strings into `BigDecimal`, `Integer`, or date representations at runtime.

### Code Trace

#### 1. Schema Layer (`schema-legacy.sql`)

All columns are defined as `VARCHAR`, e.g.:
```sql
BORR_CRDT_SCR   VARCHAR(5),         -- credit score as string
BORR_ANN_INCM   VARCHAR(15),        -- annual income as string with commas
LN_ORIG_AMT     VARCHAR(15),        -- original amount as string
LN_INT_RT       VARCHAR(8),         -- interest rate as string "5.250"
```

No CHECK constraints or triggers enforce that these strings contain valid numbers or dates.

#### 2. Entity Layer (`LegacyBorrower.java`, `LegacyLoanAccount.java`, `LegacyPayment.java`)

All entity fields are `String`:
```java
// LegacyLoanAccount.java:35-36
@Column(name = "LN_ORIG_AMT")
private String originalAmount;
```

JPA reads raw VARCHAR values directly into Java `String` fields — no validation occurs here.

#### 3. Service Layer (`LoanService.java`)

Parsing happens in three private methods:

**`parseLegacyAmount()` (line 152-155):**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}
```
- Handles null/blank → returns `BigDecimal.ZERO` (silently converts missing data to $0).
- Strips commas — works for `"285,000"` and `"1,487.02"`.
- **Failure point:** Throws uncaught `NumberFormatException` for `"$285,000"`, `"N/A"`, `"285,000.00.00"`, or any non-numeric string after comma removal.

**`parseLegacyDecimal()` (line 157-160):**
```java
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());
}
```
- Does NOT strip commas — only trims whitespace.
- Used for `interestRate` parsing. If an interest rate contained commas (e.g., `"1,250"` basis points), this would throw `NumberFormatException`.

**`parseLegacyInteger()` (line 162-165):**
```java
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());
}
```
- Used for `creditScore` parsing.
- **Failure point:** Throws uncaught `NumberFormatException` for non-numeric values like `"N/A"` or `"seven-forty"`.

#### 4. Column Mappings (`data/mappings/column_mappings.md`)

The mappings document specifies transformations that are NOT implemented:
- `BORR_DOB_DT` → `date_of_birth` (DATE): "Parse MM/DD/YYYY → DATE" — **not implemented in code**
- `BORR_ANN_INCM` → `annual_income` (DECIMAL): "Remove commas, parse → decimal" — **not exposed in DTO**
- `LN_ORIG_DT` → `origination_date` (DATE): "Parse MM/DD/YYYY → DATE" — **passed as raw string**

### Root Cause

The legacy schema uses VARCHAR for all fields as a deliberate (if poor) design choice to avoid type conversion at write time. The service layer attempts runtime parsing but:
1. Has no try/catch around `BigDecimal`/`Integer` constructors — a single bad record crashes the entire API response.
2. Silently converts null/blank amounts to `$0` instead of signaling missing data.
3. Does not parse dates at all — raw `MM/DD/YYYY` strings leak into API responses.

### Runtime Failure Scenario

If a legacy data load inserts `LN_ORIG_AMT = '$285,000'` (with dollar sign), calling `GET /api/loans` would throw:
```
java.lang.NumberFormatException: Character $ is neither a decimal digit number, decimal point, nor "e" notation exponential mark.
```
This unhandled exception would return an HTTP 500 to the client, with no indication of which record caused the failure.

---

## RCA-2: No NOT NULL Constraints on Required Fields (ANM-002)

### Anomaly Summary

The legacy schema defines every non-PK column as nullable. Business-critical fields like borrower name, loan amount, status code, and SSN can be NULL.

### Code Trace

#### 1. Schema Layer (`schema-legacy.sql`)

Only the `PRIMARY KEY` columns have implicit NOT NULL:
```sql
CREATE TABLE CDW_BORR_MSTR (
    BORR_ID         VARCHAR(20) PRIMARY KEY,
    BORR_FST_NM     VARCHAR(50),        -- nullable!
    BORR_LST_NM     VARCHAR(50),        -- nullable!
    BORR_STAT_CD    VARCHAR(5),         -- nullable!
    ...
);
```

#### 2. Service Layer — Null Propagation Paths

**`toBorrowerDto()` (LoanService.java:120-132):**
```java
String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
```
- If `getFirstName()` returns `null`: fullName = `"null R. Mitchell"`.
- If `getLastName()` returns `null`: fullName = `"James R. null"`.
- Both null: fullName = `"null null"`.

**`toLoanSummary()` (LoanService.java:103-118):**
```java
dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
dto.setStatus(expandStatusCode(acct.getStatusCode()));
dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
        + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
```
- Null `originalAmount` → `parseLegacyAmount(null)` → `BigDecimal.ZERO`. A $0 loan appears valid in the API.
- Null `statusCode` → `expandStatusCode(null)` → `"Unknown"`. The loan's actual status is hidden.
- Null property fields → address becomes `"null, null, null null"`.

**`getAllLoans()` (LoanService.java:48-56):**
```java
Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
        .stream()
        .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
```
- If any `LegacyLoanProduct` has a `null` productCode, `Collectors.toMap()` throws `NullPointerException`, crashing the entire `GET /api/loans` endpoint.

#### 3. Repository Layer

JPA repositories return entities with null fields directly — no null-checking layer exists between the database and the service.

### Root Cause

The legacy DW was designed as a staging area where data completeness was not enforced at the schema level. The service layer was written assuming data would always be complete — it contains no null guards on critical fields beyond the middle initial check.

### Runtime Failure Scenario

If a borrower record is inserted with `BORR_FST_NM = NULL` and `BORR_LST_NM = NULL`:
- `GET /api/borrowers` returns `{"fullName": "null null", "creditScore": null, ...}` — the word "null" literally appears as the person's name.
- Downstream systems parsing this response might treat "null" as a real name, corrupting their own databases.

---

## RCA-3: Payment Component Amounts Don't Sum to Total (ANM-006)

### Anomaly Summary

In `CDW_PMT_HIST`, the `PMT_AMT` (total payment) should equal the sum of `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. Several records violate this invariant.

### Code Trace

#### 1. Seed Data (`data-legacy.sql`)

**PMT-2025120001 (Loan LN-2019-00142):**
```
PMT_AMT = '1,487.02'
PMT_PRIN_AMT = '456.78'
PMT_INT_AMT = '1,074.69'
PMT_ESCROW_AMT = '355.55'
PMT_LATE_FEE = '0.00'
Sum of components = 456.78 + 1,074.69 + 355.55 + 0.00 = 1,887.02
Discrepancy = 1,887.02 - 1,487.02 = +$400.00
```

The escrow amount (355.55) appears inflated or the total was not updated after escrow was added.

**PMT-2025110003 (Loan LN-2018-00089):**
```
PMT_AMT = '1,077.05'
PMT_PRIN_AMT = '295.82'
PMT_INT_AMT = '781.23'
PMT_ESCROW_AMT = '0.00'
PMT_LATE_FEE = '47.50'
Sum = 295.82 + 781.23 + 0.00 + 47.50 = 1,124.55
Discrepancy = 1,124.55 - 1,077.05 = +$47.50
```

The total equals the regular payment amount but does not include the late fee — the late fee was appended without updating the total.

#### 2. Service Layer (`LoanService.java:134-147`)

```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    PaymentDto dto = new PaymentDto();
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
    ...
}
```

Each field is parsed independently with **no cross-field validation**. The service blindly trusts that the total equals the sum of components.

#### 3. API Response Impact

`GET /api/loans/LN-2019-00142/payments` returns:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```

A consumer summing the components gets $1,887.02 — $400 more than the stated total. This is a material financial discrepancy.

#### 4. Column Mappings (`data/mappings/column_mappings.md`)

The mappings specify 1:1 field transfers with "Remove commas, parse → decimal" but no cross-field validation rule. The assumption is that source data is internally consistent.

### Root Cause

The legacy DW loads payment data from multiple upstream sources without reconciliation. The `PMT_AMT` total appears to be the contractual payment amount, while the components reflect actual allocation — including escrow and late fees that may have been added after the initial record was created. The total was never recalculated.

### Runtime Failure Scenario

- **Financial reporting:** A report summing `PMT_AMT` across all payments will understate total payments collected. A report summing components will show the correct (higher) figure. The $400 discrepancy per payment compounds across thousands of records.
- **Audit failure:** SOX or regulatory audits comparing total vs. component amounts will flag these records as reconciliation failures.
- **API consumer confusion:** Different consumers using different fields for the "total" will compute different portfolio values, leading to conflicting dashboards and reports.

---

## Summary of Root Causes

| RCA | Anomaly | Root Cause | Impact | Where It Fails |
|---|---|---|---|---|
| RCA-1 | ANM-001 | VARCHAR-for-everything schema with no type enforcement | Uncaught `NumberFormatException` crashes entire endpoints | `parseLegacyAmount()`, `parseLegacyDecimal()`, `parseLegacyInteger()` |
| RCA-2 | ANM-002 | No NOT NULL constraints, service assumes complete data | "null" appears as literal text in names; $0 amounts mask missing data | `toBorrowerDto()`, `toLoanSummary()`, `Collectors.toMap()` |
| RCA-3 | ANM-006 | Payment totals not recalculated after component changes | Material financial discrepancies in API responses | `toPaymentDto()` — no cross-validation |
