#!/usr/bin/env python3
"""CLI entry point for the read-only OpenAI AWS incident triage agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError
from openai import OpenAI
from prompts import SYSTEM_PROMPT, ensure_report_contract, investigation_request
from tools import AwsTarget, ReadOnlyAwsTools, ToolDispatcher, redact_sensitive_text


def run_agent(
    *,
    client: OpenAI,
    model: str,
    dispatcher: ToolDispatcher,
    request: str,
    max_tool_rounds: int = 8,
) -> str:
    """Run a Responses API function-calling loop and return the final report."""

    response = client.responses.create(
        model=model,
        instructions=SYSTEM_PROMPT,
        input=request,
        tools=dispatcher.definitions,
        tool_choice="required",
    )

    for _ in range(max_tool_rounds):
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            required_evidence = {"ecs_status", "log_errors", "failure_patterns"}
            missing = sorted(required_evidence - set(dispatcher.evidence))
            if missing:
                response = client.responses.create(
                    model=model,
                    instructions=SYSTEM_PROMPT,
                    previous_response_id=response.id,
                    input=(
                        "The investigation is incomplete. Call the tools needed to collect: "
                        + ", ".join(missing)
                        + ". Do not generate the report yet."
                    ),
                    tools=dispatcher.definitions,
                    tool_choice="required",
                )
                continue
            return ensure_report_contract(response.output_text)

        tool_outputs: list[dict[str, str]] = []
        for call in calls:
            try:
                arguments = json.loads(call.arguments or "{}")
                result = dispatcher.call(call.name, arguments)
                payload = {"ok": True, "result": result}
            except (ValueError, TypeError, KeyError, BotoCoreError, ClientError) as exc:
                payload = {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:1_000],
                }
            tool_outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(payload, default=str),
                }
            )

        response = client.responses.create(
            model=model,
            instructions=SYSTEM_PROMPT,
            previous_response_id=response.id,
            input=tool_outputs,
            tools=dispatcher.definitions,
            tool_choice="auto",
        )

    raise RuntimeError(f"Agent exceeded {max_tool_rounds} tool-call rounds")


def evidence_report(evidence: dict[str, dict[str, Any]], target: AwsTarget) -> str:
    """Produce a deterministic evidence bundle for --collect-only operation."""

    return ensure_report_contract(
        "# AWS Incident Evidence Bundle\n\n"
        "## Executive summary\n\n"
        "Read-only evidence collection completed. OpenAI analysis was intentionally skipped.\n\n"
        "## Customer and system impact\n\n"
        "Not established from infrastructure evidence alone.\n\n"
        "## Timeline\n\n"
        f"- {datetime.now(timezone.utc).isoformat()} — Evidence bundle generated.\n\n"
        "## Confirmed root cause\n\n"
        "Not established; collect-only mode does not make causal claims.\n\n"
        "## Contributing factors\n\n"
        "See failure-pattern evidence below.\n\n"
        "## Mitigation and recovery\n\n"
        "No actions were performed or recommended in collect-only mode.\n\n"
        "## Evidence\n\n"
        f"Target: `{target.cluster}` / `{target.service}` / `{target.log_group}` in `{target.region}`.\n\n"
        "```json\n"
        + json.dumps(evidence, indent=2, default=str)
        + "\n```\n\n"
        "## Corrective actions\n\n"
        "- [P2] [Owner: TBD] Review the collected evidence and assign remediation.\n\n"
        "## Detection gaps\n\n"
        "Not assessed in collect-only mode.\n\n"
        "## Unverified hypotheses\n\n"
        "None generated in collect-only mode."
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Investigate one ECS service with read-only AWS calls and generate an RCA report."
    )
    parser.add_argument("--cluster", default=os.getenv("ECS_CLUSTER"))
    parser.add_argument("--service", default=os.getenv("ECS_SERVICE"))
    parser.add_argument("--log-group", default=os.getenv("CLOUDWATCH_LOG_GROUP"))
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1",
    )
    parser.add_argument("--profile", default=os.getenv("AWS_PROFILE"))
    parser.add_argument("--model", default=os.getenv("OPENAI_MODEL", "gpt-5.6"))
    parser.add_argument("--lookback-minutes", type=int, default=180)
    parser.add_argument("--log-limit", type=int, default=200)
    parser.add_argument("--max-tool-rounds", type=int, default=8)
    parser.add_argument("--incident-context")
    parser.add_argument(
        "--output",
        help="Report path. Defaults to incidents/incident-<UTC timestamp>.md; use - for stdout.",
    )
    parser.add_argument(
        "--collect-only",
        action="store_true",
        help="Collect AWS evidence without calling OpenAI.",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    missing = [name for name in ("cluster", "service", "log_group") if not getattr(args, name)]
    if missing:
        parser.error(
            "missing target values: "
            + ", ".join(f"--{name.replace('_', '-')}" for name in missing)
        )
    if not 1 <= args.lookback_minutes <= 10_080:
        parser.error("--lookback-minutes must be between 1 and 10080")
    if not 1 <= args.log_limit <= 500:
        parser.error("--log-limit must be between 1 and 500")
    if not 1 <= args.max_tool_rounds <= 20:
        parser.error("--max-tool-rounds must be between 1 and 20")


def _write_report(report: str, output: str | None) -> Path | None:
    if output == "-":
        print(report, end="")
        return None
    if output:
        path = Path(output).expanduser()
    else:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = Path(__file__).resolve().parent.parent / "incidents" / f"incident-{timestamp}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    return path.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)

    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    target = AwsTarget(
        cluster=args.cluster,
        service=args.service,
        log_group=args.log_group,
        region=args.region,
    )
    dispatcher = ToolDispatcher(
        ReadOnlyAwsTools(target, session=session),
        default_lookback_minutes=args.lookback_minutes,
        default_log_limit=args.log_limit,
    )

    try:
        if args.collect_only:
            report = evidence_report(dispatcher.collect_all(), target)
        else:
            report = run_agent(
                client=OpenAI(),
                model=args.model,
                dispatcher=dispatcher,
                max_tool_rounds=args.max_tool_rounds,
                request=investigation_request(
                    cluster=target.cluster,
                    service=target.service,
                    log_group=target.log_group,
                    region=target.region,
                    lookback_minutes=args.lookback_minutes,
                    incident_context=(
                        redact_sensitive_text(args.incident_context, max_length=4_000)
                        if args.incident_context
                        else None
                    ),
                ),
            )
        path = _write_report(report, args.output)
    except (NoCredentialsError, BotoCoreError, ClientError) as exc:
        print(f"AWS evidence collection failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Triage failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1

    if path:
        print(f"RCA report written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
