package com.workshop.loanservice.service;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyLoanProduct;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Nested;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

/**
 * Tests for data quality validation logic in LoanService.
 * Each nested class covers a specific anomaly type identified in the DATA_ANOMALY_REPORT.
 */
@ExtendWith(MockitoExtension.class)
class LoanServiceValidationTest {

    @Mock
    private LegacyBorrowerRepository borrowerRepository;
    @Mock
    private LegacyLoanAccountRepository loanAccountRepository;
    @Mock
    private LegacyLoanProductRepository loanProductRepository;
    @Mock
    private LegacyPaymentRepository paymentRepository;

    @InjectMocks
    private LoanService loanService;

    // =========================================================================
    // ANO-001: Payment Component Sum Validation
    // =========================================================================

    @Nested
    class PaymentComponentSumValidation {

        @Test
        void shouldWarnWhenComponentsExceedTotal() {
            LegacyPayment pmt = buildPayment("PMT-001", "1,487.02", "456.78", "1,074.69", "355.55", "0.00");
            PaymentDto dto = loanService.toPaymentDto(pmt);

            assertThat(dto.getComputedTotal()).isEqualByComparingTo(new BigDecimal("1887.02"));
            assertThat(dto.getTotalAmount()).isEqualByComparingTo(new BigDecimal("1487.02"));
            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("Payment component mismatch"));
        }

        @Test
        void shouldNotWarnWhenComponentsMatchTotal() {
            LegacyPayment pmt = buildPayment("PMT-002", "2,924.18", "1,842.56", "815.50", "266.12", "0.00");
            PaymentDto dto = loanService.toPaymentDto(pmt);

            assertThat(dto.getComputedTotal()).isEqualByComparingTo(new BigDecimal("2924.18"));
            assertThat(dto.getDataQualityWarnings()).noneMatch(w -> w.contains("Payment component mismatch"));
        }

