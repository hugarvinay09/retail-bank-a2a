# Step-by-step implementation guide

This is the execution order for adapting the repository to a retail bank. Complete each exit
criterion before moving to the next environment. Commands assume Bash; on Windows, use WSL2 or a
controlled Linux build runner for Docker, Terraform, Helm, and Kubernetes work.

## Phase 0 — Assign ownership and constraints

Create accountable owners for product, retail payments, identity, fraud/AML, compliance, privacy,
model risk, cloud platform, SRE, security testing, and data governance. Record:

- Allowed use cases and prohibited decisions.
- Countries, customer segments, languages, currencies, products, and accessibility requirements.
- Data classes permitted at OpenAI, Pinecone, and Cohere; retention and region requirements.
- Transaction limits, approval semantics, sanctions/AML/fraud requirements, and dispute handling.
- Availability, latency, RTO/RPO, audit retention, and incident escalation requirements.

Exit: signed scope and data-flow approval. Begin with knowledge and masked balances; keep payment
execution feature-disabled until the final go-live phase.

## Phase 1 — Create the engineering baseline

```bash
git init
git add .
git commit -m "Initial retail bank agent platform"
uv python pin 3.12
uv lock
uv sync --all-extras --frozen
uv run ruff check .
uv run mypy src
uv run pytest -m "not integration and not live"
```

Create `main`, protect it, require pull requests, two bank reviewers, CI, signed commits if mandated,
no force push, no branch deletion, secret scanning, and CODEOWNERS for `domain`, `services/payments.py`,
`infra`, `deploy`, prompts, and evals. Pin third-party Actions to reviewed commit SHAs in the bank fork.

Exit: a clean reproducible build and mandatory review gates.

## Phase 2 — Configure model providers

Create separate OpenAI, Pinecone, and Cohere projects for dev/staging/prod with least-privilege keys,
budgets, alerts, and no developer-shared credentials. Confirm contractual data usage, storage, region,
abuse monitoring, and incident-notification terms.

The defaults are:

| Purpose | Default | Reason |
|---|---|---|
| Generation/routing | `gpt-5.6-terra`, low reasoning | Cost/quality balance and low-latency starting point |
| Quality-first exception eval | `gpt-5.6-sol` | Frontier capability; promote only with measured gain |
| Embedding | `text-embedding-3-large` | High-quality semantic retrieval, dimension 3072 |
| Vector index | Pinecone cosine, dimension 3072 | Matches embedding output |
| Reranker | Cohere `rerank-v3.5` | Cross-encoder relevance after metadata-filtered retrieval |

Never switch model aliases in production without a frozen-snapshot evaluation if the bank requires
change control. Capture model, prompt image version, latency, tokens, and decision codes in telemetry
without storing raw customer content.

Exit: provider risk approval, project isolation, spend limits, and synthetic connectivity test.

## Phase 3 — Build the approved knowledge supply chain

1. Provision the S3 document bucket with KMS, versioning, public-access block, access logging, and
   Object Lock (Terraform includes the base controls).
2. Create `incoming/`, `quarantine/`, `approved/`, and `revoked/` logical prefixes.
3. Build a maker-checker workflow outside this service: malware scan, OCR quality, document owner,
   effective/expiry date, jurisdiction, segment, policy version, and approval signatures.
4. Only the publication role may copy an artifact into `approved/`.
5. Create Pinecone index `retail-bank-knowledge`, dimension 3072, cosine metric.
6. Use separate namespaces for releases, e.g. `policies-2026-08-01`; switch the read alias/config only
   after ingestion and evals. The default `approved-policies` is suitable for local testing.

```bash
aws s3 cp synthetic-approved-policy.pdf \
  s3://YOUR_BUCKET/approved/synthetic-approved-policy.pdf
PINECONE_NAMESPACE=policies-2026-08-01 \
  uv run bank-agent-ingest --prefix approved/ --segment all
```

Validate retrieval with at least 200 bank-owned questions: recall@20, NDCG@6, reranker lift,
citation page correctness, no cross-segment retrieval, stale/revoked absence, and injection-bearing
document refusal.

Exit: approved documents are versioned and recall/citation targets pass.

## Phase 4 — Replace the banking sandbox adapters

Obtain versioned OpenAPI contracts and mTLS/service-auth requirements for:

- `GET /customers/{customer}/accounts/{account}` returning masked data only.
- `GET /customers/{customer}/beneficiaries/{beneficiary}`.
- `POST /customers/{customer}/payments` accepting an idempotency key.
- `GET /payments/by-idempotency-key/{key}` for reconciliation.
- Real-time fraud/AML/sanctions decision service.

Modify only `providers/bank_api.py` (or add a new adapter implementing `BankGateway`); do not leak
provider DTOs into domain or graph code. Enforce customer/account entitlements at the downstream bank
API even though the agent layer already checks claims. Add contract tests against the certified
sandbox, including 401/403/404/409/422/429/5xx, timeouts, connection resets, duplicate keys, and
accepted-but-response-lost outcomes.

Replace `AgentNodes.fraud` with the real fraud client. Model output must never set the fraud or AML
decision. Version every policy response.

Exit: bank security review and sandbox contract suite pass; reconciliation lookup exists.

## Phase 5 — Integrate identity and step-up authorization

Map the bank IdP token to:

```json
{
  "sub": "stable-user-subject",
  "customer_id": "opaque-customer-id",
  "accounts": ["opaque-account-id"],
  "scope": "assistant:use accounts:read payments:create payments:approve",
  "step_up_verified": true,
  "iat": 0,
  "exp": 0,
  "aud": "retail-bank-a2a",
  "iss": "approved-issuer"
}
```

Use short-lived access tokens. Step-up approval must be recent, transaction-bound where supported,
and protected against token replay. Add `auth_time`, device/session binding, and transaction-signing
claims to `AuthContext` according to bank policy. Validate JWKS rotation, issuer, audience, algorithm,
expiry, not-before, revocation, customer status, and account entitlements.

Never enable `AUTH_DISABLED` outside local mode; startup explicitly rejects it in production.

Exit: identity threat model, negative token tests, and step-up user journey pass.

## Phase 6 — Bootstrap Terraform state

Create the Terraform state bucket separately with versioning, KMS, public-access block, and restricted
roles. Copy and edit the examples:

```bash
cd infra/terraform/environments/prod
cp backend.hcl.example backend.hcl
cp prod.tfvars.example prod.tfvars
terraform init -backend-config=backend.hcl
terraform fmt -check -recursive
terraform validate
terraform plan -var-file=prod.tfvars -out=tfplan
terraform show -json tfplan > tfplan.json
```

Run policy-as-code and human approval on `tfplan`. Apply through a protected infrastructure pipeline,
not a workstation. Before plan, confirm Aurora and Valkey versions in the target region:

```bash
aws rds describe-db-engine-versions --engine aurora-postgresql \
  --query 'DBEngineVersions[].EngineVersion' --output text
aws elasticache describe-cache-engine-versions --engine valkey \
  --query 'CacheEngineVersions[].EngineVersion' --output text
```

The baseline creates a three-AZ VPC, private EKS 1.36, ECR, KMS, Object-Locked S3, Aurora
PostgreSQL, ElastiCache Valkey, a secret shell, app workload identity, and GitHub OIDC deploy role.
Review NAT cost and replace broad data-security-group egress with VPC endpoints and explicit routes.

Exit: approved plan, no public cluster endpoint, no plaintext secrets, restore test scheduled.

## Phase 7 — Install EKS platform dependencies

From an approved runner inside the VPC, install and pin:

- AWS Load Balancer Controller.
- External Secrets Operator and an AWS Secrets Manager `ClusterSecretStore`.
- kube-prometheus-stack/Prometheus Operator and Grafana or bank monitoring integration.
- OpenTelemetry Collector exporting to the bank observability platform.
- EBS CSI driver (add-on is enabled) and metrics-server.
- Kyverno or Gatekeeper policies: signed images, allowed registries, non-root, resource limits,
  read-only root filesystem, no privileged pods, required network policies.

Create namespaces `retail-bank-a2a`, `monitoring`, and `ingress-system` with Pod Security Admission
`restricted`. Adjust the provided NetworkPolicy for the bank's CNI and actual egress CIDRs/FQDN
control. Kubernetes NetworkPolicy cannot express external FQDN allowlists by itself.

Exit: platform conformance tests, admission-policy tests, and private connectivity pass.

## Phase 8 — Populate and rotate secrets

Terraform creates the secret structure, but provider values remain placeholders. Populate them via an
approved secrets pipeline:

```bash
aws secretsmanager get-secret-value --secret-id /prod/retail-bank-a2a \
  --query SecretString --output text > /tmp/current-secret.json
# Edit through an approved secure mechanism; do not type secrets into shell history.
aws secretsmanager put-secret-value --secret-id /prod/retail-bank-a2a \
  --secret-string file:///tmp/current-secret.json
```

Prefer IAM database authentication or separate rotated runtime/migration users. Give External Secrets
its own workload identity. The application role only needs approved-document read access; it does not
need Secrets Manager access when secrets are projected by the operator.

Exit: secret rotation drill succeeds and no secret appears in Git, logs, plans, pod specs, or images.

## Phase 9 — Configure CI/CD and deploy staging

Create GitHub environments `staging` and `production` with required reviewers. Production variables:

`AWS_ROLE_ARN`, `AWS_REGION`, `EKS_CLUSTER_NAME`, `ECR_REPOSITORY`, `APP_ROLE_ARN`,
`DOCUMENT_BUCKET`, `API_HOST`, and `ACM_CERTIFICATE_ARN`.

The CD runner must carry labels `self-hosted, linux, x64, bank-prod-vpc` and have private DNS/network
access to EKS. It receives AWS credentials only through GitHub OIDC. Terraform adds the deploy role as
an EKS namespace-scoped access entry; `eks:DescribeCluster` alone authenticates AWS but does not
authorize Kubernetes operations. A platform administrator must create `retail-bank-a2a` and apply
its restricted Pod Security labels before the first application deployment.

```bash
helm lint deploy/helm/retail-bank-a2a
helm template retail-bank-a2a deploy/helm/retail-bank-a2a \
  --namespace retail-bank-a2a > /tmp/rendered.yaml
```

Deploy staging, run migrations as the Helm pre-upgrade hook, then verify readiness, logs, metrics,
traces, database connections, JWKS, rate limiting, and all provider paths.

Exit: atomic deployment and rollback both succeed from the protected pipeline.

## Phase 10 — Validation campaign

Run these gates on synthetic but production-like data:

1. Unit, type, lint, dependency, container, IaC, policy, and contract tests.
2. Golden task evals by language, segment, product, and intent.
3. RAG retrieval, groundedness, citation accuracy, abstention, revoked-policy, and poisoning evals.
4. Prompt injection, PII/DLP, IDOR, token, tool-output injection, and OWASP API/LLM testing.
5. Payment concurrency, duplicate, expiry, step-up, risk-deny, uncertain-outcome, and reconciliation.
6. Load/soak tests with provider quotas; autoscaling, connection pools, and cost ceilings.
7. Node/AZ/provider/database/cache failures, rollback, backups, and regional DR game day.
8. Human factors: warnings, confirmation screen, accessibility, translations, and support escalation.

Record the exact image digest, config, prompt version, model snapshot/alias behavior, index namespace,
policy version, and evaluation report as release evidence.

Exit: every product, risk, security, privacy, compliance, and SRE approver signs the release evidence.

## Phase 11 — Progressive production release

1. Deploy with knowledge only and employee traffic.
2. Canary 1%, then 5%, 25%, 50%, 100%, with fixed observation windows and automatic rollback gates.
3. Enable masked account reads after entitlement/error review.
4. Enable payment proposals without execution; compare drafts to human-entered transfers.
5. Enable execution for low-value internal pilot customers, then progressively expand approved limits.
6. Keep independent kill switches for knowledge, account reads, proposals, and payment execution.

Do not use LLM output as the basis for credit, underwriting, fraud denial, investment advice, or other
regulated automated decisions without a separate legal/model-risk program.

## Phase 12 — Operate and improve

- Daily: errors, guardrails, fraud/compliance decisions, empty retrieval, cost, and provider status.
- Weekly: sampled conversation review with approved redaction, eval trends, failed-payment reconciliation.
- Monthly: access review, prompt/index/model changes, dependency and base-image updates.
- Quarterly: red team, restore/DR exercise, provider exit/rebuild, threat model, and model-risk review.
- Every release: immutable evidence bundle and rollback rehearsal.

Use [RUNBOOK.md](RUNBOOK.md) for incidents. Changes to prompts, models, tools, routing, limits,
identity claims, risk logic, policy documents, or retrieval filters are controlled production changes,
not content-only edits.
