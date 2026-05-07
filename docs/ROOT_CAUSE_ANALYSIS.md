# Root Cause Analysis — Top 3 Critical Anomalies

> **Generated:** 2026-05-07
> **Analyzed Service:** `com.workshop.loanservice.service.LoanService`

---

## RCA-001: SSN Last-4 Digits Populated from Phone Number (ANO-001)

### Symptom

All 5 loan accounts in `CDW_LN_ACCT` have `BORR_SSN_LST4` values identical to the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR`.

### Code Path Trace

1. **Data entry point:** `data-legacy.sql` inserts into `CDW_LN_ACCT` with the SSN last-4 values:
   ```sql
   INSERT INTO CDW_LN_ACCT VALUES ('LN-2019-00142', 'B-10001', 'James', 'Mitchell', '0142', ...)
   ```
   Here `'0142'` is the SSN last-4 for borrower B-10001, whose phone is `217-555-0142`.

2. **Entity mapping:** `LegacyLoanAccount.java:29-30` maps the column:
   ```java
   @Column(name = "BORR_SSN_LST4")
   private String borrowerSsnLast4;
   ```

3. **Service consumption:** `LoanService.toLoanSummary()` (line 103-118) does **not** use `BORR_SSN_LST4` in the DTO output. The field is read from the database but never validated or surfaced.

4. **Column mappings:** `data/mappings/column_mappings.md` line 51 marks this field as `*(dropped)*` in the modern schema — the migration plan drops it in favor of the borrower FK. However, during the migration validation phase, this corrupt data would be used for identity cross-referencing.

### Root Cause

The legacy CDW ETL process that populated `CDW_LN_ACCT.BORR_SSN_LST4` appears to have sourced the value from `CDW_BORR_MSTR.BORR_PH_NBR` (phone number) instead of deriving it from `CDW_BORR_MSTR.BORR_SSN_ENCR` (encrypted SSN). The 100% correlation across all records rules out coincidence. This is a systemic ETL mapping error in the upstream data warehouse.

### Runtime Impact

- **Current:** No direct runtime failure because `toLoanSummary()` does not expose SSN last-4 to the API. The field is silently ignored.
- **Migration risk:** If migration validation compares `BORR_SSN_LST4` against the encrypted SSN to verify data integrity, every record will fail, potentially blocking the migration.
- **Downstream risk:** Any external system consuming the raw `CDW_LN_ACCT` table directly (bypassing the service layer) would use incorrect SSN data for identity verification.

### Recommended Action

Add a validation check that cross-references `BORR_SSN_LST4` against `BORR_PH_NBR` to detect and flag this pattern. Mark all existing `BORR_SSN_LST4` values as untrusted in the migration plan.

---

## RCA-002: Payment Component Amounts Exceed Total (ANO-002)

### Symptom

Payment records PMT-2025120001, PMT-2025110001, and PMT-2025110003 have component sums (principal + interest + escrow + late fee) that exceed the stated total payment amount.

### Code Path Trace

1. **Data entry point:** `data-legacy.sql` line 27-28:
   ```sql
   INSERT INTO CDW_PMT_HIST VALUES ('PMT-2025120001', 'LN-2019-00142', '12/15/2025',
       '1,487.02', '456.78', '1,074.69', '355.55', '0.00', 'REG', 'PST', ...);
   ```
   Components: 456.78 + 1,074.69 + 355.55 = **1,887.02**, but total is **1,487.02** (Δ = $400.00).

2. **Entity mapping:** `LegacyPayment.java` maps each field independently:
   ```java
   @Column(name = "PMT_AMT")     private String totalAmount;      // line 25-26
   @Column(name = "PMT_PRIN_AMT") private String principalAmount;  // line 28-29
   @Column(name = "PMT_INT_AMT")  private String interestAmount;   // line 31-32
   @Column(name = "PMT_ESCROW_AMT") private String escrowAmount;   // line 34-35
   @Column(name = "PMT_LATE_FEE") private String lateFee;          // line 37-38
   ```

3. **Service consumption:** `LoanService.toPaymentDto()` (line 134-147) parses each amount independently and sets them on `PaymentDto`:
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
   ```
   **No cross-field validation** is performed. Each amount is parsed and returned independently.

