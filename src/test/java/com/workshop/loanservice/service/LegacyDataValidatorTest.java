package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class LegacyDataValidatorTest {

    @Mock
    private LegacyBorrowerRepository borrowerRepository;

    @Mock
    private LegacyLoanProductRepository productRepository;

    @Mock
    private LegacyLoanAccountRepository loanAccountRepository;

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator(borrowerRepository, productRepository, loanAccountRepository);
    }

    // =========================================================================
    // ANO-001: Payment Component Sum Mismatch
    // =========================================================================
    @Nested
    class PaymentComponentSumTests {

        @Test
        void detectsMismatchWhenEscrowInflatesTotal() {
            when(loanAccountRepository.existsById(anyString())).thenReturn(true);

            LegacyPayment pmt = buildPayment("PMT-001", "LN-001",
                    "1,487.02", "456.78", "1,074.69", "355.55", "0.00");

            ValidationResult result = validator.validatePayment(pmt);

            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("PMT_AMT") && e.contains("does not match component sum")));
        }

        @Test
        void detectsMismatchWhenLateFeeNotIncludedInTotal() {
            when(loanAccountRepository.existsById(anyString())).thenReturn(true);

            LegacyPayment pmt = buildPayment("PMT-002", "LN-001",
                    "1,077.05", "295.82", "781.23", "0.00", "47.50");

            ValidationResult result = validator.validatePayment(pmt);

            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("PMT_AMT") && e.contains("does not match")));
        }

        @Test
        void passesWhenComponentsSumCorrectly() {
            when(loanAccountRepository.existsById(anyString())).thenReturn(true);

            LegacyPayment pmt = buildPayment("PMT-003", "LN-001",
                    "2,924.18", "1,842.56", "815.50", "266.12", "0.00");

            ValidationResult result = validator.validatePayment(pmt);

            assertFalse(result.getErrors().stream()
                    .anyMatch(e -> e.contains("does not match component sum")));
        }
    }

    // =========================================================================
    // ANO-002: Numeric String Parse Failures
    // =========================================================================
    @Nested
    class NumericParseTests {

        @Test
        void safeParseAmountHandlesDollarSign() {
            BigDecimal result = validator.safeParseAmount("$285,000");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void safeParseAmountHandlesValidAmount() {
            BigDecimal result = validator.safeParseAmount("285,000");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void safeParseAmountHandlesDecimalWithCommas() {
            BigDecimal result = validator.safeParseAmount("1,487.02");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        void safeParseAmountHandlesNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount(null));
        }

        @Test
        void safeParseAmountHandlesBlank() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("  "));
        }

        @Test
        void safeParseAmountHandlesTextValue() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("N/A"));
        }

        @Test
        void safeParseIntegerHandlesValidValue() {
            assertEquals(745, validator.safeParseInteger("745"));
        }

        @Test
        void safeParseIntegerHandlesNull() {
            assertNull(validator.safeParseInteger(null));
        }

        @Test
        void safeParseIntegerHandlesNonNumeric() {
            assertNull(validator.safeParseInteger("N/A"));
        }

        @Test
        void safeParseIntegerHandlesDecimalString() {
            assertNull(validator.safeParseInteger("7.5"));
        }

        @Test
        void safeParseDecimalHandlesPercentSign() {
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal("5.250%"));
        }

        @Test
        void safeParseDecimalHandlesValidValue() {
            assertEquals(new BigDecimal("5.250"), validator.safeParseDecimal("5.250"));
        }

        @Test
        void validatorDetectsUnparseableAmount() {
            when(loanAccountRepository.existsById(anyString())).thenReturn(true);

            LegacyPayment pmt = buildPayment("PMT-BAD", "LN-001",
                    "$500", "200", "300", "0", "0");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("PMT_AMT") && e.contains("cannot parse")));
        }

        @Test
        void validatorDetectsUnparseableCreditScore() {
            LegacyBorrower borrower = buildBorrower("B-BAD", "John", "Doe", "ACT");
            borrower.setCreditScore("EXCELLENT");

            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("BORR_CRDT_SCR") && e.contains("cannot parse")));
        }

        @Test
        void validatorDetectsUnparseableInterestRate() {
            when(borrowerRepository.existsById(anyString())).thenReturn(true);
            when(productRepository.existsById(anyString())).thenReturn(true);

            LegacyLoanAccount acct = buildLoanAccount("LN-BAD", "B-001", "FXD30", "ACT");
            acct.setInterestRate("high");

            ValidationResult result = validator.validateLoanAccount(acct);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("LN_INT_RT") && e.contains("cannot parse")));
        }
    }

    // =========================================================================
    // ANO-003: Date Format Validation
    // =========================================================================
    @Nested
    class DateFormatTests {

        @Test
        void validatorAcceptsValidLegacyDate() {
            LegacyBorrower borrower = buildBorrower("B-001", "Jane", "Doe", "ACT");
            borrower.setDateOfBirth("03/15/1978");
            borrower.setCreatedDate("01/15/2019");
            borrower.setUpdatedDate("11/03/2025");

            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.getErrors().stream()
                    .anyMatch(e -> e.contains("invalid date")));
        }

        @Test
        void validatorRejectsIsoFormatDate() {
            LegacyBorrower borrower = buildBorrower("B-002", "Jane", "Doe", "ACT");
            borrower.setDateOfBirth("1978-03-15");

            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("BORR_DOB_DT") && e.contains("invalid date")));
        }

        @Test
        void validatorRejectsInvalidDayInDate() {
            LegacyBorrower borrower = buildBorrower("B-003", "Jane", "Doe", "ACT");
            borrower.setDateOfBirth("02/30/2020");

            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("BORR_DOB_DT") && e.contains("invalid date")));
        }

        @Test
        void validatorRejectsTextDate() {
            LegacyBorrower borrower = buildBorrower("B-004", "Jane", "Doe", "ACT");
            borrower.setDateOfBirth("TBD");

            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("BORR_DOB_DT") && e.contains("invalid date")));
        }

        @Test
        void safeParseDateReturnsNullForBadFormat() {
            assertNull(validator.safeParseDate("2025-01-15"));
        }

        @Test
        void safeParseDateReturnsDateForValidFormat() {
            assertNotNull(validator.safeParseDate("01/15/2025"));
        }
    }

    // =========================================================================
    // ANO-006: Referential Integrity (Orphaned Records)
    // =========================================================================
    @Nested
    class ReferentialIntegrityTests {

        @Test
        void detectsOrphanedBorrowerReference() {
            when(borrowerRepository.existsById("B-GHOST")).thenReturn(false);
            when(productRepository.existsById(anyString())).thenReturn(true);

            LegacyLoanAccount acct = buildLoanAccount("LN-ORPHAN", "B-GHOST", "FXD30", "ACT");

            ValidationResult result = validator.validateLoanAccount(acct);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("BORR_ID") && e.contains("non-existent borrower")));
        }

        @Test
        void detectsOrphanedProductReference() {
            when(borrowerRepository.existsById(anyString())).thenReturn(true);
            when(productRepository.existsById("BOGUS")).thenReturn(false);

            LegacyLoanAccount acct = buildLoanAccount("LN-ORPHAN2", "B-001", "BOGUS", "ACT");

            ValidationResult result = validator.validateLoanAccount(acct);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("PROD_CD") && e.contains("non-existent product")));
        }

        @Test
        void detectsOrphanedPaymentLoanReference() {
            when(loanAccountRepository.existsById("LN-GONE")).thenReturn(false);

            LegacyPayment pmt = buildPayment("PMT-ORPHAN", "LN-GONE",
                    "500.00", "200.00", "300.00", "0.00", "0.00");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("LN_ACCT_NBR") && e.contains("non-existent loan")));
        }

        @Test
        void passesWhenAllReferencesExist() {
            when(borrowerRepository.existsById("B-001")).thenReturn(true);
            when(productRepository.existsById("FXD30")).thenReturn(true);
            when(borrowerRepository.findById("B-001")).thenReturn(Optional.empty());

            LegacyLoanAccount acct = buildLoanAccount("LN-GOOD", "B-001", "FXD30", "ACT");

            ValidationResult result = validator.validateLoanAccount(acct);
            assertFalse(result.getErrors().stream()
                    .anyMatch(e -> e.contains("non-existent")));
        }
    }

    // =========================================================================
    // ANO-005: Denormalized Borrower Data Divergence
    // =========================================================================
    @Nested
    class DenormalizedDataTests {

        @Test
        void detectsBorrowerNameDivergence() {
            LegacyBorrower master = buildBorrower("B-001", "Sarah", "Chen-Smith", "ACT");
            when(borrowerRepository.existsById("B-001")).thenReturn(true);
            when(borrowerRepository.findById("B-001")).thenReturn(Optional.of(master));
            when(productRepository.existsById(anyString())).thenReturn(true);

            LegacyLoanAccount acct = buildLoanAccount("LN-DIV", "B-001", "FXD30", "ACT");
            acct.setBorrowerFirstName("Sarah");
            acct.setBorrowerLastName("Chen");

            ValidationResult result = validator.validateLoanAccount(acct);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("BORR_LST_NM") && w.contains("differs from master")));
        }
    }

    // =========================================================================
    // ANO-007: Payment Date Ordering
    // =========================================================================
    @Nested
    class PaymentDateOrderTests {

        @Test
        void detectsLateReceivedDate() {
            when(loanAccountRepository.existsById(anyString())).thenReturn(true);

            LegacyPayment pmt = buildPayment("PMT-LATE", "LN-001",
                    "1,077.05", "295.82", "781.23", "0.00", "0.00");
            pmt.setPaymentDate("11/01/2025");
            pmt.setReceivedDate("11/18/2025");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("PMT_RECV_DT") && w.contains("17 days")));
        }

        @Test
        void noWarningForNormalReceivedDate() {
            when(loanAccountRepository.existsById(anyString())).thenReturn(true);

            LegacyPayment pmt = buildPayment("PMT-OK", "LN-001",
                    "1,487.02", "456.78", "674.69", "355.55", "0.00");
            pmt.setPaymentDate("12/15/2025");
            pmt.setReceivedDate("12/14/2025");

            ValidationResult result = validator.validatePayment(pmt);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("PMT_RECV_DT")));
        }
    }

    // =========================================================================
    // ANO-008: Delinquency/Status Inconsistency
    // =========================================================================
    @Nested
    class DelinquencyStatusTests {

        @Test
        void detectsDelinquencyWithActiveStatus() {
            when(borrowerRepository.existsById(anyString())).thenReturn(true);
            when(productRepository.existsById(anyString())).thenReturn(true);
            when(borrowerRepository.findById(anyString())).thenReturn(Optional.empty());

            LegacyLoanAccount acct = buildLoanAccount("LN-DLQ", "B-001", "FXD30", "ACT");
            acct.setDelinquencyDays("15");

            ValidationResult result = validator.validateLoanAccount(acct);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("LN_DLQ_DAYS") && w.contains("delinquency days")));
        }

        @Test
        void noWarningForZeroDelinquencyActiveStatus() {
            when(borrowerRepository.existsById(anyString())).thenReturn(true);
            when(productRepository.existsById(anyString())).thenReturn(true);
            when(borrowerRepository.findById(anyString())).thenReturn(Optional.empty());

            LegacyLoanAccount acct = buildLoanAccount("LN-OK", "B-001", "FXD30", "ACT");
            acct.setDelinquencyDays("0");

            ValidationResult result = validator.validateLoanAccount(acct);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("delinquency")));
        }
    }

    // =========================================================================
    // ANO-009: Null Required Fields
    // =========================================================================
    @Nested
    class NullRequiredFieldTests {

        @Test
        void detectsNullBorrowerFirstName() {
            LegacyBorrower borrower = buildBorrower("B-NULL", null, "Doe", "ACT");

            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("BORR_FST_NM") && e.contains("required")));
        }

        @Test
        void detectsNullBorrowerLastName() {
            LegacyBorrower borrower = buildBorrower("B-NULL2", "Jane", null, "ACT");

            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("BORR_LST_NM") && e.contains("required")));
        }

        @Test
        void detectsNullLoanBorrowerId() {
            when(productRepository.existsById(anyString())).thenReturn(true);

            LegacyLoanAccount acct = buildLoanAccount("LN-NULL", null, "FXD30", "ACT");

            ValidationResult result = validator.validateLoanAccount(acct);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("BORR_ID") && e.contains("required")));
        }

        @Test
        void detectsNullPaymentTotal() {
            when(loanAccountRepository.existsById(anyString())).thenReturn(true);

            LegacyPayment pmt = buildPayment("PMT-NULL", "LN-001",
                    null, "200.00", "300.00", "0.00", "0.00");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasErrors());
            assertTrue(result.getErrors().stream()
                    .anyMatch(e -> e.contains("PMT_AMT") && e.contains("required")));
        }
    }

    // =========================================================================
    // ANO-010: Unrecognized Status Codes
    // =========================================================================
    @Nested
    class UnrecognizedStatusCodeTests {

        @Test
        void detectsUnrecognizedBorrowerStatus() {
            LegacyBorrower borrower = buildBorrower("B-UNK", "Jane", "Doe", "XYZ");

            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("BORR_STAT_CD") && w.contains("unrecognized")));
        }

        @Test
        void acceptsKnownBorrowerStatus() {
            LegacyBorrower borrower = buildBorrower("B-OK", "Jane", "Doe", "ACT");

            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("BORR_STAT_CD")));
        }

        @Test
        void detectsUnrecognizedPaymentStatus() {
            when(loanAccountRepository.existsById(anyString())).thenReturn(true);

            LegacyPayment pmt = buildPayment("PMT-UNK", "LN-001",
                    "500.00", "200.00", "300.00", "0.00", "0.00");
            pmt.setStatusCode("BAD");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("PMT_STAT_CD") && w.contains("unrecognized")));
        }

        @Test
        void detectsUnrecognizedPaymentType() {
            when(loanAccountRepository.existsById(anyString())).thenReturn(true);

            LegacyPayment pmt = buildPayment("PMT-UNK2", "LN-001",
                    "500.00", "200.00", "300.00", "0.00", "0.00");
            pmt.setTypeCode("ZZZ");

            ValidationResult result = validator.validatePayment(pmt);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("PMT_TYP_CD") && w.contains("unrecognized")));
        }
    }

    // =========================================================================
    // Credit Score Range Validation
    // =========================================================================
    @Nested
    class CreditScoreRangeTests {

        @Test
        void detectsOutOfRangeCreditScore() {
            LegacyBorrower borrower = buildBorrower("B-CSR", "Jane", "Doe", "ACT");
            borrower.setCreditScore("900");

            ValidationResult result = validator.validateBorrower(borrower);
            assertTrue(result.hasWarnings());
            assertTrue(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("BORR_CRDT_SCR") && w.contains("outside valid range")));
        }

        @Test
        void acceptsValidCreditScore() {
            LegacyBorrower borrower = buildBorrower("B-CSR2", "Jane", "Doe", "ACT");
            borrower.setCreditScore("745");

            ValidationResult result = validator.validateBorrower(borrower);
            assertFalse(result.getWarnings().stream()
                    .anyMatch(w -> w.contains("BORR_CRDT_SCR")));
        }
    }

    // =========================================================================
    // Helper builders
    // =========================================================================

    private LegacyBorrower buildBorrower(String id, String firstName, String lastName, String status) {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId(id);
        b.setFirstName(firstName);
        b.setLastName(lastName);
        b.setStatusCode(status);
        b.setDateOfBirth("01/01/1980");
        b.setCreatedDate("01/01/2020");
        b.setUpdatedDate("01/01/2025");
        b.setCreditScore("700");
        b.setAnnualIncome("80,000");
        return b;
    }

    private LegacyLoanAccount buildLoanAccount(String acctNum, String borrowerId,
                                                String productCode, String status) {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber(acctNum);
        acct.setBorrowerId(borrowerId);
        acct.setProductCode(productCode);
        acct.setStatusCode(status);
        acct.setOriginalAmount("200,000");
        acct.setCurrentBalance("180,000");
        acct.setInterestRate("4.500");
        acct.setTermMonths("360");
        acct.setMonthlyPayment("1,013.37");
        acct.setEscrowBalance("2,500");
        acct.setLtvPercent("80.0");
        acct.setDelinquencyDays("0");
        acct.setAppraisedValue("250,000");
        acct.setOriginationDate("01/01/2020");
        acct.setMaturityDate("01/01/2050");
        acct.setFirstPaymentDate("02/01/2020");
        acct.setNextPaymentDate("01/01/2026");
        acct.setCreatedDate("01/01/2020");
        acct.setUpdatedDate("01/01/2025");
        acct.setBorrowerFirstName("Test");
        acct.setBorrowerLastName("User");
        acct.setPropertyType("SFR");
        return acct;
    }

    private LegacyPayment buildPayment(String seqNum, String loanAcctNum,
                                        String total, String principal, String interest,
                                        String escrow, String lateFee) {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber(seqNum);
        pmt.setLoanAccountNumber(loanAcctNum);
        pmt.setTotalAmount(total);
        pmt.setPrincipalAmount(principal);
        pmt.setInterestAmount(interest);
        pmt.setEscrowAmount(escrow);
        pmt.setLateFee(lateFee);
        pmt.setPaymentDate("12/01/2025");
        pmt.setReceivedDate("11/30/2025");
        pmt.setProcessedDate("12/01/2025");
        pmt.setCreatedDate("12/01/2025");
        pmt.setUpdatedDate("12/01/2025");
        pmt.setTypeCode("REG");
        pmt.setStatusCode("PST");
        return pmt;
    }
}
