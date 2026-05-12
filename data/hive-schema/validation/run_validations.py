#!/usr/bin/env python3
"""
Main runner for Hive data validation automation.
Orchestrates all validation test modules (row counts, transformations,
aggregates, regression, integration) and generates execution summary reports.

Usage:
    python run_validations.py --as-of-dt 2024-01-31 [OPTIONS]

Options:
    --as-of-dt          Required. Snapshot date to validate (YYYY-MM-DD).
    --as-of-dt-prev     Optional. Previous snapshot for regression comparison.
    --jdbc-url          Override BEELINE_JDBC_URL from config.
    --user              Override BEELINE_USER from config.
    --password          Override BEELINE_PASSWORD from config.
    --categories        Comma-separated list of categories to run.
                        Options: row_count,transformation,aggregate,regression,integration
                        Default: all categories.
    --report-formats    Comma-separated report formats: text,html,json. Default: all.
    --verbose           Enable debug logging.

Examples:
    # Full validation for a month-end snapshot
    python run_validations.py --as-of-dt 2024-01-31 --as-of-dt-prev 2023-12-31

    # Only row counts and transformations
    python run_validations.py --as-of-dt 2024-01-15 --categories row_count,transformation

    # Custom JDBC endpoint with JSON report only
    python run_validations.py --as-of-dt 2024-01-31 \\
        --jdbc-url jdbc:hive2://hive-prod:10000 \\
        --report-formats json
"""

import argparse
import logging
import sys
import time

import config
import report_generator
import test_aggregates
import test_integration
import test_regression
import test_row_counts
import test_transformations

logger = logging.getLogger(__name__)


ALL_CATEGORIES = {
    "row_count",
    "transformation",
    "aggregate",
    "regression",
    "integration",
}


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Hive data validation automation — executes test cases via beeline JDBC."
    )
    parser.add_argument(
        "--as-of-dt",
        required=True,
        help="Snapshot date to validate (YYYY-MM-DD format).",
    )
    parser.add_argument(
        "--as-of-dt-prev",
        default=None,
        help="Previous snapshot date for regression comparison (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--jdbc-url",
        default=None,
        help="Override beeline JDBC URL.",
    )
    parser.add_argument(
        "--user",
        default=None,
        help="Override beeline user.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Override beeline password.",
    )
    parser.add_argument(
        "--categories",
        default=None,
        help="Comma-separated categories to run (default: all).",
    )
    parser.add_argument(
        "--report-formats",
        default="text,html,json",
        help="Comma-separated report formats: text,html,json (default: all).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def configure_logging(verbose: bool) -> None:
    """Set up logging with the appropriate level."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def apply_overrides(args: argparse.Namespace) -> None:
    """Apply CLI overrides to the config module."""
    if args.jdbc_url:
        config.BEELINE_JDBC_URL = args.jdbc_url
    if args.user:
        config.BEELINE_USER = args.user
    if args.password:
        config.BEELINE_PASSWORD = args.password


def run_category(
    category: str,
    as_of_dt: str,
    as_of_dt_prev: str | None,
) -> list[dict]:
    """
    Run all tests for a given category and return results.

    Args:
        category: One of ALL_CATEGORIES.
        as_of_dt: Current snapshot date.
        as_of_dt_prev: Previous snapshot date (required for regression).

    Returns:
        List of test result dicts.
    """
    if category == "row_count":
        return test_row_counts.run_all(as_of_dt)
    elif category == "transformation":
        return test_transformations.run_all(as_of_dt)
    elif category == "aggregate":
        return test_aggregates.run_all(as_of_dt)
    elif category == "regression":
        if not as_of_dt_prev:
            logger.warning(
                "Skipping regression tests: --as-of-dt-prev not provided."
            )
            return [{
                "test_id": "TC-RG-SKIP",
                "test_name": "Regression tests skipped",
                "category": "regression",
                "sql": "N/A",
                "expected": "N/A",
                "actual": "SKIPPED",
                "passed": True,
                "message": "No previous snapshot date provided; regression tests skipped.",
            }]
        return test_regression.run_all(as_of_dt, as_of_dt_prev)
    elif category == "integration":
        return test_integration.run_all(as_of_dt)
    else:
        logger.error("Unknown category: %s", category)
        return []


def main() -> int:
    """Main entry point. Returns 0 on all-pass, 1 on any failure."""
    args = parse_args()
    configure_logging(args.verbose)

    logger.info("=" * 60)
    logger.info("Hive Data Validation Automation — Starting")
    logger.info("=" * 60)

    # Apply config overrides from CLI
    apply_overrides(args)

    # Determine categories to run
    if args.categories:
        categories = {c.strip() for c in args.categories.split(",")}
        invalid = categories - ALL_CATEGORIES
        if invalid:
            logger.error("Invalid categories: %s. Valid: %s", invalid, ALL_CATEGORIES)
            return 2
    else:
        categories = ALL_CATEGORIES

    # Determine report formats
    report_formats = {f.strip() for f in args.report_formats.split(",")}

    logger.info("as_of_dt:      %s", args.as_of_dt)
    logger.info("as_of_dt_prev: %s", args.as_of_dt_prev or "N/A")
    logger.info("Categories:    %s", sorted(categories))
    logger.info("Report formats: %s", sorted(report_formats))

    # Run validations
    start_time = time.time()
    all_results = []

    for cat in sorted(categories):
        logger.info("-" * 40)
        logger.info("Running category: %s", cat)
        logger.info("-" * 40)
        cat_results = run_category(cat, args.as_of_dt, args.as_of_dt_prev)
        all_results.extend(cat_results)
        # Log category summary
        cat_passed = sum(1 for r in cat_results if r.get("passed"))
        cat_total = len(cat_results)
        logger.info(
            "Category '%s': %d/%d passed", cat, cat_passed, cat_total
        )

    elapsed = time.time() - start_time
    total = len(all_results)
    passed = sum(1 for r in all_results if r.get("passed"))
    failed = total - passed

    logger.info("=" * 60)
    logger.info("OVERALL: %d/%d passed, %d failed (%.1fs)", passed, total, failed, elapsed)
    logger.info("=" * 60)

    # Generate reports
    run_params = {
        "as_of_dt": args.as_of_dt,
        "as_of_dt_previous": args.as_of_dt_prev or "N/A",
        "execution_time": f"{elapsed:.1f}s",
        "jdbc_url": config.BEELINE_JDBC_URL,
        "categories": sorted(categories),
    }

    report_paths = []
    if "text" in report_formats:
        path = report_generator.generate_text_report(all_results, run_params)
        report_paths.append(path)
    if "html" in report_formats:
        path = report_generator.generate_html_report(all_results, run_params)
        report_paths.append(path)
    if "json" in report_formats:
        path = report_generator.generate_json_report(all_results, run_params)
        report_paths.append(path)

    for p in report_paths:
        logger.info("Report: %s", p)

    # Exit code: 0 if all passed, 1 if any failed
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
