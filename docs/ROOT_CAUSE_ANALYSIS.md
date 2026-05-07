# Root Cause Analysis — Top 3 Critical Anomalies

> **Generated:** 2026-05-07
> **Scope:** Service layer (`LoanService.java`), repository layer, column mappings
> **Reference:** See `docs/DATA_ANOMALY_REPORT.md` for full anomaly catalog

---

## RCA-1: Payment Component Sum Mismatch (ANO-001)

### Anomaly

Three of ten payment records in `CDW_PMT_HIST` have component amounts (principal + interest + escrow + late fee) that do not sum to the stated `PMT_AMT` total.

### Code Path Trace

1. **Entry point:** `LoanController.getPayments()` (`LoanController.java:33-36`)
   ```
   GET /api/loans/{loanId}/payments
   → loanService.getPaymentsByLoan(loanId)
   ```

2. **Repository call:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` (`LegacyPaymentRepository.java:14`)
   - Returns raw `LegacyPayment` entities with all amounts as `VARCHAR` strings.

3. **Translation:** `LoanService.toPaymentDto()` (`LoanService.java:134-147`)
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));        // "1,487.02"
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // "456.78"
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // "1,074.69"
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // "355.55"
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // "0.00"
   ```
   Each field is parsed independently. There is **no cross-field validation** that the components sum to the total.

4. **API response:** The `PaymentDto` is serialized to JSON with the inconsistent values intact:
   ```json
   {
     "totalAmount": 1487.02,
     "principalAmount": 456.78,
     "interestAmount": 1074.69,
     "escrowAmount": 355.55,
     "lateFee": 0.00
   }
   ```
   A consumer summing the components gets 1,887.02 while the `totalAmount` field says 1,487.02.

### Root Cause

**The legacy ETL pipeline that populates `CDW_PMT_HIST` uses two different conventions for computing `PMT_AMT`:**
- For some loans (e.g., `LN-2019-00142`), `PMT_AMT` represents only the P&I (principal + interest) portion, excluding escrow. The escrow is tracked in `PMT_ESCROW_AMT` but not added to the total.
- For payments with late fees (e.g., `PMT-2025110003`), the late fee is recorded in `PMT_LATE_FEE` but excluded from `PMT_AMT`.

The service layer in `LoanService.java` blindly trusts all values from the database and performs no reconciliation. The `toPaymentDto` method (lines 134-147) maps each field independently without any integrity check.

### Where Runtime Failure Occurs

- **Incorrect API response:** Any consumer that computes `totalAmount - (principalAmount + interestAmount + escrowAmount + lateFee)` to derive "unallocated amount" will get a negative value (-$400), which is nonsensical.
- **Financial reporting:** Aggregating `totalAmount` across all payments will under-report total collections by $400/month for loan `LN-2019-00142`.
- **No exception thrown:** This anomaly is silent — the service returns HTTP 200 with corrupt data. There is no error signal.

### Column Mapping Reference

Per `data/mappings/column_mappings.md` (lines 82-86):
| Legacy Column | Modern Column | Transformation |
|---|---|---|
| `PMT_AMT` | `total_amount` | Remove commas, parse to DECIMAL |
| `PMT_PRIN_AMT` | `principal_amount` | Remove commas, parse to DECIMAL |

The mapping assumes the source data is correct and defines no validation rule for component-sum consistency.

---

## RCA-2: Numeric String Parsing Without Error Handling (ANO-005)

### Anomaly

All numeric values in the legacy schema are stored as `VARCHAR`. The service layer parses them with methods that throw unhandled exceptions on malformed input.

### Code Path Trace

1. **Entry point:** Any endpoint — `GET /api/loans`, `GET /api/borrowers`, `GET /api/loans/{id}/payments`

2. **Parsing methods in `LoanService.java`:**

   **`parseLegacyAmount` (lines 152-155):**
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   - Handles: null, blank, commas
   - Does NOT handle: currency symbols (`$`), spaces within numbers, alphabetic chars, locale-specific formatting (`285.000,00`)
   - Throws: `NumberFormatException` (uncaught)

   **`parseLegacyInteger` (lines 162-165):**
   ```java
   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```
   - Handles: null, blank, leading/trailing whitespace
   - Does NOT handle: decimal points (`745.0`), commas, non-numeric text (`N/A`, `pending`)
   - Throws: `NumberFormatException` (uncaught)

   **`parseLegacyDecimal` (lines 157-160):**
   ```java
   private BigDecimal parseLegacyDecimal(String value) {
       if (value == null || value.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(value.trim());
   }
   ```
   - Does NOT call `.replace(",", "")` unlike `parseLegacyAmount`
   - An interest rate stored as `"4,750"` instead of `"4.750"` would throw `NumberFormatException`

3. **Exception propagation:** Spring Boot's default error handler converts the uncaught `NumberFormatException` into an HTTP 500 response with a stack trace (in dev mode) or a generic error (in prod).

