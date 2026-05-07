# Root Cause Analysis — Top 3 Critical Anomalies

This document traces the three most critical data quality anomalies through the application code to identify where each would cause a runtime failure or incorrect API response.

---

## RCA-1: VARCHAR Numeric Parsing Failures (ANM-001)

### Anomaly Summary
All numeric values (amounts, rates, scores, counts) are stored as VARCHAR strings in the legacy schema. The service layer parses these to `BigDecimal` and `Integer` without defensive error handling.

### Code Trace

#### 1. Entry Point — `LoanController.getAllLoans()` (LoanController.java:24)
```java
@GetMapping
public List<LoanSummaryDto> getAllLoans() {
    return loanService.getAllLoans();
}
```

#### 2. Service Layer — `LoanService.getAllLoans()` (LoanService.java:48–56)
```java
public List<LoanSummaryDto> getAllLoans() {
    Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
            .stream()
            .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));

    return loanAccountRepository.findAll().stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
}
```
All loan accounts are loaded and mapped in a single stream. An exception in **any** record's mapping aborts the entire operation.

#### 3. Translation Layer — `LoanService.toLoanSummary()` (LoanService.java:103–118)
```java
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
```

#### 4. Parsing Methods — (LoanService.java:152–165)
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // FAILURE POINT
}

private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // FAILURE POINT
}
```

### Root Cause
The `parseLegacyAmount()` method strips commas but does not handle:
- Currency symbols: `"$285,000"` → after comma removal: `"$285000"` → `NumberFormatException`
- Parenthetical negatives: `"(1,487.02)"` (accounting format) → `"(1487.02)"` → `NumberFormatException`
- Text values: `"N/A"`, `"PENDING"`, `"TBD"` → `NumberFormatException`
- Multiple decimals: `"1,487.02.5"` → `NumberFormatException`
- Whitespace variants: `"285, 000"` (space after comma) → `"285 000"` → `NumberFormatException`

The `parseLegacyInteger()` method has the same issue for credit scores and term months.

### Failure Mode
A single malformed value in any of the ~17 numeric fields across all loaded records causes an **unhandled `NumberFormatException`** that propagates up through the stream, through the controller, and results in a **500 Internal Server Error** for the entire API call. No individual record is skipped — the whole response fails.

### Column Mapping Reference
From `data/mappings/column_mappings.md`:
- `BORR_ANN_INCM` (VARCHAR(15)) → `annual_income` (DECIMAL(12,2)): "Remove commas, parse → decimal"
- `LN_ORIG_AMT` (VARCHAR(15)) → `original_amount` (DECIMAL(12,2)): "Remove commas, parse → decimal"
- `BORR_CRDT_SCR` (VARCHAR(5)) → `credit_score` (INTEGER): "Parse string → integer"

The mappings document acknowledges the transformation is needed but the current code does not handle parsing failures.

### Impact Assessment
- **Runtime**: 500 error on `/api/loans`, `/api/loans/{id}`, `/api/borrowers/{id}`
- **Blast radius**: One bad record takes down the entire endpoint for all users
- **Detection**: Only discoverable at runtime when the bad record is loaded

---

## RCA-2: Unvalidated Date Strings (ANM-002)

### Anomaly Summary
All date fields are stored as `VARCHAR(10)` with expected format `MM/DD/YYYY`. The service layer passes these strings through to DTOs without parsing or validating them.

### Code Trace

#### 1. Entity Layer — `LegacyLoanAccount.java:50–51`
```java
@Column(name = "LN_ORIG_DT")
private String originationDate;
```
The origination date is a raw `String` — no type safety.

#### 2. Service Layer — `LoanService.toLoanSummary()` (LoanService.java:113)
```java
dto.setOriginationDate(acct.getOriginationDate());
```
The raw string from the database is passed directly to the DTO with **zero validation or parsing**.

#### 3. DTO Layer — `LoanSummaryDto.java:18,38–39`
```java
private String originationDate;
// ...
public void setOriginationDate(String originationDate) { this.originationDate = originationDate; }
```
The DTO accepts any string. The API consumer receives whatever was in the database.

#### 4. Payment dates follow the same path — `LoanService.toPaymentDto()` (LoanService.java:138)
```java
dto.setPaymentDate(pmt.getPaymentDate());
```

### Root Cause
The application treats date fields as opaque strings throughout the entire pipeline: Entity → Service → DTO → JSON response. There is **no `DateTimeFormatter`**, no parsing, no validation anywhere in the code. The column mappings document (line 12) specifies `Parse MM/DD/YYYY → DATE` as the required transformation, but this transformation is not implemented.

This means:
1. Invalid dates like `"02/30/2025"` or `"13/45/2020"` pass through silently
2. Different formats like `"2025-02-15"` (ISO) or `"15/02/2025"` (DD/MM/YYYY) pass through without detection
3. Literal placeholders like `"00/00/0000"` or `"MM/DD/YYYY"` pass through
4. Empty strings `""` pass through (not caught by null check since the field isn't null)

### Failure Mode
- **Current behavior**: Silent data corruption — invalid dates appear in API responses
- **Migration failure**: When migrating to the modern schema (which uses `DATE` type), `DateTimeParseException` will occur for any non-conforming date string, halting the migration
- **Downstream impact**: API consumers parsing the date string will fail if the format is inconsistent

### Column Mapping Reference
From `data/mappings/column_mappings.md`:
- `BORR_DOB_DT` (VARCHAR(10)) → `date_of_birth` (DATE): "Parse MM/DD/YYYY → DATE"
- `LN_ORIG_DT` (VARCHAR(10)) → `origination_date` (DATE): "Parse MM/DD/YYYY → DATE"
- `PMT_DT` (VARCHAR(10)) → `payment_date` (DATE): "Parse MM/DD/YYYY → DATE"

All 16+ date fields require this transformation, but none are implemented.

### Impact Assessment
- **Runtime**: Silent — bad dates flow through to API responses undetected
- **Migration**: Hard blocker — any invalid date prevents row insertion into modern schema
- **Downstream**: API consumers receive unpredictable date formats

---

## RCA-3: No Foreign Key Constraints — Orphaned Records (ANM-003)

### Anomaly Summary
The legacy schema has zero foreign key constraints. Referential integrity between `CDW_LN_ACCT.BORR_ID` → `CDW_BORR_MSTR.BORR_ID`, `CDW_LN_ACCT.PROD_CD` → `CDW_LN_PROD.PROD_CD`, and `CDW_PMT_HIST.LN_ACCT_NBR` → `CDW_LN_ACCT.LN_ACCT_NBR` is not enforced.

### Code Trace

#### 1. Orphaned Loan Account (invalid PROD_CD) — `LoanService.getAllLoans()` (LoanService.java:48–56)
```java
Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
        .stream()
        .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));

