# Root Cause Analysis — Top 3 Critical Anomalies

---

## RCA-1: Payment Component Sum Mismatch (ANM-001)

### Anomaly

Payment records `PMT-2025120001` and `PMT-2025110001` (both for loan `LN-2019-00142`) have component amounts that sum to $1,887.02, but the total payment field (`PMT_AMT`) is $1,487.02 — a $400.00 discrepancy. Payment `PMT-2025110003` (for loan `LN-2018-00089`) has a $47.50 late fee that is not included in the stated total.

### Code Trace

1. **Data ingestion:** `data-legacy.sql` inserts raw values into `CDW_PMT_HIST`. No trigger, constraint, or check validates that `PMT_AMT = PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE`.

2. **Entity layer:** `LegacyPayment.java` maps all columns as `String` fields. No validation occurs at the JPA entity level.

3. **Repository layer:** `LegacyPaymentRepository.java` extends `JpaRepository` with no custom validation.

4. **Service layer — `LoanService.toPaymentDto()` (lines 134–147):**
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
   ```
   Each field is parsed independently. **No cross-field validation** checks that the components sum to the total. The mismatched values are passed directly to the API consumer.

5. **Column mappings** (`data/mappings/column_mappings.md`, lines 82–86) specify that all payment amount fields should be parsed from string to `DECIMAL(10,2)` with comma removal. No mention of a sum-validation step.

### Root Cause

**The legacy ETL process that populates `CDW_PMT_HIST` computes the total and component amounts independently** (likely from different source systems or calculation steps), and there is no reconciliation check. For loan `LN-2019-00142`, the escrow amount ($355.55) appears to have been added to the components after the total was calculated, or the total was sourced from a payment gateway while the breakdown came from the loan servicing system. For `PMT-2025110003`, the late fee was assessed after the regular payment total was recorded.

The service layer (`LoanService.java`) trusts the data implicitly. It parses each field in isolation and passes them through to the DTO without any integrity check. There is no `assert` or `if` that validates the mathematical relationship between the fields.

### Runtime Impact

- **API Response:** `/api/payments/loan/LN-2019-00142` returns JSON where `totalAmount: 1487.02` but `principalAmount + interestAmount + escrowAmount + lateFee = 1887.02`. Any consumer computing a checksum or displaying a breakdown will see a $400 discrepancy.
- **Financial Reporting:** Reports that sum component amounts will overstate totals by $400 per affected payment. Over time, this compounds into material misstatement.
- **No Runtime Exception:** The code does not crash — it silently returns incorrect data, which is worse than a crash from a data integrity perspective.

### Fix Location

`LoanService.toPaymentDto()` — add post-parse validation that checks `principal + interest + escrow + lateFee == total`. If they diverge, log a warning and set a `dataQualityWarning` flag on the DTO (or recalculate the total from components).

---

## RCA-2: Numeric String Parsing Without Error Handling (ANM-002)

### Anomaly

All numeric values across all four legacy tables are stored as `VARCHAR` strings. The schema enforces no content constraints. The service layer's parsing methods throw unchecked exceptions on malformed input.

### Code Trace

1. **Schema layer:** `schema-legacy.sql` defines all numeric columns as `VARCHAR`:
   ```sql
   BORR_CRDT_SCR   VARCHAR(5),         -- credit score as string
   BORR_ANN_INCM   VARCHAR(15),        -- annual income as string with commas
   LN_ORIG_AMT     VARCHAR(15),        -- original amount as string
   LN_INT_RT       VARCHAR(8),         -- interest rate as string "5.250"
   ```

2. **Entity layer:** All entity classes (`LegacyBorrower.java`, `LegacyLoanAccount.java`, `LegacyPayment.java`, `LegacyLoanProduct.java`) map these as `String` fields — correct for the schema but pushes all type conversion responsibility to the service layer.

3. **Service layer — parsing methods (`LoanService.java`, lines 152–165):**
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));  // throws NumberFormatException
   }

   private BigDecimal parseLegacyDecimal(String value) {
       if (value == null || value.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(value.trim());  // throws NumberFormatException
   }

   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());  // throws NumberFormatException
   }
   ```

4. **Call sites:**
   - `toLoanSummary()` calls `parseLegacyAmount()` for `originalAmount`, `currentBalance`, `monthlyPayment` and `parseLegacyDecimal()` for `interestRate` (lines 108–111).
   - `toBorrowerDto()` calls `parseLegacyInteger()` for `creditScore` (line 129).
   - `toPaymentDto()` calls `parseLegacyAmount()` for all five monetary fields (lines 139–143).

5. **Column mappings** (`data/mappings/column_mappings.md`) document the transformations ("Remove commas, parse to decimal", "Parse string to integer") but do not mention error handling.

