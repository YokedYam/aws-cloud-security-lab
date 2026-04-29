# How to build the Cloud Security Posture Lab

> A step-by-step build guide written for a student who has **no prior AWS experience**. We'll click through the AWS Console first to learn what each service does, then optionally re-do it as code in Terraform at the end.

If you're just visiting the repo, read [README.md](./README.md) first. This file is the actual build manual.

---

## Pre-flight checklist

You will need:

1. **A new email address** (a Gmail alias like `youremail+awslab@gmail.com` works) — keep your AWS account isolated from your personal email signup.
2. **A credit card** — AWS requires one for sign-up, even on the Free Tier. We'll set guardrails so you don't get charged.
3. **A phone for SMS** — for verification.
4. **A hardware or virtual MFA app** — Authy, 1Password, or Google Authenticator.
5. **About 4–6 hours of focused time**, split across 2–3 sittings.

> ⚠️ **Important:** AWS Free Tier ≠ "free no matter what." Some services are free **only for the first 12 months**, others are **always free up to a quota**, and some are **never free** (NAT Gateways, anything in a "Pro" tier). The HOWTO sticks to free services, but **you must complete Phase 8 (cleanup)** when the lab is done. See [[aws-free-tier]] for details.

---

## Mental model — what we are actually building

A real cloud security team has three jobs:

1. **Know what's in the environment** (asset inventory, config tracking)
2. **Know when something bad happens** (detection)
3. **Do something about it** (response/remediation)

This lab maps exactly to those three jobs:

| Job | Service we'll use |
|-----|-------------------|
| Audit log of every action | [[cloudtrail]] |
| Track configuration drift / non-compliant resources | [[aws-config]] |
| Detect threats & malicious behavior | [[guardduty]] |
| Route events to humans or automation | [[eventbridge]] |
| Notify a human | [[sns]] |
| Take automated action | [[lambda]] |

The pattern of "service generates an event → EventBridge routes it → Lambda or SNS handles it" is the **canonical AWS event-driven architecture**, and learning it once means you can apply it to almost any other automation problem in AWS.

The umbrella term for what we're building is [[cloud-security-posture-management]] (CSPM), and the design philosophy we're following is [[defense-in-depth]] — we don't trust any single layer to catch everything; we layer logging + detection + posture + automation so a failure in one layer is caught by the next.

---

## Phase 1 — Account foundation (the part most tutorials skip)

The single biggest cause of "AWS surprise bills" and "AWS account got hacked" is a weak account foundation. We do this **first**, before anything else.

### 1.1 — Create the AWS account

