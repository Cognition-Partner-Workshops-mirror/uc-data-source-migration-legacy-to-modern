# Root Cause Analysis — Top 3 Critical Data Anomalies

---

## RCA-1: Payment Component Amounts Do Not Sum to Total (ANO-001)

### Anomaly Summary
In `CDW_PMT_HIST`, the sum of `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE` does not equal `PMT_AMT` for 3 out of 10 payment records (30% failure rate).

### Affected Code Path

**Entry point:** `LoanController.getPayments()` (`LoanController.java:33-36`)
```
GET /api/loans/{loanId}/payments
  -> LoanService.getPaymentsByLoan()
    -> LegacyPaymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc()
    -> LoanService.toPaymentDto()       <-- components mapped individually, no cross-validation
```

**Translation layer:** `LoanService.toPaymentDto()` (`LoanService.java:134-147`)
```java
dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
```

Each field is parsed independently. There is no check that the components sum to the total.

**Repository layer:** `LegacyPaymentRepository` (`LegacyPaymentRepository.java:14`) uses Spring Data JPA `findByLoanAccountNumberOrderByPaymentDateDesc` — a direct SELECT with no computed columns or validation.

**Column mappings:** `column_mappings.md` (lines 82-86) specifies each amount field maps independently with "Remove commas, parse -> decimal". No cross-field integrity rule is defined.

### Root Cause

The legacy CDW system stores payment components that were independently updated by different subsystems:
- The **payment posting system** writes `PMT_AMT` as the borrower's scheduled monthly payment amount.
- The **escrow accounting system** writes `PMT_ESCROW_AMT` independently based on escrow analysis.
- No batch reconciliation job exists to verify component consistency.

For loan `LN-2019-00142`, the escrow analysis increased the escrow portion by $400 (from an assumed $0 to $355.55 x 2 payments), but the total was never updated. For `PMT-2025110003`, the late fee of $47.50 was appended after the total was recorded.

### Runtime Failure Mode

The API returns inconsistent financial data:
```json
{
  "totalAmount": 1487.02,
  "principalAmount": 456.78,
  "interestAmount": 1074.69,
  "escrowAmount": 355.55,
  "lateFee": 0.00
}
```
A frontend that sums components will show $1,887.02 while the total field shows $1,487.02. This creates user confusion and potential regulatory reporting errors.

### Fix Location
`LoanService.toPaymentDto()` — add a post-mapping validation that computes the component sum and either:
1. Logs a warning and flags the discrepancy in the DTO, or
2. Recalculates the total from components as the authoritative value.

---

## RCA-2: SSN Last-4 Digits Sourced from Phone Numbers (ANO-002)

### Anomaly Summary
100% of `BORR_SSN_LST4` values in `CDW_LN_ACCT` match the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR`. This indicates a systemic ETL or data entry error.

### Affected Code Path

**Entry point:** `LoanController.getAllLoans()` (`LoanController.java:23-26`)
```
GET /api/loans
  -> LoanService.getAllLoans()
    -> LoanService.toLoanSummary()      <-- uses denormalized borrower data from CDW_LN_ACCT
