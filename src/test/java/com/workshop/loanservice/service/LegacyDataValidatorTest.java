package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANO-003: Numeric string parsing with error handling
    // =========================================================================

    @Nested
    class SafeParseLegacyAmount {

        @Test
        void parsesCommaFormattedAmount() {
            assertEquals(new BigDecimal("285000"), validator.safeParseLegacyAmount("285,000"));
        }

        @Test
        void parsesDecimalAmount() {
            assertEquals(new BigDecimal("1487.02"), validator.safeParseLegacyAmount("1,487.02"));
        }

        @Test
        void parsesAmountWithDollarSign() {
            assertEquals(new BigDecimal("285000"), validator.safeParseLegacyAmount("$285,000"));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount(null));
        }

        @Test
        void returnsZeroForBlank() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount(""));
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount("   "));
        }

        @Test
        void returnsZeroForMalformedInput() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount("N/A"));
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount("abc"));
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyAmount("12.34.56"));
        }

        @Test
        void stripsDoubleCommasSuccessfully() {
            // "1,,487.02" → commas removed → "1487.02" — parseable
            assertEquals(new BigDecimal("1487.02"), validator.safeParseLegacyAmount("1,,487.02"));
        }
    }

    @Nested
    class SafeParseLegacyDecimal {

        @Test
        void parsesDecimalString() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseLegacyDecimal("4.750"));
        }

        @Test
        void parsesWithLeadingTrailingSpaces() {
            assertEquals(new BigDecimal("82.5"), validator.safeParseLegacyDecimal("  82.5  "));
        }

        @Test
        void returnsZeroForNull() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyDecimal(null));
        }

        @Test
        void returnsZeroForMalformed() {
            assertEquals(BigDecimal.ZERO, validator.safeParseLegacyDecimal("N/A"));
        }
    }

    @Nested
    class SafeParseLegacyInteger {

        @Test
        void parsesIntegerString() {
            assertEquals(745, validator.safeParseLegacyInteger("745"));
        }

        @Test
        void parsesWithSpaces() {
            assertEquals(780, validator.safeParseLegacyInteger("  780  "));
        }

        @Test
        void parsesCommaFormatted() {
            assertEquals(1500, validator.safeParseLegacyInteger("1,500"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyInteger(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseLegacyInteger(""));
        }

        @Test
        void returnsNullForMalformed() {
            assertNull(validator.safeParseLegacyInteger("N/A"));
            assertNull(validator.safeParseLegacyInteger("abc"));
        }
    }

    // =========================================================================
    // ANO-008: Date format validation
    // =========================================================================

    @Nested
    class DateParsing {

        @Test
        void parsesValidLegacyDate() {
            assertNotNull(validator.safeParseLegacyDate("03/15/1978"));
            assertEquals("1978-03-15", validator.safeParseLegacyDate("03/15/1978").toString());
        }

        @Test
        void returnsNullForInvalidDate() {
            assertNull(validator.safeParseLegacyDate("2025-01-15"));
            assertNull(validator.safeParseLegacyDate("15/03/1978"));
        }

        @Test
        void returnsNullForNullDate() {
            assertNull(validator.safeParseLegacyDate(null));
        }

        @Test
        void formatsDateForApi() {
            assertEquals("2019-02-15", validator.formatDateForApi("02/15/2019"));
        }

        @Test
        void passesThrough_whenUnparseable() {
            assertEquals("bad-date", validator.formatDateForApi("bad-date"));
        }
    }

    // =========================================================================
    // ANO-004 / ANO-010: Null-safe string handling
    // =========================================================================

    @Nested
    class StringHelpers {

        @Test
        void safeStringReturnsFallbackForNull() {
            assertEquals("[Unknown]", validator.safeString(null, "[Unknown]"));
        }

        @Test
        void safeStringReturnsFallbackForBlank() {
            assertEquals("[Unknown]", validator.safeString("", "[Unknown]"));
        }

        @Test
        void safeStringReturnsValueWhenPresent() {
            assertEquals("James", validator.safeString("James", "[Unknown]"));
        }

        @Test
        void buildFullNameHandlesAllFieldsPresent() {
            assertEquals("James R. Mitchell", validator.buildFullName("James", "R", "Mitchell"));
        }

        @Test
        void buildFullNameHandlesNullMiddleInitial() {
            assertEquals("Robert Williams", validator.buildFullName("Robert", null, "Williams"));
        }

        @Test
        void buildFullNameHandlesNullFirstName() {
            assertEquals("[Unknown] R. Mitchell", validator.buildFullName(null, "R", "Mitchell"));
        }

        @Test
        void buildFullNameHandlesNullLastName() {
            assertEquals("James R. [Unknown]", validator.buildFullName("James", "R", null));
        }

        @Test
        void buildBorrowerNameHandlesNulls() {
            assertEquals("[Unknown] Mitchell", validator.buildBorrowerName(null, "Mitchell"));
            assertEquals("James [Unknown]", validator.buildBorrowerName("James", null));
        }

        @Test
        void buildPropertyAddressHandlesNulls() {
            String result = validator.buildPropertyAddress(null, "Springfield", "IL", "62701");
            assertEquals(", Springfield, IL 62701", result);
        }

        @Test
        void buildPropertyAddressAllPresent() {
            String result = validator.buildPropertyAddress("742 Elm Street", "Springfield", "IL", "62701");
            assertEquals("742 Elm Street, Springfield, IL 62701", result);
        }
    }

    // =========================================================================
    // ANO-004: Borrower validation — null required fields, credit score range
    // =========================================================================

    @Nested
    class BorrowerValidation {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower b = createBorrower("B-10001", "James", "Mitchell", "745", "03/15/1978");
            List<String> warnings = validator.validateBorrower(b);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void nullFirstNameProducesWarning() {
            LegacyBorrower b = createBorrower("B-10001", null, "Mitchell", "745", "03/15/1978");
            List<String> warnings = validator.validateBorrower(b);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("first name is null/blank"));
        }

        @Test
        void nullLastNameProducesWarning() {
            LegacyBorrower b = createBorrower("B-10001", "James", null, "745", "03/15/1978");
            List<String> warnings = validator.validateBorrower(b);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("last name is null/blank"));
        }

        @Test
        void creditScoreOutOfRangeProducesWarning() {
            LegacyBorrower b = createBorrower("B-10001", "James", "Mitchell", "200", "03/15/1978");
            List<String> warnings = validator.validateBorrower(b);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("credit score"));
            assertTrue(warnings.get(0).contains("outside valid range"));
        }

        @Test
        void creditScoreAboveMaxProducesWarning() {
            LegacyBorrower b = createBorrower("B-10001", "James", "Mitchell", "900", "03/15/1978");
            List<String> warnings = validator.validateBorrower(b);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("outside valid range"));
        }

        @Test
        void invalidDateOfBirthProducesWarning() {
            LegacyBorrower b = createBorrower("B-10001", "James", "Mitchell", "745", "1978-03-15");
            List<String> warnings = validator.validateBorrower(b);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("unparseable date of birth"));
        }

        private LegacyBorrower createBorrower(String id, String first, String last,
                                               String creditScore, String dob) {
            LegacyBorrower b = new LegacyBorrower();
            b.setBorrowerId(id);
            b.setFirstName(first);
            b.setLastName(last);
            b.setCreditScore(creditScore);
            b.setDateOfBirth(dob);
            return b;
        }
    }

    // =========================================================================
    // ANO-005: Delinquency vs. status inconsistency
    // ANO-009: LTV calculation discrepancy
    // =========================================================================

    @Nested
    class LoanAccountValidation {

        @Test
        void validLoanProducesNoWarnings() {
            LegacyLoanAccount acct = createLoanAccount("ACT", "0", "195,000", "260,000", "75.0");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void delinquentDaysWithActiveStatusProducesWarning() {
            LegacyLoanAccount acct = createLoanAccount("ACT", "15", "195,000", "260,000", "75.0");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("delinquency days but status is ACT")));
        }

        @Test
        void zeroDelinquencyDaysNoWarning() {
            LegacyLoanAccount acct = createLoanAccount("ACT", "0", "195,000", "260,000", "75.0");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("delinquency")));
        }

        @Test
        void ltvDiscrepancyOverThresholdProducesWarning() {
            // original=100,000 appraised=200,000 → calc LTV=50.0, stored=55.0 → diff=5.0 > 0.5
            LegacyLoanAccount acct = createLoanAccount("ACT", "0", "100,000", "200,000", "55.0");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("stored LTV") && w.contains("differs")));
        }

        @Test
        void ltvMinorRoundingNoWarning() {
            // original=285,000 appraised=345,000 → calc LTV=82.6, stored=82.5 → diff=0.1 < 0.5
            LegacyLoanAccount acct = createLoanAccount("ACT", "0", "285,000", "345,000", "82.5");
            List<String> warnings = validator.validateLoanAccount(acct);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("LTV")));
        }

        private LegacyLoanAccount createLoanAccount(String status, String dlqDays,
                                                     String origAmt, String appraisedVal, String ltv) {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST-001");
            acct.setStatusCode(status);
            acct.setDelinquencyDays(dlqDays);
            acct.setOriginalAmount(origAmt);
            acct.setAppraisedValue(appraisedVal);
            acct.setLtvPercent(ltv);
            return acct;
        }
    }

    // =========================================================================
    // ANO-001: Payment component arithmetic mismatch
    // =========================================================================

    @Nested
    class PaymentValidation {

        @Test
        void balancedPaymentProducesNoWarnings() {
            // 2924.18 = 1842.56 + 815.50 + 266.12 + 0.00
            LegacyPayment pmt = createPayment("PMT-001", "2,924.18",
                    "1,842.56", "815.50", "266.12", "0.00", "12/01/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void unbalancedPaymentProducesWarning() {
            // total=1,487.02 but components sum to 1,887.02 — off by 400
            LegacyPayment pmt = createPayment("PMT-2025120001", "1,487.02",
                    "456.78", "1,074.69", "355.55", "0.00", "12/15/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("component sum"));
            assertTrue(warnings.get(0).contains("differs from total"));
        }

        @Test
        void lateFeeNotInTotalProducesWarning() {
            // total=1,077.05 but components=295.82+781.23+0+47.50=1,124.55
            LegacyPayment pmt = createPayment("PMT-2025110003", "1,077.05",
                    "295.82", "781.23", "0.00", "47.50", "11/01/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("differs from total"));
        }

        @Test
        void invalidPaymentDateProducesWarning() {
            LegacyPayment pmt = createPayment("PMT-001", "1,000.00",
                    "500.00", "500.00", "0.00", "0.00", "2025-12-01");
            List<String> warnings = validator.validatePayment(pmt);
            assertEquals(1, warnings.size());
            assertTrue(warnings.get(0).contains("unparseable payment date"));
        }

        @Test
        void toleratesRoundingWithinPenny() {
            // Components sum to 1000.01, total is 1000.00 → within tolerance
            LegacyPayment pmt = createPayment("PMT-001", "1,000.00",
                    "500.005", "500.005", "0.00", "0.00", "12/01/2025");
            List<String> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.isEmpty());
        }

        private LegacyPayment createPayment(String id, String total,
                                             String principal, String interest,
                                             String escrow, String lateFee, String date) {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber(id);
            pmt.setLoanAccountNumber("LN-TEST-001");
            pmt.setTotalAmount(total);
            pmt.setPrincipalAmount(principal);
            pmt.setInterestAmount(interest);
            pmt.setEscrowAmount(escrow);
            pmt.setLateFee(lateFee);
            pmt.setPaymentDate(date);
            return pmt;
        }
    }

    // =========================================================================
    // ANO-002: SSN last-4 cross-validation
    // =========================================================================

    @Nested
    class SsnCrossValidation {

        @Test
        void detectsSsnMatchingPhoneSuffix() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST-001");
            acct.setBorrowerSsnLast4("0142");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setPhoneNumber("217-555-0142");

            // Should log a warning (no exception thrown)
            assertDoesNotThrow(() -> validator.crossValidateSsnLast4(acct, borrower));
        }

        @Test
        void noIssueWhenSsnDoesNotMatchPhone() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST-001");
            acct.setBorrowerSsnLast4("9999");

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setPhoneNumber("217-555-0142");

            assertDoesNotThrow(() -> validator.crossValidateSsnLast4(acct, borrower));
        }

        @Test
        void handlesNullSsnGracefully() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-TEST-001");
            acct.setBorrowerSsnLast4(null);

            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setPhoneNumber("217-555-0142");

            assertDoesNotThrow(() -> validator.crossValidateSsnLast4(acct, borrower));
        }
    }

    // =========================================================================
    // Status code expansion with validation
    // =========================================================================

    @Nested
    class StatusCodeExpansion {

        @Test
        void expandsKnownLoanStatuses() {
            assertEquals("Active", validator.expandLoanStatus("ACT"));
            assertEquals("Closed", validator.expandLoanStatus("CLO"));
            assertEquals("Default", validator.expandLoanStatus("DFT"));
            assertEquals("Forbearance", validator.expandLoanStatus("FRB"));
        }

        @Test
        void returnsUnknownForNullLoanStatus() {
            assertEquals("Unknown", validator.expandLoanStatus(null));
        }

        @Test
        void passesUnrecognizedLoanStatusThrough() {
            assertEquals("XYZ", validator.expandLoanStatus("XYZ"));
        }

        @Test
        void expandsKnownPropertyTypes() {
            assertEquals("Single Family Residence", validator.expandPropertyType("SFR"));
            assertEquals("Condominium", validator.expandPropertyType("CND"));
            assertEquals("Multi-Family Residence", validator.expandPropertyType("MFR"));
            assertEquals("Townhouse", validator.expandPropertyType("TWN"));
        }

        @Test
        void expandsKnownPaymentTypes() {
            assertEquals("Regular", validator.expandPaymentType("REG"));
            assertEquals("Extra", validator.expandPaymentType("EXT"));
            assertEquals("Partial", validator.expandPaymentType("PRT"));
            assertEquals("Prepayment", validator.expandPaymentType("PRE"));
        }

        @Test
        void expandsKnownPaymentStatuses() {
            assertEquals("Posted", validator.expandPaymentStatus("PST"));
            assertEquals("Reversed", validator.expandPaymentStatus("REV"));
            assertEquals("Non-Sufficient Funds", validator.expandPaymentStatus("NSF"));
            assertEquals("Pending", validator.expandPaymentStatus("PND"));
        }

        @Test
        void returnsUnknownForNullPaymentStatus() {
            assertEquals("Unknown", validator.expandPaymentStatus(null));
            assertEquals("Unknown", validator.expandPaymentType(null));
            assertEquals("Unknown", validator.expandPropertyType(null));
        }
    }
}
