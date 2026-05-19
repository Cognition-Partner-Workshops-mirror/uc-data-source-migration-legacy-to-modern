package com.workshop.loanservice.controller;

import com.workshop.loanservice.service.DataMigrationService;
import com.workshop.loanservice.service.DualReadService;
import org.springframework.web.bind.annotation.*;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * REST controller for migration operations:
 *   - Trigger the legacy-to-modern migration
 *   - View migration report / status
 *   - Switch between data source modes (legacy/modern/dual)
 *   - View dual-read comparison results
 */
@RestController
@RequestMapping("/api/migration")
public class MigrationController {

    private final DataMigrationService migrationService;
    private final DualReadService dualReadService;

    // Cached last migration report
    private DataMigrationService.MigrationReport lastReport;

    public MigrationController(DataMigrationService migrationService,
                               DualReadService dualReadService) {
        this.migrationService = migrationService;
        this.dualReadService = dualReadService;
    }

    /**
     * POST /api/migration/run — Execute the full legacy-to-modern data migration.
     * Returns a summary report with counts, warnings, and errors.
     */
    @PostMapping("/run")
    public DataMigrationService.MigrationReport runMigration() {
        lastReport = migrationService.runMigration();
        return lastReport;
    }

    /**
     * GET /api/migration/report — View the last migration report.
     */
    @GetMapping("/report")
    public Object getReport() {
        if (lastReport == null) {
            Map<String, String> response = new LinkedHashMap<>();
            response.put("status", "No migration has been run yet");
            response.put("action", "POST /api/migration/run to start migration");
            return response;
        }
        return lastReport;
    }

    /**
     * GET /api/migration/mode — View the current data source mode.
     */
    @GetMapping("/mode")
    public Map<String, String> getMode() {
        Map<String, String> response = new LinkedHashMap<>();
        response.put("mode", dualReadService.getMode());
        response.put("description", getModeDescription(dualReadService.getMode()));
        return response;
    }

    /**
     * PUT /api/migration/mode?mode=legacy|modern|dual — Switch data source mode.
     */
    @PutMapping("/mode")
    public Map<String, String> setMode(@RequestParam String mode) {
        if (!List.of("legacy", "modern", "dual").contains(mode)) {
            throw new RuntimeException("Invalid mode: " + mode + ". Use: legacy, modern, or dual");
        }
        dualReadService.setMode(mode);
        Map<String, String> response = new LinkedHashMap<>();
        response.put("mode", mode);
        response.put("description", getModeDescription(mode));
        response.put("status", "Mode switched successfully");
        return response;
    }

    /**
     * GET /api/migration/comparison — View recent dual-read comparison results.
     * Only populated when mode=dual and API calls have been made.
     */
    @GetMapping("/comparison")
    public List<DualReadService.ComparisonResult> getComparisons() {
        return dualReadService.getRecentComparisons();
    }

    private String getModeDescription(String mode) {
        return switch (mode) {
            case "legacy" -> "Reading from legacy CDW tables only";
            case "modern" -> "Reading from modern normalized tables only";
            case "dual" -> "Reading from both; comparing results and returning legacy data";
            default -> "Unknown mode";
        };
    }
}
