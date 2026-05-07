# Root Cause Analysis — Top 3 Critical Anomalies

## RCA #1: Payment Component Amounts Exceed Total Payment

### Anomaly Description

In `CDW_PMT_HIST`, the sum of `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT` exceeds `PMT_AMT` (the total payment) for loan LN-2019-00142. The discrepancy is exactly $400.00 across multiple months, suggesting a systematic error rather than a one-off data entry mistake.

### Code Path Trace

1. **Entry Point:** `LoanController.getPayments()` → `LoanService.getPaymentsByLoan()`
   - File: `src/main/java/com/workshop/loanservice/service/LoanService.java:90-95`

2. **Repository Query:** `paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc(loanAccountNumber)`
   - File: `src/main/java/com/workshop/loanservice/repository/LegacyPaymentRepository.java`
   - Returns all payment records for the loan — no filtering of inconsistent records.

3. **DTO Mapping:** `toPaymentDto(LegacyPayment pmt)` at line 134-147
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // 1,487.02
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // 456.78
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // 1,074.69
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // 355.55
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // 0.00
   ```

4. **No Validation:** The service blindly passes all values through `parseLegacyAmount()` without cross-checking that components sum to the total.

### Root Cause

The service layer at `LoanService.java:134-147` performs no arithmetic consistency validation. It treats each column as an independent value and converts them individually. There is no business rule check that `principal + interest + escrow + lateFee == total`.

### Runtime Failure Mode

- **No immediate runtime failure** — the API responds with HTTP 200 containing mathematically inconsistent data.
- **Silent data corruption**: API consumers (loan servicing UIs, accounting systems) receive amounts that don't add up, leading to incorrect balance calculations, reconciliation failures, and potential regulatory reporting errors.
- If a downstream system computes remaining balance by subtracting the component amounts instead of the total, balances will be $400 off per payment — compounding month over month.

### Location in Column Mappings

From `data/mappings/column_mappings.md` lines 82-86:
- `PMT_AMT` → `total_amount` (DECIMAL)
- `PMT_PRIN_AMT` → `principal_amount` (DECIMAL)
- `PMT_INT_AMT` → `interest_amount` (DECIMAL)
- `PMT_ESCROW_AMT` → `escrow_amount` (DECIMAL)

The mappings define type conversion only — no cross-field validation rules.

---

## RCA #2: SSN Last-4 Contains Phone Number Suffixes (PII Corruption)

### Anomaly Description

Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` exactly matches the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR`. This indicates the field was populated from the wrong source column during an ETL process.

### Code Path Trace

1. **Entry Point:** `LoanController.getLoan()` → `LoanService.getLoanById()`
   - File: `src/main/java/com/workshop/loanservice/service/LoanService.java:58-64`

2. **Entity Load:** `loanAccountRepository.findById(loanAccountNumber)`
   - Loads `LegacyLoanAccount` entity which includes `borrowerSsnLast4` field
   - File: `src/main/java/com/workshop/loanservice/entity/LegacyLoanAccount.java:29-30`
   ```java
   @Column(name = "BORR_SSN_LST4")
   private String borrowerSsnLast4;
   ```

3. **DTO Mapping:** `toLoanSummary()` at line 103-118
   - The `borrowerSsnLast4` field is loaded into the entity but is **not currently exposed** in `LoanSummaryDto`.
   - However, it IS accessible via the entity getter and could be used by future code or other consumers.

4. **Column Mapping Definition:** From `data/mappings/column_mappings.md` line 51:
   ```
   | BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
   ```
   The mapping correctly marks this as "dropped" in the modern schema — but does NOT flag that the existing data is corrupt.

### Root Cause

The legacy ETL process that populated `CDW_LN_ACCT.BORR_SSN_LST4` extracted the last 4 characters from `BORR_PH_NBR` instead of from the decrypted `BORR_SSN_ENCR` field. This was likely a column-offset error in the ETL mapping (phone number column was adjacent to SSN column in the source extract).

The service layer has no validation to detect this corruption because:
- There is no cross-table check comparing `BORR_SSN_LST4` against the SSN source
- The field is simply mapped as a string with no semantic validation

### Runtime Failure Mode

- **Identity verification failure**: Any KYC or fraud-detection system using SSN last-4 from this service will match against phone suffixes instead of actual SSN digits.
- **Compliance violation**: Reporting this field as "SSN last 4" to regulators or credit bureaus constitutes inaccurate PII handling under GLBA/FCRA.
- **No runtime exception** — the corrupt data silently passes through as a valid 4-character string.

---

## RCA #3: Unguarded Numeric String Parsing Causes Runtime Failures

### Anomaly Description

All monetary amounts, rates, scores, and counts are stored as VARCHAR strings in the legacy schema. The service layer parses these with `new BigDecimal(...)` and `Integer.parseInt(...)` which throw uncaught `NumberFormatException` for any non-numeric content.

### Code Path Trace

1. **Entry Point:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()`
   - File: `src/main/java/com/workshop/loanservice/service/LoanService.java:48-56`

2. **Parsing Methods:**

   **`parseLegacyAmount(String amount)`** at line 152-155:
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   - Handles: null, blank, commas
   - Fails on: `"$285,000"`, `"N/A"`, `"285.000,00"`, `"TBD"`, `" "` (non-breaking space)

   **`parseLegacyDecimal(String value)`** at line 157-160:
   ```java
   private BigDecimal parseLegacyDecimal(String value) {
       if (value == null || value.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(value.trim());
   }
   ```
   - Handles: null, blank, leading/trailing whitespace
   - Fails on: commas in value, currency symbols, text

   **`parseLegacyInteger(String value)`** at line 162-165:
   ```java
   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```
   - Handles: null, blank, leading/trailing whitespace
   - Fails on: decimal values like `"745.0"`, commas like `"1,000"`, text

3. **Invocation in `toLoanSummary()`** at line 103-118:
   ```java
   dto.setOriginalAmount(parseLegacyAmount(acct.getOriginalAmount()));
   dto.setCurrentBalance(parseLegacyAmount(acct.getCurrentBalance()));
   dto.setInterestRate(parseLegacyDecimal(acct.getInterestRate()));
   dto.setMonthlyPayment(parseLegacyAmount(acct.getMonthlyPayment()));
   ```

4. **Invocation in `toBorrowerDto()`** at line 120-132:
   ```java
   dto.setCreditScore(parseLegacyInteger(borrower.getCreditScore()));
   ```

### Root Cause

The parsing methods assume data cleanliness that the schema does not enforce. The VARCHAR columns accept any string up to their max length. The code has null/blank guards but no `try-catch` for `NumberFormatException`. A single bad record in any of the 17+ numeric VARCHAR columns will crash the entire API response.

### Runtime Failure Mode

- **Hard failure**: `NumberFormatException` propagates up as an unhandled exception → Spring returns HTTP 500 Internal Server Error.
- **Blast radius**: In `getAllLoans()`, one bad record in ANY loan causes the entire list endpoint to fail (the stream operation aborts).
- **No partial results**: The service does not skip bad records — it's all-or-nothing.
- **Example scenario**: If `LN_CURR_BAL` contains `"PENDING"` for a single loan, `GET /api/loans` returns 500 for ALL consumers, not just queries involving that loan.

### Column Mappings Reference

From `data/mappings/column_mappings.md`, the transformation rules state:
- "Remove commas, parse → decimal" (lines 37, 38, 53, 54, 57, 64, 65, 71, 82-86)
- "Parse string → integer" (lines 35, 56, 63)
- "Parse string → decimal" (lines 55, 65)

These transformations will all fail silently if the source data contains unexpected formats — the mappings document the happy path only.
