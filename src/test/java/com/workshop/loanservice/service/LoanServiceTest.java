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
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Collections;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

/**
 * Unit tests for LoanService covering all public methods and
 * legacy translation logic (parsing, status expansion, etc.).
 */
@ExtendWith(MockitoExtension.class)
class LoanServiceTest {

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

    private LegacyLoanProduct sampleProduct;
    private LegacyLoanAccount sampleAccount;
    private LegacyBorrower sampleBorrower;
    private LegacyPayment samplePayment;

    @BeforeEach
    void setUp() {
        // Set up a sample loan product
        sampleProduct = new LegacyLoanProduct();
        sampleProduct.setProductCode("FXD30");
        sampleProduct.setDescription("30-Year Fixed Rate Mortgage");
        sampleProduct.setTypeCode("FXD");
        sampleProduct.setTermMonths("360");
        sampleProduct.setRateType("FIXED");
        sampleProduct.setMinAmount("50,000");
        sampleProduct.setMaxAmount("1,500,000");
        sampleProduct.setStatusCode("ACT");
        sampleProduct.setEffectiveDate("01/01/2020");
        sampleProduct.setExpirationDate("12/31/2099");

        // Set up a sample loan account
        sampleAccount = new LegacyLoanAccount();
        sampleAccount.setLoanAccountNumber("LN-2019-00142");
        sampleAccount.setBorrowerId("B-10001");
        sampleAccount.setBorrowerFirstName("James");
        sampleAccount.setBorrowerLastName("Mitchell");
        sampleAccount.setBorrowerSsnLast4("0142");
        sampleAccount.setProductCode("FXD30");
        sampleAccount.setOriginalAmount("285,000");
        sampleAccount.setCurrentBalance("271,432.56");
        sampleAccount.setInterestRate("4.750");
        sampleAccount.setTermMonths("360");
        sampleAccount.setMonthlyPayment("1,487.02");
        sampleAccount.setOriginationDate("02/15/2019");
        sampleAccount.setMaturityDate("02/15/2049");
        sampleAccount.setFirstPaymentDate("03/15/2019");
        sampleAccount.setNextPaymentDate("01/15/2026");
        sampleAccount.setStatusCode("ACT");
        sampleAccount.setDelinquencyDays("0");
        sampleAccount.setEscrowBalance("3,245.80");
        sampleAccount.setLtvPercent("82.5");
        sampleAccount.setPropertyAddress("742 Elm Street");
        sampleAccount.setPropertyCity("Springfield");
        sampleAccount.setPropertyState("IL");
        sampleAccount.setPropertyZip("62701");
        sampleAccount.setPropertyType("SFR");
        sampleAccount.setAppraisedValue("345,000");
        sampleAccount.setCreatedDate("02/01/2019");
        sampleAccount.setUpdatedDate("12/01/2025");

        // Set up a sample borrower
        sampleBorrower = new LegacyBorrower();
        sampleBorrower.setBorrowerId("B-10001");
        sampleBorrower.setFirstName("James");
        sampleBorrower.setLastName("Mitchell");
        sampleBorrower.setMiddleInitial("R");
        sampleBorrower.setSsnEncrypted("ENC_XXX_001");
        sampleBorrower.setDateOfBirth("03/15/1978");
        sampleBorrower.setAddressLine1("742 Elm Street");
        sampleBorrower.setAddressLine2("Apt 3B");
        sampleBorrower.setCity("Springfield");
        sampleBorrower.setStateCode("IL");
        sampleBorrower.setZipCode("62701");
        sampleBorrower.setPhoneNumber("217-555-0142");
        sampleBorrower.setEmail("j.mitchell@email.com");
        sampleBorrower.setCreditScore("745");
        sampleBorrower.setEmploymentStatus("EMPLOYED");
        sampleBorrower.setAnnualIncome("92,500");
        sampleBorrower.setCreatedDate("01/15/2019");
        sampleBorrower.setUpdatedDate("11/03/2025");
        sampleBorrower.setStatusCode("ACT");
        sampleBorrower.setRecordType("PRI");

        // Set up a sample payment
        samplePayment = new LegacyPayment();
        samplePayment.setPaymentSequenceNumber("PMT-2025120001");
        samplePayment.setLoanAccountNumber("LN-2019-00142");
        samplePayment.setPaymentDate("12/15/2025");
        samplePayment.setTotalAmount("1,487.02");
        samplePayment.setPrincipalAmount("456.78");
        samplePayment.setInterestAmount("1,074.69");
        samplePayment.setEscrowAmount("355.55");
        samplePayment.setLateFee("0.00");
        samplePayment.setTypeCode("REG");
        samplePayment.setStatusCode("PST");
        samplePayment.setReceivedDate("12/14/2025");
        samplePayment.setProcessedDate("12/15/2025");
        samplePayment.setCreatedDate("12/15/2025");
        samplePayment.setUpdatedDate("12/15/2025");
    }

