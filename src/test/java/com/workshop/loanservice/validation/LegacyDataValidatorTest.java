package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =====================================================================
    // Numeric parsing with error handling (ANO-003)
    // =====================================================================

    @Test
    void parseAmount_validAmountWithCommas() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseAmount("285,000", "REC-1", "FIELD", warnings);
        assertEquals(new BigDecimal("285000"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_validDecimalWithCommas() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseAmount("1,487.02", "REC-1", "FIELD", warnings);
        assertEquals(new BigDecimal("1487.02"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_nullReturnsZero() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseAmount(null, "REC-1", "FIELD", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_blankReturnsZero() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseAmount("  ", "REC-1", "FIELD", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_nonNumericReturnsZeroWithWarning() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseAmount("N/A", "REC-1", "AMOUNT", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertEquals(1, warnings.size());
        assertEquals("INVALID_NUMERIC", warnings.get(0).getAnomalyType());
        assertEquals("Critical", warnings.get(0).getSeverity());
        assertEquals("REC-1", warnings.get(0).getRecordId());
        assertEquals("AMOUNT", warnings.get(0).getField());
    }

    @Test
    void parseAmount_currencySymbolStripped() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseAmount("$285,000", "REC-1", "FIELD", warnings);
        assertEquals(new BigDecimal("285000"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseAmount_textValueReturnsZeroWithWarning() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseAmount("PENDING", "REC-1", "FIELD", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertEquals(1, warnings.size());
        assertEquals("INVALID_NUMERIC", warnings.get(0).getAnomalyType());
    }

    @Test
    void parseDecimal_validDecimal() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseDecimal("4.750", "REC-1", "RATE", warnings);
        assertEquals(new BigDecimal("4.750"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseDecimal_percentSignStripped() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseDecimal("4.750%", "REC-1", "RATE", warnings);
        assertEquals(new BigDecimal("4.750"), result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseDecimal_nonNumericReturnsZeroWithWarning() {
        List<ValidationWarning> warnings = new ArrayList<>();
        BigDecimal result = validator.parseDecimal("variable", "REC-1", "RATE", warnings);
        assertEquals(BigDecimal.ZERO, result);
        assertEquals(1, warnings.size());
        assertEquals("INVALID_NUMERIC", warnings.get(0).getAnomalyType());
    }

    @Test
    void parseInteger_validInteger() {
        List<ValidationWarning> warnings = new ArrayList<>();
        Integer result = validator.parseInteger("745", "REC-1", "SCORE", warnings);
        assertEquals(745, result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseInteger_nullReturnsNull() {
        List<ValidationWarning> warnings = new ArrayList<>();
        Integer result = validator.parseInteger(null, "REC-1", "SCORE", warnings);
        assertNull(result);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseInteger_nonNumericReturnsNullWithWarning() {
        List<ValidationWarning> warnings = new ArrayList<>();
        Integer result = validator.parseInteger("PEND", "REC-1", "SCORE", warnings);
        assertNull(result);
        assertEquals(1, warnings.size());
        assertEquals("INVALID_NUMERIC", warnings.get(0).getAnomalyType());
    }

    // =====================================================================
    // Date validation (ANO-010, ANO-004)
    // =====================================================================

    @Test
    void parseDate_validDate() {
        List<ValidationWarning> warnings = new ArrayList<>();
        var result = validator.parseDate("03/15/1978", "REC-1", "DOB", warnings);
        assertNotNull(result);
        assertEquals(1978, result.getYear());
        assertEquals(3, result.getMonthValue());
        assertEquals(15, result.getDayOfMonth());
        assertTrue(warnings.isEmpty());
    }

    @Test
    void parseDate_invalidDateFormat() {
        List<ValidationWarning> warnings = new ArrayList<>();
        var result = validator.parseDate("2020-03-15", "REC-1", "DOB", warnings);
        assertNull(result);
        assertEquals(1, warnings.size());
        assertEquals("INVALID_DATE", warnings.get(0).getAnomalyType());
    }

    @Test
    void parseDate_impossibleDate() {
        List<ValidationWarning> warnings = new ArrayList<>();
        var result = validator.parseDate("02/30/2021", "REC-1", "DOB", warnings);
        assertNull(result);
        assertEquals(1, warnings.size());
        assertEquals("INVALID_DATE", warnings.get(0).getAnomalyType());
    }

    @Test
    void parseDate_textValue() {
        List<ValidationWarning> warnings = new ArrayList<>();
        var result = validator.parseDate("PENDING", "REC-1", "DOB", warnings);
        assertNull(result);
        assertEquals(1, warnings.size());
        assertEquals("INVALID_DATE", warnings.get(0).getAnomalyType());
    }

    @Test
    void parseDate_nullReturnsNull() {
        List<ValidationWarning> warnings = new ArrayList<>();
        var result = validator.parseDate(null, "REC-1", "DOB", warnings);
        assertNull(result);
        assertTrue(warnings.isEmpty());
    }

    // =====================================================================
    // Borrower validation (ANO-007, ANO-009)
    // =====================================================================

    @Test
    void validateBorrower_validBorrower() {
        LegacyBorrower borrower = createValidBorrower();
        List<ValidationWarning> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateBorrower_nullFirstName() {
        LegacyBorrower borrower = createValidBorrower();
        borrower.setFirstName(null);
        List<ValidationWarning> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "NULL_REQUIRED_FIELD".equals(w.getAnomalyType()) && "BORR_FST_NM".equals(w.getField())));
    }

    @Test
    void validateBorrower_nullLastName() {
        LegacyBorrower borrower = createValidBorrower();
        borrower.setLastName(null);
        List<ValidationWarning> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "NULL_REQUIRED_FIELD".equals(w.getAnomalyType()) && "BORR_LST_NM".equals(w.getField())));
    }

    @Test
    void validateBorrower_creditScoreOutOfRange() {
        LegacyBorrower borrower = createValidBorrower();
        borrower.setCreditScore("200");
        List<ValidationWarning> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "OUT_OF_RANGE".equals(w.getAnomalyType()) && "BORR_CRDT_SCR".equals(w.getField())));
    }

    @Test
    void validateBorrower_creditScoreNonNumeric() {
        LegacyBorrower borrower = createValidBorrower();
        borrower.setCreditScore("N/A");
        List<ValidationWarning> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "INVALID_NUMERIC".equals(w.getAnomalyType()) && "BORR_CRDT_SCR".equals(w.getField())));
    }

    @Test
    void validateBorrower_negativeIncome() {
        LegacyBorrower borrower = createValidBorrower();
        borrower.setAnnualIncome("-5,000");
        List<ValidationWarning> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "NEGATIVE_VALUE".equals(w.getAnomalyType()) && "BORR_ANN_INCM".equals(w.getField())));
    }

    @Test
    void validateBorrower_invalidStatusCode() {
        LegacyBorrower borrower = createValidBorrower();
        borrower.setStatusCode("XYZ");
        List<ValidationWarning> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "INVALID_STATUS_CODE".equals(w.getAnomalyType()) && "BORR_STAT_CD".equals(w.getField())));
    }

    @Test
    void validateBorrower_invalidDateOfBirth() {
        LegacyBorrower borrower = createValidBorrower();
        borrower.setDateOfBirth("13/01/2020");
        List<ValidationWarning> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "INVALID_DATE".equals(w.getAnomalyType()) && "BORR_DOB_DT".equals(w.getField())));
    }

    // =====================================================================
    // Loan account validation (ANO-005, ANO-006, ANO-009)
    // =====================================================================

    @Test
    void validateLoanAccount_validLoan() {
        LegacyLoanAccount loan = createValidLoan();
        List<ValidationWarning> warnings = validator.validateLoanAccount(
                loan, Set.of("B-10001"), Set.of("FXD30"));
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLoanAccount_orphanedBorrowerId() {
        LegacyLoanAccount loan = createValidLoan();
        List<ValidationWarning> warnings = validator.validateLoanAccount(
                loan, Set.of("B-99999"), Set.of("FXD30"));
        assertTrue(warnings.stream().anyMatch(w ->
                "ORPHANED_REFERENCE".equals(w.getAnomalyType()) && "BORR_ID".equals(w.getField())));
    }

    @Test
    void validateLoanAccount_orphanedProductCode() {
        LegacyLoanAccount loan = createValidLoan();
        List<ValidationWarning> warnings = validator.validateLoanAccount(
                loan, Set.of("B-10001"), Set.of("NOEXIST"));
        assertTrue(warnings.stream().anyMatch(w ->
                "ORPHANED_REFERENCE".equals(w.getAnomalyType()) && "PROD_CD".equals(w.getField())));
    }

    @Test
    void validateLoanAccount_delinquencyStatusInconsistency() {
        LegacyLoanAccount loan = createValidLoan();
        loan.setDelinquencyDays("15");
        loan.setStatusCode("ACT");
        List<ValidationWarning> warnings = validator.validateLoanAccount(
                loan, Set.of("B-10001"), Set.of("FXD30"));
        assertTrue(warnings.stream().anyMatch(w ->
                "STATUS_INCONSISTENCY".equals(w.getAnomalyType()) && "LN_DLQ_DAYS".equals(w.getField())));
    }

    @Test
    void validateLoanAccount_invalidStatusCode() {
        LegacyLoanAccount loan = createValidLoan();
        loan.setStatusCode("XYZ");
        List<ValidationWarning> warnings = validator.validateLoanAccount(
                loan, Set.of("B-10001"), Set.of("FXD30"));
        assertTrue(warnings.stream().anyMatch(w ->
                "INVALID_STATUS_CODE".equals(w.getAnomalyType()) && "LN_STAT_CD".equals(w.getField())));
    }

    @Test
    void validateLoanAccount_invalidPropertyType() {
        LegacyLoanAccount loan = createValidLoan();
        loan.setPropertyType("ZZZ");
        List<ValidationWarning> warnings = validator.validateLoanAccount(
                loan, Set.of("B-10001"), Set.of("FXD30"));
        assertTrue(warnings.stream().anyMatch(w ->
                "INVALID_STATUS_CODE".equals(w.getAnomalyType()) && "PROP_TYP_CD".equals(w.getField())));
    }

    @Test
    void validateLoanAccount_balanceExceedsOriginal() {
        LegacyLoanAccount loan = createValidLoan();
        loan.setOriginalAmount("100,000");
        loan.setCurrentBalance("150,000");
        List<ValidationWarning> warnings = validator.validateLoanAccount(
                loan, Set.of("B-10001"), Set.of("FXD30"));
        assertTrue(warnings.stream().anyMatch(w ->
                "BALANCE_EXCEEDS_ORIGINAL".equals(w.getAnomalyType())));
    }

    @Test
    void validateLoanAccount_nullBorrowerId() {
        LegacyLoanAccount loan = createValidLoan();
        loan.setBorrowerId(null);
        List<ValidationWarning> warnings = validator.validateLoanAccount(
                loan, Set.of("B-10001"), Set.of("FXD30"));
        assertTrue(warnings.stream().anyMatch(w ->
                "NULL_REQUIRED_FIELD".equals(w.getAnomalyType()) && "BORR_ID".equals(w.getField())));
    }

    // =====================================================================
    // Payment validation (ANO-001, ANO-005)
    // =====================================================================

    @Test
    void validatePayment_validPayment() {
        LegacyPayment payment = createValidPayment();
        List<ValidationWarning> warnings = validator.validatePayment(
                payment, Set.of("LN-2019-00142"));
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validatePayment_componentSumMismatch() {
        LegacyPayment payment = createValidPayment();
        payment.setTotalAmount("1,487.02");
        payment.setPrincipalAmount("456.78");
        payment.setInterestAmount("1,074.69");
        payment.setEscrowAmount("355.55");
        payment.setLateFee("0.00");
        // Sum = 1887.02, total = 1487.02 — mismatch of 400.00
        List<ValidationWarning> warnings = validator.validatePayment(
                payment, Set.of("LN-2019-00142"));
        assertTrue(warnings.stream().anyMatch(w ->
                "COMPONENT_SUM_MISMATCH".equals(w.getAnomalyType())));
        ValidationWarning mismatch = warnings.stream()
                .filter(w -> "COMPONENT_SUM_MISMATCH".equals(w.getAnomalyType()))
                .findFirst().orElseThrow();
        assertEquals("Critical", mismatch.getSeverity());
        assertTrue(mismatch.getMessage().contains("1887.02"));
        assertTrue(mismatch.getMessage().contains("1487.02"));
    }

    @Test
    void validatePayment_orphanedLoanAccount() {
        LegacyPayment payment = createValidPayment();
        List<ValidationWarning> warnings = validator.validatePayment(
                payment, Set.of("LN-DIFFERENT"));
        assertTrue(warnings.stream().anyMatch(w ->
                "ORPHANED_REFERENCE".equals(w.getAnomalyType()) && "LN_ACCT_NBR".equals(w.getField())));
    }

    @Test
    void validatePayment_invalidPaymentType() {
        LegacyPayment payment = createValidPayment();
        payment.setTypeCode("BAD");
        List<ValidationWarning> warnings = validator.validatePayment(
                payment, Set.of("LN-2019-00142"));
        assertTrue(warnings.stream().anyMatch(w ->
                "INVALID_STATUS_CODE".equals(w.getAnomalyType()) && "PMT_TYP_CD".equals(w.getField())));
    }

    @Test
    void validatePayment_invalidPaymentStatus() {
        LegacyPayment payment = createValidPayment();
        payment.setStatusCode("BAD");
        List<ValidationWarning> warnings = validator.validatePayment(
                payment, Set.of("LN-2019-00142"));
        assertTrue(warnings.stream().anyMatch(w ->
                "INVALID_STATUS_CODE".equals(w.getAnomalyType()) && "PMT_STAT_CD".equals(w.getField())));
    }

    @Test
    void validatePayment_nonNumericAmount() {
        LegacyPayment payment = createValidPayment();
        payment.setTotalAmount("REFUND");
        List<ValidationWarning> warnings = validator.validatePayment(
                payment, Set.of("LN-2019-00142"));
        assertTrue(warnings.stream().anyMatch(w ->
                "INVALID_NUMERIC".equals(w.getAnomalyType()) && "PMT_AMT".equals(w.getField())));
    }

    // =====================================================================
    // Denormalized data cross-reference (ANO-002, ANO-008)
    // =====================================================================

    @Test
    void validateDenormalizedData_ssnMatchesPhoneLast4() {
        LegacyLoanAccount loan = createValidLoan();
        loan.setBorrowerSsnLast4("0142");
        LegacyBorrower borrower = createValidBorrower();
        borrower.setPhoneNumber("217-555-0142");
        List<ValidationWarning> warnings = validator.validateDenormalizedBorrowerData(loan, borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "DATA_CROSS_CONTAMINATION".equals(w.getAnomalyType())
                        && "BORR_SSN_LST4".equals(w.getField())));
        ValidationWarning contamination = warnings.stream()
                .filter(w -> "DATA_CROSS_CONTAMINATION".equals(w.getAnomalyType()))
                .findFirst().orElseThrow();
        assertEquals("Critical", contamination.getSeverity());
    }

    @Test
    void validateDenormalizedData_namesDrift() {
        LegacyLoanAccount loan = createValidLoan();
        loan.setBorrowerFirstName("Jim");
        LegacyBorrower borrower = createValidBorrower();
        borrower.setFirstName("James");
        List<ValidationWarning> warnings = validator.validateDenormalizedBorrowerData(loan, borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "DENORMALIZED_DRIFT".equals(w.getAnomalyType()) && "BORR_FST_NM".equals(w.getField())));
    }

    @Test
    void validateDenormalizedData_lastNamesDrift() {
        LegacyLoanAccount loan = createValidLoan();
        loan.setBorrowerLastName("Smith");
        LegacyBorrower borrower = createValidBorrower();
        borrower.setLastName("Mitchell");
        List<ValidationWarning> warnings = validator.validateDenormalizedBorrowerData(loan, borrower);
        assertTrue(warnings.stream().anyMatch(w ->
                "DENORMALIZED_DRIFT".equals(w.getAnomalyType()) && "BORR_LST_NM".equals(w.getField())));
    }

    @Test
    void validateDenormalizedData_nullBorrowerNoErrors() {
        LegacyLoanAccount loan = createValidLoan();
        List<ValidationWarning> warnings = validator.validateDenormalizedBorrowerData(loan, null);
        assertTrue(warnings.isEmpty());
    }

    // =====================================================================
    // Helper methods to build test entities
    // =====================================================================

    private LegacyBorrower createValidBorrower() {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId("B-10001");
        b.setFirstName("James");
        b.setLastName("Mitchell");
        b.setMiddleInitial("R");
        b.setSsnEncrypted("ENC_XXX_001");
        b.setDateOfBirth("03/15/1978");
        b.setAddressLine1("742 Elm Street");
        b.setCity("Springfield");
        b.setStateCode("IL");
        b.setZipCode("62701");
        b.setPhoneNumber("217-555-0142");
        b.setEmail("j.mitchell@email.com");
        b.setCreditScore("745");
        b.setEmploymentStatus("EMPLOYED");
        b.setAnnualIncome("92,500");
        b.setCreatedDate("01/15/2019");
        b.setUpdatedDate("11/03/2025");
        b.setStatusCode("ACT");
        b.setRecordType("PRI");
        return b;
    }

    private LegacyLoanAccount createValidLoan() {
        LegacyLoanAccount l = new LegacyLoanAccount();
        l.setLoanAccountNumber("LN-2019-00142");
        l.setBorrowerId("B-10001");
        l.setBorrowerFirstName("James");
        l.setBorrowerLastName("Mitchell");
        l.setBorrowerSsnLast4("1234");
        l.setProductCode("FXD30");
        l.setOriginalAmount("285,000");
        l.setCurrentBalance("271,432.56");
        l.setInterestRate("4.750");
        l.setTermMonths("360");
        l.setMonthlyPayment("1,487.02");
        l.setOriginationDate("02/15/2019");
        l.setMaturityDate("02/15/2049");
        l.setFirstPaymentDate("03/15/2019");
        l.setNextPaymentDate("01/15/2026");
        l.setStatusCode("ACT");
        l.setDelinquencyDays("0");
        l.setEscrowBalance("3,245.80");
        l.setLtvPercent("82.5");
        l.setPropertyAddress("742 Elm Street");
        l.setPropertyCity("Springfield");
        l.setPropertyState("IL");
        l.setPropertyZip("62701");
        l.setPropertyType("SFR");
        l.setAppraisedValue("345,000");
        l.setCreatedDate("02/01/2019");
        l.setUpdatedDate("12/01/2025");
        return l;
    }

    private LegacyPayment createValidPayment() {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber("PMT-TEST001");
        p.setLoanAccountNumber("LN-2019-00142");
        p.setPaymentDate("12/15/2025");
        p.setTotalAmount("1,000.00");
        p.setPrincipalAmount("400.00");
        p.setInterestAmount("500.00");
        p.setEscrowAmount("100.00");
        p.setLateFee("0.00");
        p.setTypeCode("REG");
        p.setStatusCode("PST");
        p.setReceivedDate("12/14/2025");
        p.setProcessedDate("12/15/2025");
        p.setCreatedDate("12/15/2025");
        p.setUpdatedDate("12/15/2025");
        return p;
    }
}