```

**Translation layer:** `LoanService.toLoanSummary()` (`LoanService.java:103-118`)
```java
dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
```

The SSN last-4 field (`borrowerSsnLast4`) is present in the `LegacyLoanAccount` entity (`LegacyLoanAccount.java:29-30`) but is **not currently mapped to any DTO field**. This means the corrupted data is stored but not currently exposed through the API.

However, the `column_mappings.md` (line 51) documents this field as "*(dropped)* — Denormalized; use borrower FK", meaning it was intended to be dropped during migration. But if any future code references it for verification (e.g., borrower identity confirmation during loan servicing), it will use phone-derived data instead of actual SSN data.

**Repository layer:** `LegacyLoanAccountRepository` reads directly from `CDW_LN_ACCT` with no joins to `CDW_BORR_MSTR` — the denormalized SSN last-4 is the only copy available in the loan context.

### Root Cause

The legacy ETL process that populates `CDW_LN_ACCT` from the origination system has a column mapping error. The source query likely selected the wrong column:
```sql
-- Probable ETL bug:
SELECT ..., RIGHT(BORR_PH_NBR, 4) AS BORR_SSN_LST4, ...  -- wrong source column
-- Should have been:
SELECT ..., RIGHT(DECRYPT(BORR_SSN_ENCR), 4) AS BORR_SSN_LST4, ...
```

The `CDW_BORR_MSTR` table stores only the encrypted full SSN (`BORR_SSN_ENCR`), not the last-4. The ETL needed to decrypt and extract, but instead grabbed the phone number suffix.

### Runtime Failure Mode

Currently no API exposure. But the corrupted field exists in the entity layer and could be used by:
1. Future loan servicing endpoints that verify borrower identity
2. Migration scripts that copy `BORR_SSN_LST4` to the modern schema
3. Fraud detection systems that cross-reference SSN last-4

### Fix Location
1. `LegacyLoanAccount` entity — add a comment marking `borrowerSsnLast4` as untrusted.
2. `LoanService` — add a validation method that cross-checks SSN last-4 against phone last-4. If they match, flag the record as having a corrupted SSN field.
3. Ensure the modern migration script does NOT copy this field (as `column_mappings.md` already specifies).

---

## RCA-3: Unhandled NumberFormatException in All Parsing Methods (ANO-003)

### Anomaly Summary
`LoanService` methods `parseLegacyAmount()`, `parseLegacyDecimal()`, and `parseLegacyInteger()` have no try-catch error handling. Any non-numeric value in a VARCHAR amount/number field causes an uncaught `NumberFormatException` that propagates as an HTTP 500.

### Affected Code Path

**All API endpoints are affected:**

```
GET /api/loans           -> getAllLoans()       -> parseLegacyAmount() x5 per record
GET /api/loans/{id}      -> getLoanById()       -> parseLegacyAmount() x5
GET /api/borrowers       -> getAllBorrowers()   -> parseLegacyInteger() x1 per record
GET /api/borrowers/{id}  -> getBorrowerById()   -> parseLegacyInteger() + parseLegacyAmount() x5
GET /api/loans/{id}/payments -> getPaymentsByLoan() -> parseLegacyAmount() x5 per payment
```

**Vulnerable methods:** (`LoanService.java:152-165`)

```java
// Line 154: No try-catch — throws NumberFormatException on "$285,000", "N/A", "TBD"
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}

// Line 159: No try-catch — throws on "N/A", trailing spaces with special chars
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());
}

// Line 164: No try-catch — throws on "N/A", "750+", "unknown"
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());
}
```

**Column mappings context:** `column_mappings.md` (lines 94-98) documents 5 transformation patterns, all assuming clean data:
1. Date conversion: `MM/DD/YYYY` string -> DATE (no error handling specified)
2. Amount conversion: "Remove commas, parse -> DECIMAL" (no error handling specified)
3. Status expansion: Short codes -> readable values (default case returns raw code)
4. Denormalization removal (structural, no parsing)
5. ID resolution (structural, no parsing)

The mapping documentation assumes all data conforms to the expected format, which is invalid for a legacy DW with known quality issues.

### Root Cause

The service layer was written with an implicit assumption that all legacy VARCHAR values conform to a clean numeric format. The only preprocessing is:
- Null/blank check (returns zero or null)
- Comma removal for amounts

Missing preprocessing:
- No currency symbol stripping (`$`, `EUR`)
- No whitespace normalization beyond `trim()`
- No handling of placeholder values (`N/A`, `TBD`, `PENDING`, `-`)
- No handling of numeric values with trailing text (`750 (estimated)`)
- No try-catch around `new BigDecimal()` or `Integer.parseInt()`

### Runtime Failure Mode

**Scenario:** A single bad record is inserted into `CDW_BORR_MSTR`:
```sql
INSERT INTO CDW_BORR_MSTR VALUES ('B-99999', 'Test', 'User', NULL, NULL,
    '01/01/1990', '123 Main St', NULL, 'Anytown', 'XX', '00000',
    '000-000-0000', 'test@test.com', 'N/A', 'UNKNOWN', 'TBD', ...);
```

Calling `GET /api/borrowers`:
1. `LoanService.getAllBorrowers()` iterates all borrowers
2. For B-99999, `parseLegacyInteger("N/A")` is called for credit score
3. `Integer.parseInt("N/A")` throws `NumberFormatException`
4. Exception is unhandled — Spring Boot returns HTTP 500 with stack trace
5. **All** borrower data is unavailable, not just the bad record

This is a **single-record poison pill** pattern where one bad row breaks the entire endpoint.

### Fix Location

`LoanService.java` — all three parsing methods need:
1. Try-catch wrapping around the parse call
2. Sanitization: strip non-numeric characters (except `.`, `-`) before parsing
3. Logging: warn-level log with the original value and record context
4. Safe default: return `BigDecimal.ZERO` for amounts, `null` for optional integers
5. Consider adding a `DataQualityWarning` list to DTOs so API consumers know which fields had parse issues
