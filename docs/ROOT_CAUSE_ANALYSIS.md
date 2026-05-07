# Root Cause Analysis — Top 3 Critical Anomalies

This document traces the three most critical data anomalies through the application code to identify exactly where they cause runtime failures or incorrect API responses.

---

## RCA-1: All-VARCHAR Schema — Universal Parsing Risk (ANOM-010)

### Anomaly Summary

Every column in the legacy CDW schema is defined as `VARCHAR`, including fields that semantically represent integers (`LN_TERM_MOS`, `BORR_CRDT_SCR`, `LN_DLQ_DAYS`), decimals (`LN_INT_RT`, `LN_LTV_PCT`), currency amounts (`LN_ORIG_AMT`, `LN_CURR_BAL`), and dates (`LN_ORIG_DT`, `BORR_DOB_DT`). The database enforces no type constraints.

### Code Trace

**Entry point:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()` (line 48)

```
LoanService.java:48-56
public List<LoanSummaryDto> getAllLoans() {
    ...
    return loanAccountRepository.findAll().stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
}
```

**Failure path:** `toLoanSummary()` (line 103) calls parsing methods on every record:

```
LoanService.java:108-110
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
```

**Root cause method:** `parseLegacyDecimal()` (line 157):

```
LoanService.java:157-160
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());
}
```

This method only guards against `null` and blank strings. Any non-numeric string (e.g., `"TBD"`, `"N/A"`, `"5.250%"`) throws `java.lang.NumberFormatException`.

**Same pattern in:** `parseLegacyAmount()` (line 152) and `parseLegacyInteger()` (line 162).

### Runtime Failure

`parseLegacyInteger()` is called from `toBorrowerDto()` (line 129):

```
LoanService.java:129
dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
```

`Integer.parseInt()` throws `NumberFormatException` for any non-integer string. Since this is called inside a `.stream().map()` chain in `getAllBorrowers()` (line 67), **a single bad borrower record crashes the entire `/api/borrowers` endpoint**.

### Column Mappings Reference

From `data/mappings/column_mappings.md`:
- `BORR_CRDT_SCR` VARCHAR(5) → `credit_score` INTEGER — "Parse string → integer"
- `LN_INT_RT` VARCHAR(8) → `interest_rate` DECIMAL(5,3) — "Parse string → decimal"
- `PROD_TERM_MOS` VARCHAR(5) → `term_months` INTEGER — "Parse string → integer"

All these transformations assume the source data is well-formed, which the VARCHAR schema does not guarantee.

### Impact

- **Scope:** All 4 API endpoints (`/api/loans`, `/api/loans/{id}`, `/api/loans/{id}/payments`, `/api/borrowers`, `/api/borrowers/{id}`)
- **Failure mode:** Unhandled `NumberFormatException` → HTTP 500 Internal Server Error
- **Blast radius:** One bad record poisons the entire list endpoint (no per-record error isolation)

---

## RCA-2: Comma-Formatted Numeric Strings (ANOM-002)

### Anomaly Summary

Currency amounts are stored with comma thousand-separators as strings: `'285,000'`, `'1,487.02'`, `'92,500'`. The parsing code strips commas, but has no protection against other formatting variations common in legacy data warehouses (dollar signs, spaces, parentheses for negatives, currency codes).

### Code Trace

**Entry point:** `LoanController.getAllLoans()` → `LoanService.toLoanSummary()` (line 103)

```
LoanService.java:108
dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
```

**Root cause method:** `parseLegacyAmount()` (line 152):

```
LoanService.java:152-155
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}
```

The method only strips commas. Consider these realistic legacy data values:

| Input | After `.replace(",", "")` | `new BigDecimal()` result |
|---|---|---|
| `"285,000"` | `"285000"` | `285000` (correct) |
| `"$285,000"` | `"$285000"` | **NumberFormatException** |
| `" 285,000 "` | `" 285000 "` | **NumberFormatException** (no `.trim()`) |
| `"285,000.00-"` | `"285000.00-"` | **NumberFormatException** |
| `"(1,487.02)"` | `"(1487.02)"` | **NumberFormatException** |
| `"N/A"` | `"N/A"` | **NumberFormatException** |

**Payment path:** `toPaymentDto()` (line 134) calls `parseLegacyAmount()` for 5 separate fields per payment record:

```
LoanService.java:139-143
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
```

### Column Mappings Reference

From `data/mappings/column_mappings.md`:
- `BORR_ANN_INCM` VARCHAR(15) → `annual_income` DECIMAL(12,2) — "Remove commas, parse → decimal"
- `LN_ORIG_AMT` VARCHAR(15) → `original_amount` DECIMAL(12,2) — "Remove commas, parse → decimal"

The mappings document acknowledges the comma-removal step but assumes no other formatting issues exist.

### Runtime Failure

If the legacy data warehouse upstream system changes its export format (e.g., adds a dollar sign, uses parentheses for negative amounts, or includes trailing spaces), all financial amount fields across all 4 tables will fail to parse.

The `parseLegacyAmount()` method is called **23 times** across the three translation methods (`toLoanSummary`: 4 calls, `toPaymentDto`: 5 calls per payment, `toBorrowerDto`: 0 calls — but annual income in `CDW_BORR_MSTR` also has commas and is never parsed by the current API).

### Impact

- **Scope:** All loan and payment endpoints
- **Failure mode:** `NumberFormatException` → HTTP 500
- **Data risk:** The current seed data works, but any format variation in production data will cause silent failures

---

## RCA-3: No Foreign Key Constraints — Orphaned Records (ANOM-005)

### Anomaly Summary

The legacy schema has **zero foreign key constraints**. `CDW_LN_ACCT.BORR_ID` is not constrained to exist in `CDW_BORR_MSTR.BORR_ID`. `CDW_LN_ACCT.PROD_CD` is not constrained to exist in `CDW_LN_PROD.PROD_CD`. `CDW_PMT_HIST.LN_ACCT_NBR` is not constrained to exist in `CDW_LN_ACCT.LN_ACCT_NBR`.

### Code Trace

**Path 1 — Orphaned product code:**

`LoanService.getAllLoans()` (line 48):

```
LoanService.java:49-51
Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
        .stream()
        .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
