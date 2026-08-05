data "aws_availability_zones" "available" { state = "available" }
data "aws_caller_identity" "current" {}

locals {
  name = "${var.name}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 3)
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.6.1"

  name = local.name
  cidr = var.vpc_cidr
  azs  = local.azs
  private_subnets  = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, index)]
  database_subnets = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 4, index + 8)]
  public_subnets   = [for index, _ in local.azs : cidrsubnet(var.vpc_cidr, 8, index + 48)]

  enable_nat_gateway = true
  one_nat_gateway_per_az = true
  single_nat_gateway = false
  enable_dns_hostnames = true
  enable_dns_support = true
  create_database_subnet_group = true
  enable_flow_log = true
  create_flow_log_cloudwatch_log_group = true
  create_flow_log_cloudwatch_iam_role = true

  private_subnet_tags = {
    "kubernetes.io/role/internal-elb" = "1"
  }
  public_subnet_tags = {
    "kubernetes.io/role/elb" = "1"
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "21.24.1"

  name               = local.name
  kubernetes_version = var.cluster_version
  endpoint_private_access = true
  endpoint_public_access  = false
  enable_irsa = true
  enable_cluster_creator_admin_permissions = true
  authentication_mode = "API"
  deletion_protection = true
  upgrade_policy = { support_type = "STANDARD" }

  access_entries = {
    github_deployer = {
      principal_arn = aws_iam_role.github.arn
      policy_associations = {
        namespace_admin = {
          policy_arn = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSAdminPolicy"
          access_scope = {
            type       = "namespace"
            namespaces = ["retail-bank-a2a"]
          }
        }
      }
    }
  }

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets
  control_plane_subnet_ids = module.vpc.private_subnets

  enabled_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]
  cloudwatch_log_group_retention_in_days = 365
  encryption_config = { provider_key_arn = aws_kms_key.platform.arn, resources = ["secrets"] }

  addons = {
    coredns = { most_recent = true }
    kube-proxy = { most_recent = true }
    vpc-cni = { most_recent = true, before_compute = true }
    aws-ebs-csi-driver = { most_recent = true }
  }

  eks_managed_node_groups = {
    system = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m7i.large", "m7a.large"]
      min_size       = 3
      max_size       = 12
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
      labels = { workload = "system" }
      update_config = { max_unavailable_percentage = 25 }
    }
    agents = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = ["m7i.xlarge", "m7a.xlarge"]
      min_size       = 3
      max_size       = 30
      desired_size   = 3
      capacity_type  = "ON_DEMAND"
      labels = { workload = "agents" }
      update_config = { max_unavailable_percentage = 25 }
    }
  }
}

resource "aws_kms_key" "platform" {
  description             = "${local.name} envelope encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}
resource "aws_kms_alias" "platform" {
  name          = "alias/${local.name}"
  target_key_id = aws_kms_key.platform.key_id
}

resource "aws_ecr_repository" "app" {
  name                 = var.name
  image_tag_mutability = "IMMUTABLE"
  encryption_configuration {
    encryption_type = "KMS"
    kms_key          = aws_kms_key.platform.arn
  }
  image_scanning_configuration {
    scan_on_push = true
  }
}
resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({ rules = [{
    rulePriority = 1
    description  = "Retain the latest 100 release images"
    selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 100 }
    action       = { type = "expire" }
  }] })
}

resource "aws_s3_bucket" "documents" {
  bucket        = "${local.name}-documents-${data.aws_caller_identity.current.account_id}"
  force_destroy = false
  object_lock_enabled = true
}
resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.platform.arn
    }
  }
}
resource "aws_s3_bucket_public_access_block" "documents" {
  bucket = aws_s3_bucket.documents.id
  block_public_acls = true
  block_public_policy = true
  ignore_public_acls = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_object_lock_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 30
    }
  }
}

