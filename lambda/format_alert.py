import boto3
import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sns = boto3.client("sns")
TOPIC_ARN = os.environ["ALERT_TOPIC_ARN"]

_SEVERITY = {
    "low":    (1, 3,  "LOW",    "[LOW]"),
    "medium": (4, 6,  "MEDIUM", "[MEDIUM]"),
    "high":   (7, 10, "HIGH",   "[HIGH]"),
}


def _severity_label(score):
    score = float(score)
    if score >= 7:
        return "HIGH", "[HIGH]"
    if score >= 4:
        return "MEDIUM", "[MEDIUM]"
    return "LOW", "[LOW]"


def _format_guardduty(event):
    d = event["detail"]
    score = d.get("severity", 0)
    label, tag = _severity_label(score)
    resource = d.get("resource", {})
    resource_type = resource.get("resourceType", "Unknown")

    lines = [
        f"{tag} GuardDuty Alert",
        f"",
        f"Type:     {d.get('type', 'Unknown')}",
        f"Severity: {score} ({label})",
        f"Account:  {event.get('account', 'Unknown')}",
        f"Region:   {event.get('region', 'Unknown')}",
        f"Time:     {event.get('time', 'Unknown')}",
        f"",
        f"Resource type: {resource_type}",
    ]

    if resource_type == "AccessKey":
        kd = resource.get("accessKeyDetails", {})
        lines.append(f"User:     {kd.get('userName', 'Unknown')} ({kd.get('userType', '')})")
        lines.append(f"Key ID:   {kd.get('accessKeyId', 'Unknown')}")
    elif resource_type == "Instance":
        inst = resource.get("instanceDetails", {})
        lines.append(f"Instance: {inst.get('instanceId', 'Unknown')} ({inst.get('instanceType', '')})")
    elif resource_type == "S3Bucket":
        s3 = resource.get("s3BucketDetails", [{}])[0]
        lines.append(f"Bucket:   {s3.get('name', 'Unknown')}")

    lines += [
        f"",
        f"Finding ID:  {d.get('id', 'Unknown')}",
        f"Console URL: https://console.aws.amazon.com/guardduty/home?region={event.get('region', 'us-east-1')}#/findings",
    ]

    subject = f"{tag} GuardDuty: {d.get('type', 'Unknown')}"
    return subject[:100], "\n".join(lines)


def _format_root_login(event):
    d = event.get("detail", {})
    lines = [
        f"[ALERT] Root User Login Detected",
        f"",
        f"Account:    {event.get('account', 'Unknown')}",
        f"Region:     {event.get('region', 'Unknown')}",
        f"Time:       {event.get('time', 'Unknown')}",
        f"Source IP:  {d.get('sourceIPAddress', 'Unknown')}",
        f"User agent: {d.get('userAgent', 'Unknown')}",
        f"",
        f"If you did not initiate this login, your account may be compromised.",
        f"Immediately review: https://console.aws.amazon.com/iam/home#/security_credentials",
    ]
    return "[ALERT] Root login on your AWS account", "\n".join(lines)


def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))

    detail_type = event.get("detail-type", "")

    if detail_type == "GuardDuty Finding":
        subject, message = _format_guardduty(event)
    elif detail_type == "AWS Console Sign In via CloudTrail":
        subject, message = _format_root_login(event)
    else:
        subject = f"AWS Security Alert: {detail_type}"[:100]
        message = json.dumps(event, indent=2)

    logger.info("Publishing: %s", subject)
    sns.publish(TopicArn=TOPIC_ARN, Subject=subject, Message=message)
    return {"status": "sent", "subject": subject}
