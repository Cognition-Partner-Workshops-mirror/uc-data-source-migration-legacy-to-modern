package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for DataQualityValidator covering each anomaly type
 * identified in the DATA_ANOMALY_REPORT.
 */
class DataQualityValidatorTest {

    private DataQualityValidator validator;

    @BeforeEach
    void setUp() {
        validator = new DataQualityValidator();
    }

    // =========================================================================
    // ANO-001: Payment amount component mismatch
    // =========================================================================

    @Nested
    @DisplayName("ANO-001: Payment Amount Component Mismatch")
    class PaymentAmountComponentTests {

        @Test
        @DisplayName("Should warn when payment components do not sum to total")
        void shouldWarnOnComponentSumMismatch() {
            // Simulate PMT-2025120001: total=1487.02, prin=456.78+int=1074.69+esc=355.55 = 1887.02
            LegacyPayment payment = buildPayment("PMT-TEST-001", "LN-001",
                    "12/15/2025", "1,487.02", "456.78", "1,074.69", "355.55", "0.00",
                    "REG", "PST");

            List<String> warnings = validator.validatePayment(payment);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum")
                            && w.contains("does not match total")),
                    "Expected warning about component sum mismatch, got: " + warnings);
        }

        @Test
        @DisplayName("Should not warn when payment components sum correctly")
        void shouldNotWarnOnCorrectComponentSum() {
            // Simulate a balanced payment: 100 + 50 + 25 + 5 = 180
            LegacyPayment payment = buildPayment("PMT-TEST-002", "LN-001",
                    "12/01/2025", "180.00", "100.00", "50.00", "25.00", "5.00",
                    "REG", "PST");

            List<String> warnings = validator.validatePayment(payment);

            assertTrue(warnings.stream().noneMatch(w -> w.contains("component sum")),
                    "Should not have component sum warning, got: " + warnings);
        }

        @Test
        @DisplayName("Should detect late fee excluded from total (ANO-001 variant)")
        void shouldDetectLateFeeExcludedFromTotal() {
            // Simulate PMT-2025110003: total=1077.05, prin+int+esc+latefee = 1124.55
            LegacyPayment payment = buildPayment("PMT-TEST-003", "LN-001",
                    "11/01/2025", "1,077.05", "295.82", "781.23", "0.00", "47.50",
                    "REG", "PST");

            List<String> warnings = validator.validatePayment(payment);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum")
                            && w.contains("does not match total")),
                    "Expected warning for late-fee excluded from total");
        }
    }

    // =========================================================================
    // ANO-003: Null values in required fields
    // =========================================================================

    @Nested
    @DisplayName("ANO-003: Null Values in Required Fields")
    class NullRequiredFieldTests {

        @Test
        @DisplayName("Should throw for borrower with null first name")
        void shouldThrowForNullBorrowerFirstName() {
            LegacyBorrower borrower = buildBorrower("B-001", null, "Smith", "A",
                    "750", "80,000", "01/01/1990", "01/01/2020", "ACT");

            DataQualityException ex = assertThrows(DataQualityException.class,
                    () -> validator.validateBorrower(borrower));

            assertEquals("ANO-003", ex.getAnomalyType());
            assertTrue(ex.getMessage().contains("first name"));
        }

        @Test
        @DisplayName("Should throw for borrower with null last name")
        void shouldThrowForNullBorrowerLastName() {
            LegacyBorrower borrower = buildBorrower("B-002", "John", null, "A",
                    "750", "80,000", "01/01/1990", "01/01/2020", "ACT");

            DataQualityException ex = assertThrows(DataQualityException.class,
                    () -> validator.validateBorrower(borrower));

            assertEquals("ANO-003", ex.getAnomalyType());
            assertTrue(ex.getMessage().contains("last name"));
        }

        @Test
        @DisplayName("Should throw for loan with null borrower ID")
        void shouldThrowForNullLoanBorrowerId() {
            LegacyLoanAccount account = buildLoanAccount("LN-001", null, "FXD30",
                    "100,000", "90,000", "4.5", "1,000", "ACT", "0",
                    "01/01/2020", "01/01/2050");

            DataQualityException ex = assertThrows(DataQualityException.class,
                    () -> validator.validateLoanAccount(account));

            assertEquals("ANO-003", ex.getAnomalyType());
            assertTrue(ex.getMessage().contains("borrower ID"));
        }

        @Test
        @DisplayName("Should throw for loan with null interest rate")
        void shouldThrowForNullLoanInterestRate() {
            LegacyLoanAccount account = buildLoanAccount("LN-002", "B-001", "FXD30",
                    "100,000", "90,000", null, "1,000", "ACT", "0",
                    "01/01/2020", "01/01/2050");

            DataQualityException ex = assertThrows(DataQualityException.class,
                    () -> validator.validateLoanAccount(account));

            assertEquals("ANO-003", ex.getAnomalyType());
            assertTrue(ex.getMessage().contains("interest rate"));
        }

        @Test
        @DisplayName("Should throw for payment with null total amount")
        void shouldThrowForNullPaymentTotal() {
            LegacyPayment payment = buildPayment("PMT-001", "LN-001",
                    "12/01/2025", null, "100.00", "50.00", "0.00", "0.00",
                    "REG", "PST");

            DataQualityException ex = assertThrows(DataQualityException.class,
                    () -> validator.validatePayment(payment));

            assertEquals("ANO-003", ex.getAnomalyType());
            assertTrue(ex.getMessage().contains("total amount"));
        }

        @Test
        @DisplayName("Should throw for payment with null loan account number")
        void shouldThrowForNullPaymentLoanAccount() {
            LegacyPayment payment = buildPayment("PMT-002", null,
                    "12/01/2025", "100.00", "50.00", "30.00", "15.00", "5.00",
                    "REG", "PST");

            DataQualityException ex = assertThrows(DataQualityException.class,
                    () -> validator.validatePayment(payment));

            assertEquals("ANO-003", ex.getAnomalyType());
            assertTrue(ex.getMessage().contains("loan account number"));
        }
    }

    // =========================================================================
    // ANO-004: Delinquency / status inconsistency
    // =========================================================================

    @Nested
    @DisplayName("ANO-004: Delinquency / Status Inconsistency")
    class DelinquencyStatusTests {

        @Test
        @DisplayName("Should warn when delinquency days > 0 but status is ACT")
        void shouldWarnOnDelinquentActiveStatus() {
            LegacyLoanAccount account = buildLoanAccount("LN-DLQ", "B-001", "FXD30",
                    "100,000", "90,000", "4.5", "1,000", "ACT", "15",
                    "01/01/2020", "01/01/2050");

            List<String> warnings = validator.validateLoanAccount(account);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("delinquent")
                            && w.contains("ACT")),
                    "Expected delinquency/status warning, got: " + warnings);
        }

        @Test
        @DisplayName("Should not warn when delinquency days is 0 and status is ACT")
        void shouldNotWarnOnZeroDelinquencyActiveStatus() {
            LegacyLoanAccount account = buildLoanAccount("LN-OK", "B-001", "FXD30",
                    "100,000", "90,000", "4.5", "1,000", "ACT", "0",
                    "01/01/2020", "01/01/2050");

            List<String> warnings = validator.validateLoanAccount(account);

            assertTrue(warnings.stream().noneMatch(w -> w.contains("delinquent")),
                    "Should not have delinquency warning, got: " + warnings);
        }
    }

    // =========================================================================
    // ANO-006: Numeric values stored as strings — malformed parsing
    // =========================================================================

    @Nested
    @DisplayName("ANO-006: Malformed Numeric String Parsing")
    class NumericParsingTests {

        @Test
        @DisplayName("Should safely parse valid amount with commas")
        void shouldParseValidAmount() {
            BigDecimal result = validator.safeParseAmount("1,487.02");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        @DisplayName("Should return null for malformed amount")
        void shouldReturnNullForMalformedAmount() {
            assertNull(validator.safeParseAmount("N/A"));
            assertNull(validator.safeParseAmount("$285,000"));
            assertNull(validator.safeParseAmount("abc"));
        }

        @Test
        @DisplayName("Should return null for null or blank amount")
        void shouldReturnNullForNullAmount() {
            assertNull(validator.safeParseAmount(null));
            assertNull(validator.safeParseAmount(""));
            assertNull(validator.safeParseAmount("   "));
        }

        @Test
        @DisplayName("Should safely parse valid integer")
        void shouldParseValidInteger() {
            assertEquals(745, validator.safeParseInteger("745"));
        }

        @Test
        @DisplayName("Should return null for malformed integer")
        void shouldReturnNullForMalformedInteger() {
            assertNull(validator.safeParseInteger("N/A"));
            assertNull(validator.safeParseInteger("7.5"));
        }

        @Test
        @DisplayName("Should warn on invalid credit score range")
        void shouldWarnOnInvalidCreditScoreRange() {
            // Credit score of 200 is below valid FICO range (300-850)
            LegacyBorrower borrower = buildBorrower("B-RANGE", "John", "Doe", "A",
                    "200", "80,000", "01/01/1990", "01/01/2020", "ACT");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("FICO range")),
                    "Expected FICO range warning, got: " + warnings);
        }

        @Test
        @DisplayName("Should warn on unparseable credit score")
        void shouldWarnOnUnparseableCreditScore() {
            LegacyBorrower borrower = buildBorrower("B-BAD", "John", "Doe", "A",
                    "N/A", "80,000", "01/01/1990", "01/01/2020", "ACT");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("credit score")
                            && w.contains("not a valid integer")),
                    "Expected credit score parse warning, got: " + warnings);
        }

        @Test
        @DisplayName("Should warn on unparseable interest rate")
        void shouldWarnOnUnparseableInterestRate() {
            LegacyLoanAccount account = buildLoanAccount("LN-BAD-RATE", "B-001", "FXD30",
                    "100,000", "90,000", "TBD", "1,000", "ACT", "0",
                    "01/01/2020", "01/01/2050");

            List<String> warnings = validator.validateLoanAccount(account);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("interest rate")
                            && w.contains("not a valid decimal")),
                    "Expected interest rate parse warning, got: " + warnings);
        }
    }

    // =========================================================================
    // ANO-007: Invalid date formats
    // =========================================================================

    @Nested
    @DisplayName("ANO-007: Invalid Date Formats")
    class DateFormatTests {

        @Test
        @DisplayName("Should parse valid MM/DD/YYYY date")
        void shouldParseValidDate() {
            assertNotNull(validator.safeParseLegacyDate("03/15/1978"));
            assertNotNull(validator.safeParseLegacyDate("12/31/2025"));
        }

        @Test
        @DisplayName("Should return null for invalid date format")
        void shouldReturnNullForInvalidDate() {
            // YYYY-MM-DD instead of MM/DD/YYYY
            assertNull(validator.safeParseLegacyDate("1978-03-15"));
            // Impossible date
            assertNull(validator.safeParseLegacyDate("02/30/2025"));
            // Non-date string
            assertNull(validator.safeParseLegacyDate("NOT-A-DATE"));
        }

        @Test
        @DisplayName("Should warn on invalid borrower DOB date")
        void shouldWarnOnInvalidBorrowerDob() {
            LegacyBorrower borrower = buildBorrower("B-DATE", "John", "Doe", "A",
                    "750", "80,000", "13/01/1990", "01/01/2020", "ACT");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("DOB")
                            && w.contains("not a valid")),
                    "Expected DOB date format warning, got: " + warnings);
        }

        @Test
        @DisplayName("Should warn on invalid payment date")
        void shouldWarnOnInvalidPaymentDate() {
            LegacyPayment payment = buildPayment("PMT-DATE", "LN-001",
                    "2025-12-01", "100.00", "60.00", "30.00", "10.00", "0.00",
                    "REG", "PST");

            List<String> warnings = validator.validatePayment(payment);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("payment date")
                            && w.contains("not a valid")),
                    "Expected payment date format warning, got: " + warnings);
        }
    }

    // =========================================================================
    // Validation of status/type codes
    // =========================================================================

    @Nested
    @DisplayName("Status and Type Code Validation")
    class StatusCodeTests {

        @Test
        @DisplayName("Should warn on unknown borrower status code")
        void shouldWarnOnUnknownBorrowerStatus() {
            LegacyBorrower borrower = buildBorrower("B-STAT", "John", "Doe", "A",
                    "750", "80,000", "01/01/1990", "01/01/2020", "XYZ");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("unknown status code")
                            && w.contains("XYZ")),
                    "Expected unknown status code warning, got: " + warnings);
        }

        @Test
        @DisplayName("Should warn on unknown payment type code")
        void shouldWarnOnUnknownPaymentType() {
            LegacyPayment payment = buildPayment("PMT-TYPE", "LN-001",
                    "12/01/2025", "100.00", "60.00", "30.00", "10.00", "0.00",
                    "ZZZ", "PST");

            List<String> warnings = validator.validatePayment(payment);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("unknown type code")
                            && w.contains("ZZZ")),
                    "Expected unknown type code warning, got: " + warnings);
        }

        @Test
        @DisplayName("Should warn on unknown loan status code")
        void shouldWarnOnUnknownLoanStatus() {
            LegacyLoanAccount account = buildLoanAccount("LN-STAT", "B-001", "FXD30",
                    "100,000", "90,000", "4.5", "1,000", "BAD", "0",
                    "01/01/2020", "01/01/2050");

            List<String> warnings = validator.validateLoanAccount(account);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("unknown status code")
                            && w.contains("BAD")),
                    "Expected unknown status code warning, got: " + warnings);
        }
    }

    // =========================================================================
    // Valid data passes without errors or warnings
    // =========================================================================

    @Nested
    @DisplayName("Valid Data Passes Validation")
    class ValidDataTests {

        @Test
        @DisplayName("Should validate a clean borrower without warnings")
        void shouldPassValidBorrower() {
            LegacyBorrower borrower = buildBorrower("B-CLEAN", "James", "Mitchell", "R",
                    "745", "92,500", "03/15/1978", "01/15/2019", "ACT");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.isEmpty(), "Expected no warnings, got: " + warnings);
        }

        @Test
        @DisplayName("Should validate a clean loan account without critical warnings")
        void shouldPassValidLoanAccount() {
            LegacyLoanAccount account = buildLoanAccount("LN-CLEAN", "B-001", "FXD30",
                    "285,000", "271,432.56", "4.750", "1,487.02", "ACT", "0",
                    "02/15/2019", "02/15/2049");

            List<String> warnings = validator.validateLoanAccount(account);

            assertTrue(warnings.isEmpty(), "Expected no warnings, got: " + warnings);
        }

        @Test
        @DisplayName("Should validate a balanced payment without warnings")
        void shouldPassValidPayment() {
            LegacyPayment payment = buildPayment("PMT-CLEAN", "LN-001",
                    "12/01/2025", "2,924.18", "1,842.56", "815.50", "266.12", "0.00",
                    "REG", "PST");

            List<String> warnings = validator.validatePayment(payment);

            // Only check for component-sum or parse warnings, not date warnings from receive/process dates
            assertTrue(warnings.stream().noneMatch(w -> w.contains("component sum")),
                    "Expected no component sum warning, got: " + warnings);
        }
    }

    // =========================================================================
    // Builder helpers for test entities
    // =========================================================================

    private LegacyBorrower buildBorrower(String id, String firstName, String lastName,
                                         String middleInitial, String creditScore,
                                         String annualIncome, String dob,
                                         String createdDate, String statusCode) {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId(id);
        b.setFirstName(firstName);
        b.setLastName(lastName);
        b.setMiddleInitial(middleInitial);
        b.setCreditScore(creditScore);
        b.setAnnualIncome(annualIncome);
        b.setDateOfBirth(dob);
        b.setCreatedDate(createdDate);
        b.setStatusCode(statusCode);
        return b;
    }

    private LegacyLoanAccount buildLoanAccount(String accountNumber, String borrowerId,
                                                String productCode, String origAmount,
                                                String currentBalance, String interestRate,
                                                String monthlyPayment, String statusCode,
                                                String delinquencyDays,
                                                String originationDate, String maturityDate) {
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber(accountNumber);
        a.setBorrowerId(borrowerId);
        a.setProductCode(productCode);
        a.setOriginalAmount(origAmount);
        a.setCurrentBalance(currentBalance);
        a.setInterestRate(interestRate);
        a.setMonthlyPayment(monthlyPayment);
        a.setStatusCode(statusCode);
        a.setDelinquencyDays(delinquencyDays);
        a.setOriginationDate(originationDate);
        a.setMaturityDate(maturityDate);
        // Set non-null property fields to avoid unrelated warnings
        a.setPropertyType("SFR");
        a.setBorrowerFirstName("Test");
        a.setBorrowerLastName("User");
        return a;
    }

    private LegacyPayment buildPayment(String seqNbr, String loanAcctNbr,
                                        String paymentDate, String totalAmt,
                                        String principalAmt, String interestAmt,
                                        String escrowAmt, String lateFee,
                                        String typeCode, String statusCode) {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber(seqNbr);
        p.setLoanAccountNumber(loanAcctNbr);
        p.setPaymentDate(paymentDate);
        p.setTotalAmount(totalAmt);
        p.setPrincipalAmount(principalAmt);
        p.setInterestAmount(interestAmt);
        p.setEscrowAmount(escrowAmt);
        p.setLateFee(lateFee);
        p.setTypeCode(typeCode);
        p.setStatusCode(statusCode);
        return p;
    }
}
