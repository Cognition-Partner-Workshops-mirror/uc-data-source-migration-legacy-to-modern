package com.workshop.loanservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Spring Boot entry point for the loan-service workshop application.
 * This application facilitates the migration from a legacy CDW
 * (Core Data Warehouse) denormalized schema to a modern normalized
 * relational schema.
 */
@SpringBootApplication
public class LoanServiceApplication {

    public static void main(String[] args) {
        SpringApplication.run(LoanServiceApplication.class, args);
    }
}
