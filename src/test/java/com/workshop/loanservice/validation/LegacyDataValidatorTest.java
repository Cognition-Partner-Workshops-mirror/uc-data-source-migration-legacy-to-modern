package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    @Nested
    class ParseAmountTests {

        @Test
        void parsesValidAmountWithCommas() {
            BigDecimal result = validator.parseAmount("285,000", "TEST", "REC-1");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void parsesValidAmountWithCommasAndDecimals() {
            BigDecimal result = validator.parseAmount("1,487.02", "TEST", "REC-1");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount(null, "TEST", "REC-1"));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("  ", "TEST", "REC-1"));
        }

        @Test
        void handlesNonNumericGracefully() {
            BigDecimal result = validator.parseAmount("N/A", "TEST", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void handlesCurrencySymbol() {
            BigDecimal result = validator.parseAmount("$285,000", "TEST", "REC-1");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void handlesTbdPlaceholder() {
            BigDecimal result = validator.parseAmount("TBD", "TEST", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void parsesPlainInteger() {
            BigDecimal result = validator.parseAmount("0", "TEST", "REC-1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void parsesNegativeAmount() {
            BigDecimal result = validator.parseAmount("-1,234.56", "TEST", "REC-1");
            assertEquals(new BigDecimal("-1234.56"), result);
        }
    }

    @Nested
    class ParseDecimalTests {

        @Test
        void parsesValidDecimal() {
            BigDecimal result = validator.parseDecimal("5.250", "TEST", "REC-1");
            assertEquals(new BigDecimal("5.250"), result);
        }

        @Test
        void handlesLeadingTrailingSpaces() {
            BigDecimal result = validator.parseDecimal("  82.5  ", "TEST", "REC-1");
            assertEquals(new BigDecimal("82.5"), result);
        }

        @Test
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal("N/A", "TEST", "REC-1"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal(null, "TEST", "REC-1"));
        }
    }

    @Nested
    class ParseIntegerTests {

        @Test
        void parsesValidInteger() {
            assertEquals(745, validator.parseInteger("745", "TEST", "REC-1"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseInteger(null, "TEST", "REC-1"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseInteger("  ", "TEST", "REC-1"));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.parseInteger("N/A", "TEST", "REC-1"));
        }

        @Test
        void handlesIntegerWithSpaces() {
            assertEquals(360, validator.parseInteger(" 360 ", "TEST", "REC-1"));
        }

        @Test
        void handlesIntegerWithNonDigitSuffix() {
            assertEquals(750, validator.parseInteger("750+", "TEST", "REC-1"));
        }
    }

    @Nested
    class ParseDateTests {

        @Test
        void parsesValidLegacyDate() {
            String result = validator.parseDate("03/15/1978", "TEST", "REC-1");
            assertEquals("1978-03-15", result);
        }

        @Test
        void parsesEndOfMonth() {
            String result = validator.parseDate("02/28/1990", "TEST", "REC-1");
            assertEquals("1990-02-28", result);
        }

        @Test
        void returnsNullForInvalidFormat() {
            assertNull(validator.parseDate("2025-01-15", "TEST", "REC-1"));
        }

        @Test
        void returnsNullForGarbage() {
            assertNull(validator.parseDate("not-a-date", "TEST", "REC-1"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseDate(null, "TEST", "REC-1"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseDate("", "TEST", "REC-1"));
        }

        @Test
        void returnsNullForInvalidDay() {
            assertNull(validator.parseDate("13/45/2025", "TEST", "REC-1"));
        }
    }

    @Nested
    class BuildBorrowerNameTests {

        @Test
        void buildsFullNameWithMiddleInitial() {
            String result = validator.buildBorrowerName("James", "Mitchell", "R");
            assertEquals("James R. Mitchell", result);
        }

        @Test
        void buildsFullNameWithoutMiddleInitial() {
            String result = validator.buildBorrowerName("Robert", "Williams", null);
            assertEquals("Robert Williams", result);
        }

        @Test
        void handlesNullFirstName() {
            String result = validator.buildBorrowerName(null, "Smith", "A");
            assertEquals("[Unknown] A. Smith", result);
        }

        @Test
        void handlesNullLastName() {
            String result = validator.buildBorrowerName("John", null, null);
            assertEquals("John [Unknown]", result);
        }

        @Test
        void handlesBothNullNames() {
            String result = validator.buildBorrowerName(null, null, null);
            assertEquals("[Unknown] [Unknown]", result);
        }

        @Test
        void handlesBlankFirstName() {
            String result = validator.buildBorrowerName("  ", "Doe", null);
            assertEquals("[Unknown] Doe", result);
        }
    }

    @Nested
    class PaymentComponentValidationTests {

        @Test
        void passesWhenComponentsSumToTotal() {
            List<String> warnings = validator.validatePaymentComponents(
                    "PMT-001",
                    new BigDecimal("2924.18"),
                    new BigDecimal("1842.56"),
                    new BigDecimal("815.50"),
                    new BigDecimal("266.12"),
                    BigDecimal.ZERO);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsMismatchWhenEscrowNotInTotal() {
            List<String> warnings = validator.validatePaymentComponents(
                    "PMT-2025120001",
                    new BigDecimal("1487.02"),
                    new BigDecimal("456.78"),
                    new BigDecimal("1074.69"),
                    new BigDecimal("355.55"),
                    BigDecimal.ZERO);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("PMT-2025120001"));
            assertTrue(warnings.get(0).contains("difference"));
        }

        @Test
        void detectsLateFeeNotInTotal() {
            List<String> warnings = validator.validatePaymentComponents(
                    "PMT-2025110003",
                    new BigDecimal("1077.05"),
                    new BigDecimal("295.82"),
                    new BigDecimal("781.23"),
                    BigDecimal.ZERO,
                    new BigDecimal("47.50"));
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("PMT-2025110003"));
        }

        @Test
        void allowsSmallRoundingDifference() {
            List<String> warnings = validator.validatePaymentComponents(
                    "PMT-ROUND",
                    new BigDecimal("100.00"),
                    new BigDecimal("50.005"),
                    new BigDecimal("49.999"),
                    BigDecimal.ZERO,
                    BigDecimal.ZERO);
            assertTrue(warnings.isEmpty());
        }
    }

    @Nested
    class LateFeeConsistencyTests {

        @Test
        void detectsLateFeeWithPostedStatus() {
            List<String> warnings = validator.validateLateFeeConsistency(
                    "PMT-001", new BigDecimal("47.50"), "PST");
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("late fee"));
        }

        @Test
        void noWarningForZeroLateFee() {
            List<String> warnings = validator.validateLateFeeConsistency(
                    "PMT-001", BigDecimal.ZERO, "PST");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void noWarningForNonPostedStatus() {
            List<String> warnings = validator.validateLateFeeConsistency(
                    "PMT-001", new BigDecimal("47.50"), "NSF");
            assertTrue(warnings.isEmpty());
        }
    }

    @Nested
    class DelinquencyStatusTests {

        @Test
        void detectsActiveStatusWithDelinquency() {
            List<String> warnings = validator.validateDelinquencyStatus(
                    "LN-001", "15", "ACT");
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("delinquency days"));
            assertTrue(warnings.get(0).contains("ACT"));
        }

        @Test
        void noWarningForZeroDelinquency() {
            List<String> warnings = validator.validateDelinquencyStatus(
                    "LN-001", "0", "ACT");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void noWarningForDefaultStatus() {
            List<String> warnings = validator.validateDelinquencyStatus(
                    "LN-001", "90", "DFT");
            assertTrue(warnings.isEmpty());
        }
    }

    @Nested
    class LtvValidationTests {

        @Test
        void noWarningForAccurateLtv() {
            List<String> warnings = validator.validateLtv(
                    "LN-001", "75.0", "195,000", "260,000");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void noWarningForSmallRounding() {
            List<String> warnings = validator.validateLtv(
                    "LN-001", "82.5", "285,000", "345,000");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsLargeDiscrepancy() {
            List<String> warnings = validator.validateLtv(
                    "LN-001", "90.0", "285,000", "345,000");
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("stored LTV"));
            assertTrue(warnings.get(0).contains("computed"));
        }
    }

    @Nested
    class SsnPhoneValidationTests {

        @Test
        void detectsSsnMatchingPhone() {
            List<String> warnings = validator.validateSsnNotFromPhone(
                    "LN-001", "0142", "217-555-0142");
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("SSN last-4"));
            assertTrue(warnings.get(0).contains("phone last-4"));
        }

        @Test
        void noWarningWhenSsnDiffersFromPhone() {
            List<String> warnings = validator.validateSsnNotFromPhone(
                    "LN-001", "9999", "217-555-0142");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void noWarningForNullSsn() {
            List<String> warnings = validator.validateSsnNotFromPhone(
                    "LN-001", null, "217-555-0142");
            assertTrue(warnings.isEmpty());
        }

        @Test
        void noWarningForNullPhone() {
            List<String> warnings = validator.validateSsnNotFromPhone(
                    "LN-001", "0142", null);
            assertTrue(warnings.isEmpty());
        }
    }

    @Nested
    class BorrowerValidationTests {

        @Test
        void detectsMissingFirstName() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-TEST");
            borrower.setLastName("Smith");
            borrower.setStatusCode("ACT");
            borrower.setSsnEncrypted("ENC_XXX");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing first name")));
        }

        @Test
        void detectsMissingLastName() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-TEST");
            borrower.setFirstName("John");
            borrower.setStatusCode("ACT");
            borrower.setSsnEncrypted("ENC_XXX");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing last name")));
        }

        @Test
        void detectsMissingSsn() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-TEST");
            borrower.setFirstName("John");
            borrower.setLastName("Smith");
            borrower.setStatusCode("ACT");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing encrypted SSN")));
        }

        @Test
        void detectsInvalidCreditScore() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-TEST");
            borrower.setFirstName("John");
            borrower.setLastName("Smith");
            borrower.setSsnEncrypted("ENC_XXX");
            borrower.setStatusCode("ACT");
            borrower.setCreditScore("200");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("credit score") && w.contains("outside valid range")));
        }

        @Test
        void detectsUnparseableDateOfBirth() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-TEST");
            borrower.setFirstName("John");
            borrower.setLastName("Smith");
            borrower.setSsnEncrypted("ENC_XXX");
            borrower.setStatusCode("ACT");
            borrower.setDateOfBirth("not-a-date");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unparseable date of birth")));
        }

        @Test
        void detectsMissingStatusCode() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-TEST");
            borrower.setFirstName("John");
            borrower.setLastName("Smith");
            borrower.setSsnEncrypted("ENC_XXX");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing status code")));
        }

        @Test
        void noWarningsForValidBorrower() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-10001");
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");
            borrower.setSsnEncrypted("ENC_XXX_001");
            borrower.setStatusCode("ACT");
            borrower.setCreditScore("745");
            borrower.setDateOfBirth("03/15/1978");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.isEmpty());
        }
    }

    @Nested
    class LoanAccountValidationTests {

        @Test
        void detectsMissingBorrowerId() {
            LegacyLoanAccount account = new LegacyLoanAccount();
            account.setLoanAccountNumber("LN-TEST");
            account.setProductCode("FXD30");
            account.setStatusCode("ACT");
            account.setDelinquencyDays("0");
            account.setLtvPercent("80.0");
            account.setOriginalAmount("200,000");
            account.setAppraisedValue("250,000");

            List<String> warnings = validator.validateLoanAccount(account);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing borrower ID")));
        }

        @Test
        void detectsMissingProductCode() {
            LegacyLoanAccount account = new LegacyLoanAccount();
            account.setLoanAccountNumber("LN-TEST");
            account.setBorrowerId("B-10001");
            account.setStatusCode("ACT");
            account.setDelinquencyDays("0");
            account.setLtvPercent("80.0");
            account.setOriginalAmount("200,000");
            account.setAppraisedValue("250,000");

            List<String> warnings = validator.validateLoanAccount(account);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing product code")));
        }

        @Test
        void detectsDelinquencyStatusMismatch() {
            LegacyLoanAccount account = new LegacyLoanAccount();
            account.setLoanAccountNumber("LN-TEST");
            account.setBorrowerId("B-10001");
            account.setProductCode("FXD30");
            account.setStatusCode("ACT");
            account.setDelinquencyDays("15");
            account.setLtvPercent("75.0");
            account.setOriginalAmount("195,000");
            account.setAppraisedValue("260,000");

            List<String> warnings = validator.validateLoanAccount(account);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("delinquency days") && w.contains("ACT")));
        }

        @Test
        void noWarningsForValidAccount() {
            LegacyLoanAccount account = new LegacyLoanAccount();
            account.setLoanAccountNumber("LN-2019-00142");
            account.setBorrowerId("B-10001");
            account.setProductCode("FXD30");
            account.setStatusCode("ACT");
            account.setDelinquencyDays("0");
            account.setLtvPercent("82.5");
            account.setOriginalAmount("285,000");
            account.setAppraisedValue("345,000");

            List<String> warnings = validator.validateLoanAccount(account);
            assertTrue(warnings.isEmpty());
        }
    }

    @Nested
    class PaymentValidationTests {

        @Test
        void detectsComponentMismatch() {
            LegacyPayment payment = new LegacyPayment();
            payment.setPaymentSequenceNumber("PMT-TEST");
            payment.setLoanAccountNumber("LN-001");
            payment.setTotalAmount("1,487.02");
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");
            payment.setStatusCode("PST");

            List<String> warnings = validator.validatePayment(payment);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum")));
        }

        @Test
        void detectsLateFeeInconsistency() {
            LegacyPayment payment = new LegacyPayment();
            payment.setPaymentSequenceNumber("PMT-TEST");
            payment.setLoanAccountNumber("LN-001");
            payment.setTotalAmount("1,124.55");
            payment.setPrincipalAmount("295.82");
            payment.setInterestAmount("781.23");
            payment.setEscrowAmount("0.00");
            payment.setLateFee("47.50");
            payment.setStatusCode("PST");

            List<String> warnings = validator.validatePayment(payment);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("late fee")));
        }

        @Test
        void detectsMissingLoanAccountNumber() {
            LegacyPayment payment = new LegacyPayment();
            payment.setPaymentSequenceNumber("PMT-TEST");
            payment.setTotalAmount("100.00");
            payment.setPrincipalAmount("50.00");
            payment.setInterestAmount("50.00");
            payment.setEscrowAmount("0.00");
            payment.setLateFee("0.00");
            payment.setStatusCode("PST");

            List<String> warnings = validator.validatePayment(payment);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing loan account number")));
        }

        @Test
        void noWarningsForValidPayment() {
            LegacyPayment payment = new LegacyPayment();
            payment.setPaymentSequenceNumber("PMT-TEST");
            payment.setLoanAccountNumber("LN-001");
            payment.setTotalAmount("2,924.18");
            payment.setPrincipalAmount("1,842.56");
            payment.setInterestAmount("815.50");
            payment.setEscrowAmount("266.12");
            payment.setLateFee("0.00");
            payment.setStatusCode("PST");

            List<String> warnings = validator.validatePayment(payment);
            assertTrue(warnings.isEmpty());
        }
    }
}
