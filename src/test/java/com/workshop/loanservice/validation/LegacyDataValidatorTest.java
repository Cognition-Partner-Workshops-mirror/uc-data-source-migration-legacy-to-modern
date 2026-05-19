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
 * Tests for LegacyDataValidator, verifying each anomaly type from
 * docs/DATA_ANOMALY_REPORT.md is caught at ingestion time.
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // ---------------------------------------------------------------
    // Safe parsing utility tests
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("Safe parsing utilities")
    class SafeParsingTests {

        @Test
        @DisplayName("safeParseAmount handles comma-formatted amounts")
        void parseAmountWithCommas() {
            assertEquals(new BigDecimal("285000"), validator.safeParseAmount("285,000"));
            assertEquals(new BigDecimal("1487.02"), validator.safeParseAmount("1,487.02"));
            assertEquals(new BigDecimal("92500"), validator.safeParseAmount("92,500"));
        }

        @Test
        @DisplayName("safeParseAmount returns null for malformed input instead of throwing")
        void parseAmountMalformed() {
            // Malformed amounts should return null, not throw NumberFormatException
            assertNull(validator.safeParseAmount("$285,000"));
            assertNull(validator.safeParseAmount("abc"));
            assertNull(validator.safeParseAmount("12.34.56"));
        }

        @Test
        @DisplayName("safeParseAmount returns null for null/blank input")
        void parseAmountNullBlank() {
            assertNull(validator.safeParseAmount(null));
            assertNull(validator.safeParseAmount(""));
            assertNull(validator.safeParseAmount("   "));
        }

        @Test
        @DisplayName("safeParseInt handles valid integers and returns null for malformed")
        void parseIntSafe() {
            assertEquals(745, validator.safeParseInt("745"));
            assertEquals(0, validator.safeParseInt("0"));
            assertNull(validator.safeParseInt("abc"));
            assertNull(validator.safeParseInt("12.5"));
            assertNull(validator.safeParseInt(null));
        }

        @Test
        @DisplayName("safeParseDecimal handles valid decimals and returns null for malformed")
        void parseDecimalSafe() {
            assertEquals(new BigDecimal("4.750"), validator.safeParseDecimal("4.750"));
            assertNull(validator.safeParseDecimal("abc"));
            assertNull(validator.safeParseDecimal(null));
        }

        @Test
        @DisplayName("safeParseDate handles MM/dd/yyyy and returns null for bad formats")
        void parseDateSafe() {
            assertNotNull(validator.safeParseDate("03/15/1978"));
            assertNotNull(validator.safeParseDate("12/31/2025"));
            // Invalid formats return null
            assertNull(validator.safeParseDate("2025-01-01"));
            assertNull(validator.safeParseDate("13/32/2025"));
            assertNull(validator.safeParseDate("not-a-date"));
            assertNull(validator.safeParseDate(null));
        }
    }

    // ---------------------------------------------------------------
    // ANO-001: Payment component sum mismatch
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("ANO-001: Payment component sum mismatch")
    class PaymentSumMismatchTests {

        @Test
        @DisplayName("Detects when payment components exceed total amount")
        void detectComponentSumExceedsTotal() {
            // PMT-2025120001: total=1,487.02 but principal+interest+escrow = 1,887.02
            LegacyPayment pmt = buildPayment("PMT-TEST-001", "LN-001",
                    "12/15/2025", "1,487.02", "456.78", "1,074.69", "355.55", "0.00",
                    "REG", "PST");

            List<String> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum")),
                    "Should detect payment component sum mismatch");
        }

        @Test
        @DisplayName("Detects late fee not included in total")
        void detectLateFeeNotInTotal() {
            // PMT-2025110003: total=1,077.05 but components sum to 1,124.55
            LegacyPayment pmt = buildPayment("PMT-TEST-002", "LN-001",
                    "11/01/2025", "1,077.05", "295.82", "781.23", "0.00", "47.50",
                    "REG", "PST");

            List<String> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("component sum")),
                    "Should detect late fee not reflected in total");
        }

        @Test
        @DisplayName("No warning when components sum correctly")
        void noWarningWhenComponentsMatch() {
            // PMT-2025120002: total=2,924.18 = 1,842.56 + 815.50 + 266.12 + 0.00
            LegacyPayment pmt = buildPayment("PMT-TEST-003", "LN-002",
                    "12/01/2025", "2,924.18", "1,842.56", "815.50", "266.12", "0.00",
                    "REG", "PST");

            List<String> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().noneMatch(w -> w.contains("component sum")),
                    "Should not warn when components sum correctly");
        }
    }

    // ---------------------------------------------------------------
    // ANO-002: SSN last-4 matches phone last-4
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("ANO-002: SSN-phone cross-contamination")
    class SsnPhoneCrossContaminationTests {

        @Test
        @DisplayName("Detects SSN last-4 matching phone last-4")
        void detectSsnPhoneMatch() {
            LegacyBorrower borrower = buildBorrower("B-10001", "James", "Mitchell",
                    "745", "92,500", "217-555-0142", "ACT");
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001",
                    "James", "Mitchell", "0142", "FXD30", "285,000", "271,432.56",
                    "4.750", "360", "ACT", "0");

            List<String> warnings = validator.validateLoanAccount(acct, borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-002")),
                    "Should detect SSN last-4 matching phone last-4");
        }

        @Test
        @DisplayName("No warning when SSN last-4 differs from phone last-4")
        void noWarningWhenSsnDiffersFromPhone() {
            LegacyBorrower borrower = buildBorrower("B-10001", "James", "Mitchell",
                    "745", "92,500", "217-555-0142", "ACT");
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001",
                    "James", "Mitchell", "9999", "FXD30", "285,000", "271,432.56",
                    "4.750", "360", "ACT", "0");

            List<String> warnings = validator.validateLoanAccount(acct, borrower);

            assertTrue(warnings.stream().noneMatch(w -> w.contains("ANO-002")),
                    "Should not warn when SSN last-4 differs from phone");
        }
    }

    // ---------------------------------------------------------------
    // ANO-003: Delinquency days > 0 with Active status
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("ANO-003: Delinquency vs status inconsistency")
    class DelinquencyStatusTests {

        @Test
        @DisplayName("Detects delinquent loan with Active status")
        void detectDelinquentActiveStatus() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001",
                    "James", "Mitchell", "9999", "FXD30", "285,000", "271,432.56",
                    "4.750", "360", "ACT", "15");

            List<String> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().anyMatch(w ->
                            w.contains("delinquent loan shows as Active")),
                    "Should detect delinquency > 0 with Active status");
        }

        @Test
        @DisplayName("No warning when delinquency is zero with Active status")
        void noWarningWhenNoDelinquency() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001",
                    "James", "Mitchell", "9999", "FXD30", "285,000", "271,432.56",
                    "4.750", "360", "ACT", "0");

            List<String> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().noneMatch(w ->
                            w.contains("delinquent loan shows as Active")),
                    "Should not warn when delinquency is 0");
        }

        @Test
        @DisplayName("No warning when delinquent with non-Active status")
        void noWarningWhenDelinquentWithDefaultStatus() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001",
                    "James", "Mitchell", "9999", "FXD30", "285,000", "271,432.56",
                    "4.750", "360", "DFT", "90");

            List<String> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().noneMatch(w ->
                            w.contains("delinquent loan shows as Active")),
                    "Should not warn when status is DFT (Default)");
        }
    }

    // ---------------------------------------------------------------
    // ANO-004: Numeric fields as VARCHAR — parse crash risk
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("ANO-004: Numeric string parsing validation")
    class NumericParsingTests {

        @Test
        @DisplayName("Detects non-numeric credit score")
        void detectBadCreditScore() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe",
                    "N/A", "80,000", "555-123-4567", "ACT");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_CRDT_SCR")),
                    "Should detect non-numeric credit score");
        }

        @Test
        @DisplayName("Detects credit score outside valid FICO range")
        void detectOutOfRangeCreditScore() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe",
                    "999", "80,000", "555-123-4567", "ACT");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("outside valid FICO range")),
                    "Should detect credit score outside 300-850 range");
        }

        @Test
        @DisplayName("Detects non-numeric annual income")
        void detectBadAnnualIncome() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe",
                    "745", "$80k", "555-123-4567", "ACT");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_ANN_INCM")),
                    "Should detect non-numeric annual income");
        }

        @Test
        @DisplayName("Detects non-numeric loan amounts")
        void detectBadLoanAmount() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001",
                    "James", "Mitchell", "0142", "FXD30", "two-hundred-k", "271,432.56",
                    "4.750", "360", "ACT", "0");

            List<String> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("LN_ORIG_AMT")),
                    "Should detect non-numeric original amount");
        }

        @Test
        @DisplayName("Detects non-numeric payment amounts")
        void detectBadPaymentAmount() {
            LegacyPayment pmt = buildPayment("PMT-TEST", "LN-001",
                    "12/01/2025", "bad-amount", "100.00", "200.00", "0.00", "0.00",
                    "REG", "PST");

            List<String> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("PMT_AMT")),
                    "Should detect non-numeric total payment amount");
        }
    }

    // ---------------------------------------------------------------
    // ANO-005: Date format validation
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("ANO-005: Date format validation")
    class DateFormatTests {

        @Test
        @DisplayName("Detects ISO date format instead of MM/DD/YYYY")
        void detectIsoDateFormat() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe",
                    "745", "80,000", "555-123-4567", "ACT");
            borrower.setDateOfBirth("1978-03-15");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_DOB_DT")),
                    "Should detect ISO date format as invalid");
        }

        @Test
        @DisplayName("Detects impossible date (month 13)")
        void detectImpossibleDate() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe",
                    "745", "80,000", "555-123-4567", "ACT");
            borrower.setDateOfBirth("13/32/2025");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_DOB_DT")),
                    "Should detect impossible date");
        }

        @Test
        @DisplayName("Accepts valid MM/dd/yyyy dates")
        void acceptValidDates() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe",
                    "745", "80,000", "555-123-4567", "ACT");
            borrower.setDateOfBirth("03/15/1978");
            borrower.setCreatedDate("01/15/2019");
            borrower.setUpdatedDate("11/03/2025");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().noneMatch(w ->
                            w.contains("not a valid MM/dd/yyyy date")),
                    "Should not warn for valid dates");
        }
    }

    // ---------------------------------------------------------------
    // ANO-006: Invalid status codes
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("ANO-006: Invalid status code detection")
    class StatusCodeTests {

        @Test
        @DisplayName("Detects invalid borrower status code")
        void detectInvalidBorrowerStatus() {
            LegacyBorrower borrower = buildBorrower("B-TEST", "John", "Doe",
                    "745", "80,000", "555-123-4567", "XYZ");

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_STAT_CD")),
                    "Should detect invalid borrower status code");
        }

        @Test
        @DisplayName("Detects invalid loan status code")
        void detectInvalidLoanStatus() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001",
                    "James", "Mitchell", "0142", "FXD30", "285,000", "271,432.56",
                    "4.750", "360", "BAD", "0");

            List<String> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("LN_STAT_CD")),
                    "Should detect invalid loan status code");
        }

        @Test
        @DisplayName("Detects invalid payment type code")
        void detectInvalidPaymentType() {
            LegacyPayment pmt = buildPayment("PMT-TEST", "LN-001",
                    "12/01/2025", "1,000.00", "500.00", "500.00", "0.00", "0.00",
                    "XXX", "PST");

            List<String> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("PMT_TYP_CD")),
                    "Should detect invalid payment type code");
        }

        @Test
        @DisplayName("Detects invalid payment status code")
        void detectInvalidPaymentStatus() {
            LegacyPayment pmt = buildPayment("PMT-TEST", "LN-001",
                    "12/01/2025", "1,000.00", "500.00", "500.00", "0.00", "0.00",
                    "REG", "BAD");

            List<String> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("PMT_STAT_CD")),
                    "Should detect invalid payment status code");
        }
    }

    // ---------------------------------------------------------------
    // ANO-007: Denormalized name drift
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("ANO-007: Denormalized borrower name drift")
    class DenormalizedNameDriftTests {

        @Test
        @DisplayName("Detects first name mismatch between loan account and borrower master")
        void detectFirstNameDrift() {
            LegacyBorrower borrower = buildBorrower("B-10001", "James", "Mitchell",
                    "745", "92,500", "217-555-9999", "ACT");
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001",
                    "Jim", "Mitchell", "9999", "FXD30", "285,000", "271,432.56",
                    "4.750", "360", "ACT", "0");

            List<String> warnings = validator.validateLoanAccount(acct, borrower);

            assertTrue(warnings.stream().anyMatch(w ->
                            w.contains("Denormalized BORR_FST_NM")),
                    "Should detect first name drift");
        }

        @Test
        @DisplayName("Detects last name mismatch between loan account and borrower master")
        void detectLastNameDrift() {
            LegacyBorrower borrower = buildBorrower("B-10002", "Sarah", "Chen-Williams",
                    "780", "125,000", "503-555-9999", "ACT");
            LegacyLoanAccount acct = buildLoanAccount("LN-002", "B-10002",
                    "Sarah", "Chen", "9999", "FXD15", "420,000", "312,876.43",
                    "3.125", "180", "ACT", "0");

            List<String> warnings = validator.validateLoanAccount(acct, borrower);

            assertTrue(warnings.stream().anyMatch(w ->
                            w.contains("Denormalized BORR_LST_NM")),
                    "Should detect last name drift");
        }

        @Test
        @DisplayName("No warning when names match")
        void noWarningWhenNamesMatch() {
            LegacyBorrower borrower = buildBorrower("B-10001", "James", "Mitchell",
                    "745", "92,500", "217-555-9999", "ACT");
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-10001",
                    "James", "Mitchell", "9999", "FXD30", "285,000", "271,432.56",
                    "4.750", "360", "ACT", "0");

            List<String> warnings = validator.validateLoanAccount(acct, borrower);

            assertTrue(warnings.stream().noneMatch(w ->
                            w.contains("Denormalized")),
                    "Should not warn when names match");
        }
    }

    // ---------------------------------------------------------------
    // Required field null checks
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("Required field null checks")
    class RequiredFieldTests {

        @Test
        @DisplayName("Detects null required borrower fields")
        void detectNullBorrowerFields() {
            LegacyBorrower borrower = new LegacyBorrower();
            borrower.setBorrowerId("B-NULL");
            // Leave firstName, lastName, ssnEncrypted as null

            List<String> warnings = validator.validateBorrower(borrower);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_FST_NM")),
                    "Should detect null first name");
            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_LST_NM")),
                    "Should detect null last name");
            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_SSN_ENCR")),
                    "Should detect null SSN");
        }

        @Test
        @DisplayName("Detects null required loan account fields")
        void detectNullLoanFields() {
            LegacyLoanAccount acct = new LegacyLoanAccount();
            acct.setLoanAccountNumber("LN-NULL");
            // Leave borrowerId, productCode as null

            List<String> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("BORR_ID")),
                    "Should detect null borrower ID");
            assertTrue(warnings.stream().anyMatch(w -> w.contains("PROD_CD")),
                    "Should detect null product code");
        }

        @Test
        @DisplayName("Detects null required payment fields")
        void detectNullPaymentFields() {
            LegacyPayment pmt = new LegacyPayment();
            pmt.setPaymentSequenceNumber("PMT-NULL");
            // Leave loanAccountNumber as null

            List<String> warnings = validator.validatePayment(pmt);

            assertTrue(warnings.stream().anyMatch(w -> w.contains("LN_ACCT_NBR")),
                    "Should detect null loan account number");
        }
    }

    // ---------------------------------------------------------------
    // Integration: validate actual seed data anomalies
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("Seed data anomaly detection")
    class SeedDataAnomalyTests {

        @Test
        @DisplayName("Detects all 3 mismatched payments from legacy seed data")
        void detectAllSeedDataPaymentMismatches() {
            // PMT-2025120001: escrow not reflected in total
            LegacyPayment pmt1 = buildPayment("PMT-2025120001", "LN-2019-00142",
                    "12/15/2025", "1,487.02", "456.78", "1,074.69", "355.55", "0.00",
                    "REG", "PST");
            // PMT-2025110001: same escrow issue
            LegacyPayment pmt2 = buildPayment("PMT-2025110001", "LN-2019-00142",
                    "11/15/2025", "1,487.02", "454.97", "1,076.50", "355.55", "0.00",
                    "REG", "PST");
            // PMT-2025110003: late fee not in total
            LegacyPayment pmt3 = buildPayment("PMT-2025110003", "LN-2018-00089",
                    "11/01/2025", "1,077.05", "295.82", "781.23", "0.00", "47.50",
                    "REG", "PST");

            assertTrue(validator.validatePayment(pmt1).stream()
                    .anyMatch(w -> w.contains("component sum")));
            assertTrue(validator.validatePayment(pmt2).stream()
                    .anyMatch(w -> w.contains("component sum")));
            assertTrue(validator.validatePayment(pmt3).stream()
                    .anyMatch(w -> w.contains("component sum")));
        }

        @Test
        @DisplayName("Detects SSN-phone crossover for all seed data borrowers")
        void detectAllSeedDataSsnPhoneCrossover() {
            // All 5 borrowers have SSN last-4 matching phone last-4
            String[][] data = {
                    {"B-10001", "James", "Mitchell", "217-555-0142", "0142"},
                    {"B-10002", "Sarah", "Chen", "503-555-0198", "0198"},
                    {"B-10003", "Michael", "Torres", "512-555-0167", "0167"},
                    {"B-10004", "Emily", "Johnson", "303-555-0134", "0134"},
                    {"B-10005", "Robert", "Williams", "602-555-0156", "0156"},
            };

            for (String[] row : data) {
                LegacyBorrower borrower = buildBorrower(row[0], row[1], row[2],
                        "745", "80,000", row[3], "ACT");
                LegacyLoanAccount acct = buildLoanAccount("LN-" + row[0], row[0],
                        row[1], row[2], row[4], "FXD30", "200,000", "180,000",
                        "4.5", "360", "ACT", "0");

                List<String> warnings = validator.validateLoanAccount(acct, borrower);
                assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-002")),
                        "SSN-phone crossover not detected for " + row[0]);
            }
        }

        @Test
        @DisplayName("Detects delinquency/status mismatch for LN-2018-00089")
        void detectSeedDataDelinquencyMismatch() {
            LegacyLoanAccount acct = buildLoanAccount("LN-2018-00089", "B-10003",
                    "Michael", "Torres", "0167", "ARM51", "195,000", "178,234.12",
                    "5.250", "360", "ACT", "15");

            List<String> warnings = validator.validateLoanAccount(acct, null);

            assertTrue(warnings.stream().anyMatch(w ->
                            w.contains("delinquent loan shows as Active")),
                    "Should detect LN-2018-00089 delinquency/status mismatch");
        }
    }

    // ---------------------------------------------------------------
    // Internal helper: extractLast4Digits
    // ---------------------------------------------------------------

    @Nested
    @DisplayName("extractLast4Digits helper")
    class ExtractLast4DigitsTests {

        @Test
        @DisplayName("Extracts last 4 digits from phone numbers")
        void extractFromPhone() {
            assertEquals("0142", validator.extractLast4Digits("217-555-0142"));
            assertEquals("0198", validator.extractLast4Digits("503-555-0198"));
            assertEquals("4567", validator.extractLast4Digits("(555) 123-4567"));
        }

        @Test
        @DisplayName("Returns null for null/blank/short input")
        void handlesBadInput() {
            assertNull(validator.extractLast4Digits(null));
            assertNull(validator.extractLast4Digits(""));
            assertNull(validator.extractLast4Digits("12"));
        }
    }

    // ---------------------------------------------------------------
    // Builder helpers
    // ---------------------------------------------------------------

    private LegacyBorrower buildBorrower(String id, String firstName, String lastName,
                                         String creditScore, String income,
                                         String phone, String status) {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId(id);
        b.setFirstName(firstName);
        b.setLastName(lastName);
        b.setSsnEncrypted("ENC_XXX");
        b.setDateOfBirth("03/15/1978");
        b.setCreditScore(creditScore);
        b.setAnnualIncome(income);
        b.setPhoneNumber(phone);
        b.setCreatedDate("01/15/2019");
        b.setUpdatedDate("11/03/2025");
        b.setStatusCode(status);
        return b;
    }

    private LegacyLoanAccount buildLoanAccount(String acctNbr, String borrowerId,
                                                String firstName, String lastName,
                                                String ssnLast4, String prodCd,
                                                String origAmt, String currBal,
                                                String intRate, String termMos,
                                                String status, String dlqDays) {
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber(acctNbr);
        a.setBorrowerId(borrowerId);
        a.setBorrowerFirstName(firstName);
        a.setBorrowerLastName(lastName);
        a.setBorrowerSsnLast4(ssnLast4);
        a.setProductCode(prodCd);
        a.setOriginalAmount(origAmt);
        a.setCurrentBalance(currBal);
        a.setInterestRate(intRate);
        a.setTermMonths(termMos);
        a.setStatusCode(status);
        a.setDelinquencyDays(dlqDays);
        a.setMonthlyPayment("1,000.00");
        a.setOriginationDate("02/15/2019");
        a.setMaturityDate("02/15/2049");
        a.setFirstPaymentDate("03/15/2019");
        a.setNextPaymentDate("01/15/2026");
        a.setEscrowBalance("3,000.00");
        a.setLtvPercent("80.0");
        a.setAppraisedValue("300,000");
        a.setCreatedDate("02/01/2019");
        a.setUpdatedDate("12/01/2025");
        return a;
    }

    private LegacyPayment buildPayment(String seqNbr, String acctNbr,
                                        String pmtDate, String total,
                                        String principal, String interest,
                                        String escrow, String lateFee,
                                        String type, String status) {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber(seqNbr);
        p.setLoanAccountNumber(acctNbr);
        p.setPaymentDate(pmtDate);
        p.setTotalAmount(total);
        p.setPrincipalAmount(principal);
        p.setInterestAmount(interest);
        p.setEscrowAmount(escrow);
        p.setLateFee(lateFee);
        p.setTypeCode(type);
        p.setStatusCode(status);
        p.setReceivedDate(pmtDate);
        p.setProcessedDate(pmtDate);
        p.setCreatedDate(pmtDate);
        p.setUpdatedDate(pmtDate);
        return p;
    }
}
