package com.workshop.loanservice.validation;

import com.workshop.loanservice.entity.LegacyBorrower;
import com.workshop.loanservice.entity.LegacyLoanAccount;
import com.workshop.loanservice.entity.LegacyPayment;
import com.workshop.loanservice.repository.LegacyBorrowerRepository;
import com.workshop.loanservice.repository.LegacyLoanAccountRepository;
import com.workshop.loanservice.repository.LegacyLoanProductRepository;
import com.workshop.loanservice.repository.LegacyPaymentRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;

/**
 * Integration test that runs the DataQualityValidator against the actual
 * legacy seed data loaded from data-legacy.sql to verify it detects
 * the known anomalies documented in docs/DATA_ANOMALY_REPORT.md.
 */
@SpringBootTest
class LegacyDataQualityIntegrationTest {

    @Autowired
    private DataQualityValidator validator;

    @Autowired
    private LegacyBorrowerRepository borrowerRepository;

    @Autowired
    private LegacyLoanAccountRepository loanAccountRepository;

    @Autowired
    private LegacyLoanProductRepository loanProductRepository;

    @Autowired
    private LegacyPaymentRepository paymentRepository;

    @Test
    void detectsPaymentComponentSumMismatchInSeedData() {
        Set<String> validLoanIds = loanAccountRepository.findAll().stream()
                .map(LegacyLoanAccount::getLoanAccountNumber)
                .collect(Collectors.toSet());

        List<DataQualityIssue> allIssues = new ArrayList<>();
        for (LegacyPayment payment : paymentRepository.findAll()) {
            allIssues.addAll(validator.validatePayment(payment, validLoanIds));
        }

        List<DataQualityIssue> sumMismatches = allIssues.stream()
                .filter(i -> i.getColumn().equals("PMT_AMT")
                        && i.getMessage().contains("do not sum"))
                .toList();

        assertEquals(3, sumMismatches.size(),
                "Expected 3 payment sum mismatches (PMT-2025120001, PMT-2025110001, PMT-2025110003), got: "
                        + sumMismatches);
    }

    @Test
    void detectsDelinquencyStatusInconsistencyInSeedData() {
        Set<String> validBorrowerIds = borrowerRepository.findAll().stream()
                .map(LegacyBorrower::getBorrowerId)
                .collect(Collectors.toSet());
        Set<String> validProductCodes = loanProductRepository.findAll().stream()
                .map(p -> p.getProductCode())
                .collect(Collectors.toSet());

        List<DataQualityIssue> allIssues = new ArrayList<>();
        for (LegacyLoanAccount account : loanAccountRepository.findAll()) {
            allIssues.addAll(validator.validateLoanAccount(account, validBorrowerIds, validProductCodes));
        }

        List<DataQualityIssue> delinquencyIssues = allIssues.stream()
                .filter(i -> i.getColumn().equals("LN_DLQ_DAYS")
                        && i.getMessage().contains("delinquency"))
                .toList();

        assertEquals(1, delinquencyIssues.size(),
                "Expected 1 delinquency/status inconsistency (LN-2018-00089), got: "
                        + delinquencyIssues);
        assertTrue(delinquencyIssues.get(0).getContext().contains("LN-2018-00089"));
    }

    @Test
    void allBorrowersPassBasicValidation() {
        List<DataQualityIssue> allIssues = new ArrayList<>();
        for (LegacyBorrower borrower : borrowerRepository.findAll()) {
            allIssues.addAll(validator.validateBorrower(borrower));
        }

        List<DataQualityIssue> criticalIssues = allIssues.stream()
                .filter(i -> i.getSeverity() == DataQualityIssue.Severity.CRITICAL)
                .toList();

        assertTrue(criticalIssues.isEmpty(),
                "Seed data borrowers should not have CRITICAL issues: " + criticalIssues);
    }

    @Test
    void noOrphanedRecordsInSeedData() {
        Set<String> validBorrowerIds = borrowerRepository.findAll().stream()
                .map(LegacyBorrower::getBorrowerId)
                .collect(Collectors.toSet());
        Set<String> validProductCodes = loanProductRepository.findAll().stream()
                .map(p -> p.getProductCode())
                .collect(Collectors.toSet());
        Set<String> validLoanIds = loanAccountRepository.findAll().stream()
                .map(LegacyLoanAccount::getLoanAccountNumber)
                .collect(Collectors.toSet());

        List<DataQualityIssue> orphanIssues = new ArrayList<>();

        for (LegacyLoanAccount account : loanAccountRepository.findAll()) {
            orphanIssues.addAll(
                    validator.validateLoanAccount(account, validBorrowerIds, validProductCodes)
                            .stream()
                            .filter(i -> i.getMessage().contains("Orphaned"))
                            .toList());
        }
        for (LegacyPayment payment : paymentRepository.findAll()) {
            orphanIssues.addAll(
                    validator.validatePayment(payment, validLoanIds)
                            .stream()
                            .filter(i -> i.getMessage().contains("Orphaned"))
                            .toList());
        }

        assertTrue(orphanIssues.isEmpty(),
                "Seed data should not have orphaned records: " + orphanIssues);
    }
}
