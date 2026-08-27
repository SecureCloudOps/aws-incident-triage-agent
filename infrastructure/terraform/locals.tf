data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  service_name = var.name_prefix

  valid_fargate_memory = {
    "256"  = [512, 1024, 2048]
    "512"  = [for size in range(1, 5) : size * 1024]
    "1024" = [for size in range(2, 9) : size * 1024]
    "2048" = [for size in range(4, 17) : size * 1024]
    "4096" = [for size in range(8, 31) : size * 1024]
  }

  public_subnets = {
    for index, cidr in var.public_subnet_cidrs : format("public-%02d", index + 1) => {
      availability_zone = data.aws_availability_zones.available.names[index]
      cidr_block        = cidr
    }
  }
}
