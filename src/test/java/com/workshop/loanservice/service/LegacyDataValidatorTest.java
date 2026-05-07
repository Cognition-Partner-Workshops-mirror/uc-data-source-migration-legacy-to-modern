package com.workshop.loanservice.service;

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

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANM-003: Numeric String Parsing
    // =========================================================================

    @Nested
    @DisplayName("ANM-003: Amount parsing (commas, dollar signs, malformed)")
    class AmountParsingTests {

        @Test
        @DisplayName("Parses amount with commas")
        void parsesAmountWithCommas() {
            BigDecimal result = validator.parseAmount("285,000", "LN_ORIG_AMT", "LN-001");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Parses amount with commas and decimals")
        void parsesAmountWithCommasAndDecimals() {
            BigDecimal result = validator.parseAmount("1,487.02", "PMT_AMT", "PMT-001");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        @DisplayName("Parses amount with dollar sign")
        void parsesAmountWithDollarSign() {
            BigDecimal result = validator.parseAmount("$285,000", "LN_ORIG_AMT", "LN-001");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Returns zero for null amount")
        void returnsZeroForNull() {
            BigDecimal result = validator.parseAmount(null, "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns zero for blank amount")
        void returnsZeroForBlank() {
            BigDecimal result = validator.parseAmount("  ", "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns zero for non-numeric string instead of throwing")
        void returnsZeroForNonNumeric() {
            BigDecimal result = validator.parseAmount("N/A", "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Returns zero for text with numbers")
        void returnsZeroForMixedText() {
            BigDecimal result = validator.parseAmount("TBD", "LN_ORIG_AMT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }
    }

    @Nested
    @DisplayName("ANM-003: Decimal parsing")
    class DecimalParsingTests {

        @Test
        @DisplayName("Parses decimal rate string")
        void parsesDecimalRate() {
            BigDecimal result = validator.parseDecimal("5.250", "LN_INT_RT", "LN-001");
            assertEquals(new BigDecimal("5.250"), result);
        }

        @Test
        @DisplayName("Parses decimal with whitespace")
        void parsesDecimalWithWhitespace() {
            BigDecimal result = validator.parseDecimal("  4.750  ", "LN_INT_RT", "LN-001");
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        @DisplayName("Returns zero for non-numeric decimal")
        void returnsZeroForNonNumeric() {
            BigDecimal result = validator.parseDecimal("abc", "LN_INT_RT", "LN-001");
            assertEquals(BigDecimal.ZERO, result);
        }
    }

    @Nested
    @DisplayName("ANM-003: Integer parsing (credit scores, terms)")
    class IntegerParsingTests {

        @Test
        @DisplayName("Parses valid credit score")
        void parsesValidCreditScore() {
            Integer result = validator.parseInteger("745", "BORR_CRDT_SCR", "B-001");
            assertEquals(745, result);
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNull() {
            Integer result = validator.parseInteger(null, "BORR_CRDT_SCR", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("Returns null for non-numeric string instead of throwing")
        void returnsNullForNonNumeric() {
            Integer result = validator.parseInteger("N/A", "BORR_CRDT_SCR", "B-001");
            assertNull(result);
        }

        @Test
        @DisplayName("Parses integer with whitespace")
        void parsesIntegerWithWhitespace() {
            Integer result = validator.parseInteger("  360  ", "PROD_TERM_MOS", "FXD30");
            assertEquals(360, result);
        }
    }

    // =========================================================================
    // ANM-004: Date Parsing and Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-004: Date string parsing and ISO formatting")
    class DateParsingTests {

        @Test
        @DisplayName("Parses valid MM/DD/YYYY date")
        void parsesValidDate() {
            assertNotNull(validator.parseDate("03/15/1978", "BORR_DOB_DT", "B-001"));
        }

        @Test
        @DisplayName("Formats date to ISO-8601")
        void formatsDateToIso() {
            String result = validator.formatDateToIso("02/15/2019", "LN_ORIG_DT", "LN-001");
            assertEquals("2019-02-15", result);
        }

        @Test
        @DisplayName("Returns null for invalid date instead of throwing")
        void returnsNullForInvalidDate() {
            assertNull(validator.parseDate("13/32/2025", "PMT_DT", "PMT-001"));
        }

        @Test
        @DisplayName("Returns null for empty date")
        void returnsNullForEmptyDate() {
            assertNull(validator.parseDate("", "PMT_DT", "PMT-001"));
        }

        @Test
        @DisplayName("Returns null for null date")
        void returnsNullForNullDate() {
            assertNull(validator.parseDate(null, "PMT_DT", "PMT-001"));
        }

        @Test
        @DisplayName("Returns raw string when date format is invalid")
        void returnsRawStringOnInvalidFormat() {
            String result = validator.formatDateToIso("not-a-date", "LN_ORIG_DT", "LN-001");
            assertEquals("not-a-date", result);
        }

        @Test
        @DisplayName("Returns raw string for YYYY-MM-DD format (wrong format)")
        void returnsRawStringForWrongFormat() {
            String result = validator.formatDateToIso("2025-12-15", "PMT_DT", "PMT-001");
            assertEquals("2025-12-15", result);
        }
    }

    // =========================================================================
    // ANM-001: Payment Component Sum Validation
    // =========================================================================

    @Nested
    @DisplayName("ANM-001: Payment component sum mismatch")
    class PaymentSumValidationTests {

        @Test
        @DisplayName("Detects payment where components exceed total")
        void detectsComponentSumExceedsTotal() {
            LegacyPayment pmt = createPayment("PMT-001", "1,487.02", "456.78", "1,074.69", "355.55", "0.00");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum") && w.contains("does not match total")),
                    "Should warn about component sum mismatch. Warnings: " + warnings);
        }

        @Test
        @DisplayName("No warning when components sum correctly")
        void noWarningWhenComponentsSumCorrectly() {
            LegacyPayment pmt = createPayment("PMT-002", "2,924.18", "1,842.56", "815.50", "266.12", "0.00");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("component sum")),
                    "Should not warn when components sum correctly. Warnings: " + warnings);
        }

        private LegacyPayment createPayment(String id, String total, String principal,
                                              String interest, String escrow, String lateFee) {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber(id);
            pmt.setLoanAccountNumber("LN-001");
            pmt.setTotalAmount(total);
            pmt.setPrincipalAmount(principal);
            pmt.setInterestAmount(interest);
            pmt.setEscrowAmount(escrow);
            pmt.setLateFee(lateFee);
            pmt.setTypeCode("REG");
            pmt.setStatusCode("PST");
            return pmt;
        }
    }

    // =========================================================================
    // ANM-002: Status / Delinquency Inconsistency
    // =========================================================================

    @Nested
    @DisplayName("ANM-002: Delinquent loan with active status")
    class StatusDelinquencyTests {

        @Test
        @DisplayName("Detects delinquent loan marked as active")
        void detectsDelinquentActiveLoan() {
            LegacyLoanAccount acct = createLoanAccount("LN-001", "ACT", "15");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("delinquency days") && w.contains("ACT")),
                    "Should warn about delinquency/status mismatch. Warnings: " + warnings);
        }

        @Test
        @DisplayName("No warning for active loan with zero delinquency")
        void noWarningForActiveLoanZeroDelinquency() {
            LegacyLoanAccount acct = createLoanAccount("LN-002", "ACT", "0");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("delinquency")),
                    "Should not warn for zero delinquency. Warnings: " + warnings);
        }

        @Test
        @DisplayName("No warning for delinquent loan with DFT status")
        void noWarningForDelinquentDefaultLoan() {
            LegacyLoanAccount acct = createLoanAccount("LN-003", "DFT", "30");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("delinquency")),
                    "Should not warn when status matches delinquency. Warnings: " + warnings);
        }

        private LegacyLoanAccount createLoanAccount(String id, String status, String dlqDays) {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber(id);
            acct.setBorrowerId("B-10001");
            acct.setBorrowerFirstName("Test");
            acct.setBorrowerLastName("User");
            acct.setStatusCode(status);
            acct.setDelinquencyDays(dlqDays);
            acct.setProductCode("FXD30");
            return acct;
        }
    }

    // =========================================================================
    // ANM-006: Null Required Fields
    // =========================================================================

    @Nested
    @DisplayName("ANM-006: Null values in required fields")
    class NullFieldTests {

        @Test
        @DisplayName("Detects null first name in borrower")
        void detectsNullFirstName() {
            LegacyBorrower borrower = createBorrower("B-001", null, "Smith", "ACT");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing first name")),
                    "Should warn about missing first name. Warnings: " + warnings);
        }

        @Test
        @DisplayName("Detects null last name in borrower")
        void detectsNullLastName() {
            LegacyBorrower borrower = createBorrower("B-002", "John", null, "ACT");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing last name")),
                    "Should warn about missing last name. Warnings: " + warnings);
        }

        @Test
        @DisplayName("Detects null status code in borrower")
        void detectsNullStatusCode() {
            LegacyBorrower borrower = createBorrower("B-003", "John", "Smith", null);
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing status code")),
                    "Should warn about missing status code. Warnings: " + warnings);
        }

        @Test
        @DisplayName("No warnings for complete borrower record")
        void noWarningsForCompleteBorrower() {
            LegacyBorrower borrower = createBorrower("B-004", "James", "Mitchell", "ACT");
            borrower.setCreditScore("745");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.isEmpty(), "Should have no warnings for valid borrower. Warnings: " + warnings);
        }

        @Test
        @DisplayName("Detects null borrower names in loan account")
        void detectsNullBorrowerNamesInLoan() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-001");
            acct.setBorrowerId("B-10001");
            acct.setBorrowerFirstName(null);
            acct.setBorrowerLastName(null);
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("0");
            acct.setProductCode("FXD30");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("denormalized borrower name")),
                    "Should warn about null borrower names. Warnings: " + warnings);
        }

        private LegacyBorrower createBorrower(String id, String firstName, String lastName, String status) {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId(id);
            borrower.setFirstName(firstName);
            borrower.setLastName(lastName);
            borrower.setStatusCode(status);
            return borrower;
        }
    }

    // =========================================================================
    // Safe Name Building
    // =========================================================================

    @Nested
    @DisplayName("Safe name building with null handling")
    class SafeNameTests {

        @Test
        @DisplayName("Builds name with all parts present")
        void buildsFullName() {
            assertEquals("James R. Mitchell", validator.safeFullName("James", "R", "Mitchell"));
        }

        @Test
        @DisplayName("Builds name with null middle initial")
        void buildsNameWithoutMiddle() {
            assertEquals("Robert Williams", validator.safeFullName("Robert", null, "Williams"));
        }

        @Test
        @DisplayName("Handles null first name")
        void handlesNullFirstName() {
            String result = validator.safeBorrowerName(null, "Mitchell");
            assertEquals("Unknown Mitchell", result);
        }

        @Test
        @DisplayName("Handles null last name")
        void handlesNullLastName() {
            String result = validator.safeBorrowerName("James", null);
            assertEquals("James Unknown", result);
        }

        @Test
        @DisplayName("Handles both names null")
        void handlesBothNamesNull() {
            String result = validator.safeBorrowerName(null, null);
            assertEquals("Unknown Unknown", result);
        }
    }

    // =========================================================================
    // Invalid Status Code Validation
    // =========================================================================

    @Nested
    @DisplayName("Invalid status code detection")
    class InvalidStatusCodeTests {

        @Test
        @DisplayName("Detects unrecognized loan status code")
        void detectsUnrecognizedLoanStatus() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-001");
            acct.setBorrowerId("B-10001");
            acct.setBorrowerFirstName("Test");
            acct.setBorrowerLastName("User");
            acct.setStatusCode("XYZ");
            acct.setDelinquencyDays("0");
            acct.setProductCode("FXD30");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized status code")),
                    "Should warn about unrecognized status code. Warnings: " + warnings);
        }

        @Test
        @DisplayName("Detects unrecognized payment status code")
        void detectsUnrecognizedPaymentStatus() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-001");
            pmt.setLoanAccountNumber("LN-001");
            pmt.setTotalAmount("100.00");
            pmt.setPrincipalAmount("50.00");
            pmt.setInterestAmount("50.00");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("0.00");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("BAD");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized status code")),
                    "Should warn about unrecognized payment status code. Warnings: " + warnings);
        }

        @Test
        @DisplayName("Detects unrecognized payment type code")
        void detectsUnrecognizedPaymentType() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-001");
            pmt.setLoanAccountNumber("LN-001");
            pmt.setTotalAmount("100.00");
            pmt.setPrincipalAmount("50.00");
            pmt.setInterestAmount("50.00");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("0.00");
            pmt.setTypeCode("ZZZ");
            pmt.setStatusCode("PST");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized type code")),
                    "Should warn about unrecognized payment type code. Warnings: " + warnings);
        }

        @Test
        @DisplayName("Detects unrecognized property type code")
        void detectsUnrecognizedPropertyType() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-001");
            acct.setBorrowerId("B-10001");
            acct.setBorrowerFirstName("Test");
            acct.setBorrowerLastName("User");
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("0");
            acct.setProductCode("FXD30");
            acct.setPropertyType("XYZ");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized property type code")),
                    "Should warn about unrecognized property type code. Warnings: " + warnings);
        }
    }

    // =========================================================================
    // Credit Score Range Validation
    // =========================================================================

    @Nested
    @DisplayName("Credit score range validation")
    class CreditScoreRangeTests {

        @Test
        @DisplayName("Detects credit score below valid range")
        void detectsLowCreditScore() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-001");
            borrower.setFirstName("Test");
            borrower.setLastName("User");
            borrower.setStatusCode("ACT");
            borrower.setCreditScore("100");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("credit score") && w.contains("outside valid range")),
                    "Should warn about low credit score. Warnings: " + warnings);
        }

        @Test
        @DisplayName("Detects credit score above valid range")
        void detectsHighCreditScore() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-001");
            borrower.setFirstName("Test");
            borrower.setLastName("User");
            borrower.setStatusCode("ACT");
            borrower.setCreditScore("900");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("credit score") && w.contains("outside valid range")),
                    "Should warn about high credit score. Warnings: " + warnings);
        }

        @Test
        @DisplayName("No warning for valid credit score")
        void noWarningForValidCreditScore() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-001");
            borrower.setFirstName("Test");
            borrower.setLastName("User");
            borrower.setStatusCode("ACT");
            borrower.setCreditScore("745");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("credit score")),
                    "Should not warn for valid credit score. Warnings: " + warnings);
        }
    }
}
