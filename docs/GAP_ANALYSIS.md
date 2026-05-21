# Gap Analysis — Loan Service

This document compares the current codebase against engineering best practices across seven categories. Each gap is rated by **Severity** (Critical / High / Medium / Low) and estimated **Effort** to remediate (Small / Medium / Large).

---

## 1. Code Organization

### GAP-ORG-01: All entity fields are `String` — no proper Java types

**Current:** Every field in all four legacy entity classes (`LegacyBorrower`, `LegacyLoanAccount`, `LegacyLoanProduct`, `LegacyPayment`) is declared as `String`, mirroring the legacy VARCHAR-everything schema.

**Best Practice:** JPA entities should use proper Java types (`LocalDate`, `BigDecimal`, `Integer`, `Boolean`) to leverage compile-time type safety and Hibernate type conversion.

**Impact:** The service layer is burdened with manual parsing (`parseLegacyAmount`, `parseLegacyInteger`, etc.) that would be unnecessary with properly typed entities.

| Severity | Effort |
|----------|--------|
| High | Large |

---

### GAP-ORG-02: No JPA relationships between entities

**Current:** Entities reference each other by string IDs (e.g., `LegacyLoanAccount.borrowerId` is a plain `String`). There are no `@ManyToOne`, `@OneToMany`, or `@JoinColumn` annotations.

**Best Practice:** JPA relationships should be modeled with proper annotations to enable join queries, cascading, lazy/eager loading, and referential integrity at the ORM level.

**Impact:** Every cross-entity query requires manual orchestration in the service layer (e.g., loading all products into a map, then looking up by code).

| Severity | Effort |
|----------|--------|
| High | Large |

---

### GAP-ORG-03: Denormalized data in CDW_LN_ACCT

**Current:** `LegacyLoanAccount` contains denormalized borrower fields (`borrowerFirstName`, `borrowerLastName`, `borrowerSsnLast4`) that duplicate data from `LegacyBorrower`.

**Best Practice:** Data should be normalized; loan accounts should reference borrowers via a foreign key.

**Impact:** Risk of data inconsistency between loan accounts and borrower master records. Service layer must decide which source of truth to use for borrower names.

| Severity | Effort |
|----------|--------|
| High | Large |

---

### GAP-ORG-04: Single service class for all business logic

**Current:** `LoanService` handles borrower retrieval, loan retrieval, payment retrieval, and all data translation logic in a single 210-line class.

**Best Practice:** Separate concerns into domain-specific services (e.g., `BorrowerService`, `PaymentService`) and extract translation/mapping into dedicated mapper classes.

**Impact:** As the application grows, this monolithic service will become difficult to test and maintain.

| Severity | Effort |
|----------|--------|
| Medium | Medium |

---

### GAP-ORG-05: No shared DTO mapper / mapping framework

**Current:** Entity-to-DTO mapping is done manually in private methods within `LoanService`.

**Best Practice:** Use a mapping framework like MapStruct or at least extract mapping logic into dedicated mapper classes for reusability and testability.

| Severity | Effort |
|----------|--------|
| Low | Small |

---

### GAP-ORG-06: `pom.xml` contains a typo (`<relativeTo/>`)

**Current:** The parent POM reference uses `<relativeTo/>` instead of `<relativePath/>`.

**Best Practice:** Build files should be syntactically correct without external fixups.

**Impact:** Requires a `sed` workaround in the environment blueprint to build successfully.

| Severity | Effort |
|----------|--------|
| Medium | Small |

---

## 2. Error Handling

### GAP-ERR-01: No global exception handler

**Current:** There is no `@ControllerAdvice` or `@ExceptionHandler`. Errors produce Spring Boot's default whitelabel error response.

**Best Practice:** Implement a `@RestControllerAdvice` with handlers for common exceptions, returning consistent `ProblemDetail` (RFC 7807) responses.

