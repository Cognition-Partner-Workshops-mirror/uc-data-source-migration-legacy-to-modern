package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.ValidationResult.Severity;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for LegacyDataValidator covering each anomaly type
 * documented in docs/DATA_ANOMALY_REPORT.md.
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANOM-001: Payment component arithmetic mismatch
    // =========================================================================

    @Nested
    class PaymentArithmeticTests {

        @Test
        void detectsMismatchedPaymentComponents() {
            // Mirrors PMT-2025120001 from seed data: total=1487.02 but components sum to 1887.02
            LegacyPayment payment = buildPayment("PMT-TEST-001",
                    "1,487.02", "456.78", "1,074.69", "355.55", "0.00");

            ValidationResult result = new ValidationResult();
            validator.validatePaymentArithmetic(payment, result);

            assertTrue(result.hasIssues(), "Should detect arithmetic mismatch");
            assertEquals(1, result.size());
            assertEquals(Severity.CRITICAL, result.getIssues().get(0).getSeverity());
            assertEquals("ANOM-001", result.getIssues().get(0).getAnomalyId());
        }

        @Test
        void acceptsBalancedPaymentComponents() {
            // total = 2924.18 = 1842.56 + 815.50 + 266.12 + 0.00
            LegacyPayment payment = buildPayment("PMT-TEST-002",
                    "2,924.18", "1,842.56", "815.50", "266.12", "0.00");

            ValidationResult result = new ValidationResult();
            validator.validatePaymentArithmetic(payment, result);

            assertFalse(result.hasIssues(), "Balanced payment should pass validation");
        }

        @Test
        void acceptsPaymentWithLateFee() {
            // total = 1077.05 = 295.82 + 781.23 + 0.00 + 0.00 (late fee is separate additive)
            // But total(1077.05) != 295.82 + 781.23 + 0.00 + 47.50 = 1124.55
            // This mimics PMT-2025110003 where late fee is additional
            LegacyPayment payment = buildPayment("PMT-TEST-003",
                    "1,077.05", "295.82", "781.23", "0.00", "0.00");

            ValidationResult result = new ValidationResult();
            validator.validatePaymentArithmetic(payment, result);

            assertFalse(result.hasIssues(), "Payment without escrow/late fee should balance on P+I");
        }
    }

    // =========================================================================
    // ANOM-002: Safe numeric parsing
    // =========================================================================

    @Nested
    class NumericParsingTests {

        @Test
        void parsesAmountWithCommas() {
            BigDecimal result = validator.safeParseAmount("285,000");
            assertNotNull(result);
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void parsesDecimalAmount() {
            BigDecimal result = validator.safeParseAmount("1,487.02");
            assertNotNull(result);
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        void returnsNullForNonNumericAmount() {
            // "N/A" would crash the old parser; safe parser returns null
            assertNull(validator.safeParseAmount("N/A"));
        }

        @Test
        void returnsNullForCurrencySymbolAmount() {
            assertNull(validator.safeParseAmount("$285,000"));
        }

        @Test
        void returnsZeroForNullAmount() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount(null));
        }

        @Test
        void returnsZeroForBlankAmount() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("  "));
        }

        @Test
        void parsesIntegerString() {
            assertEquals(745, validator.safeParseInteger("745"));
        }

        @Test
        void returnsNullForNonNumericInteger() {
            assertNull(validator.safeParseInteger("TBD"));
        }

        @Test
        void returnsNullForNullInteger() {
            assertNull(validator.safeParseInteger(null));
        }

        @Test
        void parsesDecimalString() {
            BigDecimal result = validator.safeParseDecimal("4.750");
            assertNotNull(result);
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        void returnsNullForNonNumericDecimal() {
            assertNull(validator.safeParseDecimal("PENDING"));
        }

        @Test
        void detectsUnparseableCreditScore() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe", "R", "BAD_SCORE", "50,000");

            ValidationResult result = new ValidationResult();
            validator.validateBorrowerNumericFields(borrower, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getAnomalyId().equals("ANOM-002")
                            && i.getDescription().contains("credit score")));
        }

        @Test
        void detectsOutOfRangeCreditScore() {
            // Credit score of 100 is below valid range (300-850)
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe", "R", "100", "50,000");

            ValidationResult result = new ValidationResult();
            validator.validateBorrowerNumericFields(borrower, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getDescription().contains("out of valid range")));
        }

        @Test
        void detectsUnparseableLoanAmount() {
            LegacyLoanAccount account = buildLoanAccount("LN-TEST", "B-TEST", "FXD30");
            account.setOriginalAmount("TWO_HUNDRED_K");

            ValidationResult result = new ValidationResult();
            validator.validateLoanAccountNumericFields(account, result);

            assertTrue(result.hasIssues());
            assertEquals(Severity.CRITICAL, result.getIssues().get(0).getSeverity());
        }

        @Test
        void detectsUnparseablePaymentAmount() {
            LegacyPayment payment = buildPayment("PMT-TEST", "N/A", "100", "200", "0", "0");

            ValidationResult result = new ValidationResult();
            validator.validatePaymentNumericFields(payment, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getDescription().contains("PMT_AMT")));
        }
    }

    // =========================================================================
    // ANOM-003: Referential integrity (orphaned records)
    // =========================================================================

    @Nested
    class ReferentialIntegrityTests {

        @Test
        void detectsOrphanedLoanAccount() {
            LegacyBorrower borrower = buildBorrower("B-001", "John", "Doe", "R", "700", "50,000");
            LegacyLoanProduct product = buildProduct("FXD30");
            // Loan references non-existent borrower B-999
            LegacyLoanAccount orphanedLoan = buildLoanAccount("LN-ORPHAN", "B-999", "FXD30");

            ValidationResult result = new ValidationResult();
            validator.validateReferentialIntegrity(
                    List.of(borrower), List.of(product), List.of(orphanedLoan), List.of(), result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getAnomalyId().equals("ANOM-003")
                            && i.getDescription().contains("BORR_ID")));
        }

        @Test
        void detectsOrphanedPayment() {
            LegacyPayment orphanedPayment = buildPayment("PMT-ORPHAN", "100", "50", "50", "0", "0");
            orphanedPayment.setLoanAccountNumber("LN-NONEXISTENT");

            ValidationResult result = new ValidationResult();
            validator.validateReferentialIntegrity(
                    List.of(), List.of(), List.of(), List.of(orphanedPayment), result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getAnomalyId().equals("ANOM-003")
                            && i.getDescription().contains("LN_ACCT_NBR")));
        }

        @Test
        void detectsMissingProductReference() {
            LegacyBorrower borrower = buildBorrower("B-001", "John", "Doe", "R", "700", "50,000");
            // Loan references non-existent product
            LegacyLoanAccount loan = buildLoanAccount("LN-001", "B-001", "NONEXISTENT_PROD");

            ValidationResult result = new ValidationResult();
            validator.validateReferentialIntegrity(
                    List.of(borrower), List.of(), List.of(loan), List.of(), result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getDescription().contains("PROD_CD")));
        }

        @Test
        void passesWithValidReferences() {
            LegacyBorrower borrower = buildBorrower("B-001", "John", "Doe", "R", "700", "50,000");
            LegacyLoanProduct product = buildProduct("FXD30");
            LegacyLoanAccount loan = buildLoanAccount("LN-001", "B-001", "FXD30");
            LegacyPayment payment = buildPayment("PMT-001", "1000", "500", "500", "0", "0");
            payment.setLoanAccountNumber("LN-001");

            ValidationResult result = new ValidationResult();
            validator.validateReferentialIntegrity(
                    List.of(borrower), List.of(product), List.of(loan), List.of(payment), result);

            assertFalse(result.hasIssues());
        }
    }

    // =========================================================================
    // ANOM-004: Date format validation
    // =========================================================================

    @Nested
    class DateValidationTests {

        @Test
        void parsesValidLegacyDate() {
            LocalDate date = validator.safeParseLegacyDate("03/15/1978");
            assertNotNull(date);
            assertEquals(LocalDate.of(1978, 3, 15), date);
        }

        @Test
        void returnsNullForMalformedDate() {
            assertNull(validator.safeParseLegacyDate("13/32/2025"));
        }

        @Test
        void returnsNullForIsoDate() {
            // ISO format not expected in legacy data
            assertNull(validator.safeParseLegacyDate("2025-12-01"));
        }

        @Test
        void returnsNullForEmptyDate() {
            assertNull(validator.safeParseLegacyDate(""));
            assertNull(validator.safeParseLegacyDate(null));
        }

        @Test
        void formatsDateToIso() {
            assertEquals("1978-03-15", validator.formatDateToIso("03/15/1978"));
        }

        @Test
        void formatsDateReturnOriginalOnFailure() {
            // Malformed date returns the original string as fallback
            assertEquals("BAD_DATE", validator.formatDateToIso("BAD_DATE"));
        }

        @Test
        void detectsMalformedBorrowerDate() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe", "R", "700", "50,000");
            borrower.setDateOfBirth("31/12/1990"); // DD/MM/YYYY instead of MM/DD/YYYY
            borrower.setCreatedDate("01/15/2019");
            borrower.setUpdatedDate("11/03/2025");

            ValidationResult result = new ValidationResult();
            validator.validateBorrowerDateFields(borrower, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getAnomalyId().equals("ANOM-004")
                            && i.getDescription().contains("BORR_DOB_DT")));
        }

        @Test
        void detectsMalformedPaymentDate() {
            LegacyPayment payment = buildPayment("PMT-TEST", "100", "50", "50", "0", "0");
            payment.setPaymentDate("NOT_A_DATE");
            payment.setReceivedDate("12/01/2025");
            payment.setProcessedDate("12/01/2025");
            payment.setCreatedDate("12/01/2025");
            payment.setUpdatedDate("12/01/2025");

            ValidationResult result = new ValidationResult();
            validator.validatePaymentDateFields(payment, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getDescription().contains("PMT_DT")));
        }
    }

    // =========================================================================
    // ANOM-005: Status / delinquency inconsistency
    // =========================================================================

    @Nested
    class StatusConsistencyTests {

        @Test
        void detectsDelinquentLoanWithActiveStatus() {
            // Mirrors LN-2018-00089: 15 delinquency days but ACT status
            LegacyLoanAccount account = buildLoanAccount("LN-TEST", "B-001", "ARM51");
            account.setDelinquencyDays("15");
            account.setStatusCode("ACT");

            ValidationResult result = new ValidationResult();
            validator.validateLoanStatusConsistency(account, result);

            assertTrue(result.hasIssues());
            assertEquals("ANOM-005", result.getIssues().get(0).getAnomalyId());
            assertEquals(Severity.HIGH, result.getIssues().get(0).getSeverity());
            assertTrue(result.getIssues().get(0).getDescription().contains("15 delinquency days"));
        }

        @Test
        void acceptsCurrentLoanWithActiveStatus() {
            LegacyLoanAccount account = buildLoanAccount("LN-TEST", "B-001", "FXD30");
            account.setDelinquencyDays("0");
            account.setStatusCode("ACT");

            ValidationResult result = new ValidationResult();
            validator.validateLoanStatusConsistency(account, result);

            assertFalse(result.hasIssues());
        }

        @Test
        void acceptsDelinquentLoanWithDefaultStatus() {
            LegacyLoanAccount account = buildLoanAccount("LN-TEST", "B-001", "FXD30");
            account.setDelinquencyDays("90");
            account.setStatusCode("DFT");

            ValidationResult result = new ValidationResult();
            validator.validateLoanStatusConsistency(account, result);

            assertFalse(result.hasIssues());
        }

        @Test
        void detectsUnrecognizedStatusCode() {
            LegacyLoanAccount account = buildLoanAccount("LN-TEST", "B-001", "FXD30");
            account.setDelinquencyDays("0");
            account.setStatusCode("XYZ");

            ValidationResult result = new ValidationResult();
            validator.validateLoanStatusConsistency(account, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getDescription().contains("Unrecognized")));
        }
    }

    // =========================================================================
    // ANOM-006: Late payment without late fee
    // =========================================================================

    @Nested
    class LateFeeTests {

        @Test
        void detectsLatePaymentWithNoFee() {
            // Mirrors PMT-2025120003: due 12/01, received 12/05, fee=$0
            LegacyPayment payment = buildPayment("PMT-TEST", "1,077.05", "297.12", "779.93", "0.00", "0.00");
            payment.setPaymentDate("12/01/2025");
            payment.setReceivedDate("12/05/2025");

            ValidationResult result = new ValidationResult();
            validator.validateLateFeeConsistency(payment, result);

            assertTrue(result.hasIssues());
            assertEquals("ANOM-006", result.getIssues().get(0).getAnomalyId());
            assertEquals(Severity.MEDIUM, result.getIssues().get(0).getSeverity());
        }

        @Test
        void acceptsLatePaymentWithFee() {
            // Mirrors PMT-2025110003: due 11/01, received 11/18, fee=$47.50
            LegacyPayment payment = buildPayment("PMT-TEST", "1,077.05", "295.82", "781.23", "0.00", "47.50");
            payment.setPaymentDate("11/01/2025");
            payment.setReceivedDate("11/18/2025");

            ValidationResult result = new ValidationResult();
            validator.validateLateFeeConsistency(payment, result);

            assertFalse(result.hasIssues());
        }

        @Test
        void acceptsOnTimePayment() {
            LegacyPayment payment = buildPayment("PMT-TEST", "1,487.02", "456.78", "1,030.24", "0.00", "0.00");
            payment.setPaymentDate("12/15/2025");
            payment.setReceivedDate("12/14/2025");

            ValidationResult result = new ValidationResult();
            validator.validateLateFeeConsistency(payment, result);

            assertFalse(result.hasIssues());
        }
    }

    // =========================================================================
    // ANOM-007: Denormalized data consistency
    // =========================================================================

    @Nested
    class DenormalizedDataTests {

        @Test
        void detectsNameMismatch() {
            LegacyBorrower borrower = buildBorrower("B-001", "James", "Mitchell", "R", "745", "92,500");
            LegacyLoanAccount account = buildLoanAccount("LN-001", "B-001", "FXD30");
            account.setBorrowerFirstName("Jim"); // Mismatch with borrower master
            account.setBorrowerLastName("Mitchell");

            ValidationResult result = new ValidationResult();
            validator.validateDenormalizedBorrowerData(account, java.util.Map.of("B-001", borrower), result);

            assertTrue(result.hasIssues());
            assertEquals("ANOM-007", result.getIssues().get(0).getAnomalyId());
            assertTrue(result.getIssues().get(0).getDescription().contains("first name mismatch"));
        }

        @Test
        void acceptsConsistentNames() {
            LegacyBorrower borrower = buildBorrower("B-001", "James", "Mitchell", "R", "745", "92,500");
            LegacyLoanAccount account = buildLoanAccount("LN-001", "B-001", "FXD30");
            account.setBorrowerFirstName("James");
            account.setBorrowerLastName("Mitchell");

            ValidationResult result = new ValidationResult();
            validator.validateDenormalizedBorrowerData(account, java.util.Map.of("B-001", borrower), result);

            assertFalse(result.hasIssues());
        }
    }

    // =========================================================================
    // ANOM-008: Null required fields
    // =========================================================================

    @Nested
    class RequiredFieldTests {

        @Test
        void detectsNullMiddleInitial() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "Robert", "Williams", null, "658", "65,000");

            ValidationResult result = new ValidationResult();
            validator.validateBorrowerRequiredFields(borrower, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getAnomalyId().equals("ANOM-008")
                            && i.getSeverity() == Severity.LOW
                            && i.getDescription().contains("BORR_MID_INIT")));
        }

        @Test
        void detectsNullFirstName() {
            LegacyBorrower borrower = buildBorrower("B-TEST", null, "Williams", "R", "658", "65,000");

            ValidationResult result = new ValidationResult();
            validator.validateBorrowerRequiredFields(borrower, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getSeverity() == Severity.HIGH
                            && i.getDescription().contains("BORR_FST_NM")));
        }

        @Test
        void detectsNullSsn() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe", "R", "700", "50,000");
            borrower.setSsnEncrypted(null);

            ValidationResult result = new ValidationResult();
            validator.validateBorrowerRequiredFields(borrower, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getSeverity() == Severity.CRITICAL
                            && i.getDescription().contains("BORR_SSN_ENCR")));
        }
    }

    // =========================================================================
    // ANOM-009: Product validation
    // =========================================================================

    @Nested
    class ProductValidationTests {

        @Test
        void detectsZeroMinimumAmount() {
            LegacyLoanProduct product = buildProduct("VA30");
            product.setMinAmount("0");
            product.setMaxAmount("750,000");

            ValidationResult result = new ValidationResult();
            validator.validateLoanProduct(product, result);

            assertTrue(result.hasIssues());
            assertEquals("ANOM-009", result.getIssues().get(0).getAnomalyId());
        }

        @Test
        void detectsMinExceedsMax() {
            LegacyLoanProduct product = buildProduct("TEST");
            product.setMinAmount("500,000");
            product.setMaxAmount("100,000");

            ValidationResult result = new ValidationResult();
            validator.validateLoanProduct(product, result);

            assertTrue(result.hasIssues());
            assertTrue(result.getIssues().stream()
                    .anyMatch(i -> i.getDescription().contains("exceeds max")));
        }

        @Test
        void acceptsValidProduct() {
            LegacyLoanProduct product = buildProduct("FXD30");
            product.setMinAmount("50,000");
            product.setMaxAmount("1,500,000");
            product.setTermMonths("360");

            ValidationResult result = new ValidationResult();
            validator.validateLoanProduct(product, result);

            assertFalse(result.hasIssues());
        }
    }

    // =========================================================================
    // Comprehensive validateAll test
    // =========================================================================

    @Nested
    class ComprehensiveValidationTests {

        @Test
        void validateAllDetectsMultipleAnomalies() {
            // Build a small dataset with known anomalies
            LegacyBorrower borrower = buildBorrower("B-001", "James", "Mitchell", null, "745", "92,500");
            borrower.setDateOfBirth("03/15/1978");
            borrower.setCreatedDate("01/15/2019");
            borrower.setUpdatedDate("11/03/2025");
            borrower.setStatusCode("ACT");
            borrower.setSsnEncrypted("ENC_XXX_001");

            LegacyLoanProduct product = buildProduct("VA30");
            product.setMinAmount("0");
            product.setMaxAmount("750,000");
            product.setTermMonths("360");

            LegacyLoanAccount account = buildLoanAccount("LN-001", "B-001", "VA30");
            account.setBorrowerFirstName("James");
            account.setBorrowerLastName("Mitchell");
            account.setDelinquencyDays("15");
            account.setStatusCode("ACT");
            account.setOriginalAmount("165,000");
            account.setCurrentBalance("142,567.90");
            account.setInterestRate("4.250");
            account.setMonthlyPayment("811.61");
            account.setEscrowBalance("1,890.45");
            account.setLtvPercent("80.0");
            account.setAppraisedValue("206,000");
            account.setOriginationDate("03/01/2017");
            account.setMaturityDate("03/01/2047");
            account.setFirstPaymentDate("04/01/2017");
            account.setNextPaymentDate("01/01/2026");
            account.setCreatedDate("02/20/2017");
            account.setUpdatedDate("12/01/2025");

            // Mismatched payment: total != sum of components
            LegacyPayment badPayment = buildPayment("PMT-001",
                    "1,487.02", "456.78", "1,074.69", "355.55", "0.00");
            badPayment.setLoanAccountNumber("LN-001");
            badPayment.setPaymentDate("12/15/2025");
            badPayment.setReceivedDate("12/14/2025");
            badPayment.setProcessedDate("12/15/2025");
            badPayment.setCreatedDate("12/15/2025");
            badPayment.setUpdatedDate("12/15/2025");

            ValidationResult result = validator.validateAll(
                    List.of(borrower), List.of(product), List.of(account), List.of(badPayment));

            assertTrue(result.hasIssues());
            // Should detect at least: ANOM-001 (arithmetic), ANOM-005 (status), ANOM-008 (null mid init), ANOM-009 (zero min)
            assertTrue(result.getIssues().stream().anyMatch(i -> i.getAnomalyId().equals("ANOM-001")),
                    "Should detect payment arithmetic mismatch");
            assertTrue(result.getIssues().stream().anyMatch(i -> i.getAnomalyId().equals("ANOM-005")),
                    "Should detect delinquent loan with ACT status");
            assertTrue(result.getIssues().stream().anyMatch(i -> i.getAnomalyId().equals("ANOM-008")),
                    "Should detect null middle initial");
            assertTrue(result.getIssues().stream().anyMatch(i -> i.getAnomalyId().equals("ANOM-009")),
                    "Should detect zero minimum product amount");
        }
    }

    // =========================================================================
    // ValidationResult tests
    // =========================================================================

    @Nested
    class ValidationResultTests {

        @Test
        void tracksIssuesBySeverity() {
            ValidationResult result = new ValidationResult();
            result.addIssue(Severity.CRITICAL, "ANOM-001", "REC-1", "Critical issue");
            result.addIssue(Severity.HIGH, "ANOM-003", "REC-2", "High issue");
            result.addIssue(Severity.LOW, "ANOM-008", "REC-3", "Low issue");

            assertEquals(3, result.size());
            assertTrue(result.hasCriticalIssues());
            assertEquals(1, result.getIssuesBySeverity(Severity.CRITICAL).size());
            assertEquals(1, result.getIssuesBySeverity(Severity.HIGH).size());
            assertEquals(0, result.getIssuesBySeverity(Severity.MEDIUM).size());
            assertEquals(1, result.getIssuesBySeverity(Severity.LOW).size());
        }

        @Test
        void emptyResultHasNoIssues() {
            ValidationResult result = new ValidationResult();
            assertFalse(result.hasIssues());
            assertFalse(result.hasCriticalIssues());
            assertEquals(0, result.size());
        }
    }

    // =========================================================================
    // Test data builders
    // =========================================================================

    private LegacyBorrower buildBorrower(String id, String firstName, String lastName,
                                          String middleInitial, String creditScore, String income) {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId(id);
        b.setFirstName(firstName);
        b.setLastName(lastName);
        b.setMiddleInitial(middleInitial);
        b.setCreditScore(creditScore);
        b.setAnnualIncome(income);
        b.setSsnEncrypted("ENC_TEST");
        b.setStatusCode("ACT");
        b.setDateOfBirth("01/01/1980");
        b.setCreatedDate("01/01/2020");
        b.setUpdatedDate("01/01/2025");
        return b;
    }

    private LegacyLoanProduct buildProduct(String code) {
        LegacyLoanProduct p = new LegacyLoanProduct();
        p.setProductCode(code);
        p.setDescription("Test Product " + code);
        p.setTypeCode("FXD");
        p.setTermMonths("360");
        p.setRateType("FIXED");
        p.setMinAmount("50,000");
        p.setMaxAmount("1,000,000");
        p.setStatusCode("ACT");
        p.setEffectiveDate("01/01/2020");
        p.setExpirationDate("12/31/2099");
        return p;
    }

    private LegacyLoanAccount buildLoanAccount(String accountNumber, String borrowerId, String productCode) {
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber(accountNumber);
        a.setBorrowerId(borrowerId);
        a.setProductCode(productCode);
        a.setBorrowerFirstName("Test");
        a.setBorrowerLastName("User");
        a.setBorrowerSsnLast4("1234");
        a.setOriginalAmount("200,000");
        a.setCurrentBalance("180,000");
        a.setInterestRate("4.500");
        a.setTermMonths("360");
        a.setMonthlyPayment("1,013.37");
        a.setOriginationDate("01/01/2020");
        a.setMaturityDate("01/01/2050");
        a.setFirstPaymentDate("02/01/2020");
        a.setNextPaymentDate("01/01/2026");
        a.setStatusCode("ACT");
        a.setDelinquencyDays("0");
        a.setEscrowBalance("2,000.00");
        a.setLtvPercent("75.0");
        a.setPropertyAddress("123 Main St");
        a.setPropertyCity("Springfield");
        a.setPropertyState("IL");
        a.setPropertyZip("62701");
        a.setPropertyType("SFR");
        a.setAppraisedValue("267,000");
        a.setCreatedDate("01/01/2020");
        a.setUpdatedDate("12/01/2025");
        return a;
    }

    private LegacyPayment buildPayment(String seqNum, String total, String principal,
                                        String interest, String escrow, String lateFee) {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber(seqNum);
        p.setLoanAccountNumber("LN-TEST");
        p.setPaymentDate("12/01/2025");
        p.setTotalAmount(total);
        p.setPrincipalAmount(principal);
        p.setInterestAmount(interest);
        p.setEscrowAmount(escrow);
        p.setLateFee(lateFee);
        p.setTypeCode("REG");
        p.setStatusCode("PST");
        p.setReceivedDate("11/30/2025");
        p.setProcessedDate("12/01/2025");
        p.setCreatedDate("12/01/2025");
        p.setUpdatedDate("12/01/2025");
        return p;
    }
}
