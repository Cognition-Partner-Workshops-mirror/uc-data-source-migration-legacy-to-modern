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

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Amount Parsing Tests (ANO-004, ANO-009)
    // =========================================================================

    @Nested
    class AmountParsingTests {

        @Test
        void parsesCommaFormattedAmount() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("285,000", "TEST-001", "amount", warnings);
            assertEquals(new BigDecimal("285000"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void parsesDecimalAmountWithCommas() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("1,487.02", "TEST-001", "amount", warnings);
            assertEquals(new BigDecimal("1487.02"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesNullAmountWithFallback() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount(null, "TEST-001", "amount", warnings);
            assertEquals(BigDecimal.ZERO, result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesBlankAmountWithFallback() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("  ", "TEST-001", "amount", warnings);
            assertEquals(BigDecimal.ZERO, result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesDollarSignInAmount() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("$92,500", "TEST-001", "income", warnings);
            assertEquals(new BigDecimal("92500"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesPercentSignInRate() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseDecimal("4.750%", "TEST-001", "rate", warnings);
            assertEquals(new BigDecimal("4.750"), result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesNonNumericAmountWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("N/A", "TEST-001", "income", warnings);
            assertEquals(BigDecimal.ZERO, result);
            assertFalse(warnings.isEmpty());
            assertEquals(Severity.HIGH, warnings.get(0).getSeverity());
        }

        @Test
        void handlesCompletelyGarbageInputWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            BigDecimal result = validator.parseAmount("---", "TEST-001", "amount", warnings);
            assertEquals(BigDecimal.ZERO, result);
            assertFalse(warnings.isEmpty());
        }
    }

    // =========================================================================
    // Integer Parsing Tests (ANO-004)
    // =========================================================================

    @Nested
    class IntegerParsingTests {

        @Test
        void parsesValidInteger() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("745", "B-10001", "BORR_CRDT_SCR", warnings);
            assertEquals(745, result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesNullIntegerReturnsNull() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger(null, "B-10001", "BORR_CRDT_SCR", warnings);
            assertNull(result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesNonNumericIntegerWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("N/A", "B-10001", "BORR_CRDT_SCR", warnings);
            assertNull(result);
            assertFalse(warnings.isEmpty());
            assertEquals(Severity.HIGH, warnings.get(0).getSeverity());
        }

        @Test
        void handlesWhitespaceOnlyWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            Integer result = validator.parseInteger("   ", "B-10001", "score", warnings);
            assertNull(result);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // Date Parsing & Format Tests (ANO-006)
    // =========================================================================

    @Nested
    class DateParsingTests {

        @Test
        void parsesValidLegacyDate() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.formatDateToIso("03/15/1978", "B-10001", "DOB", warnings);
            assertEquals("1978-03-15", result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesInvalidDateFormatWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.formatDateToIso("2019-02-15", "LN-001", "date", warnings);
            assertEquals("2019-02-15", result);
            assertFalse(warnings.isEmpty());
            assertTrue(warnings.get(0).getMessage().contains("Unparseable date"));
        }

        @Test
        void handlesEuropeanDateFormatWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.formatDateToIso("15/02/2019", "LN-001", "date", warnings);
            assertFalse(warnings.isEmpty());
        }

        @Test
        void handlesNullDateReturnsNull() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.formatDateToIso(null, "LN-001", "date", warnings);
            assertNull(result);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void handlesGarbageDateWithWarning() {
            List<DataQualityWarning> warnings = new ArrayList<>();
            String result = validator.formatDateToIso("not-a-date", "LN-001", "date", warnings);
            assertEquals("not-a-date", result);
            assertFalse(warnings.isEmpty());
            assertEquals(Severity.MEDIUM, warnings.get(0).getSeverity());
        }
    }

    // =========================================================================
    // Null-Safe String Tests (ANO-005)
    // =========================================================================

    @Nested
    class NullSafeStringTests {

        @Test
        void buildAddressWithAllFieldsPresent() {
            String result = validator.buildAddress("742 Elm Street", "Springfield", "IL", "62701");
            assertEquals("742 Elm Street, Springfield, IL 62701", result);
        }

        @Test
        void buildAddressWithNullCity() {
            String result = validator.buildAddress("742 Elm Street", null, "IL", "62701");
            assertEquals("742 Elm Street, IL 62701", result);
            assertFalse(result.contains("null"));
        }

        @Test
        void buildAddressWithAllNulls() {
            String result = validator.buildAddress(null, null, null, null);
            assertEquals("Unknown", result);
        }

        @Test
        void buildFullNameWithBothPresent() {
            String result = validator.buildFullName("James", "Mitchell");
            assertEquals("James Mitchell", result);
        }

        @Test
        void buildFullNameWithNullFirstName() {
            String result = validator.buildFullName(null, "Mitchell");
            assertEquals("Mitchell", result);
            assertFalse(result.contains("null"));
        }

        @Test
        void buildFullNameWithBothNull() {
            String result = validator.buildFullName(null, null);
            assertEquals("Unknown", result);
        }

        @Test
        void safeStringReturnsValueWhenPresent() {
            assertEquals("hello", validator.safeString("hello", "default"));
        }

        @Test
        void safeStringReturnsFallbackWhenNull() {
            assertEquals("default", validator.safeString(null, "default"));
        }

        @Test
        void safeStringReturnsFallbackWhenBlank() {
            assertEquals("default", validator.safeString("  ", "default"));
        }
    }

    // =========================================================================
    // Payment Component Validation Tests (ANO-001)
    // =========================================================================

    @Nested
    class PaymentValidationTests {

        @Test
        void detectsPaymentComponentMismatch() {
            LegacyPayment pmt = buildPayment("PMT-001", "LN-001",
                    "1,487.02", "456.78", "1,074.69", "355.55", "0.00",
                    "REG", "PST");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);

            boolean hasMismatch = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("components sum")
                            && w.getSeverity() == Severity.CRITICAL);
            assertTrue(hasMismatch, "Should detect payment component sum mismatch");
        }

        @Test
        void acceptsMatchingPaymentComponents() {
            LegacyPayment pmt = buildPayment("PMT-002", "LN-001",
                    "2,924.18", "1,842.56", "815.50", "266.12", "0.00",
                    "REG", "PST");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);

            boolean hasMismatch = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("components sum"));
            assertFalse(hasMismatch, "Should not flag matching components");
        }

        @Test
        void detectsLateFeeNotIncludedInTotal() {
            LegacyPayment pmt = buildPayment("PMT-003", "LN-001",
                    "1,077.05", "295.82", "781.23", "0.00", "47.50",
                    "REG", "PST");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);

            boolean hasMismatch = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("components sum")
                            && w.getSeverity() == Severity.CRITICAL);
            assertTrue(hasMismatch, "Should detect late fee not reflected in total");
        }

        @Test
        void detectsInvalidPaymentType() {
            LegacyPayment pmt = buildPayment("PMT-004", "LN-001",
                    "100.00", "50.00", "50.00", "0.00", "0.00",
                    "XYZ", "PST");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);

            boolean hasInvalidType = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("Unknown payment type"));
            assertTrue(hasInvalidType);
        }

        @Test
        void detectsInvalidPaymentStatus() {
            LegacyPayment pmt = buildPayment("PMT-005", "LN-001",
                    "100.00", "50.00", "50.00", "0.00", "0.00",
                    "REG", "BAD");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);

            boolean hasInvalidStatus = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("Unknown payment status"));
            assertTrue(hasInvalidStatus);
        }

        @Test
        void detectsOrphanedPayment() {
            LegacyPayment pmt = buildPayment("PMT-006", null,
                    "100.00", "50.00", "50.00", "0.00", "0.00",
                    "REG", "PST");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);

            boolean hasOrphan = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("orphaned record")
                            && w.getSeverity() == Severity.CRITICAL);
            assertTrue(hasOrphan);
        }

        private LegacyPayment buildPayment(String seqNbr, String loanAcctNbr,
                                            String total, String principal, String interest,
                                            String escrow, String lateFee,
                                            String typeCode, String statusCode) {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber(seqNbr);
            pmt.setLoanAccountNumber(loanAcctNbr);
            pmt.setTotalAmount(total);
            pmt.setPrincipalAmount(principal);
            pmt.setInterestAmount(interest);
            pmt.setEscrowAmount(escrow);
            pmt.setLateFee(lateFee);
            pmt.setTypeCode(typeCode);
            pmt.setStatusCode(statusCode);
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/01/2025");
            pmt.setProcessedDate("12/01/2025");
            pmt.setCreatedDate("12/01/2025");
            pmt.setUpdatedDate("12/01/2025");
            return pmt;
        }
    }

    // =========================================================================
    // Loan Account Validation Tests (ANO-003, ANO-007)
    // =========================================================================

    @Nested
    class LoanAccountValidationTests {

        @Test
        void detectsDelinquentLoanMarkedActive() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "ACT", "15");
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);

            boolean hasStatusMismatch = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("status/delinquency mismatch")
                            && w.getSeverity() == Severity.HIGH);
            assertTrue(hasStatusMismatch, "Should detect delinquent loan marked as active");
        }

        @Test
        void acceptsActiveLoanWithZeroDelinquency() {
            LegacyLoanAccount acct = buildLoanAccount("LN-002", "B-001", "ACT", "0");
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);

            boolean hasStatusMismatch = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("status/delinquency mismatch"));
            assertFalse(hasStatusMismatch, "Should not flag active loan with 0 delinquency days");
        }

        @Test
        void detectsOrphanedLoanAccount() {
            LegacyLoanAccount acct = buildLoanAccount("LN-003", null, "ACT", "0");
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);

            boolean hasOrphan = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("orphaned record")
                            && w.getSeverity() == Severity.CRITICAL);
            assertTrue(hasOrphan, "Should detect missing borrower ID");
        }

        @Test
        void detectsInvalidLoanStatusCode() {
            LegacyLoanAccount acct = buildLoanAccount("LN-004", "B-001", "XYZ", "0");
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);

            boolean hasInvalidStatus = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("Unknown loan status"));
            assertTrue(hasInvalidStatus);
        }

        @Test
        void detectsInvalidPropertyType() {
            LegacyLoanAccount acct = buildLoanAccount("LN-005", "B-001", "ACT", "0");
            acct.setPropertyType("XXX");
            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct);

            boolean hasInvalidPropType = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("Unknown property type"));
            assertTrue(hasInvalidPropType);
        }

        private LegacyLoanAccount buildLoanAccount(String acctNbr, String borrowerId,
                                                     String statusCode, String delinquencyDays) {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber(acctNbr);
            acct.setBorrowerId(borrowerId);
            acct.setBorrowerFirstName("Test");
            acct.setBorrowerLastName("User");
            acct.setBorrowerSsnLast4("1234");
            acct.setProductCode("FXD30");
            acct.setOriginalAmount("100,000");
            acct.setCurrentBalance("95,000");
            acct.setInterestRate("4.500");
            acct.setTermMonths("360");
            acct.setMonthlyPayment("506.69");
            acct.setOriginationDate("01/01/2020");
            acct.setMaturityDate("01/01/2050");
            acct.setFirstPaymentDate("02/01/2020");
            acct.setNextPaymentDate("01/01/2026");
            acct.setStatusCode(statusCode);
            acct.setDelinquencyDays(delinquencyDays);
            acct.setEscrowBalance("1,000.00");
            acct.setLtvPercent("80.0");
            acct.setPropertyAddress("123 Main St");
            acct.setPropertyCity("Anytown");
            acct.setPropertyState("CA");
            acct.setPropertyZip("90210");
            acct.setPropertyType("SFR");
            acct.setAppraisedValue("125,000");
            acct.setCreatedDate("01/01/2020");
            acct.setUpdatedDate("12/01/2025");
            return acct;
        }
    }

    // =========================================================================
    // Borrower Validation Tests (ANO-004, ANO-010)
    // =========================================================================

    @Nested
    class BorrowerValidationTests {

        @Test
        void detectsMissingRequiredFirstName() {
            LegacyBorrower borrower = buildBorrower("B-001", null, "Smith", "ACT");
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);

            boolean hasMissingName = warnings.stream()
                    .anyMatch(w -> w.getField().equals("BORR_FST_NM")
                            && w.getSeverity() == Severity.HIGH);
            assertTrue(hasMissingName);
        }

        @Test
        void detectsMissingRequiredLastName() {
            LegacyBorrower borrower = buildBorrower("B-002", "John", null, "ACT");
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);

            boolean hasMissingName = warnings.stream()
                    .anyMatch(w -> w.getField().equals("BORR_LST_NM")
                            && w.getSeverity() == Severity.HIGH);
            assertTrue(hasMissingName);
        }

        @Test
        void detectsInvalidCreditScoreRange() {
            LegacyBorrower borrower = buildBorrower("B-003", "John", "Smith", "ACT");
            borrower.setCreditScore("200");
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);

            boolean hasOutOfRange = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("outside valid range"));
            assertTrue(hasOutOfRange);
        }

        @Test
        void acceptsValidCreditScore() {
            LegacyBorrower borrower = buildBorrower("B-004", "John", "Smith", "ACT");
            borrower.setCreditScore("745");
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);

            boolean hasScoreIssue = warnings.stream()
                    .anyMatch(w -> w.getField().equals("BORR_CRDT_SCR"));
            assertFalse(hasScoreIssue);
        }

        @Test
        void detectsUnknownBorrowerStatusCode() {
            LegacyBorrower borrower = buildBorrower("B-005", "John", "Smith", "XYZ");
            List<DataQualityWarning> warnings = validator.validateBorrower(borrower);

            boolean hasInvalidStatus = warnings.stream()
                    .anyMatch(w -> w.getMessage().contains("Unknown status code"));
            assertTrue(hasInvalidStatus);
        }

        private LegacyBorrower buildBorrower(String id, String firstName, String lastName, String statusCode) {
            LegacyBorrower b = new LegacyBorrower();
            b.setBorrowerId(id);
            b.setFirstName(firstName);
            b.setLastName(lastName);
            b.setMiddleInitial("M");
            b.setSsnEncrypted("ENC_XXX");
            b.setDateOfBirth("01/01/1980");
            b.setAddressLine1("123 Main St");
            b.setCity("Anytown");
            b.setStateCode("CA");
            b.setZipCode("90210");
            b.setPhoneNumber("555-555-0100");
            b.setEmail("test@example.com");
            b.setCreditScore("750");
            b.setEmploymentStatus("EMPLOYED");
            b.setAnnualIncome("100,000");
            b.setCreatedDate("01/01/2020");
            b.setUpdatedDate("12/01/2025");
            b.setStatusCode(statusCode);
            b.setRecordType("PRI");
            return b;
        }
    }

    // =========================================================================
    // Status Resolution Tests (ANO-003)
    // =========================================================================

    @Nested
    class StatusResolutionTests {

        @Test
        void resolvesActiveWithNoDelinquency() {
            String status = validator.resolveEffectiveLoanStatus("ACT", "0");
            assertEquals("Active", status);
        }

        @Test
        void resolvesActiveWithDelinquency() {
            String status = validator.resolveEffectiveLoanStatus("ACT", "15");
            assertEquals("Active - Delinquent (15 days)", status);
        }

        @Test
        void resolvesClosed() {
            String status = validator.resolveEffectiveLoanStatus("CLO", "0");
            assertEquals("Closed", status);
        }

        @Test
        void resolvesDefault() {
            String status = validator.resolveEffectiveLoanStatus("DFT", "30");
            assertEquals("Default", status);
        }

        @Test
        void resolvesForbearance() {
            String status = validator.resolveEffectiveLoanStatus("FRB", "0");
            assertEquals("Forbearance", status);
        }

        @Test
        void handlesNullStatus() {
            String status = validator.resolveEffectiveLoanStatus(null, "0");
            assertEquals("Unknown", status);
        }

        @Test
        void handlesUnknownStatusCode() {
            String status = validator.resolveEffectiveLoanStatus("XYZ", "0");
            assertEquals("XYZ", status);
        }

        @Test
        void handlesNullDelinquencyDays() {
            String status = validator.resolveEffectiveLoanStatus("ACT", null);
            assertEquals("Active", status);
        }

        @Test
        void handlesNonNumericDelinquencyDays() {
            String status = validator.resolveEffectiveLoanStatus("ACT", "N/A");
            assertEquals("Active", status);
        }
    }
}
