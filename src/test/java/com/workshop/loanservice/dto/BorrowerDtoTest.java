package com.workshop.loanservice.dto;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Tests for BorrowerDto getters, setters, and loans list.
 */
class BorrowerDtoTest {

    @Test
    void gettersAndSetters() {
        BorrowerDto dto = new BorrowerDto();

        dto.setId("B-10001");
        assertEquals("B-10001", dto.getId());

        dto.setFullName("James R. Mitchell");
        assertEquals("James R. Mitchell", dto.getFullName());

        dto.setEmail("j.mitchell@email.com");
        assertEquals("j.mitchell@email.com", dto.getEmail());

        dto.setPhone("217-555-0142");
        assertEquals("217-555-0142", dto.getPhone());

        dto.setCity("Springfield");
        assertEquals("Springfield", dto.getCity());

        dto.setState("IL");
        assertEquals("IL", dto.getState());

        dto.setCreditScore(745);
        assertEquals(745, dto.getCreditScore());

        dto.setEmploymentStatus("EMPLOYED");
        assertEquals("EMPLOYED", dto.getEmploymentStatus());
    }

    @Test
    void loans_getterAndSetter() {
        BorrowerDto dto = new BorrowerDto();
        assertNull(dto.getLoans());

        LoanSummaryDto loan = new LoanSummaryDto();
        loan.setLoanAccountNumber("LN-001");
        dto.setLoans(List.of(loan));

        assertNotNull(dto.getLoans());
        assertEquals(1, dto.getLoans().size());
        assertEquals("LN-001", dto.getLoans().get(0).getLoanAccountNumber());
    }
}
