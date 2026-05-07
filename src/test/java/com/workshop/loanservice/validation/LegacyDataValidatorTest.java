package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
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
    // Safe parsing utilities
    // =========================================================================

    @Nested
    class SafeParseAmountTests {

        @Test
        void parsesAmountWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("285,000"));
        }

        @Test
        void parsesAmountWithCommasAndDecimals() {
            assertEquals(new BigDecimal("1487.02"), validator.safeParseAmount("1,487.02"));
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
        void returnsNullForNonNumeric() {
            assertNull(validator.safeParseAmount("N/A"));
        }

        @Test
        void returnsNullForCurrencySymbol() {
            assertNull(validator.safeParseAmount("$285,000"));
        }
    }

    @Nested
    class SafeParseDecimalTests {

        @Test
        void parsesDecimalString() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseDecimal("4.750"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseDecimal(null));
        }

        @Test
        void returnsNullForNonNumeric() {
            assertNull(validator.safeParseDecimal("TBD"));
        }

        @Test
        void handlesLeadingTrailingSpaces() {
            assertEquals(new BigDecimal("5.250"), validator.safeParseDecimal(" 5.250 "));
        }
    }

    @Nested
    class SafeParseIntegerTests {

        @Test
        void parsesIntegerString() {
            assertEquals(745, validator.safeParseInteger("745"));
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
            assertNull(validator.safeParseInteger("750+"));
        }

        @Test
        void handlesLeadingTrailingSpaces() {
            assertEquals(360, validator.safeParseInteger(" 360 "));
        }
    }

    @Nested
    class SafeParseLegacyDateTests {

        @Test
        void parsesMMDDYYYY() {
            assertEquals(LocalDate.of(1978, 3, 15), validator.safeParseLegacyDate("03/15/1978"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyDate(null));
        }

        @Test
        void returnsNullForISOFormat() {
            assertNull(validator.safeParseLegacyDate("2025-12-01"));
        }

        @Test
        void returnsNullForInvalidDate() {
            // "13/01/2025" has an invalid month (13), which strict parsing rejects
            assertNull(validator.safeParseLegacyDate("13/01/2025"));
        }

        @Test
        void returnsNullForGarbage() {
            assertNull(validator.safeParseLegacyDate("not-a-date"));
        }
    }

    @Nested
    class SafeStringTests {

        @Test
        void returnsValueWhenNotNull() {
            assertEquals("hello", validator.safeString("hello", "fallback"));
        }

        @Test
        void returnsFallbackWhenNull() {
            assertEquals("fallback", validator.safeString(null, "fallback"));
        }
    }

    // =========================================================================
    // Borrower validation
    // =========================================================================

    @Nested
    class ValidateBorrowerTests {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower b = buildValidBorrower();
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.isEmpty(), "Expected no warnings, got: " + warnings);
        }

        @Test
        void detectsNullFirstName() {
            LegacyBorrower b = buildValidBorrower();
            b.setFirstName(null);
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("first name")));
        }

        @Test
        void detectsNullLastName() {
            LegacyBorrower b = buildValidBorrower();
            b.setLastName(null);
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("last name")));
        }

        @Test
        void detectsNullEmail() {
            LegacyBorrower b = buildValidBorrower();
            b.setEmail(null);
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("email")));
        }

        @Test
        void detectsNonNumericCreditScore() {
            LegacyBorrower b = buildValidBorrower();
            b.setCreditScore("PENDING");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("credit score") && w.contains("not a valid integer")));
        }

        @Test
        void detectsCreditScoreOutOfRange() {
            LegacyBorrower b = buildValidBorrower();
            b.setCreditScore("200");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("outside valid range")));
        }

        @Test
        void detectsCreditScoreAboveMax() {
            LegacyBorrower b = buildValidBorrower();
            b.setCreditScore("900");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("outside valid range")));
        }

        @Test
        void detectsUnparseableIncome() {
            LegacyBorrower b = buildValidBorrower();
            b.setAnnualIncome("$92,500");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("annual income") && w.contains("not parseable")));
        }

        @Test
        void detectsInvalidDateOfBirth() {
            LegacyBorrower b = buildValidBorrower();
            b.setDateOfBirth("1978-03-15");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("date of birth") && w.contains("MM/DD/YYYY")));
        }

        @Test
        void detectsUnknownEmploymentStatus() {
            LegacyBorrower b = buildValidBorrower();
            b.setEmploymentStatus("FREELANCE");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("employment status")));
        }

        @Test
        void acceptsNullMiddleInitial() {
            LegacyBorrower b = buildValidBorrower();
            b.setMiddleInitial(null);
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.isEmpty());
        }
    }

    // =========================================================================
    // Loan account validation
    // =========================================================================

    @Nested
    class ValidateLoanAccountTests {

        @Test
        void validLoanProducesNoWarningsExceptSsnPhoneMatch() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            LegacyBorrower borrower = buildValidBorrower();
            List<String> warnings = validator.validateLoanAccount(acct, borrower);
            // The valid test data has SSN last-4 matching phone last-4
            assertTrue(warnings.stream().anyMatch(w -> w.contains("SSN_LST4")));
            // But no other warnings besides the SSN phone match
            long nonSsnWarnings = warnings.stream().filter(w -> !w.contains("SSN_LST4")).count();
            assertEquals(0, nonSsnWarnings, "Expected only SSN warning, got: " + warnings);
        }

        @Test
        void detectsNullBorrowerId() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setBorrowerId(null);
            List<String> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("borrower ID")));
        }

        @Test
        void detectsNullProductCode() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setProductCode(null);
            List<String> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("product code")));
        }

        @Test
        void detectsUnparseableOriginalAmount() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setOriginalAmount("UNKNOWN");
            List<String> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("original amount") && w.contains("not parseable")));
        }

        @Test
        void detectsDelinquencyStatusMismatch() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setDelinquencyDays("15");
            acct.setStatusCode("ACT");
            List<String> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("delinquency") && w.contains("mismatch")));
        }

        @Test
        void noDelinquencyWarningWhenZeroDays() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setDelinquencyDays("0");
            acct.setStatusCode("ACT");
            List<String> warnings = validator.validateLoanAccount(acct, null);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("delinquency")));
        }

        @Test
        void detectsUnknownLoanStatus() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setStatusCode("BKR");
            List<String> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unknown status code")));
        }

        @Test
        void detectsUnknownPropertyType() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setPropertyType("MOB");
            List<String> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unknown property type")));
        }

        @Test
        void detectsSsnMatchingPhoneLast4() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setBorrowerSsnLast4("0142");
            LegacyBorrower borrower = buildValidBorrower();
            borrower.setPhoneNumber("217-555-0142");
            List<String> warnings = validator.validateLoanAccount(acct, borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("SSN_LST4") && w.contains("phone")));
        }

        @Test
        void noSsnWarningWhenNotMatchingPhone() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setBorrowerSsnLast4("9999");
            LegacyBorrower borrower = buildValidBorrower();
            borrower.setPhoneNumber("217-555-0142");
            List<String> warnings = validator.validateLoanAccount(acct, borrower);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("SSN_LST4")));
        }

        @Test
        void detectsBorrowerNameDrift() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setBorrowerFirstName("Jim");
            LegacyBorrower borrower = buildValidBorrower();
            borrower.setPhoneNumber("111-222-3333"); // avoid SSN match
            acct.setBorrowerSsnLast4("0142");
            List<String> warnings = validator.validateLoanAccount(acct, borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("denormalized first name") && w.contains("differs")));
        }

        @Test
        void detectsInvalidDate() {
            LegacyLoanAccount acct = buildValidLoanAccount();
            acct.setOriginationDate("2019-02-15");
            List<String> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("origination date") && w.contains("MM/DD/YYYY")));
        }
    }

    // =========================================================================
    // Payment validation
    // =========================================================================

    @Nested
    class ValidatePaymentTests {

        @Test
        void validPaymentProducesNoWarnings() {
            LegacyPayment pmt = buildValidPayment();
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.isEmpty(), "Expected no warnings, got: " + warnings);
        }

        @Test
        void detectsNullLoanAccountNumber() {
            LegacyPayment pmt = buildValidPayment();
            pmt.setLoanAccountNumber(null);
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("loan account number")));
        }

        @Test
        void detectsComponentSumMismatch() {
            LegacyPayment pmt = buildValidPayment();
            // Total = 1487.02, but components sum to 1887.02
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            pmt.setLateFee("0.00");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum") && w.contains("!= total")));
        }

        @Test
        void noMismatchWarningWhenComponentsBalance() {
            LegacyPayment pmt = buildValidPayment();
            // Total = 2924.18, components = 1842.56 + 815.50 + 266.12 + 0 = 2924.18
            pmt.setTotalAmount("2,924.18");
            pmt.setPrincipalAmount("1,842.56");
            pmt.setInterestAmount("815.50");
            pmt.setEscrowAmount("266.12");
            pmt.setLateFee("0.00");
            List<String> warnings = validator.validatePayment(pmt);
            assertFalse(warnings.stream().anyMatch(w -> w.contains("component sum")));
        }

        @Test
        void detectsUnknownPaymentStatus() {
            LegacyPayment pmt = buildValidPayment();
            pmt.setStatusCode("XYZ");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unknown status code")));
        }

        @Test
        void detectsUnknownPaymentType() {
            LegacyPayment pmt = buildValidPayment();
            pmt.setTypeCode("ADJ");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unknown payment type")));
        }

        @Test
        void detectsUnparseableTotalAmount() {
            LegacyPayment pmt = buildValidPayment();
            pmt.setTotalAmount("N/A");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("total amount") && w.contains("not parseable")));
        }

        @Test
        void detectsInvalidPaymentDate() {
            LegacyPayment pmt = buildValidPayment();
            pmt.setPaymentDate("2025-12-15");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("payment date") && w.contains("MM/DD/YYYY")));
        }
    }

    // =========================================================================
    // Test data builders
    // =========================================================================

    private LegacyBorrower buildValidBorrower() {
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

    private LegacyLoanAccount buildValidLoanAccount() {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber("LN-2019-00142");
        acct.setBorrowerId("B-10001");
        acct.setBorrowerFirstName("James");
        acct.setBorrowerLastName("Mitchell");
        acct.setBorrowerSsnLast4("0142");
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

    private LegacyPayment buildValidPayment() {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber("PMT-2025120002");
        pmt.setLoanAccountNumber("LN-2020-00398");
        pmt.setPaymentDate("12/01/2025");
        pmt.setTotalAmount("2,924.18");
        pmt.setPrincipalAmount("1,842.56");
        pmt.setInterestAmount("815.50");
        pmt.setEscrowAmount("266.12");
        pmt.setLateFee("0.00");
        pmt.setTypeCode("REG");
        pmt.setStatusCode("PST");
        pmt.setReceivedDate("11/30/2025");
        pmt.setProcessedDate("12/01/2025");
        pmt.setCreatedDate("12/01/2025");
        pmt.setUpdatedDate("12/01/2025");
        return pmt;
    }
}
