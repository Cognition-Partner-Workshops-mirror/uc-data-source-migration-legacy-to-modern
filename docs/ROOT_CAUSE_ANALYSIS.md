# Root Cause Analysis — Top 3 Critical Anomalies

## RCA-001: SSN Last-4 Populated with Phone Number Suffixes (ANM-001)

### Anomaly Summary

Every `BORR_SSN_LST4` value in `CDW_LN_ACCT` matches the last 4 digits of the corresponding borrower's phone number, not their SSN.

### Code Trace

**Data Flow:**
```
CDW_LN_ACCT.BORR_SSN_LST4 (VARCHAR)
  → LegacyLoanAccount.borrowerSsnLast4 (entity field, line 30)
    → Not exposed via LoanService (field is read but unused in DTO mapping)
```

**Entity mapping** (`LegacyLoanAccount.java:29-30`):
```java
@Column(name = "BORR_SSN_LST4")
private String borrowerSsnLast4;
```

**Service layer** (`LoanService.java:103-118`): The `toLoanSummary()` method maps loan accounts to DTOs but does NOT currently use `borrowerSsnLast4`. However, the field IS loaded by JPA and would be used by any future identity-verification feature or migration process.

**Column mapping** (`data/mappings/column_mappings.md:51`):
```
| BORR_SSN_LST4 | VARCHAR(4) | *(dropped)* | — | Denormalized; use borrower FK |
```

The mapping document marks this field as "dropped" in the modern schema, which would propagate the corruption silently — migration code would skip validation of this field entirely.

### Root Cause

The ETL process that populated `CDW_LN_ACCT` used an incorrect source column. The loading script likely extracted characters from positions matching the phone number field (`BORR_PH_NBR`) instead of the encrypted SSN field (`BORR_SSN_ENCR`). Evidence:

1. **100% correlation** between SSN_LST4 and phone suffix across all records
2. **Pattern**: Phone format is `XXX-555-YYYY` and SSN_LST4 = `YYYY` for every row
3. **ETL column offset error**: In a fixed-width or positional extract, phone and SSN fields are adjacent in the borrower record, suggesting a column offset miscalculation

### Runtime Impact

- **Current**: No immediate runtime failure (field is loaded but unused in API)
- **Migration risk**: If migration code attempts to validate SSN consistency between `CDW_BORR_MSTR.BORR_SSN_ENCR` and `CDW_LN_ACCT.BORR_SSN_LST4`, 100% of records would fail validation
- **Future feature risk**: Any identity verification feature using this field would produce false negatives

### Resolution

Add ingestion-time validation that:
1. Verifies `BORR_SSN_LST4` is exactly 4 digits
2. Cross-checks it does NOT match the last 4 of the borrower's phone number
3. Flags all current records as requiring SSN data remediation

---

## RCA-002: Payment Component Amounts Do Not Sum to Total (ANM-002)

### Anomaly Summary

For loan `LN-2019-00142`, payment component amounts (principal + interest + escrow + late fee) sum to $1,887.02 but the stated total is $1,487.02 — a consistent $400.00 discrepancy across both payment records for this loan.

### Code Trace

**Data Flow:**
```
CDW_PMT_HIST.PMT_AMT → LegacyPayment.totalAmount → parseLegacyAmount() → PaymentDto.totalAmount
CDW_PMT_HIST.PMT_PRIN_AMT → LegacyPayment.principalAmount → parseLegacyAmount() → PaymentDto.principalAmount
CDW_PMT_HIST.PMT_INT_AMT → LegacyPayment.interestAmount → parseLegacyAmount() → PaymentDto.interestAmount
CDW_PMT_HIST.PMT_ESCROW_AMT → LegacyPayment.escrowAmount → parseLegacyAmount() → PaymentDto.escrowAmount
CDW_PMT_HIST.PMT_LATE_FEE → LegacyPayment.lateFee → parseLegacyAmount() → PaymentDto.lateFee
```

**Service layer** (`LoanService.java:134-147`):
```java
private PaymentDto toPaymentDto(LegacyPayment pmt) {
    dto.setTotalAmount(parseLegacyAmount(pmt.getTotalAmount()));
    dto.setPrincipalAmount(parseLegacyAmount(pmt.getPrincipalAmount()));
    dto.setInterestAmount(parseLegacyAmount(pmt.getInterestAmount()));
    dto.setEscrowAmount(parseLegacyAmount(pmt.getEscrowAmount()));
    dto.setLateFee(parseLegacyAmount(pmt.getLateFee()));
    // NO validation that components sum to total
}
```

**The parser** (`LoanService.java:152-155`):
```java
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));
}
```

Each field is parsed independently with zero cross-field validation. The API returns all values as-is, presenting mathematically inconsistent data to consumers.

### Root Cause

The $400.00 discrepancy is exactly equal to the escrow amount ($355.55) plus a rounding artifact ($44.45). Analysis:

