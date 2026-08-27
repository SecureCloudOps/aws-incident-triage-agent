"""Bounded, read-only AWS evidence collectors for the triage agent.

The module deliberately exposes no AWS mutating operation.  It also keeps the
raw boto3 clients behind a small interface so the collectors can be unit tested
with botocore stubs.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import boto3
from botocore.config import Config

ERROR_FILTER_PATTERN = "?ERROR ?Exception ?Traceback ?FATAL ?CRITICAL ?500"
MAX_LOG_EVENTS = 500
MAX_TASKS_PER_STATE = 100

_SECRET_PATTERN = re.compile(
    r"(?i)(authorization|api[-_]?key|password|passwd|secret|token)"
    r"(\s*[=:]\s*|\"\s*:\s*\")[^\s,}\"]+"
)
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
_AWS_ACCESS_KEY_PATTERN = re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")
_OPENAI_KEY_PATTERN = re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")
_PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_IP_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_LONG_NUMBER_PATTERN = re.compile(r"\b\d{4,}\b")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def redact_sensitive_text(value: str, *, max_length: int = 4_000) -> str:
    """Best-effort redaction before untrusted evidence crosses the model boundary."""

    value = _BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", value)
    value = _SECRET_PATTERN.sub(r"\1\2[REDACTED]", value)
    value = _AWS_ACCESS_KEY_PATTERN.sub("[REDACTED_AWS_ACCESS_KEY]", value)
    value = _OPENAI_KEY_PATTERN.sub("[REDACTED_OPENAI_KEY]", value)
    value = _PRIVATE_KEY_PATTERN.sub("[REDACTED_PRIVATE_KEY]", value)
    if len(value) > max_length:
        return value[:max_length] + "...[truncated]"
    return value


def _json_message(message: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _looks_like_error(message: str) -> bool:
    parsed = _json_message(message)
    if parsed:
        level = str(parsed.get("level", "")).upper()
        try:
            status_code = int(parsed.get("status_code", 0))
        except (TypeError, ValueError):
            status_code = 0
        if level in {"ERROR", "FATAL", "CRITICAL"} or status_code >= 500:
            return True
    lowered = message.lower()
    return any(
        token in lowered
        for token in ("error", "exception", "traceback", "fatal", "critical", "status 500")
    )


@dataclass(frozen=True)
class AwsTarget:
    cluster: str
    service: str
    log_group: str
    region: str


class ReadOnlyAwsTools:
    """Collect ECS and CloudWatch Logs evidence without mutation APIs."""

    def __init__(
        self,
        target: AwsTarget,
        *,
        session: boto3.Session | None = None,
        ecs_client: Any | None = None,
        logs_client: Any | None = None,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.target = target
        self._now = now
        if ecs_client is None or logs_client is None:
            session = session or boto3.Session(region_name=target.region)
            config = Config(retries={"max_attempts": 4, "mode": "standard"})
            ecs_client = ecs_client or session.client("ecs", config=config)
            logs_client = logs_client or session.client("logs", config=config)
        self.ecs = ecs_client
        self.logs = logs_client

    def get_ecs_service_status(self) -> dict[str, Any]:
        """Return service, deployment, event, and task health for one ECS service."""

        cluster_response = self.ecs.describe_clusters(clusters=[self.target.cluster])
        service_response = self.ecs.describe_services(
            cluster=self.target.cluster,
            services=[self.target.service],
        )
        failures = service_response.get("failures", [])
        services = service_response.get("services", [])
        if failures or not services:
            detail = failures or [{"reason": "MISSING", "arn": self.target.service}]
            return {
                "collected_at": self._now().isoformat(),
                "target": self._target_dict(),
                "status": "NOT_FOUND",
                "failures": detail,
            }

        service = services[0]
        tasks: list[dict[str, Any]] = []
        for desired_status in ("RUNNING", "PENDING", "STOPPED"):
            arns = self._list_task_arns(desired_status)
            for start in range(0, len(arns), 100):
                described = self.ecs.describe_tasks(
                    cluster=self.target.cluster,
                    tasks=arns[start : start + 100],
                )
                tasks.extend(
                    self._task_summary(task, desired_status)
                    for task in described.get("tasks", [])
                )

        deployments = [
            {
                key: _iso(deployment.get(key))
                for key in (
                    "id",
                    "status",
                    "taskDefinition",
                    "desiredCount",
                    "pendingCount",
                    "runningCount",
                    "failedTasks",
                    "rolloutState",
                    "rolloutStateReason",
                    "createdAt",
                    "updatedAt",
                )
                if deployment.get(key) is not None
            }
            for deployment in service.get("deployments", [])
        ]
        events = [
            {
                "id": event.get("id"),
                "createdAt": _iso(event.get("createdAt")),
                "message": redact_sensitive_text(
                    str(event.get("message", "")), max_length=1_000
                ),
            }
            for event in service.get("events", [])[:20]
        ]
        clusters = cluster_response.get("clusters", [])
        cluster = clusters[0] if clusters else {}

        return {
            "collected_at": self._now().isoformat(),
            "target": self._target_dict(),
            "cluster": {
                "status": cluster.get("status"),
                "runningTasksCount": cluster.get("runningTasksCount"),
                "pendingTasksCount": cluster.get("pendingTasksCount"),
                "activeServicesCount": cluster.get("activeServicesCount"),
            },
            "service": {
                key: service.get(key)
                for key in (
                    "serviceArn",
                    "serviceName",
                    "status",
                    "desiredCount",
                    "runningCount",
                    "pendingCount",
                    "launchType",
                    "platformVersion",
                    "healthCheckGracePeriodSeconds",
                )
                if service.get(key) is not None
            },
            "deployments": deployments,
            "recent_events": events,
            "tasks": tasks,
        }

    def get_recent_cloudwatch_errors(
        self,
        *,
        lookback_minutes: int = 180,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return recent error-like events from one configured log group."""

        if not 1 <= lookback_minutes <= 10_080:
            raise ValueError("lookback_minutes must be between 1 and 10080")
        if not 1 <= limit <= MAX_LOG_EVENTS:
            raise ValueError(f"limit must be between 1 and {MAX_LOG_EVENTS}")

        ended_at = self._now()
        started_at = ended_at - timedelta(minutes=lookback_minutes)
        events: list[dict[str, Any]] = []
        next_token: str | None = None
        pages = 0

        while len(events) < limit and pages < 10:
            request: dict[str, Any] = {
                "logGroupName": self.target.log_group,
                "startTime": int(started_at.timestamp() * 1_000),
                "endTime": int(ended_at.timestamp() * 1_000),
                "filterPattern": ERROR_FILTER_PATTERN,
                "limit": min(10_000, max(100, limit - len(events))),
                "interleaved": True,
            }
            if next_token:
                request["nextToken"] = next_token
            response = self.logs.filter_log_events(**request)
            pages += 1
            for event in response.get("events", []):
                message = redact_sensitive_text(str(event.get("message", "")))
                if not _looks_like_error(message):
                    continue
                timestamp = datetime.fromtimestamp(
                    event.get("timestamp", 0) / 1_000,
                    tz=timezone.utc,
                ).isoformat()
                parsed = _json_message(message)
                events.append(
                    {
                        "event_id": event.get("eventId"),
                        "timestamp": timestamp,
                        "log_stream": event.get("logStreamName"),
                        "message": parsed or message,
                    }
                )
                if len(events) >= limit:
                    break
            new_token = response.get("nextToken")
            if not new_token or new_token == next_token:
                break
            next_token = new_token

        events.sort(key=lambda item: item["timestamp"])
        return {
            "collected_at": ended_at.isoformat(),
            "target": self._target_dict(),
            "window": {
                "start": started_at.isoformat(),
                "end": ended_at.isoformat(),
                "lookback_minutes": lookback_minutes,
            },
            "filter_pattern": ERROR_FILTER_PATTERN,
            "matched_event_count": len(events),
            "truncated": len(events) >= limit or pages >= 10,
            "events": events,
        }

    def _list_task_arns(self, desired_status: str) -> list[str]:
        arns: list[str] = []
        next_token: str | None = None
        while len(arns) < MAX_TASKS_PER_STATE:
            request: dict[str, Any] = {
                "cluster": self.target.cluster,
                "serviceName": self.target.service,
                "desiredStatus": desired_status,
                "maxResults": min(100, MAX_TASKS_PER_STATE - len(arns)),
            }
            if next_token:
                request["nextToken"] = next_token
            response = self.ecs.list_tasks(**request)
            arns.extend(response.get("taskArns", []))
            new_token = response.get("nextToken")
            if not new_token or new_token == next_token:
                break
            next_token = new_token
        return arns[:MAX_TASKS_PER_STATE]

    @staticmethod
    def _task_summary(task: dict[str, Any], queried_status: str) -> dict[str, Any]:
        return {
            key: _iso(task.get(key))
            for key in (
                "taskArn",
                "taskDefinitionArn",
                "availabilityZone",
                "connectivity",
                "connectivityAt",
                "createdAt",
                "startedAt",
                "stoppingAt",
                "stoppedAt",
                "desiredStatus",
                "lastStatus",
                "healthStatus",
                "stopCode",
                "stoppedReason",
                "launchType",
                "platformVersion",
                "cpu",
                "memory",
            )
            if task.get(key) is not None
        } | {
            "queried_status": queried_status,
            "containers": [
                {
                    key: container.get(key)
                    for key in (
                        "name",
                        "image",
                        "imageDigest",
                        "lastStatus",
                        "healthStatus",
                        "exitCode",
                        "reason",
                    )
                    if container.get(key) is not None
                }
                for container in task.get("containers", [])
            ],
        }

    def _target_dict(self) -> dict[str, str]:
        return {
            "cluster": self.target.cluster,
            "service": self.target.service,
            "log_group": self.target.log_group,
            "region": self.target.region,
        }