**Impact:** Clients receive inconsistent, framework-generated error bodies with stack traces exposed in non-production profiles.

| Severity | Effort |
|----------|--------|
| High | Small |

---

### GAP-ERR-02: Raw `RuntimeException` for not-found cases

**Current:** `LoanService.getLoanById()` and `getBorrowerById()` throw `new RuntimeException("Loan not found: ...")` when entities are missing.

**Best Practice:** Use custom exception classes (e.g., `ResourceNotFoundException`) mapped to HTTP 404 via `@ExceptionHandler`.

**Impact:** Callers receive HTTP 500 instead of HTTP 404 for missing resources. Stack traces are leaked in responses.

| Severity | Effort |
|----------|--------|
| High | Small |

---

### GAP-ERR-03: No input validation

**Current:** Path variables (`id`, `loanId`) are accepted without any validation. No `@Valid`, `@Pattern`, or custom validators.

**Best Practice:** Validate input at the controller layer using Bean Validation annotations or custom validators.

**Impact:** Malformed or injection-style inputs are passed directly to the persistence layer.

| Severity | Effort |
|----------|--------|
| Medium | Small |

---

### GAP-ERR-04: Silent null handling in parsing methods

**Current:** Methods like `parseLegacyAmount()` return `BigDecimal.ZERO` for null/blank inputs, and `parseLegacyInteger()` returns `null`. No logging of unexpected data.

**Best Practice:** Log warnings for unexpected or malformed data during parsing to aid debugging.

| Severity | Effort |
|----------|--------|
| Low | Small |

---

## 3. Testing

### GAP-TST-01: Only one test — a context-load smoke test

**Current:** The entire test suite consists of a single `contextLoads()` test in `LoanServiceApplicationTests`.

**Best Practice:** Comprehensive test suite including:
- Unit tests for `LoanService` parsing/translation methods
- Integration tests for repository queries
- Controller tests (MockMvc) for API contract verification
- Golden file tests for migration parity validation

**Impact:** Zero confidence that code changes don't break functionality. The migration task specifically calls for golden file tests (Task 4 in MIGRATION_TASKS.md) that don't exist yet.

| Severity | Effort |
|----------|--------|
| Critical | Large |

---

### GAP-TST-02: No test data fixtures or factories

**Current:** Tests rely on the same `data-legacy.sql` seed data loaded for the application.

**Best Practice:** Use test-specific data builders or fixtures to isolate test state from production seed data.

| Severity | Effort |
|----------|--------|
| Medium | Medium |

---

## 4. Security

### GAP-SEC-01: No authentication or authorization

**Current:** All API endpoints are completely open — no Spring Security, no JWT, no API keys.

**Best Practice:** Secure endpoints with Spring Security. At minimum, add basic authentication for sensitive borrower data (SSN hashes, financial data).

**Impact:** PII (names, addresses, emails, credit scores, SSN hashes) is accessible without any authentication.

| Severity | Effort |
|----------|--------|
| Critical | Medium |

---

### GAP-SEC-02: Encrypted SSN stored and accessible

**Current:** `LegacyBorrower.ssnEncrypted` is mapped from the database but not exposed via the API (the DTO excludes it). However, it is accessible via H2 console.

**Best Practice:** Sensitive fields should be explicitly excluded from JPA results when not needed, or the H2 console should be disabled in production.

| Severity | Effort |
|----------|--------|
| High | Small |

---

### GAP-SEC-03: H2 console enabled without authentication

**Current:** `spring.h2.console.enabled=true` with default credentials (`sa` / empty password).

**Best Practice:** H2 console should be disabled by default and only enabled in development profiles with restricted access.

| Severity | Effort |
|----------|--------|
| High | Small |

---

### GAP-SEC-04: No CORS configuration

**Current:** No CORS headers configured. Default Spring Boot behavior blocks cross-origin requests.

**Best Practice:** Explicitly configure CORS policy for known frontend origins.

