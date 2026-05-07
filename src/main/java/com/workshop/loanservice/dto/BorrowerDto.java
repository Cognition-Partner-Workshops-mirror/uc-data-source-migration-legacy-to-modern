package com.workshop.loanservice.dto;

import java.math.BigDecimal;
import java.util.List;

/**
 * Clean DTO for API responses.
 * The service layer translates legacy string fields into proper types.
 */
public class BorrowerDto {

    private String id;
    private String fullName;
    private String email;
    private String phone;
    private String city;
    private String state;
    private Integer creditScore;
    private String employmentStatus;
    private BigDecimal annualIncome;
    private List<LoanSummaryDto> loans;

    public String getId() { return id; }
    public void setId(String id) { this.id = id; }
    public String getFullName() { return fullName; }
    public void setFullName(String fullName) { this.fullName = fullName; }
    public String getEmail() { return email; }
    public void setEmail(String email) { this.email = email; }
    public String getPhone() { return phone; }
    public void setPhone(String phone) { this.phone = phone; }
    public String getCity() { return city; }
    public void setCity(String city) { this.city = city; }
    public String getState() { return state; }
    public void setState(String state) { this.state = state; }
    public Integer getCreditScore() { return creditScore; }
    public void setCreditScore(Integer creditScore) { this.creditScore = creditScore; }
    public String getEmploymentStatus() { return employmentStatus; }
    public void setEmploymentStatus(String employmentStatus) { this.employmentStatus = employmentStatus; }
    public BigDecimal getAnnualIncome() { return annualIncome; }
    public void setAnnualIncome(BigDecimal annualIncome) { this.annualIncome = annualIncome; }
    public List<LoanSummaryDto> getLoans() { return loans; }
    public void setLoans(List<LoanSummaryDto> loans) { this.loans = loans; }
}
