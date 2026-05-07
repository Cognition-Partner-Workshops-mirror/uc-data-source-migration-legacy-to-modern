package com.workshop.loanservice.validation;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Captures validation outcomes for a legacy record.
 * Each warning represents a detected anomaly that was handled with a fallback.
 */
public class ValidationResult {

    public enum Severity {
        CRITICAL, HIGH, MEDIUM, LOW
    }

    public record Warning(Severity severity, String field, String message, String rawValue) {}

    private final List<Warning> warnings = new ArrayList<>();
    private boolean valid = true;

    public void addWarning(Severity severity, String field, String message, String rawValue) {
        warnings.add(new Warning(severity, field, message, rawValue));
        if (severity == Severity.CRITICAL || severity == Severity.HIGH) {
            valid = false;
        }
    }

    public boolean isValid() {
        return valid;
    }

    public boolean hasWarnings() {
        return !warnings.isEmpty();
    }

    public List<Warning> getWarnings() {
        return Collections.unmodifiableList(warnings);
    }

    public List<Warning> getWarningsBySeverity(Severity severity) {
        return warnings.stream()
                .filter(w -> w.severity() == severity)
                .toList();
    }
}
