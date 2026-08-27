from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_AWS_API_METHODS = {
    "describe_clusters",
    "describe_services",
    "list_tasks",
    "describe_tasks",
    "filter_log_events",
}
EXPECTED_IAM_ACTIONS = {
    "ecs:DescribeClusters",
    "ecs:DescribeServices",
    "ecs:ListTasks",
    "ecs:DescribeTasks",
    "logs:FilterLogEvents",
}


class ReadOnlyContractTest(unittest.TestCase):
    def test_collectors_call_only_the_five_approved_aws_apis(self):
        source = (ROOT / "triage-agent" / "tools.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        methods = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Attribute)
            and isinstance(node.func.value.value, ast.Name)
            and node.func.value.value.id == "self"
            and node.func.value.attr in {"ecs", "logs"}
        }

        self.assertEqual(methods, EXPECTED_AWS_API_METHODS)

    def test_terraform_policy_grants_only_the_five_approved_actions(self):
        policy = (ROOT / "infrastructure" / "terraform" / "triage-iam.tf").read_text(
            encoding="utf-8"
        )
        actions = set(re.findall(r'"((?:ecs|logs):[A-Z][A-Za-z]+)"', policy))

        self.assertEqual(actions, EXPECTED_IAM_ACTIONS)
        self.assertIn('sid       = "ListTargetClusterTasks"', policy)
        self.assertIn('resources = ["*"]', policy)
        self.assertIn('variable = "ecs:cluster"', policy)


if __name__ == "__main__":
    unittest.main()
