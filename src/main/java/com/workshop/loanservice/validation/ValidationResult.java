package com.workshop.loanservice.validation;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Accumulates validation warnings and errors for a single legacy record.
 */
public class ValidationResult {

    public enum Severity { ERROR, WARNING }

    public record Issue(Severity severity, String field, String message) {}

    private final List<Issue> issues = new ArrayList<>();

    public void addError(String field, String message) {
        issues.add(new Issue(Severity.ERROR, field, message));
    }

    public void addWarning(String field, String message) {
        issues.add(new Issue(Severity.WARNING, field, message));
    }

    public boolean hasErrors() {
        return issues.stream().anyMatch(i -> i.severity() == Severity.ERROR);
    }

    public boolean hasWarnings() {
        return issues.stream().anyMatch(i -> i.severity() == Severity.WARNING);
    }

    public boolean isClean() {
        return issues.isEmpty();
    }

    public List<Issue> getIssues() {
        return Collections.unmodifiableList(issues);
    }

    public List<Issue> getErrors() {
        return issues.stream().filter(i -> i.severity() == Severity.ERROR).toList();
    }

    public List<Issue> getWarnings() {
        return issues.stream().filter(i -> i.severity() == Severity.WARNING).toList();
    }
}
