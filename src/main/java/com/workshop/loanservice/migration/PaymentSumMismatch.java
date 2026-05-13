package com.workshop.loanservice.migration;

import java.math.BigDecimal;

/**
 * Records a payment where the component amounts (principal + interest + escrow + lateFee)
 * do not sum to the total payment amount. Captured during pre-flight validation
 * for audit review before migration.
 */
public class PaymentSumMismatch {

    private final String paymentId;
    private final String loanAccountNumber;
    private final BigDecimal totalAmount;
    private final BigDecimal componentSum;
    private final BigDecimal delta;

    public PaymentSumMismatch(String paymentId, String loanAccountNumber,
                              BigDecimal totalAmount, BigDecimal componentSum, BigDecimal delta) {
        this.paymentId = paymentId;
        this.loanAccountNumber = loanAccountNumber;
        this.totalAmount = totalAmount;
        this.componentSum = componentSum;
        this.delta = delta;
    }

    public String getPaymentId() {
        return paymentId;
    }

    public String getLoanAccountNumber() {
        return loanAccountNumber;
    }

    public BigDecimal getTotalAmount() {
        return totalAmount;
    }

    public BigDecimal getComponentSum() {
        return componentSum;
    }

    public BigDecimal getDelta() {
        return delta;
    }

    @Override
    public String toString() {
        return "PaymentSumMismatch{id=" + paymentId + ", loan=" + loanAccountNumber
                + ", total=" + totalAmount + ", components=" + componentSum
                + ", delta=" + delta + "}";
    }
}