### Root Cause

**The parsing methods only handle null/blank inputs but do not handle malformed non-blank inputs.** A `VARCHAR` column can contain any string value. The legacy DW has no CHECK constraints. Common real-world scenarios that would trigger exceptions:
- Dollar signs: `"$285,000"` → `NumberFormatException` (the `$` is not removed)
- Negative values with parentheses: `"(1,200.00)"` → `NumberFormatException`
- Placeholder text: `"N/A"`, `"TBD"`, `"PENDING"` → `NumberFormatException`
- Double commas or trailing commas: `"285,,000"`, `"285,000,"` → `NumberFormatException`

Because `parseLegacyAmount()` is called inside `Stream.map()` in `getAllLoans()` (line 54) and `getAllBorrowers()` (line 68), **a single bad row causes the entire stream to fail with an uncaught exception**, which Spring translates to a 500 Internal Server Error. No partial results are returned.

### Runtime Impact

- **API Crash:** Any endpoint (`/api/loans`, `/api/borrowers`, `/api/payments/loan/{id}`) returns HTTP 500 if even one record has a malformed numeric field.
- **No Graceful Degradation:** The stream-based processing means no partial results — it's all or nothing.
- **Silent Zero-Default:** Null/blank values return `BigDecimal.ZERO` for amounts, which silently understates balances. A null credit score returns `null` in the DTO, which is more appropriate but inconsistent with the amount handling.

### Fix Location

All three parsing methods in `LoanService.java` (lines 152–165). Wrap each with try-catch for `NumberFormatException`. Return a sensible default and log a warning with the field name, raw value, and record ID for traceability.

---

## RCA-3: Missing NOT NULL Constraints Causing Null Concatenation (ANM-003)

### Anomaly

The schema allows NULL in all non-primary-key columns. The service layer concatenates string fields without null guards, which would produce `"null"` literals in API output.

### Code Trace

1. **Schema layer:** `schema-legacy.sql` — no column has a NOT NULL constraint except primary keys (which get it implicitly):
   ```sql
   BORR_FST_NM     VARCHAR(50),      -- can be NULL
   BORR_LST_NM     VARCHAR(50),      -- can be NULL
   ```

2. **Service layer — `toLoanSummary()` (lines 103–117):**
   ```java
   dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
   ```
   If `getBorrowerFirstName()` returns `null`, Java's string concatenation produces `"null Mitchell"`. If both are null: `"null null"`.

   ```java
   dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
           + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
   ```
   If any property field is null: `"null, null, null null"`.

3. **Service layer — `toBorrowerDto()` (lines 120–131):**
   ```java
   String middle = borrower.getMiddleInitial() != null ? " " + borrower.getMiddleInitial() + "." : "";
   dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
   ```
   The middle initial IS null-checked (line 123), but `getFirstName()` and `getLastName()` are NOT. Inconsistent handling.

4. **Column mappings** (`data/mappings/column_mappings.md`) specify "Direct copy" for name fields, with no mention of null handling.

5. **Current data:** `B-10005` Robert Williams has `BORR_MID_INIT = NULL`, which is handled correctly. But if `BORR_FST_NM` were null for any record, the API would return `"null R. Williams"`.

### Root Cause

**The service layer assumes certain fields will never be null, based on the current seed data rather than the schema constraints.** The schema permits null everywhere, but the code only null-checks fields where the current test data happens to contain nulls (like `middleInitial`). This is a classic "works with test data, fails with production data" bug.

The null-handling is inconsistent across the codebase:
- `middleInitial`: null-checked (line 123)
- `firstName`, `lastName`: NOT null-checked (lines 106, 124)
- `propertyAddress`, `propertyCity`, `propertyState`, `propertyZip`: NOT null-checked (lines 114-115)
- `statusCode` in `expandStatusCode()`: null-checked (line 168)
- `propertyType` in `expandPropertyType()`: null-checked (line 179)

### Runtime Impact

- **Garbled API Output:** `/api/loans` would return `"borrowerName": "null null"` for records with null names. This is visible to end users and breaks downstream name parsing.
- **Property Address Garbage:** `"propertyAddress": "null, null, null null"` is not useful and would fail address validation in consuming systems.
- **No Exception:** Unlike the numeric parsing issue, nulls don't crash the app — they produce silently wrong output, which can propagate through systems before being detected.

### Fix Location

`LoanService.toLoanSummary()` (lines 106, 114-115) and `LoanService.toBorrowerDto()` (line 124). Add null-safe string handling for all concatenated fields. Use helper methods like `Objects.toString(value, "")` or explicit null checks with fallback values like `"[Unknown]"`.
