"""
Tests for the JIL-to-DAB converter pipeline: parsing, conversion, and YAML generation.

Covers:
  - JIL parsing of all job types (CMD, BOX, FW, FT)
  - Condition parsing (single, multiple, combined with AND/OR)
  - Schedule conversion to Quartz cron expressions
  - Box-to-multi-task job conversion
  - File watcher to trigger conversion
  - YAML output structure validation
  - End-to-end pipeline from JIL text to DAB YAML
"""

import os
import tempfile
import unittest

import yaml

from jil_to_dab.converter import convert_jobs
from jil_to_dab.generator import bundle_to_dict, generate_yaml
from jil_to_dab.models import JilJobType
from jil_to_dab.parser import parse_conditions, parse_jil_text


class TestJilParser(unittest.TestCase):
    """Tests for the JIL parser module."""

    def test_parse_single_cmd_job(self):
        """Verify parsing a minimal CMD job with core attributes."""
        jil = """
        insert_job: test_job   job_type: CMD
        machine: server1
        owner: user@domain.com
        command: /path/to/script.sh
        description: "Test command job"
        """
        jobs = parse_jil_text(jil)
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual(job.job_name, "test_job")
        self.assertEqual(job.job_type, JilJobType.CMD)
        self.assertEqual(job.machine, "server1")
        self.assertEqual(job.owner, "user@domain.com")
        self.assertEqual(job.command, "/path/to/script.sh")
        self.assertEqual(job.description, "Test command job")

    def test_parse_box_with_children(self):
        """Verify parsing a BOX job and its child CMD jobs."""
        jil = """
        insert_job: my_box   job_type: BOX
        date_conditions: 1
        days_of_week: mo,tu,we,th,fr
        start_times: "08:00"

        insert_job: child1   job_type: CMD
        box_name: my_box
        command: /scripts/step1.sh

        insert_job: child2   job_type: CMD
        box_name: my_box
        command: /scripts/step2.sh
        condition: s(child1)
        """
        jobs = parse_jil_text(jil)
        self.assertEqual(len(jobs), 3)

        # Box job
        self.assertEqual(jobs[0].job_type, JilJobType.BOX)
        self.assertTrue(jobs[0].date_conditions)
        self.assertEqual(jobs[0].days_of_week, "mo,tu,we,th,fr")

        # Child jobs with box membership
        self.assertEqual(jobs[1].box_name, "my_box")
        self.assertEqual(jobs[2].box_name, "my_box")

        # Dependency condition on child2
        self.assertEqual(len(jobs[2].conditions), 1)
        self.assertEqual(jobs[2].conditions[0].job_name, "child1")

    def test_parse_file_watcher(self):
        """Verify parsing a file watcher job with all FW attributes."""
        jil = """
        insert_job: fw_job   job_type: FW
        machine: server1
        watch_file: /data/incoming/file_*.csv
        watch_interval: 120
        watch_file_min_size: 1024
        """
        jobs = parse_jil_text(jil)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_type, JilJobType.FW)
        self.assertEqual(jobs[0].watch_file, "/data/incoming/file_*.csv")
        self.assertEqual(jobs[0].watch_interval, 120)
        self.assertEqual(jobs[0].watch_file_min_size, 1024)

    def test_parse_file_transfer(self):
        """Verify parsing a file transfer job."""
        jil = """
        insert_job: ft_job   job_type: FT
        src_machine: server1
        dest_machine: server2
        src_file: /data/output/report.csv
        dest_file: /archive/reports/
        """
        jobs = parse_jil_text(jil)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_type, JilJobType.FT)
        self.assertEqual(jobs[0].src_machine, "server1")
        self.assertEqual(jobs[0].dest_file, "/archive/reports/")

    def test_parse_delete_job(self):
        """Verify delete_job directives are flagged correctly."""
        jil = """
        delete_job: old_job
        """
        jobs = parse_jil_text(jil)
        self.assertEqual(len(jobs), 1)
        self.assertTrue(jobs[0].is_delete)

    def test_parse_retry_and_alarm(self):
        """Verify retry count, alarm, and timeout attributes are parsed."""
        jil = """
        insert_job: retry_job   job_type: CMD
        command: /scripts/flaky.sh
        alarm_if_fail: 1
        n_retrys: 3
        term_run_time: 60
        max_run_alarm: 45
        """
        jobs = parse_jil_text(jil)
        job = jobs[0]
        self.assertTrue(job.alarm_if_fail)
        self.assertEqual(job.n_retrys, 3)
        self.assertEqual(job.term_run_time, 60)
        self.assertEqual(job.max_run_alarm, 45)

    def test_skip_comments_and_blanks(self):
        """Verify comments and blank lines are ignored."""
        jil = """
        /* This is a comment */
        # This is also a comment

        insert_job: real_job   job_type: CMD
        command: /scripts/real.sh
        """
        jobs = parse_jil_text(jil)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].job_name, "real_job")

    def test_parse_scheduling_attributes(self):
        """Verify all scheduling-related attributes are parsed correctly."""
        jil = """
        insert_job: scheduled_job   job_type: CMD
        command: /scripts/scheduled.sh
        date_conditions: 1
        days_of_week: mo,we,fr
        start_times: "14:30"
        timezone: US/Pacific
        run_calendar: business_days
        """
        jobs = parse_jil_text(jil)
        job = jobs[0]
        self.assertTrue(job.date_conditions)
        self.assertEqual(job.days_of_week, "mo,we,fr")
        self.assertEqual(job.start_times, "14:30")
        self.assertEqual(job.timezone, "US/Pacific")
        self.assertEqual(job.run_calendar, "business_days")


