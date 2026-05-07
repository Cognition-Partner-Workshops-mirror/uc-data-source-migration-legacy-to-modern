# Root Cause Analysis — Top 3 Critical Data Anomalies

> **Generated:** 2026-05-07
> **Reference:** `docs/DATA_ANOMALY_REPORT.md` (ANOM-001, ANOM-002, ANOM-003)

---

## RCA-001: Payment Component Mismatch (ANOM-001)

### Anomaly

Payments PMT-2025120001 and PMT-2025110001 (both for loan LN-2019-00142) have component sums
(`PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT`) that exceed `PMT_AMT` by exactly $400.00.

### Code Path Trace

1. **Entry point:** `LoanController.getPayments()` → `LoanService.getPaymentsByLoan()`
   (`LoanController.java:33-36`, `LoanService.java:90-95`)

2. **Repository query:** `LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()`
   (`LegacyPaymentRepository.java:14`) — returns raw `LegacyPayment` entities with all fields as strings.

3. **Translation:** `LoanService.toPaymentDto()` (`LoanService.java:134-147`) parses each amount
   field independently:
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));       // "1,487.02" → 1487.02
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // "456.78" → 456.78
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // "1,074.69" → 1074.69
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // "355.55" → 355.55
   ```

4. **No cross-field validation:** `parseLegacyAmount()` (`LoanService.java:152-155`) strips commas
   and parses to BigDecimal. There is no check that components sum to the total. The mismatched
   data passes through the entire pipeline and is served as-is in the JSON response.

5. **Column mappings:** `column_mappings.md` lines 82-86 map each payment amount field independently
   (`PMT_AMT → total_amount`, `PMT_PRIN_AMT → principal_amount`, etc.). No transformation notes
   mention cross-field validation.

### Root Cause

The legacy CDW lacks database-level CHECK constraints (e.g.,
`CHECK (PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT = PMT_AMT)`), and the service layer performs
only field-by-field type conversion with no business rule validation. The source ETL likely loaded
the interest portion incorrectly for loan LN-2019-00142 payments, and nothing in the pipeline
caught the discrepancy.

### Runtime Failure Mode

**No crash, but silently incorrect data.** The API returns a `PaymentDto` where
`principalAmount + interestAmount + escrowAmount = 1887.02` but `totalAmount = 1487.02`. Any
consumer computing derived values (e.g., amortization schedules, interest-to-principal ratios)
will get wrong results. Financial reconciliation reports will not balance.

### Fix Location

`LoanService.toPaymentDto()` — add a post-parse validation step that checks component sum against
total. If mismatched, log a warning with the payment ID and delta, and flag the record in the DTO.

---

## RCA-002: Null Required Fields Causing NPE or Silent Data Loss (ANOM-002)

### Anomaly

The legacy schema has zero NOT NULL constraints (except on primary keys). All fields — including
business-critical ones like borrower names, loan amounts, and dates — allow NULL. The current seed
data has NULLs in optional fields (BORR_ADDR_LN2, BORR_MID_INIT), but the schema permits NULLs
everywhere.

### Code Path Trace

1. **Entry point:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()`
   (`LoanController.java:23-26`, `LoanService.java:48-56`)

2. **Crash path — name concatenation:** `LoanService.toLoanSummary()` at line 106:
   ```java
   dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
   ```
   If `getBorrowerFirstName()` returns `null`, Java produces the string `"null Mitchell"`.
   If `getBorrowerLastName()` also returns `null`, the result is `"null null"`.
   **This does not throw NPE** (Java string concatenation converts null to the literal "null"),
   but produces corrupted display data.

3. **Crash path — property address:** `LoanService.toLoanSummary()` at line 114:
   ```java
   dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
           + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
   ```
   Same issue: null fields produce `"null, null, null null"` in the address.

4. **Silent zero substitution:** `LoanService.parseLegacyAmount()` at line 153:
   ```java
   if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
   ```
   A null `LN_ORIG_AMT` becomes `BigDecimal.ZERO`, making a missing loan amount
   indistinguishable from a $0 loan. This is a silent data loss: the API consumer
   cannot tell whether the loan is genuinely $0 or the data is missing.

5. **Crash path — integer parsing:** `LoanService.parseLegacyInteger()` at line 163:
   ```java
   if (value == null || value.isBlank()) return null;
   return Integer.parseInt(value.trim());
   ```
   Returns null for missing credit scores, which propagates to `BorrowerDto.creditScore`.
   This is correctly handled (Integer type is nullable), but consumers must null-check.