    // =========================================================================
    // getAllLoans tests
    // =========================================================================

    @Test
    void getAllLoans_returnsTranslatedLoanSummaries() {
        when(loanProductRepository.findAll()).thenReturn(List.of(sampleProduct));
        when(loanAccountRepository.findAll()).thenReturn(List.of(sampleAccount));

        List<LoanSummaryDto> result = loanService.getAllLoans();

        assertEquals(1, result.size());
        LoanSummaryDto dto = result.get(0);
        assertEquals("LN-2019-00142", dto.getLoanAccountNumber());
        assertEquals("James Mitchell", dto.getBorrowerName());
        assertEquals("30-Year Fixed Rate Mortgage", dto.getProductDescription());
        assertEquals(new BigDecimal("285000"), dto.getOriginalAmount());
        assertEquals(new BigDecimal("271432.56"), dto.getCurrentBalance());
        assertEquals(new BigDecimal("4.750"), dto.getInterestRate());
        assertEquals(new BigDecimal("1487.02"), dto.getMonthlyPayment());
        assertEquals("Active", dto.getStatus());
        assertEquals("02/15/2019", dto.getOriginationDate());
        assertEquals("742 Elm Street, Springfield, IL 62701", dto.getPropertyAddress());
        assertEquals("Single Family Residence", dto.getPropertyType());
    }

    @Test
    void getAllLoans_emptyList() {
        when(loanProductRepository.findAll()).thenReturn(Collections.emptyList());
        when(loanAccountRepository.findAll()).thenReturn(Collections.emptyList());

        List<LoanSummaryDto> result = loanService.getAllLoans();

        assertTrue(result.isEmpty());
    }

    @Test
    void getAllLoans_productNotFound_usesProductCode() {
        // Account references a product code that doesn't exist in the product map
        sampleAccount.setProductCode("UNKNOWN");
        when(loanProductRepository.findAll()).thenReturn(List.of(sampleProduct));
        when(loanAccountRepository.findAll()).thenReturn(List.of(sampleAccount));

        List<LoanSummaryDto> result = loanService.getAllLoans();

        assertEquals(1, result.size());
        // When product is null, the service falls back to using the product code
        assertEquals("UNKNOWN", result.get(0).getProductDescription());
    }

    // =========================================================================
    // getLoanById tests
    // =========================================================================

    @Test
    void getLoanById_found() {
        when(loanAccountRepository.findById("LN-2019-00142")).thenReturn(Optional.of(sampleAccount));
        when(loanProductRepository.findById("FXD30")).thenReturn(Optional.of(sampleProduct));

        LoanSummaryDto dto = loanService.getLoanById("LN-2019-00142");

        assertNotNull(dto);
        assertEquals("LN-2019-00142", dto.getLoanAccountNumber());
        assertEquals("30-Year Fixed Rate Mortgage", dto.getProductDescription());
    }

    @Test
    void getLoanById_notFound_throwsException() {
        when(loanAccountRepository.findById("INVALID")).thenReturn(Optional.empty());

        RuntimeException ex = assertThrows(RuntimeException.class,
                () -> loanService.getLoanById("INVALID"));
        assertTrue(ex.getMessage().contains("Loan not found: INVALID"));
    }

