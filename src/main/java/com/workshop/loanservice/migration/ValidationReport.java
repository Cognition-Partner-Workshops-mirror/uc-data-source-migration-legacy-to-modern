package com.workshop.loanservice.migration;

import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;

/**
 * Aggregates all {@link ValidationResult} objects for a single source row.
 * Tracks the source table name and primary key for traceability during
 * migration dry-run validation.
 */
public class ValidationReport {

    private final String sourceTable;
    private final String sourcePrimaryKey;
    private final List<ValidationResult<?>> results = new ArrayList<>();

    public ValidationReport(String sourceTable, String sourcePrimaryKey) {
        this.sourceTable = sourceTable;
        this.sourcePrimaryKey = sourcePrimaryKey;
    }

    /** Add a single validation result to this row's report */
    public void add(ValidationResult<?> result) {
        if (result != null && result.getSeverity() != null) {
            results.add(result);
        }
    }

    /** Add multiple validation results (e.g. from date ordering checks) */
    public void addAll(List<ValidationResult<?>> resultList) {
        if (resultList != null) {
            resultList.forEach(this::add);
        }
    }

    /** True if at least one ERROR-level result exists */
    public boolean hasErrors() {
        return results.stream()
                .anyMatch(r -> r.getSeverity() == ValidationResult.Severity.ERROR);
    }

    /** True if at least one WARNING-level result exists */
    public boolean hasWarnings() {
        return results.stream()
                .anyMatch(r -> r.getSeverity() == ValidationResult.Severity.WARNING);
    }

    /** Return only ERROR-level results */
    public List<ValidationResult<?>> getErrors() {
        return results.stream()
                .filter(r -> r.getSeverity() == ValidationResult.Severity.ERROR)
                .collect(Collectors.toList());
    }

    /** Return only WARNING-level results */
    public List<ValidationResult<?>> getWarnings() {
        return results.stream()
                .filter(r -> r.getSeverity() == ValidationResult.Severity.WARNING)
                .collect(Collectors.toList());
    }

    /** Human-readable summary of this row's validation findings */
    public String getSummary() {
        long errors = results.stream()
                .filter(r -> r.getSeverity() == ValidationResult.Severity.ERROR).count();
        long warnings = results.stream()
                .filter(r -> r.getSeverity() == ValidationResult.Severity.WARNING).count();
        long infos = results.stream()
                .filter(r -> r.getSeverity() == ValidationResult.Severity.INFO).count();
        return String.format("[%s:%s] %d error(s), %d warning(s), %d info(s)",
                sourceTable, sourcePrimaryKey, errors, warnings, infos);
    }

    // ---- Accessors ----

    public String getSourceTable() {
        return sourceTable;
    }

    public String getSourcePrimaryKey() {
        return sourcePrimaryKey;
    }

    public List<ValidationResult<?>> getResults() {
        return results;
    }
}
