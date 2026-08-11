# ADR 004: Use AWS Lambda and API Gateway for the Rate-Limiter Service

## Status

Superseded by ADR 008: Use AWS Lambda for Internal Rate-Limit Execution

## Context

The original implementation exposed the rate limiter as an HTTP service using Amazon API Gateway in front of AWS Lambda.

This provided a managed HTTP boundary and allowed external callers to invoke the rate limiter over HTTPS.

As the architecture evolved, the rate limiter became an internal infrastructure component intended to be invoked by other workloads running within AWS. A public HTTP API was therefore no longer required.

The API Gateway layer was removed to reduce unnecessary infrastructure, latency, cost, monitoring surface, and deployment complexity.

The decision to use AWS Lambda as the initial compute platform remains valid and is documented in ADR 008.

## Decision

This decision is superseded.

The current architecture no longer uses Amazon API Gateway as the invocation boundary for the rate limiter.

See ADR 008 for the current compute and invocation architecture.

## Consequences

The following consequences of the original decision no longer apply:

- API Gateway access logging;
- API Gateway request IDs;
- API Gateway HTTP status mapping;
- API Gateway metrics and alarms;
- Lambda proxy integration;
- an externally exposed HTTP endpoint.

The following parts of the original decision remain relevant and are carried forward into ADR 008:

- stateless Lambda compute;
- horizontal scaling through Lambda concurrency;
- VPC connectivity to Valkey;
- independent scaling of compute and shared state;
- monitoring of Lambda concurrency, duration, errors, and throttles;
- the possibility of moving to ECS/Fargate if production workload characteristics favor long-running compute.

## Notes

This ADR is retained to document the architectural evolution of the service rather than being rewritten as though API Gateway had never been selected. Context

The rate limiter is exposed as an HTTP service that determines whether a request for a customer should be allowed according to a token-bucket policy.

The service has a relatively small compute responsibility:

1. validate the incoming request;
2. identify the customer's rate-limit bucket;
3. execute the token-bucket operation against Valkey;
4. return the rate-limit decision.

The service does not maintain authoritative application state within the compute process. Shared rate-limit state is stored in Valkey, as described in ADR 001.

The workload may also be bursty. A large number of rate-limit checks may arrive concurrently, while periods of little or no traffic should not require continuously running application servers.

The architecture therefore requires an HTTP entry point, horizontally scalable compute, integration with AWS networking and IAM, and sufficient observability to understand scaling and failure behavior.

## Decision

Use Amazon API Gateway as the public HTTP interface and AWS Lambda as the compute platform for the rate-limiter service.

The request path is:

```text
Client
   │
   │ HTTPS
   ▼
API Gateway
   │
   │ Lambda proxy integration
   ▼
Rate-Limiter Lambda
   │
   │ IAM-authenticated connection
   ▼
Valkey
```

API Gateway provides the external HTTP API and invokes the Lambda function using Lambda proxy integration.

The Lambda function validates the request, performs the rate-limit operation, and maps the result to the appropriate HTTP response.

The Lambda function runs inside the application's VPC so that it can communicate with the ElastiCache Serverless Valkey cache through private networking.

The Lambda function remains stateless between requests with respect to rate-limit state. Lambda execution environments may be reused for connection and resource initialization, but correctness does not depend on a request being handled by any particular execution environment.

## Consequences

### Positive

* **Horizontal scaling.** Lambda can create multiple execution environments in response to concurrent requests without requiring application-managed server instances.
* **Supports bursty workloads.** Compute capacity can scale with incoming demand rather than requiring continuously provisioned application servers.
* **Stateless compute model.** Lambda instances do not own rate-limit state, making them interchangeable and independently scalable.
* **Managed HTTP boundary.** API Gateway provides routing, HTTP integration, access logging, and service-level metrics without requiring a separate web server or load balancer.
* **AWS identity integration.** API Gateway invocation permissions, Lambda execution permissions, and Valkey authentication can all be controlled through IAM.
* **Independent scaling of compute and state.** Lambda and ElastiCache Serverless can scale independently according to their respective workloads.
* **Infrastructure as code.** API Gateway, Lambda, networking, permissions, monitoring, and Valkey can be deployed together using SAM and CloudFormation.

### Negative