return loanAccountRepository.findAll().stream()
        .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
        //                                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        //                          Returns null for unknown product codes
        .collect(Collectors.toList());
```

If `acct.getProductCode()` is `"INVALID"`, then `products.get("INVALID")` returns `null`.

#### 2. Null Product Handling — `LoanService.toLoanSummary()` (LoanService.java:107)
```java
dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
```
The null product is handled — it falls back to the raw code. **But this masks the orphaned record.** The API returns the cryptic code (e.g., `"INVALID"`) as the product description without any indication that this is an error.

#### 3. Orphaned Loan Account (invalid BORR_ID) — `LoanService.getBorrowerById()` (LoanService.java:72–88)
```java
public BorrowerDto getBorrowerById(String borrowerId) {
    LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
            .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
    // ...
    List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
            .stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
    dto.setLoans(loans);
    return dto;
}
```
This direction works — querying loans by borrower ID is fine. But the **reverse** is the problem: `getAllLoans()` returns loan records with borrower names from the denormalized fields. If a `BORR_ID` in `CDW_LN_ACCT` doesn't match any `CDW_BORR_MSTR` record, the denormalized `BORR_FST_NM`/`BORR_LST_NM` are used — which may be stale or wrong.

#### 4. Orphaned Payments — `LoanService.getPaymentsByLoan()` (LoanService.java:90–95)
```java
public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
    return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
            .stream()
            .map(this::toPaymentDto)
            .collect(Collectors.toList());
}
```
The repository queries by `LN_ACCT_NBR`. If a payment references a non-existent loan account number, it won't be returned here (since the query is loan→payments). But if someone queries all payments (not currently exposed), orphaned payments would appear. More critically, orphaned payments contribute to data inconsistency when migrating — they'll fail FK insertion into the modern `payments` table.

### Root Cause
The legacy schema (`schema-legacy.sql` line 8: `-- No foreign key constraints`) intentionally omits FK constraints — a common pattern in data warehouses for ETL performance. The application layer does not compensate with referential integrity checks. The only safeguard is the null-check on the product lookup (`product != null ? ...`), which silently degrades rather than alerting.

### Column Mapping Reference
From `data/mappings/column_mappings.md`:
- `CDW_LN_ACCT.BORR_ID` → `loan_accounts.borrower_id` (BIGINT FK): "Lookup borrowers.id by external_id"
- `CDW_LN_ACCT.PROD_CD` → `loan_accounts.product_id` (BIGINT FK): "Lookup loan_products.id by code"
- `CDW_PMT_HIST.LN_ACCT_NBR` → `payments.loan_account_id` (BIGINT FK): "Lookup loan_accounts.id by account_number"

The modern schema (`modern_tables.sql` lines 79–80, 99) enforces these as proper FK constraints. Any orphaned legacy record will fail migration.

### Impact Assessment
- **Runtime**: Silent data degradation — cryptic product codes in responses, no error
- **Migration**: Hard blocker — orphaned records fail FK insertion
- **Data integrity**: No way to detect orphaned records without explicit validation

---

## Summary

| RCA | Anomaly | Runtime Failure Mode | Migration Impact | Fix Priority |
|---|---|---|---|---|
| RCA-1 | Numeric parsing | `NumberFormatException` → 500 error, entire endpoint down | Parse failures block row migration | Highest — add try-catch with fallbacks |
| RCA-2 | Date strings unvalidated | Silent — bad dates flow to API | `DateTimeParseException` blocks migration | High — add date parsing/validation |
| RCA-3 | No FK constraints | Silent — cryptic codes in responses | FK violation blocks migration | High — add referential integrity checks |

All three anomalies share a common pattern: **the legacy schema's loose typing pushes data quality enforcement to the application layer, but the application layer does not enforce it.** The service layer's translation methods handle the happy path (well-formed data) but fail on any deviation.
