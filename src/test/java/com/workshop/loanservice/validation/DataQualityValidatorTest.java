package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class DataQualityValidatorTest {

    private DataQualityValidator validator;

    @BeforeEach
    void setUp() {
        validator = new DataQualityValidator();
    }

    @Nested
    @DisplayName("Borrower Validation")
    class BorrowerValidation {

        @Test
        @DisplayName("Valid borrower produces no issues")
        void validBorrower() {
            LegacyBorrower borrower = createValidBorrower();
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.isEmpty(), "Expected no issues but got: " + issues);
        }

        @Test
        @DisplayName("Null first name is flagged as CRITICAL")
        void nullFirstName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertHasIssue(issues, ValidationIssue.Severity.CRITICAL, "BORR_FST_NM");
        }

        @Test
        @DisplayName("Blank last name is flagged as CRITICAL")
        void blankLastName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName("   ");
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertHasIssue(issues, ValidationIssue.Severity.CRITICAL, "BORR_LST_NM");
        }

        @Test
        @DisplayName("Invalid status code is flagged as MEDIUM")
        void invalidStatusCode() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setStatusCode("XYZ");
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertHasIssue(issues, ValidationIssue.Severity.MEDIUM, "BORR_STAT_CD");
        }

        @Test
        @DisplayName("Non-numeric credit score is flagged as HIGH")
        void nonNumericCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("N/A");
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertHasIssue(issues, ValidationIssue.Severity.HIGH, "BORR_CRDT_SCR");
        }

        @Test
        @DisplayName("Credit score out of range is flagged as MEDIUM")
        void creditScoreOutOfRange() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("200");
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertHasIssue(issues, ValidationIssue.Severity.MEDIUM, "BORR_CRDT_SCR");
        }

        @Test
        @DisplayName("Invalid date format is flagged as MEDIUM")
        void invalidDateFormat() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("1978-03-15");
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertHasIssue(issues, ValidationIssue.Severity.MEDIUM, "BORR_DOB_DT");
        }

        @Test
        @DisplayName("Invalid date value (Feb 30) is flagged")
        void invalidDateValue() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("02/30/1978");
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertHasIssue(issues, ValidationIssue.Severity.MEDIUM, "BORR_DOB_DT");
        }

        @Test
        @DisplayName("Annual income with dollar sign is flagged as HIGH")
        void annualIncomeWithDollarSign() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("$92,500");
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertHasIssue(issues, ValidationIssue.Severity.HIGH, "BORR_ANN_INCM");
        }

        @Test
        @DisplayName("Annual income with valid comma format passes")
        void validAnnualIncome() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("125,000");
            List<ValidationIssue> issues = validator.validateBorrower(borrower);
            assertTrue(issues.stream().noneMatch(i -> i.getColumn().equals("BORR_ANN_INCM")));
        }
    }

    @Nested
    @DisplayName("Loan Account Validation")
    class LoanAccountValidation {

        private final Set<String> validBorrowerIds = Set.of("B-10001", "B-10002", "B-10003");
        private final Set<String> validProductCodes = Set.of("FXD30", "FXD15", "ARM51");

        @Test
        @DisplayName("Valid loan account produces no issues")
        void validLoanAccount() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<ValidationIssue> issues = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertTrue(issues.isEmpty(), "Expected no issues but got: " + issues);
        }

        @Test
        @DisplayName("Orphaned borrower ID is flagged as CRITICAL")
        void orphanedBorrowerId() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerId("B-99999");
            List<ValidationIssue> issues = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertHasIssue(issues, ValidationIssue.Severity.CRITICAL, "BORR_ID");
            assertTrue(issues.stream().anyMatch(i ->
                    i.getMessage().contains("Orphaned record")));
        }

        @Test
        @DisplayName("Orphaned product code is flagged as HIGH")
        void orphanedProductCode() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setProductCode("INVALID");
            List<ValidationIssue> issues = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertHasIssue(issues, ValidationIssue.Severity.HIGH, "PROD_CD");
            assertTrue(issues.stream().anyMatch(i ->
                    i.getMessage().contains("product not found")));
        }

        @Test
        @DisplayName("Invalid loan status code is flagged")
        void invalidLoanStatus() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setStatusCode("BAD");
            List<ValidationIssue> issues = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertHasIssue(issues, ValidationIssue.Severity.MEDIUM, "LN_STAT_CD");
        }

        @Test
        @DisplayName("Amount with invalid characters is flagged as HIGH")
        void invalidAmountFormat() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setOriginalAmount("$285,000");
            List<ValidationIssue> issues = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertHasIssue(issues, ValidationIssue.Severity.HIGH, "LN_ORIG_AMT");
        }

        @Test
        @DisplayName("Interest rate out of range is flagged")
        void interestRateOutOfRange() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setInterestRate("45.0");
            List<ValidationIssue> issues = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertHasIssue(issues, ValidationIssue.Severity.MEDIUM, "LN_INT_RT");
        }

        @Test
        @DisplayName("Non-numeric delinquency days is flagged")
        void nonNumericDelinquencyDays() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setDelinquencyDays("none");
            List<ValidationIssue> issues = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertHasIssue(issues, ValidationIssue.Severity.HIGH, "LN_DLQ_DAYS");
        }

        @Test
        @DisplayName("Null borrower ID is flagged as CRITICAL")
        void nullBorrowerId() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerId(null);
            List<ValidationIssue> issues = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertHasIssue(issues, ValidationIssue.Severity.CRITICAL, "BORR_ID");
        }

        @Test
        @DisplayName("Unknown property type is flagged as LOW")
        void unknownPropertyType() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setPropertyType("XYZ");
            List<ValidationIssue> issues = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertHasIssue(issues, ValidationIssue.Severity.LOW, "PROP_TYP_CD");
        }
    }

    @Nested
    @DisplayName("Payment Validation")
    class PaymentValidation {

        private final Set<String> validLoanAccounts = Set.of("LN-2019-00142", "LN-2020-00398");

        @Test
        @DisplayName("Valid payment produces no issues")
        void validPayment() {
            LegacyPayment pmt = createValidPayment();
            List<ValidationIssue> issues = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(issues.isEmpty(), "Expected no issues but got: " + issues);
        }

        @Test
        @DisplayName("Orphaned loan account is flagged as CRITICAL")
        void orphanedLoanAccount() {
            LegacyPayment pmt = createValidPayment();
            pmt.setLoanAccountNumber("LN-NONEXIST");
            List<ValidationIssue> issues = validator.validatePayment(pmt, validLoanAccounts);
            assertHasIssue(issues, ValidationIssue.Severity.CRITICAL, "LN_ACCT_NBR");
        }

        @Test
        @DisplayName("Payment components not reconciling is flagged as CRITICAL")
        void paymentReconciliationFailure() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");
            // Sum = 1887.02, discrepancy = 400.00
            List<ValidationIssue> issues = validator.validatePayment(pmt, validLoanAccounts);
            assertHasIssue(issues, ValidationIssue.Severity.CRITICAL, "PMT_AMT");
            assertTrue(issues.stream().anyMatch(i ->
                    i.getMessage().contains("do not reconcile")));
        }

        @Test
        @DisplayName("Payment components reconciling within tolerance produces no issue")
        void paymentReconciliationSuccess() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTotalAmount("2,924.18");
            pmt.setPrincipalAmount("1,842.56");
            pmt.setInterestAmount("815.50");
            pmt.setEscrowAmount("266.12");
            pmt.setLateFee("0.00");
            // Sum = 2924.18, matches total
            List<ValidationIssue> issues = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(issues.stream().noneMatch(i ->
                    i.getMessage().contains("do not reconcile")));
        }

        @Test
        @DisplayName("Invalid payment status code is flagged")
        void invalidPaymentStatus() {
            LegacyPayment pmt = createValidPayment();
            pmt.setStatusCode("XXX");
            List<ValidationIssue> issues = validator.validatePayment(pmt, validLoanAccounts);
            assertHasIssue(issues, ValidationIssue.Severity.MEDIUM, "PMT_STAT_CD");
        }

        @Test
        @DisplayName("Invalid payment type code is flagged")
        void invalidPaymentType() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTypeCode("BAD");
            List<ValidationIssue> issues = validator.validatePayment(pmt, validLoanAccounts);
            assertHasIssue(issues, ValidationIssue.Severity.MEDIUM, "PMT_TYP_CD");
        }

        @Test
        @DisplayName("Non-numeric payment amount is flagged")
        void nonNumericAmount() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTotalAmount("$1,487.02");
            List<ValidationIssue> issues = validator.validatePayment(pmt, validLoanAccounts);
            assertHasIssue(issues, ValidationIssue.Severity.HIGH, "PMT_AMT");
        }

        @Test
        @DisplayName("Invalid payment date format is flagged")
        void invalidPaymentDate() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("2025-12-15");
            List<ValidationIssue> issues = validator.validatePayment(pmt, validLoanAccounts);
            assertHasIssue(issues, ValidationIssue.Severity.MEDIUM, "PMT_DT");
        }
    }

    // =========================================================================
    // Helper Methods
    // =========================================================================

    private void assertHasIssue(List<ValidationIssue> issues, ValidationIssue.Severity severity, String column) {
        boolean found = issues.stream().anyMatch(i ->
                i.getSeverity() == severity && i.getColumn().equals(column));
        assertTrue(found, String.format("Expected %s issue on column %s but got: %s",
                severity, column, issues));
    }

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
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber("LN-2019-00142");
        acct.setBorrowerId("B-10001");
        acct.setBorrowerFirstName("James");
        acct.setBorrowerLastName("Mitchell");
        acct.setBorrowerSsnLast4("0142");
        acct.setProductCode("FXD30");
        acct.setOriginalAmount("285,000");
        acct.setCurrentBalance("271,432.56");
        acct.setInterestRate("4.750");
        acct.setTermMonths("360");
        acct.setMonthlyPayment("1,487.02");
        acct.setOriginationDate("02/15/2019");
        acct.setMaturityDate("02/15/2049");
        acct.setFirstPaymentDate("03/15/2019");
        acct.setNextPaymentDate("01/15/2026");
        acct.setStatusCode("ACT");
        acct.setDelinquencyDays("0");
        acct.setEscrowBalance("3,245.80");
        acct.setLtvPercent("82.5");
        acct.setPropertyAddress("742 Elm Street");
        acct.setPropertyCity("Springfield");
        acct.setPropertyState("IL");
        acct.setPropertyZip("62701");
        acct.setPropertyType("SFR");
        acct.setAppraisedValue("345,000");
        acct.setCreatedDate("02/01/2019");
        acct.setUpdatedDate("12/01/2025");
        return acct;
    }

    private LegacyPayment createValidPayment() {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber("PMT-2025120001");
        pmt.setLoanAccountNumber("LN-2019-00142");
        pmt.setPaymentDate("12/15/2025");
        pmt.setTotalAmount("1,000.00");
        pmt.setPrincipalAmount("400.00");
        pmt.setInterestAmount("500.00");
        pmt.setEscrowAmount("100.00");
        pmt.setLateFee("0.00");
        pmt.setTypeCode("REG");
        pmt.setStatusCode("PST");
        pmt.setReceivedDate("12/14/2025");
        pmt.setProcessedDate("12/15/2025");
        pmt.setCreatedDate("12/15/2025");
        pmt.setUpdatedDate("12/15/2025");
        return pmt;
    }
}
