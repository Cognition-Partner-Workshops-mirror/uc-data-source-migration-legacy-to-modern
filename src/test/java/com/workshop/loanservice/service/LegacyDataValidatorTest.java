package com.workshop.loanservice.service;

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
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANO-003: Numeric Parsing with Error Handling
    // =========================================================================

    @Nested
    @DisplayName("ANO-003: parseLegacyAmount")
    class ParseLegacyAmountTests {

        @Test
        void parsesCommaFormattedAmount() {
            assertEquals(new BigDecimal("285000"), validator.parseLegacyAmount("285,000", "TEST", "field"));
        }

        @Test
        void parsesDecimalAmount() {
            assertEquals(new BigDecimal("1487.02"), validator.parseLegacyAmount("1,487.02", "TEST", "field"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyAmount(null, "TEST", "field"));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyAmount("  ", "TEST", "field"));
        }

        @Test
        void handlesCorruptDollarSign() {
            assertEquals(new BigDecimal("285000"), validator.parseLegacyAmount("$285,000", "TEST", "field"));
        }

        @Test
        void handlesCorruptTextGracefully() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyAmount("N/A", "TEST", "field"));
        }

        @Test
        void handlesCorruptMainframeTrailingSign() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyAmount("1234.56-", "TEST", "field"));
        }

        @Test
        void handlesEmptyString() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyAmount("", "TEST", "field"));
        }
    }

    @Nested
    @DisplayName("ANO-003: parseLegacyDecimal")
    class ParseLegacyDecimalTests {

        @Test
        void parsesInterestRate() {
            assertEquals(new BigDecimal("4.750"), validator.parseLegacyDecimal("4.750", "TEST", "field"));
        }

        @Test
        void handlesWhitespace() {
            assertEquals(new BigDecimal("3.125"), validator.parseLegacyDecimal("  3.125  ", "TEST", "field"));
        }

        @Test
        void handlesCorruptTextGracefully() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyDecimal("VARIABLE", "TEST", "field"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.parseLegacyDecimal(null, "TEST", "field"));
        }
    }

    @Nested
    @DisplayName("ANO-003: parseLegacyInteger")
    class ParseLegacyIntegerTests {

        @Test
        void parsesCreditScore() {
            assertEquals(745, validator.parseLegacyInteger("745", "TEST", "field"));
        }

        @Test
        void handlesWhitespace() {
            assertEquals(780, validator.parseLegacyInteger("  780  ", "TEST", "field"));
        }

        @Test
        void handlesCorruptTextGracefully() {
            assertNull(validator.parseLegacyInteger("N/A", "TEST", "field"));
        }

        @Test
        void handlesDecimalStringGracefully() {
            assertNull(validator.parseLegacyInteger("745.0", "TEST", "field"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseLegacyInteger(null, "TEST", "field"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseLegacyInteger("", "TEST", "field"));
        }
    }

    // =========================================================================
    // ANO-006: Date Validation
    // =========================================================================

    @Nested
    @DisplayName("ANO-006: parseLegacyDate")
    class ParseLegacyDateTests {

        @Test
        void parsesValidDate() {
            assertEquals(LocalDate.of(2025, 12, 15), validator.parseLegacyDate("12/15/2025", "TEST", "field"));
        }

        @Test
        void parsesLeapYearDate() {
            assertEquals(LocalDate.of(2024, 2, 29), validator.parseLegacyDate("02/29/2024", "TEST", "field"));
        }

        @Test
        void rejectsInvalidMonth() {
            assertNull(validator.parseLegacyDate("13/01/2025", "TEST", "field"));
        }

        @Test
        void rejectsInvalidDay() {
            assertNull(validator.parseLegacyDate("02/30/2025", "TEST", "field"));
        }

        @Test
        void rejectsNonLeapYear() {
            assertNull(validator.parseLegacyDate("02/29/2023", "TEST", "field"));
        }

        @Test
        void rejectsGarbageDate() {
            assertNull(validator.parseLegacyDate("00/00/0000", "TEST", "field"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.parseLegacyDate(null, "TEST", "field"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.parseLegacyDate("", "TEST", "field"));
        }
    }

    // =========================================================================
    // ANO-007: Null-Safe Name Handling
    // =========================================================================

    @Nested
    @DisplayName("ANO-007: safeFullName")
    class SafeFullNameTests {

        @Test
        void concatenatesNormally() {
            assertEquals("James Mitchell", validator.safeFullName("James", "Mitchell"));
        }

        @Test
        void handlesNullFirstName() {
            assertEquals("Unknown Mitchell", validator.safeFullName(null, "Mitchell"));
        }

        @Test
        void handlesNullLastName() {
            assertEquals("James Unknown", validator.safeFullName("James", null));
        }

        @Test
        void handlesBothNull() {
            assertEquals("Unknown Unknown", validator.safeFullName(null, null));
        }
    }

    @Nested
    @DisplayName("ANO-007: safeFullNameWithMiddle")
    class SafeFullNameWithMiddleTests {

        @Test
        void includesMiddleInitial() {
            assertEquals("James R. Mitchell",
                    validator.safeFullNameWithMiddle("James", "R", "Mitchell"));
        }

        @Test
        void omitsNullMiddleInitial() {
            assertEquals("Robert Williams",
                    validator.safeFullNameWithMiddle("Robert", null, "Williams"));
        }

        @Test
        void handlesAllNull() {
            assertEquals("Unknown Unknown",
                    validator.safeFullNameWithMiddle(null, null, null));
        }
    }

    // =========================================================================
    // ANO-001: SSN/Phone Correlation
    // =========================================================================

    @Nested
    @DisplayName("ANO-001: isSsnPhoneCorrelated")
    class SsnPhoneCorrelationTests {

        @Test
        void detectsMatchingLast4() {
            assertTrue(validator.isSsnPhoneCorrelated("0142", "217-555-0142"));
        }

        @Test
        void rejectsNonMatchingLast4() {
            assertFalse(validator.isSsnPhoneCorrelated("9999", "217-555-0142"));
        }

        @Test
        void handlesNullSsn() {
            assertFalse(validator.isSsnPhoneCorrelated(null, "217-555-0142"));
        }

        @Test
        void handlesNullPhone() {
            assertFalse(validator.isSsnPhoneCorrelated("0142", null));
        }
    }

    // =========================================================================
    // ANO-004: Orphaned Record Detection
    // =========================================================================

    @Nested
    @DisplayName("ANO-004: Orphaned Record Detection")
    class OrphanedRecordTests {

        @Test
        void detectsOrphanedLoan() {
            Set<String> validBorrowerIds = Set.of("B-10001", "B-10002");
            assertTrue(validator.isOrphanedLoan("B-99999", validBorrowerIds));
        }

        @Test
        void acceptsValidLoan() {
            Set<String> validBorrowerIds = Set.of("B-10001", "B-10002");
            assertFalse(validator.isOrphanedLoan("B-10001", validBorrowerIds));
        }

        @Test
        void detectsNullBorrowerId() {
            assertTrue(validator.isOrphanedLoan(null, Set.of("B-10001")));
        }

        @Test
        void detectsOrphanedProduct() {
            Set<String> validProductCodes = Set.of("FXD30", "FXD15");
            assertTrue(validator.isOrphanedProduct("UNKNOWN", validProductCodes));
        }

        @Test
        void detectsOrphanedPayment() {
            Set<String> validLoanNumbers = Set.of("LN-2019-00142");
            assertTrue(validator.isOrphanedPayment("LN-GHOST-999", validLoanNumbers));
        }
    }

    // =========================================================================
    // ANO-002: Payment Component Sum Validation
    // =========================================================================

    @Nested
    @DisplayName("ANO-002: Payment Validation")
    class PaymentValidationTests {

        @Test
        void detectsComponentSumMismatch() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-TEST-001");
            pmt.setLoanAccountNumber("LN-TEST");
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("PST");
            pmt.setPaymentDate("12/15/2025");
            pmt.setReceivedDate("12/14/2025");
            pmt.setProcessedDate("12/15/2025");

            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-002")),
                    "Should detect component sum mismatch");
        }

        @Test
        void acceptsBalancedPayment() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-TEST-002");
            pmt.setLoanAccountNumber("LN-TEST");
            pmt.setTotalAmount("2,924.18");
            pmt.setPrincipalAmount("1,842.56");
            pmt.setInterestAmount("815.50");
            pmt.setEscrowAmount("266.12");
            pmt.setLateFee("0.00");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("PST");
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("11/30/2025");
            pmt.setProcessedDate("12/01/2025");

            List<String> warnings = validator.validatePayment(pmt);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("ANO-002")),
                    "Balanced payment should not trigger ANO-002");
        }

        @Test
        void detectsLateFeeNotInTotal() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-TEST-003");
            pmt.setLoanAccountNumber("LN-TEST");
            pmt.setTotalAmount("1,077.05");
            pmt.setPrincipalAmount("295.82");
            pmt.setInterestAmount("781.23");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("47.50");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("PST");
            pmt.setPaymentDate("11/01/2025");
            pmt.setReceivedDate("11/18/2025");
            pmt.setProcessedDate("11/19/2025");

            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-002")),
                    "Should detect late fee not included in total");
        }

        @Test
        void detectsInvalidPaymentType() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-TEST-004");
            pmt.setLoanAccountNumber("LN-TEST");
            pmt.setTotalAmount("100.00");
            pmt.setPrincipalAmount("50.00");
            pmt.setInterestAmount("50.00");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("0.00");
            pmt.setTypeCode("XYZ");
            pmt.setStatusCode("PST");
            pmt.setPaymentDate("01/01/2025");
            pmt.setReceivedDate("01/01/2025");
            pmt.setProcessedDate("01/01/2025");

            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-009")),
                    "Should detect unrecognized payment type");
        }

        @Test
        void detectsInvalidPaymentStatus() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-TEST-005");
            pmt.setLoanAccountNumber("LN-TEST");
            pmt.setTotalAmount("100.00");
            pmt.setPrincipalAmount("50.00");
            pmt.setInterestAmount("50.00");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("0.00");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("BAD");
            pmt.setPaymentDate("01/01/2025");
            pmt.setReceivedDate("01/01/2025");
            pmt.setProcessedDate("01/01/2025");

            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-009")),
                    "Should detect unrecognized payment status");
        }
    }

    // =========================================================================
    // ANO-005: Delinquency / Status Inconsistency
    // =========================================================================

    @Nested
    @DisplayName("ANO-005: Loan Account Validation")
    class LoanAccountValidationTests {

        @Test
        void detectsActiveWithDelinquency() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST-001");
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("15");
            acct.setPropertyType("SFR");
            acct.setOriginationDate("07/01/2018");
            acct.setMaturityDate("07/01/2048");
            acct.setFirstPaymentDate("08/01/2018");
            acct.setNextPaymentDate("01/01/2026");
            acct.setCreatedDate("06/15/2018");
            acct.setUpdatedDate("12/01/2025");
            acct.setBorrowerFirstName("Test");
            acct.setBorrowerLastName("User");

            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-005")),
                    "Should detect active loan with delinquency days");
        }

        @Test
        void acceptsActiveWithZeroDelinquency() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST-002");
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("0");
            acct.setPropertyType("SFR");
            acct.setOriginationDate("02/15/2019");
            acct.setMaturityDate("02/15/2049");
            acct.setFirstPaymentDate("03/15/2019");
            acct.setNextPaymentDate("01/15/2026");
            acct.setCreatedDate("02/01/2019");
            acct.setUpdatedDate("12/01/2025");
            acct.setBorrowerFirstName("Test");
            acct.setBorrowerLastName("User");

            List<String> warnings = validator.validateLoanAccount(acct);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("ANO-005")),
                    "Active loan with zero delinquency should be fine");
        }

        @Test
        void detectsInvalidLoanStatus() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST-003");
            acct.setStatusCode("XYZ");
            acct.setDelinquencyDays("0");
            acct.setPropertyType("SFR");
            acct.setOriginationDate("01/01/2020");
            acct.setMaturityDate("01/01/2050");
            acct.setFirstPaymentDate("02/01/2020");
            acct.setNextPaymentDate("01/01/2026");
            acct.setCreatedDate("01/01/2020");
            acct.setUpdatedDate("12/01/2025");
            acct.setBorrowerFirstName("Test");
            acct.setBorrowerLastName("User");

            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-009")),
                    "Should detect unrecognized loan status");
        }

        @Test
        void detectsInvalidPropertyType() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST-004");
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("0");
            acct.setPropertyType("ZZZ");
            acct.setOriginationDate("01/01/2020");
            acct.setMaturityDate("01/01/2050");
            acct.setFirstPaymentDate("02/01/2020");
            acct.setNextPaymentDate("01/01/2026");
            acct.setCreatedDate("01/01/2020");
            acct.setUpdatedDate("12/01/2025");
            acct.setBorrowerFirstName("Test");
            acct.setBorrowerLastName("User");

            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-009")),
                    "Should detect unrecognized property type");
        }

        @Test
        void detectsNullBorrowerNameInLoanRecord() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST-005");
            acct.setStatusCode("ACT");
            acct.setDelinquencyDays("0");
            acct.setPropertyType("SFR");
            acct.setOriginationDate("01/01/2020");
            acct.setMaturityDate("01/01/2050");
            acct.setFirstPaymentDate("02/01/2020");
            acct.setNextPaymentDate("01/01/2026");
            acct.setCreatedDate("01/01/2020");
            acct.setUpdatedDate("12/01/2025");
            acct.setBorrowerFirstName(null);
            acct.setBorrowerLastName(null);

            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-007")),
                    "Should detect null borrower name in denormalized loan record");
        }
    }

    // =========================================================================
    // ANO-009: Borrower Validation
    // =========================================================================

    @Nested
    @DisplayName("ANO-009: Borrower Validation")
    class BorrowerValidationTests {

        @Test
        void detectsNullFirstName() {
            LegacyBorrower borrower = createBorrower("B-TEST-001", null, "Smith", "ACT");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-007")),
                    "Should detect null first name");
        }

        @Test
        void detectsNullLastName() {
            LegacyBorrower borrower = createBorrower("B-TEST-002", "John", null, "ACT");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-007")),
                    "Should detect null last name");
        }

        @Test
        void detectsInvalidBorrowerStatus() {
            LegacyBorrower borrower = createBorrower("B-TEST-003", "John", "Smith", "XYZ");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-009")),
                    "Should detect unrecognized borrower status");
        }

        @Test
        void acceptsValidBorrower() {
            LegacyBorrower borrower = createBorrower("B-TEST-004", "John", "Smith", "ACT");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.isEmpty(), "Valid borrower should have no warnings");
        }

        @Test
        void detectsOutOfRangeCreditScore() {
            LegacyBorrower borrower = createBorrower("B-TEST-005", "John", "Smith", "ACT");
            borrower.setCreditScore("200");

            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-003") && w.contains("Credit score")),
                    "Should detect out-of-range credit score");
        }

        private LegacyBorrower createBorrower(String id, String firstName, String lastName, String status) {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId(id);
            borrower.setFirstName(firstName);
            borrower.setLastName(lastName);
            borrower.setStatusCode(status);
            borrower.setCreditScore("750");
            borrower.setDateOfBirth("01/15/1980");
            borrower.setCreatedDate("01/01/2020");
            borrower.setUpdatedDate("12/01/2025");
            return borrower;
        }
    }

    // =========================================================================
    // ANO-008: Denormalized Data Drift
    // =========================================================================

    @Nested
    @DisplayName("ANO-008: Denormalized Drift Detection")
    class DenormalizedDriftTests {

        @Test
        void detectsFirstNameDrift() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-DRIFT-001");
            acct.setBorrowerFirstName("Jim");
            acct.setBorrowerLastName("Mitchell");
            acct.setBorrowerSsnLast4("1234");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-10001");
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");
            borrower.setPhoneNumber("217-555-0000");

            List<String> warnings = validator.checkDenormalizedDrift(acct, borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-008") && w.contains("First name")),
                    "Should detect first name drift");
        }

        @Test
        void detectsLastNameDrift() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-DRIFT-002");
            acct.setBorrowerFirstName("Sarah");
            acct.setBorrowerLastName("Chen-Williams");
            acct.setBorrowerSsnLast4("1234");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-10002");
            borrower.setFirstName("Sarah");
            borrower.setLastName("Chen");
            borrower.setPhoneNumber("503-555-0000");

            List<String> warnings = validator.checkDenormalizedDrift(acct, borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-008") && w.contains("Last name")),
                    "Should detect last name drift");
        }

        @Test
        void detectsSsnPhoneCorrelation() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-SSN-001");
            acct.setBorrowerFirstName("James");
            acct.setBorrowerLastName("Mitchell");
            acct.setBorrowerSsnLast4("0142");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-10001");
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");
            borrower.setPhoneNumber("217-555-0142");

            List<String> warnings = validator.checkDenormalizedDrift(acct, borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-001")),
                    "Should detect SSN last-4 matching phone last-4");
        }

        @Test
        void acceptsConsistentData() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-OK-001");
            acct.setBorrowerFirstName("James");
            acct.setBorrowerLastName("Mitchell");
            acct.setBorrowerSsnLast4("5678");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-10001");
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");
            borrower.setPhoneNumber("217-555-0142");

            List<String> warnings = validator.checkDenormalizedDrift(acct, borrower);
            assertTrue(warnings.isEmpty(), "Consistent data should produce no warnings");
        }
    }
}
