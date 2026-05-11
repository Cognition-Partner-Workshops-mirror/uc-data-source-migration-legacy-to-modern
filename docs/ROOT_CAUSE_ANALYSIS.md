# Root Cause Analysis — Top 3 Critical Data Anomalies

> **Generated:** 2026-05-11  
> **Scope:** Service layer (`LoanService.java`), repository layer, column mappings (`data/mappings/column_mappings.md`), seed data

---

## RCA-001: Payment Amount Component Mismatch (ANO-001)

### Anomaly Summary

In 3 of 10 payment records, the sum of `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` does not equal `PMT_AMT` (the stated total). Two records are overstated by exactly $400.00, and one by exactly $47.50.

### Code Path Trace

**1. Data ingestion:** `data-legacy.sql` → H2 in-memory database at startup via `spring.sql.init.data-locations`.

**2. Repository call:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` retrieves raw `LegacyPayment` entities with all amounts as `String` fields.

**3. Service translation — `LoanService.toPaymentDto()` (line 134–147):**
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
    ...
}
```
Each amount is independently parsed via `parseLegacyAmount()`. There is **no cross-validation** that the components sum to the total.

**4. API response:** `LoanController.getPayments()` returns the list of `PaymentDto` objects as JSON. The API consumer receives inconsistent financial data with no indication of the discrepancy.

### Root Cause

The service layer performs a **pass-through translation** — it converts strings to `BigDecimal` but does not enforce any business invariants. The `toPaymentDto()` method trusts the source data completely. There is no validation layer between the repository and the DTO assembly.

The $400 discrepancy on `PMT-2025120001` and `PMT-2025110001` suggests the interest amount (`PMT_INT_AMT`) was incorrectly populated in the legacy system — both records have interest that is ~$400 higher than what would balance the equation. This pattern (identical delta across consecutive months) points to a systematic upstream ETL error, likely an incorrect interest calculation formula in the CDW load process.

The $47.50 discrepancy on `PMT-2025110003` exactly equals the late fee. This suggests the legacy system has two different conventions for `PMT_AMT`: some records include late fees in the total, others do not. The inconsistent convention was never reconciled.

### Where This Causes Runtime Failure

- **`GET /api/loans/{loanId}/payments`** returns payment records where component amounts do not add up to the total. Any consumer that cross-checks (e.g., a reconciliation system, a tax reporting engine) will flag discrepancies.
- No exception is thrown — the failure is **silent data corruption** in the API response.

### Recommended Service-Layer Fix

Add a `validatePaymentAmounts()` method in `LoanService` that runs after parsing:
- Compute `expected = principal + interest + escrow + lateFee`
- Compare to `total`; if mismatch exceeds a tolerance (e.g., $0.01), log a warning and flag the record
- Optionally recalculate the total from components and annotate the response

---

## RCA-002: SSN Last-4 / Phone Number Data Contamination (ANO-002)

### Anomaly Summary

All 5 loan accounts have `BORR_SSN_LST4` values that match the last 4 digits of the borrower's phone number instead of their actual SSN last 4.

### Code Path Trace

**1. Schema:** `CDW_LN_ACCT.BORR_SSN_LST4` is `VARCHAR(4)` — a denormalized field meant to store the last 4 digits of the borrower's SSN for quick identity verification.

**2. Column mapping** (`data/mappings/column_mappings.md`, line 51):
```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```
The migration plan correctly identifies this as a denormalized field to be dropped. However, the **current production code still reads and exposes it**.