def analyze_failure_patterns(
    ecs_status: dict[str, Any],
    log_errors: dict[str, Any],
) -> dict[str, Any]:
    """Rank recurring failure signals without asking the model to invent counts."""

    signals: dict[str, list[dict[str, Any]]] = defaultdict(list)

    def add_signal(category: str, source: str, timestamp: Any, detail: str) -> None:
        signals[category].append(
            {
                "source": source,
                "timestamp": _iso(timestamp),
                "detail": redact_sensitive_text(detail, max_length=1_000),
            }
        )

    searchable: list[tuple[str, Any, str]] = []
    for event in ecs_status.get("recent_events", []):
        searchable.append(("ecs_event", event.get("createdAt"), str(event.get("message", ""))))
    for task in ecs_status.get("tasks", []):
        if task.get("stoppedReason"):
            searchable.append(("ecs_task", task.get("stoppedAt"), str(task["stoppedReason"])))
        for container in task.get("containers", []):
            reason = str(container.get("reason", ""))
            exit_code = container.get("exitCode")
            detail = f"container={container.get('name')} exit_code={exit_code} reason={reason}"
            if exit_code not in (None, 0) or reason:
                searchable.append(("ecs_container", task.get("stoppedAt"), detail))

    for event in log_errors.get("events", []):
        message = event.get("message", "")
        detail = json.dumps(message, sort_keys=True, default=str) if isinstance(message, dict) else str(message)
        searchable.append(("cloudwatch_log", event.get("timestamp"), detail))

    classifiers = {
        "out_of_memory": ("outofmemory", "out of memory", "exit_code=137", "oomkilled"),
        "image_pull_failure": ("cannotpullcontainererror", "image pull", "manifest unknown"),
        "container_start_failure": ("resourceinitializationerror", "cannotstartcontainererror", "failed to start"),
        "health_check_failure": ("health check", "unhealthy", "healthcheck"),
        "access_denied": ("accessdenied", "access denied", "not authorized"),
        "throttling": ("throttl", "rate exceeded", "too many requests"),
        "timeout_or_connectivity": ("timed out", "timeout", "connection refused", "connection reset", "dns"),
        "application_5xx": ("status_code\": 5", "status 5", "simulated application failure"),
        "exception_or_traceback": ("exception", "traceback", "request failed"),
    }

    fingerprints: Counter[str] = Counter()
    fingerprint_examples: dict[str, str] = {}
    for source, timestamp, detail in searchable:
        lowered = detail.lower()
        matched = False
        for category, needles in classifiers.items():
            if any(needle in lowered for needle in needles):
                add_signal(category, source, timestamp, detail)
                matched = True
        if not matched and source in {"cloudwatch_log", "ecs_task", "ecs_container"}:
            add_signal("unclassified_failure", source, timestamp, detail)

        fingerprint = _fingerprint(detail)
        fingerprints[fingerprint] += 1
        fingerprint_examples.setdefault(fingerprint, detail[:500])

    patterns = []
    for category, evidence in signals.items():
        sources = sorted({item["source"] for item in evidence})
        patterns.append(
            {
                "category": category,
                "count": len(evidence),
                "sources": sources,
                "confidence": "high" if len(sources) > 1 else "medium",
                "first_seen": min(
                    (str(item["timestamp"]) for item in evidence if item["timestamp"]),
                    default=None,
                ),
                "last_seen": max(
                    (str(item["timestamp"]) for item in evidence if item["timestamp"]),
                    default=None,
                ),
                "examples": evidence[:3],
            }
        )
    patterns.sort(key=lambda item: (-item["count"], item["category"]))

    recurring = [
        {
            "fingerprint": digest,
            "count": count,
            "example": redact_sensitive_text(fingerprint_examples[digest], max_length=500),
        }
        for digest, count in fingerprints.most_common(10)
        if count > 1
    ]
    return {
        "analyzed_at": _utc_now().isoformat(),
        "evidence_items_analyzed": len(searchable),
        "patterns": patterns,
        "recurring_fingerprints": recurring,
        "limitations": [
            "Pattern matches are correlations, not proof of root cause.",
            "The configured lookback window and event limits can omit older or high-volume evidence.",
        ],
    }


