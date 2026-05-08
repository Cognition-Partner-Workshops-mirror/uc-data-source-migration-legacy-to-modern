package com.workshop.loanservice.entity;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Tests for LegacyLoanAccount entity getters and setters.
 */
class LegacyLoanAccountTest {

    @Test
    void gettersAndSetters() {
        LegacyLoanAccount a = new LegacyLoanAccount();

        a.setLoanAccountNumber("LN-2019-00142");
        assertEquals("LN-2019-00142", a.getLoanAccountNumber());

        a.setBorrowerId("B-10001");
        assertEquals("B-10001", a.getBorrowerId());

        a.setBorrowerFirstName("James");
        assertEquals("James", a.getBorrowerFirstName());

        a.setBorrowerLastName("Mitchell");
        assertEquals("Mitchell", a.getBorrowerLastName());

        a.setBorrowerSsnLast4("0142");
        assertEquals("0142", a.getBorrowerSsnLast4());

        a.setProductCode("FXD30");
        assertEquals("FXD30", a.getProductCode());

        a.setOriginalAmount("285,000");
        assertEquals("285,000", a.getOriginalAmount());

        a.setCurrentBalance("271,432.56");
        assertEquals("271,432.56", a.getCurrentBalance());

        a.setInterestRate("4.750");
        assertEquals("4.750", a.getInterestRate());

        a.setTermMonths("360");
        assertEquals("360", a.getTermMonths());

        a.setMonthlyPayment("1,487.02");
        assertEquals("1,487.02", a.getMonthlyPayment());

        a.setOriginationDate("02/15/2019");
        assertEquals("02/15/2019", a.getOriginationDate());

        a.setMaturityDate("02/15/2049");
        assertEquals("02/15/2049", a.getMaturityDate());

        a.setFirstPaymentDate("03/15/2019");
        assertEquals("03/15/2019", a.getFirstPaymentDate());

        a.setNextPaymentDate("01/15/2026");
        assertEquals("01/15/2026", a.getNextPaymentDate());

        a.setStatusCode("ACT");
        assertEquals("ACT", a.getStatusCode());

        a.setDelinquencyDays("0");
        assertEquals("0", a.getDelinquencyDays());

        a.setEscrowBalance("3,245.80");
        assertEquals("3,245.80", a.getEscrowBalance());

        a.setLtvPercent("82.5");
        assertEquals("82.5", a.getLtvPercent());

        a.setPropertyAddress("742 Elm Street");
        assertEquals("742 Elm Street", a.getPropertyAddress());

        a.setPropertyCity("Springfield");
        assertEquals("Springfield", a.getPropertyCity());

        a.setPropertyState("IL");
        assertEquals("IL", a.getPropertyState());

        a.setPropertyZip("62701");
        assertEquals("62701", a.getPropertyZip());

        a.setPropertyType("SFR");
        assertEquals("SFR", a.getPropertyType());

        a.setAppraisedValue("345,000");
        assertEquals("345,000", a.getAppraisedValue());

        a.setCreatedDate("02/01/2019");
        assertEquals("02/01/2019", a.getCreatedDate());

        a.setUpdatedDate("12/01/2025");
        assertEquals("12/01/2025", a.getUpdatedDate());
    }

    @Test
    void defaultValues_areNull() {
        LegacyLoanAccount a = new LegacyLoanAccount();
        assertNull(a.getLoanAccountNumber());
        assertNull(a.getBorrowerId());
        assertNull(a.getPropertyType());
    }
}
