# Root Cause Analysis: Top 3 Critical Data Anomalies

> **Generated:** 2026-05-07
> **Scope:** Tracing ANO-001, ANO-002, ANO-003 from `DATA_ANOMALY_REPORT.md` through the codebase

---

## RCA-001: Numeric VARCHAR Parsing Failures (ANO-001)

### Failure Path

```
API Request: GET /api/loans
  → LoanController.getAllLoans()
    → LoanService.getAllLoans()
      → loanAccountRepository.findAll()          // returns raw VARCHAR strings
      → toLoanSummary(acct, product)
        → parseLegacyAmount(acct.getOriginalAmount())   // "285,000" → strips commas → OK
        → parseLegacyAmount(malformed_value)             // "$285,000" → BOOM
```

### Code Trace

**1. Entity Layer** (`LegacyLoanAccount.java:35-36`)
```java
@Column(name = "LN_ORIG_AMT")
private String originalAmount;   // raw VARCHAR from DB — no validation
```
The entity faithfully maps the VARCHAR column to a Java String. No validation occurs at this layer.

**2. Service Layer** (`LoanService.java:108`)
```java
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
```

**3. Parsing Method** (`LoanService.java:152-155`)
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}
```

### Root Cause

The `parseLegacyAmount()` method only handles two cases:
1. **null/blank** → returns `BigDecimal.ZERO`
2. **comma-formatted number** → strips commas, parses as BigDecimal

It does NOT handle:
- Currency symbols (`$285,000`)
- Alphabetic text (`N/A`, `PENDING`, `TBD`)
- Multiple decimal points (`1,234.56.78`)
- Negative numbers with parentheses (`(500.00)` — accounting notation)
- Whitespace-padded values (`  285,000  ` — `replace(",","")` runs before `trim()`)

The `parseLegacyDecimal()` method (`LoanService.java:157-160`) has the same vulnerability but does NOT strip commas — so `"5.250"` works but `"5,250"` would throw.

The `parseLegacyInteger()` method (`LoanService.java:162-165`) is worst: `Integer.parseInt()` throws on commas, decimals, or any non-digit character. A credit score of `"N/A"` crashes the borrower API.

### Runtime Failure

```
java.lang.NumberFormatException: Character $ is neither a decimal digit number,
decimal point, nor "e" notation exponential mark.
  at java.base/java.math.BigDecimal.<init>
  at com.workshop.loanservice.service.LoanService.parseLegacyAmount(LoanService.java:154)
  at com.workshop.loanservice.service.LoanService.toLoanSummary(LoanService.java:108)
```

This propagates as an unhandled 500 Internal Server Error to the API consumer. **All loans in the response fail** because `getAllLoans()` processes them in a stream — one bad record kills the entire list.

### Column Mappings Context

Per `data/mappings/column_mappings.md`:
- `LN_ORIG_AMT` (VARCHAR 15) → `original_amount` (DECIMAL 12,2): "Remove commas, parse → decimal"
- `BORR_CRDT_SCR` (VARCHAR 5) → `credit_score` (INTEGER): "Parse string → integer"
- `BORR_ANN_INCM` (VARCHAR 15) → `annual_income` (DECIMAL 12,2): "Remove commas, parse → decimal"

The mappings document acknowledges the transformation is needed but the current implementation lacks defensive error handling.

---

## RCA-002: Date Format Inconsistency and Pass-Through (ANO-002)

### Failure Path

```
API Request: GET /api/loans/LN-2019-00142
  → LoanController.getLoan("LN-2019-00142")
    → LoanService.getLoanById("LN-2019-00142")
      → toLoanSummary(acct, product)
        → dto.setOriginationDate(acct.getOriginationDate())   // raw string pass-through!
