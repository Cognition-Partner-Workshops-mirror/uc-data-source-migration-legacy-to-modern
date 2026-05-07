package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
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
    // Safe Amount Parsing
    // =========================================================================

    @Nested
    class SafeParseLegacyAmount {

        @Test
        void parsesStandardAmountWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.safeParseLegacyAmount("285,000"));
        }

        @Test
        void parsesDecimalAmountWithCommas() {
            assertEquals(new BigDecimal("1487.02"), validator.safeParseLegacyAmount("1,487.02"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount(null));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount("  "));
        }

        @Test
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount("N/A"));
        }

        @Test
        void stripsDollarSign() {
            assertEquals(new BigDecimal("285000"), validator.safeParseLegacyAmount("$285,000"));
        }

        @Test
        void returnsZeroForTextPlaceholder() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount("TBD"));
        }

        @Test
        void returnsZeroForParenthesizedNegative() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount("(1,234.56)"));
        }

        @Test
        void parsesZeroString() {
            assertEquals(new BigDecimal("0"), validator.safeParseLegacyAmount("0"));
        }

        @Test
        void parsesZeroDecimalString() {
            assertEquals(new BigDecimal("0.00"), validator.safeParseLegacyAmount("0.00"));
        }
    }

    // =========================================================================
    // Safe Decimal Parsing
    // =========================================================================

    @Nested
    class SafeParseLegacyDecimal {

        @Test
        void parsesInterestRate() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseLegacyDecimal("4.750"));
        }

        @Test
        void stripsPercentSign() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseLegacyDecimal("4.750%"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyDecimal(null));
        }

        @Test
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyDecimal("VARIABLE"));
        }

        @Test
        void handlesLeadingTrailingWhitespace() {
            assertEquals(new BigDecimal("3.125"), validator.safeParseLegacyDecimal("  3.125  "));
        }
    }

    // =========================================================================
    // Safe Integer Parsing
    // =========================================================================

    @Nested
    class SafeParseLegacyInteger {

        @Test
        void parsesValidInteger() {
            assertEquals(745, validator.safeParseLegacyInteger("745"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyInteger(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseLegacyInteger("  "));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.safeParseLegacyInteger("N/A"));
        }

        @Test
        void returnsNullForPending() {
            assertNull(validator.safeParseLegacyInteger("PENDING"));
        }

        @Test
        void handlesDecimalCreditScore() {
            assertEquals(745, validator.safeParseLegacyInteger("745.0"));
        }

        @Test
        void handlesCommasInInteger() {
            assertEquals(92500, validator.safeParseLegacyInteger("92,500"));
        }
    }

    // =========================================================================
    // Safe Date Parsing
    // =========================================================================

    @Nested
    class SafeParseLegacyDate {

        @Test
        void parsesValidDate() {
            assertEquals(LocalDate.of(2025, 12, 15), validator.safeParseLegacyDate("12/15/2025"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyDate(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseLegacyDate(""));
        }

        @Test
        void returnsNullForInvalidFormat() {
            assertNull(validator.safeParseLegacyDate("2025-12-15"));
        }

        @Test
        void returnsNullForGarbage() {
            assertNull(validator.safeParseLegacyDate("NOT-A-DATE"));
        }

        @Test
        void handlesLeadingTrailingWhitespace() {
            assertEquals(LocalDate.of(1978, 3, 15), validator.safeParseLegacyDate("  03/15/1978  "));
        }
    }

    // =========================================================================
    // Borrower Validation
    // =========================================================================

    @Nested
    class ValidateBorrower {

        @Test
        void validBorrowerProducesNoAnomalies() {
            LegacyBorrower b = createValidBorrower();
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.isEmpty(), "Expected no anomalies but got: " + anomalies);
        }

        @Test
        void detectsMissingFirstName() {
            LegacyBorrower b = createValidBorrower();
            b.setFirstName(null);
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("missing required first name")));
        }

        @Test
        void detectsMissingLastName() {
            LegacyBorrower b = createValidBorrower();
            b.setLastName("");
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("missing required last name")));
        }

        @Test
        void detectsMissingEmail() {
            LegacyBorrower b = createValidBorrower();
            b.setEmail(null);
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("missing required email")));
        }

        @Test
        void detectsUnparseableCreditScore() {
            LegacyBorrower b = createValidBorrower();
            b.setCreditScore("N/A");
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("not a valid number")));
        }

        @Test
        void detectsCreditScoreOutOfRange() {
            LegacyBorrower b = createValidBorrower();
            b.setCreditScore("200");
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("outside valid range")));
        }

        @Test
        void detectsInvalidDateOfBirth() {
            LegacyBorrower b = createValidBorrower();
            b.setDateOfBirth("1978-03-15");
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("not valid MM/DD/YYYY")));
        }

        @Test
        void detectsInvalidStatusCode() {
            LegacyBorrower b = createValidBorrower();
            b.setStatusCode("XYZ");
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("invalid borrower status code")));
        }

        @Test
        void acceptsValidStatusCodes() {
            LegacyBorrower b = createValidBorrower();
            b.setStatusCode("ACT");
            assertTrue(validator.validateBorrower(b).isEmpty());
            b.setStatusCode("INA");
            assertTrue(validator.validateBorrower(b).isEmpty());
        }

        @Test
        void detectsInvalidCreatedDate() {
            LegacyBorrower b = createValidBorrower();
            b.setCreatedDate("INVALID");
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("created date") && a.contains("not valid")));
        }

        @Test
        void detectsInvalidUpdatedDate() {
            LegacyBorrower b = createValidBorrower();
            b.setUpdatedDate("BAD-DATE");
            List<String> anomalies = validator.validateBorrower(b);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("updated date") && a.contains("not valid")));
        }
    }

    // =========================================================================
    // Loan Account Validation
    // =========================================================================

    @Nested
    class ValidateLoanAccount {

        @Test
        void validLoanAccountProducesNoAnomalies() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<String> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.isEmpty(), "Expected no anomalies but got: " + anomalies);
        }

        @Test
        void detectsOrphanedBorrower() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<String> anomalies = validator.validateLoanAccount(acct, false, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("non-existent borrower")));
        }

        @Test
        void detectsOrphanedProduct() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<String> anomalies = validator.validateLoanAccount(acct, true, false);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("non-existent product")));
        }

        @Test
        void detectsCurrentBalanceExceedingOriginalAmount() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setCurrentBalance("300,000");
            acct.setOriginalAmount("285,000");
            List<String> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("current balance") && a.contains("exceeds original")));
        }

        @Test
        void detectsInvalidLoanStatusCode() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setStatusCode("BAD");
            List<String> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("invalid loan status code")));
        }

        @Test
        void acceptsValidLoanStatusCodes() {
            LegacyLoanAccount acct = createValidLoanAccount();
            for (String code : List.of("ACT", "CLO", "DFT", "FRB")) {
                acct.setStatusCode(code);
                List<String> anomalies = validator.validateLoanAccount(acct, true, true);
                assertTrue(anomalies.isEmpty(), "Expected no anomalies for status " + code + " but got: " + anomalies);
            }
        }

        @Test
        void detectsInvalidPropertyTypeCode() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setPropertyType("XYZ");
            List<String> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("invalid property type code")));
        }

        @Test
        void detectsLtvDrift() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setCurrentBalance("271,432.56");
            acct.setAppraisedValue("345,000");
            acct.setLtvPercent("82.5");
            List<String> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("LTV drift")));
        }

        @Test
        void detectsInvalidOriginationDate() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setOriginationDate("INVALID");
            List<String> anomalies = validator.validateLoanAccount(acct, true, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("origination date")));
        }
    }

    // =========================================================================
    // Payment Validation
    // =========================================================================

    @Nested
    class ValidatePayment {

        @Test
        void validPaymentProducesNoAnomalies() {
            LegacyPayment pmt = createValidPayment();
            List<String> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.isEmpty(), "Expected no anomalies but got: " + anomalies);
        }

        @Test
        void detectsOrphanedLoanAccount() {
            LegacyPayment pmt = createValidPayment();
            List<String> anomalies = validator.validatePayment(pmt, false);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("non-existent loan account")));
        }

        @Test
        void detectsPaymentComponentSumMismatch() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");
            List<String> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("component sum") && a.contains("does not equal total")));
        }

        @Test
        void acceptsPaymentWithMatchingComponents() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTotalAmount("2,924.18");
            pmt.setPrincipalAmount("1,842.56");
            pmt.setInterestAmount("815.50");
            pmt.setEscrowAmount("266.12");
            pmt.setLateFee("0.00");
            List<String> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().noneMatch(a -> a.contains("component sum")));
        }

        @Test
        void detectsInvalidPaymentTypeCode() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTypeCode("XXX");
            List<String> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("invalid payment type code")));
        }

        @Test
        void detectsInvalidPaymentStatusCode() {
            LegacyPayment pmt = createValidPayment();
            pmt.setStatusCode("BAD");
            List<String> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("invalid payment status code")));
        }

        @Test
        void detectsLatePaymentWithNoFee() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/05/2025");
            pmt.setLateFee("0.00");
            pmt.setTotalAmount("1077.05");
            pmt.setPrincipalAmount("297.12");
            pmt.setInterestAmount("779.93");
            pmt.setEscrowAmount("0.00");
            List<String> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("days late but no late fee")));
        }

        @Test
        void acceptsOnTimePaymentWithNoFee() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("12/15/2025");
            pmt.setReceivedDate("12/14/2025");
            pmt.setLateFee("0.00");
            List<String> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().noneMatch(a -> a.contains("late fee")));
        }

        @Test
        void detectsInvalidPaymentDate() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("BAD-DATE");
            List<String> anomalies = validator.validatePayment(pmt, true);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("payment date") && a.contains("not valid")));
        }
    }

    // =========================================================================
    // Denormalized Name Drift / SSN Check
    // =========================================================================

    @Nested
    class DenormalizedDataChecks {

        @Test
        void detectsFirstNameDrift() {
            LegacyLoanAccount acct = createValidLoanAccount();
            LegacyBorrower borrower = createValidBorrower();
            acct.setBorrowerFirstName("Jim");
            borrower.setFirstName("James");
            List<String> anomalies = validator.checkDenormalizedNameDrift(acct, borrower);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("first name mismatch")));
        }

        @Test
        void detectsLastNameDrift() {
            LegacyLoanAccount acct = createValidLoanAccount();
            LegacyBorrower borrower = createValidBorrower();
            acct.setBorrowerLastName("Mitchell-Smith");
            borrower.setLastName("Mitchell");
            List<String> anomalies = validator.checkDenormalizedNameDrift(acct, borrower);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("last name mismatch")));
        }

        @Test
        void detectsSsnMatchingPhoneSuffix() {
            LegacyLoanAccount acct = createValidLoanAccount();
            LegacyBorrower borrower = createValidBorrower();
            borrower.setPhoneNumber("217-555-0142");
            acct.setBorrowerSsnLast4("0142");
            List<String> anomalies = validator.checkDenormalizedNameDrift(acct, borrower);
            assertTrue(anomalies.stream().anyMatch(a -> a.contains("SSN last-4") && a.contains("matches borrower phone")));
        }

        @Test
        void noAnomalyWhenNamesMatch() {
            LegacyLoanAccount acct = createValidLoanAccount();
            LegacyBorrower borrower = createValidBorrower();
            acct.setBorrowerFirstName("James");
            acct.setBorrowerLastName("Mitchell");
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");
            borrower.setPhoneNumber("217-555-9999");
            acct.setBorrowerSsnLast4("0142");
            List<String> anomalies = validator.checkDenormalizedNameDrift(acct, borrower);
            assertTrue(anomalies.isEmpty(), "Expected no anomalies but got: " + anomalies);
        }
    }

    // =========================================================================
    // Factory methods for test data
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
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber("LN-2020-00398");
        a.setBorrowerId("B-10002");
        a.setBorrowerFirstName("Sarah");
        a.setBorrowerLastName("Chen");
        a.setBorrowerSsnLast4("0198");
        a.setProductCode("FXD15");
        a.setOriginalAmount("420,000");
        a.setCurrentBalance("312,876.43");
        a.setInterestRate("3.125");
        a.setTermMonths("180");
        a.setMonthlyPayment("2,924.18");
        a.setOriginationDate("04/01/2020");
        a.setMaturityDate("04/01/2035");
        a.setFirstPaymentDate("05/01/2020");
        a.setNextPaymentDate("01/01/2026");
        a.setStatusCode("ACT");
        a.setDelinquencyDays("0");
        a.setEscrowBalance("4,890.12");
        a.setLtvPercent("50.9");
        a.setPropertyAddress("1100 Oak Avenue");
        a.setPropertyCity("Portland");
        a.setPropertyState("OR");
        a.setPropertyZip("97201");
        a.setPropertyType("CND");
        a.setAppraisedValue("615,000");
        a.setCreatedDate("03/20/2020");
        a.setUpdatedDate("12/01/2025");
        return a;
    }

    private LegacyPayment createValidPayment() {
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
}