```

Then in `toLoanSummary()` (line 107):

```
LoanService.java:107
dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
```

If a loan account references `PROD_CD = 'XYZ'` which doesn't exist in `CDW_LN_PROD`, the `products.get(acct.getProductCode())` returns `null`. The code **silently falls back** to using the raw product code as the description. This masks a data integrity issue — the API consumer sees `"XYZ"` as the product description instead of an error.

**Path 2 — Orphaned borrower ID (NullPointerException):**

`LoanService.getBorrowerById()` (line 72):

```
LoanService.java:72-88
public BorrowerDto getBorrowerById(String borrowerId) {
    LegacyBorrower borrower = borrowerRepository.findById(borrowerId)
            .orElseThrow(() -> new RuntimeException("Borrower not found: " + borrowerId));
    ...
    List<LoanSummaryDto> loans = loanAccountRepository.findByBorrowerId(borrowerId)
            .stream()
            .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
            .collect(Collectors.toList());
    dto.setLoans(loans);
    return dto;
}
```

This path is safe for the borrower lookup (it throws if not found). However, consider the reverse scenario: a loan account in `CDW_LN_ACCT` references `BORR_ID = 'B-99999'` which doesn't exist in `CDW_BORR_MSTR`. When `getAllLoans()` returns this loan, the denormalized `BORR_FST_NM` and `BORR_LST_NM` in the loan account table are used for the borrower name (line 106):

```
LoanService.java:106
dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
```

If the denormalized name fields are `null` (possible since the schema allows it), the concatenation produces `"null null"` as the borrower name — a visible data quality issue in the API response.

**Path 3 — Orphaned payment loan account:**

`LoanService.getPaymentsByLoan()` (line 90) queries payments by loan account number. If `CDW_PMT_HIST` contains a payment referencing `LN_ACCT_NBR = 'LN-NONEXISTENT'`, the payment is never retrieved because queries always start from a known loan ID. However, if a batch reporting job iterates over all payments, orphaned payments would appear without a parent loan context.

### Column Mappings Reference

From `data/mappings/column_mappings.md`:
- `BORR_ID` VARCHAR(20) → `borrower_id` BIGINT — "Lookup borrowers.id by external_id"
- `PROD_CD` VARCHAR(10) → `product_id` BIGINT — "Lookup loan_products.id by code"
- `LN_ACCT_NBR` VARCHAR(20) → `loan_account_id` BIGINT — "Lookup loan_accounts.id by account_number"

All three mappings require FK resolution during migration. Orphaned records will cause migration failures at INSERT time when the modern schema enforces FK constraints.

### Impact

- **Scope:** Loan listing endpoint and migration process
- **Failure mode (current):** Silent data quality degradation (product code as description, `"null null"` borrower names)
- **Failure mode (migration):** Hard failure at INSERT — FK constraint violation when migrating orphaned records to the modern schema
- **Detection difficulty:** High — orphaned records produce degraded-but-functional responses, not crashes

---

## Summary of Root Causes

| RCA | Anomaly | Root Cause | Failure Type | Fix Priority |
|---|---|---|---|---|
| RCA-1 | ANOM-010 | No try-catch around `Integer.parseInt()`, `new BigDecimal()` | Runtime crash (500) | Immediate |
| RCA-2 | ANOM-002 | `parseLegacyAmount()` only strips commas, no other sanitization | Runtime crash (500) | Immediate |
| RCA-3 | ANOM-005 | No FK validation; silent fallback masks orphaned records | Silent data corruption + migration failure | Before migration |
