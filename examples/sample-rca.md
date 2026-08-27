# Sanitized sample RCA

> This is a fictionalized example derived from the demo failure mode. Account IDs, ARNs, task IDs,
> event IDs, timestamps, and people are synthetic. It is safe for documentation and must not be used
> as evidence for a real incident.

## Executive summary

From 14:02 to 14:09 UTC, the `checkout-demo` ECS service failed to place replacement tasks because
the deployed container manifest did not include `linux/amd64`. Six ECS service events reported the
same `CannotPullContainerError`. A later deployment using a compatible digest reached steady state
at 14:12 UTC. The agent made no changes.

Two controlled `/crash` requests returned HTTP 500 after recovery. They are separate demo events and
did not cause the placement failure.

## Customer and system impact

- Six replacement-task launches failed during a seven-minute deployment window.
- Availability impact is unconfirmed because no load-balancer or request-rate metrics were queried.
- At evidence collection time, desired/running/pending task counts were `1/1/0`.

## Timeline

- **14:02:11 UTC** — First ECS `CannotPullContainerError` reports no `linux/amd64` descriptor.
- **14:02–14:09 UTC** — Five more task-placement attempts fail with the same reason.
- **14:10:43 UTC** — ECS starts task `task/example-running-01` with a compatible image digest.
- **14:12:06 UTC** — Deployment `ecs-svc/example-02` reaches steady state.
- **14:18:20 UTC** — Controlled `GET /crash` returns HTTP 500 and logs `DemoFailure`.
- **14:20:00 UTC** — Read-only evidence collection completes.

## Confirmed root cause

The task-placement failures were caused by an image architecture mismatch. ECS explicitly reported
that the referenced manifest had no descriptor for the configured `linux/amd64` runtime.

The upstream reason the incompatible image was selected is not confirmed because build provenance,
the earlier task-definition diff, and deployment audit records were outside the collector scope.

## Contributing factors

- Image architecture was not validated before deployment.
- The demo service desired count was one, limiting redundancy.
- No deployment gate compared the image manifest with the task runtime platform.

## Mitigation and recovery

No mitigation was executed by the agent. ECS later reached steady state with a compatible immutable
image digest. The lowest-risk operator action is to verify that digest and preserve the healthy task
while reviewing the release pipeline.

## Evidence

- Target: `example-cluster` / `checkout-demo`, `us-east-1`.
- ECS event IDs: `event-example-01` through `event-example-06`.
- Repeated reason: `CannotPullContainerError: image manifest does not contain descriptor matching
  platform linux/amd64`.
- Current deployment: `COMPLETED`; desired/running/pending `1/1/0`.
- CloudWatch event `log-example-01`: controlled `/crash`, HTTP 500, `DemoFailure`.
- Query window: 180 minutes; 12 evidence items; `truncated: false`.

## Corrective actions

- **P0 — Owner: Release Engineering** — Fail CI when the image manifest lacks the task platform.
- **P1 — Owner: Service Team** — Deploy only reviewed immutable image digests.
- **P1 — Owner: Observability** — Alert on `CannotPullContainerError` and desired/running mismatch.
- **P2 — Owner: Reliability** — Review whether desired count one meets demo availability goals.

## Detection gaps

- No load-balancer, request, latency, or customer-impact metrics were collected.
- No CloudTrail deployment actor or task-definition diff was collected.
- No registry manifest or build provenance was collected.
- Evidence outside the requested window was not searched.

## Unverified hypotheses

1. **A developer published a single-architecture ARM image.** Compatible with the ECS error, but
   unverified without registry/build evidence.
2. **The later deployment changed only the image digest.** Compatible with recovery timing, but
   unverified without a task-definition diff.
3. **Customers experienced an outage.** Possible with one desired task, but unsupported without
   traffic or target-health evidence.

