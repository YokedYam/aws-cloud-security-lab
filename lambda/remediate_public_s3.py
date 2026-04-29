import boto3
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")


def lambda_handler(event, context):
    logger.info("Received event: %s", json.dumps(event))

    try:
        bucket_name = (
            event["detail"]
            ["newEvaluationResult"]
            ["evaluationResultIdentifier"]
            ["evaluationResultQualifier"]
            ["resourceId"]
        )
    except KeyError as e:
        logger.error("Could not extract bucket name from event: %s", e)
        return {"status": "error", "reason": "missing key in event"}

    logger.info("Remediating bucket: %s", bucket_name)

    s3.put_public_access_block(
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )

    logger.info("Public access block re-enabled on %s", bucket_name)
    return {"status": "remediated", "bucket": bucket_name}