    @Test
    void getLoanById_productNotFound_usesProductCode() {
        when(loanAccountRepository.findById("LN-2019-00142")).thenReturn(Optional.of(sampleAccount));
        when(loanProductRepository.findById("FXD30")).thenReturn(Optional.empty());

        LoanSummaryDto dto = loanService.getLoanById("LN-2019-00142");

        // When product is not found, falls back to product code
        assertEquals("FXD30", dto.getProductDescription());
    }

    // =========================================================================
    // getAllBorrowers tests
    // =========================================================================

    @Test
    void getAllBorrowers_returnsTranslatedBorrowers() {
        when(borrowerRepository.findAll()).thenReturn(List.of(sampleBorrower));

        List<BorrowerDto> result = loanService.getAllBorrowers();

        assertEquals(1, result.size());
        BorrowerDto dto = result.get(0);
        assertEquals("B-10001", dto.getId());
        // Middle initial "R" should appear as " R."
        assertEquals("James R. Mitchell", dto.getFullName());
        assertEquals("j.mitchell@email.com", dto.getEmail());
        assertEquals("217-555-0142", dto.getPhone());
        assertEquals("Springfield", dto.getCity());
        assertEquals("IL", dto.getState());
        assertEquals(745, dto.getCreditScore());
        assertEquals("EMPLOYED", dto.getEmploymentStatus());
    }

    @Test
    void getAllBorrowers_emptyList() {
        when(borrowerRepository.findAll()).thenReturn(Collections.emptyList());

        List<BorrowerDto> result = loanService.getAllBorrowers();

        assertTrue(result.isEmpty());
    }

    @Test
    void getAllBorrowers_nullMiddleInitial_omitsMiddle() {
        // Borrower without a middle initial
        sampleBorrower.setMiddleInitial(null);
        when(borrowerRepository.findAll()).thenReturn(List.of(sampleBorrower));

        List<BorrowerDto> result = loanService.getAllBorrowers();

        assertEquals("James Mitchell", result.get(0).getFullName());
    }

    // =========================================================================
    // getBorrowerById tests
    // =========================================================================

    @Test
    void getBorrowerById_found_withLoans() {
        when(borrowerRepository.findById("B-10001")).thenReturn(Optional.of(sampleBorrower));
        when(loanProductRepository.findAll()).thenReturn(List.of(sampleProduct));
        when(loanAccountRepository.findByBorrowerId("B-10001")).thenReturn(List.of(sampleAccount));

        BorrowerDto dto = loanService.getBorrowerById("B-10001");

        assertNotNull(dto);
        assertEquals("B-10001", dto.getId());
        assertEquals("James R. Mitchell", dto.getFullName());
        assertNotNull(dto.getLoans());
        assertEquals(1, dto.getLoans().size());
        assertEquals("LN-2019-00142", dto.getLoans().get(0).getLoanAccountNumber());
    }

    @Test
    void getBorrowerById_notFound_throwsException() {
        when(borrowerRepository.findById("INVALID")).thenReturn(Optional.empty());

        RuntimeException ex = assertThrows(RuntimeException.class,
                () -> loanService.getBorrowerById("INVALID"));
        assertTrue(ex.getMessage().contains("Borrower not found: INVALID"));
    }

    @Test
    void getBorrowerById_found_noLoans() {
        when(borrowerRepository.findById("B-10001")).thenReturn(Optional.of(sampleBorrower));
        when(loanProductRepository.findAll()).thenReturn(Collections.emptyList());
        when(loanAccountRepository.findByBorrowerId("B-10001")).thenReturn(Collections.emptyList());

        BorrowerDto dto = loanService.getBorrowerById("B-10001");

        assertNotNull(dto);
        assertTrue(dto.getLoans().isEmpty());
    }

    // =========================================================================
    // getPaymentsByLoan tests
    // =========================================================================

