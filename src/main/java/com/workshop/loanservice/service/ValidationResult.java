package com.workshop.loanservice.service;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class ValidationResult {

    private final String recordId;
    private final List<String> warnings;
    private final List<String> errors;

    public ValidationResult(String recordId) {
        this.recordId = recordId;
        this.warnings = new ArrayList<>();
        this.errors = new ArrayList<>();
    }

    public void addWarning(String message) {
        warnings.add(message);
    }

    public void addError(String message) {
        errors.add(message);
    }

    public boolean hasErrors() {
        return !errors.isEmpty();
    }

    public boolean hasWarnings() {
        return !warnings.isEmpty();
    }

    public String getRecordId() {
        return recordId;
    }

    public List<String> getWarnings() {
        return Collections.unmodifiableList(warnings);
    }

    public List<String> getErrors() {
        return Collections.unmodifiableList(errors);
    }
}
