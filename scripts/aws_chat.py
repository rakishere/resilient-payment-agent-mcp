"""Call the AWS_IAM-protected API Gateway /chat URL using local AWS credentials."""
import argparse
import json
import os

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True, help="ChatUrl from SAM output")
    parser.add_argument("--payment-id", required=True)
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--region", default=os.getenv("AWS_DEFAULT_REGION", "us-east-1"))
    args = parser.parse_args()
    payload = json.dumps({"payment_intent_id": args.payment_id, "use_ai": not args.no_ai}).encode()
    credentials = boto3.Session().get_credentials()
    if credentials is None:
        parser.error("Configure AWS CLI credentials first (aws configure or aws sso login)")
    req = AWSRequest(method="POST", url=args.url, data=payload,
                     headers={"Content-Type": "application/json"})
    SigV4Auth(credentials.get_frozen_credentials(), "execute-api", args.region).add_auth(req)
    with httpx.Client(timeout=30) as client:
        res = client.post(args.url, content=payload, headers=dict(req.headers))
    print("HTTP", res.status_code)
    try:
        print(json.dumps(res.json(), indent=2))
    except ValueError:
        print(res.text)
    res.raise_for_status()


if __name__ == "__main__":
    main()
