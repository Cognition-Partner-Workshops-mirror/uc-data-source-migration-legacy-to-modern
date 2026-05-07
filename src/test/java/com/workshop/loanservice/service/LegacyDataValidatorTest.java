package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
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
    // Numeric Parsing Tests (ANO-002)
    // =========================================================================

    @Nested
    class SafeParseLegacyAmountTests {

        @Test
        void parsesValidAmountWithCommas() {
            BigDecimal result = validator.safeParseLegacyAmount("285,000", "field", "rec1");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void parsesValidAmountWithDecimal() {
            BigDecimal result = validator.safeParseLegacyAmount("1,487.02", "field", "rec1");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        void returnsZeroForNull() {
            BigDecimal result = validator.safeParseLegacyAmount(null, "field", "rec1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void returnsZeroForBlank() {
            BigDecimal result = validator.safeParseLegacyAmount("  ", "field", "rec1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void handlesUnparseableAmountWithCurrencySymbol() {
            BigDecimal result = validator.safeParseLegacyAmount("$285,000", "field", "rec1");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        void handlesTextPlaceholder() {
            BigDecimal result = validator.safeParseLegacyAmount("N/A", "field", "rec1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void handlesAccountingNegativeNotation() {
            BigDecimal result = validator.safeParseLegacyAmount("(1,487.02)", "field", "rec1");
            assertEquals(new BigDecimal("-1487.02"), result);
        }

        @Test
        void parsesPlainInteger() {
            BigDecimal result = validator.safeParseLegacyAmount("50000", "field", "rec1");
            assertEquals(new BigDecimal("50000"), result);
        }

        @Test
        void handlesDoubleDecimalGracefully() {
            BigDecimal result = validator.safeParseLegacyAmount("271,432..56", "field", "rec1");
            assertEquals(BigDecimal.ZERO, result);
        }
    }

    @Nested
    class SafeParseLegacyDecimalTests {

        @Test
        void parsesValidDecimal() {
            BigDecimal result = validator.safeParseLegacyDecimal("4.750", "field", "rec1");
            assertEquals(new BigDecimal("4.750"), result);
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyDecimal(null, "field", "rec1"));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyDecimal("", "field", "rec1"));
        }

        @Test
        void handlesUnparseableDecimal() {
            BigDecimal result = validator.safeParseLegacyDecimal("TBD", "field", "rec1");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        void trimsWhitespace() {
            BigDecimal result = validator.safeParseLegacyDecimal("  3.125  ", "field", "rec1");
            assertEquals(new BigDecimal("3.125"), result);
        }
    }

    @Nested
    class SafeParseLegacyIntegerTests {

        @Test
        void parsesValidInteger() {
            Integer result = validator.safeParseLegacyInteger("745", "field", "rec1");
            assertEquals(745, result);
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyInteger(null, "field", "rec1"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseLegacyInteger("", "field", "rec1"));
        }

        @Test
        void handlesUnparseableInteger() {
            Integer result = validator.safeParseLegacyInteger("N/A", "field", "rec1");
            assertNull(result);
        }

        @Test
        void trimsWhitespace() {
            Integer result = validator.safeParseLegacyInteger("  360  ", "field", "rec1");
            assertEquals(360, result);
        }

        @Test
        void handlesDecimalInIntegerField() {
            Integer result = validator.safeParseLegacyInteger("82.5", "field", "rec1");
            assertNull(result);
        }
    }

    // =========================================================================
    // Date Parsing Tests (ANO-008)
    // =========================================================================

    @Nested
    class SafeParseLegacyDateTests {

        @Test
        void parsesValidDate() {
            String result = validator.safeParseLegacyDate("03/15/1978", "field", "rec1");
            assertEquals("1978-03-15", result);
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyDate(null, "field", "rec1"));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseLegacyDate("  ", "field", "rec1"));
        }

        @Test
        void returnsRawStringForInvalidDate() {
            String result = validator.safeParseLegacyDate("13/32/2025", "field", "rec1");
            assertEquals("13/32/2025", result);
        }

        @Test
        void returnsRawStringForIsoFormat() {
            String result = validator.safeParseLegacyDate("2025-01-15", "field", "rec1");
            assertEquals("2025-01-15", result);
        }

        @Test
        void parsesDecemberDate() {
            String result = validator.safeParseLegacyDate("12/01/2025", "field", "rec1");
            assertEquals("2025-12-01", result);
        }
    }

    // =========================================================================
    // Name Joining Tests (ANO-009 — null handling)
    // =========================================================================

    @Nested
    class SafeJoinNameTests {

        @Test
        void joinsValidNames() {
            String result = validator.safeJoinName("James", "Mitchell", "rec1");
            assertEquals("James Mitchell", result);
        }

        @Test
        void handlesNullFirstName() {
            String result = validator.safeJoinName(null, "Mitchell", "rec1");
            assertEquals("Unknown Mitchell", result);
        }

        @Test
        void handlesNullLastName() {
            String result = validator.safeJoinName("James", null, "rec1");
            assertEquals("James Unknown", result);
        }

        @Test
        void handlesBothNull() {
            String result = validator.safeJoinName(null, null, "rec1");
            assertEquals("Unknown Unknown", result);
        }

        @Test
        void handlesBlankNames() {
            String result = validator.safeJoinName("  ", "", "rec1");
            assertEquals("Unknown Unknown", result);
        }
    }

    @Nested
    class SafeJoinFullNameTests {

        @Test
        void joinsWithMiddleInitial() {
            String result = validator.safeJoinFullName("James", "R", "Mitchell", "rec1");
            assertEquals("James R. Mitchell", result);
        }

        @Test
        void joinsWithoutMiddleInitial() {
            String result = validator.safeJoinFullName("Robert", null, "Williams", "rec1");
            assertEquals("Robert Williams", result);
        }

        @Test
        void handlesAllNull() {
            String result = validator.safeJoinFullName(null, null, null, "rec1");
            assertEquals("Unknown Unknown", result);
        }
    }

    // =========================================================================
    // Address Joining Tests
    // =========================================================================

    @Nested
    class SafeJoinAddressTests {

        @Test
        void joinsFullAddress() {
            String result = validator.safeJoinAddress("742 Elm Street", "Springfield", "IL", "62701", "rec1");
            assertEquals("742 Elm Street, Springfield, IL 62701", result);
        }

        @Test
        void handlesNullComponents() {
            String result = validator.safeJoinAddress(null, null, null, null, "rec1");
            assertEquals("Unknown Address, Unknown, ?? 00000", result);
        }
    }

    // =========================================================================
    // Borrower Validation Tests (ANO-009, ANO-004)
    // =========================================================================

    @Nested
    class ValidateBorrowerTests {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "R",
                    "ENC_XXX", "03/15/1978", "j@email.com", "745", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void missingFirstNameProducesWarning() {
            LegacyBorrower b = buildBorrower("B-10001", null, "Mitchell", "R",
                    "ENC_XXX", "03/15/1978", "j@email.com", "745", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing first name")));
        }

        @Test
        void missingLastNameProducesWarning() {
            LegacyBorrower b = buildBorrower("B-10001", "James", null, "R",
                    "ENC_XXX", "03/15/1978", "j@email.com", "745", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing last name")));
        }

        @Test
        void missingSsnProducesWarning() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "R",
                    null, "03/15/1978", "j@email.com", "745", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing SSN")));
        }

        @Test
        void missingEmailProducesWarning() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "R",
                    "ENC_XXX", "03/15/1978", null, "745", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing email")));
        }

        @Test
        void creditScoreOutOfRangeProducesWarning() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "R",
                    "ENC_XXX", "03/15/1978", "j@email.com", "200", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("credit score out of range")));
        }

        @Test
        void creditScoreAboveRangeProducesWarning() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "R",
                    "ENC_XXX", "03/15/1978", "j@email.com", "900", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("credit score out of range")));
        }

        @Test
        void invalidDateFormatProducesWarning() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "R",
                    "ENC_XXX", "1978-03-15", "j@email.com", "745", "ACT");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("invalid date")));
        }

        @Test
        void unrecognizedStatusCodeProducesWarning() {
            LegacyBorrower b = buildBorrower("B-10001", "James", "Mitchell", "R",
                    "ENC_XXX", "03/15/1978", "j@email.com", "745", "XYZ");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized status code")));
        }
    }

    // =========================================================================
    // Loan Account Validation Tests (ANO-003, ANO-006)
    // =========================================================================

    @Nested
    class ValidateLoanAccountTests {

        private final Set<String> validBorrowerIds = Set.of("B-10001", "B-10002");
        private final Set<String> validProductCodes = Set.of("FXD30", "FXD15", "ARM51");

        @Test
        void validLoanProducesNoWarnings() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001", "James", "Mitchell",
                    "FXD30", "ACT", "0", "SFR", "02/15/2019", "02/15/2049");
            List<String> warnings = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void orphanedBorrowerReferenceProducesWarning() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-99999", "Ghost", "Borrower",
                    "FXD30", "ACT", "0", "SFR", "02/15/2019", "02/15/2049");
            List<String> warnings = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("orphaned borrower reference")));
        }

        @Test
        void orphanedProductReferenceProducesWarning() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001", "James", "Mitchell",
                    "JUMBO", "ACT", "0", "SFR", "02/15/2019", "02/15/2049");
            List<String> warnings = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("orphaned product reference")));
        }

        @Test
        void unrecognizedStatusCodeProducesWarning() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001", "James", "Mitchell",
                    "FXD30", "BAD", "0", "SFR", "02/15/2019", "02/15/2049");
            List<String> warnings = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized status code")));
        }

        @Test
        void unrecognizedPropertyTypeProducesWarning() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001", "James", "Mitchell",
                    "FXD30", "ACT", "0", "XXX", "02/15/2019", "02/15/2049");
            List<String> warnings = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized property type")));
        }

        @Test
        void delinquentLoanWithActiveStatusProducesWarning() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001", "James", "Mitchell",
                    "FXD30", "ACT", "15", "SFR", "02/15/2019", "02/15/2049");
            List<String> warnings = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("delinquent") && w.contains("ACT")));
        }

        @Test
        void missingBorrowerNameProducesWarning() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001", null, "Mitchell",
                    "FXD30", "ACT", "0", "SFR", "02/15/2019", "02/15/2049");
            List<String> warnings = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("missing denormalized borrower name")));
        }

        @Test
        void invalidOriginationDateProducesWarning() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001", "James", "Mitchell",
                    "FXD30", "ACT", "0", "SFR", "2019-02-15", "02/15/2049");
            List<String> warnings = validator.validateLoanAccount(acct, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("invalid date")));
        }
    }

    // =========================================================================
    // Payment Validation Tests (ANO-001, ANO-003)
    // =========================================================================

    @Nested
    class ValidatePaymentTests {

        private final Set<String> validLoanAccounts = Set.of("LN-2019-00142", "LN-2020-00398");

        @Test
        void validPaymentProducesNoWarnings() {
            LegacyPayment pmt = buildPayment("PMT-001", "LN-2019-00142",
                    "12/01/2025", "2,924.18", "1,842.56", "815.50", "266.12", "0.00",
                    "REG", "PST");
            List<String> warnings = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void paymentComponentSumMismatchProducesWarning() {
            LegacyPayment pmt = buildPayment("PMT-001", "LN-2019-00142",
                    "12/15/2025", "1,487.02", "456.78", "1,074.69", "355.55", "0.00",
                    "REG", "PST");
            List<String> warnings = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum")));
        }

        @Test
        void lateFeeNotInTotalProducesWarning() {
            LegacyPayment pmt = buildPayment("PMT-002", "LN-2019-00142",
                    "11/01/2025", "1,077.05", "295.82", "781.23", "0.00", "47.50",
                    "REG", "PST");
            List<String> warnings = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum")));
        }

        @Test
        void orphanedLoanReferenceProducesWarning() {
            LegacyPayment pmt = buildPayment("PMT-001", "LN-DELETED",
                    "12/01/2025", "100.00", "50.00", "50.00", "0.00", "0.00",
                    "REG", "PST");
            List<String> warnings = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("orphaned loan reference")));
        }

        @Test
        void unrecognizedStatusCodeProducesWarning() {
            LegacyPayment pmt = buildPayment("PMT-001", "LN-2019-00142",
                    "12/01/2025", "100.00", "50.00", "50.00", "0.00", "0.00",
                    "REG", "BAD");
            List<String> warnings = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized status code")));
        }

        @Test
        void unrecognizedTypeCodeProducesWarning() {
            LegacyPayment pmt = buildPayment("PMT-001", "LN-2019-00142",
                    "12/01/2025", "100.00", "50.00", "50.00", "0.00", "0.00",
                    "BAD", "PST");
            List<String> warnings = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized type code")));
        }

        @Test
        void invalidPaymentDateProducesWarning() {
            LegacyPayment pmt = buildPayment("PMT-001", "LN-2019-00142",
                    "13/32/2025", "100.00", "50.00", "50.00", "0.00", "0.00",
                    "REG", "PST");
            List<String> warnings = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("invalid date")));
        }

        @Test
        void balancedPaymentWithinToleranceProducesNoWarning() {
            LegacyPayment pmt = buildPayment("PMT-001", "LN-2019-00142",
                    "12/01/2025", "100.01", "50.00", "50.00", "0.00", "0.00",
                    "REG", "PST");
            List<String> warnings = validator.validatePayment(pmt, validLoanAccounts);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("component sum")));
        }
    }

    // =========================================================================
    // Helper Methods
    // =========================================================================

    private LegacyBorrower buildBorrower(String id, String first, String last, String middle,
                                         String ssn, String dob, String email, String creditScore,
                                         String status) {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId(id);
        b.setFirstName(first);
        b.setLastName(last);
        b.setMiddleInitial(middle);
        b.setSsnEncrypted(ssn);
        b.setDateOfBirth(dob);
        b.setEmail(email);
        b.setCreditScore(creditScore);
        b.setStatusCode(status);
        b.setCreatedDate("01/01/2020");
        return b;
    }

    private LegacyLoanAccount buildLoanAccount(String loanNumber, String borrowerId,
                                                String borrowerFirst, String borrowerLast,
                                                String productCode, String status,
                                                String delinquencyDays, String propertyType,
                                                String origDate, String matDate) {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber(loanNumber);
        acct.setBorrowerId(borrowerId);
        acct.setBorrowerFirstName(borrowerFirst);
        acct.setBorrowerLastName(borrowerLast);
        acct.setProductCode(productCode);
        acct.setStatusCode(status);
        acct.setDelinquencyDays(delinquencyDays);
        acct.setPropertyType(propertyType);
        acct.setOriginationDate(origDate);
        acct.setMaturityDate(matDate);
        acct.setOriginalAmount("285,000");
        acct.setCurrentBalance("271,432.56");
        acct.setInterestRate("4.750");
        acct.setMonthlyPayment("1,487.02");
        acct.setPropertyAddress("742 Elm Street");
        acct.setPropertyCity("Springfield");
        acct.setPropertyState("IL");
        acct.setPropertyZip("62701");
        return acct;
    }

    private LegacyPayment buildPayment(String seqNumber, String loanAccount,
                                        String paymentDate, String total,
                                        String principal, String interest,
                                        String escrow, String lateFee,
                                        String typeCode, String statusCode) {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber(seqNumber);
        pmt.setLoanAccountNumber(loanAccount);
        pmt.setPaymentDate(paymentDate);
        pmt.setTotalAmount(total);
        pmt.setPrincipalAmount(principal);
        pmt.setInterestAmount(interest);
        pmt.setEscrowAmount(escrow);
        pmt.setLateFee(lateFee);
        pmt.setTypeCode(typeCode);
        pmt.setStatusCode(statusCode);
        pmt.setReceivedDate("12/01/2025");
        pmt.setProcessedDate("12/01/2025");
        pmt.setCreatedDate("12/01/2025");
        pmt.setUpdatedDate("12/01/2025");
        return pmt;
    }
}