    @Test
    void getPaymentsByLoan_returnsTranslatedPayments() {
        when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-2019-00142"))
                .thenReturn(List.of(samplePayment));

        List<PaymentDto> result = loanService.getPaymentsByLoan("LN-2019-00142");

        assertEquals(1, result.size());
        PaymentDto dto = result.get(0);
        assertEquals("PMT-2025120001", dto.getPaymentId());
        assertEquals("LN-2019-00142", dto.getLoanAccountNumber());
        assertEquals("12/15/2025", dto.getPaymentDate());
        assertEquals(new BigDecimal("1487.02"), dto.getTotalAmount());
        assertEquals(new BigDecimal("456.78"), dto.getPrincipalAmount());
        assertEquals(new BigDecimal("1074.69"), dto.getInterestAmount());
        assertEquals(new BigDecimal("355.55"), dto.getEscrowAmount());
        assertEquals(new BigDecimal("0.00"), dto.getLateFee());
        assertEquals("Regular", dto.getType());
        assertEquals("Posted", dto.getStatus());
    }

    @Test
    void getPaymentsByLoan_emptyList() {
        when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-NONE"))
                .thenReturn(Collections.emptyList());

        List<PaymentDto> result = loanService.getPaymentsByLoan("LN-NONE");

        assertTrue(result.isEmpty());
    }

    // =========================================================================
    // Legacy translation edge cases (tested via public API)
    // =========================================================================

    @Test
    void parseLegacyAmount_nullAndBlank_returnZero() {
        // Test null amount fields through loan summary translation
        sampleAccount.setOriginalAmount(null);
        sampleAccount.setCurrentBalance("");
        sampleAccount.setMonthlyPayment("  ");
        when(loanAccountRepository.findById("LN-2019-00142")).thenReturn(Optional.of(sampleAccount));
        when(loanProductRepository.findById("FXD30")).thenReturn(Optional.of(sampleProduct));

        LoanSummaryDto dto = loanService.getLoanById("LN-2019-00142");

        assertEquals(BigDecimal.ZERO, dto.getOriginalAmount());
        assertEquals(BigDecimal.ZERO, dto.getCurrentBalance());
        assertEquals(BigDecimal.ZERO, dto.getMonthlyPayment());
    }

    @Test
    void parseLegacyDecimal_nullAndBlank_returnZero() {
        // Test null/blank interest rate
        sampleAccount.setInterestRate(null);
        when(loanAccountRepository.findById("LN-2019-00142")).thenReturn(Optional.of(sampleAccount));
        when(loanProductRepository.findById("FXD30")).thenReturn(Optional.of(sampleProduct));

        LoanSummaryDto dto = loanService.getLoanById("LN-2019-00142");

        assertEquals(BigDecimal.ZERO, dto.getInterestRate());
    }

    @Test
    void parseLegacyDecimal_blankValue_returnZero() {
        sampleAccount.setInterestRate("   ");
        when(loanAccountRepository.findById("LN-2019-00142")).thenReturn(Optional.of(sampleAccount));
        when(loanProductRepository.findById("FXD30")).thenReturn(Optional.of(sampleProduct));

        LoanSummaryDto dto = loanService.getLoanById("LN-2019-00142");

        assertEquals(BigDecimal.ZERO, dto.getInterestRate());
    }

    @Test
    void parseLegacyInteger_nullAndBlank_returnNull() {
        // Test null credit score
        sampleBorrower.setCreditScore(null);
        when(borrowerRepository.findAll()).thenReturn(List.of(sampleBorrower));

        List<BorrowerDto> result = loanService.getAllBorrowers();

        assertNull(result.get(0).getCreditScore());
    }

    @Test
    void parseLegacyInteger_blankValue_returnNull() {
        sampleBorrower.setCreditScore("  ");
        when(borrowerRepository.findAll()).thenReturn(List.of(sampleBorrower));

        List<BorrowerDto> result = loanService.getAllBorrowers();

        assertNull(result.get(0).getCreditScore());
    }

    // =========================================================================
    // Status code expansion tests (all branches)
    // =========================================================================

    @Test
    void expandStatusCode_allCodes() {
        // Test each loan status code via getLoanById
        verifyLoanStatus("ACT", "Active");
        verifyLoanStatus("CLO", "Closed");
        verifyLoanStatus("DFT", "Default");
        verifyLoanStatus("FRB", "Forbearance");
        verifyLoanStatus("XYZ", "XYZ"); // unknown code returns as-is
        verifyLoanStatus(null, "Unknown");
    }