resource "random_password" "db" {
  length           = 40
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}
resource "aws_security_group" "data" {
  name_prefix = "${local.name}-data-"
  vpc_id      = module.vpc.vpc_id
  ingress {
    description     = "PostgreSQL from EKS nodes"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  ingress {
    description     = "Valkey from EKS nodes"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [module.eks.node_security_group_id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_rds_cluster" "postgres" {
  cluster_identifier = "${local.name}-postgres"
  engine              = "aurora-postgresql"
  engine_version      = var.aurora_engine_version
  database_name       = var.db_name
  master_username     = var.db_master_username
  master_password     = random_password.db.result
  db_subnet_group_name   = module.vpc.database_subnet_group_name
  vpc_security_group_ids = [aws_security_group.data.id]
  storage_encrypted   = true
  kms_key_id          = aws_kms_key.platform.arn
  backup_retention_period = 35
  preferred_backup_window = "18:00-19:00"
  deletion_protection = true
  skip_final_snapshot = false
  final_snapshot_identifier = "${local.name}-final"
  enabled_cloudwatch_logs_exports = ["postgresql"]
  serverlessv2_scaling_configuration {
    min_capacity = 2
    max_capacity = 32
  }
}
resource "aws_rds_cluster_instance" "postgres" {
  count              = 2
  identifier         = "${local.name}-postgres-${count.index}"
  cluster_identifier = aws_rds_cluster.postgres.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.postgres.engine
  engine_version     = aws_rds_cluster.postgres.engine_version
  performance_insights_enabled = true
  performance_insights_kms_key_id = aws_kms_key.platform.arn
  monitoring_interval = 60
  monitoring_role_arn = aws_iam_role.rds_monitoring.arn
}

data "aws_iam_policy_document" "rds_monitoring_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["monitoring.rds.amazonaws.com"]
    }
  }
}
resource "aws_iam_role" "rds_monitoring" {
  name               = "${local.name}-rds-monitoring"
  assume_role_policy = data.aws_iam_policy_document.rds_monitoring_assume.json
}
resource "aws_iam_role_policy_attachment" "rds_monitoring" {
  role       = aws_iam_role.rds_monitoring.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonRDSEnhancedMonitoringRole"
}

resource "aws_elasticache_subnet_group" "cache" {
  name       = local.name
  subnet_ids = module.vpc.database_subnets
}
resource "aws_elasticache_replication_group" "cache" {
  replication_group_id = "${local.name}-cache"
  description          = "Agent rate limits and ephemeral coordination"
  engine               = "valkey"
  engine_version       = var.valkey_engine_version
  node_type            = "cache.r7g.large"
  port                 = 6379
  parameter_group_name = "default.valkey8"
  subnet_group_name    = aws_elasticache_subnet_group.cache.name
  security_group_ids   = [aws_security_group.data.id]
  num_cache_clusters   = 3
  automatic_failover_enabled = true
  multi_az_enabled     = true
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  kms_key_id            = aws_kms_key.platform.arn
  snapshot_retention_limit = 7
  apply_immediately = false
}

resource "aws_secretsmanager_secret" "application" {
  name       = "/${var.environment}/${var.name}"
  kms_key_id = aws_kms_key.platform.arn
  recovery_window_in_days = 30
}
resource "aws_secretsmanager_secret_version" "application" {
  secret_id = aws_secretsmanager_secret.application.id
  secret_string = jsonencode({
    DATABASE_URL = "postgresql+asyncpg://${var.db_master_username}:${urlencode(random_password.db.result)}@${aws_rds_cluster.postgres.endpoint}:5432/${var.db_name}"
    REDIS_URL    = "rediss://${aws_elasticache_replication_group.cache.primary_endpoint_address}:6379/0"
    OPENAI_API_KEY = "REPLACE_IN_SECRETS_MANAGER"
    COHERE_API_KEY = "REPLACE_IN_SECRETS_MANAGER"
    PINECONE_API_KEY = "REPLACE_IN_SECRETS_MANAGER"
    BANK_API_TOKEN = "REPLACE_IN_SECRETS_MANAGER"
    SAFETY_HMAC_KEY = random_password.safety.result
  })
  lifecycle { ignore_changes = [secret_string] }
}
resource "random_password" "safety" {
  length  = 64
  special = false
}
