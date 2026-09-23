resource "aws_ecs_cluster" "main" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "disabled"
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.name}"
  retention_in_days = 7
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# The agent's role: pulls the image, reads the secret, writes the logs.
resource "aws_iam_role" "execution" {
  name               = "${var.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "execution_secrets" {
  name = "read-secrets"
  role = aws_iam_role.execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.database_url.arn,
        aws_secretsmanager_secret.passphrase_hash.arn,
      ]
    }]
  })
}

# The application's own role. It needs nothing yet; it exists so that the day
# the service calls an AWS API, the grant has an obvious home that is not the
# execution role.
resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

locals {
  image = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
}

resource "aws_ecs_task_definition" "api" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  # Graviton: same image the laptop builds natively, ~20% cheaper to run.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64"
  }

  container_definitions = jsonencode([{
    name      = "api"
    image     = local.image
    essential = true

    portMappings = [{
      containerPort = 8000
      protocol      = "tcp"
    }]

    # The browser reaches the edge over HTTPS, so the session cookie is
    # marked Secure even though CloudFront talks to the load balancer in plain
    # HTTP inside the VPC.
    environment = [{
      name  = "SIFT_COOKIE_SECURE"
      value = "true"
    }]

    secrets = [
      {
        name      = "SIFT_DATABASE_URL"
        valueFrom = aws_secretsmanager_secret.database_url.arn
      },
      {
        name      = "SIFT_PASSPHRASE_HASH"
        valueFrom = aws_secretsmanager_secret.passphrase_hash.arn
      },
    ]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])

  # CI registers new revisions; Terraform should not fight it over the tag.
  lifecycle {
    ignore_changes = [container_definitions]
  }
}

resource "aws_lb" "main" {
  name               = var.name
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]
}

resource "aws_lb_target_group" "api" {
  name        = var.name
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  # /health answers 200 with a body saying whether the database is reachable,
  # so this checks that the process serves, not that the system is well.
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 10
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

resource "aws_ecs_service" "api" {
  name            = var.name
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.public[*].id
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  health_check_grace_period_seconds = 30

  # A deployment that never reaches a healthy target rolls itself back rather
  # than leaving the service half-replaced.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  # The secret's value is derived from the database endpoint, so it lands late
  # in a fresh apply. Without this the service can start against a secret that
  # has no version yet, and the circuit breaker retires the deployment.
  depends_on = [
    aws_lb_listener.http,
    aws_secretsmanager_secret_version.database_url,
    aws_secretsmanager_secret_version.passphrase_hash,
  ]

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }
}
