package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Helper builders
    // =========================================================================

    private LegacyBorrower validBorrower() {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId("B-10001");
        b.setFirstName("James");
        b.setLastName("Mitchell");
        b.setMiddleInitial("R");
        b.setDateOfBirth("03/15/1978");
        b.setCreatedDate("01/15/2019");
        b.setUpdatedDate("11/03/2025");
        b.setCreditScore("745");
        b.setAnnualIncome("92,500");
        b.setStatusCode("ACT");
        b.setPhoneNumber("217-555-0142");
        b.setEmail("j.mitchell@email.com");
        b.setCity("Springfield");
        b.setStateCode("IL");
        b.setEmploymentStatus("EMPLOYED");
        return b;
    }

    private LegacyLoanAccount validLoanAccount() {
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber("LN-2019-00142");
        a.setBorrowerId("B-10001");
        a.setBorrowerFirstName("James");
        a.setBorrowerLastName("Mitchell");
        a.setBorrowerSsnLast4("1234");
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
        a.setLtvPercent("82.6");
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

    private LegacyPayment validPayment() {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber("PMT-2025120002");
        p.setLoanAccountNumber("LN-2020-00398");
        p.setPaymentDate("12/01/2025");
        p.setTotalAmount("2,924.18");
        p.setPrincipalAmount("1,842.56");
        p.setInterestAmount("815.50");
        p.setEscrowAmount("266.12");
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
    // ANO-001: SSN Last-4 vs Phone Last-4
    // =========================================================================

    @Nested
    @DisplayName("ANO-001: SSN Last-4 / Phone Last-4 Cross-Check")
    class SsnPhoneCrossCheck {

        @Test
        @DisplayName("Detects when SSN last-4 matches phone last-4")
        void detectsSsnMatchesPhone() {
            LegacyBorrower borrower = validBorrower();
            borrower.setPhoneNumber("217-555-0142");

            LegacyLoanAccount acct = validLoanAccount();
            acct.setBorrowerSsnLast4("0142"); // matches phone last 4

            ValidationResult result = validator.validateLoanAccount(acct, borrower);
            assertTrue(result.hasErrors(), "Should flag SSN matching phone");
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("BORR_SSN_LST4")));
        }

        @Test
        @DisplayName("Passes when SSN last-4 does not match phone last-4")
        void passesWhenSsnDiffers() {
            LegacyBorrower borrower = validBorrower();
            borrower.setPhoneNumber("217-555-0142");

            LegacyLoanAccount acct = validLoanAccount();
            acct.setBorrowerSsnLast4("9999");

            ValidationResult result = validator.validateLoanAccount(acct, borrower);
            assertFalse(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("BORR_SSN_LST4")));
        }
    }

    // =========================================================================
    // ANO-002: Payment Component Sum Mismatch
    // =========================================================================

    @Nested
    @DisplayName("ANO-002: Payment Component Sum Validation")
    class PaymentComponentSum {

        @Test
        @DisplayName("Detects escrow not included in total")
        void detectsEscrowMismatch() {
            LegacyPayment pmt = validPayment();
            pmt.setPaymentSequenceNumber("PMT-2025120001");
            pmt.setLoanAccountNumber("LN-2019-00142");
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasErrors(), "Should detect component sum mismatch");
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.message().contains("does not match total")));
        }

        @Test
        @DisplayName("Detects late fee not included in total")
        void detectsLateFeeMismatch() {
            LegacyPayment pmt = validPayment();
            pmt.setPaymentSequenceNumber("PMT-2025110003");
            pmt.setLoanAccountNumber("LN-2018-00089");
            pmt.setTotalAmount("1,077.05");
            pmt.setPrincipalAmount("295.82");
            pmt.setInterestAmount("781.23");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("47.50");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasErrors(), "Should detect late fee not in total");
        }

        @Test
        @DisplayName("Passes when components match total")
        void passesWhenComponentsMatch() {
            LegacyPayment pmt = validPayment();
            // 1842.56 + 815.50 + 266.12 + 0.00 = 2924.18
            ValidationResult result = validator.validatePayment(pmt);
            assertFalse(result.hasErrors(), "Should pass for matching components");
        }
    }

    // =========================================================================
    // ANO-003: Null/Blank Required Fields
    // =========================================================================

    @Nested
    @DisplayName("ANO-003: Null/Blank Required Field Validation")
    class NullRequiredFields {

        @Test
        @DisplayName("Detects null borrower first name")
        void detectsNullBorrowerName() {
            LegacyBorrower b = validBorrower();
            b.setFirstName(null);

            ValidationResult result = validator.validateBorrower(b);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("BORR_FST_NM")));
        }

        @Test
        @DisplayName("Detects blank loan original amount")
        void detectsBlankLoanAmount() {
            LegacyLoanAccount acct = validLoanAccount();
            acct.setOriginalAmount("");

            ValidationResult result = validator.validateLoanAccount(acct, validBorrower());
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("LN_ORIG_AMT")));
        }

        @Test
        @DisplayName("Detects null payment total amount")
        void detectsNullPaymentAmount() {
            LegacyPayment pmt = validPayment();
            pmt.setTotalAmount(null);

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("PMT_AMT")));
        }

        @Test
        @DisplayName("Detects null loan account number on payment")
        void detectsNullPaymentLoanRef() {
            LegacyPayment pmt = validPayment();
            pmt.setLoanAccountNumber(null);

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("LN_ACCT_NBR")));
        }
    }

    // =========================================================================
    // ANO-005: Denormalized Name Drift
    // =========================================================================

    @Nested
    @DisplayName("ANO-005: Denormalized Borrower Name Drift")
    class DenormalizedNameDrift {

        @Test
        @DisplayName("Detects first name mismatch between loan and borrower master")
        void detectsFirstNameDrift() {
            LegacyBorrower borrower = validBorrower();
            borrower.setFirstName("James");

            LegacyLoanAccount acct = validLoanAccount();
            acct.setBorrowerFirstName("Jim");
            acct.setBorrowerSsnLast4("9999"); // avoid SSN check triggering

            ValidationResult result = validator.validateLoanAccount(acct, borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("BORR_FST_NM")
                            && i.message().contains("differs")));
        }

        @Test
        @DisplayName("Detects last name mismatch")
        void detectsLastNameDrift() {
            LegacyBorrower borrower = validBorrower();
            borrower.setLastName("Mitchell");

            LegacyLoanAccount acct = validLoanAccount();
            acct.setBorrowerLastName("Mitchell-Jones");
            acct.setBorrowerSsnLast4("9999");

            ValidationResult result = validator.validateLoanAccount(acct, borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("BORR_LST_NM")));
        }
    }

    // =========================================================================
    // ANO-006: Date Format Validation
    // =========================================================================

    @Nested
    @DisplayName("ANO-006: Date Format Validation")
    class DateFormatValidation {

        @Test
        @DisplayName("Detects invalid date format YYYY-MM-DD")
        void detectsIsoDateFormat() {
            LegacyBorrower b = validBorrower();
            b.setDateOfBirth("1978-03-15");

            ValidationResult result = validator.validateBorrower(b);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("BORR_DOB_DT")
                            && i.message().contains("Invalid date")));
        }

        @Test
        @DisplayName("Detects impossible date 02/30/2025")
        void detectsImpossibleDate() {
            LegacyLoanAccount acct = validLoanAccount();
            acct.setOriginationDate("02/30/2025");
            acct.setBorrowerSsnLast4("9999");

            ValidationResult result = validator.validateLoanAccount(acct, null);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("LN_ORIG_DT")));
        }

        @Test
        @DisplayName("Accepts valid MM/DD/YYYY date")
        void acceptsValidDate() {
            LegacyBorrower b = validBorrower();
            b.setDateOfBirth("03/15/1978");

            ValidationResult result = validator.validateBorrower(b);
            assertFalse(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("BORR_DOB_DT")));
        }
    }

    // =========================================================================
    // ANO-007: LTV Rounding Inconsistency
    // =========================================================================

    @Nested
    @DisplayName("ANO-007: LTV Consistency Check")
    class LtvConsistency {

        @Test
        @DisplayName("Warns when stored LTV differs from computed")
        void warnsOnLtvMismatch() {
            LegacyLoanAccount acct = validLoanAccount();
            acct.setOriginalAmount("285,000");
            acct.setAppraisedValue("345,000");
            acct.setLtvPercent("90.0"); // actual ~82.6%
            acct.setBorrowerSsnLast4("9999");

            ValidationResult result = validator.validateLoanAccount(acct, null);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("LN_LTV_PCT")));
        }

        @Test
        @DisplayName("Passes when LTV is within tolerance")
        void passesWhenLtvClose() {
            LegacyLoanAccount acct = validLoanAccount();
            acct.setOriginalAmount("285,000");
            acct.setAppraisedValue("345,000");
            acct.setLtvPercent("82.6"); // matches computed
            acct.setBorrowerSsnLast4("9999");

            ValidationResult result = validator.validateLoanAccount(acct, null);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("LN_LTV_PCT")));
        }
    }

    // =========================================================================
    // ANO-008: Numeric String Parsing Fragility
    // =========================================================================

    @Nested
    @DisplayName("ANO-008: Numeric String Parsing")
    class NumericParsing {

        @Test
        @DisplayName("Detects currency symbol in amount field")
        void detectsCurrencySymbol() {
            LegacyLoanAccount acct = validLoanAccount();
            acct.setOriginalAmount("$285,000");
            acct.setBorrowerSsnLast4("9999");

            // Validator should accept (strips $), no error
            ValidationResult result = validator.validateLoanAccount(acct, null);
            assertFalse(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("LN_ORIG_AMT")));
        }

        @Test
        @DisplayName("Detects non-numeric text in amount field")
        void detectsNonNumericAmount() {
            LegacyLoanAccount acct = validLoanAccount();
            acct.setOriginalAmount("N/A");
            acct.setBorrowerSsnLast4("9999");

            ValidationResult result = validator.validateLoanAccount(acct, null);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("LN_ORIG_AMT")
                            && i.message().contains("Cannot parse")));
        }

        @Test
        @DisplayName("Detects non-numeric credit score")
        void detectsNonNumericCreditScore() {
            LegacyBorrower b = validBorrower();
            b.setCreditScore("HIGH");

            ValidationResult result = validator.validateBorrower(b);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(i -> i.field().equals("BORR_CRDT_SCR")));
        }

        @Test
        @DisplayName("Warns on out-of-range credit score")
        void warnsOutOfRangeCreditScore() {
            LegacyBorrower b = validBorrower();
            b.setCreditScore("200");

            ValidationResult result = validator.validateBorrower(b);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("BORR_CRDT_SCR")
                            && i.message().contains("outside expected range")));
        }
    }

    // =========================================================================
    // ANO-010: Unknown Status Codes
    // =========================================================================

    @Nested
    @DisplayName("ANO-010: Status Code Validation")
    class StatusCodeValidation {

        @Test
        @DisplayName("Warns on unknown loan status code")
        void warnsUnknownLoanStatus() {
            LegacyLoanAccount acct = validLoanAccount();
            acct.setStatusCode("XYZ");
            acct.setBorrowerSsnLast4("9999");

            ValidationResult result = validator.validateLoanAccount(acct, null);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("LN_STAT_CD")));
        }

        @Test
        @DisplayName("Warns on unknown payment status code")
        void warnsUnknownPaymentStatus() {
            LegacyPayment pmt = validPayment();
            pmt.setStatusCode("ABC");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("PMT_STAT_CD")));
        }

        @Test
        @DisplayName("Warns on unknown payment type code")
        void warnsUnknownPaymentType() {
            LegacyPayment pmt = validPayment();
            pmt.setTypeCode("ZZZ");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("PMT_TYP_CD")));
        }

        @Test
        @DisplayName("Warns on unknown borrower status code")
        void warnsUnknownBorrowerStatus() {
            LegacyBorrower b = validBorrower();
            b.setStatusCode("DEL");

            ValidationResult result = validator.validateBorrower(b);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("BORR_STAT_CD")));
        }

        @Test
        @DisplayName("Accepts valid status codes without warnings")
        void acceptsValidStatusCodes() {
            LegacyPayment pmt = validPayment();
            pmt.setStatusCode("PST");
            pmt.setTypeCode("REG");

            ValidationResult result = validator.validatePayment(pmt);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(i -> i.field().equals("PMT_STAT_CD")
                            || i.field().equals("PMT_TYP_CD")));
        }
    }

    // =========================================================================
    // Clean record validation
    // =========================================================================

    @Nested
    @DisplayName("Clean Records Pass Validation")
    class CleanRecords {

        @Test
        @DisplayName("Valid borrower passes without issues")
        void validBorrowerPasses() {
            ValidationResult result = validator.validateBorrower(validBorrower());
            assertFalse(result.hasErrors());
        }

        @Test
        @DisplayName("Valid loan account passes without errors")
        void validLoanPasses() {
            LegacyLoanAccount acct = validLoanAccount();
            acct.setBorrowerSsnLast4("9999"); // non-matching
            ValidationResult result = validator.validateLoanAccount(acct, null);
            assertFalse(result.hasErrors());
        }

        @Test
        @DisplayName("Valid payment passes without errors")
        void validPaymentPasses() {
            ValidationResult result = validator.validatePayment(validPayment());
            assertFalse(result.hasErrors());
        }
    }
}
