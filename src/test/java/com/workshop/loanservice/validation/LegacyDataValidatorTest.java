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

/**
 * Tests for LegacyDataValidator covering each anomaly type
 * documented in docs/DATA_ANOMALY_REPORT.md.
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Helper factory methods for building test entities
    // =========================================================================

    /** Creates a valid borrower with all fields populated. */
    private LegacyBorrower validBorrower() {
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

    /** Creates a valid loan account with all fields populated. */
    private LegacyLoanAccount validLoanAccount() {
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber("LN-2019-00142");
        a.setBorrowerId("B-10001");
        a.setBorrowerFirstName("James");
        a.setBorrowerLastName("Mitchell");
        a.setBorrowerSsnLast4("9999");
        a.setProductCode("FXD30");
        a.setOriginalAmount("285,000");
        a.setCurrentBalance("271,432.56");
        a.setInterestRate("4.750");
        a.setTermMonths("360");
        a.setMonthlyPayment("1,487.02");
        a.setOriginationDate("02/15/2019");
        a.setMaturityDate("02/15/2049");
        a.setFirstPaymentDate("03/15/2019");
        a.setNextPaymentDate("01/15/2026");
        a.setStatusCode("ACT");
        a.setDelinquencyDays("0");
        a.setEscrowBalance("3,245.80");
        a.setLtvPercent("82.5");
        a.setPropertyAddress("742 Elm Street");
        a.setPropertyCity("Springfield");
        a.setPropertyState("IL");
        a.setPropertyZip("62701");
        a.setPropertyType("SFR");
        a.setAppraisedValue("345,000");
        a.setCreatedDate("02/01/2019");
        a.setUpdatedDate("12/01/2025");
        return a;
    }

    /** Creates a valid payment with reconciling amounts. */
    private LegacyPayment validPayment() {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber("PMT-TEST-001");
        p.setLoanAccountNumber("LN-2019-00142");
        p.setPaymentDate("12/01/2025");
        p.setTotalAmount("1,000.00");
        p.setPrincipalAmount("400.00");
        p.setInterestAmount("500.00");
        p.setEscrowAmount("100.00");
        p.setLateFee("0.00");
        p.setTypeCode("REG");
        p.setStatusCode("PST");
        p.setReceivedDate("11/30/2025");
        p.setProcessedDate("12/01/2025");
        p.setCreatedDate("12/01/2025");
        p.setUpdatedDate("12/01/2025");
        return p;
    }

    // =========================================================================
    // ANM-001: SSN Last-4 = Phone Last-4 (PII Corruption)
    // =========================================================================

    @Nested
    @DisplayName("ANM-001: SSN-Phone Cross-Reference")
    class SsnPhoneCrossReference {

        @Test
        @DisplayName("Detects SSN last-4 matching phone last-4")
        void detectsSsnMatchingPhone() {
            LegacyLoanAccount account = validLoanAccount();
            // Set SSN last-4 to match phone last-4 digits
            account.setBorrowerSsnLast4("0142");

            LegacyBorrower borrower = validBorrower();
            borrower.setPhoneNumber("217-555-0142");

            List<ValidationResult> results = validator.validateLoanAccount(account, borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("BORR_SSN_LST4")
                                    && r.message().contains("PII data corruption")),
                    "Should detect SSN-phone match as PII corruption");
        }

        @Test
        @DisplayName("No error when SSN last-4 differs from phone last-4")
        void noErrorWhenSsnDiffersFromPhone() {
            LegacyLoanAccount account = validLoanAccount();
            account.setBorrowerSsnLast4("9999");

            LegacyBorrower borrower = validBorrower();
            borrower.setPhoneNumber("217-555-0142");

            List<ValidationResult> results = validator.validateLoanAccount(account, borrower);

            assertFalse(results.stream().anyMatch(r ->
                            r.column().equals("BORR_SSN_LST4")
                                    && r.message().contains("PII data corruption")),
                    "Should not flag when SSN and phone differ");
        }
    }

    // =========================================================================
    // ANM-002: Payment Component Reconciliation
    // =========================================================================

    @Nested
    @DisplayName("ANM-002: Payment Reconciliation")
    class PaymentReconciliation {

        @Test
        @DisplayName("Detects payment components not summing to total")
        void detectsReconciliationFailure() {
            LegacyPayment payment = validPayment();
            // Total = 1,487.02 but components sum to 1,887.02 (real anomaly from data)
            payment.setTotalAmount("1,487.02");
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");

            List<ValidationResult> results = validator.validatePayment(payment);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.message().contains("do not reconcile")),
                    "Should detect payment reconciliation failure");
        }

        @Test
        @DisplayName("No error when payment components reconcile correctly")
        void noErrorWhenReconciled() {
            LegacyPayment payment = validPayment();
            // Components sum exactly to total: 400 + 500 + 100 + 0 = 1000
            payment.setTotalAmount("1,000.00");
            payment.setPrincipalAmount("400.00");
            payment.setInterestAmount("500.00");
            payment.setEscrowAmount("100.00");
            payment.setLateFee("0.00");

            List<ValidationResult> results = validator.validatePayment(payment);

            assertFalse(results.stream().anyMatch(r ->
                            r.message().contains("do not reconcile")),
                    "Should not flag correctly reconciled payment");
        }
    }

    // =========================================================================
    // ANM-003: Numeric Parsing Failures (VARCHAR fields)
    // =========================================================================

    @Nested
    @DisplayName("ANM-003: Numeric/Date Format Validation")
    class NumericFormatValidation {

        @Test
        @DisplayName("Detects non-numeric credit score")
        void detectsNonNumericCreditScore() {
            LegacyBorrower borrower = validBorrower();
            borrower.setCreditScore("N/A");

            List<ValidationResult> results = validator.validateBorrower(borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("BORR_CRDT_SCR")
                                    && r.message().contains("Non-numeric")),
                    "Should detect non-numeric credit score");
        }

        @Test
        @DisplayName("Detects credit score outside valid range")
        void detectsCreditScoreOutOfRange() {
            LegacyBorrower borrower = validBorrower();
            borrower.setCreditScore("100");

            List<ValidationResult> results = validator.validateBorrower(borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("BORR_CRDT_SCR")
                                    && r.message().contains("outside valid range")),
                    "Should warn about credit score out of range");
        }

        @Test
        @DisplayName("Detects non-numeric annual income")
        void detectsNonNumericIncome() {
            LegacyBorrower borrower = validBorrower();
            borrower.setAnnualIncome("$92,500");

            List<ValidationResult> results = validator.validateBorrower(borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("BORR_ANN_INCM")
                                    && r.message().contains("Non-numeric")),
                    "Should detect non-numeric income with $ sign");
        }

        @Test
        @DisplayName("Detects non-numeric loan amount")
        void detectsNonNumericLoanAmount() {
            LegacyLoanAccount account = validLoanAccount();
            account.setOriginalAmount("UNKNOWN");

            List<ValidationResult> results = validator.validateLoanAccount(account, validBorrower());

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("LN_ORIG_AMT")),
                    "Should detect non-numeric loan amount");
        }

        @Test
        @DisplayName("Detects non-numeric interest rate")
        void detectsNonNumericInterestRate() {
            LegacyLoanAccount account = validLoanAccount();
            account.setInterestRate("VARIABLE");

            List<ValidationResult> results = validator.validateLoanAccount(account, validBorrower());

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("LN_INT_RT")),
                    "Should detect non-numeric interest rate");
        }

        @Test
        @DisplayName("Detects invalid date format")
        void detectsInvalidDateFormat() {
            LegacyBorrower borrower = validBorrower();
            borrower.setDateOfBirth("1978-03-15");

            List<ValidationResult> results = validator.validateBorrower(borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("BORR_DOB_DT")
                                    && r.message().contains("Invalid date format")),
                    "Should detect ISO date where MM/DD/YYYY is expected");
        }

        @Test
        @DisplayName("Detects non-numeric payment amount")
        void detectsNonNumericPaymentAmount() {
            LegacyPayment payment = validPayment();
            payment.setTotalAmount("PENDING");

            List<ValidationResult> results = validator.validatePayment(payment);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("PMT_AMT")),
                    "Should detect non-numeric payment total");
        }
    }

    // =========================================================================
    // ANM-004: Referential Integrity (Orphaned Records)
    // =========================================================================

    @Nested
    @DisplayName("ANM-004: Referential Integrity")
    class ReferentialIntegrity {

        @Test
        @DisplayName("Detects orphaned loan account (missing borrower)")
        void detectsOrphanedLoan() {
            LegacyLoanAccount account = validLoanAccount();
            account.setBorrowerId("B-99999");

            // Pass null borrower to simulate not found
            List<ValidationResult> results = validator.validateLoanAccount(account, null);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("BORR_ID")
                                    && r.message().contains("orphaned")),
                    "Should detect orphaned loan record");
        }

        @Test
        @DisplayName("Detects orphaned payment (missing loan account number)")
        void detectsOrphanedPayment() {
            LegacyPayment payment = validPayment();
            payment.setLoanAccountNumber(null);

            List<ValidationResult> results = validator.validatePayment(payment);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("LN_ACCT_NBR")
                                    && r.message().contains("orphaned")),
                    "Should detect orphaned payment record");
        }
    }

    // =========================================================================
    // ANM-005: Delinquency Days > 0 With Active Status
    // =========================================================================

    @Nested
    @DisplayName("ANM-005: Delinquency/Status Consistency")
    class DelinquencyStatusConsistency {

        @Test
        @DisplayName("Warns when delinquency > 0 but status is ACT")
        void warnsDelinquentButActive() {
            LegacyLoanAccount account = validLoanAccount();
            account.setDelinquencyDays("15");
            account.setStatusCode("ACT");

            List<ValidationResult> results = validator.validateLoanAccount(account, validBorrower());

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("LN_DLQ_DAYS")
                                    && r.message().contains("delinquent")),
                    "Should warn about delinquent loan with Active status");
        }

        @Test
        @DisplayName("No warning when delinquency is 0 with ACT status")
        void noWarningWhenNotDelinquent() {
            LegacyLoanAccount account = validLoanAccount();
            account.setDelinquencyDays("0");
            account.setStatusCode("ACT");

            List<ValidationResult> results = validator.validateLoanAccount(account, validBorrower());

            assertFalse(results.stream().anyMatch(r ->
                            r.column().equals("LN_DLQ_DAYS")
                                    && r.message().contains("delinquent")),
                    "Should not warn when delinquency is 0");
        }
    }

    // =========================================================================
    // ANM-006: Null Required Fields
    // =========================================================================

    @Nested
    @DisplayName("ANM-006: Null Required Fields")
    class NullRequiredFields {

        @Test
        @DisplayName("Detects null first name")
        void detectsNullFirstName() {
            LegacyBorrower borrower = validBorrower();
            borrower.setFirstName(null);

            List<ValidationResult> results = validator.validateBorrower(borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("BORR_FST_NM")),
                    "Should detect null first name");
        }

        @Test
        @DisplayName("Detects null last name")
        void detectsNullLastName() {
            LegacyBorrower borrower = validBorrower();
            borrower.setLastName(null);

            List<ValidationResult> results = validator.validateBorrower(borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("BORR_LST_NM")),
                    "Should detect null last name");
        }

        @Test
        @DisplayName("Detects null SSN")
        void detectsNullSsn() {
            LegacyBorrower borrower = validBorrower();
            borrower.setSsnEncrypted(null);

            List<ValidationResult> results = validator.validateBorrower(borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR
                                    && r.column().equals("BORR_SSN_ENCR")),
                    "Should detect null SSN");
        }
    }

    // =========================================================================
    // ANM-007: Denormalized Data Drift
    // =========================================================================

    @Nested
    @DisplayName("ANM-007: Denormalized Data Drift")
    class DenormalizedDataDrift {

        @Test
        @DisplayName("Warns when denormalized first name differs from master")
        void warnsOnFirstNameDrift() {
            LegacyLoanAccount account = validLoanAccount();
            account.setBorrowerFirstName("Jim");

            LegacyBorrower borrower = validBorrower();
            borrower.setFirstName("James");

            List<ValidationResult> results = validator.validateLoanAccount(account, borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("BORR_FST_NM")
                                    && r.message().contains("differs from master")),
                    "Should warn about first name drift");
        }

        @Test
        @DisplayName("Warns when denormalized last name differs from master")
        void warnsOnLastNameDrift() {
            LegacyLoanAccount account = validLoanAccount();
            account.setBorrowerLastName("Smith");

            LegacyBorrower borrower = validBorrower();
            borrower.setLastName("Mitchell");

            List<ValidationResult> results = validator.validateLoanAccount(account, borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("BORR_LST_NM")
                                    && r.message().contains("differs from master")),
                    "Should warn about last name drift");
        }
    }

    // =========================================================================
    // ANM-009: Late Payment Without Late Fee
    // =========================================================================

    @Nested
    @DisplayName("ANM-009: Late Payment Fee Consistency")
    class LatePaymentFeeConsistency {

        @Test
        @DisplayName("Warns when payment received > 15 days late with no late fee")
        void warnsLatePmtNoFee() {
            LegacyPayment payment = validPayment();
            payment.setPaymentDate("11/01/2025");
            payment.setReceivedDate("11/20/2025");
            payment.setLateFee("0.00");

            List<ValidationResult> results = validator.validatePayment(payment);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("PMT_LATE_FEE")
                                    && r.message().contains("days late")),
                    "Should warn about late payment with no fee");
        }

        @Test
        @DisplayName("No warning when payment received within grace period")
        void noWarningWithinGracePeriod() {
            LegacyPayment payment = validPayment();
            payment.setPaymentDate("12/01/2025");
            payment.setReceivedDate("12/05/2025");
            payment.setLateFee("0.00");

            List<ValidationResult> results = validator.validatePayment(payment);

            assertFalse(results.stream().anyMatch(r ->
                            r.column().equals("PMT_LATE_FEE")
                                    && r.message().contains("days late")),
                    "Should not warn about payment within grace period");
        }
    }

    // =========================================================================
    // ANM-010: Invalid Status Codes
    // =========================================================================

    @Nested
    @DisplayName("ANM-010: Status Code Validation")
    class StatusCodeValidation {

        @Test
        @DisplayName("Warns on unknown borrower status code")
        void warnsUnknownBorrowerStatus() {
            LegacyBorrower borrower = validBorrower();
            borrower.setStatusCode("XXX");

            List<ValidationResult> results = validator.validateBorrower(borrower);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("BORR_STAT_CD")
                                    && r.message().contains("Unknown status")),
                    "Should warn about unknown borrower status");
        }

        @Test
        @DisplayName("Warns on unknown loan status code")
        void warnsUnknownLoanStatus() {
            LegacyLoanAccount account = validLoanAccount();
            account.setStatusCode("ZZZ");

            List<ValidationResult> results = validator.validateLoanAccount(account, validBorrower());

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("LN_STAT_CD")
                                    && r.message().contains("Unknown loan status")),
                    "Should warn about unknown loan status");
        }

        @Test
        @DisplayName("Warns on unknown payment type code")
        void warnsUnknownPaymentType() {
            LegacyPayment payment = validPayment();
            payment.setTypeCode("BAD");

            List<ValidationResult> results = validator.validatePayment(payment);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("PMT_TYP_CD")
                                    && r.message().contains("Unknown payment type")),
                    "Should warn about unknown payment type");
        }

        @Test
        @DisplayName("Warns on unknown payment status code")
        void warnsUnknownPaymentStatus() {
            LegacyPayment payment = validPayment();
            payment.setStatusCode("BAD");

            List<ValidationResult> results = validator.validatePayment(payment);

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("PMT_STAT_CD")
                                    && r.message().contains("Unknown payment status")),
                    "Should warn about unknown payment status");
        }

        @Test
        @DisplayName("Warns on unknown property type code")
        void warnsUnknownPropertyType() {
            LegacyLoanAccount account = validLoanAccount();
            account.setPropertyType("XYZ");

            List<ValidationResult> results = validator.validateLoanAccount(account, validBorrower());

            assertTrue(results.stream().anyMatch(r ->
                            r.severity() == ValidationResult.Severity.WARNING
                                    && r.column().equals("PROP_TYP_CD")),
                    "Should warn about unknown property type");
        }
    }

    // =========================================================================
    // Valid records should produce no errors
    // =========================================================================

    @Nested
    @DisplayName("Valid Records — No Errors")
    class ValidRecords {

        @Test
        @DisplayName("Valid borrower produces no errors")
        void validBorrowerNoErrors() {
            List<ValidationResult> results = validator.validateBorrower(validBorrower());

            assertTrue(results.stream().noneMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR),
                    "Valid borrower should have no errors");
        }

        @Test
        @DisplayName("Valid loan account produces no errors")
        void validLoanNoErrors() {
            List<ValidationResult> results = validator.validateLoanAccount(validLoanAccount(), validBorrower());

            assertTrue(results.stream().noneMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR),
                    "Valid loan account should have no errors");
        }

        @Test
        @DisplayName("Valid payment produces no errors")
        void validPaymentNoErrors() {
            List<ValidationResult> results = validator.validatePayment(validPayment());

            assertTrue(results.stream().noneMatch(r ->
                            r.severity() == ValidationResult.Severity.ERROR),
                    "Valid payment should have no errors");
        }
    }

    // =========================================================================
    // Helper method unit tests
    // =========================================================================

    @Nested
    @DisplayName("Helper Methods")
    class HelperMethods {

        @Test
        @DisplayName("extractLast4Digits handles phone with dashes")
        void extractLast4Dashes() {
            assertEquals("0142", validator.extractLast4Digits("217-555-0142"));
        }

        @Test
        @DisplayName("extractLast4Digits handles phone with spaces")
        void extractLast4Spaces() {
            assertEquals("0142", validator.extractLast4Digits("217 555 0142"));
        }

        @Test
        @DisplayName("extractLast4Digits returns null for short input")
        void extractLast4Short() {
            assertNull(validator.extractLast4Digits("12"));
        }

        @Test
        @DisplayName("isValidAmount accepts comma-separated amounts")
        void validAmountWithCommas() {
            assertTrue(validator.isValidAmount("1,487.02"));
            assertTrue(validator.isValidAmount("285,000"));
        }

        @Test
        @DisplayName("isValidAmount rejects non-numeric strings")
        void invalidAmount() {
            assertFalse(validator.isValidAmount("$100"));
            assertFalse(validator.isValidAmount("N/A"));
            assertFalse(validator.isValidAmount(""));
        }

        @Test
        @DisplayName("isValidDate accepts MM/dd/yyyy format")
        void validDate() {
            assertTrue(validator.isValidDate("03/15/1978"));
            assertTrue(validator.isValidDate("12/31/2025"));
        }

        @Test
        @DisplayName("isValidDate rejects ISO format and garbage")
        void invalidDate() {
            assertFalse(validator.isValidDate("1978-03-15"));
            assertFalse(validator.isValidDate("March 15, 1978"));
            assertFalse(validator.isValidDate(""));
        }
    }
}