    @Test
    void expandPropertyType_allCodes() {
        // Test each property type code
        verifyPropertyType("SFR", "Single Family Residence");
        verifyPropertyType("CND", "Condominium");
        verifyPropertyType("MFR", "Multi-Family Residence");
        verifyPropertyType("TWN", "Townhouse");
        verifyPropertyType("OTH", "OTH"); // unknown code returns as-is
        verifyPropertyType(null, "Unknown");
    }

    @Test
    void expandPaymentType_allCodes() {
        // Test each payment type code
        verifyPaymentType("REG", "Regular");
        verifyPaymentType("EXT", "Extra");
        verifyPaymentType("PRT", "Partial");
        verifyPaymentType("PRE", "Prepayment");
        verifyPaymentType("UNK", "UNK"); // unknown code returns as-is
        verifyPaymentType(null, "Unknown");
    }

    @Test
    void expandPaymentStatus_allCodes() {
        // Test each payment status code
        verifyPaymentStatus("PST", "Posted");
        verifyPaymentStatus("REV", "Reversed");
        verifyPaymentStatus("NSF", "Non-Sufficient Funds");
        verifyPaymentStatus("PND", "Pending");
        verifyPaymentStatus("ZZZ", "ZZZ"); // unknown code returns as-is
        verifyPaymentStatus(null, "Unknown");
    }

    // =========================================================================
    // Helper methods for status expansion tests
    // =========================================================================

    /** Verifies loan status code expansion via getLoanById */
    private void verifyLoanStatus(String code, String expected) {
        sampleAccount.setStatusCode(code);
        when(loanAccountRepository.findById("LN-2019-00142")).thenReturn(Optional.of(sampleAccount));
        when(loanProductRepository.findById("FXD30")).thenReturn(Optional.of(sampleProduct));

        LoanSummaryDto dto = loanService.getLoanById("LN-2019-00142");
        assertEquals(expected, dto.getStatus());
    }

    /** Verifies property type code expansion via getLoanById */
    private void verifyPropertyType(String code, String expected) {
        sampleAccount.setPropertyType(code);
        when(loanAccountRepository.findById("LN-2019-00142")).thenReturn(Optional.of(sampleAccount));
        when(loanProductRepository.findById("FXD30")).thenReturn(Optional.of(sampleProduct));

        LoanSummaryDto dto = loanService.getLoanById("LN-2019-00142");
        assertEquals(expected, dto.getPropertyType());
    }

    /** Verifies payment type code expansion via getPaymentsByLoan */
    private void verifyPaymentType(String code, String expected) {
        samplePayment.setTypeCode(code);
        when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-2019-00142"))
                .thenReturn(List.of(samplePayment));

        List<PaymentDto> result = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(expected, result.get(0).getType());
    }

    /** Verifies payment status code expansion via getPaymentsByLoan */
    private void verifyPaymentStatus(String code, String expected) {
        samplePayment.setStatusCode(code);
        when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-2019-00142"))
                .thenReturn(List.of(samplePayment));

        List<PaymentDto> result = loanService.getPaymentsByLoan("LN-2019-00142");
        assertEquals(expected, result.get(0).getStatus());
    }

    // =========================================================================
    // Payment translation edge cases
    // =========================================================================

    @Test
    void toPaymentDto_nullAmountFields_returnZero() {
        samplePayment.setTotalAmount(null);
        samplePayment.setPrincipalAmount("");
        samplePayment.setInterestAmount("  ");
        samplePayment.setEscrowAmount(null);
        samplePayment.setLateFee(null);

        when(paymentRepository.findByLoanAccountNumberOrderByPaymentDateDesc("LN-2019-00142"))
                .thenReturn(List.of(samplePayment));

        List<PaymentDto> result = loanService.getPaymentsByLoan("LN-2019-00142");
        PaymentDto dto = result.get(0);

        assertEquals(BigDecimal.ZERO, dto.getTotalAmount());
        assertEquals(BigDecimal.ZERO, dto.getPrincipalAmount());
        assertEquals(BigDecimal.ZERO, dto.getInterestAmount());
        assertEquals(BigDecimal.ZERO, dto.getEscrowAmount());
        assertEquals(BigDecimal.ZERO, dto.getLateFee());
    }
}