* **Cold-start latency.** New Lambda execution environments incur initialization overhead. VPC networking and application initialization can contribute to this latency.
* **Concurrency limits.** Lambda scaling is constrained by AWS account and function concurrency limits. Requests may be throttled when available concurrency is exhausted.
* **Downstream pressure.** Lambda may scale more rapidly than downstream dependencies. Uncontrolled concurrency could place excessive connection or request pressure on Valkey.
* **Platform coupling.** The implementation depends on AWS Lambda, API Gateway, IAM, VPC networking, and AWS-specific deployment infrastructure.
* **Distributed observability is required.** A request crosses API Gateway, Lambda, and Valkey, requiring correlation IDs, structured logging, metrics, and tracing to diagnose failures effectively.
* **Additional network latency.** Every rate-limit decision crosses both the API Gateway/Lambda boundary and the Lambda/Valkey network boundary.

## Scalability

Lambda concurrency is an explicit part of the architecture rather than an implementation detail.

By default, the rate-limiter function uses the account's available unreserved Lambda concurrency. This allows it to scale horizontally without assigning a fixed amount of capacity to the function.

The function's concurrency is monitored using CloudWatch metrics, including:

* `ConcurrentExecutions`
* `Throttles`
* `Errors`
* `Duration`

Reserved concurrency may be configured when necessary to place an upper bound on the number of simultaneous Lambda executions.

This provides a mechanism for protecting Valkey and other downstream resources from a sudden increase in Lambda concurrency.

Reserved concurrency should be based on observed workload and downstream capacity rather than selected arbitrarily.

## Failure Semantics

The API distinguishes expected rate-limit decisions from infrastructure and application failures.

```text
Condition                         Response
------------------------------------------------
Valid request, token available   200 OK
Invalid request                  400 Bad Request
Token bucket exhausted           429 Too Many Requests
Valkey unavailable               503 Service Unavailable
Configuration/auth failure       500 Internal Server Error
Unexpected application failure   500 Internal Server Error
```

A `429` therefore indicates that the rate limiter is functioning normally and has rejected the request according to policy.

A `503` indicates that the service could not make a reliable rate-limit decision because its shared state dependency was unavailable.

This distinction allows operational failures to be monitored independently from legitimate rate-limit rejections.

## Observability

The architecture uses observability at both the API Gateway and Lambda layers.

API Gateway access logs capture request-level information including:

* request ID;
* HTTP status;
* integration status;
* integration latency; and
* total response latency.

The Lambda function emits structured logs containing information such as:

* API Gateway request ID;
* Lambda request ID;
* anonymized customer key;
* allowed or rejected result;
* remaining tokens;
* handler latency;
* cold-start state; and
* error classification.

The API Gateway request ID is propagated into the Lambda logs so that a request can be correlated across the HTTP and compute layers.

CloudWatch metrics and alarms separately monitor Lambda errors, throttling, latency, concurrency, API failures, and application-level rate-limit behavior.

## Alternatives Considered

### Long-running service on EC2

Rejected because the application does not require dedicated servers or persistent compute state.

EC2 would provide greater control over runtime behavior and connection management but would require instance provisioning, scaling, patching, health management, and load balancing for a comparatively small service.

### Containerized service on ECS or Fargate

A containerized service would provide more predictable long-running processes and greater control over connection pooling and concurrency.

This could become attractive for a sustained high-volume workload where Lambda execution characteristics or cost become limiting.

It was not selected for the current architecture because the rate limiter is small, stateless, and well suited to request-driven serverless execution. Lambda also reduces the amount of infrastructure required for the demonstration.

### Rate limiting entirely within API Gateway

Rejected because the project requires rate limits to be maintained independently for individual customer keys using the application's token-bucket policy.

The custom Lambda and Valkey implementation provides explicit control over bucket state, refill behavior, customer identification, atomicity, and rate-limit responses.

## Notes

The choice of Lambda does not imply that unlimited horizontal scaling is always desirable.

The compute layer and state layer have different scaling characteristics:

```text
Incoming traffic
      │
      ▼
 API Gateway
      │
      ▼
Lambda concurrency
      │
      │  controlled/monitored boundary
      ▼
    Valkey
```

Monitoring concurrency and downstream behavior is therefore part of the architecture.

If production workload characteristics eventually favor persistent connections, highly predictable latency, or sustained high throughput over request-driven scaling, moving the compute layer to a long-running container service could be reconsidered without changing the fundamental decision to maintain shared token-bucket state in Valkey.
