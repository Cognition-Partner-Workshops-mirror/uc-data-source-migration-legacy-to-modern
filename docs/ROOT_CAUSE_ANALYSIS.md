# Root Cause Analysis — Top 3 Critical Anomalies

## RCA-1: Payment Component Sum Mismatch (ANO-001)

### Anomaly

Three payment records have component amounts (principal + interest + escrow + late fee) that do not sum to the stated total payment amount:

| Record | Total | Components Sum | Delta |
|---|---|---|---|
| PMT-2025120001 | 1,487.02 | 1,887.02 | +400.00 |
| PMT-2025110001 | 1,487.02 | 1,887.02 | +400.00 |
| PMT-2025110003 | 1,077.05 | 1,124.55 | +47.50 |

### Code Path Trace

1. **Data ingestion:** `data-legacy.sql` inserts raw string values into `CDW_PMT_HIST`. No constraints validate arithmetic consistency.

2. **Entity mapping:** `LegacyPayment.java` maps all `PMT_*` columns as `String` fields — no validation occurs at the JPA layer.

3. **Service translation:** `LoanService.toPaymentDto()` (lines 134–147) parses each component independently:
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));        // "1,487.02"
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount())); // "456.78"
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));   // "1,074.69"
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));       // "355.55"
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));                 // "0.00"
   ```
   Each field is parsed in isolation. No cross-field validation compares the sum of components to the total.

4. **API response:** `LoanController.getPayments()` returns the `PaymentDto` list directly. The API consumer receives `totalAmount: 1487.02` alongside `principalAmount: 456.78 + interestAmount: 1074.69 + escrowAmount: 355.55 = 1887.02`, which is a mathematical contradiction.

5. **Column mappings:** `column_mappings.md` specifies that each legacy `PMT_*_AMT` field maps independently to its modern `DECIMAL` counterpart. No mapping rule enforces the invariant `total = principal + interest + escrow + late_fee`.

### Root Cause

The legacy CDW data warehouse stored payment components as independent string fields with no CHECK constraint or trigger enforcing the accounting identity. The two specific failure patterns are:

- **PMT-2025120001 / PMT-2025110001:** The total (1,487.02) equals approximately principal + interest only (456.78 + 1,074.69 = 1,531.47, close but not exact — indicating the escrow of 355.55 was excluded from the total calculation). The escrow balance for loan LN-2019-00142 is 3,245.80, and the monthly escrow payment is 355.55. The likely root cause is that an upstream ETL process calculated `PMT_AMT` as `PMT_PRIN_AMT + PMT_INT_AMT` without including `PMT_ESCROW_AMT`.

- **PMT-2025110003:** The total (1,077.05) matches the regular monthly payment for loan LN-2018-00089, but a late fee of 47.50 was applied. The total was not recalculated after the late fee was added.

### Runtime Failure Mode

No crash occurs — this is a **silent data correctness failure**. The API returns mathematically inconsistent payment data. Any downstream system that recalculates totals from components will disagree with the stated total, causing:
- Failed reconciliation in accounting systems
- Incorrect amortization schedule calculations
- Audit findings for financial reporting

### Fix Location

`LoanService.toPaymentDto()` — add a cross-field validation after parsing all components. See implementation in `LegacyDataValidator.java`.

---

## RCA-2: SSN Last-4 Populated with Phone Digits (ANO-002)

### Anomaly

All 5 loan accounts have `BORR_SSN_LST4` values that match the last 4 digits of the borrower's phone number, not their SSN.

### Code Path Trace

1. **Data ingestion:** `data-legacy.sql` inserts BORR_SSN_LST4 values: `'0142'`, `'0198'`, `'0167'`, `'0134'`, `'0156'`.

2. **Cross-reference with borrower data:** Comparing against `CDW_BORR_MSTR`:
   ```
   B-10001: phone=217-555-0142, ssn_lst4=0142  → phone last 4
   B-10002: phone=503-555-0198, ssn_lst4=0198  → phone last 4
   B-10003: phone=512-555-0167, ssn_lst4=0167  → phone last 4
   B-10004: phone=303-555-0134, ssn_lst4=0134  → phone last 4
   B-10005: phone=602-555-0156, ssn_lst4=0156  → phone last 4
   ```
   100% correlation — not coincidence.

3. **Entity mapping:** `LegacyLoanAccount.java` maps `BORR_SSN_LST4` to `borrowerSsnLast4` (line 30). The field is available to the service layer.

4. **Service usage:** `LoanService.toLoanSummary()` does **not** currently use `borrowerSsnLast4` in the DTO output. However, the field exists on the entity and could be used by future code or other consumers of the repository.

5. **Column mappings:** `column_mappings.md` (line 51) marks `BORR_SSN_LST4` as `*(dropped)*` in the modern schema — correctly identifying that denormalized SSN data should not be migrated.

### Root Cause

The upstream ETL process that populates `CDW_LN_ACCT` extracted the wrong field from the source system. The column derivation logic used `SUBSTR(BORR_PH_NBR, -4)` instead of `SUBSTR(DECRYPT(BORR_SSN_ENCR), -4)`. This is a classic ETL column-mapping error that went undetected because:
1. Both fields produce 4-digit strings, passing format validation
2. No cross-validation compared the derived `BORR_SSN_LST4` against the actual SSN
3. The schema uses `VARCHAR` for everything, so no type-based check caught the error

### Runtime Failure Mode

No crash — this is a **silent PII data corruption**. If any identity verification workflow uses `BORR_SSN_LST4`:
- Authentication based on "last 4 of SSN" would accept phone digits instead
- An attacker who knows the borrower's phone number could pass SSN verification
- Compliance audits for GLBA/SOX would flag this as a PII handling violation

### Fix Location

The service layer should not expose `BORR_SSN_LST4` in any API response. Validation should cross-check this field against borrower phone numbers and flag matches as suspect. See `LegacyDataValidator.java`.

---

## RCA-3: Uncaught NumberFormatException in String-to-Numeric Parsing (ANO-003)

### Anomaly

All numeric fields are stored as `VARCHAR` strings. The parsing methods in `LoanService.java` will throw uncaught exceptions for any malformed input.

### Code Path Trace

1. **parseLegacyAmount (lines 152–155):**
   ```java
   private BigDecimal parseLegacyAmount(String amount) {
       if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(amount.replace(",", ""));
   }
   ```
   Handles null/blank. Does NOT handle: `'$285,000'`, `'N/A'`, `'TBD'`, `'285 000'` (space as separator), `'285,000.00.00'` (double decimal). Any of these throw `NumberFormatException`.

2. **parseLegacyInteger (lines 162–165):**
   ```java
   private Integer parseLegacyInteger(String value) {
       if (value == null || value.isBlank()) return null;
       return Integer.parseInt(value.trim());
   }
   ```
   Handles null/blank. Does NOT handle: `'N/A'`, `'745.0'` (decimal credit score), `'~750'`, negative values for credit score. The column mapping specifies `BORR_CRDT_SCR` → `INTEGER`, but no range validation exists (valid FICO scores are 300–850).

3. **parseLegacyDecimal (lines 157–160):**
   ```java
   private BigDecimal parseLegacyDecimal(String value) {
       if (value == null || value.isBlank()) return BigDecimal.ZERO;
       return new BigDecimal(value.trim());
   }
   ```
   Same issue — no error handling for malformed strings.

4. **Exception propagation:** None of these methods catch exceptions. A `NumberFormatException` thrown in any parsing method propagates up through `toLoanSummary()` → `getAllLoans()` → `LoanController.getAllLoans()`, resulting in an unhandled exception that Spring Boot converts to an HTTP 500 response with a stack trace.

5. **Blast radius:** A single bad record in any table will cause the **entire list endpoint** to fail. For example, one bad `LN_ORIG_AMT` in any of the 5 loan accounts will crash `GET /api/loans` for all users.

### Root Cause

The service layer assumes all legacy string data is well-formed for numeric parsing. This assumption is unsafe because:
1. The legacy schema uses `VARCHAR` for everything — no database-level type enforcement
2. Legacy data warehouses commonly contain placeholder values (`'N/A'`, `'TBD'`, `'PENDING'`)
3. Different upstream systems may use different number formatting conventions
4. There are no input validation checks before parsing

### Runtime Failure Mode

**Hard crash** — HTTP 500 error for any API request that touches a record with a malformed numeric field. The entire request fails, not just the one bad record. This is a **service availability risk**.

### Fix Location

All three parsing methods in `LoanService.java` need try-catch blocks with:
- Structured error logging (which record, which field, what value)
- Safe fallback defaults (BigDecimal.ZERO for amounts, null for optional integers)
- Accumulated validation warnings that can be logged or returned

See implementation in `LegacyDataValidator.java`.