4. **API exposure:** `LoanController.getPayments()` (line 33-36) returns the `PaymentDto` list directly, exposing the inconsistent data to API consumers.

### Root Cause

The legacy system stores each payment component independently with no database-level CHECK constraint enforcing `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`. The mismatch pattern for PMT-2025120001/PMT-2025110001 (both $400 over) matches exactly the escrow amount of $355.55 plus rounding in the interest allocation — suggesting the escrow component was added to the breakdown after the total was computed, or the total field represents only the principal+interest portion.

For PMT-2025110003, the $47.50 discrepancy matches the late fee exactly, indicating the late fee was recorded as a component but not added to the total.

### Runtime Impact

- **Current:** The API returns inconsistent payment data. A consumer summing `principalAmount + interestAmount + escrowAmount + lateFee` gets a different number than `totalAmount`. This breaks any financial reconciliation built on top of the API.
- **Incorrect API response:** `GET /api/loans/LN-2019-00142/payments` returns payment records where displayed amounts are mathematically inconsistent.

### Recommended Action

Add a payment integrity validator that computes the expected sum and compares it against the stated total. Log a warning for discrepancies and include a `balanceVerified` flag in the payment DTO so consumers know whether to trust the breakdown.

---

## RCA-003: Unhandled NumberFormatException in Legacy Parsers (ANO-003)

### Symptom

The parsing methods `parseLegacyAmount`, `parseLegacyDecimal`, and `parseLegacyInteger` in `LoanService` will throw uncaught `NumberFormatException` for any malformed input string, causing a 500 Internal Server Error.

### Code Path Trace

1. **parseLegacyAmount** (LoanService.java line 152-155):
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   Only handles null/blank and commas. Fails on: `$`, spaces in middle, letters, mainframe trailing signs (`1234.56-`).

2. **parseLegacyDecimal** (line 157-160):
   ```java
   private BigDecimal parseLegacyDecimal(String value) {
       if (value == null || value.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(value.trim());
   }
   ```
   Only trims whitespace. Fails on commas, currency symbols, or text.

3. **parseLegacyInteger** (line 162-165):
   ```java
   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```
   No try-catch. Fails on decimals (`"745.0"`), commas, or text.

4. **Call sites in getAllLoans()** (line 48-56):
   ```java
   return loanAccountRepository.findAll().stream()
       .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
       .collect(Collectors.toList());
   ```
   This streams ALL loan accounts through `toLoanSummary`, which calls `parseLegacyAmount` on multiple fields. A single corrupt record causes the entire stream to fail, returning zero results with a 500 error.

5. **Column mappings context:** `column_mappings.md` documents transformations like "Remove commas, parse → decimal" (line 53, 54, 57, etc.) but does not specify error handling for malformed values. The mapping assumes clean data.

### Root Cause

The service layer was written assuming the legacy CDW data would always conform to the expected patterns (comma-separated numeric strings, valid integers). No defensive parsing was implemented because the initial seed data happened to be well-formed. However, the CDW is a shared data warehouse where upstream systems can introduce malformed data at any time.

### Runtime Impact

- **Single-record failure cascades:** `GET /api/loans` calls `getAllLoans()` which iterates all records. One corrupt amount field causes `NumberFormatException` → HTTP 500 → **all loan data is inaccessible**.
- **No error isolation:** The stream-based processing has no per-record error handling. The exception bubbles up through the stream, the controller, and Spring's exception handler.
- **No observability:** The raw `NumberFormatException` stack trace doesn't indicate which record or field was corrupt, making debugging difficult.

### Recommended Action

1. Wrap all parse methods in try-catch blocks returning safe defaults.
2. Add structured logging that identifies the specific record ID and field name when parsing fails.
3. Consider per-record error isolation in the stream: catch exceptions per record and skip/flag corrupt records rather than failing the entire request.
