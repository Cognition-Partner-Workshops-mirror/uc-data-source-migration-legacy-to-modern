package com.workshop.loanservice.migration;

import com.workshop.loanservice.repository.modern.BorrowerRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

/**
 * Runs the data migration from legacy CDW tables to modern schema
 * on application startup. This ensures modern tables are populated
 * before any API requests are served.
 * Skips migration if modern tables already contain data (idempotent).
 */
@Component
public class MigrationRunner implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(MigrationRunner.class);

    private final DataMigrationService migrationService;
    private final BorrowerRepository borrowerRepository;

    public MigrationRunner(DataMigrationService migrationService,
                           BorrowerRepository borrowerRepository) {
        this.migrationService = migrationService;
        this.borrowerRepository = borrowerRepository;
    }

    @Override
    public void run(ApplicationArguments args) {
        // Skip migration if modern tables already have data (idempotent)
        if (borrowerRepository.count() > 0) {
            log.info("Modern schema already populated, skipping migration");
            return;
        }

        log.info("Executing legacy-to-modern data migration on startup...");
        DataMigrationService.MigrationResult result = migrationService.migrateAll();
        log.info("Startup migration completed: {}", result);
    }
}