| Severity | Effort |
|----------|--------|
| Low | Small |

---

### GAP-SEC-05: SQL logging enabled (`show-sql=true`)

**Current:** `spring.jpa.show-sql=true` is hardcoded, logging all SQL statements including those with sensitive data.

**Best Practice:** Disable SQL logging by default; enable only in development profiles.

| Severity | Effort |
|----------|--------|
| Medium | Small |

---

## 5. API Design

### GAP-API-01: No pagination or filtering

**Current:** `GET /api/loans` and `GET /api/borrowers` return all records with no pagination, sorting, or filtering support.

**Best Practice:** Implement `Pageable` support with `page`, `size`, `sort` query parameters. Return pagination metadata in responses.

**Impact:** Will not scale beyond small datasets. Currently only 5 records, but a production dataset would overwhelm clients.

| Severity | Effort |
|----------|--------|
| High | Medium |

---

### GAP-API-02: No API versioning

**Current:** Endpoints use `/api/loans` with no version prefix.

**Best Practice:** Use versioned paths (`/api/v1/loans`) or header-based versioning to support backward compatibility during migration.

| Severity | Effort |
|----------|--------|
| Medium | Small |

---

### GAP-API-03: No OpenAPI / Swagger documentation

**Current:** No `springdoc-openapi` or Swagger dependency. No API documentation.

**Best Practice:** Add `springdoc-openapi-starter-webmvc-ui` for auto-generated OpenAPI 3.0 docs at `/swagger-ui.html`.

| Severity | Effort |
|----------|--------|
| Medium | Small |

---

### GAP-API-04: Inconsistent date representation in responses

**Current:** Dates are returned as raw legacy strings (e.g., `"02/15/2019"` in `originationDate`) rather than ISO 8601 format.

**Best Practice:** API responses should use ISO 8601 date format (`YYYY-MM-DD`) for interoperability.

| Severity | Effort |
|----------|--------|
| Medium | Small |

---

### GAP-API-05: No HATEOAS or resource linking

**Current:** DTOs are flat objects with no hypermedia links between related resources.

**Best Practice:** Consider Spring HATEOAS for linking borrowers to their loans, loans to their payments, etc.

| Severity | Effort |
|----------|--------|
| Low | Medium |

---

### GAP-API-06: Read-only API — no write endpoints

**Current:** Only `GET` endpoints exist. No `POST`, `PUT`, `PATCH`, or `DELETE`.

**Best Practice:** For a complete CRUD service, expose write endpoints with proper validation and idempotency.

**Note:** This may be intentional for the current migration-focused scope.

| Severity | Effort |
|----------|--------|
| Low | Large |

---

### GAP-API-07: Payment endpoint URL inconsistency

**Current:** README documents `GET /api/payments/loan/{loanId}` but the actual implementation is `GET /api/loans/{loanId}/payments` (nested under loans).

**Best Practice:** Documentation and implementation should match. The nested URL is the better REST design.

| Severity | Effort |
|----------|--------|
| Low | Small |

---

## 6. Observability

### GAP-OBS-01: No structured logging

**Current:** No SLF4J logger is used anywhere in the application code. The only logging comes from framework-level SQL output (`show-sql=true`).

**Best Practice:** Add structured logging (SLF4J + Logback) in service and controller layers for request tracing, error reporting, and audit trails.

| Severity | Effort |
|----------|--------|
| High | Small |

---

### GAP-OBS-02: No health check endpoint

**Current:** Spring Boot Actuator is not included as a dependency. No `/actuator/health` endpoint.

**Best Practice:** Add `spring-boot-starter-actuator` with health, info, and metrics endpoints.

| Severity | Effort |
|----------|--------|
| High | Small |

---

### GAP-OBS-03: No metrics or distributed tracing

**Current:** No Micrometer, Prometheus, or tracing (Zipkin/OpenTelemetry) integration.

