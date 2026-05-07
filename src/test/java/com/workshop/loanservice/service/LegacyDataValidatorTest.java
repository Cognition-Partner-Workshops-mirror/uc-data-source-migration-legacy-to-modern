package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // Safe Parsing Tests
    // =========================================================================

    @Nested
    class SafeParseAmountTests {

        @Test
        void parsesValidAmountWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("285,000"));
        }

        @Test
        void parsesValidAmountWithDecimalAndCommas() {
            assertEquals(new BigDecimal("271432.56"), validator.safeParseAmount("271,432.56"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount(null));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.safeParseAmount("  "));
        }

        @Test
        void returnsNullForMalformedValue() {
            assertNull(validator.safeParseAmount("N/A"));
        }

        @Test
        void returnsNullForDollarSign() {
            assertNull(validator.safeParseAmount("$285,000"));
        }

        @Test
        void parsesZeroAmount() {
            assertEquals(new BigDecimal("0.00"), validator.safeParseAmount("0.00"));
        }
    }

    @Nested
    class SafeParseIntegerTests {

        @Test
        void parsesValidInteger() {
            assertEquals(745, validator.safeParseInteger("745"));
        }

        @Test
        void parsesIntegerWithWhitespace() {
            assertEquals(360, validator.safeParseInteger(" 360 "));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseInteger(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseInteger(""));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.safeParseInteger("PENDING"));
        }

        @Test
        void returnsNullForDecimalString() {
            assertNull(validator.safeParseInteger("4.75"));
        }
    }

    @Nested
    class SafeParseDateTests {

        @Test
        void parsesValidLegacyDate() {
            assertEquals(LocalDate.of(2025, 12, 15), validator.safeParseDate("12/15/2025"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseDate(null));
        }

        @Test
        void returnsNullForIsoFormat() {
            assertNull(validator.safeParseDate("2025-12-15"));
        }

        @Test
        void returnsNullForInvalidDate() {
            assertNull(validator.safeParseDate("13/45/2025"));
        }

        @Test
        void returnsNullForNonDateString() {
            assertNull(validator.safeParseDate("UNKNOWN"));
        }
    }

    @Nested
    class SafeParseDecimalTests {

        @Test
        void parsesValidDecimal() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseDecimal("4.750"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal(null));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.safeParseDecimal("VARIABLE"));
        }
    }

    // =========================================================================
    // Borrower Validation Tests
    // =========================================================================

    @Nested
    class BorrowerValidationTests {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower borrower = createValidBorrower();
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.isEmpty(), "Expected no warnings for valid borrower, got: " + warnings);
        }

        @Test
        void detectsNullRequiredFields() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-TEST");
            // All other fields null
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("firstName")));
            assertTrue(warnings.stream().anyMatch(w -> w.contains("lastName")));
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ssnEncrypted")));
            assertTrue(warnings.stream().anyMatch(w -> w.contains("statusCode")));
        }

        @Test
        void detectsInvalidCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("9999");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Credit score") && w.contains("out of range")));
        }

        @Test
        void detectsUnparseableCreditScore() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setCreditScore("EXCELLENT");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Credit score") && w.contains("unparseable")));
        }

        @Test
        void detectsUnparseableDate() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setDateOfBirth("1978-03-15");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("dateOfBirth") && w.contains("unparseable")));
        }

        @Test
        void detectsInvalidStatusCode() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setStatusCode("XYZ");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Invalid borrower status code")));
        }

        @Test
        void detectsUnparseableAnnualIncome() {
            LegacyBorrower borrower = createValidBorrower();
            borrower.setAnnualIncome("$92,500");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("annualIncome") && w.contains("unparseable")));
        }
    }

    // =========================================================================
    // Loan Account Validation Tests
    // =========================================================================

    @Nested
    class LoanAccountValidationTests {

        private Map<String, LegacyBorrower> borrowerIndex;
        private Map<String, LegacyLoanProduct> productIndex;

        @BeforeEach
        void setUp() {
            LegacyBorrower borrower = createValidBorrower();
            borrowerIndex = Map.of("B-10001", borrower);

            LegacyLoanProduct product = createValidProduct();
            productIndex = Map.of("FXD30", product);
        }

        @Test
        void validLoanAccountProducesNoWarnings() {
            LegacyLoanAccount account = createValidLoanAccount();
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.isEmpty(), "Expected no warnings, got: " + warnings);
        }

        @Test
        void detectsOrphanedBorrowerReference() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerId("B-99999");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Orphaned") && w.contains("BORR_ID")));
        }

        @Test
        void detectsOrphanedProductReference() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setProductCode("INVALID");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Orphaned") && w.contains("PROD_CD")));
        }

        @Test
        void detectsInvalidLoanStatusCode() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setStatusCode("BAD");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Invalid loan status code")));
        }

        @Test
        void detectsDelinquentWithActiveStatus() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setDelinquencyDays("15");
            account.setStatusCode("ACT");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Delinquent") && w.contains("ACT")));
        }

        @Test
        void detectsMaturityBeforeOrigination() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setOriginationDate("12/01/2049");
            account.setMaturityDate("01/01/2020");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Origination date") && w.contains("maturity")));
        }

        @Test
        void detectsSsnLast4MatchingPhoneDigits() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerSsnLast4("0142");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(
                    w -> w.contains("BORR_SSN_LST4") && w.contains("phone")),
                    "Expected SSN/phone mismatch warning, got: " + warnings);
        }

        @Test
        void detectsDenormalizedNameMismatch() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerFirstName("Jim");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("first name mismatch")));
        }

        @Test
        void detectsInvalidPropertyType() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setPropertyType("CASTLE");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Invalid property type code")));
        }

        @Test
        void detectsUnparseableAmount() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setOriginalAmount("LOTS");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("originalAmount") && w.contains("unparseable")));
        }

        @Test
        void detectsInterestRateOutOfRange() {
            LegacyLoanAccount account = createValidLoanAccount();
            account.setInterestRate("150.000");
            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Interest rate out of range")));
        }
    }

    // =========================================================================
    // Payment Validation Tests
    // =========================================================================

    @Nested
    class PaymentValidationTests {

        private Map<String, LegacyLoanAccount> loanIndex;

        @BeforeEach
        void setUp() {
            LegacyLoanAccount account = createValidLoanAccount();
            loanIndex = Map.of("LN-2019-00142", account);
        }

        @Test
        void validPaymentProducesNoWarnings() {
            LegacyPayment payment = createValidPayment();
            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertTrue(warnings.isEmpty(), "Expected no warnings, got: " + warnings);
        }

        @Test
        void detectsOrphanedLoanReference() {
            LegacyPayment payment = createValidPayment();
            payment.setLoanAccountNumber("LN-NONEXISTENT");
            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Orphaned") && w.contains("LN_ACCT_NBR")));
        }

        @Test
        void detectsPaymentComponentMismatch() {
            LegacyPayment payment = createValidPayment();
            // total = 1487.02 but components sum to more
            payment.setTotalAmount("1,487.02");
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");
            // sum = 1887.02, total = 1487.02
            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Payment total") && w.contains("≠")),
                    "Expected payment component mismatch warning, got: " + warnings);
        }

        @Test
        void noWarningWhenComponentsMatch() {
            LegacyPayment payment = createValidPayment();
            // components sum to exactly total
            payment.setTotalAmount("2,924.18");
            payment.setPrincipalAmount("1,842.56");
            payment.setInterestAmount("815.50");
            payment.setEscrowAmount("266.12");
            payment.setLateFee("0.00");
            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("Payment total")),
                    "Should not flag matching components, got: " + warnings);
        }

        @Test
        void detectsPaymentMismatchWithLateFee() {
            LegacyPayment payment = createValidPayment();
            // PMT-2025110003 scenario: total excludes late fee
            payment.setTotalAmount("1,077.05");
            payment.setPrincipalAmount("295.82");
            payment.setInterestAmount("781.23");
            payment.setEscrowAmount("0.00");
            payment.setLateFee("47.50");
            // sum = 1124.55, total = 1077.05
            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Payment total") && w.contains("≠")));
        }

        @Test
        void detectsInvalidPaymentTypeCode() {
            LegacyPayment payment = createValidPayment();
            payment.setTypeCode("XXX");
            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Invalid payment type code")));
        }

        @Test
        void detectsInvalidPaymentStatusCode() {
            LegacyPayment payment = createValidPayment();
            payment.setStatusCode("ZZZ");
            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Invalid payment status code")));
        }

        @Test
        void detectsNullRequiredPaymentFields() {
            LegacyPayment payment = new LegacyPayment();
            payment.setPaymentSequenceNumber("PMT-TEST");
            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("loanAccountNumber")));
            assertTrue(warnings.stream().anyMatch(w -> w.contains("paymentDate")));
            assertTrue(warnings.stream().anyMatch(w -> w.contains("totalAmount")));
            assertTrue(warnings.stream().anyMatch(w -> w.contains("statusCode")));
            assertTrue(warnings.stream().anyMatch(w -> w.contains("typeCode")));
        }

        @Test
        void detectsUnparseablePaymentAmount() {
            LegacyPayment payment = createValidPayment();
            payment.setTotalAmount("REFUND");
            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("totalAmount") && w.contains("unparseable")));
        }
    }

    // =========================================================================
    // Loan Product Validation Tests
    // =========================================================================

    @Nested
    class LoanProductValidationTests {

        @Test
        void validProductProducesNoWarnings() {
            LegacyLoanProduct product = createValidProduct();
            List<String> warnings = validator.validateLoanProduct(product);
            assertTrue(warnings.isEmpty(), "Expected no warnings, got: " + warnings);
        }

        @Test
        void detectsMinExceedsMax() {
            LegacyLoanProduct product = createValidProduct();
            product.setMinAmount("2,000,000");
            product.setMaxAmount("500,000");
            List<String> warnings = validator.validateLoanProduct(product);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Min amount") && w.contains("exceeds")));
        }

        @Test
        void detectsInvalidProductStatusCode() {
            LegacyLoanProduct product = createValidProduct();
            product.setStatusCode("OLD");
            List<String> warnings = validator.validateLoanProduct(product);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Invalid product status code")));
        }

        @Test
        void detectsNullRequiredFields() {
            LegacyLoanProduct product = new LegacyLoanProduct();
            product.setProductCode("TEST");
            List<String> warnings = validator.validateLoanProduct(product);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("description")));
            assertTrue(warnings.stream().anyMatch(w -> w.contains("typeCode")));
            assertTrue(warnings.stream().anyMatch(w -> w.contains("statusCode")));
        }
    }

    // =========================================================================
    // Integration: Real Seed Data Anomaly Detection
    // =========================================================================

    @Nested
    class SeedDataAnomalyDetection {

        @Test
        void detectsKnownPaymentMismatchInSeedData() {
            // Reproduces PMT-2025120001 from data-legacy.sql
            LegacyPayment payment = new LegacyPayment();
            payment.setPaymentSequenceNumber("PMT-2025120001");
            payment.setLoanAccountNumber("LN-2019-00142");
            payment.setPaymentDate("12/15/2025");
            payment.setTotalAmount("1,487.02");
            payment.setPrincipalAmount("456.78");
            payment.setInterestAmount("1,074.69");
            payment.setEscrowAmount("355.55");
            payment.setLateFee("0.00");
            payment.setTypeCode("REG");
            payment.setStatusCode("PST");
            payment.setReceivedDate("12/14/2025");
            payment.setProcessedDate("12/15/2025");

            LegacyLoanAccount account = createValidLoanAccount();
            Map<String, LegacyLoanAccount> loanIndex = Map.of("LN-2019-00142", account);

            List<String> warnings = validator.validatePayment(payment, loanIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Payment total") && w.contains("≠")),
                    "Should detect the known $400 mismatch in PMT-2025120001");
        }

        @Test
        void detectsKnownSsnPhoneConfusionInSeedData() {
            // Reproduces the SSN/phone confusion for B-10001 / LN-2019-00142
            LegacyBorrower borrower = createValidBorrower();
            Map<String, LegacyBorrower> borrowerIndex = Map.of("B-10001", borrower);

            LegacyLoanProduct product = createValidProduct();
            Map<String, LegacyLoanProduct> productIndex = Map.of("FXD30", product);

            LegacyLoanAccount account = createValidLoanAccount();
            account.setBorrowerSsnLast4("0142"); // matches phone 217-555-0142

            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_SSN_LST4") && w.contains("phone")),
                    "Should detect SSN last-4 matching phone digits");
        }

        @Test
        void detectsKnownDelinquencyStatusMismatchInSeedData() {
            // Reproduces LN-2018-00089 — 15 days delinquent but status ACT
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-10003");
            borrower.setFirstName("Michael");
            borrower.setLastName("Torres");
            borrower.setPhoneNumber("512-555-0167");
            borrower.setSsnEncrypted("ENC_XXX_003");
            borrower.setStatusCode("ACT");

            Map<String, LegacyBorrower> borrowerIndex = Map.of("B-10003", borrower);

            LegacyLoanProduct product = createValidProduct();
            product.setProductCode("ARM51");
            Map<String, LegacyLoanProduct> productIndex = Map.of("ARM51", product);

            LegacyLoanAccount account = new LegacyLoanAccount();
            account.setLoanAccountNumber("LN-2018-00089");
            account.setBorrowerId("B-10003");
            account.setBorrowerFirstName("Michael");
            account.setBorrowerLastName("Torres");
            account.setProductCode("ARM51");
            account.setOriginalAmount("195,000");
            account.setCurrentBalance("178,234.12");
            account.setInterestRate("5.250");
            account.setTermMonths("360");
            account.setMonthlyPayment("1,077.05");
            account.setOriginationDate("07/01/2018");
            account.setMaturityDate("07/01/2048");
            account.setFirstPaymentDate("08/01/2018");
            account.setNextPaymentDate("01/01/2026");
            account.setStatusCode("ACT");
            account.setDelinquencyDays("15");
            account.setEscrowBalance("2,100.00");
            account.setLtvPercent("75.0");
            account.setPropertyType("SFR");
            account.setAppraisedValue("260,000");

            List<String> warnings = validator.validateLoanAccount(account, borrowerIndex, productIndex);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("Delinquent") && w.contains("ACT")),
                    "Should detect delinquent loan with active status");
        }
    }

    // =========================================================================
    // Test Data Factories
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

    private LegacyLoanProduct createValidProduct() {
        LegacyLoanProduct p = new LegacyLoanProduct();
        p.setProductCode("FXD30");
        p.setDescription("30-Year Fixed Rate Mortgage");
        p.setTypeCode("FXD");
        p.setTermMonths("360");
        p.setRateType("FIXED");
        p.setMinAmount("50,000");
        p.setMaxAmount("1,500,000");
        p.setStatusCode("ACT");
        p.setEffectiveDate("01/01/2020");
        p.setExpirationDate("12/31/2099");
        return p;
    }

    private LegacyLoanAccount createValidLoanAccount() {
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber("LN-2019-00142");
        a.setBorrowerId("B-10001");
        a.setBorrowerFirstName("James");
        a.setBorrowerLastName("Mitchell");
        a.setBorrowerSsnLast4("1234");
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
        p.setPaymentSequenceNumber("PMT-TEST001");
        p.setLoanAccountNumber("LN-2019-00142");
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
