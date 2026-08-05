# Threat model

## Assets

Customer identity and entitlements, balances, beneficiary IDs, payment authority, provider/API
credentials, approved policy documents, agent prompts, risk/compliance decisions, and audit records.

## Main threats and implemented controls

| Threat | Control in this repository | Additional bank control |
|---|---|---|
| Prompt injection | Pre-model patterns, fixed graph, no arbitrary tools, bounded prompts | Adversarial corpus, content classifier, WAF signals |
| Cross-customer access | Account allowlist from signed token; customer-scoped bank path | Entitlement service and ABAC at bank API |
| Model-triggered payment | Model only creates draft; execution is separate service | Transaction signing, device binding, bank authorization engine |
| Duplicate payment | DB compare-and-set plus idempotency key | Bank-side idempotency and reconciliation ledger |
| Knowledge poisoning | Approved S3 prefix, versioned chunks, metadata filters | Maker-checker publishing and document signatures |
| Secret/PII leakage | Redaction, no raw prompt logs, `store=false`, HMAC safety ID | DLP gateway, contractual ZDR, regional endpoint |
| Tool response injection | Typed Pydantic parsing and synthesis from explicit fields | Provider contract validation and output encoding |
| Excessive agency | Fixed topology, scoped tools, explicit approval boundary | Model-risk policy and kill switch |
| Supply-chain compromise | Lockfile, CI audit, container scan, immutable ECR | Signed images, admission verification, SHA-pinned actions |
| Insider misuse | Scoped IAM, audit trail, immutable S3 plan | PAM/JIT access, dual control, SIEM analytics |
| Denial of service | WAF/API limits, Redis limiter, timeouts, HPA | Quotas, provider budgets, circuit breakers, load shedding |

## Abuse tests required before launch

- Instructions to ignore policies, reveal prompts, call hidden tools, or fabricate an approval.
- Full card, PIN, CVV, password, access token, Aadhaar/SSN, and mixed-language secrets.
- Account IDs owned by a different customer and IDOR attempts on approval/status endpoints.
- Duplicate, concurrent, expired, high-value, unsupported-currency, and inactive-beneficiary transfers.
- Poisoned PDFs containing tool instructions, invisible text, conflicting policy, or stale versions.
- Provider timeouts before/after payment acceptance and crash between bank acceptance and DB update.
- Unicode obfuscation, long input, JSON/schema tricks, citation fabrication, and indirect injection.

## Non-negotiable go-live gates

No production data until privacy/DPA/data-residency approval. No payments until bank authorization,
fraud/AML, reconciliation, step-up authentication, operations procedures, penetration test, and model
risk validation are complete. Keep a feature flag that disables proposal creation and another that
disables execution independently.

