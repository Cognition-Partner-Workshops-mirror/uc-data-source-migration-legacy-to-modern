package com.workshop.loanservice;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.*;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * API contract tests verifying that the refactored service layer produces
 * the same JSON response structure and values as the legacy implementation.
 * These tests ensure backward compatibility with existing API consumers.
 */
@SpringBootTest
@AutoConfigureMockMvc
class LoanApiContractTest {

    @Autowired
    private MockMvc mockMvc;

    // =========================================================================
    // GET /api/loans — all loans
    // =========================================================================

    @Test
    void getAllLoans_returnsCorrectStructure() throws Exception {
        mockMvc.perform(get("/api/loans"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(5)))
                .andExpect(jsonPath("$[0].loanAccountNumber").exists())
                .andExpect(jsonPath("$[0].borrowerName").exists())
                .andExpect(jsonPath("$[0].productDescription").exists())
                .andExpect(jsonPath("$[0].originalAmount").exists())
                .andExpect(jsonPath("$[0].currentBalance").exists())
                .andExpect(jsonPath("$[0].interestRate").exists())
                .andExpect(jsonPath("$[0].monthlyPayment").exists())
                .andExpect(jsonPath("$[0].status").exists())
                .andExpect(jsonPath("$[0].originationDate").exists())
                .andExpect(jsonPath("$[0].propertyAddress").exists())
                .andExpect(jsonPath("$[0].propertyType").exists());
    }

    @Test
    void getAllLoans_containsExpectedLoan() throws Exception {
        mockMvc.perform(get("/api/loans"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[?(@.loanAccountNumber == 'LN-2019-00142')].borrowerName",
                        contains("James Mitchell")))
                .andExpect(jsonPath("$[?(@.loanAccountNumber == 'LN-2019-00142')].productDescription",
                        contains("30-Year Fixed Rate Mortgage")))
                .andExpect(jsonPath("$[?(@.loanAccountNumber == 'LN-2019-00142')].originalAmount",
                        contains(285000.00)))
                .andExpect(jsonPath("$[?(@.loanAccountNumber == 'LN-2019-00142')].status",
                        contains("Active")));
    }

    // =========================================================================
    // GET /api/loans/{id} — single loan
    // =========================================================================

