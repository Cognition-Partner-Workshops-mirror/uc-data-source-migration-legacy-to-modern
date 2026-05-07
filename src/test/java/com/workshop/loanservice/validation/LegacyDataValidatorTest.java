package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.DataQualityWarning.Severity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.ArrayList;
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
    // ANM-003: Numeric string parsing with error handling
    // =========================================================================

    @Nested
    class NumericParsingTests {

        @Test
        void parseAmount_validAmountWithCommas() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("285,000", "REC-1", "amount", warnings);
            assertEquals(new BigDecimal("285000"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parseAmount_validDecimalWithCommas() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("1,487.02", "REC-1", "amount", warnings);
            assertEquals(new BigDecimal("1487.02"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parseAmount_nullReturnsZero() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount(null, "REC-1", "amount", warnings);
            assertEquals(BigDecimal.ZERO, result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parseAmount_blankReturnsZero() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("   ", "REC-1", "amount", warnings);
            assertEquals(BigDecimal.ZERO, result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parseAmount_invalidStringReturnsZeroWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("$285,000", "REC-1", "amount", warnings);
            assertEquals(BigDecimal.ZERO, result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.CRITICAL, warnings.get(0).getSeverity());
            assertEquals("amount", warnings.get(0).getField());
        }

        @Test
        void parseAmount_textValueReturnsZeroWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("N/A", "REC-1", "amount", warnings);
            assertEquals(BigDecimal.ZERO, result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.CRITICAL, warnings.get(0).getSeverity());
        }

        @Test
        void parseDecimal_validDecimal() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseDecimal("5.250", "REC-1", "rate", warnings);
            assertEquals(new BigDecimal("5.250"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parseDecimal_invalidDecimalReturnsZeroWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseDecimal("5.250%", "REC-1", "rate", warnings);
            assertEquals(BigDecimal.ZERO, result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.CRITICAL, warnings.get(0).getSeverity());
        }

        @Test
        void parseInteger_validInteger() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("745", "REC-1", "score", warnings);
            assertEquals(745, result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parseInteger_nullReturnsNull() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger(null, "REC-1", "score", warnings);
            assertNull(result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parseInteger_invalidStringReturnsNullWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("N/A", "REC-1", "score", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.CRITICAL, warnings.get(0).getSeverity());
        }

        @Test
        void parseInteger_decimalStringReturnsNullWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("7.5", "REC-1", "days", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
        }
    }

    // =========================================================================
    // ANM-007: Date format validation
    // =========================================================================

    @Nested
    class DateValidationTests {

        @Test
        void validateDate_validMMddyyyy() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.validateAndFormatDate("03/15/1978", "REC-1", "dob", warnings);
            assertEquals("1978-03-15", result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void validateDate_nullReturnsNull() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.validateAndFormatDate(null, "REC-1", "dob", warnings);
            assertNull(result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void validateDate_invalidFormatPassesThroughWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.validateAndFormatDate("2025-01-15", "REC-1", "dob", warnings);
            assertEquals("2025-01-15", result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.MEDIUM, warnings.get(0).getSeverity());
        }

        @Test
        void validateDate_garbageDatePassesThroughWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.validateAndFormatDate("UNKNOWN", "REC-1", "dob", warnings);
            assertEquals("UNKNOWN", result);
            assertEquals(1, warnings.size());
        }
    }

    // =========================================================================
    // ANM-004: Null-safe string concatenation
    // =========================================================================

    @Nested
    class NullSafeStringTests {

        @Test
        void buildBorrowerName_bothPresent() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.buildBorrowerName("James", "Mitchell", "LN-001", warnings);
            assertEquals("James Mitchell", result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void buildBorrowerName_nullFirstName() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.buildBorrowerName(null, "Mitchell", "LN-001", warnings);
            assertEquals("Unknown Mitchell", result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.HIGH, warnings.get(0).getSeverity());
            assertEquals("borrowerFirstName", warnings.get(0).getField());
        }

        @Test
        void buildBorrowerName_nullLastName() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.buildBorrowerName("James", null, "LN-001", warnings);
            assertEquals("James Unknown", result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.HIGH, warnings.get(0).getSeverity());
            assertEquals("borrowerLastName", warnings.get(0).getField());
        }

        @Test
        void buildBorrowerName_bothNull() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.buildBorrowerName(null, null, "LN-001", warnings);
            assertEquals("Unknown Unknown", result);
            assertEquals(2, warnings.size());
        }

        @Test
        void buildPropertyAddress_allPresent() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.buildPropertyAddress(
                    "742 Elm Street", "Springfield", "IL", "62701", "LN-001", warnings);
            assertEquals("742 Elm Street, Springfield, IL 62701", result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void buildPropertyAddress_allNull() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.buildPropertyAddress(null, null, null, null, "LN-001", warnings);
            assertEquals("Unknown", result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.HIGH, warnings.get(0).getSeverity());
        }

        @Test
        void safeString_nonBlankReturnsValue() {
            assertEquals("hello", validator.safeString("hello", "fallback"));
        }

        @Test
        void safeString_nullReturnsFallback() {
            assertEquals("fallback", validator.safeString(null, "fallback"));
        }

        @Test
        void safeString_blankReturnsFallback() {
            assertEquals("fallback", validator.safeString("   ", "fallback"));
        }
    }

    // =========================================================================
    // ANM-001: Payment component mismatch
    // =========================================================================

    @Nested
    class PaymentComponentTests {

        @Test
        void validatePaymentComponents_matchingAmounts() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validatePaymentComponents("PMT-001",
                    new BigDecimal("2924.18"),
                    new BigDecimal("1842.56"),
                    new BigDecimal("815.50"),
                    new BigDecimal("266.12"),
                    new BigDecimal("0.00"),
                    warnings);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void validatePaymentComponents_mismatchDetected() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validatePaymentComponents("PMT-2025120001",
                    new BigDecimal("1487.02"),
                    new BigDecimal("456.78"),
                    new BigDecimal("1074.69"),
                    new BigDecimal("355.55"),
                    new BigDecimal("0.00"),
                    warnings);
            assertEquals(1, warnings.size());
            assertEquals(Severity.CRITICAL, warnings.get(0).getSeverity());
            assertEquals("paymentComponents", warnings.get(0).getField());
            assertTrue(warnings.get(0).getMessage().contains("does not match total"));
        }

        @Test
        void validatePaymentComponents_lateFeeNotInTotal() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validatePaymentComponents("PMT-2025110003",
                    new BigDecimal("1077.05"),
                    new BigDecimal("295.82"),
                    new BigDecimal("781.23"),
                    new BigDecimal("0.00"),
                    new BigDecimal("47.50"),
                    warnings);
            assertEquals(1, warnings.size());
            assertEquals(Severity.CRITICAL, warnings.get(0).getSeverity());
        }

        @Test
        void validatePaymentComponents_withinTolerance() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validatePaymentComponents("PMT-001",
                    new BigDecimal("100.00"),
                    new BigDecimal("50.005"),
                    new BigDecimal("49.995"),
                    BigDecimal.ZERO,
                    BigDecimal.ZERO,
                    warnings);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // ANM-002: SSN last-4 vs phone number
    // =========================================================================

    @Nested
    class SsnPhoneTests {

        @Test
        void validateSsnLast4_matchesPhoneLast4_flagged() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateSsnLast4AgainstPhone("0142", "217-555-0142", "LN-001", warnings);
            assertEquals(1, warnings.size());
            assertEquals(Severity.CRITICAL, warnings.get(0).getSeverity());
            assertEquals("borrowerSsnLast4", warnings.get(0).getField());
            assertTrue(warnings.get(0).getMessage().contains("phone number"));
        }

        @Test
        void validateSsnLast4_doesNotMatchPhone_noWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateSsnLast4AgainstPhone("9876", "217-555-0142", "LN-001", warnings);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void validateSsnLast4_nullSsn_noWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateSsnLast4AgainstPhone(null, "217-555-0142", "LN-001", warnings);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void validateSsnLast4_nullPhone_noWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateSsnLast4AgainstPhone("0142", null, "LN-001", warnings);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // Status code validation
    // =========================================================================

    @Nested
    class StatusCodeTests {

        @Test
        void validateStatusCode_validCode() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Set<String> valid = Set.of("ACT", "CLO", "DFT", "FRB");
            String result = validator.validateStatusCode("ACT", valid, "REC-1", "status", warnings);
            assertEquals("ACT", result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void validateStatusCode_invalidCode() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Set<String> valid = Set.of("ACT", "CLO", "DFT", "FRB");
            String result = validator.validateStatusCode("XYZ", valid, "REC-1", "status", warnings);
            assertEquals("XYZ", result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.MEDIUM, warnings.get(0).getSeverity());
        }

        @Test
        void validateStatusCode_nullCode() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Set<String> valid = Set.of("ACT", "CLO");
            String result = validator.validateStatusCode(null, valid, "REC-1", "status", warnings);
            assertNull(result);
            assertEquals(1, warnings.size());
            assertEquals(Severity.HIGH, warnings.get(0).getSeverity());
        }
    }

    // =========================================================================
    // ANM-005: Referential integrity (orphaned records)
    // =========================================================================

    @Nested
    class ReferentialIntegrityTests {

        @Test
        void validateBorrowerExists_exists_noWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateBorrowerExists("B-10001", true, "LN-001", warnings);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void validateBorrowerExists_notExists_warning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateBorrowerExists("B-99999", false, "LN-001", warnings);
            assertEquals(1, warnings.size());
            assertEquals(Severity.HIGH, warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("Orphaned"));
        }

        @Test
        void validateProductExists_notExists_warning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateProductExists("INVALID", false, "LN-001", warnings);
            assertEquals(1, warnings.size());
            assertEquals(Severity.HIGH, warnings.get(0).getSeverity());
        }

        @Test
        void validateLoanAccountExists_notExists_warning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateLoanAccountExists("LN-INVALID", false, "PMT-001", warnings);
            assertEquals(1, warnings.size());
            assertEquals(Severity.HIGH, warnings.get(0).getSeverity());
        }
    }

    // =========================================================================
    // ANM-009: Denormalized data drift
    // =========================================================================

    @Nested
    class DenormalizedDataTests {

        @Test
        void validateDenormalizedName_matching_noWarning() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-001");
            acct.setBorrowerFirstName("James");
            acct.setBorrowerLastName("Mitchell");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setFirstName("James");
            borrower.setLastName("Mitchell");

            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateDenormalizedBorrowerName(acct, borrower, warnings);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void validateDenormalizedName_lastNameDrift_warning() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-001");
            acct.setBorrowerFirstName("Sarah");
            acct.setBorrowerLastName("Chen");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setFirstName("Sarah");
            borrower.setLastName("Chen-Williams");

            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateDenormalizedBorrowerName(acct, borrower, warnings);
            assertEquals(1, warnings.size());
            assertEquals(Severity.MEDIUM, warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("differs from master"));
        }

        @Test
        void validateDenormalizedName_nullBorrower_noWarning() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-001");

            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateDenormalizedBorrowerName(acct, null, warnings);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // ANM-010: Late fee consistency
    // =========================================================================

    @Nested
    class LateFeeTests {

        @Test
        void validateLateFee_latePaymentWithNoFee_warning() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-001");
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/05/2025");
            pmt.setLateFee("0.00");

            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateLateFeeConsistency(pmt, warnings);
            assertEquals(1, warnings.size());
            assertEquals(Severity.LOW, warnings.get(0).getSeverity());
            assertTrue(warnings.get(0).getMessage().contains("days late"));
        }

        @Test
        void validateLateFee_latePaymentWithFee_noWarning() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-001");
            pmt.setPaymentDate("11/01/2025");
            pmt.setReceivedDate("11/18/2025");
            pmt.setLateFee("47.50");

            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateLateFeeConsistency(pmt, warnings);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void validateLateFee_onTimePayment_noWarning() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-001");
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("11/30/2025");
            pmt.setLateFee("0.00");

            List<DataQualityWarning> warnings = new ArrayList<>();
            validator.validateLateFeeConsistency(pmt, warnings);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // Full entity validation
    // =========================================================================

    @Nested
    class EntityValidationTests {

        @Test
        void validateBorrower_validRecord_noHighSeverityWarnings() {
            LegacyBorrower borrower = createValidBorrower();
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
            long criticalOrHigh = warnings.stream()
                    .filter(w -> w.getSeverity() == Severity.CRITICAL || w.getSeverity() == Severity.HIGH)
                    .count();
            assertEquals(0, criticalOrHigh);
        }

        @Test
        void validateBorrower_nullRequiredFields_highWarnings() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-TEST");
            // firstName, lastName, ssnEncrypted all null
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
            long highWarnings = warnings.stream()
                    .filter(w -> w.getSeverity() == Severity.HIGH)
                    .count();
            assertTrue(highWarnings >= 3, "Expected at least 3 HIGH warnings for null required fields");
        }

        @Test
        void validateBorrower_invalidCreditScore_warning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("900");
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(
                    w -> w.getField().equals("creditScore") && w.getSeverity() == Severity.MEDIUM));
        }

        @Test
        void validateBorrower_unparseableCreditScore_criticalWarning() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("GOOD");
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(
                    w -> w.getField().equals("creditScore") && w.getSeverity() == Severity.CRITICAL));
        }

        @Test
        void validateLoanAccount_validRecord() {
            LegacyLoanAccount acct = createValidLoanAccount();
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);
            long criticalOrHigh = warnings.stream()
                    .filter(w -> w.getSeverity() == Severity.CRITICAL || w.getSeverity() == Severity.HIGH)
                    .count();
            assertEquals(0, criticalOrHigh);
        }

        @Test
        void validateLoanAccount_nullBorrowerIdAndProductCode() {
            LegacyLoanAccount acct = createValidLoanAccount();
            acct.setBorrowerId(null);
            acct.setProductCode(null);
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);
            long highWarnings = warnings.stream()
                    .filter(w -> w.getSeverity() == Severity.HIGH)
                    .count();
            assertTrue(highWarnings >= 2);
        }

        @Test
        void validatePayment_validRecord() {
            LegacyPayment pmt = createValidPayment();
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            long criticalOrHigh = warnings.stream()
                    .filter(w -> w.getSeverity() == Severity.CRITICAL || w.getSeverity() == Severity.HIGH)
                    .count();
            assertEquals(0, criticalOrHigh);
        }

        @Test
        void validatePayment_componentMismatch() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(
                    w -> w.getField().equals("paymentComponents") && w.getSeverity() == Severity.CRITICAL));
        }

        @Test
        void validatePayment_nullLoanAccountNumber() {
            LegacyPayment pmt = createValidPayment();
            pmt.setLoanAccountNumber(null);
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(
                    w -> w.getField().equals("loanAccountNumber") && w.getSeverity() == Severity.HIGH));
        }
    }

    // =========================================================================
    // Test helpers
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
