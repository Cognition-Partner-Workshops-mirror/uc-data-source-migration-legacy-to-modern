package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.DataAnomaly.Severity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
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
    // Safe Parsing Tests
    // =========================================================================

    @Nested
    class ParseSafeAmountTests {

        @Test
        void parsesAmountWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.parseSafeAmount("285,000"));
        }

        @Test
        void parsesAmountWithCommasAndDecimals() {
            assertEquals(new BigDecimal("1487.02"), validator.parseSafeAmount("1,487.02"));
        }

        @Test
        void parsesAmountWithDollarSign() {
            assertEquals(new BigDecimal("285000"), validator.parseSafeAmount("$285,000"));
        }

        @Test
        void parsesParentheticalNegative() {
            assertEquals(new BigDecimal("-1487.02"), validator.parseSafeAmount("(1,487.02)"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseSafeAmount(null));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.parseSafeAmount("   "));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.parseSafeAmount("N/A"));
        }

        @Test
        void returnsNullForLetters() {
            assertNull(validator.parseSafeAmount("abc"));
        }

        @Test
        void parsesPlainDecimal() {
            assertEquals(new BigDecimal("271432.56"), validator.parseSafeAmount("271,432.56"));
        }

        @Test
        void parsesZero() {
            assertEquals(new BigDecimal("0"), validator.parseSafeAmount("0"));
        }

        @Test
        void parsesAmountWithSpaces() {
            assertEquals(new BigDecimal("285000"), validator.parseSafeAmount(" 285,000 "));
        }
    }

    @Nested
    class ParseSafeDecimalTests {

        @Test
        void parsesSimpleDecimal() {
            assertEquals(new BigDecimal("4.750"), validator.parseSafeDecimal("4.750"));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.parseSafeDecimal(""));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.parseSafeDecimal("VARIABLE"));
        }

        @Test
        void parsesWithLeadingTrailingSpaces() {
            assertEquals(new BigDecimal("82.5"), validator.parseSafeDecimal("  82.5  "));
        }
    }

    @Nested
    class ParseSafeIntegerTests {

        @Test
        void parsesValidInteger() {
            assertEquals(745, validator.parseSafeInteger("745"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseSafeInteger(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseSafeInteger(""));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.parseSafeInteger("N/A"));
        }

        @Test
        void returnsNullForDecimal() {
            assertNull(validator.parseSafeInteger("4.5"));
        }

        @Test
        void parsesWithSpaces() {
            assertEquals(360, validator.parseSafeInteger(" 360 "));
        }
    }

    @Nested
    class ParseSafeDateTests {

        @Test
        void parsesValidLegacyDate() {
            LocalDate result = validator.parseSafeDate("03/15/1978");
            assertEquals(LocalDate.of(1978, 3, 15), result);
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseSafeDate(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseSafeDate(""));
        }

        @Test
        void returnsNullForIsoFormat() {
            assertNull(validator.parseSafeDate("1978-03-15"));
        }

        @Test
        void returnsNullForInvalidDate() {
            assertNull(validator.parseSafeDate("13/32/2025"));
        }

        @Test
        void returnsNullForNonDateString() {
            assertNull(validator.parseSafeDate("NOT_A_DATE"));
        }

        @Test
        void parsesLeapYearDate() {
            assertEquals(LocalDate.of(2024, 2, 29), validator.parseSafeDate("02/29/2024"));
        }

        @Test
        void adjustsInvalidLeapYearToLastValidDay() {
            // Java's DateTimeFormatter with MM/dd/yyyy resolves 02/29 in non-leap years
            // to 02/28 by default. The parser does not reject it.
            assertEquals(LocalDate.of(2025, 2, 28), validator.parseSafeDate("02/29/2025"));
        }
    }

    // =========================================================================
    // Borrower Validation Tests
    // =========================================================================

    @Nested
    class ValidateBorrowerTests {

        @Test
        void validBorrowerProducesNoAnomalies() {
            LegacyBorrower borrower = createValidBorrower();
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertTrue(anomalies.isEmpty(), "Valid borrower should produce no anomalies");
        }

        @Test
        void nullFirstNameIsCritical() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(1, anomalies.size());
            assertEquals(Severity.CRITICAL, anomalies.get(0).getSeverity());
            assertTrue(anomalies.get(0).getMessage().contains("First name"));
        }

        @Test
        void blankLastNameIsCritical() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setLastName("   ");
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(1, anomalies.size());
            assertEquals(Severity.CRITICAL, anomalies.get(0).getSeverity());
            assertTrue(anomalies.get(0).getMessage().contains("Last name"));
        }

        @Test
        void nonNumericCreditScoreIsHigh() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("N/A");
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(1, anomalies.size());
            assertEquals(Severity.HIGH, anomalies.get(0).getSeverity());
            assertTrue(anomalies.get(0).getMessage().contains("not a valid integer"));
        }

        @Test
        void creditScoreOutOfRangeIsMedium() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("200");
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(1, anomalies.size());
            assertEquals(Severity.MEDIUM, anomalies.get(0).getSeverity());
            assertTrue(anomalies.get(0).getMessage().contains("out of valid range"));
        }

        @Test
        void creditScoreAboveMaxIsMedium() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("900");
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(1, anomalies.size());
            assertEquals(Severity.MEDIUM, anomalies.get(0).getSeverity());
        }

        @Test
        void nonNumericAnnualIncomeIsHigh() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("UNKNOWN");
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(1, anomalies.size());
            assertEquals(Severity.HIGH, anomalies.get(0).getSeverity());
            assertTrue(anomalies.get(0).getMessage().contains("not a valid amount"));
        }

        @Test
        void negativeAnnualIncomeIsHigh() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("-50,000");
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(1, anomalies.size());
            assertEquals(Severity.HIGH, anomalies.get(0).getSeverity());
            assertTrue(anomalies.get(0).getMessage().contains("negative"));
        }

        @Test
        void invalidDateFormatIsHigh() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("1978-03-15");
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(1, anomalies.size());
            assertEquals(Severity.HIGH, anomalies.get(0).getSeverity());
            assertTrue(anomalies.get(0).getMessage().contains("MM/DD/YYYY"));
        }

        @Test
        void invalidStatusCodeIsHigh() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setStatusCode("XYZ");
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(1, anomalies.size());
            assertEquals(Severity.HIGH, anomalies.get(0).getSeverity());
            assertTrue(anomalies.get(0).getMessage().contains("Invalid borrower status"));
        }

        @Test
        void nullMiddleInitialIsAccepted() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setMiddleInitial(null);
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertTrue(anomalies.isEmpty(), "Null middle initial should not be an anomaly");
        }

        @Test
        void multipleAnomaliesDetectedAtOnce() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setFirstName(null);
            borrower.setCreditScore("BAD");
            borrower.setDateOfBirth("INVALID");
            List<DataAnomaly> anomalies = validator.validateBorrower(borrower);
            assertEquals(3, anomalies.size());
        }
    }

    // =========================================================================
    // Loan Account Validation Tests
    // =========================================================================

    @Nested
    class ValidateLoanAccountTests {

        @Test
        void validLoanAccountProducesNoAnomalies() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.isEmpty(), "Valid loan should produce no anomalies");
        }

        @Test
        void orphanedBorrowerIsCritical() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, false, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.CRITICAL && a.getMessage().contains("Orphaned loan")));
        }

        @Test
        void orphanedProductIsCritical() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, false);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.CRITICAL && a.getMessage().contains("product")));
        }

        @Test
        void invalidOriginalAmountIsHigh() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setOriginalAmount("NOT_A_NUMBER");
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getColumn().equals("LN_ORIG_AMT")));
        }

        @Test
        void invalidInterestRateIsHigh() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setInterestRate("VARIABLE");
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getMessage().contains("not a valid decimal")));
        }

        @Test
        void delinquentButActiveIsHigh() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setDelinquencyDays("15");
            acct.setStatusCode("ACT");
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getMessage().contains("delinquent")));
        }

        @Test
        void zeroDelinquencyActiveIsOk() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setDelinquencyDays("0");
            acct.setStatusCode("ACT");
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.isEmpty());
        }

        @Test
        void invalidLoanStatusCodeIsHigh() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setStatusCode("XXX");
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getMessage().contains("Invalid loan status")));
        }

        @Test
        void invalidPropertyTypeIsMedium() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setPropertyType("ZZZ");
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.MEDIUM && a.getMessage().contains("property type")));
        }

        @Test
        void invalidOriginationDateIsHigh() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setOriginationDate("2019-02-15");
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getColumn().equals("LN_ORIG_DT")));
        }

        @Test
        void nonNumericDelinquencyDaysIsHigh() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setDelinquencyDays("MANY");
            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getMessage().contains("Delinquency days")));
        }
    }

    // =========================================================================
    // Payment Validation Tests
    // =========================================================================

    @Nested
    class ValidatePaymentTests {

        @Test
        void validPaymentProducesNoAnomalies() {
            LegacyPayment pmt = createValidPayment();
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.isEmpty(), "Valid payment should produce no anomalies");
        }

        @Test
        void orphanedPaymentIsCritical() {
            LegacyPayment pmt = createValidPayment();
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, false);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.CRITICAL && a.getMessage().contains("Orphaned payment")));
        }

        @Test
        void componentSumMismatchIsCritical() {
            LegacyPayment pmt = createValidPayment();
            pmt.setEscrowAmount("355.55");
            // total=1,000.00 but components = 400+550+355.55+0 = 1,305.55
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.CRITICAL && a.getMessage().contains("component mismatch")));
        }

        @Test
        void componentSumWithinToleranceIsOk() {
            LegacyPayment pmt = createValidPayment();
            // total=1,000.00, components = 400+550+50+0 = 1,000.00
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().noneMatch(a ->
                    a.getMessage().contains("component mismatch")));
        }

        @Test
        void nonNumericPaymentAmountIsHigh() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTotalAmount("PENDING");
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getColumn().equals("PMT_AMT")));
        }

        @Test
        void invalidPaymentTypeCodeIsHigh() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTypeCode("ZZZ");
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getMessage().contains("payment type")));
        }

        @Test
        void invalidPaymentStatusCodeIsHigh() {
            LegacyPayment pmt = createValidPayment();
            pmt.setStatusCode("BAD");
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getMessage().contains("payment status")));
        }

        @Test
        void invalidPaymentDateIsHigh() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("2025-12-15");
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH && a.getColumn().equals("PMT_DT")));
        }

        @Test
        void processedBeforeReceivedIsMedium() {
            LegacyPayment pmt = createValidPayment();
            pmt.setReceivedDate("12/20/2025");
            pmt.setProcessedDate("12/15/2025");
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.MEDIUM && a.getMessage().contains("Processed date")));
        }

        @Test
        void lateFeeIncludedInComponentMismatch() {
            LegacyPayment pmt = createValidPayment();
            pmt.setLateFee("47.50");
            // total=1,000.00 but components = 400+550+50+47.50 = 1,047.50
            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.CRITICAL && a.getMessage().contains("component mismatch")));
        }

        @Test
        void allValidPaymentTypesAccepted() {
            for (String code : List.of("REG", "EXT", "PRT", "PRE")) {
                LegacyPayment pmt = createValidPayment();
                pmt.setTypeCode(code);
                List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
                assertTrue(anomalies.stream().noneMatch(a ->
                        a.getMessage().contains("payment type")),
                        "Type code " + code + " should be valid");
            }
        }

        @Test
        void allValidPaymentStatusesAccepted() {
            for (String code : List.of("PST", "REV", "NSF", "PND")) {
                LegacyPayment pmt = createValidPayment();
                pmt.setStatusCode(code);
                List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
                assertTrue(anomalies.stream().noneMatch(a ->
                        a.getMessage().contains("payment status")),
                        "Status code " + code + " should be valid");
            }
        }
    }

    // =========================================================================
    // Seed Data Specific Tests (tests against actual data-legacy.sql values)
    // =========================================================================

    @Nested
    class SeedDataAnomalyTests {

        @Test
        void seedPaymentPMT2025120001HasComponentMismatch() {
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

            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.CRITICAL
                            && a.getMessage().contains("component mismatch")),
                    "PMT-2025120001 should have a component sum mismatch anomaly");
        }

        @Test
        void seedPaymentPMT2025110003HasComponentMismatch() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-2025110003");
            pmt.setLoanAccountNumber("LN-2018-00089");
            pmt.setPaymentDate("11/01/2025");
            pmt.setTotalAmount("1,077.05");
            pmt.setPrincipalAmount("295.82");
            pmt.setInterestAmount("781.23");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("47.50");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("PST");
            pmt.setReceivedDate("11/18/2025");
            pmt.setProcessedDate("11/19/2025");

            List<DataAnomaly> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.CRITICAL
                            && a.getMessage().contains("component mismatch")),
                    "PMT-2025110003 should have a component sum mismatch anomaly");
        }

        @Test
        void seedLoanLN2018DelinquentButActive() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-2018-00089");
            acct.setBorrowerId("B-10003");
            acct.setProductCode("ARM51");
            acct.setOriginalAmount("195,000");
            acct.setCurrentBalance("178,234.12");
            acct.setInterestRate("5.250");
            acct.setTermMonths("360");
            acct.setMonthlyPayment("1,077.05");
            acct.setOriginationDate("07/01/2018");
            acct.setMaturityDate("07/01/2048");
            acct.setFirstPaymentDate("08/01/2018");
            acct.setNextPaymentDate("01/01/2026");
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("15");
            acct.setEscrowBalance("2,100.00");
            acct.setLtvPercent("75.0");
            acct.setPropertyAddress("305 Pine Road");
            acct.setPropertyCity("Austin");
            acct.setPropertyState("TX");
            acct.setPropertyZip("78701");
            acct.setPropertyType("SFR");
            acct.setAppraisedValue("260,000");
            acct.setCreatedDate("06/15/2018");
            acct.setUpdatedDate("12/01/2025");

            List<DataAnomaly> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a ->
                    a.getSeverity() == Severity.HIGH
                            && a.getMessage().contains("delinquent")),
                    "LN-2018-00089 with 15 delinquency days and ACT status should flag anomaly");
        }
    }

    // =========================================================================
    // Test Helpers
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
        b.setAddressLine2("Apt 3B");
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
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber("LN-2019-00142");
        a.setBorrowerId("B-10001");
        a.setBorrowerFirstName("James");
        a.setBorrowerLastName("Mitchell");
        a.setBorrowerSsnLast4("0142");
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

    private LegacyPayment createValidPayment() {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber("PMT-TEST-001");
        p.setLoanAccountNumber("LN-2019-00142");
        p.setPaymentDate("12/15/2025");
        p.setTotalAmount("1,000.00");
        p.setPrincipalAmount("400.00");
        p.setInterestAmount("550.00");
        p.setEscrowAmount("50.00");
        p.setLateFee("0.00");
        p.setTypeCode("REG");
        p.setStatusCode("PST");
        p.setReceivedDate("12/15/2025");
        p.setProcessedDate("12/16/2025");
        p.setCreatedDate("12/16/2025");
        p.setUpdatedDate("12/16/2025");
        return p;
    }
}