1. **Loan LN-2019-00142** has `LN_ESCROW_BAL = '3,245.80'` and monthly payment of `1,487.02`
2. The total `PMT_AMT = 1,487.02` matches the monthly payment amount exactly
3. The component breakdown appears to be from a **different calculation basis** — likely from a full amortization schedule that includes escrow as a component

**Hypothesis**: Two different systems populated these fields:
- **System A** (payment processing): Set `PMT_AMT` to the actual payment received (principal + interest only = ~$1,487)
- **System B** (amortization engine): Set component breakdowns including escrow allocation, which totals $1,887.02

The $44.45 excess in principal+interest (1,531.47 vs 1,487.02) suggests the amortization engine calculated components based on a different loan balance snapshot.

### Runtime Impact

- **Current**: API returns inconsistent data — consumers doing `total - principal - interest` get different values than `escrow + lateFee`
- **Financial calculations**: Any downstream system summing components will calculate a different balance than one using the total
- **Audit trail**: Payment reconciliation reports will show a persistent $400 imbalance

### Resolution

Add validation at ingestion time:
1. Calculate expected total from components
2. Flag records where `|total - componentSum| > $0.01`
3. Include a `validated` flag or `discrepancy` field in the DTO so consumers know when data is inconsistent

---

## RCA-003: Numeric Parsing Without Error Handling (ANM-003)

### Anomaly Summary

All numeric conversions in the service layer use raw `Integer.parseInt()` and `new BigDecimal()` with no exception handling, making the entire API vulnerable to a single malformed record.

### Code Trace

**Vulnerable methods** in `LoanService.java`:

```java
// Line 152-155: Amount parsing
private BigDecimal parseLegacyAmount(String amount) {
    if (amount == null || amount.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(amount.replace(",", ""));  // THROWS on "$", "%", "N/A", etc.
}

// Line 157-160: Decimal parsing
private BigDecimal parseLegacyDecimal(String value) {
    if (value == null || value.isBlank()) return BigDecimal.ZERO;
    return new BigDecimal(value.trim());  // THROWS on non-numeric
}

// Line 162-165: Integer parsing
private Integer parseLegacyInteger(String value) {
    if (value == null || value.isBlank()) return null;
    return Integer.parseInt(value.trim());  // THROWS on "N/A", "780+", "---"
}
```

**Call chain for a single API request** (`GET /api/loans`):

```
LoanController.getAllLoans()
  → LoanService.getAllLoans()
    → loanAccountRepository.findAll()  [loads ALL records]
    → .map(acct -> toLoanSummary(acct, product))
      → parseLegacyAmount(acct.getOriginalAmount())     // can throw
      → parseLegacyAmount(acct.getCurrentBalance())     // can throw
      → parseLegacyDecimal(acct.getInterestRate())      // can throw
      → parseLegacyAmount(acct.getMonthlyPayment())     // can throw
```

A single bad record in ANY amount field will cause `NumberFormatException` which propagates as an HTTP 500 for the ENTIRE `/api/loans` response — not just the bad record.

**Column mapping context** (`data/mappings/column_mappings.md`):
- Line 20: `BORR_CRDT_SCR` → `credit_score INTEGER` — "Parse string → integer"
- Line 22: `BORR_ANN_INCM` → `annual_income DECIMAL` — "Remove commas, parse → decimal"
- Line 55: `LN_INT_RT` → `interest_rate DECIMAL(5,3)` — "Parse string → decimal"

The mapping document acknowledges these transformations are needed but the service code implements them without defensive guards.

### Root Cause

The legacy schema uses VARCHAR for ALL fields (schema comment: "VARCHAR for everything (loose typing)"). This design decision means:

1. **No database-level type enforcement**: Any string can be inserted into numeric-intent columns
2. **Service layer assumes well-formed data**: Parsing methods only handle null/blank but not malformed values
3. **No data quality gate**: There is no validation layer between the database and the parsing logic
4. **Blast radius is full-table**: `findAll()` queries load every record, and `.map()` applies parsing to each one — a single bad record in the table takes down the entire endpoint

### Runtime Impact

- **Availability**: One malformed record → entire API endpoint returns HTTP 500
- **Debugging difficulty**: `NumberFormatException` message doesn't identify which record or field caused the failure
- **Data visibility loss**: When an endpoint fails, ALL records become inaccessible, not just the bad one
- **Silent zero-value substitution**: For null/blank values, `BigDecimal.ZERO` is returned — this hides missing data by treating it as zero dollars

### Resolution

1. Wrap all parsing in try-catch blocks with structured error logging (record ID + field name + raw value)
2. Return fallback values (null or zero) for unparseable fields instead of crashing
3. Add a `List<String> validationWarnings` field to DTOs so consumers know when fallbacks were applied
4. Implement pre-ingestion validation that pattern-matches values before parsing
