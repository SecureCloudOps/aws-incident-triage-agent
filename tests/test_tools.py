from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "triage-agent"))

from prompts import REQUIRED_SECTIONS, ensure_report_contract  # noqa: E402
from tools import (  # noqa: E402
    AwsTarget,
    ReadOnlyAwsTools,
    ToolDispatcher,
    analyze_failure_patterns,
    redact_sensitive_text,
)

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)


class FakeEcsClient:
    def describe_clusters(self, **kwargs):
        self.cluster_request = kwargs
        return {
            "clusters": [
                {
                    "status": "ACTIVE",
                    "runningTasksCount": 1,
                    "pendingTasksCount": 0,
                    "activeServicesCount": 1,
                }
            ]
        }

    def describe_services(self, **kwargs):
        self.service_request = kwargs
        return {
            "services": [
                {
                    "serviceArn": "arn:aws:ecs:us-east-1:111122223333:service/demo/app",
                    "serviceName": "app",
                    "status": "ACTIVE",
                    "desiredCount": 1,
                    "runningCount": 1,
                    "pendingCount": 0,
                    "deployments": [
                        {
                            "id": "ecs-svc/1",
                            "status": "PRIMARY",
                            "desiredCount": 1,
                            "runningCount": 1,
                            "rolloutState": "COMPLETED",
                            "createdAt": NOW,
                        }
                    ],
                    "events": [
                        {
                            "id": "event-1",
                            "createdAt": NOW,
                            "message": "service reached a steady state",
                        }
                    ],
                }
            ],
            "failures": [],
        }

    def list_tasks(self, **kwargs):
        if kwargs["desiredStatus"] == "RUNNING":
            return {"taskArns": ["arn:aws:ecs:us-east-1:111122223333:task/demo/task-1"]}
        if kwargs["desiredStatus"] == "STOPPED":
            return {"taskArns": ["arn:aws:ecs:us-east-1:111122223333:task/demo/task-2"]}
        return {"taskArns": []}

    def describe_tasks(self, **kwargs):
        if kwargs["tasks"][0].endswith("task-1"):
            return {
                "tasks": [
                    {
                        "taskArn": kwargs["tasks"][0],
                        "lastStatus": "RUNNING",
                        "desiredStatus": "RUNNING",
                        "healthStatus": "HEALTHY",
                        "containers": [{"name": "app", "lastStatus": "RUNNING"}],
                    }
                ]
            }
        return {
            "tasks": [
                {
                    "taskArn": kwargs["tasks"][0],
                    "lastStatus": "STOPPED",
                    "desiredStatus": "STOPPED",
                    "stoppedAt": NOW,
                    "stoppedReason": "Essential container in task exited",
                    "containers": [
                        {
                            "name": "app",
                            "lastStatus": "STOPPED",
                            "exitCode": 137,
                            "reason": "OutOfMemoryError",
                        }
                    ],
                }
            ]
        }


class FakeLogsClient:
    def filter_log_events(self, **kwargs):
        self.request = kwargs
        return {
            "events": [
                {
                    "eventId": "log-1",
                    "timestamp": int(NOW.timestamp() * 1_000),
                    "logStreamName": "ecs/app/task-1",
                    "message": json.dumps(
                        {
                            "level": "ERROR",
                            "message": "request failed",
                            "status_code": 500,
                            "token": "must-not-leak",
                        }
                    ),
                },
                {
                    "eventId": "log-2",
                    "timestamp": int(NOW.timestamp() * 1_000),
                    "logStreamName": "ecs/app/task-1",
                    "message": '{"level":"INFO","message":"healthy"}',
                },
            ]
        }


class ReadOnlyAwsToolsTest(unittest.TestCase):
    def setUp(self):
        self.ecs = FakeEcsClient()
        self.logs = FakeLogsClient()
        self.target = AwsTarget("demo", "app", "/ecs/app", "us-east-1")
        self.tools = ReadOnlyAwsTools(
            self.target,
            ecs_client=self.ecs,
            logs_client=self.logs,
            now=lambda: NOW,
        )

    def test_collects_service_and_task_status(self):
        result = self.tools.get_ecs_service_status()

        self.assertEqual(result["service"]["runningCount"], 1)
        self.assertEqual(len(result["tasks"]), 2)
        self.assertEqual(result["tasks"][1]["containers"][0]["exitCode"], 137)
        self.assertEqual(self.ecs.service_request, {"cluster": "demo", "services": ["app"]})

    def test_filters_and_redacts_log_errors(self):
        result = self.tools.get_recent_cloudwatch_errors(lookback_minutes=60, limit=20)

        self.assertEqual(result["matched_event_count"], 1)
        serialized = json.dumps(result)
        self.assertNotIn("must-not-leak", serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertEqual(self.logs.request["logGroupName"], "/ecs/app")

    def test_analyzes_correlated_failure_patterns(self):
        ecs = self.tools.get_ecs_service_status()
        logs = self.tools.get_recent_cloudwatch_errors(lookback_minutes=60, limit=20)

        result = analyze_failure_patterns(ecs, logs)
        categories = {item["category"] for item in result["patterns"]}

        self.assertIn("out_of_memory", categories)
        self.assertIn("application_5xx", categories)
        self.assertIn("exception_or_traceback", categories)

    def test_dispatcher_caches_all_evidence(self):
        dispatcher = ToolDispatcher(self.tools, default_lookback_minutes=60, default_log_limit=20)

        evidence = dispatcher.collect_all()

        self.assertEqual(
            set(evidence),
            {"ecs_status", "log_errors", "failure_patterns"},
        )

    def test_report_contract_adds_missing_sections(self):
        report = ensure_report_contract("## Executive summary\n\nPartial")

        for section in REQUIRED_SECTIONS:
            self.assertIn(f"## {section}", report)

    def test_redacts_common_standalone_credential_formats(self):
        aws_key = "".join(("AKIA", "ABCDEFGHIJKLMNOP"))
        openai_key = "".join(("sk-proj-", "abcdefghijklmnopqrstuvwxyz123456"))
        bearer_value = "abcdefghijklmnopqrstuvwxyz"
        sample = (
            f"key {aws_key} token {openai_key} "
            f"Authorization: Bearer {bearer_value}"
        )

        redacted = redact_sensitive_text(sample)

        self.assertNotIn(aws_key, redacted)
        self.assertNotIn(openai_key, redacted)
        self.assertNotIn(bearer_value, redacted)
        self.assertIn("[REDACTED", redacted)


if __name__ == "__main__":
    unittest.main()
