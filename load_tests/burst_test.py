import argparse
import json
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import boto3


REGION = "us-west-2"
DEFAULT_CONCURRENCY = 30


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a concurrent burst test against the deployed rate limiter."
    )

    parser.add_argument(
        "--environment",
        "-e",
        required=True,
        help="Deployment environment, e.g. dev, staging, prod",
    )

    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Number of concurrent invocations (default: {DEFAULT_CONCURRENCY})",
    )

    parser.add_argument(
        "--region",
        default=REGION,
        help=f"AWS region (default: {REGION})",
    )

    return parser.parse_args()


def get_stack_name(environment):
    if environment == "dev":
        return "paymentDemoStack"

    return f"{environment}-paymentDemoStack"


def get_function_name(cloudformation_client, stack_name):
    response = cloudformation_client.describe_stacks(
        StackName=stack_name,
    )

    outputs = response["Stacks"][0].get("Outputs", [])

    for output in outputs:
        if output["OutputKey"] == "RateLimiterFunctionName":
            return output["OutputValue"]

    raise RuntimeError(
        f"CloudFormation stack '{stack_name}' does not contain "
        "a RateLimiterFunctionName output"
    )


def invoke(lambda_client, function_name, customer_id, request_number):
    response = lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "customer_id": customer_id,
        }).encode("utf-8"),
    )

    payload = json.load(response["Payload"])

    function_error = response.get("FunctionError")

    if function_error:
        raise RuntimeError(
            f"Lambda invocation failed: {function_error}: {payload}"
        )

    return {
        "request_number": request_number,
        "status_code": response["StatusCode"],
        "payload": payload,
    }


def run_burst(
    lambda_client,
    function_name,
    customer_id,
    concurrency,
):
    with ThreadPoolExecutor(
        max_workers=concurrency
    ) as executor:

        futures = [
            executor.submit(
                invoke,
                lambda_client,
                function_name,
                customer_id,
                request_number,
            )
            for request_number in range(1, concurrency + 1)
        ]

        return [
            future.result()
            for future in as_completed(futures)
        ]


def classify(result):
    payload = result["payload"]

    if payload.get("allowed") is True:
        return "allowed"

    if payload.get("allowed") is False:
        return "rejected"

    return "unexpected"


def print_results(results, concurrency):
    counts = Counter(
        classify(result)
        for result in results
    )

    print("\nBurst test results")
    print("==================")
    print(f"Requests:   {concurrency}")
    print(f"Allowed:    {counts['allowed']}")
    print(f"Rejected:   {counts['rejected']}")
    print(f"Unexpected: {counts['unexpected']}")

    unexpected = [
        result
        for result in results
        if classify(result) == "unexpected"
    ]

    if unexpected:
        print("\nUnexpected responses:")

        for result in unexpected:
            print(
                f"Request {result['request_number']}: "
                f"{result['payload']}"
            )

    assert len(results) == concurrency, (
        f"Expected {concurrency} results, got {len(results)}"
    )

    assert counts["unexpected"] == 0, (
        f"Received {counts['unexpected']} unexpected responses"
    )

    assert (
        counts["allowed"] + counts["rejected"]
        == concurrency
    )

    print("\nPASS: every invocation produced a rate-limit decision")


def main():
    args = parse_args()

    stack_name = get_stack_name(args.environment)

    cloudformation = boto3.client(
        "cloudformation",
        region_name=args.region,
    )

    lambda_client = boto3.client(
        "lambda",
        region_name=args.region,
    )

    function_name = get_function_name(
        cloudformation,
        stack_name,
    )

    # All requests in this run deliberately use the same new bucket.
    customer_id = f"burst-{uuid.uuid4()}"

    print("Burst test")
    print("==========")
    print(f"Environment: {args.environment}")
    print(f"Region:      {args.region}")
    print(f"Stack:       {stack_name}")
    print(f"Function:    {function_name}")
    print(f"Customer:    {customer_id}")
    print(f"Concurrency: {args.concurrency}")

    results = run_burst(
        lambda_client=lambda_client,
        function_name=function_name,
        customer_id=customer_id,
        concurrency=args.concurrency,
    )

    print_results(
        results,
        args.concurrency,
    )


if __name__ == "__main__":
    main()