package com.workshop.loanservice.controller;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.dto.LoanSummaryDto;
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
 * MockMvc tests for BorrowerController endpoints.
 */
@WebMvcTest(BorrowerController.class)
class BorrowerControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @MockBean
    private LoanService loanService;

    @Test
    void getAllBorrowers_returnsJsonList() throws Exception {
        BorrowerDto dto = new BorrowerDto();
        dto.setId("B-10001");
        dto.setFullName("James R. Mitchell");
        dto.setEmail("j.mitchell@email.com");
        dto.setPhone("217-555-0142");
        dto.setCity("Springfield");
        dto.setState("IL");
        dto.setCreditScore(745);
        dto.setEmploymentStatus("EMPLOYED");

        when(loanService.getAllBorrowers()).thenReturn(List.of(dto));

        mockMvc.perform(get("/api/borrowers"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").value("B-10001"))
                .andExpect(jsonPath("$[0].fullName").value("James R. Mitchell"))
                .andExpect(jsonPath("$[0].email").value("j.mitchell@email.com"))
                .andExpect(jsonPath("$[0].phone").value("217-555-0142"))
                .andExpect(jsonPath("$[0].city").value("Springfield"))
                .andExpect(jsonPath("$[0].state").value("IL"))
                .andExpect(jsonPath("$[0].creditScore").value(745))
                .andExpect(jsonPath("$[0].employmentStatus").value("EMPLOYED"));
    }

    @Test
    void getAllBorrowers_emptyList() throws Exception {
        when(loanService.getAllBorrowers()).thenReturn(Collections.emptyList());

        mockMvc.perform(get("/api/borrowers"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$").isArray())
                .andExpect(jsonPath("$").isEmpty());
    }

    @Test
    void getBorrowerById_found() throws Exception {
        BorrowerDto dto = new BorrowerDto();
        dto.setId("B-10001");
        dto.setFullName("James R. Mitchell");
        dto.setEmail("j.mitchell@email.com");
        dto.setPhone("217-555-0142");
        dto.setCity("Springfield");
        dto.setState("IL");
        dto.setCreditScore(745);
        dto.setEmploymentStatus("EMPLOYED");

        // Attach a loan to the borrower
        LoanSummaryDto loan = new LoanSummaryDto();
        loan.setLoanAccountNumber("LN-2019-00142");
        loan.setBorrowerName("James Mitchell");
        loan.setProductDescription("30-Year Fixed Rate Mortgage");
        loan.setOriginalAmount(new BigDecimal("285000"));
        loan.setCurrentBalance(new BigDecimal("271432.56"));
        loan.setInterestRate(new BigDecimal("4.750"));
        loan.setMonthlyPayment(new BigDecimal("1487.02"));
        loan.setStatus("Active");
        loan.setOriginationDate("02/15/2019");
        loan.setPropertyAddress("742 Elm Street, Springfield, IL 62701");
        loan.setPropertyType("Single Family Residence");
        dto.setLoans(List.of(loan));

        when(loanService.getBorrowerById("B-10001")).thenReturn(dto);

        mockMvc.perform(get("/api/borrowers/B-10001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value("B-10001"))
                .andExpect(jsonPath("$.fullName").value("James R. Mitchell"))
                .andExpect(jsonPath("$.loans[0].loanAccountNumber").value("LN-2019-00142"))
                .andExpect(jsonPath("$.loans[0].status").value("Active"));
    }

    @Test
    void getBorrowerById_notFound_throwsException() {
        when(loanService.getBorrowerById("INVALID"))
                .thenThrow(new RuntimeException("Borrower not found: INVALID"));

        // The RuntimeException propagates as a ServletException in MockMvc
        assertThrows(Exception.class, () ->
                mockMvc.perform(get("/api/borrowers/INVALID")));
    }
}
