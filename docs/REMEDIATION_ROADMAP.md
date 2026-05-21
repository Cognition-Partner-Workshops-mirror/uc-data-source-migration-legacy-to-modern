# Remediation Roadmap — Loan Service

Prioritized plan to address gaps identified in `GAP_ANALYSIS.md`. Each item includes an actionable Devin prompt that can be executed directly.

---

## Phase 1 — Quick Wins (High Severity / Small Effort)

These items deliver immediate value with minimal code changes.

---

### 1.1 Fix `pom.xml` typo (GAP-ORG-06)

**Priority:** Unblocks clean builds without external workarounds.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, fix the `pom.xml` typo: replace `<relativeTo/>` with `<relativePath/>` in the `<parent>` section. Verify the build succeeds with `mvn clean package`.

---

### 1.2 Add global exception handler (GAP-ERR-01, GAP-ERR-02)

**Priority:** Prevents stack trace leaks and returns proper HTTP status codes.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, create a `@RestControllerAdvice` class at `src/main/java/com/workshop/loanservice/exception/GlobalExceptionHandler.java`. Create a custom `ResourceNotFoundException` extending `RuntimeException`. Map it to HTTP 404 with a JSON body using RFC 7807 `ProblemDetail`. Map generic `RuntimeException` to HTTP 500. Map `MethodArgumentTypeMismatchException` to HTTP 400. Update `LoanService.getLoanById()` and `getBorrowerById()` to throw `ResourceNotFoundException` instead of `RuntimeException`. Add comments explaining each handler. Add unit tests for the exception handler.

---

### 1.3 Add structured logging (GAP-OBS-01)

**Priority:** Essential for debugging and production monitoring.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add SLF4J logging throughout the application. Add a `private static final Logger log = LoggerFactory.getLogger(...)` to `LoanService`, `LoanController`, and `BorrowerController`. Log at INFO level for incoming requests (method + path + parameters), WARN level for not-found cases, and ERROR level for unexpected exceptions. In the parsing methods (`parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`), log WARN when encountering null/blank/malformed values. Add comments explaining the logging strategy.

---

### 1.4 Add Spring Boot Actuator health endpoint (GAP-OBS-02)

**Priority:** Baseline health monitoring.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add `spring-boot-starter-actuator` to `pom.xml`. Configure `application.properties` to expose `health`, `info`, and `metrics` endpoints under `/actuator`. Add a comment in `application.properties` explaining the actuator configuration. Verify the `/actuator/health` endpoint returns `{"status":"UP"}` after running the app.

---

### 1.5 Secure H2 console and disable SQL logging (GAP-SEC-03, GAP-SEC-05)

**Priority:** Prevents data exposure in non-development environments.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, create a Spring profile-based configuration. Create `src/main/resources/application-dev.properties` with `spring.h2.console.enabled=true` and `spring.jpa.show-sql=true`. In the main `application.properties`, set `spring.h2.console.enabled=false` and `spring.jpa.show-sql=false`. Add a comment explaining that the H2 console and SQL logging are only enabled in the `dev` profile. Update `README.md` to document running with the dev profile: `mvn spring-boot:run -Dspring-boot.run.profiles=dev`.

---

### 1.6 Add input validation (GAP-ERR-03)

**Priority:** Prevents malformed inputs from reaching the persistence layer.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add `spring-boot-starter-validation` to `pom.xml`. Add `@Pattern` or `@Size` constraints on path variables in `LoanController` and `BorrowerController` (e.g., validate that loan IDs match the pattern `LN-\d{4}-\d{5}` and borrower IDs match `B-\d{5}`). Handle `ConstraintViolationException` in the global exception handler with HTTP 400. Add comments documenting the validation patterns.

---

### 1.7 Add OpenAPI documentation (GAP-API-03)

**Priority:** Self-documenting API for developers.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add `springdoc-openapi-starter-webmvc-ui` (open-source, version 2.3.0) to `pom.xml`. Add `@Operation` and `@ApiResponse` annotations to all controller methods. Add `@Schema` annotations to DTO classes with field descriptions. Configure the OpenAPI info (title: "Loan Service API", version: "1.0.0", description) in `application.properties`. Verify Swagger UI loads at `/swagger-ui.html`.

---

### 1.8 Fix README endpoint documentation mismatch (GAP-API-07)

**Priority:** Prevents developer confusion.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, update `README.md` to fix the payment endpoint URL. Change `GET /api/payments/loan/{loanId}` to `GET /api/loans/{loanId}/payments` to match the actual `LoanController` implementation. Add a comment in the README noting this correction.

---

## Phase 2 — Important (High Severity / Medium-Large Effort)

These items require more significant refactoring but address critical gaps.

---

### 2.1 Add comprehensive test suite (GAP-TST-01)

