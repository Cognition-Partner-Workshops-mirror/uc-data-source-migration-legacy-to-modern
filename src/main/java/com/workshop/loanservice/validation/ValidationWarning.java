package com.workshop.loanservice.validation;

public record ValidationWarning(
        String anomalyId,
        String severity,
        String table,
        String column,
        String recordId,
        String detail
) {
}
