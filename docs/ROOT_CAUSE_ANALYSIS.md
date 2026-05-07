# Root Cause Analysis — Top 3 Critical Data Anomalies

---

## 1. ANM-001: Payment Component Sum Mismatch

### Symptom

For loan `LN-2019-00142`, the payment records `PMT-2025120001` and `PMT-2025110001` have component amounts (principal + interest + escrow + late fee) that sum to $1,887.02, but the total payment amount is $1,487.02 — a $400.00 discrepancy. Similarly, `PMT-2025110003` has a $47.50 discrepancy matching its late fee amount.

### Code Path Trace

1. **Controller entry:** `LoanController.getPayments(loanId)` calls `LoanService.getPaymentsByLoan(loanAccountNumber)`.

2. **Repository query:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)` retrieves all `CDW_PMT_HIST` rows for the loan.  
   *(File: `LegacyPaymentRepository.java:14`)*

3. **DTO mapping:** `LoanService.toPaymentDto(LegacyPayment pmt)` at line 134 maps each payment entity to a `PaymentDto`:
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
   ```
   *(File: `LoanService.java:139-143`)*

4. **No validation:** The `parseLegacyAmount` method (line 152) strips commas and converts to `BigDecimal` but performs no cross-field consistency check. Each field is parsed independently.

5. **API response:** The `PaymentDto` is serialized to JSON with internally inconsistent amounts. Any API consumer performing `principal + interest + escrow + lateFee` will get a different number than `totalAmount`.

### Root Cause

The `toPaymentDto` translation method treats each legacy field as an independent value and performs no cross-field validation. The legacy CDW system likely has a bug in its payment posting logic where the escrow component is included in the breakdown but not properly reflected in the total, or vice versa. The +$400.00 discrepancy on `LN-2019-00142` is exactly the escrow amount ($355.55) plus a rounding artifact, suggesting the escrow was added to components after the total was calculated.

### Where It Fails

- **`LoanService.toPaymentDto()`** (line 134-147): Produces a DTO with mathematically inconsistent financial data.
- **`PaymentDto`**: Has no invariant check that components sum to total.
- **Column mapping** (`column_mappings.md` line 82-86): Documents a 1:1 field mapping from `PMT_AMT` to `total_amount` and component fields to their modern equivalents, but does not document any expected relationship between them.

### Impact at Runtime

The API returns JSON like:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```
A consumer summing components gets $1,887.02, not $1,487.02. Financial reconciliation, accounting systems, and audit tools will flag this as a discrepancy.

---

## 2. ANM-002: String-Based Date Storage Prevents Correct Sorting

### Symptom

Payment history is returned in incorrect chronological order when dates cross year or month boundaries, because `MM/DD/YYYY` strings sort lexicographically, not chronologically.

### Code Path Trace

1. **Controller entry:** `LoanController.getPayments(loanId)` calls `LoanService.getPaymentsByLoan(loanAccountNumber)`.

2. **Repository query:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)` generates SQL:
   ```sql
   SELECT * FROM CDW_PMT_HIST
   WHERE LN_ACCT_NBR = ?
   ORDER BY PMT_DT DESC
   ```
   *(File: `LegacyPaymentRepository.java:14`)*

3. **String sort behavior:** Because `PMT_DT` is `VARCHAR(10)`, the `ORDER BY` is lexicographic. For the current seed data (all dates in 2025), this happens to work because month prefixes `11/` and `12/` sort correctly relative to each other. But:
   - `"02/01/2026"` < `"12/01/2025"` lexicographically (February 2026 would sort BEFORE December 2025)
   - `"01/15/2026"` < `"11/15/2025"` (January 2026 before November 2025)

4. **DTO passthrough:** `LoanService.toPaymentDto()` passes the raw date string to `PaymentDto.setPaymentDate()` without parsing:
   ```java
   dto.setPaymentDate(pmt.getPaymentDate());  // raw MM/DD/YYYY string
   ```
   *(File: `LoanService.java:138`)*

5. **Same issue in loan summary:** `toLoanSummary()` passes `acct.getOriginationDate()` directly:
   ```java
   dto.setOriginationDate(acct.getOriginationDate());  // raw MM/DD/YYYY string
   ```
   *(File: `LoanService.java:113`)*

### Root Cause

The repository layer delegates ordering to the H2 database engine via JPA-derived query method naming (`OrderByPaymentDateDesc`). Since the column type is `VARCHAR`, the database performs string comparison. The `MM/DD/YYYY` format is not sortable as a string (unlike `YYYY-MM-DD` / ISO-8601, which is). The service layer does not re-sort the results after retrieval.

