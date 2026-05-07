package com.workshop.loanservice.validation;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public class ValidationResult {

    private final List<DataQualityWarning> warnings = new ArrayList<>();
    private boolean valid = true;

    public void addWarning(DataQualityWarning warning) {
        warnings.add(warning);
        if (warning.getSeverity() == DataQualityWarning.Severity.CRITICAL
                || warning.getSeverity() == DataQualityWarning.Severity.HIGH) {
            valid = false;
        }
    }

    public boolean isValid() { return valid; }

    public List<DataQualityWarning> getWarnings() {
        return Collections.unmodifiableList(warnings);
    }

    public boolean hasWarnings() { return !warnings.isEmpty(); }
}
