data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "triage_agent_read_only" {
  statement {
    sid    = "ReadTargetCluster"
    effect = "Allow"
    actions = [
      "ecs:DescribeClusters",
    ]
    resources = [
      aws_ecs_cluster.this.arn,
    ]
  }

  statement {
    sid    = "ReadTargetService"
    effect = "Allow"
    actions = [
      "ecs:DescribeServices",
    ]
    resources = [
      aws_ecs_service.service.id,
    ]
  }

  # ECS ListTasks does not support cluster/service ARNs in Resource. Restrict the required
  # wildcard resource with the supported ecs:cluster condition; code also fixes serviceName.
  statement {
    sid       = "ListTargetClusterTasks"
    effect    = "Allow"
    actions   = ["ecs:ListTasks"]
    resources = ["*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = [aws_ecs_cluster.this.arn]
    }
  }

  statement {
    sid    = "ReadTargetTasks"
    effect = "Allow"
    actions = [
      "ecs:DescribeTasks",
    ]
    resources = [
      "arn:aws:ecs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:task/${aws_ecs_cluster.this.name}/*",
    ]
  }

  statement {
    sid    = "ReadTargetLogs"
    effect = "Allow"
    actions = [
      "logs:FilterLogEvents",
    ]
    resources = [
      "${aws_cloudwatch_log_group.service.arn}:*",
    ]
  }
}

resource "aws_iam_policy" "triage_agent_read_only" {
  name        = "${local.service_name}-triage-agent-read-only"
  description = "Read-only ECS and CloudWatch Logs evidence access for the incident triage agent"
  policy      = data.aws_iam_policy_document.triage_agent_read_only.json

  tags = {
    Name = "${local.service_name}-triage-agent-read-only"
  }
}
