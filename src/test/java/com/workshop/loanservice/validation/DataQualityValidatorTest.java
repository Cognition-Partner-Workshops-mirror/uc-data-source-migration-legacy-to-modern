package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for DataQualityValidator — verifies that each anomaly type
 * documented in docs/DATA_ANOMALY_REPORT.md is detected at ingestion time.
 */
class DataQualityValidatorTest {

    private DataQualityValidator validator;

    @BeforeEach
    void setUp() {
        validator = new DataQualityValidator();
    }

    // =========================================================================
    // Helper methods to create valid baseline entities for testing
    // =========================================================================

    /** Creates a valid borrower with all required fields populated. */
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

    /** Creates a valid loan account with all required fields populated. */
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

    /** Creates a valid payment with components that sum to the total. */
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

    // =========================================================================
    // ANOM-001: Payment component mismatch
    // =========================================================================

    @Nested
    @DisplayName("ANOM-001: Payment Component Mismatch")
    class PaymentComponentMismatchTests {

        @Test
        @DisplayName("Detects when principal + interest + escrow != total")
        void detectsComponentMismatch() {
            LegacyPayment pmt = createValidPayment();
            // Set components that don't sum to total (matches seed data anomaly)
            pmt.setPaymentSequenceNumber("PMT-2025120001");
            pmt.setLoanAccountNumber("LN-2019-00142");
            pmt.setTotalAmount("1,487.02");
            pmt.setPrincipalAmount("456.78");
            pmt.setInterestAmount("1,074.69");
            pmt.setEscrowAmount("355.55");
            // Sum = 456.78 + 1074.69 + 355.55 = 1887.02, but total = 1487.02

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i -> i.contains("Component mismatch")),
                    "Should detect payment component mismatch: " + issues);
        }

        @Test
        @DisplayName("Accepts payment where components sum correctly")
        void acceptsValidPaymentComponents() {
            LegacyPayment pmt = createValidPayment();
            // Sum: 1842.56 + 815.50 + 266.12 = 2924.18 = total

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().noneMatch(i -> i.contains("Component mismatch")),
                    "Valid payment should not trigger mismatch: " + issues);
        }
    }

    // =========================================================================
    // ANOM-002: Null required fields
    // =========================================================================

    @Nested
    @DisplayName("ANOM-002: Null Required Fields")
    class NullRequiredFieldTests {

        @Test
        @DisplayName("Detects null first name on borrower")
        void detectsNullBorrowerFirstName() {
            LegacyBorrower b = createValidBorrower();
            b.setFirstName(null);

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_FST_NM") && i.contains("null/blank")),
                    "Should detect null first name: " + issues);
        }

        @Test
        @DisplayName("Detects null last name on borrower")
        void detectsNullBorrowerLastName() {
            LegacyBorrower b = createValidBorrower();
            b.setLastName(null);

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_LST_NM") && i.contains("null/blank")),
                    "Should detect null last name: " + issues);
        }

        @Test
        @DisplayName("Detects null SSN on borrower")
        void detectsNullBorrowerSsn() {
            LegacyBorrower b = createValidBorrower();
            b.setSsnEncrypted(null);

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_SSN_ENCR") && i.contains("null/blank")),
                    "Should detect null SSN: " + issues);
        }

        @Test
        @DisplayName("Detects null borrower ID on loan account")
        void detectsNullLoanBorrowerId() {
            LegacyLoanAccount a = createValidLoanAccount();
            a.setBorrowerId(null);

            List<String> issues = validator.validateLoanAccount(a);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_ID") && i.contains("null/blank")),
                    "Should detect null borrower ID on loan: " + issues);
        }

        @Test
        @DisplayName("Detects null loan account number on payment")
        void detectsNullPaymentLoanAccountNumber() {
            LegacyPayment pmt = createValidPayment();
            pmt.setLoanAccountNumber(null);

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i -> i.contains("LN_ACCT_NBR") && i.contains("null/blank")),
                    "Should detect null loan account on payment: " + issues);
        }

        @Test
        @DisplayName("Detects blank first name on borrower")
        void detectsBlankBorrowerFirstName() {
            LegacyBorrower b = createValidBorrower();
            b.setFirstName("   ");

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_FST_NM") && i.contains("null/blank")),
                    "Should detect blank first name: " + issues);
        }

        @Test
        @DisplayName("Valid borrower produces no null-field issues")
        void validBorrowerHasNoNullIssues() {
            LegacyBorrower b = createValidBorrower();

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().noneMatch(i -> i.contains("null/blank")),
                    "Valid borrower should not have null-field issues: " + issues);
        }
    }

    // =========================================================================
    // ANOM-003: Numeric parsing risks
    // =========================================================================

    @Nested
    @DisplayName("ANOM-003: Numeric Parsing Risks")
    class NumericParsingTests {

        @Test
        @DisplayName("Detects non-numeric credit score")
        void detectsNonNumericCreditScore() {
            LegacyBorrower b = createValidBorrower();
            b.setCreditScore("N/A");

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_CRDT_SCR") && i.contains("not a valid integer")),
                    "Should detect unparseable credit score: " + issues);
        }

        @Test
        @DisplayName("Detects out-of-range credit score")
        void detectsOutOfRangeCreditScore() {
            LegacyBorrower b = createValidBorrower();
            b.setCreditScore("999");

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_CRDT_SCR") && i.contains("outside valid FICO range")),
                    "Should detect credit score outside FICO range: " + issues);
        }

        @Test
        @DisplayName("Detects non-numeric annual income")
        void detectsNonNumericAnnualIncome() {
            LegacyBorrower b = createValidBorrower();
            b.setAnnualIncome("$92,500");

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_ANN_INCM") && i.contains("not a valid amount")),
                    "Should detect unparseable annual income: " + issues);
        }

        @Test
        @DisplayName("Detects non-numeric loan amount")
        void detectsNonNumericLoanAmount() {
            LegacyLoanAccount a = createValidLoanAccount();
            a.setOriginalAmount("TBD");

            List<String> issues = validator.validateLoanAccount(a);

            assertTrue(issues.stream().anyMatch(i -> i.contains("LN_ORIG_AMT") && i.contains("not a valid amount")),
                    "Should detect unparseable loan amount: " + issues);
        }

        @Test
        @DisplayName("Detects non-numeric interest rate")
        void detectsNonNumericInterestRate() {
            LegacyLoanAccount a = createValidLoanAccount();
            a.setInterestRate("4.750%");

            List<String> issues = validator.validateLoanAccount(a);

            assertTrue(issues.stream().anyMatch(i -> i.contains("LN_INT_RT") && i.contains("not a valid decimal")),
                    "Should detect unparseable interest rate: " + issues);
        }

        @Test
        @DisplayName("Detects non-numeric term months")
        void detectsNonNumericTermMonths() {
            LegacyLoanAccount a = createValidLoanAccount();
            a.setTermMonths("30 years");

            List<String> issues = validator.validateLoanAccount(a);

            assertTrue(issues.stream().anyMatch(i -> i.contains("LN_TERM_MOS") && i.contains("not a valid integer")),
                    "Should detect unparseable term months: " + issues);
        }

        @Test
        @DisplayName("Detects non-numeric payment amount")
        void detectsNonNumericPaymentAmount() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTotalAmount("INVALID");

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i -> i.contains("PMT_AMT") && i.contains("not a valid amount")),
                    "Should detect unparseable payment amount: " + issues);
        }

        @Test
        @DisplayName("Detects negative loan amount")
        void detectsNegativeLoanAmount() {
            LegacyLoanAccount a = createValidLoanAccount();
            a.setOriginalAmount("-50,000");

            List<String> issues = validator.validateLoanAccount(a);

            assertTrue(issues.stream().anyMatch(i -> i.contains("LN_ORIG_AMT") && i.contains("negative")),
                    "Should detect negative loan amount: " + issues);
        }
    }

    // =========================================================================
    // ANOM-006: Temporal inconsistency (payment date before received date)
    // =========================================================================

    @Nested
    @DisplayName("ANOM-006: Temporal Inconsistency")
    class TemporalInconsistencyTests {

        @Test
        @DisplayName("Detects payment date before received date")
        void detectsPaymentDateBeforeReceivedDate() {
            LegacyPayment pmt = createValidPayment();
            // Payment dated 12/01 but not received until 12/05
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/05/2025");

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i -> i.contains("PMT_DT") && i.contains("before") && i.contains("PMT_RECV_DT")),
                    "Should detect payment date before received date: " + issues);
        }

        @Test
        @DisplayName("Accepts payment where received date equals payment date")
        void acceptsMatchingDates() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("12/01/2025");

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().noneMatch(i -> i.contains("before") && i.contains("PMT_RECV_DT")),
                    "Matching dates should not trigger temporal issue: " + issues);
        }

        @Test
        @DisplayName("Accepts payment where received date is before payment date")
        void acceptsReceivedBeforePaymentDate() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("12/01/2025");
            pmt.setReceivedDate("11/30/2025");

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().noneMatch(i -> i.contains("before") && i.contains("PMT_RECV_DT")),
                    "Received before payment should not trigger temporal issue: " + issues);
        }
    }

    // =========================================================================
    // ANOM-008: Date format validation
    // =========================================================================

    @Nested
    @DisplayName("ANOM-008: Date Format Validation")
    class DateFormatTests {

        @Test
        @DisplayName("Detects invalid date format on borrower DOB")
        void detectsInvalidDateFormat() {
            LegacyBorrower b = createValidBorrower();
            b.setDateOfBirth("1978-03-15");

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_DOB_DT") && i.contains("not a valid MM/DD/YYYY date")),
                    "Should detect non-MM/DD/YYYY date format: " + issues);
        }

        @Test
        @DisplayName("Detects DD/MM/YYYY format as invalid")
        void detectsDdMmYyyyFormat() {
            LegacyBorrower b = createValidBorrower();
            b.setDateOfBirth("15/03/1978");

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_DOB_DT") && i.contains("not a valid MM/DD/YYYY date")),
                    "Should detect DD/MM/YYYY format: " + issues);
        }

        @Test
        @DisplayName("Accepts valid MM/DD/YYYY date")
        void acceptsValidDate() {
            LegacyBorrower b = createValidBorrower();
            b.setDateOfBirth("03/15/1978");

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().noneMatch(i -> i.contains("BORR_DOB_DT")),
                    "Valid date should not trigger date issue: " + issues);
        }

        @Test
        @DisplayName("Detects invalid date on loan origination")
        void detectsInvalidLoanDate() {
            LegacyLoanAccount a = createValidLoanAccount();
            a.setOriginationDate("not-a-date");

            List<String> issues = validator.validateLoanAccount(a);

            assertTrue(issues.stream().anyMatch(i -> i.contains("LN_ORIG_DT") && i.contains("not a valid MM/DD/YYYY date")),
                    "Should detect invalid loan origination date: " + issues);
        }

        @Test
        @DisplayName("Detects invalid date on payment")
        void detectsInvalidPaymentDate() {
            LegacyPayment pmt = createValidPayment();
            pmt.setPaymentDate("2025-12-01");

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i -> i.contains("PMT_DT") && i.contains("not a valid MM/DD/YYYY date")),
                    "Should detect invalid payment date format: " + issues);
        }
    }

    // =========================================================================
    // ANOM-009: Invalid status codes
    // =========================================================================

    @Nested
    @DisplayName("ANOM-009: Invalid Status Codes")
    class StatusCodeTests {

        @Test
        @DisplayName("Detects invalid borrower status code")
        void detectsInvalidBorrowerStatus() {
            LegacyBorrower b = createValidBorrower();
            b.setStatusCode("XXX");

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().anyMatch(i -> i.contains("BORR_STAT_CD") && i.contains("not a recognized status")),
                    "Should detect invalid borrower status: " + issues);
        }

        @Test
        @DisplayName("Accepts valid borrower status code ACT")
        void acceptsValidBorrowerStatusAct() {
            LegacyBorrower b = createValidBorrower();
            b.setStatusCode("ACT");

            List<String> issues = validator.validateBorrower(b);

            assertTrue(issues.stream().noneMatch(i -> i.contains("BORR_STAT_CD")),
                    "Valid status ACT should not trigger issue: " + issues);
        }

        @Test
        @DisplayName("Detects invalid loan status code")
        void detectsInvalidLoanStatus() {
            LegacyLoanAccount a = createValidLoanAccount();
            a.setStatusCode("DEL");

            List<String> issues = validator.validateLoanAccount(a);

            assertTrue(issues.stream().anyMatch(i -> i.contains("LN_STAT_CD") && i.contains("not a recognized status")),
                    "Should detect invalid loan status: " + issues);
        }

        @Test
        @DisplayName("Accepts valid loan status codes")
        void acceptsValidLoanStatuses() {
            for (String status : List.of("ACT", "CLO", "DFT", "FRB")) {
                LegacyLoanAccount a = createValidLoanAccount();
                a.setStatusCode(status);

                List<String> issues = validator.validateLoanAccount(a);

                assertTrue(issues.stream().noneMatch(i -> i.contains("LN_STAT_CD")),
                        "Valid loan status " + status + " should not trigger issue: " + issues);
            }
        }

        @Test
        @DisplayName("Detects invalid payment status code")
        void detectsInvalidPaymentStatus() {
            LegacyPayment pmt = createValidPayment();
            pmt.setStatusCode("UNK");

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i -> i.contains("PMT_STAT_CD") && i.contains("not a recognized status")),
                    "Should detect invalid payment status: " + issues);
        }

        @Test
        @DisplayName("Detects invalid payment type code")
        void detectsInvalidPaymentType() {
            LegacyPayment pmt = createValidPayment();
            pmt.setTypeCode("XXX");

            List<String> issues = validator.validatePayment(pmt);

            assertTrue(issues.stream().anyMatch(i -> i.contains("PMT_TYP_CD") && i.contains("not a recognized type")),
                    "Should detect invalid payment type: " + issues);
        }

        @Test
        @DisplayName("Detects invalid property type code")
        void detectsInvalidPropertyType() {
            LegacyLoanAccount a = createValidLoanAccount();
            a.setPropertyType("ABC");

            List<String> issues = validator.validateLoanAccount(a);

            assertTrue(issues.stream().anyMatch(i -> i.contains("PROP_TYP_CD") && i.contains("not a recognized property type")),
                    "Should detect invalid property type: " + issues);
        }
    }

    // =========================================================================
    // Safe parsing helper tests
    // =========================================================================

    @Nested
    @DisplayName("Safe Parsing Helpers")
    class SafeParsingTests {

        @Test
        @DisplayName("safeParseAmount handles comma-formatted amounts")
        void safeParseAmountHandlesCommas() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("285,000"));
            assertEquals(new BigDecimal("271432.56"), validator.safeParseAmount("271,432.56"));
            assertEquals(new BigDecimal("0"), validator.safeParseAmount("0"));
        }

        @Test
        @DisplayName("safeParseAmount returns null for invalid input")
        void safeParseAmountReturnsNullForInvalid() {
            assertNull(validator.safeParseAmount("$285,000"));
            assertNull(validator.safeParseAmount("N/A"));
            assertNull(validator.safeParseAmount("abc"));
        }

        @Test
        @DisplayName("safeParseAmount returns null for null/blank input")
        void safeParseAmountReturnsNullForNullBlank() {
            assertNull(validator.safeParseAmount(null));
            assertNull(validator.safeParseAmount(""));
            assertNull(validator.safeParseAmount("   "));
        }

        @Test
        @DisplayName("safeParseInteger handles valid integers")
        void safeParseIntegerHandlesValid() {
            assertEquals(745, validator.safeParseInteger("745"));
            assertEquals(0, validator.safeParseInteger("0"));
            assertEquals(360, validator.safeParseInteger(" 360 "));
        }

        @Test
        @DisplayName("safeParseInteger returns null for invalid input")
        void safeParseIntegerReturnsNullForInvalid() {
            assertNull(validator.safeParseInteger("N/A"));
            assertNull(validator.safeParseInteger("PENDING"));
            assertNull(validator.safeParseInteger("4.5"));
        }

        @Test
        @DisplayName("safeParseLegacyDate handles MM/DD/YYYY format")
        void safeParseLegacyDateHandlesValid() {
            assertNotNull(validator.safeParseLegacyDate("03/15/1978"));
            assertNotNull(validator.safeParseLegacyDate("12/31/2025"));
        }

        @Test
        @DisplayName("safeParseLegacyDate returns null for invalid formats")
        void safeParseLegacyDateReturnsNullForInvalid() {
            assertNull(validator.safeParseLegacyDate("1978-03-15"));
            assertNull(validator.safeParseLegacyDate("15/03/1978"));
            assertNull(validator.safeParseLegacyDate("not-a-date"));
        }

        @Test
        @DisplayName("safeParseDecimal handles valid decimals")
        void safeParseDecimalHandlesValid() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseDecimal("4.750"));
            assertEquals(new BigDecimal("82.5"), validator.safeParseDecimal("82.5"));
        }

        @Test
        @DisplayName("safeParseDecimal returns null for invalid input")
        void safeParseDecimalReturnsNullForInvalid() {
            assertNull(validator.safeParseDecimal("4.750%"));
            assertNull(validator.safeParseDecimal("abc"));
        }
    }

    // =========================================================================
    // Integration: Valid records produce zero issues
    // =========================================================================

    @Nested
    @DisplayName("Valid Records Produce No Issues")
    class ValidRecordTests {

        @Test
        @DisplayName("Valid borrower has no issues")
        void validBorrowerNoIssues() {
            List<String> issues = validator.validateBorrower(createValidBorrower());
            assertTrue(issues.isEmpty(), "Valid borrower should have zero issues: " + issues);
        }

        @Test
        @DisplayName("Valid loan account has no issues")
        void validLoanAccountNoIssues() {
            List<String> issues = validator.validateLoanAccount(createValidLoanAccount());
            assertTrue(issues.isEmpty(), "Valid loan account should have zero issues: " + issues);
        }

        @Test
        @DisplayName("Valid payment has no issues")
        void validPaymentNoIssues() {
            List<String> issues = validator.validatePayment(createValidPayment());
            assertTrue(issues.isEmpty(), "Valid payment should have zero issues: " + issues);
        }
    }
}
