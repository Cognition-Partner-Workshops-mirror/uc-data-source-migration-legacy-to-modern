# Root Cause Analysis — Top 3 Critical Data Anomalies

**Date:** 2026-05-26
**Reference:** `docs/DATA_ANOMALY_REPORT.md`

---

## RCA-1: SSN Last-4 Digits Populated from Phone Numbers (ANM-001)

### Anomaly Summary
Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` exactly matches the last 4 digits of the corresponding borrower's phone number in `CDW_BORR_MSTR`, not their actual SSN.

### Code Path Trace

1. **Entity layer** — `LegacyLoanAccount.java` maps the column at line 29–30:
   ```java
   @Column(name = "BORR_SSN_LST4")
   private String borrowerSsnLast4;
   ```
   The field is loaded directly from the VARCHAR column with no validation.

2. **Service layer** — `LoanService.java` does **not** currently use `borrowerSsnLast4` in any DTO conversion. The `toLoanSummary()` method (line 103–118) builds borrower names from the denormalized fields but never references SSN last-4. This means the corrupted data is latent — it exists in the entity but is not surfaced through the current API.

3. **Column mappings** — `data/mappings/column_mappings.md` line 51 marks `BORR_SSN_LST4` as `*(dropped)*` during migration. This means the corruption would be silently discarded, but:
   - Any pre-migration reporting or identity verification using this field is compromised
   - If the migration plan changes to include SSN verification as a data quality check, it would produce false failures

### Root Cause
The ETL process that populates `CDW_LN_ACCT` has a column mapping error. The source extraction query likely selected the phone number field (`BORR_PH_NBR`) instead of the SSN field when deriving the last-4 substring. Evidence:
- 100% correlation across all records (systematic, not random)
- The pattern `SUBSTRING(phone, -4)` exactly matches the values
- The actual SSN data exists encrypted in `BORR_SSN_ENCR` but was not used for the derivation

### Where This Would Cause Runtime Failure
- **Currently:** No runtime failure — the field is not exposed in the API
- **During migration:** If any migration validation step cross-references SSN last-4 against the encrypted SSN, it would flag every record as mismatched
- **If field is added to API:** Consumers relying on SSN last-4 for identity verification (e.g., phone-based authentication) would accept anyone who knows the borrower's phone number

### Recommended Remediation
1. Add a validation rule in `LegacyDataValidator` that flags when `BORR_SSN_LST4` matches the last 4 digits of the borrower's phone number
2. Do not expose `BORR_SSN_LST4` through the API until the upstream ETL is corrected
3. Coordinate with the CDW team to fix the source extraction query

---

## RCA-2: Payment Component Amounts Do Not Sum to Total (ANM-002)

### Anomaly Summary
In 3 of 10 payment records, `PMT_PRIN_AMT + PMT_INT_AMT + PMT_ESCROW_AMT + PMT_LATE_FEE ≠ PMT_AMT`.

### Code Path Trace

1. **Entity layer** — `LegacyPayment.java` maps each amount as an independent VARCHAR field (lines 25–38). No relationship between fields is enforced at the entity level.

2. **Service layer** — `LoanService.toPaymentDto()` (lines 134–147) parses each component independently:
   ```java
   dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
   dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
   dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
   dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
   dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
   ```
   Each call to `parseLegacyAmount()` (line 152–155) strips commas and parses to BigDecimal. **No cross-field validation is performed.** The service blindly trusts that the components sum correctly.

3. **API layer** — `LoanController.getPayments()` (line 33–35) returns the DTOs directly. The consumer receives inconsistent financial data with no warning.

### Root Cause
Two distinct data quality issues are present:

**Issue A — Escrow double-counting (PMT-2025120001, PMT-2025110001):**
The total amount ($1,487.02) represents principal + interest only, but the escrow amount ($355.55) was populated separately. The component sum ($1,887.02) exceeds the total by $400.00. Root cause: the source system likely records the "payment amount" as the P&I portion, with escrow collected separately, but the ETL populated the escrow column without updating the total.

**Issue B — Late fee exclusion (PMT-2025110003):**
The total amount ($1,077.05) equals principal + interest ($295.82 + $781.23 = $1,077.05) but the late fee ($47.50) is not included. Root cause: late fees are assessed separately from the regular payment in the source system, but the ETL populated the late fee column without adding it to the total.

### Where This Causes Incorrect API Response
- `GET /api/payments/loan/LN-2019-00142` returns payment PMT-2025120001 with `totalAmount: 1487.02` and components summing to `1887.02`
- Any consumer calculating `totalAmount - principalAmount - interestAmount` to determine escrow contribution gets a negative number (-$44.47)
- Financial reconciliation reports will show discrepancies

### Recommended Remediation
1. Add component-sum validation in the service layer: flag or auto-correct when sum differs from total
2. For API responses, include a `dataQualityWarnings` field when mismatches are detected
3. Define the business rule: should total include escrow and late fees? Apply consistently

---

## RCA-3: Null-Unsafe String Operations Causing NPE and "null" Literal Risks (ANM-003)

### Anomaly Summary
The schema allows NULL in every non-PK column, but the service layer performs string concatenation and type parsing without consistent null safety.

### Code Path Trace

1. **Schema** — `schema-legacy.sql` defines all columns as nullable VARCHAR (lines 14–34, 52–81, 84–99). Only the PRIMARY KEY columns (`BORR_ID`, `LN_ACCT_NBR`, `PROD_CD`, `PMT_SEQ_NBR`) have implicit NOT NULL.

2. **Service layer — `toBorrowerDto()`** — `LoanService.java` line 124:
   ```java
   dto.setFullName(borrower.getFirstName() + middle + " " + borrower.getLastName());
   ```
   If `getFirstName()` returns null, Java string concatenation produces `"null R. Mitchell"`. If `getLastName()` is also null: `"null null"`. This is not a NullPointerException — Java auto-converts null to the literal string `"null"` in concatenation — but it produces garbage API output.

3. **Service layer — `toLoanSummary()`** — `LoanService.java` line 106:
   ```java
   dto.setBorrowerName(acct.getBorrowerFirstName() + " " + acct.getBorrowerLastName());
   ```
   Same issue: null first/last names produce `"null null"` in the borrower name.

4. **Service layer — `toLoanSummary()`** — `LoanService.java` lines 114–115:
   ```java
   dto.setPropertyAddress(acct.getPropertyAddress() + ", " + acct.getPropertyCity()
           + ", " + acct.getPropertyState() + " " + acct.getPropertyZip());
   ```
   If any property field is null, the address becomes `"null, null, null null"`.

5. **Service layer — `parseLegacyAmount()`** — `LoanService.java` lines 152–155:
   ```java
   if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
   return new BigDecimal(amount.replace(",", ""));
   ```
   Null amounts are silently converted to `BigDecimal.ZERO`. A loan with a missing original amount would show as a $0 loan — masking the data quality issue rather than surfacing it.

6. **Service layer — `parseLegacyInteger()`** — `LoanService.java` lines 162–165:
   ```java
   if (value == null || value.isBlank()) return null;
   return Integer.parseInt(value.trim());
   ```
   Returns null for missing credit scores, which is correctly set on the DTO (`Integer` type). However, `Integer.parseInt()` throws `NumberFormatException` for non-numeric strings — no try-catch protection.

### Where This Causes Runtime Failure or Incorrect API Response

| Scenario | Code Location | Result |
|----------|--------------|--------|
| Null first name in CDW_BORR_MSTR | `toBorrowerDto()` line 124 | API returns `fullName: "null R. Mitchell"` |
| Null property address in CDW_LN_ACCT | `toLoanSummary()` line 114 | API returns `propertyAddress: "null, null, null null"` |
| Null loan amount in CDW_LN_ACCT | `parseLegacyAmount()` line 153 | API returns `originalAmount: 0` (masks missing data) |
| Non-numeric credit score (e.g., "N/A") | `parseLegacyInteger()` line 164 | `NumberFormatException` → HTTP 500 |
| Non-numeric amount (e.g., "$285,000") | `parseLegacyAmount()` line 154 | `NumberFormatException` → HTTP 500 |

### Root Cause
The service layer was written assuming the current seed data is representative of all possible legacy data. The translation methods handle the happy path (valid string representations) but not the full range of legacy data quality issues: nulls in required fields, non-numeric strings in numeric fields, and malformed dates.

### Recommended Remediation
1. Add null checks before all string concatenation operations — use `Objects.toString(value, "")` or explicit fallbacks
2. Wrap all numeric parsing in try-catch blocks with logging and meaningful defaults
3. Add a `LegacyDataValidator` that runs before DTO conversion, collecting all validation errors per record
4. Return validation warnings alongside data in the API response rather than silently masking issues