1. Go to https://aws.amazon.com/free → "Create a Free Account"
2. Use the dedicated email from the pre-flight checklist
3. Choose **Personal** account type
4. Pick a strong root password (use a password manager — don't reuse a personal password)
5. Verify phone, payment method, support plan = **Basic (Free)**

### 1.2 — Lock down the root user

The **root user** is the email-and-password identity you just made. It can do *anything* in the account, including delete the account. **You should never use it for daily work.**

1. Sign in at https://console.aws.amazon.com → top-right account menu → **Security credentials**
2. Click **Activate MFA** → choose **Authenticator app** → scan with Authy/1Password
3. Confirm with two consecutive 6-digit codes
4. Confirm there are **zero access keys** for the root user. If any exist, delete them.

### 1.3 — Set the cost guardrails BEFORE anything else

This is the single most important step in the entire lab.

**a. Enable IAM-user billing access**
- Account menu → **Account** → scroll to **IAM User and Role Access to Billing Information** → Edit → **Activate** → Update.

**b. Create a zero-spend Budget**
- Search "Billing and Cost Management" → **Budgets** → Create budget → Use template → **Zero spend budget** → email = your email → Create.
- This emails you the second AWS *forecasts* even one cent of charge.

**c. Create a backup billing alarm in CloudWatch**
- Switch the AWS Console region (top-right) to **N. Virginia (us-east-1)** — billing metrics only live in this region.
- CloudWatch → Alarms → Create alarm → Browse metrics → Billing → Total Estimated Charge → currency = USD.
- Threshold: static, greater than `1` (i.e., $1.00).
- Send notification to a new SNS topic called `billing-alarms` with your email as the subscription.
- **Confirm the email AWS sends you** (otherwise SNS won't actually deliver alerts).

> 📝 *Why two alarms?* Budgets and CloudWatch billing alarms behave differently. Budgets is a forecasting/alerting service that polls daily; the CloudWatch alarm reacts to the metric directly. Belt and suspenders.

### 1.4 — Stop using the root user

- Search "IAM" → **Users** → Create user → name `johnny-admin` (or your name).
- Check **Provide user access to the AWS Management Console**.
- "I want to create an IAM user" → autogenerated password OR custom.
- **Permissions:** *Attach policies directly* → check `AdministratorAccess` for now (we'll narrow this later).
- Save the sign-in URL it gives you (looks like `https://<account-id>.signin.aws.amazon.com/console`).
- Sign out as root. Sign in as your new IAM user. From this point forward, **only use the IAM user**.

### 1.5 — Set an account password policy

IAM → Account settings → Edit password policy:
- Minimum length: 14
- Require uppercase, lowercase, number, symbol
- Allow users to change their own password: yes
- Expire passwords: 180 days

### 1.6 — Enable MFA on your IAM user too

IAM → Users → `johnny-admin` → Security credentials → Assign MFA → Authenticator app.

> ✅ **Phase 1 checkpoint:** root MFA enabled, no root access keys, $0 budget configured, $1 CloudWatch billing alarm armed, IAM admin user created with MFA, password policy set. You now have a "secure-by-default" account, which is more than 80% of personal AWS accounts on the internet have.

---

## Phase 2 — Logging: the security forensics layer

Goal: every API action in this account ends up in an encrypted, tamper-evident log archive.

### 2.1 — Create the log bucket

1. S3 → Create bucket
2. Name: `johnnyN-cloudsec-logs-<random6digits>` (S3 names are globally unique)
   (your bucket name, e.g. `yourname-cloudsec-logs-<random6digits>`)
3. Region: `us-east-1`
4. **Block all public access:** ON (default — leave it)
5. Bucket Versioning: **Enable** (protects against malicious deletion)
6. Default encryption: **SSE-S3** (free) or **SSE-KMS** with the AWS-managed key
7. Create.

After creation:
- Properties → Object Lock: leave off for now (real-world: turn on with Compliance mode for an immutable forensic archive — but it cannot be undone, so we'll skip in the lab)
- Permissions → Bucket Policy: leave default (CloudTrail will add its own when we attach it)

> 📝 *Why a separate log bucket?* If an attacker compromises a workload, you don't want them to be able to delete the evidence. The pro version of this is a separate "Security" AWS account that owns the log bucket — out of scope for now.

### 2.2 — Enable CloudTrail

[[cloudtrail]] is the audit log service. Every time anyone (you, an EC2 instance, an attacker with stolen credentials) calls an AWS API, CloudTrail records it.

1. CloudTrail → Trails → Create trail
2. Name: `cloudsec-lab-trail`
3. Storage location: **Use existing S3 bucket** → pick the one from 2.1
4. Log file SSE-KMS encryption: optional (off is fine for the lab)
5. Log file validation: **ON** (free, lets you prove logs weren't tampered with)
6. CloudWatch Logs: **Enable** — create new log group `aws-cloudtrail-logs-cloudsec` and a new IAM role
   (create a new IAM role name, e.g. `cloudSecAdmin`)
7. Events:
   - Management events: **Read + Write**, **Exclude AWS KMS events:** off
   - Data events: skip (would bill on free tier if you're not careful)
   - Insights events: skip
8. Create.

Within ~15 minutes, log files start appearing in your S3 bucket under `AWSLogs/<accountID>/CloudTrail/...`. Open one — it's compressed JSON. Each entry has a `userIdentity`, `eventName`, `sourceIPAddress`, etc. **This is gold for incident response.**

### 2.3 — Verify it's working

Do *anything* in the console (e.g., refresh the IAM page). Wait ~15 min. CloudTrail → Event history → search for your username → you should see `ConsoleLogin`, `ListUsers`, etc. as separate events.

> ✅ **Phase 2 checkpoint:** every action in this account is now permanently logged to a versioned, encrypted, private S3 bucket.
> ![[Pasted image 20260428115410.png]]

---

## Phase 3 — Threat detection: GuardDuty + AWS Config

We have logs. Now we need something that **reads** the logs and tells us when something is bad.

### 3.1 — Enable GuardDuty

[[guardduty]] is AWS's managed threat detection. It continuously analyzes CloudTrail, VPC Flow Logs, and DNS logs using ML and AWS-curated threat intelligence. You don't write detection rules — AWS does.

1. GuardDuty → Get started → **Enable GuardDuty**
2. That's it. It's now scanning your account.

> 💰 *Cost note:* GuardDuty is a 30-day free trial for new accounts. After 30 days it bills per-event-analyzed. **Set a calendar reminder for day 28.** If you want to keep the lab running past 30 days, expect roughly $3–$5/month for a low-activity personal account, or disable it before day 30 and re-enable later.

### 3.2 — Try a sample finding

GuardDuty → Settings → **Generate sample findings**. After a minute, the Findings page populates with ~50 fake findings (e.g., "Recon:IAMUser/MaliciousIPCaller", "UnauthorizedAccess:IAMUser/InstanceCredentialExfiltration"). Click into one — note the structure: `severity`, `type`, `resource`, `service`. **We'll match on this structure in Phase 4 with EventBridge.**
![[CleanShot 2026-04-29 at 01.26.17@2x.png]]

### 3.3 — Enable AWS Config

[[aws-config]] is the **posture / compliance** service. Where GuardDuty asks "is something malicious happening?", Config asks "are my resources configured the way they should be?" Things like:
- Is any S3 bucket public?
- Are there IAM users without MFA?
- Are there security groups open to 0.0.0.0/0 on port 22?

1. Config → Get started
2. Resource types: **All supported resources** (Free Tier includes 1,000 config items recorded per month)
3. Delivery channel: use the same log bucket from Phase 2 (Config will create a sub-prefix)
4. After Config is set up, add each managed rule **one at a time** (the wizard only allows one per creation flow). Rules → Add rule → AWS managed rule → search for the name → Next → Next → Save. Repeat for each:
   - `s3-bucket-public-read-prohibited`
   - `s3-bucket-public-write-prohibited`
   - `root-account-mfa-enabled`
   - `iam-user-mfa-enabled`
   Leave all parameters at their defaults. After all four are created they'll appear together on the Rules dashboard.
   ![[CleanShot 2026-04-29 at 08.49.29@2x.png]]
1. Confirm.
![[CleanShot 2026-04-29 at 04.27.44@2x.png]]
After a few minutes, Config evaluates your existing resources against those rules. If anything is non-compliant, it shows up red.

> ✅ **Phase 3 checkpoint:** Two complementary detection systems are now running. GuardDuty watches *behavior*; Config watches *configuration*.

---

## Phase 4 — Detection rules: route events to humans

Now we wire detection findings to your inbox.

### 4.1 — Create the alert SNS topic

[[sns]] is AWS's pub/sub notification service. We create one **topic** ("security-alerts"), subscribe your email to it, and any service that publishes to that topic causes you to get an email.

1. SNS → Topics → Create topic
2. Type: **Standard**
3. Name: `security-alerts`
4. Create.
5. On the topic page → Create subscription → Protocol = **Email** → Endpoint = your email → Create.
6. **Confirm the email AWS sends you.**
![[CleanShot 2026-04-29 at 04.15.25@2x.png]]
![[CleanShot 2026-04-29 at 01.32.24@2x.png]]
### 4.2 — EventBridge rule: notify on any GuardDuty finding (medium+)

[[eventbridge]] receives an event from every AWS service. We create a **rule** with a JSON pattern that matches GuardDuty findings, and a **target** that publishes to our SNS topic.

1. EventBridge → Rules → (Advanced Builder) Create rule
2. Name: `gd-medium-or-higher-to-email`
3. Event bus: `default`
4. Rule type: **Rule with an event pattern**
5. Event source: AWS events
6. Event pattern (paste this in custom-pattern editor):

```json
{
  "source": ["aws.guardduty"],
  "detail-type": ["GuardDuty Finding"],
  "detail": {
    "severity": [{ "numeric": [">=", 4] }]
  }
}
```

> 📝 *GuardDuty severity legend:* 1.0–3.9 Low, 4.0–6.9 Medium, 7.0–8.9 High. We're filtering medium+.

7. Target: **SNS topic** → `security-alerts`
8. Create.
![[CleanShot 2026-04-29 at 04.16.50@2x.png]]
### 4.3 — EventBridge rule: notify on root login

```json
{
  "source": ["aws.signin"],
  "detail-type": ["AWS Console Sign In via CloudTrail"],
  "detail": {
    "userIdentity": { "type": ["Root"] }
  }
}
```

Target = same `security-alerts` topic.

> Why this matters: root logins should be **rare** (you committed in Phase 1 to never use root). Any root login that you didn't initiate is an immediate "drop everything and investigate" event.
![[CleanShot 2026-04-29 at 04.19.17@2x.png]]

### 4.4 — Human-readable alert formatter Lambda

By default EventBridge passes the raw JSON event to SNS, which emails it as-is — unreadable for humans. This step inserts a formatter Lambda between EventBridge and SNS that turns the JSON into a plain-text email.
![[CleanShot 2026-04-29 at 06.24.24@2x.png]]
The pipeline changes from:
`EventBridge → SNS → email`

to:
`EventBridge → Formatter Lambda → SNS → email`

**a. Create the formatter Lambda IAM role**

1. IAM → Roles → Create role → AWS service → Lambda
2. Attach `AWSLambdaBasicExecutionRole`
3. Name: `cloudsec-alert-formatter-role`
4. Create, then open the role → Add inline policy → JSON:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "sns:Publish",
    "Resource": "arn:aws:sns:<your-region>:<your-account-id>:security-alerts"
  }]
}
```

Name it `PublishToSecurityAlerts`. Save.

**b. Create the formatter Lambda**

1. Lambda → Functions → Create function → Author from scratch
2. Name: `cloudsec-alert-formatter`
3. Runtime: **Python 3.12**, Architecture: x86_64
4. Permissions → Use an existing role → `cloudsec-alert-formatter-role`
5. Create.
6. Replace the code with the contents of [`lambda/format_alert.py`](./lambda/format_alert.py). Deploy.
7. **Configuration → Environment variables → Edit → Add:**
   - Key: `ALERT_TOPIC_ARN`
   - Value: `arn:aws:sns:<your-region>:<your-account-id>:security-alerts`
8. Save.
![[CleanShot 2026-04-29 at 06.39.16@2x.png]]
**c. Update the EventBridge rules to target the formatter Lambda**

For **both** rules (`gd-medium-or-higher-to-email` and the root-login rule):

1. EventBridge → Rules → click the rule → **Edit**
2. Proceed to the **Target** step
3. Change the target from **SNS topic** to **Lambda function** → select `cloudsec-alert-formatter`
4. Save.
![[CleanShot 2026-04-29 at 06.42.50@2x.png]]
> 📝 *Why the Lambda needs the SNS topic ARN as an env var:* the function publishes to SNS itself rather than relying on EventBridge to do it, which is what gives it the ability to set a custom `Subject` line and format the `Message` body.

### 4.5 — Test it
![[CleanShot 2026-04-29 at 04.28.57@2x 1.png]]

GuardDuty → Settings → Generate sample findings → check your email within 1–2 min. You should now see formatted emails with a readable subject line and structured body instead of raw JSON. (You can later raise the severity threshold to `>= 7` if it's too noisy.)
![[CleanShot 2026-04-29 at 04.31.13@2x.png]]

> ✅ **Phase 4 checkpoint:** real-time email alerts on threat findings and root logins are now working, with human-readable formatting.
![[CleanShot 2026-04-29 at 08.25.54@2x.png]]
---

## Phase 5 — Auto-remediation: a Lambda that fixes things

This is the headline feature. We build the canonical example: **a Lambda that re-privates any S3 bucket the moment someone makes it public.**

### 5.1 — Create the Lambda execution role

[[lambda]] functions don't have permissions by default — they assume an IAM role. We follow [[iam|least privilege]]: the role only gets to do exactly what it needs.

1. IAM → Roles → Create role
2. Trusted entity: **AWS service** → Lambda
3. Permissions: attach `AWSLambdaBasicExecutionRole` (lets it write logs to CloudWatch Logs)
4. Name: `cloudsec-remediate-public-s3-role`
5. Create.
6. Open the role → Add inline policy → JSON:
![[CleanShot 2026-04-29 at 04.37.20@2x.png]]

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "s3:PutBucketPublicAccessBlock",
      "s3:PutBucketAcl",
      "s3:GetBucketAcl",
      "s3:GetBucketPolicyStatus"
    ],
    "Resource": "*"
  }]
}
```

Name it `RemediatePublicS3`. Save.

### 5.2 — Create the Lambda function

1. Lambda → Functions → Create function
2. Author from scratch
3. Name: `cloudsec-remediate-public-s3`
4. Runtime: **Python 3.12**
5. Architecture: x86_64
6. Permissions → Use an existing role → `cloudsec-remediate-public-s3-role
![[CleanShot 2026-04-29 at 06.13.44@2x.png]]`
7. Create.
8. Replace the code with the contents of [`lambda/remediate_public_s3.py`](./lambda/remediate_public_s3.py) in this repo.
9. Deploy.
![[CleanShot 2026-04-29 at 06.17.50@2x.png]]
### 5.3 — Wire it to AWS Config

When the Config rule `s3-bucket-public-read-prohibited` flips to `NON_COMPLIANT`, Config emits an event to EventBridge. We catch it.

EventBridge → Rules → Create rule:
- Name: `remediate-public-s3-on-config-noncompliance`
- Event pattern:

```json
{
  "source": ["aws.config"],
  "detail-type": ["Config Rules Compliance Change"],
  "detail": {
    "messageType": ["ComplianceChangeNotification"],
    "newEvaluationResult": {
      "complianceType": ["NON_COMPLIANT"]
    },
    "configRuleName": [
      "s3-bucket-public-read-prohibited",
      "s3-bucket-public-write-prohibited"
    ]
  }
}
```

- Target: Lambda function → `cloudsec-remediate-public-s3`
![[CleanShot 2026-04-29 at 06.19.58@2x.png]]
### 5.4 — Test the auto-remediation (the satisfying part)

> ⚠️ Do this in your *lab* AWS account only.

1. Create a new test bucket: `cloudsec-test-public-<random>`
2. Permissions tab → Block public access → Edit → **uncheck** "Block all public access" → save (you'll have to type "confirm")
3. Bucket policy → paste a public-read policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::cloudsec-test-public-XXXXX/*"
  }]
}
```
![[CleanShot 2026-04-29 at 08.32.32@2x.png]]
4. Wait ~5–10 minutes for Config to evaluate.
5. Watch:
   - Config → Rules → `s3-bucket-public-read-prohibited` flips to non-compliant
   - EventBridge fires the rule
   - Lambda function logs (CloudWatch Logs → `/aws/lambda/cloudsec-remediate-public-s3`) show it ran
   - Bucket → Permissions → Block public access → flipped back to **all on**
6. **Take screenshots of each of those four panels** — these are gold for your LinkedIn post and GitHub README.

> ✅ **Phase 5 checkpoint:** you have a working detect-and-respond loop. The skill of designing one of these is exactly what cloud security engineers get hired to do.
![[CleanShot 2026-04-29 at 08.54.31@2x.png]]
![[CleanShot 2026-04-29 at 08.55.19@2x.png]]
![[CleanShot 2026-04-29 at 08.58.43@2x.png]]
![[CleanShot 2026-04-29 at 08.59.18@2x.png]]
![[CleanShot 2026-04-29 at 09.04.33@2x.png]]
![[CleanShot 2026-04-29 at 09.05.11@2x.png]]
---

## Phase 6 — End-to-end test

Now exercise everything together. Pick at least three of these:

1. Generate sample GuardDuty findings → verify email arrives.
   ![[CleanShot 2026-04-29 at 09.00.34@2x.png]]
2. Make an S3 bucket public → verify auto-remediation runs and email arrives.
   
3. Sign in with the root user → verify root-login email arrives.
4. Try to create an IAM user without MFA → verify Config flags it.
   no-MFA-account
   h2hC571A{N$04K
5. Open a security group to `0.0.0.0/0` on port 22 (in a throwaway VPC) → verify Config flags it.

Write down what worked, what didn't, and any latency you observed. This becomes your "What I learned" section in the README.

---

## Phase 7 — Document it for GitHub & LinkedIn

This is the part students skip and the part recruiters actually read.

### 7.1 — Screenshots checklist

Save these PNGs into a `screenshots/` folder you push with the repo:

- [x] AWS Budgets dashboard showing $0 budget
      ![[CleanShot 2026-04-29 at 13.19.49@2x.png]]
- [x] CloudTrail Event history showing your `ConsoleLogin` event
      ![[CleanShot 2026-04-29 at 13.22.28@2x.png]]
- [x] GuardDuty Findings page with your sample findings
      ![[CleanShot 2026-04-29 at 13.23.25@2x.png]]
- [ ] AWS Config compliance dashboard
      ![[CleanShot 2026-04-29 at 13.24.28@2x.png]]
- [ ] EventBridge rule with the JSON pattern visible
      ![[CleanShot 2026-04-29 at 13.27.30@2x.png]]
- [ ] An alert email in your inbox (redact your email!)
      ![[CleanShot 2026-04-29 at 13.28.52@2x.png]]
- [ ] CloudWatch Logs showing the Lambda's remediation run
      ![[CleanShot 2026-04-29 at 13.30.20@2x.png]]
- [ ] The S3 bucket flipping back to "all public access blocked"
      ![[CleanShot 2026-04-29 at 13.31.46@2x.png]]

### 7.2 — Architecture diagram

The ASCII diagram in README.md is fine. For bonus polish, redo it in [draw.io](https://app.diagrams.net) or [Excalidraw](https://excalidraw.com) with the AWS icon set, export PNG, embed in README.md.

### 7.3 — Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit: AWS Cloud Security Posture Lab"
git branch -M main
git remote add origin git@github.com:johnny149/aws-cloud-security-lab.git
git push -u origin main
```

### 7.4 — LinkedIn post draft

> Built and shipped a small Cloud Security Posture lab in AWS this week.
>
> The lab continuously logs every API call (CloudTrail), threat-detects on the AWS account (GuardDuty), tracks compliance posture (AWS Config), routes findings via EventBridge, alerts me by email (SNS), and auto-remediates a public S3 bucket using a Python Lambda function — all entirely on the AWS Free Tier with $0 in spend.
>
> The biggest lesson: in cloud security, the architecture *is* the control. Detection without an automated response path is just a noisier inbox.
>
> Repo + write-up: [github link]
>
> Next up: re-deploying the same baseline as a Terraform module so it's reproducible across accounts.

---

## Phase 8 — Cleanup (DO NOT SKIP)

If you're done with the lab and don't want any monthly charges:

- [ ] **GuardDuty** → Settings → Disable
- [ ] **AWS Config** → Settings → Stop the recorder, delete the delivery channel
- [ ] **CloudTrail** → delete the trail (or stop logging)
- [ ] **Lambda** → delete the function and the IAM role
- [ ] **EventBridge** → disable or delete the rules
- [ ] **SNS** → delete the topics (`security-alerts`, `billing-alarms`)
- [ ] **S3** → empty + delete the log bucket
- [ ] **CloudWatch** → delete the billing alarm and any log groups still around
- [ ] **Budgets** → leave the zero-spend budget on, even after the lab — costs nothing

> 📝 *Pro tip:* Set a calendar event titled "AWS lab teardown" for 25 days from when you started. GuardDuty's free trial is 30 days; tearing down before then is the safest way to guarantee $0.

---

## Phase 9 — Level up: re-deploy as Terraform (appendix)

[[terraform]] is the industry-standard tool for **infrastructure as code**: you describe AWS resources in `.tf` files, and Terraform makes the API calls to create/update/delete them. The advantage: every resource is in version control, peer-reviewable, and reproducible across accounts.

Once you finish Phase 1–8 in the console, the level-up exercise is:

1. Install Terraform locally (`brew install terraform` or [download](https://developer.hashicorp.com/terraform/downloads))
2. Configure AWS CLI with an access key for a *new* IAM user with limited permissions (not your admin user — see [[iam]])
3. In `terraform/main.tf` (in this repo, with stubs for you to fill out), define each resource you clicked through
4. `terraform init && terraform plan && terraform apply`
5. Watch the entire lab rebuild itself in 30 seconds.

This is the move that takes a project from "tutorial follower" to "I can hand this to a coworker." See `terraform/README.md` for the suggested module structure.

---

## Troubleshooting cheat sheet

| Symptom | Likely cause |
|---------|--------------|
| Email subscription not delivering | You didn't click the SNS confirmation email. Re-send from the SNS console. |
| EventBridge rule not firing | Event pattern doesn't match. Use EventBridge → Rules → Sandbox to test patterns against sample events. |
| Lambda fails with `AccessDenied` | Execution role is missing the action you tried. Check CloudWatch Logs. |
| GuardDuty has no findings | It's working. Real findings are rare. Use "Generate sample findings" to test. |
| CloudTrail logs not appearing in S3 | Wait 15 minutes, then check the bucket policy — CloudTrail writes the policy itself; if you removed it, recreate the trail. |
| Surprise charge on your bill | Check Cost Explorer → group by Service. Most common culprits: NAT Gateway, GuardDuty after free trial, Config after the 1k items/month. |

---

## Where to go after this lab

- **Cert path:** AWS Certified Cloud Practitioner (CCP) → AWS Certified Security – Specialty
- **Concept depth:** [[defense-in-depth]], [[cloud-security-posture-management]], [[auto-remediation]]
- **Adjacent services to explore next:** AWS Security Hub (consolidates findings), AWS Inspector (vulnerability scanner), Macie (PII detection in S3)
- **Real-world equivalent of what you built:** open-source projects like [Cloud Custodian](https://cloudcustodian.io/) and commercial CSPM tools (Wiz, Prisma Cloud, Lacework) — you've now built the kindergarten version of one
