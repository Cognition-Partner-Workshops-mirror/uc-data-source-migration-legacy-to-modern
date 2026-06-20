package com.workshop.loanservice.goldenfile;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.TestInstance;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Golden-file validation tests that capture API responses and assert
 * they match expected baseline files stored in src/test/resources/golden/.
 *
 * These tests verify that the data source migration (from legacy CDW to modern
 * normalized schema) produces the same API output as the original legacy service.
 * The golden files represent the "before" state; the tests validate the "after".
 */
@SpringBootTest
@AutoConfigureMockMvc
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class GoldenFileValidationTest {

    @Autowired
    private MockMvc mockMvc;

    private ObjectMapper objectMapper;

    @BeforeAll
    void setup() {
        objectMapper = new ObjectMapper();
        objectMapper.enable(SerializationFeature.INDENT_OUTPUT);
    }

    // =========================================================================
    // GET /api/loans — all loans listing
    // =========================================================================

    @Test
    void getAllLoansMatchesGoldenFile() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/loans"))
                .andExpect(status().isOk())
                .andReturn();

        String actualJson = result.getResponse().getContentAsString();
        String expectedJson = loadGoldenFile("get_all_loans.json");

        assertJsonEquals(expectedJson, actualJson, "/api/loans");
    }

    // =========================================================================
    // GET /api/loans/{id} — single loan details
    // =========================================================================

    @Test
    void getLoanByIdMatchesGoldenFile() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/loans/LN-2019-00142"))
                .andExpect(status().isOk())
                .andReturn();

        String actualJson = result.getResponse().getContentAsString();
        String expectedJson = loadGoldenFile("get_loan_LN-2019-00142.json");

        assertJsonEquals(expectedJson, actualJson, "/api/loans/LN-2019-00142");
    }

    // =========================================================================
    // GET /api/borrowers — all borrowers listing
    // =========================================================================

    @Test
    void getAllBorrowersMatchesGoldenFile() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/borrowers"))
                .andExpect(status().isOk())
                .andReturn();

        String actualJson = result.getResponse().getContentAsString();
        String expectedJson = loadGoldenFile("get_all_borrowers.json");

        assertJsonEquals(expectedJson, actualJson, "/api/borrowers");
    }

    // =========================================================================
    // GET /api/borrowers/{id} — single borrower with loans
    // =========================================================================

    @Test
    void getBorrowerByIdMatchesGoldenFile() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/borrowers/B-10001"))
                .andExpect(status().isOk())
                .andReturn();

        String actualJson = result.getResponse().getContentAsString();
        String expectedJson = loadGoldenFile("get_borrower_B-10001.json");

        assertJsonEquals(expectedJson, actualJson, "/api/borrowers/B-10001");
    }

    // =========================================================================
    // GET /api/payments/loan/{loanId} — payments for a loan
    // =========================================================================

    @Test
    void getPaymentsByLoanMatchesGoldenFile() throws Exception {
        MvcResult result = mockMvc.perform(get("/api/loans/LN-2019-00142/payments"))
                .andExpect(status().isOk())
                .andReturn();

        String actualJson = result.getResponse().getContentAsString();
        String expectedJson = loadGoldenFile("get_payments_LN-2019-00142.json");

        assertJsonEquals(expectedJson, actualJson, "/api/loans/LN-2019-00142/payments");
    }

    // =========================================================================
    // HELPERS
    // =========================================================================

    /**
     * Loads a golden file from the test resources directory.
     */
    private String loadGoldenFile(String filename) throws IOException {
        String path = "golden/" + filename;
        try (InputStream is = getClass().getClassLoader().getResourceAsStream(path)) {
            assertNotNull(is, "Golden file not found: " + path);
            return new String(is.readAllBytes(), StandardCharsets.UTF_8);
        }
    }

    /**
     * Compares two JSON strings structurally (ignoring formatting differences).
     * Provides a clear error message showing both expected and actual JSON.
     */
    private void assertJsonEquals(String expected, String actual, String endpoint) throws Exception {
        JsonNode expectedTree = objectMapper.readTree(expected);
        JsonNode actualTree = objectMapper.readTree(actual);

        assertEquals(expectedTree, actualTree,
                "Golden file mismatch for " + endpoint + "\n"
                + "Expected:\n" + objectMapper.writeValueAsString(expectedTree) + "\n"
                + "Actual:\n" + objectMapper.writeValueAsString(actualTree));
    }
}
