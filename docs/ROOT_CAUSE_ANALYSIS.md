# Root Cause Analysis: Top 3 Critical Data Anomalies

---

## RCA-1: VARCHAR Numeric Fields Cause Unhandled NumberFormatException

### Anomaly Reference
ANO-001 / ANO-005: All numeric fields (amounts, rates, scores, terms) stored as VARCHAR with comma formatting.

### Failure Path Trace

**Entry Point:** `LoanController.getAllLoans()` -> `LoanService.getAllLoans()`

1. **Repository Layer** (`LegacyLoanAccountRepository`):
   - `findAll()` returns `List<LegacyLoanAccount>` with all fields as `String` (entity maps VARCHAR columns directly).
   - No validation or filtering occurs at the repository level.

2. **Service Layer** (`LoanService.java`, line 108-111):
   ```java
   dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
   dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
   dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
   dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
   ```

3. **Parsing Methods** (`LoanService.java`, lines 152-165):
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }

   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```

### Root Cause

The parsing methods only handle two cases:
- `null` / blank -> returns zero or null
- Well-formed numeric string (with commas) -> parses successfully

**Missing handling for:**
- Dollar signs: `"$285,000"` -> `new BigDecimal("$285000")` throws `NumberFormatException`
- Spaces in numbers: `"285, 000"` -> `new BigDecimal("285 000")` throws `NumberFormatException`
- Text placeholders: `"N/A"`, `"PENDING"`, `"--"` -> throws `NumberFormatException`
- Negative amounts: `"-1,234.56"` -> actually works, but no business validation
- Multiple decimals: `"1,234.56.78"` -> throws `NumberFormatException`
- Overflow values: `"99999999999999999999"` -> succeeds but may cause downstream issues

**Column Mappings Impact** (from `data/mappings/column_mappings.md`):
- The mapping spec says "Remove commas, parse -> decimal" for amounts
- The mapping spec says "Parse string -> integer" for terms and scores
- Neither the spec nor the code accounts for malformed legacy data

### Runtime Failure Scenario

When a legacy ETL process inserts a record like:
```sql
INSERT INTO CDW_LN_ACCT VALUES ('LN-BAD', 'B-10001', 'James', 'Mitchell', '0142',
  'FXD30', '$285,000', ...);
```

The call chain:
1. `GET /api/loans` -> `LoanController.getAllLoans()`
2. `LoanService.getAllLoans()` iterates all accounts
3. `toLoanSummary()` calls `parseLegacyAmount("$285,000")`
4. `"$285,000".replace(",", "")` -> `"$285000"`
5. `new BigDecimal("$285000")` -> **throws `NumberFormatException`**
6. Exception propagates up unhandled -> **HTTP 500 Internal Server Error**
7. **All loan data becomes inaccessible**, not just the bad record

### Impact Severity
A single malformed record in any amount field makes the **entire `/api/loans` endpoint return 500**. There is no per-record error isolation.

---

## RCA-2: Missing Foreign Key Constraints Enable Orphaned Records

### Anomaly Reference
ANO-002: No FK constraints between CDW_LN_ACCT.BORR_ID -> CDW_BORR_MSTR.BORR_ID, CDW_LN_ACCT.PROD_CD -> CDW_LN_PROD.PROD_CD, CDW_PMT_HIST.LN_ACCT_NBR -> CDW_LN_ACCT.LN_ACCT_NBR.

### Failure Path Trace

**Entry Point:** `LoanController.getAllLoans()` -> `LoanService.getAllLoans()`

1. **Product Lookup** (`LoanService.java`, lines 49-51):
   ```java
   Map<String, LegacyLoanProduct> products = loanProductRepository.findAll()
       .stream()
       .collect(Collectors.toMap(LegacyLoanProduct::getProductCode, p -> p));
   ```
   This builds a map of all products keyed by product code.

2. **Loan-to-Product Join** (`LoanService.java`, line 54):
   ```java
   .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
   ```
   If `acct.getProductCode()` is `"ZZZ"` (nonexistent), `products.get("ZZZ")` returns `null`.

3. **Null Product Handling** (`LoanService.java`, line 107):
   ```java
   dto.setProductDescription(product != null ? product.getDescription() : acct.getProductCode());
   ```
   This line has a null check and falls back to the raw product code. **This specific path is partially handled.**

4. **Borrower Orphan Path** (`LoanService.java`, lines 72-87):
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
   }
   ```
   If a loan account references `BORR_ID = 'B-99999'` (nonexistent borrower), the loan will never appear in any borrower's loan list. It becomes an "invisible" loan - present in `/api/loans` but orphaned from any borrower context.

5. **Payment Orphan Path** (`LoanService.java`, lines 90-95):
   ```java
   public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
       return paymentRepository
           .findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
           .stream()
           .map(this::toPaymentDto)
           .collect(Collectors.toList());
   }
   ```
   Payments with nonexistent `LN_ACCT_NBR` will never be retrieved (no crash, but silent data loss).

