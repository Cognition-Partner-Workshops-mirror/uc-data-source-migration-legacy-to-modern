package com.workshop.loanservice.validation;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Holds the results of data quality validation for a single entity.
 * Collects warnings (non-fatal issues with fallback applied) and
 * errors (issues that may affect data integrity).
 */
public class DataQualityResult {

    public enum Severity {
        WARNING, ERROR
    }

    public record Issue(Severity severity, String field, String message, String recordId) {}

    private final List<Issue> issues = new ArrayList<>();
    private final String entityType;
    private final String recordId;

    public DataQualityResult(String entityType, String recordId) {
        this.entityType = entityType;
        this.recordId = recordId;
    }

    /** Add a warning — a non-fatal issue where a fallback default was applied. */
    public void addWarning(String field, String message) {
        issues.add(new Issue(Severity.WARNING, field, message, recordId));
    }

    /** Add an error — a data integrity issue that may produce incorrect results. */
    public void addError(String field, String message) {
        issues.add(new Issue(Severity.ERROR, field, message, recordId));
    }

    public boolean hasErrors() {
        return issues.stream().anyMatch(i -> i.severity() == Severity.ERROR);
    }

    public boolean hasIssues() {
        return !issues.isEmpty();
    }

    public List<Issue> getIssues() {
        return Collections.unmodifiableList(issues);
    }

    public String getEntityType() {
        return entityType;
    }

    public String getRecordId() {
        return recordId;
    }
}