6. **Column mappings:** `column_mappings.md` specifies target columns with NOT NULL in the modern
   schema (`first_name VARCHAR(50) NOT NULL`, `original_amount DECIMAL(12,2) NOT NULL`). The
   migration will fail on these records unless nulls are caught beforehand.

### Root Cause

The legacy data warehouse uses a "load everything, validate nothing" pattern common in batch ETL
systems. The application service layer assumes fields are populated because the current seed data
happens to be mostly complete. There are no null guards beyond the parse helper methods.

### Runtime Failure Mode

- **Corrupted display:** Names show as `"null Williams"`, addresses as `"null, null, null null"`
- **Silent data loss:** Missing amounts appear as $0.00 — indistinguishable from genuine zeros
- **Migration blocker:** Records with null required fields will violate NOT NULL constraints in
  the modern schema, causing the entire batch to fail

### Fix Location

`LoanService.toLoanSummary()` and `LoanService.toBorrowerDto()` — add null checks before string
concatenation. `parseLegacyAmount()` — differentiate between null/missing (error) and "0" (valid).
Add a validation layer that rejects or flags records missing required fields.

---

## RCA-003: Unguarded String-to-Number Parsing (ANOM-003)

### Anomaly

All numeric fields (amounts, rates, scores, counts) are stored as VARCHAR in the legacy schema.
The service layer parses these strings to BigDecimal/Integer without try-catch protection. A single
malformed value causes an unhandled `NumberFormatException` that crashes the entire API endpoint.

### Code Path Trace

1. **Entry point:** `LoanController.getAllLoans()` → `LoanService.getAllLoans()`
   (`LoanController.java:23-26`, `LoanService.java:48-56`)

2. **Iteration over all records:** `LoanService.getAllLoans()` at lines 53-55:
   ```java
   return loanAccountRepository.findAll().stream()
           .map(acct -> toLoanSummary(acct, products.get(acct.getProductCode())))
           .collect(Collectors.toList());
   ```
   This maps over ALL loan accounts. If any single account has a malformed field, the
   stream operation throws and no results are returned.

3. **Parse failure — amounts:** `LoanService.parseLegacyAmount()` at line 154:
   ```java
   return new BigDecimal(amount.replace(",", ""));
   ```
   `new BigDecimal("$285,000".replace(",", ""))` → `new BigDecimal("$285000")` →
   **`NumberFormatException`**. Similarly for "N/A", "TBD", "285 000", or any non-numeric content.

4. **Parse failure — integers:** `LoanService.parseLegacyInteger()` at line 164:
   ```java
   return Integer.parseInt(value.trim());
   ```
   `Integer.parseInt("N/A")` → **`NumberFormatException`**. This is called for credit scores
   (`BORR_CRDT_SCR`) which could contain "PENDING", "N/A", or empty strings from legacy loads.

5. **Parse failure — decimals:** `LoanService.parseLegacyDecimal()` at line 159:
   ```java
   return new BigDecimal(value.trim());
   ```
   Called for interest rates (`LN_INT_RT`). A value like "4.750%" →
   **`NumberFormatException`**.

6. **No exception handler:** The controllers (`LoanController.java`, `BorrowerController.java`)
   have no `@ExceptionHandler` or `@ControllerAdvice`. The raw exception propagates as an HTTP 500
   with a Spring Boot error page containing stack trace details.

7. **Column mappings context:** `column_mappings.md` documents the required transformations
   ("Remove commas, parse → decimal", "Parse string → integer") but these transformation notes
   assume clean input. No error handling strategy is documented.

### Root Cause

The service layer was written assuming the legacy data is always well-formed — a dangerous
assumption for any data warehouse. The `parseLegacyAmount()`, `parseLegacyDecimal()`, and
`parseLegacyInteger()` methods handle only the happy path (null/blank check + simple parse).
There is no try-catch, no input sanitization beyond comma removal, and no fallback strategy.

### Runtime Failure Mode

**Complete endpoint failure.** One malformed record among thousands causes:
1. `NumberFormatException` thrown inside the stream `map()` operation
2. Exception propagates up through `getAllLoans()` → `LoanController` → Spring MVC
3. HTTP 500 returned with no indication of which record or field caused the failure
4. Zero results returned — all valid records are lost along with the bad one

### Fix Location

1. `LoanService.parseLegacyAmount()`, `parseLegacyDecimal()`, `parseLegacyInteger()` — wrap in
   try-catch, log the specific value that failed, return a safe default or null.
2. `LoanService.toLoanSummary()`, `toBorrowerDto()`, `toPaymentDto()` — handle parse failures
   gracefully, either skipping the record with a warning or populating an error indicator in the DTO.
3. Add a `@ControllerAdvice` global exception handler to return structured error responses instead
   of raw stack traces.