    @Test
    void getLoan_returnsCorrectValues() throws Exception {
        mockMvc.perform(get("/api/loans/LN-2019-00142"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.loanAccountNumber", is("LN-2019-00142")))
                .andExpect(jsonPath("$.borrowerName", is("James Mitchell")))
                .andExpect(jsonPath("$.productDescription", is("30-Year Fixed Rate Mortgage")))
                .andExpect(jsonPath("$.originalAmount", is(285000.00)))
                .andExpect(jsonPath("$.currentBalance", is(271432.56)))
                .andExpect(jsonPath("$.interestRate", is(4.750)))
                .andExpect(jsonPath("$.monthlyPayment", is(1487.02)))
                .andExpect(jsonPath("$.status", is("Active")))
                .andExpect(jsonPath("$.originationDate", is("02/15/2019")))
                .andExpect(jsonPath("$.propertyAddress", is("742 Elm Street, Springfield, IL 62701")))
                .andExpect(jsonPath("$.propertyType", is("Single Family Residence")));
    }

    @Test
    void getLoan_secondLoan() throws Exception {
        mockMvc.perform(get("/api/loans/LN-2020-00398"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.loanAccountNumber", is("LN-2020-00398")))
                .andExpect(jsonPath("$.borrowerName", is("Sarah Chen")))
                .andExpect(jsonPath("$.productDescription", is("15-Year Fixed Rate Mortgage")))
                .andExpect(jsonPath("$.originalAmount", is(420000.00)))
                .andExpect(jsonPath("$.status", is("Active")))
                .andExpect(jsonPath("$.propertyType", is("Condominium")));
    }

    @Test
    void getLoan_notFound_throwsException() {
        // Preserving existing error behavior (RuntimeException for missing loan)
        assertThrows(Exception.class, () ->
                mockMvc.perform(get("/api/loans/NONEXISTENT")));
    }

    // =========================================================================
    // GET /api/loans/{id}/payments — payments for a loan
    // =========================================================================

    @Test
    void getPayments_returnsCorrectStructure() throws Exception {
        mockMvc.perform(get("/api/loans/LN-2019-00142/payments"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[0].paymentId").exists())
                .andExpect(jsonPath("$[0].loanAccountNumber", is("LN-2019-00142")))
                .andExpect(jsonPath("$[0].paymentDate").exists())
                .andExpect(jsonPath("$[0].totalAmount").exists())
                .andExpect(jsonPath("$[0].principalAmount").exists())
                .andExpect(jsonPath("$[0].interestAmount").exists())
                .andExpect(jsonPath("$[0].escrowAmount").exists())
                .andExpect(jsonPath("$[0].lateFee").exists())
                .andExpect(jsonPath("$[0].type").exists())
                .andExpect(jsonPath("$[0].status").exists());
    }

    @Test
    void getPayments_returnsCorrectValues() throws Exception {
        mockMvc.perform(get("/api/loans/LN-2019-00142/payments"))
                .andExpect(status().isOk())
                // Payments ordered by date DESC — most recent first
                .andExpect(jsonPath("$[0].paymentDate", is("12/15/2025")))
                .andExpect(jsonPath("$[0].totalAmount", is(1487.02)))
                .andExpect(jsonPath("$[0].principalAmount", is(456.78)))
                .andExpect(jsonPath("$[0].interestAmount", is(1074.69)))
                .andExpect(jsonPath("$[0].escrowAmount", is(355.55)))
                .andExpect(jsonPath("$[0].lateFee", is(0.00)))
                .andExpect(jsonPath("$[0].type", is("Regular")))
                .andExpect(jsonPath("$[0].status", is("Posted")));
    }

    @Test
    void getPayments_loanWithLateFee() throws Exception {
        // LN-2018-00089 has a payment with $47.50 late fee
        mockMvc.perform(get("/api/loans/LN-2018-00089/payments"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(2)))
                .andExpect(jsonPath("$[?(@.lateFee == 47.5)]", hasSize(1)));
    }

    // =========================================================================
    // GET /api/borrowers — all borrowers
    // =========================================================================

    @Test
    void getAllBorrowers_returnsCorrectStructure() throws Exception {
        mockMvc.perform(get("/api/borrowers"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(5)))
                .andExpect(jsonPath("$[0].id").exists())
                .andExpect(jsonPath("$[0].fullName").exists())
                .andExpect(jsonPath("$[0].email").exists())
                .andExpect(jsonPath("$[0].phone").exists())
                .andExpect(jsonPath("$[0].city").exists())
                .andExpect(jsonPath("$[0].state").exists())
                .andExpect(jsonPath("$[0].creditScore").exists())
                .andExpect(jsonPath("$[0].employmentStatus").exists());
    }

    @Test
    void getAllBorrowers_containsExpectedBorrower() throws Exception {
        mockMvc.perform(get("/api/borrowers"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[?(@.id == 'B-10001')].fullName",
                        contains("James R. Mitchell")))
                .andExpect(jsonPath("$[?(@.id == 'B-10001')].email",
                        contains("j.mitchell@email.com")))
                .andExpect(jsonPath("$[?(@.id == 'B-10001')].creditScore",
                        contains(745)));
    }

    // =========================================================================
    // GET /api/borrowers/{id} — single borrower with loans
    // =========================================================================

    @Test
    void getBorrower_returnsCorrectValues() throws Exception {
        mockMvc.perform(get("/api/borrowers/B-10001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id", is("B-10001")))
                .andExpect(jsonPath("$.fullName", is("James R. Mitchell")))
                .andExpect(jsonPath("$.email", is("j.mitchell@email.com")))
                .andExpect(jsonPath("$.phone", is("217-555-0142")))
                .andExpect(jsonPath("$.city", is("Springfield")))
                .andExpect(jsonPath("$.state", is("IL")))
                .andExpect(jsonPath("$.creditScore", is(745)))
                .andExpect(jsonPath("$.employmentStatus", is("EMPLOYED")));
    }

    @Test
    void getBorrower_includesLoans() throws Exception {
        mockMvc.perform(get("/api/borrowers/B-10001"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.loans", hasSize(1)))
                .andExpect(jsonPath("$.loans[0].loanAccountNumber", is("LN-2019-00142")));
    }

    @Test
    void getBorrower_withoutMiddleInitial() throws Exception {
        // B-10005 (Robert Williams) has no middle initial
        mockMvc.perform(get("/api/borrowers/B-10005"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.fullName", is("Robert Williams")));
    }

    @Test
    void getBorrower_notFound_throwsException() {
        // Preserving existing error behavior (RuntimeException for missing borrower)
        assertThrows(Exception.class, () ->
                mockMvc.perform(get("/api/borrowers/NONEXISTENT")));
    }
}
