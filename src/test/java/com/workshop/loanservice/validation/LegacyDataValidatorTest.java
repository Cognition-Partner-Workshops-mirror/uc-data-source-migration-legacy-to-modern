package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Tests for LegacyDataValidator that verify detection of each known
 * CDW data quality anomaly type (see docs/DATA_ANOMALY_REPORT.md).
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Helper methods to create valid test entities
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
        LegacyLoanAccount loan = new LegacyLoanAccount();
        loan.setLoanAccountNumber("LN-2019-00142");
        loan.setBorrowerId("B-10001");
        loan.setBorrowerFirstName("James");
        loan.setBorrowerLastName("Mitchell");
        loan.setBorrowerSsnLast4("0142");
        loan.setProductCode("FXD30");
        loan.setOriginalAmount("285,000");
        loan.setCurrentBalance("271,432.56");
        loan.setInterestRate("4.750");
        loan.setTermMonths("360");
        loan.setMonthlyPayment("1,487.02");
        loan.setOriginationDate("02/15/2019");
        loan.setMaturityDate("02/15/2049");
        loan.setFirstPaymentDate("03/15/2019");
        loan.setNextPaymentDate("01/15/2026");
        loan.setStatusCode("ACT");
        loan.setDelinquencyDays("0");
        loan.setEscrowBalance("3,245.80");
        loan.setLtvPercent("82.5");
        loan.setPropertyAddress("742 Elm Street");
        loan.setPropertyCity("Springfield");
        loan.setPropertyState("IL");
        loan.setPropertyZip("62701");
        loan.setPropertyType("SFR");
        loan.setAppraisedValue("345,000");
        loan.setCreatedDate("02/01/2019");
        loan.setUpdatedDate("12/01/2025");
        return loan;
    }

    private LegacyPayment createValidPayment() {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber("PMT-2025120002");
        pmt.setLoanAccountNumber("LN-2020-00398");
        pmt.setPaymentDate("12/01/2025");
        // Components that correctly sum to total: 1842.56 + 815.50 + 266.12 + 0.00 = 2924.18
        pmt.setTotalAmount("2,924.18");
        pmt.setPrincipalAmount("1,842.56");
        pmt.setInterestAmount("815.50");
        pmt.setEscrowAmount("266.12");
        pmt.setLateFee("0.00");
        pmt.setTypeCode("REG");
        pmt.setStatusCode("PST");
        pmt.setReceivedDate("11/30/2025");
        pmt.setProcessedDate("12/01/2025");
        pmt.setCreatedDate("12/01/2025");
        pmt.setUpdatedDate("12/01/2025");
        return pmt;
    }

    // =========================================================================
    // ANO-001: Payment components don't sum to total
    // =========================================================================

    @Nested
    @DisplayName("ANO-001: Payment Component Sum Validation")
    class PaymentComponentSumTests {

        @Test
        @DisplayName("Detects when payment components exceed total by $400 (actual CDW anomaly)")
        void detectsPaymentComponentMismatch() {
            LegacyPayment pmt = createValidPayment();
            // Simulate the actual anomaly from LN-2019-00142:
            // total=1487.02, but principal(456.78)+interest(1074.69)+escrow(355.55)=1887.02
            pmt.setPaymentSequenceNumber("PMT-2025120001");
            pmt.setLoanAccountNumber("LN-2019-00142");
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");

            DataQualityResult result = validator.validatePayment(pmt);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("paymentComponents")
                            && issue.message().contains("does not match total")
                            && issue.message().contains("400.00"));
        }

        @Test
        @DisplayName("Passes when payment components correctly sum to total")
        void passesWhenComponentsSumCorrectly() {
            LegacyPayment pmt = createValidPayment();

            DataQualityResult result = validator.validatePayment(pmt);

            assertThat(result.hasErrors()).isFalse();
        }

        @Test
        @DisplayName("Detects when late fee is not included in total (ANO-009 variant)")
        void detectsLateFeeNotIncluded() {
            LegacyPayment pmt = createValidPayment();
            // Simulate: total = principal + interest (excludes late fee)
            pmt.setTotalAmount("1,077.05");
            pmt.setPrincipalAmount("295.82");
            pmt.setInterestAmount("781.23");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("47.50");
            // Sum: 295.82 + 781.23 + 0 + 47.50 = 1124.55 ≠ 1077.05

            DataQualityResult result = validator.validatePayment(pmt);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("paymentComponents")
                            && issue.message().contains("does not match total"));
        }
    }

    // =========================================================================
    // ANO-003: Delinquent loan marked Active
    // =========================================================================

    @Nested
    @DisplayName("ANO-003: Delinquency/Status Consistency")
    class DelinquencyStatusTests {

        @Test
        @DisplayName("Detects loan with delinquency days > 0 but status ACT")
        void detectsDelinquentLoanMarkedActive() {
            LegacyLoanAccount loan = createValidLoanAccount();
            // Simulate the actual anomaly: LN-2018-00089 has 15 days delinquent but ACT
            loan.setLoanAccountNumber("LN-2018-00089");
            loan.setDelinquencyDays("15");
            loan.setStatusCode("ACT");

            DataQualityResult result = validator.validateLoanAccount(loan);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("statusCode/delinquencyDays")
                            && issue.message().contains("15 delinquency days")
                            && issue.message().contains("ACT"));
        }

        @Test
        @DisplayName("Passes when delinquency is 0 and status is ACT")
        void passesWhenNonDelinquentAndActive() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setDelinquencyDays("0");
            loan.setStatusCode("ACT");

            DataQualityResult result = validator.validateLoanAccount(loan);

            assertThat(result.hasErrors()).isFalse();
        }

        @Test
        @DisplayName("Passes when delinquent and status is DFT")
        void passesWhenDelinquentAndDefaultStatus() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setDelinquencyDays("60");
            loan.setStatusCode("DFT");

            DataQualityResult result = validator.validateLoanAccount(loan);

            // Should not flag status/delinquency mismatch (DFT is acceptable for delinquent)
            assertThat(result.getIssues()).noneMatch(issue ->
                    issue.field().equals("statusCode/delinquencyDays"));
        }
    }

    // =========================================================================
    // ANO-005: Numeric fields as VARCHAR — parsing failures
    // =========================================================================

    @Nested
    @DisplayName("ANO-005: Numeric Field Parsing Validation")
    class NumericParsingTests {

        @Test
        @DisplayName("Detects non-numeric credit score")
        void detectsInvalidCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("N/A");

            DataQualityResult result = validator.validateBorrower(borrower);

            assertThat(result.hasIssues()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("creditScore")
                            && issue.message().contains("Cannot parse"));
        }

        @Test
        @DisplayName("Detects credit score outside valid range")
        void detectsCreditScoreOutOfRange() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("999");

            DataQualityResult result = validator.validateBorrower(borrower);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("creditScore")
                            && issue.message().contains("outside valid range"));
        }

        @Test
        @DisplayName("Detects unparseable amount with dollar sign")
        void detectsAmountWithDollarSign() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setOriginalAmount("$285,000");

            DataQualityResult result = validator.validateLoanAccount(loan);

            assertThat(result.hasIssues()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("originalAmount")
                            && issue.message().contains("Cannot parse amount"));
        }

        @Test
        @DisplayName("Detects unparseable interest rate with percent sign")
        void detectsInterestRateWithPercent() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setInterestRate("5.25%");

            DataQualityResult result = validator.validateLoanAccount(loan);

            assertThat(result.hasIssues()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("interestRate")
                            && issue.message().contains("Cannot parse"));
        }

        @Test
        @DisplayName("Passes with valid numeric strings")
        void passesWithValidNumericStrings() {
            LegacyBorrower borrower = createValidBorrower();

            DataQualityResult result = validator.validateBorrower(borrower);

            // Should have no parsing warnings for numeric fields
            assertThat(result.getIssues()).noneMatch(issue ->
                    issue.message().contains("Cannot parse"));
        }
    }

    // =========================================================================
    // ANO-006: Date strings not validated
    // =========================================================================

    @Nested
    @DisplayName("ANO-006: Date Format Validation")
    class DateFormatTests {

        @Test
        @DisplayName("Detects invalid date (February 30)")
        void detectsInvalidDateFeb30() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("02/30/1978");

            DataQualityResult result = validator.validateBorrower(borrower);

            assertThat(result.hasIssues()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("dateOfBirth")
                            && issue.message().contains("Invalid date format"));
        }

        @Test
        @DisplayName("Detects invalid month (13)")
        void detectsInvalidMonth() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setOriginationDate("13/01/2020");

            DataQualityResult result = validator.validateLoanAccount(loan);

            assertThat(result.hasIssues()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("originationDate")
                            && issue.message().contains("Invalid date format"));
        }

        @Test
        @DisplayName("Detects wrong date format (YYYY-MM-DD instead of MM/DD/YYYY)")
        void detectsWrongDateFormat() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("2025-12-01");

            DataQualityResult result = validator.validatePayment(pmt);

            assertThat(result.hasIssues()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("paymentDate")
                            && issue.message().contains("Invalid date format"));
        }

        @Test
        @DisplayName("Passes with valid MM/DD/YYYY date")
        void passesWithValidDate() {
            LegacyBorrower borrower = createValidBorrower();
            // Already has valid date "03/15/1978"

            DataQualityResult result = validator.validateBorrower(borrower);

            assertThat(result.getIssues()).noneMatch(issue ->
                    issue.field().equals("dateOfBirth"));
        }
    }

    // =========================================================================
    // ANO-008: No NOT NULL constraints — null required fields
    // =========================================================================

    @Nested
    @DisplayName("ANO-008: Required Field Null Validation")
    class NullRequiredFieldTests {

        @Test
        @DisplayName("Detects null first name on borrower")
        void detectsNullFirstName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);

            DataQualityResult result = validator.validateBorrower(borrower);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("firstName")
                            && issue.message().contains("null or blank"));
        }

        @Test
        @DisplayName("Detects null last name on borrower")
        void detectsNullLastName() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName(null);

            DataQualityResult result = validator.validateBorrower(borrower);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("lastName")
                            && issue.message().contains("null or blank"));
        }

        @Test
        @DisplayName("Detects null borrower ID on loan account")
        void detectsNullBorrowerIdOnLoan() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setBorrowerId(null);

            DataQualityResult result = validator.validateLoanAccount(loan);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("borrowerId")
                            && issue.message().contains("null or blank"));
        }

        @Test
        @DisplayName("Detects null loan account number on payment")
        void detectsNullLoanAccountOnPayment() {
            LegacyPayment pmt = createValidPayment();
            pmt.setLoanAccountNumber(null);

            DataQualityResult result = validator.validatePayment(pmt);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("loanAccountNumber")
                            && issue.message().contains("null or blank"));
        }

        @Test
        @DisplayName("Detects blank (empty string) required field")
        void detectsBlankRequiredField() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName("   ");

            DataQualityResult result = validator.validateBorrower(borrower);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("firstName")
                            && issue.message().contains("null or blank"));
        }
    }

    // =========================================================================
    // ANO-004: Referential integrity / invalid status codes
    // =========================================================================

    @Nested
    @DisplayName("ANO-004: Invalid Status Code Detection")
    class InvalidStatusCodeTests {

        @Test
        @DisplayName("Warns on unknown borrower status code")
        void warnsOnUnknownBorrowerStatus() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setStatusCode("XYZ");

            DataQualityResult result = validator.validateBorrower(borrower);

            assertThat(result.hasIssues()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("statusCode")
                            && issue.message().contains("Unknown borrower status code: 'XYZ'"));
        }

        @Test
        @DisplayName("Warns on unknown payment type code")
        void warnsOnUnknownPaymentType() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTypeCode("BAD");

            DataQualityResult result = validator.validatePayment(pmt);

            assertThat(result.hasIssues()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("typeCode")
                            && issue.message().contains("Unknown payment type code: 'BAD'"));
        }

        @Test
        @DisplayName("Warns on unknown payment status code")
        void warnsOnUnknownPaymentStatus() {
            LegacyPayment pmt = createValidPayment();
            pmt.setStatusCode("???");

            DataQualityResult result = validator.validatePayment(pmt);

            assertThat(result.hasIssues()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("statusCode")
                            && issue.message().contains("Unknown payment status code: '???'"));
        }
    }

    // =========================================================================
    // Integration test: validate actual seed data records
    // =========================================================================

    @Nested
    @DisplayName("Seed Data Validation (actual CDW records)")
    class SeedDataTests {

        @Test
        @DisplayName("Valid borrower (B-10001 James Mitchell) passes validation")
        void validBorrowerPasses() {
            LegacyBorrower borrower = createValidBorrower();

            DataQualityResult result = validator.validateBorrower(borrower);

            assertThat(result.hasErrors()).isFalse();
        }

        @Test
        @DisplayName("Delinquent loan (LN-2018-00089) triggers status inconsistency error")
        void delinquentLoanTriggersError() {
            LegacyLoanAccount loan = createValidLoanAccount();
            loan.setLoanAccountNumber("LN-2018-00089");
            loan.setBorrowerId("B-10003");
            loan.setDelinquencyDays("15");
            loan.setStatusCode("ACT");

            DataQualityResult result = validator.validateLoanAccount(loan);

            assertThat(result.hasErrors()).isTrue();
        }

        @Test
        @DisplayName("Mismatched payment (PMT-2025120001) triggers component sum error")
        void mismatchedPaymentTriggersError() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-2025120001");
            pmt.setLoanAccountNumber("LN-2019-00142");
            pmt.setPaymentDate("12/15/2025");
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("PST");
            pmt.setReceivedDate("12/14/2025");
            pmt.setProcessedDate("12/15/2025");
            pmt.setCreatedDate("12/15/2025");
            pmt.setUpdatedDate("12/15/2025");

            DataQualityResult result = validator.validatePayment(pmt);

            assertThat(result.hasErrors()).isTrue();
            assertThat(result.getIssues()).anyMatch(issue ->
                    issue.field().equals("paymentComponents"));
        }
    }
}
