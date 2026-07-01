"""
CLI entry point for the JIL-to-DAB converter.

Usage:
    python -m jil_to_dab.cli <input.jil> [--output <output.yml>] [--bundle-name <name>]

Arguments:
    input_file          Path to the AutoSys JIL file to convert
    --output, -o        Output YAML file path (default: databricks.yml)
    --bundle-name, -n   Name for the DAB bundle (default: migrated_autosys_jobs)
    --dry-run           Print YAML to stdout without writing to disk
    --verbose, -v       Show detailed conversion summary
"""

import argparse
import sys
from pathlib import Path

from .converter import convert_jobs
from .generator import generate_yaml, write_yaml
from .parser import parse_jil_file


def _print_summary(jobs, bundle) -> None:
    """Print a human-readable conversion summary to stderr."""
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"JIL-to-DAB Conversion Summary", file=sys.stderr)
    print(f"{'='*60}", file=sys.stderr)
    print(f"  Input JIL jobs parsed:     {len(jobs)}", file=sys.stderr)
    print(f"  DAB jobs generated:        {len(bundle.jobs)}", file=sys.stderr)
    print(f"  File arrival triggers:     {len(bundle.triggers)}", file=sys.stderr)

    # Count total tasks across all jobs
    total_tasks = sum(len(job.tasks) for job in bundle.jobs.values())
    print(f"  Total DAB tasks:           {total_tasks}", file=sys.stderr)

    # List job types found
    job_types = set()
    for j in jobs:
        job_types.add(j.job_type.value)
    print(f"  Job types found:           {', '.join(sorted(job_types))}", file=sys.stderr)

    # List jobs with schedules
    scheduled = [k for k, v in bundle.jobs.items() if v.schedule]
    if scheduled:
        print(f"  Scheduled jobs:            {len(scheduled)}", file=sys.stderr)

    # List jobs with notifications
    notified = [k for k, v in bundle.jobs.items() if v.email_notifications]
    if notified:
        print(f"  Jobs with notifications:   {len(notified)}", file=sys.stderr)

    print(f"{'='*60}\n", file=sys.stderr)


def main() -> None:
    """Main CLI entry point for the JIL-to-DAB converter."""
    parser = argparse.ArgumentParser(
        prog="jil-to-dab",
        description="Convert AutoSys JIL job definitions to Databricks Asset Bundle (DAB) YAML",
        epilog="Example: python -m jil_to_dab.cli jobs.jil -o databricks.yml --verbose",
    )
    parser.add_argument(
        "input_file",
        type=str,
        help="Path to the AutoSys JIL file to convert",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="databricks.yml",
        help="Output YAML file path (default: databricks.yml)",
    )
    parser.add_argument(
        "--bundle-name", "-n",
        type=str,
        default="migrated_autosys_jobs",
        help="Name for the DAB bundle (default: migrated_autosys_jobs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print YAML to stdout without writing to disk",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed conversion summary",
    )

    args = parser.parse_args()

    # Validate input file exists
    input_path = Path(args.input_file)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Step 1: Parse the JIL file
    try:
        jobs = parse_jil_file(input_path)
    except Exception as e:
        print(f"Error parsing JIL file: {e}", file=sys.stderr)
        sys.exit(1)

    if not jobs:
        print("Warning: No jobs found in the input JIL file.", file=sys.stderr)
        sys.exit(0)

    # Step 2: Convert parsed jobs to DAB bundle
    bundle = convert_jobs(jobs, bundle_name=args.bundle_name)

    # Step 3: Generate and output YAML
    if args.dry_run:
        # Print to stdout for piping/inspection
        yaml_content = generate_yaml(bundle)
        print(yaml_content)
    else:
        output_path = write_yaml(bundle, args.output)
        print(f"DAB YAML written to: {output_path}", file=sys.stderr)

    # Print summary if verbose mode is enabled
    if args.verbose:
        _print_summary(jobs, bundle)


if __name__ == "__main__":
    main()
