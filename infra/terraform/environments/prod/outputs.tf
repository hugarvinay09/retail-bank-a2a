output "cluster_name" { value = module.eks.cluster_name }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "documents_bucket" { value = aws_s3_bucket.documents.id }
output "application_role_arn" { value = aws_iam_role.app.arn }
output "github_deploy_role_arn" { value = aws_iam_role.github.arn }
output "secret_arn" { value = aws_secretsmanager_secret.application.arn }

