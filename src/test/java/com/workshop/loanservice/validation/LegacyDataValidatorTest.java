package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // parseLegacyAmount tests
    // =========================================================================

    @Test
    void parseLegacyAmount_validCommaFormatted() {
        assertEquals(new BigDecimal("285000"), validator.parseLegacyAmount("285,000"));
    }

    @Test
    void parseLegacyAmount_validDecimalWithCommas() {
        assertEquals(new BigDecimal("1487.02"), validator.parseLegacyAmount("1,487.02"));
    }

    @Test
    void parseLegacyAmount_null_returnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseLegacyAmount(null));
    }

    @Test
    void parseLegacyAmount_blank_returnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseLegacyAmount("   "));
    }

    @Test
    void parseLegacyAmount_dollarSign_strippedAndParsed() {
        assertEquals(new BigDecimal("285000"), validator.parseLegacyAmount("$285,000"));
    }

    @Test
    void parseLegacyAmount_currencySuffix_strippedAndParsed() {
        assertEquals(new BigDecimal("285000"), validator.parseLegacyAmount("285,000 USD"));
    }

    @Test
    void parseLegacyAmount_noNumericChars_returnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseLegacyAmount("N/A"));
    }

    @Test
    void parseLegacyAmount_simpleDecimal() {
        assertEquals(new BigDecimal("4.750"), validator.parseLegacyAmount("4.750"));
    }

    @Test
    void parseLegacyAmount_zero() {
        assertEquals(new BigDecimal("0"), validator.parseLegacyAmount("0"));
    }

    @Test
    void parseLegacyAmount_negativeValue() {
        assertEquals(new BigDecimal("-100"), validator.parseLegacyAmount("-100"));
    }

    @Test
    void parseLegacyAmount_multipleDecimalPoints_returnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseLegacyAmount("12.34.56"));
    }

    // =========================================================================
    // parseLegacyDecimal tests
    // =========================================================================

    @Test
    void parseLegacyDecimal_validRate() {
        assertEquals(new BigDecimal("4.750"), validator.parseLegacyDecimal("4.750"));
    }

    @Test
    void parseLegacyDecimal_null_returnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseLegacyDecimal(null));
    }

    @Test
    void parseLegacyDecimal_blank_returnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseLegacyDecimal(""));
    }

    @Test
    void parseLegacyDecimal_withWhitespace_trimmed() {
        assertEquals(new BigDecimal("3.125"), validator.parseLegacyDecimal("  3.125  "));
    }

    @Test
    void parseLegacyDecimal_nonNumeric_returnsZero() {
        assertEquals(BigDecimal.ZERO, validator.parseLegacyDecimal("N/A"));
    }

    @Test
    void parseLegacyDecimal_percentSign_stripped() {
        assertEquals(new BigDecimal("82.5"), validator.parseLegacyDecimal("82.5%"));
    }

    // =========================================================================
    // parseLegacyInteger tests
    // =========================================================================

    @Test
    void parseLegacyInteger_validScore() {
        assertEquals(745, validator.parseLegacyInteger("745"));
    }

    @Test
    void parseLegacyInteger_null_returnsNull() {
        assertNull(validator.parseLegacyInteger(null));
    }

    @Test
    void parseLegacyInteger_blank_returnsNull() {
        assertNull(validator.parseLegacyInteger(""));
    }

    @Test
    void parseLegacyInteger_nonNumeric_returnsNull() {
        assertNull(validator.parseLegacyInteger("N/A"));
    }

    @Test
    void parseLegacyInteger_withWhitespace_trimmed() {
        assertEquals(15, validator.parseLegacyInteger("  15  "));
    }

    @Test
    void parseLegacyInteger_dash_returnsNull() {
        assertNull(validator.parseLegacyInteger("---"));
    }

    @Test
    void parseLegacyInteger_overflow_returnsNull() {
        assertNull(validator.parseLegacyInteger("2147483648"));
    }

    // =========================================================================
    // parseLegacyDate tests
    // =========================================================================

    @Test
    void parseLegacyDate_validDate() {
        assertEquals(LocalDate.of(1978, 3, 15), validator.parseLegacyDate("03/15/1978"));
    }

    @Test
    void parseLegacyDate_null_returnsNull() {
        assertNull(validator.parseLegacyDate(null));
    }

    @Test
    void parseLegacyDate_blank_returnsNull() {
        assertNull(validator.parseLegacyDate(""));
    }

    @Test
    void parseLegacyDate_invalidFormat_returnsNull() {
        assertNull(validator.parseLegacyDate("2025-12-15"));
    }

    @Test
    void parseLegacyDate_invalidDay_returnsNull() {
        assertNull(validator.parseLegacyDate("02/30/2025"));
    }

    @Test
    void parseLegacyDate_invalidMonth_returnsNull() {
        assertNull(validator.parseLegacyDate("13/01/2025"));
    }

    @Test
    void parseLegacyDate_nonLeapYear_feb29_returnsNull() {
        assertNull(validator.parseLegacyDate("02/29/2023"));
    }

    @Test
    void parseLegacyDate_leapYear_feb29_parsesCorrectly() {
        assertEquals(LocalDate.of(2024, 2, 29), validator.parseLegacyDate("02/29/2024"));
    }

    // =========================================================================
    // validateCreditScore tests
    // =========================================================================

    @Test
    void validateCreditScore_validScore() {
        assertEquals(745, validator.validateCreditScore("745"));
    }

    @Test
    void validateCreditScore_minBoundary() {
        assertEquals(300, validator.validateCreditScore("300"));
    }

    @Test
    void validateCreditScore_maxBoundary() {
        assertEquals(850, validator.validateCreditScore("850"));
    }

    @Test
    void validateCreditScore_belowMin_returnsNull() {
        assertNull(validator.validateCreditScore("299"));
    }

    @Test
    void validateCreditScore_aboveMax_returnsNull() {
        assertNull(validator.validateCreditScore("851"));
    }

    @Test
    void validateCreditScore_zero_returnsNull() {
        assertNull(validator.validateCreditScore("0"));
    }

    @Test
    void validateCreditScore_nonNumeric_returnsNull() {
        assertNull(validator.validateCreditScore("N/A"));
    }

    @Test
    void validateCreditScore_null_returnsNull() {
        assertNull(validator.validateCreditScore(null));
    }

    // =========================================================================
    // validatePaymentAmounts tests
    // =========================================================================

    @Test
    void validatePaymentAmounts_consistentPayment_noWarnings() {
        LegacyPayment pmt = createPayment("PMT-001", "2,924.18", "1,842.56", "815.50", "266.12", "0.00");
        List<String> warnings = validator.validatePaymentAmounts(pmt);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validatePaymentAmounts_mismatchedEscrow_producesWarning() {
        // Mirrors actual anomaly: PMT-2025120001 where escrow inflates component sum
        LegacyPayment pmt = createPayment("PMT-2025120001", "1,487.02", "456.78", "1,074.69", "355.55", "0.00");
        List<String> warnings = validator.validatePaymentAmounts(pmt);
        assertFalse(warnings.isEmpty());
        assertTrue(warnings.get(0).contains("PMT-2025120001"));
        assertTrue(warnings.get(0).contains("400.00"));
    }

    @Test
    void validatePaymentAmounts_mismatchedLateFee_producesWarning() {
        // Mirrors actual anomaly: PMT-2025110003 where late fee causes mismatch
        LegacyPayment pmt = createPayment("PMT-2025110003", "1,077.05", "295.82", "781.23", "0.00", "47.50");
        List<String> warnings = validator.validatePaymentAmounts(pmt);
        assertFalse(warnings.isEmpty());
        assertTrue(warnings.get(0).contains("47.50"));
    }

    // =========================================================================
    // validateLoanStatusConsistency tests
    // =========================================================================

    @Test
    void validateLoanStatusConsistency_activeWithZeroDelinquency_noWarnings() {
        LegacyLoanAccount acct = createLoanAccount("LN-001", "ACT", "0");
        List<String> warnings = validator.validateLoanStatusConsistency(acct);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLoanStatusConsistency_activeWithDelinquency_producesWarning() {
        // Mirrors actual anomaly: LN-2018-00089 has ACT status with 15 delinquency days
        LegacyLoanAccount acct = createLoanAccount("LN-2018-00089", "ACT", "15");
        List<String> warnings = validator.validateLoanStatusConsistency(acct);
        assertFalse(warnings.isEmpty());
        assertTrue(warnings.get(0).contains("LN-2018-00089"));
        assertTrue(warnings.get(0).contains("15"));
    }

    @Test
    void validateLoanStatusConsistency_defaultWithDelinquency_noWarnings() {
        LegacyLoanAccount acct = createLoanAccount("LN-002", "DFT", "90");
        List<String> warnings = validator.validateLoanStatusConsistency(acct);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLoanStatusConsistency_nullDelinquency_noWarnings() {
        LegacyLoanAccount acct = createLoanAccount("LN-003", "ACT", null);
        List<String> warnings = validator.validateLoanStatusConsistency(acct);
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // validateBorrower tests
    // =========================================================================

    @Test
    void validateBorrower_validBorrower_noWarnings() {
        LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell", "j.mitchell@email.com", "745", "03/15/1978");
        List<String> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateBorrower_missingFirstName_producesWarning() {
        LegacyBorrower borrower = createBorrower("B-001", null, "Smith", "smith@email.com", "700", "01/01/1990");
        List<String> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w -> w.contains("missing first name")));
    }

    @Test
    void validateBorrower_missingLastName_producesWarning() {
        LegacyBorrower borrower = createBorrower("B-001", "John", null, "john@email.com", "700", "01/01/1990");
        List<String> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w -> w.contains("missing last name")));
    }

    @Test
    void validateBorrower_missingEmail_producesWarning() {
        LegacyBorrower borrower = createBorrower("B-001", "John", "Smith", null, "700", "01/01/1990");
        List<String> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w -> w.contains("missing email")));
    }

    @Test
    void validateBorrower_invalidCreditScore_producesWarning() {
        LegacyBorrower borrower = createBorrower("B-001", "John", "Smith", "john@email.com", "999", "01/01/1990");
        List<String> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w -> w.contains("invalid credit score")));
    }

    @Test
    void validateBorrower_nonNumericCreditScore_producesWarning() {
        LegacyBorrower borrower = createBorrower("B-001", "John", "Smith", "john@email.com", "N/A", "01/01/1990");
        List<String> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w -> w.contains("invalid credit score")));
    }

    @Test
    void validateBorrower_invalidDate_producesWarning() {
        LegacyBorrower borrower = createBorrower("B-001", "John", "Smith", "john@email.com", "700", "13/01/2025");
        List<String> warnings = validator.validateBorrower(borrower);
        assertTrue(warnings.stream().anyMatch(w -> w.contains("invalid date of birth")));
    }

    // =========================================================================
    // validateLoanReferences tests
    // =========================================================================

    @Test
    void validateLoanReferences_allExist_noWarnings() {
        LegacyLoanAccount acct = createLoanAccount("LN-001", "ACT", "0");
        acct.setBorrowerId("B-10001");
        acct.setProductCode("FXD30");
        List<String> warnings = validator.validateLoanReferences(acct, true, true);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateLoanReferences_orphanedBorrower_producesWarning() {
        LegacyLoanAccount acct = createLoanAccount("LN-001", "ACT", "0");
        acct.setBorrowerId("B-99999");
        acct.setProductCode("FXD30");
        List<String> warnings = validator.validateLoanReferences(acct, false, true);
        assertTrue(warnings.stream().anyMatch(w -> w.contains("borrower ID")));
    }

    @Test
    void validateLoanReferences_orphanedProduct_producesWarning() {
        LegacyLoanAccount acct = createLoanAccount("LN-001", "ACT", "0");
        acct.setBorrowerId("B-10001");
        acct.setProductCode("INVALID");
        List<String> warnings = validator.validateLoanReferences(acct, true, false);
        assertTrue(warnings.stream().anyMatch(w -> w.contains("product code")));
    }

    // =========================================================================
    // validateDenormalizedBorrowerData tests
    // =========================================================================

    @Test
    void validateDenormalizedBorrowerData_consistent_noWarnings() {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber("LN-001");
        acct.setBorrowerFirstName("James");
        acct.setBorrowerLastName("Mitchell");

        LegacyBorrower borrower = new LegacyBorrower();
        borrower.setFirstName("James");
        borrower.setLastName("Mitchell");

        List<String> warnings = validator.validateDenormalizedBorrowerData(acct, borrower);
        assertTrue(warnings.isEmpty());
    }

    @Test
    void validateDenormalizedBorrowerData_nameDrift_producesWarning() {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber("LN-001");
        acct.setBorrowerFirstName("Jim");
        acct.setBorrowerLastName("Mitchell");

        LegacyBorrower borrower = new LegacyBorrower();
        borrower.setFirstName("James");
        borrower.setLastName("Mitchell");

        List<String> warnings = validator.validateDenormalizedBorrowerData(acct, borrower);
        assertFalse(warnings.isEmpty());
        assertTrue(warnings.get(0).contains("first name"));
    }

    @Test
    void validateDenormalizedBorrowerData_nullBorrower_noWarnings() {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber("LN-001");
        List<String> warnings = validator.validateDenormalizedBorrowerData(acct, null);
        assertTrue(warnings.isEmpty());
    }

    // =========================================================================
    // formatBorrowerName tests
    // =========================================================================

    @Test
    void formatBorrowerName_withMiddleInitial() {
        assertEquals("James R. Mitchell", validator.formatBorrowerName("James", "R", "Mitchell"));
    }

    @Test
    void formatBorrowerName_nullMiddleInitial() {
        assertEquals("Robert Williams", validator.formatBorrowerName("Robert", null, "Williams"));
    }

    @Test
    void formatBorrowerName_blankMiddleInitial() {
        assertEquals("Robert Williams", validator.formatBorrowerName("Robert", " ", "Williams"));
    }

    @Test
    void formatBorrowerName_nullFirstName() {
        assertEquals("Williams", validator.formatBorrowerName(null, null, "Williams"));
    }

    @Test
    void formatBorrowerName_allNull() {
        assertEquals("", validator.formatBorrowerName(null, null, null));
    }

    // =========================================================================
    // Helper methods
    // =========================================================================

    private LegacyPayment createPayment(String id, String total, String principal,
                                         String interest, String escrow, String lateFee) {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber(id);
        pmt.setLoanAccountNumber("LN-001");
        pmt.setPaymentDate("12/01/2025");
        pmt.setTotalAmount(total);
        pmt.setPrincipalAmount(principal);
        pmt.setInterestAmount(interest);
        pmt.setEscrowAmount(escrow);
        pmt.setLateFee(lateFee);
        pmt.setTypeCode("REG");
        pmt.setStatusCode("PST");
        return pmt;
    }

    private LegacyLoanAccount createLoanAccount(String id, String status, String delinquencyDays) {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber(id);
        acct.setStatusCode(status);
        acct.setDelinquencyDays(delinquencyDays);
        acct.setBorrowerId("B-10001");
        acct.setProductCode("FXD30");
        return acct;
    }

    private LegacyBorrower createBorrower(String id, String firstName, String lastName,
                                           String email, String creditScore, String dob) {
        LegacyBorrower borrower = new LegacyBorrower();
        borrower.setBorrowerId(id);
        borrower.setFirstName(firstName);
        borrower.setLastName(lastName);
        borrower.setEmail(email);
        borrower.setCreditScore(creditScore);
        borrower.setDateOfBirth(dob);
        return borrower;
    }
}