**3. Entity:** `LegacyLoanAccount.java` maps it as `borrowerSsnLast4` (line 29–30):
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```

**4. Service usage:** `LoanService.toLoanSummary()` does **not** currently include `borrowerSsnLast4` in the DTO response, so the contaminated data is not directly exposed via the API. However:
- The field is accessible on the entity and could be used by any future code
- The entity is loaded into memory with the contaminated value
- Any audit or logging that includes the entity would expose phone digits as SSN digits

### Root Cause

The contamination occurred in the **legacy CDW ETL pipeline** (upstream of this application). When the denormalized `CDW_LN_ACCT` table was populated, the ETL script likely had a column-mapping error: it pulled the last 4 digits of `BORR_PH_NBR` (phone number) instead of `BORR_SSN_ENCR` (encrypted SSN). The 100% correlation across all 5 records (every SSN-last-4 matches phone-last-4) confirms this is systematic, not random.

The application code has no validation to detect this because:
1. `BORR_SSN_LST4` is treated as an opaque string — there is no cross-reference check
2. The schema has no CHECK constraint or FK relationship to validate SSN-last-4 against the borrower master

### Where This Causes Runtime Failure

- **Not a runtime exception**, but a **data integrity and compliance failure**.
- If any code path exposes or uses `borrowerSsnLast4` for identity verification (e.g., customer support lookup, loan servicing verification), it will be comparing phone digits, not SSN digits — leading to false matches/mismatches.
- Compliance risk: if this field is reported as SSN data in regulatory filings, it constitutes misrepresentation of PII.

### Recommended Service-Layer Fix

Add a validation that cross-references `BORR_SSN_LST4` against known non-SSN fields (phone last 4, zip code) and flags matches as potentially contaminated. In the service layer, do not expose or rely on this field until the upstream data is corrected.

---

## RCA-003: Null Values in Required Fields Cause Silent Data Corruption (ANO-003)

### Anomaly Summary

The legacy schema has no `NOT NULL` constraints on any non-PK column. The service layer does not validate for null required fields before processing, leading to string concatenation with `null` literals and silent zero-substitution for missing amounts.

### Code Path Trace

**1. Schema:** Every column in every table (except PKs) is nullable `VARCHAR`. Example from `schema-legacy.sql`:
```sql
BORR_FST_NM     VARCHAR(50),   -- no NOT NULL
BORR_LST_NM     VARCHAR(50),   -- no NOT NULL
```

**2. Service — `toBorrowerDto()` (LoanService.java, line 120–132):**
```java
private BorrowerDto toBorrowerDto(LegacyBorrower borrower) {
    String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
    dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
    ...
}
```
If `getFirstName()` returns `null`, Java string concatenation produces `"null R. Mitchell"`. The method checks `middleInitial` for null but **does not check** `firstName` or `lastName`.

**3. Service — `toLoanSummary()` (LoanService.java, line 103–118):**
```java
dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
        + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
```
Any null property field produces output like `"742 Elm Street, null, null null"`.

**4. Service — `parseLegacyAmount()` (LoanService.java, line 152–155):**
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}
```
This silently converts `null` amounts to `$0.00`. A loan with a missing `LN_ORIG_AMT` would be reported as a $0 loan — a catastrophic misrepresentation.

**5. Service — `parseLegacyInteger()` (LoanService.java, line 162–165):**
```java
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());
}
```
Returns `null` for missing credit scores, which is then set on the DTO. Downstream consumers expecting a non-null integer will get a `NullPointerException` during unboxing.

### Root Cause

The service layer was written assuming the legacy data would always have values in critical fields. The `null` handling that does exist (e.g., for `middleInitial`, for amount parsing) is inconsistent:
- Some fields get explicit null checks (middleInitial)
- Some get null-to-zero conversion (amounts)
- Some get no null handling at all (first/last name, property address fields)

The **modern schema** (`data/modern-schema/modern_tables.sql`) correctly marks these as `NOT NULL`:
```sql
first_name      VARCHAR(50) NOT NULL,
last_name       VARCHAR(50) NOT NULL,
original_amount DECIMAL(12, 2) NOT NULL,
```
But the legacy schema has no such constraints, and the service layer does not compensate.

### Where This Causes Runtime Failure

1. **`GET /api/borrowers/{id}`** — If borrower has null first/last name, API returns `"null null"` as the full name.
2. **`GET /api/loans`** — If a loan has null original amount, API returns `$0.00` — a silent misrepresentation.
3. **`GET /api/borrowers/{id}`** — If credit score is null, the Integer `null` could cause `NullPointerException` in JSON serialization or downstream consumers.
4. **`GET /api/loans`** — If property address fields are null, the concatenated address becomes `"null, null, null null"`.

### Recommended Service-Layer Fix

Add a `validateRequiredFields()` method for each entity type that checks critical fields before processing:
- For `LegacyBorrower`: require non-null `firstName`, `lastName`, `borrowerId`
- For `LegacyLoanAccount`: require non-null `borrowerId`, `productCode`, `originalAmount`, `currentBalance`, `interestRate`, `statusCode`
- For `LegacyPayment`: require non-null `loanAccountNumber`, `totalAmount`, `paymentDate`

Records with null required fields should be logged as anomalies and either excluded from results or returned with a data-quality warning flag.

---

## Summary of Root Causes

| RCA | Anomaly | Root Cause Category | Failure Mode |
|---|---|---|---|
| RCA-001 | Payment component mismatch | No business-rule validation in service layer | Silent data corruption in API response |
| RCA-002 | SSN/phone contamination | Upstream ETL column-mapping error + no cross-reference validation | PII compliance risk, incorrect identity verification |
| RCA-003 | Null required fields | Missing NOT NULL in schema + inconsistent null handling in service | "null" strings in names, $0 amounts, NPE risk |