class TestConditionParser(unittest.TestCase):
    """Tests for the condition expression parser."""

    def test_single_success_condition(self):
        """Parse a single success condition."""
        conditions = parse_conditions("s(job_a)")
        self.assertEqual(len(conditions), 1)
        self.assertEqual(conditions[0].condition_type, "s")
        self.assertEqual(conditions[0].job_name, "job_a")

    def test_multiple_conditions_with_and(self):
        """Parse multiple conditions combined with AND."""
        conditions = parse_conditions("s(job_a) & s(job_b) & s(job_c)")
        self.assertEqual(len(conditions), 3)
        names = [c.job_name for c in conditions]
        self.assertIn("job_a", names)
        self.assertIn("job_b", names)
        self.assertIn("job_c", names)

    def test_mixed_condition_types(self):
        """Parse mixed success/failure/done conditions."""
        conditions = parse_conditions("s(job_a) & f(job_b) | d(job_c)")
        self.assertEqual(len(conditions), 3)
        types = {c.job_name: c.condition_type for c in conditions}
        self.assertEqual(types["job_a"], "s")
        self.assertEqual(types["job_b"], "f")
        self.assertEqual(types["job_c"], "d")

    def test_notrunning_condition(self):
        """Parse a notrunning (n) condition."""
        conditions = parse_conditions("n(blocker_job)")
        self.assertEqual(len(conditions), 1)
        self.assertEqual(conditions[0].condition_type, "n")