**Priority:** Critical for safe migration. Without tests, migration risks silent data corruption.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, create a comprehensive test suite:
>
> 1. Create `src/test/java/com/workshop/loanservice/service/LoanServiceTest.java` with unit tests for all parsing methods (`parseLegacyAmount`, `parseLegacyDecimal`, `parseLegacyInteger`), all expand methods (`expandStatusCode`, `expandPropertyType`, `expandPaymentType`, `expandPaymentStatus`), and all DTO mapping methods. Use `@ExtendWith(MockitoExtension.class)` to mock repositories.
>
> 2. Create `src/test/java/com/workshop/loanservice/controller/LoanControllerTest.java` with MockMvc integration tests for `GET /api/loans`, `GET /api/loans/{id}`, `GET /api/loans/{loanId}/payments`. Assert response status, content type, and JSON structure.
>
> 3. Create `src/test/java/com/workshop/loanservice/controller/BorrowerControllerTest.java` with MockMvc integration tests for `GET /api/borrowers`, `GET /api/borrowers/{id}`. Assert borrower fields and nested loan data.
>
> 4. Create golden file tests that capture current API responses as JSON files in `src/test/resources/golden/` and compare against them to detect regressions during migration.
>
> Add comments explaining the test strategy in each test class. Ensure all tests pass with `mvn test`.

---

### 2.2 Add pagination and filtering (GAP-API-01)

**Priority:** Required for production scalability.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add pagination support to list endpoints. Update `LegacyLoanAccountRepository` and `LegacyBorrowerRepository` to extend `PagingAndSortingRepository`. Modify `GET /api/loans` and `GET /api/borrowers` to accept `page`, `size`, and `sort` query parameters using Spring's `Pageable`. Return a wrapper DTO containing `content`, `totalElements`, `totalPages`, `page`, and `size`. Add a `@Query` method for filtering loans by status. Add comments explaining pagination defaults. Add integration tests for pagination.

---

### 2.3 Add API versioning (GAP-API-02)

**Priority:** Enables backward-compatible API evolution during migration.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add API versioning by changing `@RequestMapping("/api/loans")` to `@RequestMapping("/api/v1/loans")` and `@RequestMapping("/api/borrowers")` to `@RequestMapping("/api/v1/borrowers")` in both controllers. Update all tests and the README to reflect the new paths. Add a comment explaining the versioning strategy.

---

### 2.4 Add Spring Security with basic authentication (GAP-SEC-01)

**Priority:** Protects sensitive financial and PII data.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add `spring-boot-starter-security` to `pom.xml`. Create a `SecurityConfig` class at `src/main/java/com/workshop/loanservice/config/SecurityConfig.java` with a `SecurityFilterChain` bean. Configure HTTP Basic auth. Permit unauthenticated access to `/actuator/health`, `/swagger-ui/**`, and `/v3/api-docs/**`. Require authentication for all `/api/**` endpoints. Configure an in-memory user with username `admin` and a BCrypt-encoded password. Exclude the H2 console path from CSRF in the dev profile only. Add comments explaining each security rule. Add integration tests that verify unauthenticated requests return 401.

---

### 2.5 Add timeout and connection pool configuration (GAP-RES-01)

**Priority:** Prevents resource exhaustion under load.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add HikariCP connection pool configuration to `application.properties`: set `spring.datasource.hikari.maximum-pool-size=10`, `spring.datasource.hikari.minimum-idle=2`, `spring.datasource.hikari.connection-timeout=20000`, `spring.datasource.hikari.idle-timeout=300000`. Add JPA query timeout: `spring.jpa.properties.jakarta.persistence.query.timeout=5000`. Add comments explaining each setting.

---

### 2.6 Normalize date formats in API responses (GAP-API-04)

**Priority:** Improves API interoperability.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, update the `LoanSummaryDto.originationDate` and `PaymentDto.paymentDate` fields from `String` to `LocalDate`. In `LoanService`, parse the legacy `MM/DD/YYYY` strings into `LocalDate` using `DateTimeFormatter.ofPattern("MM/dd/yyyy")`. Configure Jackson in `application.properties` to serialize dates as ISO 8601: `spring.jackson.serialization.write-dates-as-timestamps=false`. Add comments explaining the date format standardization. Update golden file tests to expect ISO 8601 dates.

---

### 2.7 Add test data fixtures (GAP-TST-02)

**Priority:** Isolates test state from application seed data.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, create test data builders at `src/test/java/com/workshop/loanservice/testutil/TestDataBuilder.java`. Add static factory methods for creating `LegacyBorrower`, `LegacyLoanAccount`, `LegacyLoanProduct`, and `LegacyPayment` test instances with sensible defaults. Use these builders in all unit tests instead of relying on the SQL seed data. Add comments explaining the builder pattern usage.

---

## Phase 3 — Polish (Lower Severity / Various Effort)

These items improve quality and developer experience but are not blocking.

---

### 3.1 Extract DTO mappers (GAP-ORG-05)

**Priority:** Improves code organization and testability.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, extract the entity-to-DTO mapping methods from `LoanService` into dedicated mapper classes. Create `src/main/java/com/workshop/loanservice/mapper/BorrowerMapper.java`, `LoanMapper.java`, and `PaymentMapper.java` as `@Component` classes. Move the `toBorrowerDto`, `toLoanSummary`, and `toPaymentDto` methods along with the parsing/expanding helpers into the appropriate mapper. Inject mappers into `LoanService`. Add unit tests for each mapper. Add comments explaining the separation of concerns.

