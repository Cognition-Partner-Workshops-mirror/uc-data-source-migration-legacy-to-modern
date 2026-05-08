package com.workshop.loanservice.service;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for LegacyDataValidator — verifies that each anomaly type
 * from DATA_ANOMALY_REPORT.md is caught by the validation layer.
 */
class LegacyDataValidatorTest {

    private LegacyDataValidator validator;

    @BeforeEach
    void setUp() {
        validator = new LegacyDataValidator();
    }

    // =========================================================================
    // ANO-002: Safe numeric parsing tests
    // =========================================================================

    @Nested
    @DisplayName("ANO-002: Safe numeric parsing (amount, decimal, integer)")
    class SafeNumericParsingTests {

        @Test
        @DisplayName("Parse valid comma-formatted amount")
        void parseValidAmount() {
            BigDecimal result = validator.safeParseLegacyAmount("285,000", "TEST-001", "LN_ORIG_AMT");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Parse valid decimal amount with commas")
        void parseValidDecimalAmount() {
            BigDecimal result = validator.safeParseLegacyAmount("1,487.02", "TEST-001", "PMT_AMT");
            assertEquals(new BigDecimal("1487.02"), result);
        }

        @Test
        @DisplayName("Return ZERO for null amount instead of throwing")
        void parseNullAmount() {
            BigDecimal result = validator.safeParseLegacyAmount(null, "TEST-001", "LN_ORIG_AMT");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Return ZERO for blank amount instead of throwing")
        void parseBlankAmount() {
            BigDecimal result = validator.safeParseLegacyAmount("  ", "TEST-001", "LN_ORIG_AMT");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Handle dollar sign in amount without throwing (ANO-002)")
        void parseDollarSignAmount() {
            // Legacy data might include $ prefix — should not crash
            BigDecimal result = validator.safeParseLegacyAmount("$285,000", "TEST-001", "LN_ORIG_AMT");
            assertEquals(new BigDecimal("285000"), result);
        }

        @Test
        @DisplayName("Return ZERO for non-numeric amount like 'N/A' (ANO-002)")
        void parseNonNumericAmount() {
            BigDecimal result = validator.safeParseLegacyAmount("N/A", "TEST-001", "LN_ORIG_AMT");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Handle percent sign in decimal without throwing (ANO-002)")
        void parsePercentDecimal() {
            BigDecimal result = validator.safeParseLegacyDecimal("5.250%", "TEST-001", "LN_INT_RT");
            assertEquals(new BigDecimal("5.250"), result);
        }

        @Test
        @DisplayName("Return ZERO for non-numeric decimal like 'variable' (ANO-002)")
        void parseNonNumericDecimal() {
            BigDecimal result = validator.safeParseLegacyDecimal("variable", "TEST-001", "LN_INT_RT");
            assertEquals(BigDecimal.ZERO, result);
        }

        @Test
        @DisplayName("Parse valid integer string")
        void parseValidInteger() {
            Integer result = validator.safeParseLegacyInteger("745", "TEST-001", "BORR_CRDT_SCR");
            assertEquals(745, result);
        }

        @Test
        @DisplayName("Return null for non-numeric integer like 'N/A' (ANO-002)")
        void parseNonNumericInteger() {
            Integer result = validator.safeParseLegacyInteger("N/A", "TEST-001", "BORR_CRDT_SCR");
            assertNull(result);
        }

        @Test
        @DisplayName("Return null for null integer input")
        void parseNullInteger() {
            Integer result = validator.safeParseLegacyInteger(null, "TEST-001", "BORR_CRDT_SCR");
            assertNull(result);
        }

        @Test
        @DisplayName("Return null for blank integer input")
        void parseBlankInteger() {
            Integer result = validator.safeParseLegacyInteger("  ", "TEST-001", "BORR_CRDT_SCR");
            assertNull(result);
        }
    }

    // =========================================================================
    // ANO-007: Date parsing tests
    // =========================================================================

    @Nested
    @DisplayName("ANO-007: Date format validation and ISO-8601 conversion")
    class DateParsingTests {

        @Test
        @DisplayName("Parse valid MM/DD/YYYY to ISO-8601")
        void parseValidDate() {
            String result = validator.safeParseLegacyDate("03/15/1978", "TEST-001", "BORR_DOB_DT");
            assertEquals("1978-03-15", result);
        }

        @Test
        @DisplayName("Return raw string for invalid date like 13/01/2025 (ANO-007)")
        void parseInvalidMonthDate() {
            // Month 13 is invalid — should not crash, returns raw string
            String result = validator.safeParseLegacyDate("13/01/2025", "TEST-001", "BORR_DOB_DT");
            assertEquals("13/01/2025", result);
        }

        @Test
        @DisplayName("Resolve invalid leap year date 02/29/2023 to nearest valid date (ANO-007)")
        void parseInvalidLeapYearDate() {
            // 2023 is not a leap year — Java's smart resolver adjusts to Feb 28
            String result = validator.safeParseLegacyDate("02/29/2023", "TEST-001", "BORR_DOB_DT");
            assertEquals("2023-02-28", result);
        }

        @Test
        @DisplayName("Return null for null date input")
        void parseNullDate() {
            String result = validator.safeParseLegacyDate(null, "TEST-001", "BORR_DOB_DT");
            assertNull(result);
        }

        @Test
        @DisplayName("Return null for blank date input")
        void parseBlankDate() {
            String result = validator.safeParseLegacyDate("  ", "TEST-001", "BORR_DOB_DT");
            assertNull(result);
        }
    }

    // =========================================================================
    // ANO-004: Required field null checks + ANO-009: Credit score range
    // =========================================================================

    @Nested
    @DisplayName("ANO-004/ANO-009: Borrower validation")
    class BorrowerValidationTests {

        @Test
        @DisplayName("Valid borrower produces no warnings")
        void validBorrowerNoWarnings() {
            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell", "745");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.isEmpty());
        }

        @Test
        @DisplayName("Detect null first name (ANO-004)")
        void detectNullFirstName() {
            LegacyBorrower borrower = createBorrower("B-10001", null, "Mitchell", "745");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-004") && w.contains("first name")));
        }

        @Test
        @DisplayName("Detect null last name (ANO-004)")
        void detectNullLastName() {
            LegacyBorrower borrower = createBorrower("B-10001", "James", null, "745");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-004") && w.contains("last name")));
        }

        @Test
        @DisplayName("Detect null SSN (ANO-004)")
        void detectNullSsn() {
            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell", "745");
            borrower.setSsnEncrypted(null);
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-004") && w.contains("SSN")));
        }

        @Test
        @DisplayName("Detect out-of-range credit score below 300 (ANO-009)")
        void detectLowCreditScore() {
            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell", "200");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-009") && w.contains("200")));
        }

        @Test
        @DisplayName("Detect out-of-range credit score above 850 (ANO-009)")
        void detectHighCreditScore() {
            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell", "999");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-009") && w.contains("999")));
        }

        @Test
        @DisplayName("Accept valid credit score of 745 (ANO-009)")
        void acceptValidCreditScore() {
            LegacyBorrower borrower = createBorrower("B-10001", "James", "Mitchell", "745");
            List<String> warnings = validator.validateBorrower(borrower);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("ANO-009")));
        }
    }

    // =========================================================================
    // ANO-003: Delinquent loan with Active status
    // =========================================================================

    @Nested
    @DisplayName("ANO-003: Loan status/delinquency cross-validation")
    class LoanStatusValidationTests {

        private final Set<String> validBorrowerIds = Set.of("B-10001", "B-10002", "B-10003");
        private final Set<String> validProductCodes = Set.of("FXD30", "FXD15", "ARM51");

        @Test
        @DisplayName("Detect delinquent loan with Active status (ANO-003)")
        void detectDelinquentActiveStatus() {
            LegacyLoanAccount account = createLoanAccount("LN-001", "B-10001", "FXD30", "ACT", "15");
            List<String> warnings = validator.validateLoanAccount(account, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-003") && w.contains("15 delinquency days")));
        }

        @Test
        @DisplayName("Accept active loan with zero delinquency days")
        void acceptActiveWithZeroDelinquency() {
            LegacyLoanAccount account = createLoanAccount("LN-001", "B-10001", "FXD30", "ACT", "0");
            List<String> warnings = validator.validateLoanAccount(account, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("ANO-003")));
        }

        @Test
        @DisplayName("Accept defaulted loan with delinquency days")
        void acceptDefaultedWithDelinquency() {
            LegacyLoanAccount account = createLoanAccount("LN-001", "B-10001", "FXD30", "DFT", "30");
            List<String> warnings = validator.validateLoanAccount(account, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("delinquency days but status is ACT")));
        }

        @Test
        @DisplayName("Detect unrecognized status code")
        void detectUnrecognizedStatusCode() {
            LegacyLoanAccount account = createLoanAccount("LN-001", "B-10001", "FXD30", "XYZ", "0");
            List<String> warnings = validator.validateLoanAccount(account, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("unrecognized status code")));
        }

        @Test
        @DisplayName("Status expansion includes delinquency qualifier for ANO-003 cases")
        void statusExpansionWithDelinquencyQualifier() {
            String status = validator.expandLoanStatusWithDelinquencyCheck("ACT", "15", "LN-001");
            assertTrue(status.contains("Active"));
            assertTrue(status.contains("Delinquent"));
            assertTrue(status.contains("15 days"));
        }

        @Test
        @DisplayName("Status expansion returns plain Active for zero delinquency")
        void statusExpansionPlainActive() {
            String status = validator.expandLoanStatusWithDelinquencyCheck("ACT", "0", "LN-001");
            assertEquals("Active", status);
        }
    }

    // =========================================================================
    // ANO-006: Orphaned foreign key references
    // =========================================================================

    @Nested
    @DisplayName("ANO-006: Foreign key validation (orphan detection)")
    class ForeignKeyValidationTests {

        @Test
        @DisplayName("Detect orphaned borrower reference in loan account")
        void detectOrphanedBorrower() {
            Set<String> validBorrowerIds = Set.of("B-10001", "B-10002");
            Set<String> validProductCodes = Set.of("FXD30");
            // B-99999 does not exist in valid borrower IDs
            LegacyLoanAccount account = createLoanAccount("LN-001", "B-99999", "FXD30", "ACT", "0");
            List<String> warnings = validator.validateLoanAccount(account, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-006") && w.contains("B-99999")));
        }

        @Test
        @DisplayName("Detect orphaned product reference in loan account")
        void detectOrphanedProduct() {
            Set<String> validBorrowerIds = Set.of("B-10001");
            Set<String> validProductCodes = Set.of("FXD30");
            // UNKNOWN product code
            LegacyLoanAccount account = createLoanAccount("LN-001", "B-10001", "UNKNOWN", "ACT", "0");
            List<String> warnings = validator.validateLoanAccount(account, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-006") && w.contains("UNKNOWN")));
        }

        @Test
        @DisplayName("Detect orphaned loan account reference in payment")
        void detectOrphanedLoanInPayment() {
            Set<String> validLoanAccountNumbers = Set.of("LN-001", "LN-002");
            LegacyPayment payment = createPayment("PMT-001", "LN-MISSING",
                    "1,000.00", "500.00", "400.00", "100.00", "0.00");
            List<String> warnings = validator.validatePayment(payment, validLoanAccountNumbers);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-006") && w.contains("LN-MISSING")));
        }

        @Test
        @DisplayName("Accept valid foreign key references")
        void acceptValidForeignKeys() {
            Set<String> validBorrowerIds = Set.of("B-10001");
            Set<String> validProductCodes = Set.of("FXD30");
            LegacyLoanAccount account = createLoanAccount("LN-001", "B-10001", "FXD30", "ACT", "0");
            List<String> warnings = validator.validateLoanAccount(account, validBorrowerIds, validProductCodes);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("ANO-006")));
        }
    }

    // =========================================================================
    // ANO-001: Payment component sum mismatch
    // =========================================================================

    @Nested
    @DisplayName("ANO-001: Payment component sum validation")
    class PaymentSumValidationTests {

        private final Set<String> validLoanIds = Set.of("LN-001");

        @Test
        @DisplayName("Detect payment total mismatch (sum > total, ANO-001)")
        void detectPaymentSumMismatch() {
            // Total 1,487.02 but components sum to 1,887.02 — matches seed data anomaly
            LegacyPayment payment = createPayment("PMT-001", "LN-001",
                    "1,487.02", "456.78", "1,074.69", "355.55", "0.00");
            List<String> warnings = validator.validatePayment(payment, validLoanIds);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-001")));
        }

        @Test
        @DisplayName("Accept payment where components match total")
        void acceptMatchingPayment() {
            // Total 2,924.18 = 1,842.56 + 815.50 + 266.12 + 0.00
            LegacyPayment payment = createPayment("PMT-002", "LN-001",
                    "2,924.18", "1,842.56", "815.50", "266.12", "0.00");
            List<String> warnings = validator.validatePayment(payment, validLoanIds);
            assertTrue(warnings.stream().noneMatch(w -> w.contains("ANO-001")));
        }

        @Test
        @DisplayName("Detect late fee causing sum mismatch (ANO-001 variant)")
        void detectLateFeeInducedMismatch() {
            // Total 1,077.05 but 295.82 + 781.23 + 0.00 + 47.50 = 1,124.55
            LegacyPayment payment = createPayment("PMT-003", "LN-001",
                    "1,077.05", "295.82", "781.23", "0.00", "47.50");
            List<String> warnings = validator.validatePayment(payment, validLoanIds);
            assertTrue(warnings.stream().anyMatch(w -> w.contains("ANO-001")));
        }
    }

    // =========================================================================
    // ANO-004: Null-safe name building
    // =========================================================================

    @Nested
    @DisplayName("ANO-004: Null-safe name construction")
    class NullSafeNameTests {

        @Test
        @DisplayName("Build full name with middle initial")
        void fullNameWithMiddle() {
            String name = validator.safeBuildFullName("James", "R", "Mitchell");
            assertEquals("James R. Mitchell", name);
        }

        @Test
        @DisplayName("Build full name without middle initial")
        void fullNameWithoutMiddle() {
            String name = validator.safeBuildFullName("Robert", null, "Williams");
            assertEquals("Robert Williams", name);
        }

        @Test
        @DisplayName("Handle null first name with [MISSING] placeholder")
        void nullFirstName() {
            String name = validator.safeBuildFullName(null, "R", "Mitchell");
            assertEquals("[MISSING] R. Mitchell", name);
        }

        @Test
        @DisplayName("Handle null last name with [MISSING] placeholder")
        void nullLastName() {
            String name = validator.safeBuildFullName("James", "R", null);
            assertEquals("James R. [MISSING]", name);
        }

        @Test
        @DisplayName("Handle both null names with [MISSING] placeholders")
        void bothNullNames() {
            String name = validator.safeBuildFullName(null, null, null);
            assertEquals("[MISSING] [MISSING]", name);
        }

        @Test
        @DisplayName("Build borrower name from loan account denormalized fields")
        void borrowerNameFromLoanAccount() {
            String name = validator.safeBuildBorrowerName("James", "Mitchell");
            assertEquals("James Mitchell", name);
        }

        @Test
        @DisplayName("Handle null borrower name in loan account")
        void nullBorrowerNameInLoanAccount() {
            String name = validator.safeBuildBorrowerName(null, null);
            assertEquals("[MISSING] [MISSING]", name);
        }
    }

    // =========================================================================
    // Status and type expansion tests
    // =========================================================================

    @Nested
    @DisplayName("Status and type code expansion")
    class CodeExpansionTests {

        @Test
        @DisplayName("Expand all known loan status codes")
        void expandLoanStatusCodes() {
            assertEquals("Active", validator.expandStatusCode("ACT"));
            assertEquals("Closed", validator.expandStatusCode("CLO"));
            assertEquals("Default", validator.expandStatusCode("DFT"));
            assertEquals("Forbearance", validator.expandStatusCode("FRB"));
        }

        @Test
        @DisplayName("Return raw code for unknown status")
        void expandUnknownStatus() {
            assertEquals("XYZ", validator.expandStatusCode("XYZ"));
        }

        @Test
        @DisplayName("Return 'Unknown' for null status")
        void expandNullStatus() {
            assertEquals("Unknown", validator.expandStatusCode(null));
        }

        @Test
        @DisplayName("Expand all known property type codes")
        void expandPropertyTypeCodes() {
            assertEquals("Single Family Residence", validator.expandPropertyType("SFR"));
            assertEquals("Condominium", validator.expandPropertyType("CND"));
            assertEquals("Multi-Family Residence", validator.expandPropertyType("MFR"));
            assertEquals("Townhouse", validator.expandPropertyType("TWN"));
        }

        @Test
        @DisplayName("Expand all known payment type codes")
        void expandPaymentTypeCodes() {
            assertEquals("Regular", validator.expandPaymentType("REG"));
            assertEquals("Extra", validator.expandPaymentType("EXT"));
            assertEquals("Partial", validator.expandPaymentType("PRT"));
            assertEquals("Prepayment", validator.expandPaymentType("PRE"));
        }

        @Test
        @DisplayName("Expand all known payment status codes")
        void expandPaymentStatusCodes() {
            assertEquals("Posted", validator.expandPaymentStatus("PST"));
            assertEquals("Reversed", validator.expandPaymentStatus("REV"));
            assertEquals("Non-Sufficient Funds", validator.expandPaymentStatus("NSF"));
            assertEquals("Pending", validator.expandPaymentStatus("PND"));
        }
    }

    // =========================================================================
    // Helper methods to create test entities
    // =========================================================================

    private LegacyBorrower createBorrower(String id, String firstName, String lastName, String creditScore) {
        LegacyBorrower b = new LegacyBorrower();
        b.setBorrowerId(id);
        b.setFirstName(firstName);
        b.setLastName(lastName);
        b.setCreditScore(creditScore);
        b.setSsnEncrypted("ENC_XXX_001");
        b.setMiddleInitial("R");
        b.setEmail("test@email.com");
        b.setPhoneNumber("555-0100");
        b.setCity("Springfield");
        b.setStateCode("IL");
        b.setEmploymentStatus("EMPLOYED");
        b.setAnnualIncome("92,500");
        b.setStatusCode("ACT");
        return b;
    }

    private LegacyLoanAccount createLoanAccount(String loanId, String borrowerId,
                                                  String productCode, String statusCode,
                                                  String delinquencyDays) {
        LegacyLoanAccount a = new LegacyLoanAccount();
        a.setLoanAccountNumber(loanId);
        a.setBorrowerId(borrowerId);
        a.setProductCode(productCode);
        a.setStatusCode(statusCode);
        a.setDelinquencyDays(delinquencyDays);
        a.setBorrowerFirstName("James");
        a.setBorrowerLastName("Mitchell");
        a.setOriginalAmount("285,000");
        a.setCurrentBalance("271,432.56");
        a.setInterestRate("4.750");
        a.setTermMonths("360");
        a.setMonthlyPayment("1,487.02");
        a.setOriginationDate("02/15/2019");
        a.setMaturityDate("02/15/2049");
        a.setPropertyAddress("742 Elm Street");
        a.setPropertyCity("Springfield");
        a.setPropertyState("IL");
        a.setPropertyZip("62701");
        a.setPropertyType("SFR");
        a.setAppraisedValue("345,000");
        return a;
    }

    private LegacyPayment createPayment(String paymentId, String loanAccountNumber,
                                         String totalAmount, String principalAmount,
                                         String interestAmount, String escrowAmount,
                                         String lateFee) {
        LegacyPayment p = new LegacyPayment();
        p.setPaymentSequenceNumber(paymentId);
        p.setLoanAccountNumber(loanAccountNumber);
        p.setTotalAmount(totalAmount);
        p.setPrincipalAmount(principalAmount);
        p.setInterestAmount(interestAmount);
        p.setEscrowAmount(escrowAmount);
        p.setLateFee(lateFee);
        p.setTypeCode("REG");
        p.setStatusCode("PST");
        p.setPaymentDate("12/15/2025");
        p.setReceivedDate("12/14/2025");
        p.setProcessedDate("12/15/2025");
        return p;
    }
}
