package com.workshop.loanservice.dto;

import com.workshop.loanservice.validation.DataQualityWarning;
import java.math.BigDecimal;
import java.util.List;

/**
 * Summary DTO for loan listing.
 */
public class LoanSummaryDto {

    private String loanAccountNumber;
    private String borrowerName;
    private String productDescription;
    private BigDecimal originalAmount;
    private BigDecimal currentBalance;
    private BigDecimal interestRate;
    private BigDecimal monthlyPayment;
    private String status;
    private String originationDate;
    private String propertyAddress;
    private String propertyType;
    private List<DataQualityWarning> dataQualityWarnings;

    public String getLoanAccountNumber() { return loanAccountNumber; }
    public void setLoanAccountNumber(String loanAccountNumber) { this.loanAccountNumber = loanAccountNumber; }
    public String getBorrowerName() { return borrowerName; }
    public void setBorrowerName(String borrowerName) { this.borrowerName = borrowerName; }
    public String getProductDescription() { return productDescription; }
    public void setProductDescription(String productDescription) { this.productDescription = productDescription; }
    public BigDecimal getOriginalAmount() { return originalAmount; }
    public void setOriginalAmount(BigDecimal originalAmount) { this.originalAmount = originalAmount; }
    public BigDecimal getCurrentBalance() { return currentBalance; }
    public void setCurrentBalance(BigDecimal currentBalance) { this.currentBalance = currentBalance; }
    public BigDecimal getInterestRate() { return interestRate; }
    public void setInterestRate(BigDecimal interestRate) { this.interestRate = interestRate; }
    public BigDecimal getMonthlyPayment() { return monthlyPayment; }
    public void setMonthlyPayment(BigDecimal monthlyPayment) { this.monthlyPayment = monthlyPayment; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getOriginationDate() { return originationDate; }
    public void setOriginationDate(String originationDate) { this.originationDate = originationDate; }
    public String getPropertyAddress() { return propertyAddress; }
    public void setPropertyAddress(String propertyAddress) { this.propertyAddress = propertyAddress; }
    public String getPropertyType() { return propertyType; }
    public void setPropertyType(String propertyType) { this.propertyType = propertyType; }
    public List<DataQualityWarning> getDataQualityWarnings() { return dataQualityWarnings; }
    public void setDataQualityWarnings(List<DataQualityWarning> dataQualityWarnings) { this.dataQualityWarnings = dataQualityWarnings; }
}
