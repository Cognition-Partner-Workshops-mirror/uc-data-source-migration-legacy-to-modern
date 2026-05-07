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
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANM-001: Numeric Parsing Failures
    // =========================================================================

    @Nested
    class NumericParsingTests {

        @Test
        void parseAmount_validWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.parseAmount("285,000", "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseAmount_validDecimalWithCommas() {
            assertEquals(new BigDecimal("1487.02"), validator.parseAmount("1,487.02", "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseAmount_null_returnsFallback() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount(null, "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseAmount_blank_returnsFallback() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("  ", "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseAmount_currencySymbol_strippedAndParsed() {
            assertEquals(new BigDecimal("285000"), validator.parseAmount("$285,000", "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseAmount_accountingNegative_parsed() {
            assertEquals(new BigDecimal("-1487.02"), validator.parseAmount("(1,487.02)", "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseAmount_nonNumericText_returnsFallback() {
            BigDecimal fallback = new BigDecimal("-1");
            assertEquals(fallback, validator.parseAmount("N/A", "field", "rec1", fallback));
        }

        @Test
        void parseAmount_textWithNumbers_returnsFallback() {
            assertEquals(BigDecimal.ZERO, validator.parseAmount("PENDING", "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseDecimal_validRate() {
            assertEquals(new BigDecimal("5.250"), validator.parseDecimal("5.250", "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseDecimal_malformed_returnsFallback() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal("5.2.5", "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseDecimal_null_returnsFallback() {
            assertEquals(BigDecimal.ZERO, validator.parseDecimal(null, "field", "rec1", BigDecimal.ZERO));
        }

        @Test
        void parseInteger_valid() {
            assertEquals(Integer.valueOf(745), validator.parseInteger("745", "field", "rec1", null));
        }

        @Test
        void parseInteger_null_returnsFallback() {
            assertNull(validator.parseInteger(null, "field", "rec1", null));
        }

        @Test
        void parseInteger_nonNumeric_returnsFallback() {
            assertEquals(Integer.valueOf(0), validator.parseInteger("ABC", "field", "rec1", 0));
        }

        @Test
        void parseInteger_decimal_returnsFallback() {
            assertEquals(Integer.valueOf(0), validator.parseInteger("745.5", "field", "rec1", 0));
        }

        @Test
        void parseInteger_withWhitespace_trimmed() {
            assertEquals(Integer.valueOf(360), validator.parseInteger(" 360 ", "field", "rec1", null));
        }
    }

    // =========================================================================
    // ANM-002: Date Format Validation
    // =========================================================================

    @Nested
    class DateValidationTests {

        @Test
        void parseDate_validMMDDYYYY() {
            LocalDate result = validator.parseDate("03/15/1978", "dob", "B-10001");
            assertEquals(LocalDate.of(1978, 3, 15), result);
        }

        @Test
        void parseDate_null_returnsNull() {
            assertNull(validator.parseDate(null, "dob", "B-10001"));
        }

        @Test
        void parseDate_blank_returnsNull() {
            assertNull(validator.parseDate("", "dob", "B-10001"));
        }

        @Test
        void parseDate_invalidDay_returnsNull() {
            assertNull(validator.parseDate("02/31/2025", "dob", "B-10001"));
        }

        @Test
        void parseDate_invalidMonth_returnsNull() {
            assertNull(validator.parseDate("13/01/2020", "dob", "B-10001"));
        }

        @Test
        void parseDate_isoFormat_returnsNull() {
            assertNull(validator.parseDate("2025-02-15", "dob", "B-10001"));
        }

        @Test
        void parseDate_literalPlaceholder_returnsNull() {
            assertNull(validator.parseDate("MM/DD/YYYY", "dob", "B-10001"));
        }

        @Test
        void parseDate_zeroPadded_valid() {
            LocalDate result = validator.parseDate("01/01/2020", "effDate", "PROD1");
            assertEquals(LocalDate.of(2020, 1, 1), result);
        }
    }

    // =========================================================================
    // ANM-003: Foreign Key / Orphaned Record Validation
    // =========================================================================

    @Nested
    class OrphanedRecordTests {

        @Test
        void validateLoanAccount_validReferences_noOrphanWarnings() {
            LegacyLoanAccount acct = createLoanAccount("LN-001", "B-10001", "FXD30");
            Set<String> borrowerIds = Set.of("B-10001");
            Set<String> productCodes = Set.of("FXD30");

            List<String> warnings = validator.validateLoanAccount(acct, borrowerIds, productCodes);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("Orphaned")));
        }

        @Test
        void validateLoanAccount_orphanedBorrower_detected() {
            LegacyLoanAccount acct = createLoanAccount("LN-001", "B-99999", "FXD30");
            Set<String> borrowerIds = Set.of("B-10001");
            Set<String> productCodes = Set.of("FXD30");

            List<String> warnings = validator.validateLoanAccount(acct, borrowerIds, productCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Orphaned") && w.contains("B-99999")));
        }

        @Test
        void validateLoanAccount_orphanedProduct_detected() {
            LegacyLoanAccount acct = createLoanAccount("LN-001", "B-10001", "INVALID");
            Set<String> borrowerIds = Set.of("B-10001");
            Set<String> productCodes = Set.of("FXD30");

            List<String> warnings = validator.validateLoanAccount(acct, borrowerIds, productCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Orphaned") && w.contains("INVALID")));
        }

        @Test
        void validateLoanAccount_nullBorrower_detected() {
            LegacyLoanAccount acct = createLoanAccount("LN-001", null, "FXD30");
            Set<String> borrowerIds = Set.of("B-10001");
            Set<String> productCodes = Set.of("FXD30");

            List<String> warnings = validator.validateLoanAccount(acct, borrowerIds, productCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Missing borrower ID")));
        }

        @Test
        void validatePayment_orphanedLoanAccount_detected() {
            LegacyPayment pmt = createPayment("PMT-001", "LN-DELETED", "1,000.00",
                    "500.00", "500.00", "0.00", "0.00", "REG", "PST",
                    "12/01/2025", "12/01/2025", "12/01/2025");
            Set<String> loanAcctNums = Set.of("LN-001", "LN-002");

            List<String> warnings = validator.validatePayment(pmt, loanAcctNums);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Orphaned") && w.contains("LN-DELETED")));
        }
    }

    // =========================================================================
    // ANM-005: Payment Component Sum Mismatch
    // =========================================================================

    @Nested
    class PaymentSumTests {

        @Test
        void validatePayment_componentsMatchTotal_noWarning() {
            LegacyPayment pmt = createPayment("PMT-001", "LN-001", "1,000.00",
                    "400.00", "500.00", "100.00", "0.00", "REG", "PST",
                    "12/01/2025", "12/01/2025", "12/01/2025");
            Set<String> loanAcctNums = Set.of("LN-001");

            List<String> warnings = validator.validatePayment(pmt, loanAcctNums);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("component mismatch")));
        }

        @Test
        void validatePayment_componentsMismatch_detected() {
            // Total=1487.02 but components sum to 1887.02 (escrow overcounted)
            LegacyPayment pmt = createPayment("PMT-001", "LN-001", "1,487.02",
                    "456.78", "1,074.69", "355.55", "0.00", "REG", "PST",
                    "12/15/2025", "12/14/2025", "12/15/2025");
            Set<String> loanAcctNums = Set.of("LN-001");

            List<String> warnings = validator.validatePayment(pmt, loanAcctNums);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("component mismatch")));
        }

        @Test
        void validatePayment_lateFeeExcludedFromTotal_detected() {
            // Total=1077.05 but components=1124.55 (47.50 late fee not in total)
            LegacyPayment pmt = createPayment("PMT-001", "LN-001", "1,077.05",
                    "295.82", "781.23", "0.00", "47.50", "REG", "PST",
                    "11/01/2025", "11/18/2025", "11/19/2025");
            Set<String> loanAcctNums = Set.of("LN-001");

            List<String> warnings = validator.validatePayment(pmt, loanAcctNums);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("component mismatch")));
        }

        @Test
        void validatePayment_smallRoundingDifference_tolerated() {
            // 0.01 rounding diff should be within tolerance
            LegacyPayment pmt = createPayment("PMT-001", "LN-001", "1,000.00",
                    "400.01", "500.00", "100.00", "0.00", "REG", "PST",
                    "12/01/2025", "12/01/2025", "12/01/2025");
            Set<String> loanAcctNums = Set.of("LN-001");

            List<String> warnings = validator.validatePayment(pmt, loanAcctNums);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("component mismatch")));
        }
    }

    // =========================================================================
    // ANM-006: Null Values in Required Fields
    // =========================================================================

    @Nested
    class NullFieldTests {

        @Test
        void requireNonBlank_presentValue_returnsValue() {
            assertEquals("James", validator.requireNonBlank("James", "firstName", "B-10001", "Unknown"));
        }

        @Test
        void requireNonBlank_nullValue_returnsDefault() {
            assertEquals("Unknown", validator.requireNonBlank(null, "firstName", "B-10001", "Unknown"));
        }

        @Test
        void requireNonBlank_blankValue_returnsDefault() {
            assertEquals("Unknown", validator.requireNonBlank("  ", "firstName", "B-10001", "Unknown"));
        }

        @Test
        void validateBorrower_nullFirstName_reported() {
            LegacyBorrower borrower = createBorrower("B-001", null, "Mitchell", "745", "ACT");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Missing first name")));
        }

        @Test
        void validateBorrower_nullLastName_reported() {
            LegacyBorrower borrower = createBorrower("B-001", "James", null, "745", "ACT");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Missing last name")));
        }

        @Test
        void validateBorrower_validRecord_noWarnings() {
            LegacyBorrower borrower = createBorrower("B-001", "James", "Mitchell", "745", "ACT");
            borrower.setDateOfBirth("03/15/1978");
            borrower.setAnnualIncome("92,500");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // ANM-007: Invalid Status Codes
    // =========================================================================

    @Nested
    class StatusCodeTests {

        @Test
        void validateStatusCode_validLoanStatus() {
            assertEquals("ACT", validator.validateStatusCode("ACT",
                    validator.getValidLoanStatusCodes(), "loanStatus", "LN-001"));
        }

        @Test
        void validateStatusCode_invalidLoanStatus_returnsCode() {
            String result = validator.validateStatusCode("XYZ",
                    validator.getValidLoanStatusCodes(), "loanStatus", "LN-001");
            assertEquals("XYZ", result);
        }

        @Test
        void validateStatusCode_nullStatus_returnsNull() {
            assertNull(validator.validateStatusCode(null,
                    validator.getValidLoanStatusCodes(), "loanStatus", "LN-001"));
        }

        @Test
        void validateStatusCode_blankStatus_returnsNull() {
            assertNull(validator.validateStatusCode("  ",
                    validator.getValidLoanStatusCodes(), "loanStatus", "LN-001"));
        }

        @Test
        void validateStatusCode_fullWord_notInEnum() {
            String result = validator.validateStatusCode("ACTIVE",
                    validator.getValidLoanStatusCodes(), "loanStatus", "LN-001");
            assertEquals("ACTIVE", result);
        }

        @Test
        void validateStatusCode_allPaymentStatuses_valid() {
            for (String code : List.of("PST", "REV", "NSF", "PND")) {
                assertEquals(code, validator.validateStatusCode(code,
                        validator.getValidPaymentStatusCodes(), "paymentStatus", "PMT-001"));
            }
        }

        @Test
        void validateStatusCode_allPaymentTypes_valid() {
            for (String code : List.of("REG", "EXT", "PRT", "PRE")) {
                assertEquals(code, validator.validateStatusCode(code,
                        validator.getValidPaymentTypeCodes(), "paymentType", "PMT-001"));
            }
        }
    }

    // =========================================================================
    // ANM-009: Payment Date Ordering
    // =========================================================================

    @Nested
    class PaymentDateOrderingTests {

        @Test
        void validatePayment_receivedAfterProcessed_detected() {
            LegacyPayment pmt = createPayment("PMT-001", "LN-001", "1,000.00",
                    "400.00", "500.00", "100.00", "0.00", "REG", "PST",
                    "12/01/2025", "12/06/2025", "12/05/2025");  // received AFTER processed
            Set<String> loanAcctNums = Set.of("LN-001");

            List<String> warnings = validator.validatePayment(pmt, loanAcctNums);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("received date") && w.contains("after processed")));
        }

        @Test
        void validatePayment_lateWithNoFee_detected() {
            // Due 12/01, received 12/05, but no late fee
            LegacyPayment pmt = createPayment("PMT-001", "LN-001", "1,000.00",
                    "400.00", "500.00", "100.00", "0.00", "REG", "PST",
                    "12/01/2025", "12/05/2025", "12/06/2025");
            Set<String> loanAcctNums = Set.of("LN-001");

            List<String> warnings = validator.validatePayment(pmt, loanAcctNums);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("received late") && w.contains("no late fee")));
        }
    }

    // =========================================================================
    // ANM-010: Credit Score Range Validation
    // =========================================================================

    @Nested
    class CreditScoreTests {

        @Test
        void validateCreditScore_valid() {
            assertEquals(Integer.valueOf(745), validator.validateCreditScore("745", "B-10001"));
        }

        @Test
        void validateCreditScore_minimum() {
            assertEquals(Integer.valueOf(300), validator.validateCreditScore("300", "B-10001"));
        }

        @Test
        void validateCreditScore_maximum() {
            assertEquals(Integer.valueOf(850), validator.validateCreditScore("850", "B-10001"));
        }

        @Test
        void validateCreditScore_belowMinimum_returnsNull() {
            assertNull(validator.validateCreditScore("0", "B-10001"));
        }

        @Test
        void validateCreditScore_aboveMaximum_returnsNull() {
            assertNull(validator.validateCreditScore("999", "B-10001"));
        }

        @Test
        void validateCreditScore_negative_returnsNull() {
            assertNull(validator.validateCreditScore("-1", "B-10001"));
        }

        @Test
        void validateCreditScore_nonNumeric_returnsNull() {
            assertNull(validator.validateCreditScore("N/A", "B-10001"));
        }

        @Test
        void validateCreditScore_null_returnsNull() {
            assertNull(validator.validateCreditScore(null, "B-10001"));
        }
    }

    // =========================================================================
    // Helper methods for building test entities
    // =========================================================================

    private LegacyBorrower createBorrower(String id, String firstName, String lastName,
                                           String creditScore, String statusCode) {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId(id);
        b.setFirstName(firstName);
        b.setLastName(lastName);
        b.setCreditScore(creditScore);
        b.setStatusCode(statusCode);
        return b;
    }

    private LegacyLoanAccount createLoanAccount(String acctNum, String borrowerId, String productCode) {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber(acctNum);
        acct.setBorrowerId(borrowerId);
        acct.setProductCode(productCode);
        acct.setStatusCode("ACT");
        acct.setOriginalAmount("100,000");
        acct.setOriginationDate("01/01/2020");
        return acct;
    }

    private LegacyPayment createPayment(String seqNum, String loanAcctNum, String totalAmt,
                                         String principalAmt, String interestAmt, String escrowAmt,
                                         String lateFee, String typeCode, String statusCode,
                                         String paymentDate, String receivedDate, String processedDate) {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber(seqNum);
        pmt.setLoanAccountNumber(loanAcctNum);
        pmt.setTotalAmount(totalAmt);
        pmt.setPrincipalAmount(principalAmt);
        pmt.setInterestAmount(interestAmt);
        pmt.setEscrowAmount(escrowAmt);
        pmt.setLateFee(lateFee);
        pmt.setTypeCode(typeCode);
        pmt.setStatusCode(statusCode);
        pmt.setPaymentDate(paymentDate);
        pmt.setReceivedDate(receivedDate);
        pmt.setProcessedDate(processedDate);
        return pmt;
    }
}
