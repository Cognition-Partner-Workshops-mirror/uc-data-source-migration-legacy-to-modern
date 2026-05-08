package com.workshop.loanservice.dto;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Tests for PaymentDto getters and setters.
 */
class PaymentDtoTest {

    @Test
    void gettersAndSetters() {
        PaymentDto dto = new PaymentDto();

        dto.setPaymentId("PMT-2025120001");
        assertEquals("PMT-2025120001", dto.getPaymentId());

        dto.setLoanAccountNumber("LN-2019-00142");
        assertEquals("LN-2019-00142", dto.getLoanAccountNumber());

        dto.setPaymentDate("12/15/2025");
        assertEquals("12/15/2025", dto.getPaymentDate());

        dto.setTotalAmount(new BigDecimal("1487.02"));
        assertEquals(new BigDecimal("1487.02"), dto.getTotalAmount());

        dto.setPrincipalAmount(new BigDecimal("456.78"));
        assertEquals(new BigDecimal("456.78"), dto.getPrincipalAmount());

        dto.setInterestAmount(new BigDecimal("1074.69"));
        assertEquals(new BigDecimal("1074.69"), dto.getInterestAmount());

        dto.setEscrowAmount(new BigDecimal("355.55"));
        assertEquals(new BigDecimal("355.55"), dto.getEscrowAmount());

        dto.setLateFee(BigDecimal.ZERO);
        assertEquals(BigDecimal.ZERO, dto.getLateFee());

        dto.setType("Regular");
        assertEquals("Regular", dto.getType());

        dto.setStatus("Posted");
        assertEquals("Posted", dto.getStatus());
    }

    @Test
    void defaultValues_areNull() {
        PaymentDto dto = new PaymentDto();
        assertNull(dto.getPaymentId());
        assertNull(dto.getTotalAmount());
        assertNull(dto.getType());
        assertNull(dto.getStatus());
    }
}