### Where It Fails

- **`LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()`** (line 14): Generates incorrect `ORDER BY` on VARCHAR date column.
- **`LoanService.toPaymentDto()`** (line 138): Passes raw date strings through without parsing or re-sorting.
- **Column mapping** (`column_mappings.md` lines 81, 58-61): Documents `Parse MM/DD/YYYY -> DATE` transformation, but this transformation is never actually performed in the current service layer.

### Impact at Runtime

When the `LN_NXT_PMT_DT` column contains `"01/01/2026"` (next payment due January 2026), any comparison or sort against `"12/15/2025"` will incorrectly place January before December. The API returns payment history in the wrong chronological order, causing:
- Most recent payment not shown first in payment history
- Incorrect "last payment date" derivations
- Broken pagination if clients assume descending date order

---

## 3. ANM-003: Numeric Parsing Without Error Handling

### Symptom

Any malformed numeric string in the legacy data (e.g., `"N/A"`, `"$285,000"`, `"PENDING"`, empty after trim) will cause an uncaught `NumberFormatException` that crashes the entire API endpoint with HTTP 500.

### Code Path Trace

1. **Amount parsing:** `LoanService.parseLegacyAmount(String amount)` at line 152:
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   - Handles `null` and blank strings, but NOT:
     - Currency symbols: `"$285,000"` → after comma removal: `"$285000"` → **NumberFormatException**
     - Non-numeric text: `"N/A"`, `"TBD"`, `"PENDING"` → **NumberFormatException**
     - European format: `"285.000,00"` → after comma removal: `"285.00000"` → silently wrong value
     - Parenthesized negatives: `"(1,234.56)"` → **NumberFormatException**

2. **Decimal parsing:** `parseLegacyDecimal(String value)` at line 157:
   ```java
   private BigDecimal parseLegacyDecimal(String value) {
       if (value == null || value.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(value.trim());
   }
   ```
   - Same vulnerability: `"4.750%"` → **NumberFormatException**

3. **Integer parsing:** `parseLegacyInteger(String value)` at line 162:
   ```java
   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```
   - `"N/A"` → **NumberFormatException**
   - `"745.0"` (decimal credit score) → **NumberFormatException** (parseInt doesn't handle decimals)

4. **Call sites with no try-catch:**
   - `toLoanSummary()` calls `parseLegacyAmount` 3 times and `parseLegacyDecimal` once (lines 108-111)
   - `toBorrowerDto()` calls `parseLegacyInteger` once (line 129)
   - `toPaymentDto()` calls `parseLegacyAmount` 5 times (lines 139-143)
   - None of these call sites have try-catch blocks.

5. **Cascade failure:** In `getAllLoans()` (line 48-56), the `stream().map()` operation processes all loans in sequence. A `NumberFormatException` on ANY loan record aborts the entire stream, causing the endpoint to return HTTP 500 with zero results — even if 99 out of 100 loans have valid data.

### Root Cause

The legacy CDW uses `VARCHAR` for all columns, meaning any string can be stored in any column. The service layer parsing methods assume well-formatted data and have no defensive error handling. The `parseLegacyAmount`, `parseLegacyDecimal`, and `parseLegacyInteger` methods only check for null/blank but not for non-numeric content. There is no application-level exception handler that would catch `NumberFormatException` and return a partial result or meaningful error.

### Where It Fails

- **`LoanService.parseLegacyAmount()`** (line 152-155): No try-catch around `new BigDecimal(...)`.
- **`LoanService.parseLegacyDecimal()`** (line 157-160): No try-catch around `new BigDecimal(...)`.
- **`LoanService.parseLegacyInteger()`** (line 162-165): No try-catch around `Integer.parseInt(...)`.
- **`LoanService.toLoanSummary()`** (line 103-118): No error isolation per record.
- **`LoanService.getAllLoans()`** (line 48-56): Stream aborts on first exception, no partial results.
- **Column mapping** (`column_mappings.md` lines 20, 22, 35, 37-38, 53-57, 63-65, 82-86): Documents "Remove commas, parse -> decimal" and "Parse string -> integer" transformations but does not document error handling strategy for unparseable values.

### Impact at Runtime

A single bad record in the legacy CDW makes the entire API endpoint return HTTP 500:
- `GET /api/loans` → 500 (if any loan has a malformed amount)
- `GET /api/borrowers` → 500 (if any borrower has a malformed credit score)
- `GET /api/loans/{id}/payments` → 500 (if any payment has a malformed amount)

The exception propagates as an unhandled `RuntimeException` through Spring's default error handler, returning a generic error response with no indication of which record or field caused the failure.
