package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Borrower Validation Tests
    // =========================================================================

    @Nested
    @DisplayName("Borrower Validation")
    class BorrowerValidation {

        @Test
        @DisplayName("Valid borrower produces no critical warnings")
        void validBorrower() {
            LegacyBorrower borrower = createValidBorrower();
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.isValid());
        }

        @Test
        @DisplayName("Null first name produces CRITICAL warning")
        void nullFirstName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.CRITICAL, "BORR_FST_NM");
        }

        @Test
        @DisplayName("Blank last name produces CRITICAL warning")
        void blankLastName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName("   ");
            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.CRITICAL, "BORR_LST_NM");
        }

        @Test
        @DisplayName("Non-numeric credit score produces HIGH warning")
        void nonNumericCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("N/A");
            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.HIGH, "BORR_CRDT_SCR");
        }

        @Test
        @DisplayName("Out-of-range credit score produces MEDIUM warning")
        void outOfRangeCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("99");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.MEDIUM, "BORR_CRDT_SCR");
        }

        @Test
        @DisplayName("Invalid date format produces HIGH warning")
        void invalidDateFormat() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("1978-03-15");
            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.HIGH, "BORR_DOB_DT");
        }

        @Test
        @DisplayName("Non-numeric annual income produces HIGH warning")
        void nonNumericIncome() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("DECLINED");
            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.HIGH, "BORR_ANN_INCM");
        }

        @Test
        @DisplayName("Valid comma-formatted income passes validation")
        void validCommaIncome() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("125,000");
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.isValid());
        }

        @Test
        @DisplayName("Null date of birth produces MEDIUM warning")
        void nullDateOfBirth() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth(null);
            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.MEDIUM, "BORR_DOB_DT");
        }
    }

    // =========================================================================
    // Loan Account Validation Tests
    // =========================================================================

    @Nested
    @DisplayName("Loan Account Validation")
    class LoanAccountValidation {

        @Test
        @DisplayName("Valid loan account produces no critical warnings")
        void validLoanAccount() {
            LegacyLoanAccount loan = createValidLoanAccount();
            ValidationResult result = validator.validateLoanAccount(loan);
            assertTrue(result.isValid());
        }

        @Test
        @DisplayName("Null borrower ID produces CRITICAL warning (orphaned record)")
        void nullBorrowerId() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setBorrowerId(null);
            ValidationResult result = validator.validateLoanAccount(loan);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.CRITICAL, "BORR_ID");
        }

        @Test
        @DisplayName("Delinquency > 0 with ACT status produces HIGH warning")
        void delinquencyWithActiveStatus() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setDelinquencyDays("15");
            loan.setStatusCode("ACT");
            ValidationResult result = validator.validateLoanAccount(loan);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.HIGH, "LN_DLQ_DAYS/LN_STAT_CD");
        }

        @Test
        @DisplayName("Delinquency > 0 with DFT status is acceptable")
        void delinquencyWithDefaultStatus() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setDelinquencyDays("30");
            loan.setStatusCode("DFT");
            ValidationResult result = validator.validateLoanAccount(loan);
            assertTrue(result.isValid());
            assertNoWarningForField(result, "LN_DLQ_DAYS/LN_STAT_CD");
        }

        @Test
        @DisplayName("Invalid status code produces MEDIUM warning")
        void invalidStatusCode() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setStatusCode("XXX");
            ValidationResult result = validator.validateLoanAccount(loan);
            assertHasWarning(result, DataQualityWarning.Severity.MEDIUM, "LN_STAT_CD");
        }

        @Test
        @DisplayName("Non-numeric interest rate produces HIGH warning")
        void nonNumericInterestRate() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setInterestRate("4.75%");
            ValidationResult result = validator.validateLoanAccount(loan);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.HIGH, "LN_INT_RT");
        }

        @Test
        @DisplayName("Invalid property type produces MEDIUM warning")
        void invalidPropertyType() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setPropertyType("XYZ");
            ValidationResult result = validator.validateLoanAccount(loan);
            assertHasWarning(result, DataQualityWarning.Severity.MEDIUM, "PROP_TYP_CD");
        }

        @Test
        @DisplayName("Non-numeric original amount produces HIGH warning")
        void nonNumericAmount() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setOriginalAmount("$285,000");
            ValidationResult result = validator.validateLoanAccount(loan);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.HIGH, "LN_ORIG_AMT");
        }
    }

    // =========================================================================
    // Payment Validation Tests
    // =========================================================================

    @Nested
    @DisplayName("Payment Validation")
    class PaymentValidation {

        @Test
        @DisplayName("Valid payment produces no critical warnings")
        void validPayment() {
            LegacyPayment payment = createValidPayment();
            ValidationResult result = validator.validatePayment(payment);
            assertTrue(result.isValid());
        }

        @Test
        @DisplayName("Payment component sum mismatch produces CRITICAL warning")
        void componentSumMismatch() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("1,487.02");
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");
            // Sum = 1,887.02 != 1,487.02
            ValidationResult result = validator.validatePayment(payment);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.CRITICAL, "PMT_AMT");
        }

        @Test
        @DisplayName("Payment with matching components passes validation")
        void componentSumMatches() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("2,924.18");
            payment.setPrincipalAmount("1,842.56");
            payment.setInterestAmount("815.50");
            payment.setEscrowAmount("266.12");
            payment.setLateFee("0.00");
            // Sum = 2,924.18 == 2,924.18
            ValidationResult result = validator.validatePayment(payment);
            assertNoWarningForField(result, "PMT_AMT");
        }

        @Test
        @DisplayName("Late fee not reflected in total produces CRITICAL warning")
        void lateFeeNotInTotal() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("1,077.05");
            payment.setPrincipalAmount("295.82");
            payment.setInterestAmount("781.23");
            payment.setEscrowAmount("0.00");
            payment.setLateFee("47.50");
            // Sum = 1,124.55 != 1,077.05
            ValidationResult result = validator.validatePayment(payment);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.CRITICAL, "PMT_AMT");
        }

        @Test
        @DisplayName("Null loan account number produces CRITICAL warning (orphaned)")
        void orphanedPayment() {
            LegacyPayment payment = createValidPayment();
            payment.setLoanAccountNumber(null);
            ValidationResult result = validator.validatePayment(payment);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.CRITICAL, "LN_ACCT_NBR");
        }

        @Test
        @DisplayName("Invalid payment type produces MEDIUM warning")
        void invalidPaymentType() {
            LegacyPayment payment = createValidPayment();
            payment.setTypeCode("ZZZ");
            ValidationResult result = validator.validatePayment(payment);
            assertHasWarning(result, DataQualityWarning.Severity.MEDIUM, "PMT_TYP_CD");
        }

        @Test
        @DisplayName("Invalid payment status produces MEDIUM warning")
        void invalidPaymentStatus() {
            LegacyPayment payment = createValidPayment();
            payment.setStatusCode("ABC");
            ValidationResult result = validator.validatePayment(payment);
            assertHasWarning(result, DataQualityWarning.Severity.MEDIUM, "PMT_STAT_CD");
        }

        @Test
        @DisplayName("Non-numeric amount produces HIGH warning")
        void nonNumericAmount() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("INVALID");
            ValidationResult result = validator.validatePayment(payment);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.HIGH, "PMT_AMT");
        }
    }

    // =========================================================================
    // Cross-Reference Validation Tests
    // =========================================================================

    @Nested
    @DisplayName("Cross-Reference Validation")
    class CrossReferenceValidation {

        @Test
        @DisplayName("SSN last-4 matching phone last-4 produces CRITICAL warning")
        void ssnMatchesPhone() {
            ValidationResult result = new ValidationResult();
            validator.validateSsnAgainstPhone("0142", "217-555-0142", "LN-TEST", result);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.CRITICAL, "BORR_SSN_LST4");
        }

        @Test
        @DisplayName("SSN last-4 not matching phone is acceptable")
        void ssnDoesNotMatchPhone() {
            ValidationResult result = new ValidationResult();
            validator.validateSsnAgainstPhone("9876", "217-555-0142", "LN-TEST", result);
            assertTrue(result.isValid());
            assertTrue(result.getWarnings().isEmpty());
        }

        @Test
        @DisplayName("Null SSN or phone skips validation gracefully")
        void nullSsnOrPhone() {
            ValidationResult result = new ValidationResult();
            validator.validateSsnAgainstPhone(null, "217-555-0142", "LN-TEST", result);
            assertTrue(result.isValid());

            validator.validateSsnAgainstPhone("0142", null, "LN-TEST", result);
            assertTrue(result.isValid());
        }

        @Test
        @DisplayName("Non-existent borrower produces CRITICAL referential integrity warning")
        void orphanedLoanAccount() {
            LegacyLoanAccount loan = createValidLoanAccount();
            ValidationResult result = new ValidationResult();
            validator.validateReferentialIntegrity(loan, false, true, result);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.CRITICAL, "BORR_ID");
        }

        @Test
        @DisplayName("Non-existent product produces HIGH referential integrity warning")
        void orphanedProductReference() {
            LegacyLoanAccount loan = createValidLoanAccount();
            ValidationResult result = new ValidationResult();
            validator.validateReferentialIntegrity(loan, true, false, result);
            assertFalse(result.isValid());
            assertHasWarning(result, DataQualityWarning.Severity.HIGH, "PROD_CD");
        }
    }

    // =========================================================================
    // Helper Methods
    // =========================================================================

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

    private LegacyLoanAccount createValidLoanAccount() {
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
        p.setTotalAmount("2,924.18");
        p.setPrincipalAmount("1,842.56");
        p.setInterestAmount("815.50");
        p.setEscrowAmount("266.12");
        p.setLateFee("0.00");
        p.setTypeCode("REG");
        p.setStatusCode("PST");
        p.setReceivedDate("12/14/2025");
        p.setProcessedDate("12/15/2025");
        p.setCreatedDate("12/15/2025");
        p.setUpdatedDate("12/15/2025");
        return p;
    }

    private void assertHasWarning(ValidationResult result, DataQualityWarning.Severity severity, String field) {
        List<DataQualityWarning> warnings = result.getWarnings();
        boolean found = warnings.stream()
                .anyMatch(w -> w.getSeverity() == severity && w.getField().equals(field));
        assertTrue(found, "Expected " + severity + " warning for field '" + field
                + "' but got: " + warnings);
    }

    private void assertNoWarningForField(ValidationResult result, String field) {
        List<DataQualityWarning> warnings = result.getWarnings();
        boolean found = warnings.stream().anyMatch(w -> w.getField().equals(field));
        assertFalse(found, "Expected no warning for field '" + field + "' but found one: " + warnings);
    }
}
