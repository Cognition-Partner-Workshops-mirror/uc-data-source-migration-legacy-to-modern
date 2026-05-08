package com.workshop.loanservice.controller;

import com.workshop.loanservice.dto.LoanSummaryDto;
import com.workshop.loanservice.dto.PaymentDto;
import com.workshop.loanservice.service.LoanService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.Collections;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * MockMvc tests for LoanController endpoints.
 */
@WebMvcTest(LoanController.class)
class LoanControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private LoanService loanService;

    @Test
    void getAllLoans_returnsJsonList() throws Exception {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber("LN-2019-00142");
        dto.setBorrowerName("James Mitchell");
        dto.setProductDescription("30-Year Fixed Rate Mortgage");
        dto.setOriginalAmount(new BigDecimal("285000"));
        dto.setCurrentBalance(new BigDecimal("271432.56"));
        dto.setInterestRate(new BigDecimal("4.750"));
        dto.setMonthlyPayment(new BigDecimal("1487.02"));
        dto.setStatus("Active");
        dto.setOriginationDate("02/15/2019");
        dto.setPropertyAddress("742 Elm Street, Springfield, IL 62701");
        dto.setPropertyType("Single Family Residence");

        when(loanService.getAllLoans()).thenReturn(List.of(dto));

        mockMvc.perform(get("/api/loans"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].loanAccountNumber").value("LN-2019-00142"))
                .andExpect(jsonPath("$[0].borrowerName").value("James Mitchell"))
                .andExpect(jsonPath("$[0].productDescription").value("30-Year Fixed Rate Mortgage"))
                .andExpect(jsonPath("$[0].originalAmount").value(285000))
                .andExpect(jsonPath("$[0].status").value("Active"))
                .andExpect(jsonPath("$[0].propertyType").value("Single Family Residence"));
    }

    @Test
    void getAllLoans_emptyList() throws Exception {
        when(loanService.getAllLoans()).thenReturn(Collections.emptyList());

        mockMvc.perform(get("/api/loans"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$").isEmpty());
    }

    @Test
    void getLoanById_found() throws Exception {
        LoanSummaryDto dto = new LoanSummaryDto();
        dto.setLoanAccountNumber("LN-2019-00142");
        dto.setBorrowerName("James Mitchell");
        dto.setProductDescription("30-Year Fixed Rate Mortgage");
        dto.setOriginalAmount(new BigDecimal("285000"));
        dto.setCurrentBalance(new BigDecimal("271432.56"));
        dto.setInterestRate(new BigDecimal("4.750"));
        dto.setMonthlyPayment(new BigDecimal("1487.02"));
        dto.setStatus("Active");
        dto.setOriginationDate("02/15/2019");
        dto.setPropertyAddress("742 Elm Street, Springfield, IL 62701");
        dto.setPropertyType("Single Family Residence");

        when(loanService.getLoanById("LN-2019-00142")).thenReturn(dto);

        mockMvc.perform(get("/api/loans/LN-2019-00142"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.loanAccountNumber").value("LN-2019-00142"))
                .andExpect(jsonPath("$.status").value("Active"));
    }

    @Test
    void getLoanById_notFound_throwsException() {
        when(loanService.getLoanById("INVALID"))
                .thenThrow(new RuntimeException("Loan not found: INVALID"));

        // The RuntimeException propagates as a ServletException in MockMvc
        assertThrows(Exception.class, () ->
                mockMvc.perform(get("/api/loans/INVALID")));
    }

    @Test
    void getPayments_returnsJsonList() throws Exception {
        PaymentDto dto = new PaymentDto();
        dto.setPaymentId("PMT-2025120001");
        dto.setLoanAccountNumber("LN-2019-00142");
        dto.setPaymentDate("12/15/2025");
        dto.setTotalAmount(new BigDecimal("1487.02"));
        dto.setPrincipalAmount(new BigDecimal("456.78"));
        dto.setInterestAmount(new BigDecimal("1074.69"));
        dto.setEscrowAmount(new BigDecimal("355.55"));
        dto.setLateFee(BigDecimal.ZERO);
        dto.setType("Regular");
        dto.setStatus("Posted");

        when(loanService.getPaymentsByLoan("LN-2019-00142")).thenReturn(List.of(dto));

        mockMvc.perform(get("/api/loans/LN-2019-00142/payments"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].paymentId").value("PMT-2025120001"))
                .andExpect(jsonPath("$[0].loanAccountNumber").value("LN-2019-00142"))
                .andExpect(jsonPath("$[0].type").value("Regular"))
                .andExpect(jsonPath("$[0].status").value("Posted"));
    }

    @Test
    void getPayments_emptyList() throws Exception {
        when(loanService.getPaymentsByLoan("LN-NONE")).thenReturn(Collections.emptyList());

        mockMvc.perform(get("/api/loans/LN-NONE/payments"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$").isEmpty());
    }
}