**Best Practice:** Instrument with Micrometer for metrics and OpenTelemetry for distributed tracing.

| Severity | Effort |
|----------|--------|
| Medium | Medium |

---

## 7. Resilience

### GAP-RES-01: No timeout configuration

**Current:** No connection pool settings, no query timeouts, no HTTP client timeouts.

**Best Practice:** Configure HikariCP connection pool sizes and timeouts. Set JPA query timeouts.

| Severity | Effort |
|----------|--------|
| Medium | Small |

---

### GAP-RES-02: No graceful error recovery

**Current:** `NullPointerException` is possible if `products.get(acct.getProductCode())` returns null (the code handles it partially but inconsistently).

**Best Practice:** Defensive coding with proper null checks and fallback values throughout the translation layer.

| Severity | Effort |
|----------|--------|
| Medium | Small |

---

### GAP-RES-03: No circuit breaker or retry patterns

**Current:** No resilience libraries (Resilience4j, Spring Retry). Single point of failure on the H2 database.

**Best Practice:** For production with external databases, implement circuit breakers and retry policies.

**Note:** Less critical for an in-memory H2 setup, but important for production deployment.

| Severity | Effort |
|----------|--------|
| Low | Medium |

---

## Summary Table

| ID | Category | Gap | Severity | Effort |
|----|----------|-----|----------|--------|
| GAP-ORG-01 | Code Organization | All entity fields are String | High | Large |
| GAP-ORG-02 | Code Organization | No JPA relationships | High | Large |
| GAP-ORG-03 | Code Organization | Denormalized data in loan accounts | High | Large |
| GAP-ORG-04 | Code Organization | Single service class for all logic | Medium | Medium |
| GAP-ORG-05 | Code Organization | No DTO mapper framework | Low | Small |
| GAP-ORG-06 | Code Organization | pom.xml typo (`<relativeTo/>`) | Medium | Small |
| GAP-ERR-01 | Error Handling | No global exception handler | High | Small |
| GAP-ERR-02 | Error Handling | Raw RuntimeException for not-found | High | Small |
| GAP-ERR-03 | Error Handling | No input validation | Medium | Small |
| GAP-ERR-04 | Error Handling | Silent null handling in parsers | Low | Small |
| GAP-TST-01 | Testing | Only one smoke test | Critical | Large |
| GAP-TST-02 | Testing | No test data fixtures | Medium | Medium |
| GAP-SEC-01 | Security | No authentication/authorization | Critical | Medium |
| GAP-SEC-02 | Security | SSN hash accessible via H2 console | High | Small |
| GAP-SEC-03 | Security | H2 console enabled without auth | High | Small |
| GAP-SEC-04 | Security | No CORS configuration | Low | Small |
| GAP-SEC-05 | Security | SQL logging enabled in all profiles | Medium | Small |
| GAP-API-01 | API Design | No pagination or filtering | High | Medium |
| GAP-API-02 | API Design | No API versioning | Medium | Small |
| GAP-API-03 | API Design | No OpenAPI documentation | Medium | Small |
| GAP-API-04 | API Design | Inconsistent date format in responses | Medium | Small |
| GAP-API-05 | API Design | No HATEOAS | Low | Medium |
| GAP-API-06 | API Design | Read-only API (no write endpoints) | Low | Large |
| GAP-API-07 | API Design | README/code endpoint URL mismatch | Low | Small |
| GAP-OBS-01 | Observability | No structured logging | High | Small |
| GAP-OBS-02 | Observability | No health check endpoint | High | Small |
| GAP-OBS-03 | Observability | No metrics or tracing | Medium | Medium |
| GAP-RES-01 | Resilience | No timeout configuration | Medium | Small |
| GAP-RES-02 | Resilience | Inconsistent null handling | Medium | Small |
| GAP-RES-03 | Resilience | No circuit breaker / retry | Low | Medium |
