# Architecture & Design Decisions

This file documents *why* the lab is built the way it is. README.md tells you what it does; HOWTO.md walks you through building it; this file explains the trade-offs.

---

## Design principles

### 1. Defense in depth
We don't rely on a single control. CloudTrail tells us *what happened*. Config tells us *what's wrong with our configuration*. GuardDuty tells us *what looks malicious*. Each layer catches things the others miss.

### 2. Detect AND respond
A detection that doesn't trigger a response is just a louder inbox. Every detection in this lab has a target: SNS for human-in-the-loop, Lambda for fully-automated remediation.

### 3. Least privilege on every IAM principal
The Lambda role can only modify S3 public-access blocks — not delete buckets, not read objects, not anything else. If the Lambda were ever compromised, the blast radius is bounded.

### 4. Cost-bounded by design
Every service in the architecture is in the AWS Free Tier. Cost guardrails (Budgets + CloudWatch billing alarm) come first, before any other service is enabled. If the lab somehow starts billing, you find out within 24 hours.

### 5. Reproducible
Phase 1–8 build the lab via clicks (good for learning). Phase 9 re-deploys via Terraform (good for portability). Every resource has a name prefix `cloudsec-` so cleanup is unambiguous.

---

## Service-by-service rationale

### Why CloudTrail?
The **forensic foundation**. Without CloudTrail you have no record of what happened in the account; with it, you can answer "who deleted that bucket?" months later. Free tier covers management events.

### Why GuardDuty over writing detection rules ourselves?
GuardDuty is a managed service backed by AWS-curated threat intelligence (known-bad IPs, crypto-mining domains, etc). For a beginner lab, writing the equivalent detection logic from scratch in CloudWatch Log Insights is a much bigger project. We stand on AWS's shoulders.

### Why AWS Config in addition to GuardDuty?
GuardDuty is **behavioral** ("this IAM user just made calls from a Tor exit node"). Config is **declarative** ("this bucket is configured to allow public reads"). They detect different classes of problem. The auto-remediation in Phase 5 is built on Config because public-bucket detection is a configuration question, not a behavioral one.

### Why EventBridge instead of subscribing SNS directly to GuardDuty?
EventBridge gives us **filtering** (only severity ≥ 4) and **fan-out** (one event can trigger SNS *and* Lambda *and* a third target). Direct SNS subscription would alert on everything and offer no automation hook. EventBridge is the correct routing primitive.

### Why Lambda for remediation instead of Systems Manager Automation?
Both are valid. Lambda is more general-purpose, more familiar to anyone who has written Python, and the function we wrote (10 lines) is short enough that the simplicity of Lambda wins. Systems Manager Automation is the right answer once you have ≥5 remediation playbooks.

### Why S3 (encrypted, versioned, blocked-public) for log archive?
- **Encrypted** so logs are unreadable if the bucket is somehow exposed
- **Versioned** so an attacker who compromises the account cannot trivially delete evidence
- **Block public access** because a public log bucket is itself an incident
- **Same account** for simplicity in the lab; in production, you'd use a separate "Security" AWS account in an Organization, owned by a different team than the workloads it audits

---

## Trade-offs we explicitly accepted

| Choice | What it costs us | Why we accepted |
|--------|------------------|-----------------|
| Single-account architecture | Logs live in the same account as the workloads they audit; an attacker with admin can delete them | Multi-account adds AWS Organizations complexity beyond a beginner lab |
| 30-day GuardDuty trial | Service auto-bills after day 30 | Required for a realistic lab; we mitigate with calendar reminders |
| No object lock on log bucket | Versioning only — a sophisticated attacker can still delete versions | Object lock is irreversible for the lab's lifetime |
| EventBridge severity threshold of 4 | We miss low-severity findings | Low-severity findings are noisy and not actionable for a single-engineer "team" |
| Lambda has `s3:*` on the bucket-level public-access actions | Slightly broad | Tightening to per-bucket would require dynamic policy generation; out of scope |

---

## What this lab is NOT

- It is **not** a replacement for a real CSPM product (Wiz, Prisma, Lacework). A real CSPM has multi-cloud coverage, hundreds of detections, asset inventory, lineage, and a UI for triage.
- It does **not** detect application-layer attacks (SQL injection, XSS, etc.). That's WAF and AppSec territory.
- It does **not** scan code or container images. That's Inspector / ECR scanning / Snyk territory.
- It does **not** monitor your endpoints. That's CrowdStrike / SentinelOne territory.

What the lab *does* prove is that you understand the **AWS-native security event pipeline**: detection sources → routing → notification → automated response. That's the foundation every more advanced cloud security architecture is built on.