def _fingerprint(detail: str) -> str:
    normalized = detail.lower()
    normalized = _UUID_PATTERN.sub("<uuid>", normalized)
    normalized = _IP_PATTERN.sub("<ip>", normalized)
    normalized = _LONG_NUMBER_PATTERN.sub("<n>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class ToolDispatcher:
    """Map OpenAI function calls to the configured collectors and cache evidence."""

    definitions = [
        {
            "type": "function",
            "name": "get_ecs_service_status",
            "description": (
                "Get the configured ECS cluster, service, deployments, recent service events, "
                "and running/pending/stopped task status. Read-only."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            "strict": True,
        },
        {
            "type": "function",
            "name": "get_recent_cloudwatch_errors",
            "description": (
                "Get bounded, recent error-like events from the configured CloudWatch log group. "
                "Read-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lookback_minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10080,
                    },
                    "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LOG_EVENTS},
                },
                "required": ["lookback_minutes", "limit"],
                "additionalProperties": False,
            },
            "strict": True,
        },
        {
            "type": "function",
            "name": "analyze_failure_patterns",
            "description": (
                "Analyze the ECS and CloudWatch evidence already collected in this run and rank "
                "recurring failure patterns. Collects missing evidence with configured defaults."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            "strict": True,
        },
    ]

    def __init__(
        self,
        aws_tools: ReadOnlyAwsTools,
        *,
        default_lookback_minutes: int = 180,
        default_log_limit: int = 200,
    ) -> None:
        self.aws_tools = aws_tools
        self.default_lookback_minutes = default_lookback_minutes
        self.default_log_limit = default_log_limit
        self.evidence: dict[str, dict[str, Any]] = {}

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "get_ecs_service_status":
            result = self.aws_tools.get_ecs_service_status()
            self.evidence["ecs_status"] = result
            return result
        if name == "get_recent_cloudwatch_errors":
            result = self.aws_tools.get_recent_cloudwatch_errors(
                lookback_minutes=int(arguments["lookback_minutes"]),
                limit=int(arguments["limit"]),
            )
            self.evidence["log_errors"] = result
            return result
        if name == "analyze_failure_patterns":
            ecs_status = self.evidence.get("ecs_status")
            if ecs_status is None:
                ecs_status = self.call("get_ecs_service_status", {})
            log_errors = self.evidence.get("log_errors")
            if log_errors is None:
                log_errors = self.call(
                    "get_recent_cloudwatch_errors",
                    {
                        "lookback_minutes": self.default_lookback_minutes,
                        "limit": self.default_log_limit,
                    },
                )
            result = analyze_failure_patterns(ecs_status, log_errors)
            self.evidence["failure_patterns"] = result
            return result
        raise ValueError(f"Unknown tool: {name}")

    def collect_all(self) -> dict[str, dict[str, Any]]:
        self.call("get_ecs_service_status", {})
        self.call(
            "get_recent_cloudwatch_errors",
            {
                "lookback_minutes": self.default_lookback_minutes,
                "limit": self.default_log_limit,
            },
        )
        self.call("analyze_failure_patterns", {})
        return self.evidence
