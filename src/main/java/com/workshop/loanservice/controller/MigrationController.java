package com.workshop.loanservice.controller;

import com.workshop.loanservice.migration.MigrationPreFlightService;
import com.workshop.loanservice.migration.PreFlightReport;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * REST controller exposing migration validation endpoints.
 * Allows operators to run a dry-run pre-flight check of the entire legacy dataset
 * and inspect all validation issues before committing any migration.
 */
@RestController
@RequestMapping("/api/migration")
public class MigrationController {

    private final MigrationPreFlightService preFlightService;

    public MigrationController(MigrationPreFlightService preFlightService) {
        this.preFlightService = preFlightService;
    }

    /**
     * Run a full pre-flight validation of the legacy dataset.
     * Returns a JSON report with error/warning counts, orphaned FK references,
     * denormalization mismatches, payment sum discrepancies, and per-row details.
     * This is a read-only operation — no data is modified.
     */
    @GetMapping("/preflight")
    public ResponseEntity<PreFlightReport> runPreFlight() {
        PreFlightReport report = preFlightService.runFullValidation();
        return ResponseEntity.ok(report);
    }
}
