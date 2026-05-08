package com.workshop.loanservice.entity;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Tests for LegacyLoanProduct entity getters and setters.
 */
class LegacyLoanProductTest {

    @Test
    void gettersAndSetters() {
        LegacyLoanProduct p = new LegacyLoanProduct();

        p.setProductCode("FXD30");
        assertEquals("FXD30", p.getProductCode());

        p.setDescription("30-Year Fixed Rate Mortgage");
        assertEquals("30-Year Fixed Rate Mortgage", p.getDescription());

        p.setTypeCode("FXD");
        assertEquals("FXD", p.getTypeCode());

        p.setTermMonths("360");
        assertEquals("360", p.getTermMonths());

        p.setRateType("FIXED");
        assertEquals("FIXED", p.getRateType());

        p.setMinAmount("50,000");
        assertEquals("50,000", p.getMinAmount());

        p.setMaxAmount("1,500,000");
        assertEquals("1,500,000", p.getMaxAmount());

        p.setStatusCode("ACT");
        assertEquals("ACT", p.getStatusCode());

        p.setEffectiveDate("01/01/2020");
        assertEquals("01/01/2020", p.getEffectiveDate());

        p.setExpirationDate("12/31/2099");
        assertEquals("12/31/2099", p.getExpirationDate());
    }

    @Test
    void defaultValues_areNull() {
        LegacyLoanProduct p = new LegacyLoanProduct();
        assertNull(p.getProductCode());
        assertNull(p.getDescription());
    }
}
