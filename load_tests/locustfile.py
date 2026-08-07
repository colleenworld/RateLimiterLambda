import json
import os
import time
import uuid
import boto3
from locust import User, between, task

REGION = os.environ.get("AWS_REGION", "us-west-2")
ENVIRONMENT = os.environ.get("TARGET_ENV", "dev")

def get_stack_name(environment):
    if environment == "dev":
        return "paymentDemoStack"

    return f"{environment}-paymentDemoStack"


def get_function_name():
    stack_name = get_stack_name(ENVIRONMENT)

    cloudformation = boto3.client(
        "cloudformation",
        region_name=REGION,
    )

    response = cloudformation.describe_stacks(
        StackName=stack_name,
    )

    outputs = response["Stacks"][0].get("Outputs", [])

    for output in outputs:
        if output["OutputKey"] == "RateLimiterFunctionName":
            return output["OutputValue"]

    raise RuntimeError(
        f"Stack '{stack_name}' does not contain "
        "RateLimiterFunctionName"
    )


FUNCTION_NAME = get_function_name()


class RateLimiterUser(User):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.lambda_client = boto3.client(
            "lambda",
            region_name=REGION,
        )

        # Each simulated user gets its own bucket.
        self.customer_id = f"locust-{uuid.uuid4()}"

    @task
    def check_rate_limit(self):
        start = time.perf_counter()

        try:
            response = self.lambda_client.invoke(
                FunctionName=FUNCTION_NAME,
                InvocationType="RequestResponse",
                Payload=json.dumps({
                    "customer_id": self.customer_id,
                }).encode("utf-8"),
            )

            elapsed = (
                time.perf_counter() - start
            ) * 1000

            payload = json.load(
                response["Payload"]
            )

            function_error = response.get(
                "FunctionError"
            )

            if function_error:
                raise RuntimeError(
                    f"Lambda error: "
                    f"{function_error}: {payload}"
                )

            if "allowed" not in payload:
                raise RuntimeError(
                    f"Unexpected response: {payload}"
                )

            self.environment.events.request.fire(
                request_type="Lambda",
                name="rate-limit",
                response_time=elapsed,
                response_length=len(
                    json.dumps(payload)
                ),
                response=payload,
                context={},
                exception=None,
            )

        except Exception as error:
            elapsed = (
                time.perf_counter() - start
            ) * 1000

            self.environment.events.request.fire(
                request_type="Lambda",
                name="rate-limit",
                response_time=elapsed,
                response_length=0,
                response=None,
                context={},
                exception=error,
            )