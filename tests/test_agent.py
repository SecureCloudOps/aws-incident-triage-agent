from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "triage-agent"))

from agent import run_agent  # noqa: E402
from prompts import REQUIRED_SECTIONS  # noqa: E402


class FakeResponses:
    def __init__(self):
        self.requests = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if len(self.requests) <= 3:
            names = (
                "get_ecs_service_status",
                "get_recent_cloudwatch_errors",
                "analyze_failure_patterns",
            )
            name = names[len(self.requests) - 1]
            arguments = (
                '{"lookback_minutes": 60, "limit": 20}'
                if name == "get_recent_cloudwatch_errors"
                else "{}"
            )
            call = SimpleNamespace(
                type="function_call",
                name=name,
                arguments=arguments,
                call_id=f"call-{len(self.requests)}",
            )
            return SimpleNamespace(id=f"resp-{len(self.requests)}", output=[call], output_text="")
        report = "\n\n".join(f"## {section}\n\nTest content." for section in REQUIRED_SECTIONS)
        return SimpleNamespace(id="resp-2", output=[], output_text=report)


class FakeDispatcher:
    definitions = [{"type": "function", "name": "get_ecs_service_status"}]

    def __init__(self):
        self.calls = []
        self.evidence = {}

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        keys = {
            "get_ecs_service_status": "ecs_status",
            "get_recent_cloudwatch_errors": "log_errors",
            "analyze_failure_patterns": "failure_patterns",
        }
        self.evidence[keys[name]] = {"collected": True}
        return {"service": {"status": "ACTIVE"}}


class AgentLoopTest(unittest.TestCase):
    def test_returns_report_after_function_call(self):
        responses = FakeResponses()
        client = SimpleNamespace(responses=responses)
        dispatcher = FakeDispatcher()

        report = run_agent(
            client=client,
            model="test-model",
            dispatcher=dispatcher,
            request="investigate",
        )

        self.assertEqual(
            dispatcher.calls,
            [
                ("get_ecs_service_status", {}),
                ("get_recent_cloudwatch_errors", {"lookback_minutes": 60, "limit": 20}),
                ("analyze_failure_patterns", {}),
            ],
        )
        self.assertIn("## Confirmed root cause", report)
        for request in responses.requests[1:]:
            tool_output = request["input"][0]
            self.assertEqual(tool_output["type"], "function_call_output")
            self.assertTrue(json.loads(tool_output["output"])["ok"])

    def test_reprompts_if_model_skips_required_evidence(self):
        class PrematureResponses:
            def __init__(self):
                self.requests = []

            def create(self, **kwargs):
                self.requests.append(kwargs)
                if len(self.requests) == 1:
                    return SimpleNamespace(id="early", output=[], output_text="too early")
                calls = [
                    SimpleNamespace(
                        type="function_call",
                        name=name,
                        arguments=(
                            '{"lookback_minutes": 60, "limit": 20}'
                            if name == "get_recent_cloudwatch_errors"
                            else "{}"
                        ),
                        call_id=f"call-{index}",
                    )
                    for index, name in enumerate(
                        (
                            "get_ecs_service_status",
                            "get_recent_cloudwatch_errors",
                            "analyze_failure_patterns",
                        )
                    )
                ]
                if len(self.requests) == 2:
                    return SimpleNamespace(id="calls", output=calls, output_text="")
                report = "\n\n".join(
                    f"## {section}\n\nTest content." for section in REQUIRED_SECTIONS
                )
                return SimpleNamespace(id="done", output=[], output_text=report)

        responses = PrematureResponses()
        dispatcher = FakeDispatcher()

        report = run_agent(
            client=SimpleNamespace(responses=responses),
            model="test-model",
            dispatcher=dispatcher,
            request="investigate",
        )

        self.assertIn("## Evidence", report)
        self.assertIn("investigation is incomplete", responses.requests[1]["input"].lower())


if __name__ == "__main__":
    unittest.main()