### Root Cause

The legacy schema (`schema-legacy.sql`, line 8) explicitly states:
```sql
--   - No foreign key constraints
```

This is a deliberate legacy design choice. The CDW tables were likely loaded via ETL batch processes that prioritized load speed over referential integrity. The service layer has **partial** null-safety (product lookup), but no **systematic** referential integrity validation.

**Column Mappings Impact** (from `data/mappings/column_mappings.md`):
- Line 48: `BORR_ID -> borrower_id: "Lookup borrowers.id by external_id"` -- this lookup would fail for orphaned records
- Line 52: `PROD_CD -> product_id: "Lookup loan_products.id by code"` -- same issue
- Line 80: `LN_ACCT_NBR -> loan_account_id: "Lookup loan_accounts.id by account_number"` -- same issue

The migration plan assumes referential integrity exists, but the schema doesn't enforce it.

### Runtime Failure Scenario

When a legacy ETL inserts:
```sql
INSERT INTO CDW_LN_ACCT VALUES ('LN-ORPHAN', 'B-99999', 'Ghost', 'User', '0000',
  'BADPROD', '100,000', ...);
```

1. `GET /api/loans` returns a loan with `borrowerName: "Ghost User"` and `productDescription: "BADPROD"` (raw code, not expanded)
2. No borrower endpoint will ever show this loan
3. The loan appears to have no product details
4. Migration to modern schema would fail on FK constraint insertion

### Impact Severity
Orphaned records cause **silent data inconsistency** rather than crashes. Financial data appears in some views but not others, making reconciliation impossible.

---

## RCA-3: Payment Component Sum Mismatch Indicates Data Integrity Failure

### Anomaly Reference
ANO-008: Payment components (principal + interest + escrow + late_fee) do not sum to the total amount.

### Failure Path Trace

**Entry Point:** `LoanController.getPayments()` -> `LoanService.getPaymentsByLoan()`

1. **Payment Retrieval** (`LoanService.java`, lines 90-95):
   ```java
   return paymentRepository
       .findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
       .stream()
       .map(this::toPaymentDto)
       .collect(Collectors.toList());
   ```

2. **Payment DTO Mapping** (`LoanService.java`, lines 134-147):
   ```java
   private PaymentDto toPaymentDto(LegacyPayment pmt) {
       dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
       dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
       dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
       dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
       dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
       // ...
   }
   ```

3. **No Reconciliation Check**: The service blindly maps all component amounts without validating they sum to the total.

### Root Cause

Examining the seed data mathematically:

**PMT-2025120001** (LN-2019-00142, December):
| Field | Value |
|-------|-------|
| PMT_AMT (total) | 1,487.02 |
| PMT_PRIN_AMT | 456.78 |
| PMT_INT_AMT | 1,074.69 |
| PMT_ESCROW_AMT | 355.55 |
| PMT_LATE_FEE | 0.00 |
| **Component Sum** | **1,887.02** |
| **Discrepancy** | **+400.00** |

The $400.00 discrepancy appears in **both** payments for loan LN-2019-00142 (December and November), suggesting a systematic issue - likely the escrow amount of $355.55 is being double-counted or added to a payment that should not include escrow, or the total amount field was not updated when escrow was added.

**Payments for loan LN-2020-00398** sum correctly:
| PMT_AMT | Components Sum | Match? |
|---------|---------------|--------|
| 2,924.18 | 1,842.56 + 815.50 + 266.12 + 0.00 = 2,924.18 | Yes |

**Payments for loan LN-2018-00089** have zero escrow:
| PMT_AMT | Components Sum | Match? |
|---------|---------------|--------|
| 1,077.05 | 297.12 + 779.93 + 0.00 + 0.00 = 1,077.05 | Yes |

This confirms the issue is **specific to loan LN-2019-00142** and is related to escrow handling.

**Column Mappings Impact** (from `data/mappings/column_mappings.md`):
- Lines 82-86: All payment amounts are mapped with "Remove commas, parse -> decimal"
- No reconciliation rule is specified in the mapping document
- The migration would carry forward the incorrect data without flagging it

### Runtime Failure Scenario

An API consumer fetches `GET /api/loans/LN-2019-00142/payments` and receives:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```

A downstream accounting system sums the components: `456.78 + 1074.69 + 355.55 + 0.00 = 1887.02`, which doesn't match `totalAmount: 1487.02`. This causes:
1. Reconciliation failures in accounting systems
2. Incorrect amortization schedule calculations
3. Potential regulatory reporting discrepancies
4. Loss of trust in the data pipeline

### Impact Severity
Financial data integrity violation. Incorrect payment breakdowns produce **wrong amortization calculations** and **regulatory reporting errors**. The API serves this data without any warning to consumers.
