resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${local.service_name}-vpc"
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "${local.service_name}-igw"
  }
}

resource "aws_subnet" "public" {
  for_each = local.public_subnets

  vpc_id            = aws_vpc.this.id
  availability_zone = each.value.availability_zone
  cidr_block        = each.value.cidr_block

  tags = {
    Name = "${local.service_name}-${each.key}"
    Tier = "public"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "${local.service_name}-public"
  }
}

resource "aws_route_table_association" "public" {
  for_each = aws_subnet.public

  route_table_id = aws_route_table.public.id
  subnet_id      = each.value.id
}

resource "aws_security_group" "service" {
  name        = "${local.service_name}-service"
  description = "Network access for the ${local.service_name} Fargate tasks"
  vpc_id      = aws_vpc.this.id

  tags = {
    Name = "${local.service_name}-service"
  }
}

resource "aws_vpc_security_group_ingress_rule" "service" {
  for_each = var.allowed_ingress_cidrs

  security_group_id = aws_security_group.service.id
  description       = "FastAPI service access from ${each.value}"
  cidr_ipv4         = each.value
  from_port         = var.container_port
  ip_protocol       = "tcp"
  to_port           = var.container_port
}

resource "aws_vpc_security_group_egress_rule" "service" {
  security_group_id = aws_security_group.service.id
  description       = "Allow tasks to reach ECR, CloudWatch, and other AWS APIs"
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  ip_protocol       = "tcp"
  to_port           = 443
}