```

### Code Trace

**1. Entity Layer** (`LegacyLoanAccount.java:50-51`)
```java
@Column(name = "LN_ORIG_DT")
private String originationDate;   // "02/15/2019" — raw MM/DD/YYYY string
```

**2. Service Layer** (`LoanService.java:113`)
```java
dto.setOriginationDate(acct.getOriginationDate());
```
The date is passed directly from the entity to the DTO with **zero parsing or validation**.

**3. DTO Layer** (`LoanSummaryDto.java:18`)
```java
private String originationDate;   // receives raw legacy format
```

**4. Payment dates** — same pattern (`LoanService.java:138`):
```java
dto.setPaymentDate(pmt.getPaymentDate());   // raw pass-through
```

### Root Cause

Unlike amount fields (which at least get parsed through `parseLegacyAmount()`), **date fields receive no transformation at all**. They flow straight from the legacy VARCHAR column through the entity to the DTO to the JSON API response.

This means:
1. **API consumers receive `MM/DD/YYYY` format** — non-standard, not ISO-8601, and ambiguous internationally (is `01/02/2025` January 2nd or February 1st?)
2. **No validation** — if the legacy warehouse contains `'00/00/0000'`, `'TBD'`, or `'2025-01-15'` (ISO format), it passes through silently
3. **Sorting fails** — `findByLoanAccountNumberOrderByPaymentDateDesc` in `LegacyPaymentRepository.java:14` sorts by the VARCHAR `PMT_DT` column. String comparison of `MM/DD/YYYY` does NOT produce chronological order (e.g., `'02/01/2026' < '12/01/2025'` in string sort)

### Column Mappings Context

Per `data/mappings/column_mappings.md`:
- `LN_ORIG_DT` (VARCHAR 10) → `origination_date` (DATE): "Parse MM/DD/YYYY → DATE"
- `PMT_DT` (VARCHAR 10) → `payment_date` (DATE): "Parse MM/DD/YYYY → DATE"

The mappings explicitly call for date parsing, but the current service layer skips this transformation entirely.

### Incorrect API Response

```json
{
  "loanAccountNumber": "LN-2019-00142",
  "originationDate": "02/15/2019",    // should be "2019-02-15"
  "status": "Active"
}
```

Consumers expecting ISO-8601 dates (the universal REST API convention) will fail to parse these values.

---

## RCA-003: Missing Foreign Key Validation — Null Product Causes Silent Degradation (ANO-003)

### Failure Path

```
API Request: GET /api/loans
  → LoanController.getAllLoans()
    → LoanService.getAllLoans()
      → products = loanProductRepository.findAll()
                    .stream()
                    .collect(Collectors.toMap(...))          // build product lookup map
      → loanAccountRepository.findAll()
          .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
                                              // ↑ returns null if product code doesn't exist
```

### Code Trace

**1. Product Lookup** (`LoanService.java:49-51`)
```java
Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
        .stream()
        .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
```
Builds an in-memory map of all products by code.

**2. Lookup with potential null** (`LoanService.java:54`)
```java
.map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
```
If `acct.getProductCode()` is `"BADCODE"` or `null`, `products.get()` returns `null`.

**3. Null handling in toLoanSummary** (`LoanService.java:107`)
```java
dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
```
When product is null, the DTO gets the raw product code (`"BADCODE"`) instead of a description. This is a **silent fallback** — no exception, no log, no indication of a data quality issue.

**4. Single-loan path** (`LoanService.java:61-62`)
```java
LegacyLoanProduct product = loanProductRepository.findById(acct.getProductCode())
        .orElse(null);
```
Explicitly maps missing product to `null`. Same silent degradation.

**5. Payment orphan risk** (`LoanService.java:90-94`)
```java
public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
    return paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
            .stream()
            .map(this::toPaymentDto)
            .collect(Collectors.toList());
}
```
If a payment references a non-existent loan account number, this method just returns an empty list — there's no way for consumers to know whether the loan has no payments or doesn't exist.

### Root Cause

The schema (`schema-legacy.sql:8`) explicitly documents "No foreign key constraints." The service layer compensates by using `orElse(null)` and null-check ternaries, but this converts data integrity violations into silent data quality degradation:

| Scenario | Expected Behavior | Actual Behavior |
|---|---|---|
| Loan references non-existent product | Error or warning | Silently shows raw code |
| Loan references non-existent borrower | Error or warning | No detection; stale denormalized data used |
| Payment references non-existent loan | Error or warning | Empty list returned |

### Column Mappings Context

Per `data/mappings/column_mappings.md`:
- `BORR_ID` (VARCHAR 20) → `borrower_id` (BIGINT): "Lookup borrowers.id by external_id"
- `PROD_CD` (VARCHAR 10) → `product_id` (BIGINT): "Lookup loan_products.id by code"
- `LN_ACCT_NBR` (VARCHAR 20) → `loan_account_id` (BIGINT): "Lookup loan_accounts.id by account_number"

All three FK relationships require lookup-based resolution during migration. The current code does not validate that these lookups succeed, meaning orphaned records will silently produce incorrect or incomplete migration output.

---

## Summary of Fixes Required

| RCA | Anomaly | Fix Location | Fix Type |
|---|---|---|---|
| RCA-001 | Numeric parsing | `LoanService.parseLegacyAmount()`, `parseLegacyDecimal()`, `parseLegacyInteger()` | Try-catch with logging and fallback defaults |
| RCA-002 | Date pass-through | `LoanService.toLoanSummary()`, `toPaymentDto()` | Parse MM/DD/YYYY → ISO-8601 with validation |
| RCA-003 | Missing FK validation | `LoanService.getAllLoans()`, `getLoanById()`, `getPaymentsByLoan()` | Validate references exist; log warnings for orphans |
