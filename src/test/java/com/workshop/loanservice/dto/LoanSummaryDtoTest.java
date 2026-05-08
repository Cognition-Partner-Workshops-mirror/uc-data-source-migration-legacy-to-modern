package com.workshop.loanservice.dto;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Tests for LoanSummaryDto getters and setters.
 */
class LoanSummaryDtoTest {

    @Test
    void gettersAndSetters() {
        LoanSummaryDto dto = new LoanSummaryDto();

        dto.setLoanAccountNumber("LN-2019-00142");
        assertEquals("LN-2019-00142", dto.getLoanAccountNumber());

        dto.setBorrowerName("James Mitchell");
        assertEquals("James Mitchell", dto.getBorrowerName());

        dto.setProductDescription("30-Year Fixed Rate Mortgage");
        assertEquals("30-Year Fixed Rate Mortgage", dto.getProductDescription());

        dto.setOriginalAmount(new BigDecimal("285000"));
        assertEquals(new BigDecimal("285000"), dto.getOriginalAmount());

        dto.setCurrentBalance(new BigDecimal("271432.56"));
        assertEquals(new BigDecimal("271432.56"), dto.getCurrentBalance());

        dto.setInterestRate(new BigDecimal("4.750"));
        assertEquals(new BigDecimal("4.750"), dto.getInterestRate());

        dto.setMonthlyPayment(new BigDecimal("1487.02"));
        assertEquals(new BigDecimal("1487.02"), dto.getMonthlyPayment());

        dto.setStatus("Active");
        assertEquals("Active", dto.getStatus());

        dto.setOriginationDate("02/15/2019");
        assertEquals("02/15/2019", dto.getOriginationDate());

        dto.setPropertyAddress("742 Elm Street, Springfield, IL 62701");
        assertEquals("742 Elm Street, Springfield, IL 62701", dto.getPropertyAddress());

        dto.setPropertyType("Single Family Residence");
        assertEquals("Single Family Residence", dto.getPropertyType());
    }

    @Test
    void defaultValues_areNull() {
        LoanSummaryDto dto = new LoanSummaryDto();
        assertNull(dto.getLoanAccountNumber());
        assertNull(dto.getOriginalAmount());
        assertNull(dto.getStatus());
    }
}
