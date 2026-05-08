package com.workshop.loanservice.entity;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Tests for LegacyPayment entity getters and setters.
 */
class LegacyPaymentTest {

    @Test
    void gettersAndSetters() {
        LegacyPayment p = new LegacyPayment();

        p.setPaymentSequenceNumber("PMT-2025120001");
        assertEquals("PMT-2025120001", p.getPaymentSequenceNumber());

        p.setLoanAccountNumber("LN-2019-00142");
        assertEquals("LN-2019-00142", p.getLoanAccountNumber());

        p.setPaymentDate("12/15/2025");
        assertEquals("12/15/2025", p.getPaymentDate());

        p.setTotalAmount("1,487.02");
        assertEquals("1,487.02", p.getTotalAmount());

        p.setPrincipalAmount("456.78");
        assertEquals("456.78", p.getPrincipalAmount());

        p.setInterestAmount("1,074.69");
        assertEquals("1,074.69", p.getInterestAmount());

        p.setEscrowAmount("355.55");
        assertEquals("355.55", p.getEscrowAmount());

        p.setLateFee("0.00");
        assertEquals("0.00", p.getLateFee());

        p.setTypeCode("REG");
        assertEquals("REG", p.getTypeCode());

        p.setStatusCode("PST");
        assertEquals("PST", p.getStatusCode());

        p.setReceivedDate("12/14/2025");
        assertEquals("12/14/2025", p.getReceivedDate());

        p.setProcessedDate("12/15/2025");
        assertEquals("12/15/2025", p.getProcessedDate());

        p.setCreatedDate("12/15/2025");
        assertEquals("12/15/2025", p.getCreatedDate());

        p.setUpdatedDate("12/15/2025");
        assertEquals("12/15/2025", p.getUpdatedDate());
    }

    @Test
    void defaultValues_areNull() {
        LegacyPayment p = new LegacyPayment();
        assertNull(p.getPaymentSequenceNumber());
        assertNull(p.getLoanAccountNumber());
        assertNull(p.getTypeCode());
    }
}
