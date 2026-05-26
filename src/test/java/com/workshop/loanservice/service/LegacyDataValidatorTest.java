package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.service.ValidationResult.Severity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for {@link LegacyDataValidator} covering each anomaly type
 * documented in docs/DATA_ANOMALY_REPORT.md.
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANM-001: SSN Last-4 populated from phone numbers
    // =========================================================================

    @Nested
    class SsnPhoneCorrelation {

        @Test
        void detectsSsnMatchingPhoneLast4() {
            // Simulate the known data corruption: SSN last-4 = phone last-4
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setBorrowerSsnLast4("0142");

            LegacyBorrower borrower = buildBorrower();
            borrower.setPhoneNumber("217-555-0142");

            ValidationResult result = validator.validateLoanAccount(acct, borrower);

            assertTrue(result.hasErrors(), "Should flag SSN-phone correlation as error");
            assertTrue(result.getFindings().stream()
                            .anyMatch(f -> f.anomalyId().equals("ANM-001")
                                    && f.severity() == Severity.CRITICAL),
                    "Should have a CRITICAL ANM-001 finding");
        }

        @Test
        void acceptsSsnNotMatchingPhoneLast4() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setBorrowerSsnLast4("9999");

            LegacyBorrower borrower = buildBorrower();
            borrower.setPhoneNumber("217-555-0142");

            ValidationResult result = validator.validateLoanAccount(acct, borrower);

            assertTrue(result.getFindings().stream()
                    .noneMatch(f -> f.anomalyId().equals("ANM-001")),
                    "Should not flag ANM-001 when SSN differs from phone");
        }
    }

    // =========================================================================
    // ANM-002: Payment component sum mismatch
    // =========================================================================

    @Nested
    class PaymentComponentSum {

        @Test
        void detectsComponentSumExceedingTotal() {
            // Reproduces PMT-2025120001: total=1487.02 but components sum to 1887.02
            LegacyPayment pmt = buildPayment();
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");

            ValidationResult result = validator.validatePayment(pmt);

            assertTrue(result.hasErrors(), "Should flag component-sum mismatch");
            assertTrue(result.getFindings().stream()
                            .anyMatch(f -> f.anomalyId().equals("ANM-002")
                                    && f.severity() == Severity.CRITICAL),
                    "Should have a CRITICAL ANM-002 finding");
        }

        @Test
        void detectsLateFeeExcludedFromTotal() {
            // Reproduces PMT-2025110003: late fee not included in total
            LegacyPayment pmt = buildPayment();
            pmt.setTotalAmount("1,077.05");
            pmt.setPrincipalAmount("295.82");
            pmt.setInterestAmount("781.23");
            pmt.setEscrowAmount("0.00");
            pmt.setLateFee("47.50");

            ValidationResult result = validator.validatePayment(pmt);

            assertTrue(result.hasErrors(), "Should flag late-fee exclusion mismatch");
            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-002")),
                    "Should have an ANM-002 finding");
        }

        @Test
        void acceptsCorrectComponentSum() {
            // PMT-2025120002: components sum correctly
            LegacyPayment pmt = buildPayment();
            pmt.setTotalAmount("2,924.18");
            pmt.setPrincipalAmount("1,842.56");
            pmt.setInterestAmount("815.50");
            pmt.setEscrowAmount("266.12");
            pmt.setLateFee("0.00");

            ValidationResult result = validator.validatePayment(pmt);

            assertTrue(result.getFindings().stream()
                    .noneMatch(f -> f.anomalyId().equals("ANM-002")),
                    "Should not flag ANM-002 when components sum correctly");
        }
    }

    // =========================================================================
    // ANM-003: Null values in required fields
    // =========================================================================

    @Nested
    class NullRequiredFields {

        @Test
        void detectsNullBorrowerFirstName() {
            LegacyBorrower b = buildBorrower();
            b.setFirstName(null);

            ValidationResult result = validator.validateBorrower(b);

            assertTrue(result.hasErrors());
            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-003")
                            && f.message().contains("first name")));
        }

        @Test
        void detectsNullBorrowerLastName() {
            LegacyBorrower b = buildBorrower();
            b.setLastName(null);

            ValidationResult result = validator.validateBorrower(b);

            assertTrue(result.hasErrors());
            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-003")
                            && f.message().contains("last name")));
        }

        @Test
        void detectsNullLoanOriginalAmount() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setOriginalAmount(null);

            ValidationResult result = validator.validateLoanAccount(acct, buildBorrower());

            assertTrue(result.hasErrors());
            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-003")
                            && f.message().contains("original amount")));
        }

        @Test
        void detectsNullPaymentTotal() {
            LegacyPayment pmt = buildPayment();
            pmt.setTotalAmount(null);

            ValidationResult result = validator.validatePayment(pmt);

            assertTrue(result.hasErrors());
            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-003")
                            && f.message().contains("total amount")));
        }
    }

    // =========================================================================
    // ANM-004: Numeric values stored as strings with parsing risks
    // =========================================================================

    @Nested
    class NumericParsingRisks {

        @Test
        void detectsNonNumericCreditScore() {
            LegacyBorrower b = buildBorrower();
            b.setCreditScore("N/A");

            ValidationResult result = validator.validateBorrower(b);

            assertTrue(result.hasErrors());
            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-004")
                            && f.message().contains("credit score")));
        }

        @Test
        void detectsNonNumericAnnualIncome() {
            LegacyBorrower b = buildBorrower();
            b.setAnnualIncome("$92,500");

            ValidationResult result = validator.validateBorrower(b);

            assertTrue(result.hasErrors());
            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-004")
                            && f.message().contains("annual income")));
        }

        @Test
        void detectsNonNumericLoanAmount() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setOriginalAmount("TBD");

            ValidationResult result = validator.validateLoanAccount(acct, buildBorrower());

            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-004")
                            && f.message().contains("originalAmount")));
        }

        @Test
        void safeParseAmountHandlesValidInput() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("285,000"));
            assertEquals(new BigDecimal("1487.02"), validator.safeParseAmount("1,487.02"));
        }

        @Test
        void safeParseAmountHandlesInvalidInput() {
            // Should return ZERO and not throw
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount(null));
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount(""));
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("N/A"));
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("$100"));
        }

        @Test
        void safeParseIntegerHandlesInvalidInput() {
            assertNull(validator.safeParseInteger(null));
            assertNull(validator.safeParseInteger(""));
            assertNull(validator.safeParseInteger("N/A"));
            assertEquals(745, validator.safeParseInteger("745"));
        }

        @Test
        void safeParseDecimalHandlesInvalidInput() {
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal(null));
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal("abc"));
            assertEquals(new BigDecimal("5.250"), validator.safeParseDecimal("5.250"));
        }
    }

    // =========================================================================
    // ANM-005: Orphaned records (no FK constraints)
    // =========================================================================

    @Nested
    class OrphanedRecords {

        @Test
        void detectsOrphanedLoanAccount() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setBorrowerId("B-99999");

            // Pass null borrower to simulate a missing reference
            ValidationResult result = validator.validateLoanAccount(acct, null);

            assertTrue(result.hasErrors());
            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-005")
                            && f.message().contains("B-99999")));
        }
    }

    // =========================================================================
    // ANM-006: Delinquency days inconsistent with loan status
    // =========================================================================

    @Nested
    class DelinquencyStatusInconsistency {

        @Test
        void detectsDelinquentDaysWithActiveStatus() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setDelinquencyDays("15");
            acct.setStatusCode("ACT");

            ValidationResult result = validator.validateLoanAccount(acct, buildBorrower());

            assertTrue(result.hasErrors());
            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-006")
                            && f.message().contains("15 delinquency days")));
        }

        @Test
        void acceptsZeroDelinquencyWithActiveStatus() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setDelinquencyDays("0");
            acct.setStatusCode("ACT");

            ValidationResult result = validator.validateLoanAccount(acct, buildBorrower());

            assertTrue(result.getFindings().stream()
                    .noneMatch(f -> f.anomalyId().equals("ANM-006")),
                    "Should not flag ANM-006 when delinquency is 0");
        }
    }

    // =========================================================================
    // ANM-007: Date format validation
    // =========================================================================

    @Nested
    class DateFormatValidation {

        @Test
        void detectsInvalidDateFormat() {
            LegacyBorrower b = buildBorrower();
            b.setDateOfBirth("1978-03-15");  // ISO format instead of MM/DD/YYYY

            ValidationResult result = validator.validateBorrower(b);

            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-007")
                            && f.message().contains("dateOfBirth")));
        }

        @Test
        void detectsGarbageDateString() {
            LegacyBorrower b = buildBorrower();
            b.setDateOfBirth("TBD");

            ValidationResult result = validator.validateBorrower(b);

            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-007")));
        }

        @Test
        void acceptsValidLegacyDate() {
            LegacyBorrower b = buildBorrower();
            b.setDateOfBirth("03/15/1978");

            ValidationResult result = validator.validateBorrower(b);

            assertTrue(result.getFindings().stream()
                    .noneMatch(f -> f.anomalyId().equals("ANM-007")
                            && f.message().contains("dateOfBirth")),
                    "Should not flag valid MM/DD/YYYY date");
        }

        @Test
        void safeParseDateHandlesValidAndInvalidInput() {
            assertNotNull(validator.safeParseDate("03/15/1978"));
            assertNull(validator.safeParseDate(null));
            assertNull(validator.safeParseDate(""));
            assertNull(validator.safeParseDate("TBD"));
            assertNull(validator.safeParseDate("13/32/2025"));
        }
    }

    // =========================================================================
    // ANM-008: Denormalized data drift
    // =========================================================================

    @Nested
    class DenormalizedDataDrift {

        @Test
        void detectsFirstNameMismatch() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setBorrowerFirstName("Jim");  // master has "James"

            LegacyBorrower borrower = buildBorrower();
            borrower.setFirstName("James");

            ValidationResult result = validator.validateLoanAccount(acct, borrower);

            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-008")
                            && f.message().contains("first name")));
        }

        @Test
        void acceptsMatchingDenormalizedNames() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setBorrowerFirstName("James");
            acct.setBorrowerLastName("Mitchell");

            LegacyBorrower borrower = buildBorrower();
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");

            ValidationResult result = validator.validateLoanAccount(acct, borrower);

            assertTrue(result.getFindings().stream()
                    .noneMatch(f -> f.anomalyId().equals("ANM-008")),
                    "Should not flag ANM-008 when names match");
        }
    }

    // =========================================================================
    // ANM-009: Unvalidated status codes
    // =========================================================================

    @Nested
    class StatusCodeValidation {

        @Test
        void detectsUnrecognizedLoanStatus() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setStatusCode("XYZ");

            ValidationResult result = validator.validateLoanAccount(acct, buildBorrower());

            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-009")
                            && f.message().contains("XYZ")));
        }

        @Test
        void detectsUnrecognizedPaymentType() {
            LegacyPayment pmt = buildPayment();
            pmt.setTypeCode("BAD");

            ValidationResult result = validator.validatePayment(pmt);

            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-009")
                            && f.message().contains("BAD")));
        }

        @Test
        void detectsUnrecognizedPaymentStatus() {
            LegacyPayment pmt = buildPayment();
            pmt.setStatusCode("FOO");

            ValidationResult result = validator.validatePayment(pmt);

            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-009")
                            && f.message().contains("FOO")));
        }

        @Test
        void detectsUnrecognizedBorrowerStatus() {
            LegacyBorrower b = buildBorrower();
            b.setStatusCode("DEL");

            ValidationResult result = validator.validateBorrower(b);

            assertTrue(result.getFindings().stream()
                    .anyMatch(f -> f.anomalyId().equals("ANM-009")
                            && f.message().contains("DEL")));
        }

        @Test
        void acceptsValidStatusCodes() {
            LegacyLoanAccount acct = buildLoanAccount();
            acct.setStatusCode("ACT");

            // Zero delinquency days so ANM-006 is not triggered
            acct.setDelinquencyDays("0");

            ValidationResult result = validator.validateLoanAccount(acct, buildBorrower());

            assertTrue(result.getFindings().stream()
                    .noneMatch(f -> f.anomalyId().equals("ANM-009")
                            && f.message().contains("status")),
                    "Should not flag valid status codes");
        }
    }

    // =========================================================================
    // Safe string helper (ANM-003 prevention)
    // =========================================================================

    @Nested
    class SafeStringHelper {

        @Test
        void returnsValueWhenNonBlank() {
            assertEquals("James", validator.safeString("James", "[Unknown]"));
        }

        @Test
        void returnsFallbackWhenNull() {
            assertEquals("[Unknown]", validator.safeString(null, "[Unknown]"));
        }

        @Test
        void returnsFallbackWhenBlank() {
            assertEquals("[Unknown]", validator.safeString("  ", "[Unknown]"));
        }
    }

    // =========================================================================
    // Test fixtures
    // =========================================================================

    /** Builds a valid borrower record for baseline testing. */
    private LegacyBorrower buildBorrower() {
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

    /** Builds a valid loan account record for baseline testing. */
    private LegacyLoanAccount buildLoanAccount() {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber("LN-2019-00142");
        acct.setBorrowerId("B-10001");
        acct.setBorrowerFirstName("James");
        acct.setBorrowerLastName("Mitchell");
        acct.setBorrowerSsnLast4("9999"); // non-matching default
        acct.setProductCode("FXD30");
        acct.setOriginalAmount("285,000");
        acct.setCurrentBalance("271,432.56");
        acct.setInterestRate("4.750");
        acct.setTermMonths("360");
        acct.setMonthlyPayment("1,487.02");
        acct.setOriginationDate("02/15/2019");
        acct.setMaturityDate("02/15/2049");
        acct.setFirstPaymentDate("03/15/2019");
        acct.setNextPaymentDate("01/15/2026");
        acct.setStatusCode("ACT");
        acct.setDelinquencyDays("0");
        acct.setEscrowBalance("3,245.80");
        acct.setLtvPercent("82.5");
        acct.setPropertyAddress("742 Elm Street");
        acct.setPropertyCity("Springfield");
        acct.setPropertyState("IL");
        acct.setPropertyZip("62701");
        acct.setPropertyType("SFR");
        acct.setAppraisedValue("345,000");
        acct.setCreatedDate("02/01/2019");
        acct.setUpdatedDate("12/01/2025");
        return acct;
    }

    /** Builds a valid payment record for baseline testing. */
    private LegacyPayment buildPayment() {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber("PMT-TEST-001");
        pmt.setLoanAccountNumber("LN-2019-00142");
        pmt.setPaymentDate("12/15/2025");
        pmt.setTotalAmount("1,487.02");
        pmt.setPrincipalAmount("456.78");
        pmt.setInterestAmount("1,030.24");
        pmt.setEscrowAmount("0.00");
        pmt.setLateFee("0.00");
        pmt.setTypeCode("REG");
        pmt.setStatusCode("PST");
        pmt.setReceivedDate("12/14/2025");
        pmt.setProcessedDate("12/15/2025");
        pmt.setCreatedDate("12/15/2025");
        pmt.setUpdatedDate("12/15/2025");
        return pmt;
    }
}