### Root Cause

**The parsing methods assume well-formatted input and have no defensive error handling.** The legacy DW uses `VARCHAR` for all columns precisely because the source systems produce inconsistent formatting. The service layer was written against the current seed data but does not account for the range of values that a real CDW would contain.

The three parsing methods are also inconsistent with each other:
- `parseLegacyAmount` strips commas, `parseLegacyDecimal` does not
- `parseLegacyInteger` returns `null` for blank, `parseLegacyAmount` returns `BigDecimal.ZERO`

### Where Runtime Failure Occurs

- **`GET /api/loans`** (line 48-56): Calls `parseLegacyAmount` for every loan's `originalAmount`, `currentBalance`, `monthlyPayment`. A single malformed amount in any loan crashes the entire list endpoint.
- **`GET /api/borrowers`** (line 66-70): Calls `parseLegacyInteger` for every borrower's `creditScore`. A single non-numeric credit score (e.g., `"N/A"`) crashes the entire borrower listing.
- **Blast radius:** One bad record takes down the endpoint for ALL records because `findAll().stream().map(...)` fails on the first exception and the entire stream is aborted.

### Column Mapping Reference

Per `data/mappings/column_mappings.md`:
- `BORR_CRDT_SCR` (VARCHAR) → `credit_score` (INTEGER): "Parse string to integer"
- `BORR_ANN_INCM` (VARCHAR) → `annual_income` (DECIMAL): "Remove commas, parse to decimal"
- `LN_INT_RT` (VARCHAR) → `interest_rate` (DECIMAL): "Parse string to decimal"

The mappings acknowledge the transformation is needed but define no error handling for unparseable values.

---

## RCA-3: Date String Sorting Bug in Payment History (ANO-006)

### Anomaly

Payment history is sorted by `PMT_DT` (a VARCHAR column in `MM/DD/YYYY` format) using SQL `ORDER BY`, which produces lexicographic ordering instead of chronological ordering.

### Code Path Trace

1. **Entry point:** `LoanController.getPayments()` (`LoanController.java:33-36`)
   ```
   GET /api/loans/{loanId}/payments
   → loanService.getPaymentsByLoan(loanId)
   ```

2. **Service method:** `LoanService.getPaymentsByLoan()` (`LoanService.java:90-95`)
   ```java
   public List<PaymentDto> getPaymentsByLoan(String loanAccountNumber) {
       return paymentRepository
           .findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)
           .stream()
           .map(this::toPaymentDto)
           .collect(Collectors.toList());
   }
   ```

3. **Repository method:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()` (`LegacyPaymentRepository.java:14`)
   - Spring Data JPA generates: `SELECT ... FROM CDW_PMT_HIST WHERE LN_ACCT_NBR = ? ORDER BY PMT_DT DESC`
   - `PMT_DT` is `VARCHAR(10)` → SQL sorts lexicographically

4. **Translation:** `LoanService.toPaymentDto()` (line 138) copies the raw date string to the DTO:
   ```java
   dto.setPaymentDate(pmt.getPaymentDate());  // passes through as-is
   ```
   No date parsing, no re-sorting.

### Root Cause

**The repository relies on SQL `ORDER BY` on a VARCHAR date column.** The `MM/DD/YYYY` format is not lexicographically sortable:

| Date String | Lexicographic Value | Actual Date |
|-------------|--------------------:|-------------|
| "12/15/2024" | Higher (starts with '1') | Dec 15, 2024 |
| "02/15/2025" | Lower (starts with '0')  | Feb 15, 2025 |

`ORDER BY PMT_DT DESC` would return `"12/15/2024"` before `"02/15/2025"`, even though February 2025 is chronologically later.

The current seed data only contains dates from November and December 2025, so the bug is masked — string sort happens to produce the correct order within those two months. But any historical data spanning multiple months or years will be misordered.

Additionally, the `toPaymentDto` method passes the date string through to the API response without converting to a proper date type, so the API consumer receives `"12/15/2025"` as a raw string with no ISO-8601 formatting.

### Where Runtime Failure Occurs

- **Incorrect payment order:** The "most recent payment" shown to a borrower could actually be an older payment, leading to confusion about payment status.
- **Next payment date calculation:** If downstream logic picks the first element of the sorted list as the "latest payment" to compute the next due date, it would use the wrong payment, calculating an incorrect next payment date.
- **No exception thrown:** Like ANO-001, this is a silent data correctness bug — the API returns HTTP 200 with incorrectly ordered data.

### Column Mapping Reference

Per `data/mappings/column_mappings.md` (line 81):
| Legacy Column | Modern Column | Transformation |
|---|---|---|
| `PMT_DT` | `payment_date` | Parse MM/DD/YYYY to DATE |

The mapping specifies conversion to a proper `DATE` type in the modern schema, which would fix the sorting issue. But the current legacy service performs no date parsing — the `toPaymentDto` method copies the raw string.
