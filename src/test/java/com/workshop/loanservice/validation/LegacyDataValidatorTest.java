package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
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
    // ANO-003: Safe numeric parsing
    // =========================================================================

    @Nested
    @DisplayName("ANO-003: parseSafeAmount — numeric strings with commas")
    class ParseSafeAmountTests {

        @Test
        @DisplayName("Parses comma-formatted amount correctly")
        void parsesCommaFormattedAmount() {
            assertEquals(new BigDecimal("285000"), validator.parseSafeAmount("285,000", "TEST", "R1"));
        }

        @Test
        @DisplayName("Parses amount with decimals and commas")
        void parsesAmountWithDecimalsAndCommas() {
            assertEquals(new BigDecimal("1487.02"), validator.parseSafeAmount("1,487.02", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns ZERO for null input")
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseSafeAmount(null, "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns ZERO for blank input")
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.parseSafeAmount("  ", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns ZERO for non-numeric input instead of crashing")
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO, validator.parseSafeAmount("N/A", "TEST", "R1"));
        }

        @Test
        @DisplayName("Handles dollar sign prefix gracefully")
        void handlesDollarSign() {
            assertEquals(new BigDecimal("285000"), validator.parseSafeAmount("$285,000", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns ZERO for text like 'TBD'")
        void returnsZeroForPlaceholderText() {
            assertEquals(BigDecimal.ZERO, validator.parseSafeAmount("TBD", "TEST", "R1"));
        }

        @Test
        @DisplayName("Parses zero amount string")
        void parsesZeroAmount() {
            assertEquals(new BigDecimal("0.00"), validator.parseSafeAmount("0.00", "TEST", "R1"));
        }
    }

    @Nested
    @DisplayName("ANO-003: parseSafeInteger — string-to-integer conversion")
    class ParseSafeIntegerTests {

        @Test
        @DisplayName("Parses valid integer string")
        void parsesValidInteger() {
            assertEquals(745, validator.parseSafeInteger("745", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNull() {
            assertNull(validator.parseSafeInteger(null, "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns null for non-numeric input instead of crashing")
        void returnsNullForNonNumeric() {
            assertNull(validator.parseSafeInteger("N/A", "TEST", "R1"));
        }

        @Test
        @DisplayName("Handles decimal string by truncating")
        void handlesDecimalString() {
            assertEquals(745, validator.parseSafeInteger("745.0", "TEST", "R1"));
        }

        @Test
        @DisplayName("Trims whitespace before parsing")
        void trimsWhitespace() {
            assertEquals(15, validator.parseSafeInteger(" 15 ", "TEST", "R1"));
        }

        @Test
        @DisplayName("Handles comma-formatted integer")
        void handlesCommaInteger() {
            assertEquals(1500, validator.parseSafeInteger("1,500", "TEST", "R1"));
        }
    }

    @Nested
    @DisplayName("ANO-003: parseSafeDecimal — string-to-decimal conversion")
    class ParseSafeDecimalTests {

        @Test
        @DisplayName("Parses valid decimal string")
        void parsesValidDecimal() {
            assertEquals(new BigDecimal("4.750"), validator.parseSafeDecimal("4.750", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns ZERO for non-numeric input")
        void returnsZeroForNonNumeric() {
            assertEquals(BigDecimal.ZERO, validator.parseSafeDecimal("PENDING", "TEST", "R1"));
        }
    }

    // =========================================================================
    // ANO-008: Date parsing
    // =========================================================================

    @Nested
    @DisplayName("ANO-008: parseSafeDate — MM/DD/YYYY string parsing")
    class ParseSafeDateTests {

        @Test
        @DisplayName("Parses valid MM/DD/YYYY date")
        void parsesValidDate() {
            assertEquals(LocalDate.of(2019, 2, 15),
                    validator.parseSafeDate("02/15/2019", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns null for invalid date format")
        void returnsNullForInvalidFormat() {
            assertNull(validator.parseSafeDate("2019-02-15", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns null for impossible date")
        void returnsNullForImpossibleDate() {
            assertNull(validator.parseSafeDate("02/30/2021", "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns null for null input")
        void returnsNullForNull() {
            assertNull(validator.parseSafeDate(null, "TEST", "R1"));
        }

        @Test
        @DisplayName("Returns null for non-date text")
        void returnsNullForNonDate() {
            assertNull(validator.parseSafeDate("UNKNOWN", "TEST", "R1"));
        }
    }

    // =========================================================================
    // ANO-001: Payment component sum validation
    // =========================================================================

    @Nested
    @DisplayName("ANO-001: validatePayment — component sum mismatch detection")
    class PaymentValidationTests {

        @Test
        @DisplayName("Detects payment where components exceed total (escrow excluded from total)")
        void detectsEscrowMismatch() {
            LegacyPayment pmt = createPayment("PMT-TEST-001",
                    "1,487.02", "456.78", "1,074.69", "355.55", "0.00");

            List<ValidationWarning> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-001".equals(w.anomalyId()) && w.detail().contains("discrepancy")),
                    "Should detect payment component sum mismatch");
        }

        @Test
        @DisplayName("Detects payment where late fee excluded from total")
        void detectsLateFeeMismatch() {
            LegacyPayment pmt = createPayment("PMT-TEST-002",
                    "1,077.05", "295.82", "781.23", "0.00", "47.50");

            List<ValidationWarning> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-001".equals(w.anomalyId())),
                    "Should detect late fee excluded from total");
        }

        @Test
        @DisplayName("No warning for valid payment where components match total")
        void noWarningForValidPayment() {
            LegacyPayment pmt = createPayment("PMT-TEST-003",
                    "2,924.18", "1,842.56", "815.50", "266.12", "0.00");

            List<ValidationWarning> warnings = validator.validatePayment(pmt);

            assertFalse(warnings.stream().anyMatch(w ->
                    "ANO-001".equals(w.anomalyId())),
                    "Should not flag valid payment");
        }
    }

    // =========================================================================
    // ANO-002: SSN last-4 vs phone number cross-check
    // =========================================================================

    @Nested
    @DisplayName("ANO-002: validateLoanAccount — SSN last-4 vs phone number")
    class SsnPhoneValidationTests {

        @Test
        @DisplayName("Detects SSN last-4 matching phone last-4")
        void detectsSsnPhoneMatch() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-001", "B-10001", "FXD30");
            acct.setBorrowerSsnLast4("0142");

            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell");
            borrower.setPhoneNumber("217-555-0142");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, borrower);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-002".equals(w.anomalyId()) && w.detail().contains("phone last-4")),
                    "Should detect SSN last-4 matches phone number");
        }

        @Test
        @DisplayName("No warning when SSN last-4 differs from phone last-4")
        void noWarningWhenSsnDiffersFromPhone() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-002", "B-10001", "FXD30");
            acct.setBorrowerSsnLast4("9999");

            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell");
            borrower.setPhoneNumber("217-555-0142");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, borrower);

            assertFalse(warnings.stream().anyMatch(w ->
                    "ANO-002".equals(w.anomalyId())),
                    "Should not flag when SSN differs from phone");
        }
    }

    // =========================================================================
    // ANO-004: Active loan with delinquency
    // =========================================================================

    @Nested
    @DisplayName("ANO-004: validateLoanAccount — status/delinquency inconsistency")
    class DelinquencyValidationTests {

        @Test
        @DisplayName("Detects active loan with non-zero delinquency days")
        void detectsActiveWithDelinquency() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-003", "B-10003", "ARM51");
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("15");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-004".equals(w.anomalyId()) && w.detail().contains("15 delinquency days")),
                    "Should detect active loan with delinquency");
        }

        @Test
        @DisplayName("No warning for active loan with zero delinquency")
        void noWarningForActiveZeroDelinquency() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-004", "B-10001", "FXD30");
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("0");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, null);

            assertFalse(warnings.stream().anyMatch(w ->
                    "ANO-004".equals(w.anomalyId())),
                    "Should not flag active loan with zero delinquency");
        }

        @Test
        @DisplayName("No warning for defaulted loan with delinquency")
        void noWarningForDefaultWithDelinquency() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-005", "B-10003", "ARM51");
            acct.setStatusCode("DFT");
            acct.setDelinquencyDays("90");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, null);

            assertFalse(warnings.stream().anyMatch(w ->
                    "ANO-004".equals(w.anomalyId())),
                    "Should not flag defaulted loan with delinquency");
        }
    }

    // =========================================================================
    // ANO-005: Orphaned records (null FK fields)
    // =========================================================================

    @Nested
    @DisplayName("ANO-005: validateLoanAccount / validatePayment — orphaned records")
    class OrphanedRecordTests {

        @Test
        @DisplayName("Detects loan with null borrower ID")
        void detectsNullBorrowerId() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-006", null, "FXD30");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-005".equals(w.anomalyId()) && w.detail().contains("Borrower ID is null")),
                    "Should detect null borrower ID");
        }

        @Test
        @DisplayName("Detects loan with null product code")
        void detectsNullProductCode() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-007", "B-10001", null);

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-005".equals(w.anomalyId()) && w.detail().contains("Product code is null")),
                    "Should detect null product code");
        }

        @Test
        @DisplayName("Detects payment with null loan account number")
        void detectsNullLoanAccountNumber() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-ORPHAN");
            pmt.setLoanAccountNumber(null);
            pmt.setTotalAmount("100.00");
            pmt.setPrincipalAmount("50.00");
            pmt.setInterestAmount("50.00");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("0.00");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("PST");

            List<ValidationWarning> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-005".equals(w.anomalyId()) && w.detail().contains("orphaned payment")),
                    "Should detect orphaned payment");
        }
    }

    // =========================================================================
    // ANO-006: Denormalized data drift
    // =========================================================================

    @Nested
    @DisplayName("ANO-006: validateLoanAccount — denormalized name drift")
    class DenormalizedDataDriftTests {

        @Test
        @DisplayName("Detects first name mismatch between loan and borrower master")
        void detectsFirstNameDrift() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-008", "B-10001", "FXD30");
            acct.setBorrowerFirstName("Jim");

            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, borrower);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-006".equals(w.anomalyId()) && w.detail().contains("first name")),
                    "Should detect first name drift");
        }

        @Test
        @DisplayName("Detects last name mismatch between loan and borrower master")
        void detectsLastNameDrift() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-009", "B-10002", "FXD15");
            acct.setBorrowerLastName("Chang");

            LegacyBorrower borrower = createBorrower("B-10002", "Sarah", "Chen");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, borrower);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-006".equals(w.anomalyId()) && w.detail().contains("last name")),
                    "Should detect last name drift");
        }

        @Test
        @DisplayName("No warning when names match")
        void noWarningWhenNamesMatch() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-010", "B-10001", "FXD30");
            acct.setBorrowerFirstName("James");
            acct.setBorrowerLastName("Mitchell");

            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, borrower);

            assertFalse(warnings.stream().anyMatch(w ->
                    "ANO-006".equals(w.anomalyId())),
                    "Should not flag matching names");
        }
    }

    // =========================================================================
    // ANO-007: Null required fields on borrower
    // =========================================================================

    @Nested
    @DisplayName("ANO-007: validateBorrower — null required fields")
    class NullRequiredFieldTests {

        @Test
        @DisplayName("Detects null first name")
        void detectsNullFirstName() {
            LegacyBorrower borrower = createBorrower("B-TEST", null, "Smith");

            List<ValidationWarning> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-007".equals(w.anomalyId()) && w.detail().contains("first name")),
                    "Should detect null first name");
        }

        @Test
        @DisplayName("Detects null last name")
        void detectsNullLastName() {
            LegacyBorrower borrower = createBorrower("B-TEST", "John", null);

            List<ValidationWarning> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-007".equals(w.anomalyId()) && w.detail().contains("last name")),
                    "Should detect null last name");
        }

        @Test
        @DisplayName("Detects null email")
        void detectsNullEmail() {
            LegacyBorrower borrower = createBorrower("B-TEST", "John", "Smith");
            borrower.setEmail(null);

            List<ValidationWarning> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-007".equals(w.anomalyId()) && w.detail().contains("Email")),
                    "Should detect null email");
        }

        @Test
        @DisplayName("Detects out-of-range credit score")
        void detectsOutOfRangeCreditScore() {
            LegacyBorrower borrower = createBorrower("B-TEST", "John", "Smith");
            borrower.setCreditScore("200");
            borrower.setEmail("test@test.com");

            List<ValidationWarning> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w ->
                    w.detail().contains("outside valid range")),
                    "Should detect credit score outside valid FICO range");
        }

        @Test
        @DisplayName("No warning for valid borrower")
        void noWarningForValidBorrower() {
            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell");
            borrower.setEmail("j.mitchell@email.com");
            borrower.setCreditScore("745");
            borrower.setEmploymentStatus("EMPLOYED");
            borrower.setDateOfBirth("03/15/1978");

            List<ValidationWarning> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.isEmpty(),
                    "Should not produce warnings for a valid borrower, but got: " + warnings);
        }
    }

    // =========================================================================
    // ANO-009: Late payment date detection
    // =========================================================================

    @Nested
    @DisplayName("ANO-009: validatePayment — late payment detection")
    class LatePaymentTests {

        @Test
        @DisplayName("Detects payment received after due date")
        void detectsLatePayment() {
            LegacyPayment pmt = createPayment("PMT-LATE", "1,077.05", "297.12", "779.93", "0.00", "0.00");
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/05/2025");

            List<ValidationWarning> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w ->
                    "ANO-009".equals(w.anomalyId()) && w.detail().contains("4 days")),
                    "Should detect 4-day late payment");
        }

        @Test
        @DisplayName("No warning when received on due date")
        void noWarningForOnTimePayment() {
            LegacyPayment pmt = createPayment("PMT-ONTIME", "2,924.18", "1,842.56", "815.50", "266.12", "0.00");
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/01/2025");

            List<ValidationWarning> warnings = validator.validatePayment(pmt);

            assertFalse(warnings.stream().anyMatch(w ->
                    "ANO-009".equals(w.anomalyId())),
                    "Should not flag on-time payment");
        }
    }

    // =========================================================================
    // Invalid status code detection
    // =========================================================================

    @Nested
    @DisplayName("Invalid status code detection")
    class InvalidStatusCodeTests {

        @Test
        @DisplayName("Detects invalid loan status code")
        void detectsInvalidLoanStatus() {
            LegacyLoanAccount acct = createLoanAccount("LN-TEST-011", "B-10001", "FXD30");
            acct.setStatusCode("XYZ");

            List<ValidationWarning> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().anyMatch(w ->
                    w.detail().contains("Invalid loan status code")),
                    "Should detect invalid loan status");
        }

        @Test
        @DisplayName("Detects invalid payment type code")
        void detectsInvalidPaymentType() {
            LegacyPayment pmt = createPayment("PMT-BAD", "100.00", "50.00", "50.00", "0.00", "0.00");
            pmt.setTypeCode("ZZZ");
            pmt.setStatusCode("PST");
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/01/2025");

            List<ValidationWarning> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w ->
                    w.detail().contains("Invalid payment type code")),
                    "Should detect invalid payment type code");
        }

        @Test
        @DisplayName("Detects invalid payment status code")
        void detectsInvalidPaymentStatus() {
            LegacyPayment pmt = createPayment("PMT-BAD2", "100.00", "50.00", "50.00", "0.00", "0.00");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("BAD");
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/01/2025");

            List<ValidationWarning> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w ->
                    w.detail().contains("Invalid payment status code")),
                    "Should detect invalid payment status code");
        }
    }

    // =========================================================================
    // Helper methods for building test entities
    // =========================================================================

    private LegacyPayment createPayment(String id, String total, String principal,
                                         String interest, String escrow, String lateFee) {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber(id);
        pmt.setLoanAccountNumber("LN-2019-00142");
        pmt.setPaymentDate("12/15/2025");
        pmt.setTotalAmount(total);
        pmt.setPrincipalAmount(principal);
        pmt.setInterestAmount(interest);
        pmt.setEscrowAmount(escrow);
        pmt.setLateFee(lateFee);
        pmt.setTypeCode("REG");
        pmt.setStatusCode("PST");
        pmt.setReceivedDate("12/14/2025");
        pmt.setProcessedDate("12/15/2025");
        return pmt;
    }

    private LegacyLoanAccount createLoanAccount(String loanId, String borrowerId, String productCode) {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber(loanId);
        acct.setBorrowerId(borrowerId);
        acct.setBorrowerFirstName("James");
        acct.setBorrowerLastName("Mitchell");
        acct.setProductCode(productCode);
        acct.setOriginalAmount("285,000");
        acct.setCurrentBalance("271,432.56");
        acct.setInterestRate("4.750");
        acct.setTermMonths("360");
        acct.setMonthlyPayment("1,487.02");
        acct.setStatusCode("ACT");
        acct.setDelinquencyDays("0");
        acct.setPropertyType("SFR");
        return acct;
    }

    private LegacyBorrower createBorrower(String id, String firstName, String lastName) {
        LegacyBorrower borrower = new LegacyBorrower();
        borrower.setBorrowerId(id);
        borrower.setFirstName(firstName);
        borrower.setLastName(lastName);
        borrower.setMiddleInitial("R");
        borrower.setEmploymentStatus("EMPLOYED");
        return borrower;
    }
}
