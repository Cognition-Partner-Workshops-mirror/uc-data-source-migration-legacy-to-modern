package com.workshop.loanservice.controller;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.service.LoanService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * REST controller exposing borrower endpoints under {@code /api/borrowers}.
 */
@RestController
@RequestMapping("/api/borrowers")
public class BorrowerController {

    private final LoanService loanService;

    public BorrowerController(LoanService loanService) {
        this.loanService = loanService;
    }

    /**
     * Retrieves all borrowers.
     *
     * @return list of all borrowers as DTOs
     */
    @GetMapping
    public List<BorrowerDto> getAllBorrowers() {
        return loanService.getAllBorrowers();
    }

    /**
     * Retrieves a single borrower by ID, including their associated loans.
     *
     * @param id the borrower identifier
     * @return the borrower with attached loan summaries
     */
    @GetMapping("/{id}")
    public BorrowerDto getBorrower(@PathVariable String id) {
        return loanService.getBorrowerById(id);
    }
}
