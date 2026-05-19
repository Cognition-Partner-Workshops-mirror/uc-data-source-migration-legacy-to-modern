package com.workshop.loanservice.controller;

import com.workshop.loanservice.dto.BorrowerDto;
import com.workshop.loanservice.service.DualReadService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * Borrower API controller — now uses DualReadService to support
 * legacy, modern, or dual-read mode based on the datasource.mode property.
 */
@RestController
@RequestMapping("/api/borrowers")
public class BorrowerController {

    private final DualReadService dualReadService;

    public BorrowerController(DualReadService dualReadService) {
        this.dualReadService = dualReadService;
    }

    @GetMapping
    public List<BorrowerDto> getAllBorrowers() {
        return dualReadService.getAllBorrowers();
    }

    @GetMapping("/{id}")
    public BorrowerDto getBorrower(@PathVariable String id) {
        return dualReadService.getBorrowerById(id);
    }
}