---

### 3.2 Separate into domain-specific services (GAP-ORG-04)

**Priority:** Better separation of concerns for maintainability.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, split `LoanService` into three services: `BorrowerService` (handling borrower retrieval and mapping), `LoanAccountService` (handling loan retrieval, product lookup, and mapping), and `PaymentService` (handling payment retrieval and mapping). Update controllers to use the appropriate service. Ensure all existing tests still pass. Add comments explaining the service decomposition.

---

### 3.3 Add Micrometer metrics (GAP-OBS-03)

**Priority:** Production observability for performance monitoring.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add `micrometer-registry-prometheus` (open-source) to `pom.xml`. Expose the `/actuator/prometheus` endpoint in `application.properties`. Add custom metrics using `MeterRegistry` in `LoanService`: a counter for total API requests by endpoint, a timer for service method execution times, and a gauge for active database connections. Add comments explaining each metric. Verify metrics appear at `/actuator/prometheus`.

---

### 3.4 Add CORS configuration (GAP-SEC-04)

**Priority:** Enables frontend integration.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, create a `WebConfig` class at `src/main/java/com/workshop/loanservice/config/WebConfig.java` implementing `WebMvcConfigurer`. Override `addCorsMappings` to allow `GET` requests from configurable origins (default: `http://localhost:3000`). Externalize the allowed origins to `application.properties` as `app.cors.allowed-origins`. Add comments explaining the CORS policy.

---

### 3.5 Improve null handling in translation methods (GAP-ERR-04, GAP-RES-02)

**Priority:** Defensive coding for data quality issues.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, improve the defensive coding in `LoanService` translation methods. In `parseLegacyAmount`, log a WARN when encountering unexpected formats (e.g., non-numeric characters after comma removal). In `toLoanSummary`, handle the case where `products.get(acct.getProductCode())` returns null more explicitly by logging a warning. In `toBorrowerDto`, handle null `middleInitial` with a single ternary instead of the current pattern. Add comments documenting edge cases. Add unit tests for edge cases (null inputs, malformed strings, missing product codes).

---

### 3.6 Add HATEOAS links (GAP-API-05)

**Priority:** Improves API discoverability.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add `spring-boot-starter-hateoas` to `pom.xml`. Convert `BorrowerDto`, `LoanSummaryDto`, and `PaymentDto` to extend `RepresentationModel`. In controllers, add self links and related resource links (e.g., a borrower links to its loans, a loan links to its payments). Add comments explaining the HATEOAS link structure. Update tests to verify link presence.

---

### 3.7 Add circuit breaker for future external database (GAP-RES-03)

**Priority:** Prepares for production deployment with external databases.

> **Devin Prompt:**
> In the `uc-data-source-migration-legacy-to-modern` repo, add `resilience4j-spring-boot3` (open-source) to `pom.xml`. Add `@CircuitBreaker` annotations to repository-calling methods in `LoanService` with fallback methods that return empty lists or throw a `ServiceUnavailableException`. Configure circuit breaker settings in `application.properties` (failure-rate-threshold: 50%, wait-duration-in-open-state: 30s, sliding-window-size: 10). Add comments explaining the circuit breaker configuration and fallback strategy.

---

## Implementation Priority Matrix

```
                    Small Effort          Medium Effort         Large Effort
                ┌──────────────────┬──────────────────┬──────────────────┐
Critical        │                  │ 2.4 Security     │ 2.1 Test suite   │
                │                  │                  │                  │
High            │ 1.2 Exception    │ 2.2 Pagination   │ (migration work) │
                │ 1.3 Logging      │ 2.6 Date formats │                  │
                │ 1.4 Actuator     │                  │                  │
                │ 1.5 H2 security  │                  │                  │
                │                  │                  │                  │
Medium          │ 1.1 pom.xml fix  │ 2.7 Test fixtures│                  │
                │ 1.6 Validation   │ 3.3 Metrics      │ 3.2 Split svc    │
                │ 1.7 OpenAPI      │                  │                  │
                │ 2.3 Versioning   │                  │                  │
                │ 2.5 Timeouts     │                  │                  │
                │                  │                  │                  │
Low             │ 1.8 README fix   │ 3.6 HATEOAS      │                  │
                │ 3.4 CORS         │ 3.7 Circuit brkr │                  │
                │ 3.5 Null handling│                  │                  │
                └──────────────────┴──────────────────┴──────────────────┘
```

---

## Estimated Total Effort

| Phase | Items | Estimated Effort |
|-------|-------|-----------------|
| Phase 1 (Quick Wins) | 8 items | ~3–5 days |
| Phase 2 (Important) | 7 items | ~8–12 days |
| Phase 3 (Polish) | 7 items | ~5–8 days |
| **Total** | **22 items** | **~16–25 days** |

> **Note:** The core data source migration (Tasks 1–5 in `MIGRATION_TASKS.md`) is separate from this remediation work and should be prioritized alongside or ahead of Phase 2 items.
