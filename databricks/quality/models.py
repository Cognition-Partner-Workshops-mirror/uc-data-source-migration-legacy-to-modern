"""
Shared data models for the data quality framework.
Kept separate from the PySpark-dependent checks module so the report
generator can import them without requiring a Spark runtime.
"""

from dataclasses import dataclass, field
from typing import List
from datetime import datetime


@dataclass
class CheckResult:
    """Structured result for a single data quality check."""
    category: str       # ROW_COUNT, NULL_CHECK, REFERENTIAL_INTEGRITY, BUSINESS_RULE
    table: str          # Target table being checked
    check_name: str     # Human-readable check description
    status: str         # PASS or FAIL
    detail: str         # Additional context (counts, sample IDs, etc.)
    severity: str = "HIGH"  # CRITICAL, HIGH, MEDIUM, LOW


@dataclass
class QualityReport:
    """Aggregated quality report across all checks."""
    run_timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    results: List[CheckResult] = field(default_factory=list)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == "PASS")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "FAIL")

    @property
    def total_count(self) -> int:
        return len(self.results)