class TestConverter(unittest.TestCase):
    """Tests for the JIL-to-DAB converter."""

    def test_standalone_cmd_to_dab_job(self):
        """Convert a standalone CMD job to a single-task DAB job."""
        jil = """
        insert_job: daily_sync   job_type: CMD
        command: /scripts/sync.sh
        description: "Daily data sync"
        date_conditions: 1
        days_of_week: mo,tu,we,th,fr
        start_times: "08:00"
        timezone: US/Eastern
        alarm_if_fail: 1
        owner: admin@bank.com
        n_retrys: 2
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs, bundle_name="test_bundle")

        self.assertEqual(len(bundle.jobs), 1)
        dab_job = list(bundle.jobs.values())[0]
        self.assertEqual(dab_job.name, "Daily data sync")
        self.assertEqual(len(dab_job.tasks), 1)

        # Verify schedule was generated
        self.assertIsNotNone(dab_job.schedule)
        self.assertIn("MON", dab_job.schedule.quartz_cron_expression)
        self.assertEqual(dab_job.schedule.timezone_id, "US/Eastern")

        # Verify notifications
        self.assertIsNotNone(dab_job.email_notifications)
        self.assertIn("admin@bank.com", dab_job.email_notifications.on_failure)

        # Verify retry on task
        task = dab_job.tasks[0]
        self.assertEqual(task.max_retries, 2)

    def test_box_to_multitask_job(self):
        """Convert a BOX with children to a multi-task DAB job."""
        jil = """
        insert_job: etl_box   job_type: BOX
        description: "ETL Pipeline"
        date_conditions: 1
        days_of_week: mo,tu,we,th,fr
        start_times: "06:00"
        owner: etl@bank.com
        alarm_if_fail: 1

        insert_job: step1   job_type: CMD
        box_name: etl_box
        command: /scripts/extract.sh

        insert_job: step2   job_type: CMD
        box_name: etl_box
        command: /scripts/transform.sql
        condition: s(step1)

        insert_job: step3   job_type: CMD
        box_name: etl_box
        command: /scripts/load.sh
        condition: s(step2)
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs)

        # Should produce exactly 1 DAB job (the box)
        self.assertEqual(len(bundle.jobs), 1)
        dab_job = list(bundle.jobs.values())[0]

        # Should have 3 tasks (one per child)
        self.assertEqual(len(dab_job.tasks), 3)

        # Verify task dependencies are correctly mapped
        task_keys = [t.task_key for t in dab_job.tasks]
        self.assertIn("step1", task_keys)
        self.assertIn("step2", task_keys)
        self.assertIn("step3", task_keys)

        # step2 should depend on step1
        step2 = next(t for t in dab_job.tasks if t.task_key == "step2")
        dep_keys = [d.task_key for d in step2.depends_on]
        self.assertIn("step1", dep_keys)

        # step2's SQL command should map to a notebook task
        self.assertIsNotNone(step2.notebook_task)

    def test_file_watcher_to_trigger(self):
        """Convert a standalone FW job to a file arrival trigger."""
        jil = """
        insert_job: watch_files   job_type: FW
        watch_file: /data/incoming/updates_*.xml
        watch_interval: 300
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs)

        # Should produce a trigger and a companion job
        self.assertEqual(len(bundle.triggers), 1)
        self.assertEqual(len(bundle.jobs), 1)

        trigger = list(bundle.triggers.values())[0]
        self.assertIn("/data/incoming/updates_*.xml", trigger.url)
        self.assertEqual(trigger.min_time_between_triggers_seconds, 300)

    def test_file_transfer_to_shell_task(self):
        """Convert an FT job to a DAB shell task with dbutils copy command."""
        jil = """
        insert_job: archive_files   job_type: FT
        src_machine: server1
        dest_machine: archive_server
        src_file: /data/output/report.csv
        dest_file: /archive/reports/
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs)

        self.assertEqual(len(bundle.jobs), 1)
        task = list(bundle.jobs.values())[0].tasks[0]
        self.assertIsNotNone(task.shell_task)
        self.assertIn("dbutils.fs.cp", task.shell_task.command)

    def test_delete_jobs_are_skipped(self):
        """Verify delete_job directives produce no DAB output."""
        jil = """
        delete_job: old_job
        insert_job: active_job   job_type: CMD
        command: /scripts/active.sh
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs)

        # Only the active job should be in the bundle
        self.assertEqual(len(bundle.jobs), 1)
        self.assertIn("active_job", list(bundle.jobs.keys()))

    def test_tags_for_traceability(self):
        """Verify AutoSys source job name is stored in DAB tags."""
        jil = """
        insert_job: traced_job   job_type: CMD
        command: /scripts/traced.sh
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs)

        dab_job = list(bundle.jobs.values())[0]
        self.assertEqual(dab_job.tags["autosys_source"], "traced_job")

    def test_sql_command_maps_to_notebook(self):
        """Verify SQL script commands get mapped to notebook tasks."""
        jil = """
        insert_job: sql_job   job_type: CMD
        command: /opt/etl/sql/transform.sql
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs)

        task = list(bundle.jobs.values())[0].tasks[0]
        self.assertIsNotNone(task.notebook_task)
        self.assertIsNone(task.shell_task)

    def test_shell_command_maps_to_shell_task(self):
        """Verify shell script commands get mapped to shell tasks."""
        jil = """
        insert_job: shell_job   job_type: CMD
        command: /opt/scripts/run.sh
        profile: /opt/scripts/.profile
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs)

        task = list(bundle.jobs.values())[0].tasks[0]
        self.assertIsNotNone(task.shell_task)
        # Verify profile sourcing is prepended
        self.assertIn("source /opt/scripts/.profile", task.shell_task.command)


