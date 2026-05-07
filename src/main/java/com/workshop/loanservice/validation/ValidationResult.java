package com.workshop.loanservice.validation;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class ValidationResult {

    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    public record ValidationWarning(Severity severity, String table, String recordId,
                                    String field, String message, String rawValue) {
    }

    private final List<ValidationWarning> warnings = new ArrayList<>();

    public void addWarning(Severity severity, String table, String recordId,
                           String field, String message, String rawValue) {
        warnings.add(new ValidationWarning(severity, table, recordId, field, message, rawValue));
    }

    public List<ValidationWarning> getWarnings() {
        return Collections.unmodifiableList(warnings);
    }

    public List<ValidationWarning> getWarnings(Severity severity) {
        return warnings.stream()
                .filter(w -> w.severity() == severity)
                .toList();
    }

    public boolean hasWarnings() {
        return !warnings.isEmpty();
    }

    public boolean hasWarnings(Severity severity) {
        return warnings.stream().anyMatch(w -> w.severity() == severity);
    }

    public int warningCount() {
        return warnings.size();
    }

    public void merge(ValidationResult other) {
        warnings.addAll(other.warnings);
    }
}
