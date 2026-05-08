package com.workshop.loanservice.entity;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * Tests for LegacyBorrower entity getters and setters.
 */
class LegacyBorrowerTest {

    @Test
    void gettersAndSetters() {
        LegacyBorrower b = new LegacyBorrower();

        b.setBorrowerId("B-10001");
        assertEquals("B-10001", b.getBorrowerId());

        b.setFirstName("James");
        assertEquals("James", b.getFirstName());

        b.setLastName("Mitchell");
        assertEquals("Mitchell", b.getLastName());

        b.setMiddleInitial("R");
        assertEquals("R", b.getMiddleInitial());

        b.setSsnEncrypted("ENC_XXX_001");
        assertEquals("ENC_XXX_001", b.getSsnEncrypted());

        b.setDateOfBirth("03/15/1978");
        assertEquals("03/15/1978", b.getDateOfBirth());

        b.setAddressLine1("742 Elm Street");
        assertEquals("742 Elm Street", b.getAddressLine1());

        b.setAddressLine2("Apt 3B");
        assertEquals("Apt 3B", b.getAddressLine2());

        b.setCity("Springfield");
        assertEquals("Springfield", b.getCity());

        b.setStateCode("IL");
        assertEquals("IL", b.getStateCode());

        b.setZipCode("62701");
        assertEquals("62701", b.getZipCode());

        b.setPhoneNumber("217-555-0142");
        assertEquals("217-555-0142", b.getPhoneNumber());

        b.setEmail("j.mitchell@email.com");
        assertEquals("j.mitchell@email.com", b.getEmail());

        b.setCreditScore("745");
        assertEquals("745", b.getCreditScore());

        b.setEmploymentStatus("EMPLOYED");
        assertEquals("EMPLOYED", b.getEmploymentStatus());

        b.setAnnualIncome("92,500");
        assertEquals("92,500", b.getAnnualIncome());

        b.setCreatedDate("01/15/2019");
        assertEquals("01/15/2019", b.getCreatedDate());

        b.setUpdatedDate("11/03/2025");
        assertEquals("11/03/2025", b.getUpdatedDate());

        b.setStatusCode("ACT");
        assertEquals("ACT", b.getStatusCode());

        b.setRecordType("PRI");
        assertEquals("PRI", b.getRecordType());
    }

    @Test
    void defaultValues_areNull() {
        LegacyBorrower b = new LegacyBorrower();
        assertNull(b.getBorrowerId());
        assertNull(b.getFirstName());
        assertNull(b.getMiddleInitial());
    }
}