        @Test
        void shouldDetectLateFeeNotInTotal() {
            LegacyPayment pmt = buildPayment("PMT-003", "1,077.05", "295.82", "781.23", "0.00", "47.50");
            PaymentDto dto = loanService.toPaymentDto(pmt);

            assertThat(dto.getComputedTotal()).isEqualByComparingTo(new BigDecimal("1124.55"));
            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("Payment component mismatch"));
            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("delta=47.50"));
        }
    }

    // =========================================================================
    // ANO-003: Numeric Parsing Error Handling
    // =========================================================================

    @Nested
    class NumericParsingErrorHandling {

        @Test
        void parseLegacyAmount_shouldHandleDollarSign() {
            List<String> warnings = new ArrayList<>();
            BigDecimal result = loanService.parseLegacyAmount("$285,000", "amount", "TEST-1", warnings);
            assertThat(result).isEqualByComparingTo(new BigDecimal("285000"));
            assertThat(warnings).isEmpty();
        }

        @Test
        void parseLegacyAmount_shouldReturnZeroForNonNumeric() {
            List<String> warnings = new ArrayList<>();
            BigDecimal result = loanService.parseLegacyAmount("N/A", "amount", "TEST-1", warnings);
            assertThat(result).isEqualByComparingTo(BigDecimal.ZERO);
            assertThat(warnings).hasSize(1);
            assertThat(warnings.get(0)).contains("Unparseable amount");
        }

        @Test
        void parseLegacyAmount_shouldReturnZeroForNull() {
            List<String> warnings = new ArrayList<>();
            BigDecimal result = loanService.parseLegacyAmount(null, "amount", "TEST-1", warnings);
            assertThat(result).isEqualByComparingTo(BigDecimal.ZERO);
            assertThat(warnings).isEmpty();
        }

        @Test
        void parseLegacyAmount_shouldReturnZeroForBlank() {
            List<String> warnings = new ArrayList<>();
            BigDecimal result = loanService.parseLegacyAmount("   ", "amount", "TEST-1", warnings);
            assertThat(result).isEqualByComparingTo(BigDecimal.ZERO);
            assertThat(warnings).isEmpty();
        }

        @Test
        void parseLegacyAmount_shouldHandleLetters() {
            List<String> warnings = new ArrayList<>();
            BigDecimal result = loanService.parseLegacyAmount("PENDING", "amount", "TEST-1", warnings);
            assertThat(result).isEqualByComparingTo(BigDecimal.ZERO);
            assertThat(warnings).anyMatch(w -> w.contains("Unparseable amount") && w.contains("PENDING"));
        }

        @Test
        void parseLegacyAmount_shouldParseValidAmountWithCommas() {
            List<String> warnings = new ArrayList<>();
            BigDecimal result = loanService.parseLegacyAmount("1,487.02", "amount", "TEST-1", warnings);
            assertThat(result).isEqualByComparingTo(new BigDecimal("1487.02"));
            assertThat(warnings).isEmpty();
        }

        @Test
        void parseLegacyDecimal_shouldHandlePercentSign() {
            List<String> warnings = new ArrayList<>();
            BigDecimal result = loanService.parseLegacyDecimal("5.250%", "rate", "TEST-1", warnings);
            assertThat(result).isEqualByComparingTo(new BigDecimal("5.250"));
            assertThat(warnings).isEmpty();
        }

        @Test
        void parseLegacyDecimal_shouldReturnZeroForGarbage() {
            List<String> warnings = new ArrayList<>();
            BigDecimal result = loanService.parseLegacyDecimal("TBD", "rate", "TEST-1", warnings);
            assertThat(result).isEqualByComparingTo(BigDecimal.ZERO);
            assertThat(warnings).anyMatch(w -> w.contains("Unparseable decimal"));
        }

        @Test
        void parseLegacyDecimal_shouldReturnZeroForNull() {
            List<String> warnings = new ArrayList<>();
            BigDecimal result = loanService.parseLegacyDecimal(null, "rate", "TEST-1", warnings);
            assertThat(result).isEqualByComparingTo(BigDecimal.ZERO);
            assertThat(warnings).isEmpty();
        }

        @Test
        void parseLegacyInteger_shouldReturnNullForNonNumeric() {
            List<String> warnings = new ArrayList<>();
            Integer result = loanService.parseLegacyInteger("N/A", "score", "TEST-1", warnings);
            assertThat(result).isNull();
            assertThat(warnings).anyMatch(w -> w.contains("Unparseable integer"));
        }

        @Test
        void parseLegacyInteger_shouldReturnNullForNull() {
            List<String> warnings = new ArrayList<>();
            Integer result = loanService.parseLegacyInteger(null, "score", "TEST-1", warnings);
            assertThat(result).isNull();
            assertThat(warnings).isEmpty();
        }

        @Test
        void parseLegacyInteger_shouldReturnNullForBlank() {
            List<String> warnings = new ArrayList<>();
            Integer result = loanService.parseLegacyInteger("  ", "score", "TEST-1", warnings);
            assertThat(result).isNull();
            assertThat(warnings).isEmpty();
        }

        @Test
        void parseLegacyInteger_shouldParseValidInteger() {
            List<String> warnings = new ArrayList<>();
            Integer result = loanService.parseLegacyInteger("745", "score", "TEST-1", warnings);
            assertThat(result).isEqualTo(745);
            assertThat(warnings).isEmpty();
        }

        @Test
        void parseLegacyInteger_shouldHandleSpecialChars() {
            List<String> warnings = new ArrayList<>();
            Integer result = loanService.parseLegacyInteger("---", "score", "TEST-1", warnings);
            assertThat(result).isNull();
            assertThat(warnings).anyMatch(w -> w.contains("Unparseable integer") && w.contains("---"));
        }

        @Test
        void malformedAmountShouldNotCrashPaymentDto() {
            LegacyPayment pmt = buildPayment("PMT-BAD", "INVALID", "N/A", "---", "TBD", "$$$");
            PaymentDto dto = loanService.toPaymentDto(pmt);

            assertThat(dto.getTotalAmount()).isEqualByComparingTo(BigDecimal.ZERO);
            assertThat(dto.getPrincipalAmount()).isEqualByComparingTo(BigDecimal.ZERO);
            assertThat(dto.getDataQualityWarnings()).hasSizeGreaterThanOrEqualTo(4);
        }

        @Test
        void malformedCreditScoreShouldNotCrashBorrowerDto() {
            LegacyBorrower borrower = buildBorrower("B-BAD", "John", "Doe", null, "ABC");
            BorrowerDto dto = loanService.toBorrowerDto(borrower);

            assertThat(dto.getCreditScore()).isNull();
            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("Unparseable integer"));
        }
    }

    // =========================================================================
    // ANO-004: Orphaned Records (Referential Integrity)
    // =========================================================================

    @Nested
    class OrphanedRecordsValidation {

        @Test
        void shouldWarnWhenProductCodeNotFound() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "INVALID_PROD", "ACT", "0");
            LoanSummaryDto dto = loanService.toLoanSummary(acct, null);

            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("Orphaned product code"));
            assertThat(dto.getProductDescription()).isEqualTo("INVALID_PROD");
        }

        @Test
        void shouldNotWarnWhenProductCodeExists() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "FXD30", "ACT", "0");
            LegacyLoanProduct product = new LegacyLoanProduct();
            product.setProductCode("FXD30");
            product.setDescription("30-Year Fixed");

            LoanSummaryDto dto = loanService.toLoanSummary(acct, product);

            assertThat(dto.getDataQualityWarnings()).noneMatch(w -> w.contains("Orphaned product code"));
            assertThat(dto.getProductDescription()).isEqualTo("30-Year Fixed");
        }
    }

    // =========================================================================
    // ANO-005: Delinquency/Status Cross-Validation
    // =========================================================================

    @Nested
    class DelinquencyStatusValidation {

        @Test
        void shouldWarnWhenDelinquentButActive() {
            List<String> warnings = new ArrayList<>();
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "FXD30", "ACT", "15");
            loanService.validateDelinquencyStatus(acct, warnings);

            assertThat(warnings).anyMatch(w -> w.contains("Delinquency/status inconsistency"));
            assertThat(warnings).anyMatch(w -> w.contains("15 days delinquent"));
        }

        @Test
        void shouldNotWarnWhenZeroDelinquencyAndActive() {
            List<String> warnings = new ArrayList<>();
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "FXD30", "ACT", "0");
            loanService.validateDelinquencyStatus(acct, warnings);

            assertThat(warnings).isEmpty();
        }

        @Test
        void shouldNotWarnWhenDelinquentAndNotActive() {
            List<String> warnings = new ArrayList<>();
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "FXD30", "DFT", "90");
            loanService.validateDelinquencyStatus(acct, warnings);

            assertThat(warnings).isEmpty();
        }

        @Test
        void shouldHandleNullDelinquencyDays() {
            List<String> warnings = new ArrayList<>();
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "FXD30", "ACT", null);
            loanService.validateDelinquencyStatus(acct, warnings);

            assertThat(warnings).isEmpty();
        }

        @Test
        void shouldHandleNonNumericDelinquencyDays() {
            List<String> warnings = new ArrayList<>();
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "FXD30", "ACT", "N/A");
            loanService.validateDelinquencyStatus(acct, warnings);

            assertThat(warnings).isEmpty();
        }

        @Test
        void delinquencyWarningAppearsInLoanSummary() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "FXD30", "ACT", "15");
            LegacyLoanProduct product = new LegacyLoanProduct();
            product.setProductCode("FXD30");
            product.setDescription("30-Year Fixed");

            LoanSummaryDto dto = loanService.toLoanSummary(acct, product);

            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("Delinquency/status inconsistency"));
        }
    }

    // =========================================================================
    // ANO-007: Payment Date Sorting
    // =========================================================================

    @Nested
    class PaymentDateSorting {

        @Test
        void shouldSortPaymentsByParsedDateDescending() {
            LegacyPayment jan2026 = buildPayment("PMT-A", "100.00", "50.00", "50.00", "0.00", "0.00");
            jan2026.setPaymentDate("01/15/2026");

            LegacyPayment dec2025 = buildPayment("PMT-B", "100.00", "50.00", "50.00", "0.00", "0.00");
            dec2025.setPaymentDate("12/01/2025");

            LegacyPayment nov2025 = buildPayment("PMT-C", "100.00", "50.00", "50.00", "0.00", "0.00");
            nov2025.setPaymentDate("11/01/2025");

            when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-001"))
                    .thenReturn(List.of(dec2025, jan2026, nov2025));

            List<PaymentDto> result = loanService.getPaymentsByLoan("LN-001");

            assertThat(result).hasSize(3);
            assertThat(result.get(0).getPaymentDate()).isEqualTo("01/15/2026");
            assertThat(result.get(1).getPaymentDate()).isEqualTo("12/01/2025");
            assertThat(result.get(2).getPaymentDate()).isEqualTo("11/01/2025");
        }
    }

    // =========================================================================
    // ANO-008: Date Format Validation
    // =========================================================================

    @Nested
    class DateFormatValidation {

        @Test
        void shouldAcceptValidMmDdYyyyDate() {
            List<String> warnings = new ArrayList<>();
            String result = loanService.validateLegacyDate("03/15/2019", "originationDate", "LN-001", warnings);
            assertThat(result).isEqualTo("03/15/2019");
            assertThat(warnings).isEmpty();
        }

        @Test
        void shouldRejectInvalidDate_Feb30() {
            List<String> warnings = new ArrayList<>();
            String result = loanService.validateLegacyDate("02/30/2020", "originationDate", "LN-001", warnings);
            assertThat(result).isNull();
            assertThat(warnings).anyMatch(w -> w.contains("Invalid date"));
        }

        @Test
        void shouldRejectInvalidDate_Month13() {
            List<String> warnings = new ArrayList<>();
            String result = loanService.validateLegacyDate("13/01/2020", "originationDate", "LN-001", warnings);
            assertThat(result).isNull();
            assertThat(warnings).anyMatch(w -> w.contains("Invalid date"));
        }

        @Test
        void shouldRejectNonDateString() {
            List<String> warnings = new ArrayList<>();
            String result = loanService.validateLegacyDate("TBD", "originationDate", "LN-001", warnings);
            assertThat(result).isNull();
            assertThat(warnings).anyMatch(w -> w.contains("Invalid date") && w.contains("TBD"));
        }

        @Test
        void shouldReturnNullForNullDate() {
            List<String> warnings = new ArrayList<>();
            String result = loanService.validateLegacyDate(null, "originationDate", "LN-001", warnings);
            assertThat(result).isNull();
            assertThat(warnings).isEmpty();
        }

        @Test
        void shouldRejectWrongFormat_YyyyMmDd() {
            List<String> warnings = new ArrayList<>();
            String result = loanService.validateLegacyDate("2020-01-15", "originationDate", "LN-001", warnings);
            assertThat(result).isNull();
            assertThat(warnings).anyMatch(w -> w.contains("Invalid date"));
        }

        @Test
        void shouldRejectZeroDate() {
            List<String> warnings = new ArrayList<>();
            String result = loanService.validateLegacyDate("00/00/0000", "originationDate", "LN-001", warnings);
            assertThat(result).isNull();
            assertThat(warnings).anyMatch(w -> w.contains("Invalid date"));
        }

        @Test
        void dateValidationAppearsInPaymentDto() {
            LegacyPayment pmt = buildPayment("PMT-001", "100.00", "50.00", "50.00", "0.00", "0.00");
            pmt.setPaymentDate("INVALID");
            PaymentDto dto = loanService.toPaymentDto(pmt);

            assertThat(dto.getPaymentDate()).isNull();
            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("Invalid date"));
        }

        @Test
        void dateValidationAppearsInLoanSummary() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "FXD30", "ACT", "0");
            acct.setOriginationDate("BAD-DATE");
            LegacyLoanProduct product = new LegacyLoanProduct();
            product.setProductCode("FXD30");
            product.setDescription("30-Year Fixed");

            LoanSummaryDto dto = loanService.toLoanSummary(acct, product);

            assertThat(dto.getOriginationDate()).isNull();
            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("Invalid date"));
        }
    }

    // =========================================================================
    // ANO-011: Credit Score Range Validation
    // =========================================================================

    @Nested
    class CreditScoreRangeValidation {

        @Test
        void shouldNotWarnForValidScore() {
            List<String> warnings = new ArrayList<>();
            loanService.validateCreditScoreRange(745, "B-001", warnings);
            assertThat(warnings).isEmpty();
        }

        @Test
        void shouldWarnForScoreBelowMin() {
            List<String> warnings = new ArrayList<>();
            loanService.validateCreditScoreRange(200, "B-001", warnings);
            assertThat(warnings).anyMatch(w -> w.contains("outside valid FICO range"));
        }

        @Test
        void shouldWarnForScoreAboveMax() {
            List<String> warnings = new ArrayList<>();
            loanService.validateCreditScoreRange(900, "B-001", warnings);
            assertThat(warnings).anyMatch(w -> w.contains("outside valid FICO range"));
        }

        @Test
        void shouldAcceptBoundaryMinScore() {
            List<String> warnings = new ArrayList<>();
            loanService.validateCreditScoreRange(300, "B-001", warnings);
            assertThat(warnings).isEmpty();
        }

        @Test
        void shouldAcceptBoundaryMaxScore() {
            List<String> warnings = new ArrayList<>();
            loanService.validateCreditScoreRange(850, "B-001", warnings);
            assertThat(warnings).isEmpty();
        }

        @Test
        void shouldWarnForZeroScore() {
            List<String> warnings = new ArrayList<>();
            loanService.validateCreditScoreRange(0, "B-001", warnings);
            assertThat(warnings).anyMatch(w -> w.contains("outside valid FICO range"));
        }

        @Test
        void creditScoreWarningAppearsInBorrowerDto() {
            LegacyBorrower borrower = buildBorrower("B-001", "John", "Doe", null, "999");
            BorrowerDto dto = loanService.toBorrowerDto(borrower);

            assertThat(dto.getCreditScore()).isEqualTo(999);
            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("outside valid FICO range"));
        }
    }

    // =========================================================================
    // ANO-012: Null-Safe String Handling
    // =========================================================================

    @Nested
    class NullSafeStringHandling {

        @Test
        void nullSafe_shouldReturnEmptyForNull() {
            assertThat(LoanService.nullSafe(null)).isEmpty();
        }

        @Test
        void nullSafe_shouldReturnValueForNonNull() {
            assertThat(LoanService.nullSafe("hello")).isEqualTo("hello");
        }

        @Test
        void borrowerNameShouldNotContainLiteralNull() {
            LegacyBorrower borrower = buildBorrower("B-001", null, null, null, "700");
            BorrowerDto dto = loanService.toBorrowerDto(borrower);

            assertThat(dto.getFullName()).doesNotContain("null");
        }

        @Test
        void borrowerNameShouldIncludeMiddleInitialWhenPresent() {
            LegacyBorrower borrower = buildBorrower("B-001", "John", "Doe", "A", "700");
            BorrowerDto dto = loanService.toBorrowerDto(borrower);

            assertThat(dto.getFullName()).isEqualTo("John A. Doe");
        }

        @Test
        void borrowerNameShouldSkipMiddleInitialWhenNull() {
            LegacyBorrower borrower = buildBorrower("B-001", "John", "Doe", null, "700");
            BorrowerDto dto = loanService.toBorrowerDto(borrower);

            assertThat(dto.getFullName()).isEqualTo("John Doe");
        }

        @Test
        void propertyAddressShouldNotContainLiteralNull() {
            LegacyLoanAccount acct = buildLoanAccount("LN-001", "B-001", "FXD30", "ACT", "0");
            acct.setPropertyAddress(null);
            acct.setPropertyCity(null);
            acct.setPropertyState(null);
            acct.setPropertyZip(null);

            LegacyLoanProduct product = new LegacyLoanProduct();
            product.setProductCode("FXD30");
            product.setDescription("30-Year Fixed");

            LoanSummaryDto dto = loanService.toLoanSummary(acct, product);

            assertThat(dto.getPropertyAddress()).doesNotContain("null");
        }
    }

    // =========================================================================
    // Integration-style: Full DTO mapping with real seed data patterns
    // =========================================================================

    @Nested
    class FullDtoMappingWithSeedDataPatterns {

        @Test
        void shouldMapCleanLoanAccountWithNoWarnings() {
            LegacyLoanAccount acct = buildLoanAccount("LN-2020-00398", "B-10002", "ARM5", "ACT", "0");
            acct.setOriginalAmount("450,000");
            acct.setCurrentBalance("412,567.89");
            acct.setInterestRate("4.750");
            acct.setMonthlyPayment("2,924.18");
            acct.setOriginationDate("06/01/2020");
            acct.setPropertyAddress("1523 Oak Avenue");
            acct.setPropertyCity("Portland");
            acct.setPropertyState("OR");
            acct.setPropertyZip("97201");
            acct.setPropertyType("CND");
            acct.setBorrowerFirstName("Sarah");
            acct.setBorrowerLastName("Johnson");

            LegacyLoanProduct product = new LegacyLoanProduct();
            product.setProductCode("ARM5");
            product.setDescription("5/1 Adjustable Rate");

            LoanSummaryDto dto = loanService.toLoanSummary(acct, product);

            assertThat(dto.getBorrowerName()).isEqualTo("Sarah Johnson");
            assertThat(dto.getOriginalAmount()).isEqualByComparingTo(new BigDecimal("450000"));
            assertThat(dto.getCurrentBalance()).isEqualByComparingTo(new BigDecimal("412567.89"));
            assertThat(dto.getInterestRate()).isEqualByComparingTo(new BigDecimal("4.750"));
            assertThat(dto.getMonthlyPayment()).isEqualByComparingTo(new BigDecimal("2924.18"));
            assertThat(dto.getOriginationDate()).isEqualTo("06/01/2020");
            assertThat(dto.getPropertyType()).isEqualTo("Condominium");
            assertThat(dto.getStatus()).isEqualTo("Active");
            assertThat(dto.getDataQualityWarnings()).isEmpty();
        }

        @Test
        void shouldMapDelinquentLoanWithWarning() {
            LegacyLoanAccount acct = buildLoanAccount("LN-2018-00089", "B-10003", "FXD15", "ACT", "15");
            acct.setOriginalAmount("165,000");
            acct.setCurrentBalance("108,234.56");
            acct.setInterestRate("6.125");
            acct.setMonthlyPayment("1,077.05");
            acct.setOriginationDate("11/15/2018");
            acct.setPropertyAddress("892 Pine Road");
            acct.setPropertyCity("Austin");
            acct.setPropertyState("TX");
            acct.setPropertyZip("78701");
            acct.setPropertyType("TWN");
            acct.setBorrowerFirstName("Michael");
            acct.setBorrowerLastName("Torres");

            LegacyLoanProduct product = new LegacyLoanProduct();
            product.setProductCode("FXD15");
            product.setDescription("15-Year Fixed");

            LoanSummaryDto dto = loanService.toLoanSummary(acct, product);

            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("Delinquency/status inconsistency"));
        }

        @Test
        void shouldMapPaymentWithMismatchWarning() {
            LegacyPayment pmt = buildPayment("PMT-2025120001", "1,487.02", "456.78", "1,074.69", "355.55", "0.00");
            pmt.setLoanAccountNumber("LN-2019-00142");
            pmt.setPaymentDate("12/01/2025");
            pmt.setTypeCode("REG");
            pmt.setStatusCode("PST");

            PaymentDto dto = loanService.toPaymentDto(pmt);

            assertThat(dto.getType()).isEqualTo("Regular");
            assertThat(dto.getStatus()).isEqualTo("Posted");
            assertThat(dto.getDataQualityWarnings()).anyMatch(w -> w.contains("Payment component mismatch"));
        }

        @Test
        void shouldMapBorrowerWithValidCreditScore() {
            LegacyBorrower borrower = buildBorrower("B-10001", "James", "Anderson", "R", "745");
            borrower.setEmail("james.anderson@email.com");
            borrower.setPhoneNumber("217-555-0142");
            borrower.setCity("Springfield");
            borrower.setStateCode("IL");
            borrower.setEmploymentStatus("EMPLOYED");

            BorrowerDto dto = loanService.toBorrowerDto(borrower);

            assertThat(dto.getFullName()).isEqualTo("James R. Anderson");
            assertThat(dto.getCreditScore()).isEqualTo(745);
            assertThat(dto.getDataQualityWarnings()).isEmpty();
        }
    }

    // =========================================================================
    // Helpers
    // =========================================================================

    private LegacyPayment buildPayment(String id, String total, String principal,
                                        String interest, String escrow, String lateFee) {
        LegacyPayment pmt = new LegacyPayment();
        pmt.setPaymentSequenceNumber(id);
        pmt.setLoanAccountNumber("LN-TEST");
        pmt.setPaymentDate("12/01/2025");
        pmt.setTotalAmount(total);
        pmt.setPrincipalAmount(principal);
        pmt.setInterestAmount(interest);
        pmt.setEscrowAmount(escrow);
        pmt.setLateFee(lateFee);
        pmt.setTypeCode("REG");
        pmt.setStatusCode("PST");
        return pmt;
    }

    private LegacyLoanAccount buildLoanAccount(String loanNumber, String borrowerId,
                                                 String productCode, String statusCode,
                                                 String delinquencyDays) {
        LegacyLoanAccount acct = new LegacyLoanAccount();
        acct.setLoanAccountNumber(loanNumber);
        acct.setBorrowerId(borrowerId);
        acct.setProductCode(productCode);
        acct.setStatusCode(statusCode);
        acct.setDelinquencyDays(delinquencyDays);
        acct.setBorrowerFirstName("Test");
        acct.setBorrowerLastName("User");
        acct.setOriginalAmount("100,000");
        acct.setCurrentBalance("90,000");
        acct.setInterestRate("5.000");
        acct.setMonthlyPayment("1,000.00");
        acct.setOriginationDate("01/01/2020");
        acct.setPropertyAddress("123 Main St");
        acct.setPropertyCity("Anytown");
        acct.setPropertyState("IL");
        acct.setPropertyZip("60601");
        acct.setPropertyType("SFR");
        return acct;
    }

    private LegacyBorrower buildBorrower(String id, String first, String last,
                                          String middleInit, String creditScore) {
        LegacyBorrower borrower = new LegacyBorrower();
        borrower.setBorrowerId(id);
        borrower.setFirstName(first);
        borrower.setLastName(last);
        borrower.setMiddleInitial(middleInit);
        borrower.setCreditScore(creditScore);
        borrower.setEmail("test@example.com");
        borrower.setPhoneNumber("555-555-5555");
        borrower.setCity("Springfield");
        borrower.setStateCode("IL");
        borrower.setEmploymentStatus("EMPLOYED");
        return borrower;
    }
}
