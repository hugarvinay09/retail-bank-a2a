# Operations runbook

## Suggested SLOs

| Signal | Target | Alert |
|---|---:|---:|
| API availability | 99.9% monthly | burn rate 14.4×/1h or 6×/6h |
| Read request p95 | < 4 s | > 5 s for 10 min |
| Payment proposal p95 | < 6 s | > 8 s for 10 min |
| Approval API p95 | < 2 s excluding bank | > 3 s for 5 min |
| Unsafe payment execution | 0 | page immediately |
| Duplicate payment | 0 | page immediately |
| Grounded knowledge answers | ≥ 95% eval set | block release below threshold |
| Citation precision | ≥ 98% eval set | block release below threshold |

## Dashboards

Graph request rate/error/latency by intent; provider latency and rate limits; guardrail block reasons;
payment proposal/approval/execution/failed counts; Aurora connections/locks/replica lag; Valkey memory,
evictions and failovers; pod CPU/memory/restarts; HPA desired/current replicas; ALB 4xx/5xx; OpenAI
token/cost budget; Pinecone latency/empty retrievals; Cohere rerank latency.

## First response

1. Stop unsafe impact: disable payment execution or route all traffic to read-only mode.
2. Identify correlation/payment ID; never paste raw customer text or secrets into an incident channel.
3. Check audit topology, payment state, bank idempotency lookup, deployment version, provider health,
   and recent prompt/policy/index changes.
4. If outcome is uncertain, do not replay blindly. Reconcile with the bank using the stored
   idempotency key and bank reference.
5. Roll back application with Helm; a schema downgrade is a separate, reviewed decision.

## Commands

```bash
kubectl -n retail-bank-a2a get pods,deploy,hpa,pdb
kubectl -n retail-bank-a2a rollout status deploy/retail-bank-a2a
kubectl -n retail-bank-a2a logs deploy/retail-bank-a2a --since=15m --prefix
helm -n retail-bank-a2a history retail-bank-a2a
helm -n retail-bank-a2a rollback retail-bank-a2a PREVIOUS_REVISION --wait --timeout 10m
```

## Failure playbooks

### OpenAI unavailable or rate-limited

Return 503; do not bypass the graph or use unapproved models. Verify provider status, quotas,
timeouts, and token budget. Activate the approved deterministic FAQ fallback if the bank has one.

### Pinecone/Cohere unavailable

Disable knowledge answers or return a human-support handoff. Never synthesize policy from model
memory. Account/payment paths can remain available only if their dependencies are healthy.

### Redis unavailable

The chat endpoint fails closed with 503. Restore the replication group or switch to the approved
secondary region; do not remove rate limiting during an incident.

### Database unavailable

Readiness removes pods. Payment proposal/approval must stop. Check Aurora failover, connections,
security groups, certificates, and migration status.

### Payment stuck in `executing` or `failed`

Query the canonical bank API using the idempotency key. If accepted, update through a controlled
reconciliation job and record the bank reference. If absent, require operations authorization before
reusing the same idempotency key. Never create a new key for the same customer instruction.

### Bad prompt/model release

Disable payments, compare evals by model/prompt version, roll back image/config, and invalidate the
release. Prompts are deployed with code so rollback is atomic.

### Poisoned/stale knowledge

Remove the document from the approved publication set, switch retrieval to the last known-good
namespace/version, re-ingest, rerun citation/groundedness evals, and preserve evidence for review.

## Backup and DR

Test Aurora point-in-time restore, S3 version/Object Lock recovery, Secrets Manager regional recovery,
Pinecone rehydration from approved S3 documents, ECR replication, and Terraform reconstruction at
least quarterly. Define RTO/RPO with the bank; a starting reference is RTO 60 minutes and RPO 5
minutes for agent state, with zero tolerated loss for canonical bank payment records.