class TestYamlGenerator(unittest.TestCase):
    """Tests for the DAB YAML generator."""

    def test_yaml_structure(self):
        """Verify the generated YAML has the correct top-level structure."""
        jil = """
        insert_job: test_job   job_type: CMD
        command: /scripts/test.sh
        description: "Test job"
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs, bundle_name="test_bundle")
        config = bundle_to_dict(bundle)

        # Verify top-level keys
        self.assertIn("bundle", config)
        self.assertIn("resources", config)
        self.assertEqual(config["bundle"]["name"], "test_bundle")
        self.assertIn("jobs", config["resources"])

    def test_yaml_is_valid(self):
        """Verify the generated YAML string is parseable."""
        jil = """
        insert_job: yaml_test   job_type: CMD
        command: /scripts/yaml.sh
        date_conditions: 1
        days_of_week: mo,tu,we,th,fr
        start_times: "09:00"
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs)
        yaml_str = generate_yaml(bundle)

        # Should be parseable YAML
        parsed = yaml.safe_load(yaml_str)
        self.assertIsNotNone(parsed)
        self.assertIn("bundle", parsed)

    def test_schedule_in_yaml(self):
        """Verify schedule appears correctly in YAML output."""
        jil = """
        insert_job: sched_job   job_type: CMD
        command: /scripts/sched.sh
        date_conditions: 1
        days_of_week: mo,we,fr
        start_times: "14:30"
        timezone: US/Pacific
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs)
        config = bundle_to_dict(bundle)

        job_config = list(config["resources"]["jobs"].values())[0]
        self.assertIn("schedule", job_config)
        self.assertEqual(job_config["schedule"]["timezone_id"], "US/Pacific")
        self.assertIn("MON", job_config["schedule"]["quartz_cron_expression"])


class TestEndToEnd(unittest.TestCase):
    """End-to-end integration tests using the sample JIL file."""

    def test_sample_jil_conversion(self):
        """Convert the full sample JIL file and validate the output."""
        sample_path = os.path.join(
            os.path.dirname(__file__), "..", "samples", "sample_jobs.jil"
        )
        if not os.path.exists(sample_path):
            self.skipTest("Sample JIL file not found")

        from jil_to_dab.parser import parse_jil_file

        jobs = parse_jil_file(sample_path)

        # The sample file has 12 job definitions
        self.assertGreaterEqual(len(jobs), 10)

        # Convert and verify
        bundle = convert_jobs(jobs, bundle_name="banking_etl_migration")
        yaml_str = generate_yaml(bundle)

        # Should be parseable and non-empty
        parsed = yaml.safe_load(yaml_str)
        self.assertEqual(parsed["bundle"]["name"], "banking_etl_migration")
        self.assertGreater(len(parsed["resources"]["jobs"]), 0)

    def test_write_and_read_yaml(self):
        """Verify YAML can be written to disk and read back correctly."""
        jil = """
        insert_job: disk_test   job_type: CMD
        command: /scripts/disk.sh
        """
        jobs = parse_jil_text(jil)
        bundle = convert_jobs(jobs, bundle_name="disk_test")

        from jil_to_dab.generator import write_yaml

        with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as f:
            temp_path = f.name

        try:
            write_yaml(bundle, temp_path)
            with open(temp_path) as f:
                content = f.read()
            parsed = yaml.safe_load(content)
            self.assertEqual(parsed["bundle"]["name"], "disk_test")
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    unittest.main()
