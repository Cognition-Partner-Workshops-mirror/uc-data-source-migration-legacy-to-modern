package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.validation.DataQualityWarning.Severity;
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
    // Safe parsing tests
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
        void returnsNullForNull() {
            assertNull(validator.safeParseAmount(null));
        }

        @Test
        void returnsNullForBlank() {
            assertNull(validator.safeParseAmount("  "));
        }

        @Test
        void returnsNullForInvalidAmount() {
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
        void parsesDecimal() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseDecimal("4.750"));
        }

        @Test
        void parsesDecimalWithWhitespace() {
            assertEquals(new BigDecimal("3.125"), validator.safeParseDecimal(" 3.125 "));
        }

        @Test
        void returnsNullForInvalidDecimal() {
            assertNull(validator.safeParseDecimal("TBD"));
        }
    }

    @Nested
    class SafeParseIntegerTests {

        @Test
        void parsesInteger() {
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
        void returnsNullForNonNumeric() {
            assertNull(validator.safeParseInteger("PENDING"));
        }

        @Test
        void returnsNullForDecimalString() {
            assertNull(validator.safeParseInteger("745.5"));
        }
    }

    @Nested
    class SafeParseLegacyDateTests {

        @Test
        void parsesValidDate() {
            assertEquals(LocalDate.of(1978, 3, 15),
                    validator.safeParseLegacyDate("03/15/1978"));
        }

        @Test
        void returnsNullForIsoFormat() {
            assertNull(validator.safeParseLegacyDate("2025-01-15"));
        }

        @Test
        void returnsNullForInvalidMonth() {
            assertNull(validator.safeParseLegacyDate("13/01/2025"));
        }

        @Test
        void returnsNullForInvalidDay() {
            assertNull(validator.safeParseLegacyDate("02/32/2025"));
        }

        @Test
        void returnsNullForNull() {
            assertNull(validator.safeParseLegacyDate(null));
        }
    }

    // =========================================================================
    // Borrower validation tests
    // =========================================================================

    @Nested
    class BorrowerValidationTests {

        @Test
        void validBorrowerProducesNoWarnings() {
            LegacyBorrower b = makeBorrower("B-10001", "James", "Mitchell", "R",
                    "745", "92,500", "03/15/1978", "ACT");
            List<DataQualityWarning> warnings = validator.validateBorrower(b);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsNullFirstName() {
            LegacyBorrower b = makeBorrower("B-10001", null, "Mitchell", "R",
                    "745", "92,500", "03/15/1978", "ACT");
            List<DataQualityWarning> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-010".equals(w.getAnomalyCode()) && w.getColumn().contains("BORR_FST_NM")));
        }

        @Test
        void detectsNullLastName() {
            LegacyBorrower b = makeBorrower("B-10001", "James", null, "R",
                    "745", "92,500", "03/15/1978", "ACT");
            List<DataQualityWarning> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-010".equals(w.getAnomalyCode()) && w.getColumn().contains("BORR_LST_NM")));
        }

        @Test
        void detectsUnparseableCreditScore() {
            LegacyBorrower b = makeBorrower("B-10001", "James", "Mitchell", "R",
                    "N/A", "92,500", "03/15/1978", "ACT");
            List<DataQualityWarning> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-004".equals(w.getAnomalyCode()) && w.getColumn().contains("BORR_CRDT_SCR")));
        }

        @Test
        void detectsCreditScoreOutOfRange() {
            LegacyBorrower b = makeBorrower("B-10001", "James", "Mitchell", "R",
                    "200", "92,500", "03/15/1978", "ACT");
            List<DataQualityWarning> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-004".equals(w.getAnomalyCode())
                            && w.getColumn().contains("BORR_CRDT_SCR")
                            && w.getSeverity() == Severity.MEDIUM));
        }

        @Test
        void detectsUnparseableAnnualIncome() {
            LegacyBorrower b = makeBorrower("B-10001", "James", "Mitchell", "R",
                    "745", "$92,500", "03/15/1978", "ACT");
            List<DataQualityWarning> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-004".equals(w.getAnomalyCode()) && w.getColumn().contains("BORR_ANN_INCM")));
        }

        @Test
        void detectsInvalidDateOfBirth() {
            LegacyBorrower b = makeBorrower("B-10001", "James", "Mitchell", "R",
                    "745", "92,500", "13/15/1978", "ACT");
            List<DataQualityWarning> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-007".equals(w.getAnomalyCode()) && w.getColumn().contains("BORR_DOB_DT")));
        }

        @Test
        void detectsUnknownStatusCode() {
            LegacyBorrower b = makeBorrower("B-10001", "James", "Mitchell", "R",
                    "745", "92,500", "03/15/1978", "XYZ");
            List<DataQualityWarning> warnings = validator.validateBorrower(b);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getColumn().contains("BORR_STAT_CD")));
        }
    }

    // =========================================================================
    // Loan account validation tests
    // =========================================================================

    @Nested
    class LoanAccountValidationTests {

        @Test
        void validLoanAccountProducesNoWarnings() {
            LegacyLoanAccount acct = makeLoanAccount("LN-2019-00142", "B-10001",
                    "James", "Mitchell", "0142", "FXD30",
                    "285,000", "271,432.56", "4.750", "ACT", "0", "SFR",
                    "345,000", "82.5", "02/15/2019", "02/15/2049");
            LegacyBorrower borrower = makeBorrower("B-10001", "James", "Mitchell", "R",
                    "745", "92,500", "03/15/1978", "ACT");
            borrower.setPhoneNumber("217-555-9999");

            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct, borrower);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsDelinquentLoanWithActiveStatus() {
            LegacyLoanAccount acct = makeLoanAccount("LN-2018-00089", "B-10003",
                    "Michael", "Torres", "0167", "ARM51",
                    "195,000", "178,234.12", "5.250", "ACT", "15", "SFR",
                    "260,000", "75.0", "07/01/2018", "07/01/2048");

            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-005".equals(w.getAnomalyCode()) && w.getSeverity() == Severity.HIGH));
        }

        @Test
        void detectsSsnLast4MatchingPhoneLast4() {
            LegacyLoanAccount acct = makeLoanAccount("LN-2019-00142", "B-10001",
                    "James", "Mitchell", "0142", "FXD30",
                    "285,000", "271,432.56", "4.750", "ACT", "0", "SFR",
                    "345,000", "82.5", "02/15/2019", "02/15/2049");
            LegacyBorrower borrower = makeBorrower("B-10001", "James", "Mitchell", "R",
                    "745", "92,500", "03/15/1978", "ACT");
            borrower.setPhoneNumber("217-555-0142");

            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct, borrower);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-001".equals(w.getAnomalyCode()) && w.getSeverity() == Severity.CRITICAL));
        }

        @Test
        void detectsDenormalizedNameDrift() {
            LegacyLoanAccount acct = makeLoanAccount("LN-2019-00142", "B-10001",
                    "Jim", "Mitchell", "0142", "FXD30",
                    "285,000", "271,432.56", "4.750", "ACT", "0", "SFR",
                    "345,000", "82.5", "02/15/2019", "02/15/2049");
            LegacyBorrower borrower = makeBorrower("B-10001", "James", "Mitchell", "R",
                    "745", "92,500", "03/15/1978", "ACT");
            borrower.setPhoneNumber("217-555-9999");

            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct, borrower);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-006".equals(w.getAnomalyCode())));
        }

        @Test
        void detectsUnknownPropertyType() {
            LegacyLoanAccount acct = makeLoanAccount("LN-2019-00142", "B-10001",
                    "James", "Mitchell", "0142", "FXD30",
                    "285,000", "271,432.56", "4.750", "ACT", "0", "XYZ",
                    "345,000", "82.5", "02/15/2019", "02/15/2049");

            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getColumn().contains("PROP_TYP_CD")));
        }

        @Test
        void detectsNullStatusCode() {
            LegacyLoanAccount acct = makeLoanAccount("LN-2019-00142", "B-10001",
                    "James", "Mitchell", "0142", "FXD30",
                    "285,000", "271,432.56", "4.750", null, "0", "SFR",
                    "345,000", "82.5", "02/15/2019", "02/15/2049");

            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-010".equals(w.getAnomalyCode()) && w.getColumn().contains("LN_STAT_CD")));
        }

        @Test
        void detectsInvalidLoanDates() {
            LegacyLoanAccount acct = makeLoanAccount("LN-2019-00142", "B-10001",
                    "James", "Mitchell", "0142", "FXD30",
                    "285,000", "271,432.56", "4.750", "ACT", "0", "SFR",
                    "345,000", "82.5", "2019-02-15", "02/15/2049");

            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-007".equals(w.getAnomalyCode()) && w.getColumn().contains("LN_ORIG_DT")));
        }

        @Test
        void detectsUnparseableLoanAmount() {
            LegacyLoanAccount acct = makeLoanAccount("LN-2019-00142", "B-10001",
                    "James", "Mitchell", "0142", "FXD30",
                    "TBD", "271,432.56", "4.750", "ACT", "0", "SFR",
                    "345,000", "82.5", "02/15/2019", "02/15/2049");

            List<DataQualityWarning> warnings = validator.validateLoanAccount(acct, null);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-004".equals(w.getAnomalyCode()) && w.getColumn().contains("LN_ORIG_AMT")));
        }
    }

    // =========================================================================
    // Payment validation tests
    // =========================================================================

    @Nested
    class PaymentValidationTests {

        @Test
        void validPaymentProducesNoWarnings() {
            LegacyPayment pmt = makePayment("PMT-001", "LN-001",
                    "12/01/2025", "2,924.18", "1,842.56", "815.50", "266.12", "0.00",
                    "REG", "PST", "11/30/2025");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.isEmpty());
        }

        @Test
        void detectsPaymentComponentSumMismatch() {
            LegacyPayment pmt = makePayment("PMT-2025120001", "LN-2019-00142",
                    "12/15/2025", "1,487.02", "456.78", "1,074.69", "355.55", "0.00",
                    "REG", "PST", "12/14/2025");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-002".equals(w.getAnomalyCode()) && w.getSeverity() == Severity.CRITICAL));
        }

        @Test
        void detectsLateFeeExcludedFromTotal() {
            LegacyPayment pmt = makePayment("PMT-2025110003", "LN-2018-00089",
                    "11/01/2025", "1,077.05", "295.82", "781.23", "0.00", "47.50",
                    "REG", "PST", "11/18/2025");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-002".equals(w.getAnomalyCode())));
        }

        @Test
        void detectsUnknownPaymentType() {
            LegacyPayment pmt = makePayment("PMT-001", "LN-001",
                    "12/01/2025", "1,000.00", "500.00", "400.00", "100.00", "0.00",
                    "XXX", "PST", "12/01/2025");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getColumn().contains("PMT_TYP_CD")));
        }

        @Test
        void detectsUnknownPaymentStatus() {
            LegacyPayment pmt = makePayment("PMT-001", "LN-001",
                    "12/01/2025", "1,000.00", "500.00", "400.00", "100.00", "0.00",
                    "REG", "ZZZ", "12/01/2025");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w ->
                    w.getColumn().contains("PMT_STAT_CD")));
        }

        @Test
        void detectsUnparseablePaymentAmount() {
            LegacyPayment pmt = makePayment("PMT-001", "LN-001",
                    "12/01/2025", "INVALID", "500.00", "400.00", "100.00", "0.00",
                    "REG", "PST", "12/01/2025");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-004".equals(w.getAnomalyCode()) && w.getColumn().contains("PMT_AMT")));
        }

        @Test
        void detectsInvalidPaymentDate() {
            LegacyPayment pmt = makePayment("PMT-001", "LN-001",
                    "13/01/2025", "1,000.00", "500.00", "400.00", "100.00", "0.00",
                    "REG", "PST", "12/01/2025");
            List<DataQualityWarning> warnings = validator.validatePayment(pmt);
            assertTrue(warnings.stream().anyMatch(w ->
                    "ANM-007".equals(w.getAnomalyCode()) && w.getColumn().contains("PMT_DT")));
        }
    }

    // =========================================================================
    // Factory methods
    // =========================================================================

    private LegacyBorrower makeBorrower(String id, String firstName, String lastName,
                                         String middleInitial, String creditScore,
                                         String annualIncome, String dob, String status) {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId(id);
        b.setFirstName(firstName);
        b.setLastName(lastName);
        b.setMiddleInitial(middleInitial);
        b.setCreditScore(creditScore);
        b.setAnnualIncome(annualIncome);
        b.setDateOfBirth(dob);
        b.setStatusCode(status);
        b.setEmail("test@example.com");
        b.setAddressLine1("123 Main St");
        b.setCity("Springfield");
        b.setStateCode("IL");
        b.setZipCode("62701");
        return b;
    }

    private LegacyLoanAccount makeLoanAccount(String loanNumber, String borrowerId,
                                               String firstName, String lastName,
                                               String ssnLast4, String productCode,
                                               String origAmount, String currBalance,
                                               String interestRate, String status,
                                               String dlqDays, String propType,
                                               String appraisedValue, String ltv,
                                               String origDate, String matDate) {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber(loanNumber);
        acct.setBorrowerId(borrowerId);
        acct.setBorrowerFirstName(firstName);
        acct.setBorrowerLastName(lastName);
        acct.setBorrowerSsnLast4(ssnLast4);
        acct.setProductCode(productCode);
        acct.setOriginalAmount(origAmount);
        acct.setCurrentBalance(currBalance);
        acct.setInterestRate(interestRate);
        acct.setStatusCode(status);
        acct.setDelinquencyDays(dlqDays);
        acct.setPropertyType(propType);
        acct.setAppraisedValue(appraisedValue);
        acct.setLtvPercent(ltv);
        acct.setOriginationDate(origDate);
        acct.setMaturityDate(matDate);
        acct.setMonthlyPayment("1,487.02");
        acct.setPropertyAddress("742 Elm Street");
        acct.setPropertyCity("Springfield");
        acct.setPropertyState("IL");
        acct.setPropertyZip("62701");
        return acct;
    }

    private LegacyPayment makePayment(String seqNum, String loanNum,
                                       String paymentDate, String totalAmt,
                                       String principalAmt, String interestAmt,
                                       String escrowAmt, String lateFee,
                                       String typeCode, String statusCode,
                                       String receivedDate) {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber(seqNum);
        pmt.setLoanAccountNumber(loanNum);
        pmt.setPaymentDate(paymentDate);
        pmt.setTotalAmount(totalAmt);
        pmt.setPrincipalAmount(principalAmt);
        pmt.setInterestAmount(interestAmt);
        pmt.setEscrowAmount(escrowAmt);
        pmt.setLateFee(lateFee);
        pmt.setTypeCode(typeCode);
        pmt.setStatusCode(statusCode);
        pmt.setReceivedDate(receivedDate);
        pmt.setProcessedDate(receivedDate);
        pmt.setCreatedDate(receivedDate);
        pmt.setUpdatedDate(receivedDate);
        return pmt;
    }
}
