# ADR 007: Use GitHub OIDC and Separate Deployment Roles for AWS Deployment

## Status

Accepted

## Context

The project is deployed to AWS through GitHub Actions.

The deployment workflow must be able to:

1. authenticate from GitHub Actions to AWS;
2. upload SAM deployment artifacts to S3;
3. create or update the application CloudFormation stack;
4. pass an execution role to CloudFormation; and
5. avoid requiring developers to store long-lived AWS access keys in GitHub.

A simple approach would be to create an IAM user for GitHub Actions and store its access key and secret access key as GitHub repository secrets.

That approach introduces long-lived credentials that must be created, distributed, protected, rotated, and revoked manually.

GitHub Actions supports OpenID Connect (OIDC), allowing a workflow to exchange a GitHub-issued identity token for temporary AWS credentials.

The deployment architecture must also account for the distinction between actions performed directly by the GitHub workflow and actions performed later by CloudFormation.

For example:

```
GitHub Actions
      │
      ├── upload SAM artifacts to S3
      │
      ├── create/update CloudFormation stack
      │
      └── pass execution role
      │
      ▼
CloudFormation
      │
      ├── create Lambda
      ├── create DynamoDB
      ├── create networking
      ├── create ElastiCache
      ├── create monitoring
      └── create application IAM resources
```
Using a single broadly privileged role for both responsibilities would work, but would give the GitHub workflow direct permissions that are only required by CloudFormation.

The repository is also intended to be cloned and deployed by other users and organizations, so AWS account IDs, GitHub owners, regions, role ARNs, and SAM bucket names should not be hard-coded into the project.

## Decision

Use GitHub Actions OIDC to authenticate deployment workflows to AWS.

Do not create or store long-lived AWS access keys for CI/CD.

Create two separate IAM roles:

- GitHubDeployRole
- CloudFormationExecutionRole

The GitHub deployment role is assumed directly by GitHub Actions through OIDC.

The CloudFormation execution role is assumed by the CloudFormation service while deploying application resources.

The relationship is:
```
GitHub Actions
      │
      │ OIDC
      ▼
GitHubDeployRole
      │
      ├── upload SAM artifacts
      ├── manage application stack
      └── iam:PassRole
                │
                ▼
CloudFormationExecutionRole
                │
                ▼
         CloudFormation
                │
                ▼
       Application resources
```

## GitHub OIDC Trust

The GitHub deployment role trusts the GitHub Actions OIDC provider:

token.actions.githubusercontent.com

The trust policy requires the GitHub token audience to be:

sts.amazonaws.com

and restricts the token subject to the configured repository and branch.

Conceptually:

repo:<repository-owner>/<repository>:ref:refs/heads/<branch>

The repository owner, repository name, and branch are supplied during bootstrap rather than hard-coded into the template.

This allows the same project to be cloned or forked into another GitHub account or organization while preserving a narrowly scoped trust relationship.

GitHub Deployment Role Responsibilities

The GitHub deployment role has only the permissions required by the deployment workflow itself.

These include:

- uploading and reading SAM artifacts in the deployment S3 bucket;
- creating and updating the root application CloudFormation stack;
- describing stack and change-set state required by SAM deployment; and
- passing the CloudFormation execution role to the CloudFormation service.

The GitHub deployment role does not need direct permission to create every application resource.

For example, GitHub does not need direct permission to create:

- Lambda functions
- DynamoDB tables
- ElastiCache resources
- VPC resources
- CloudWatch alarms
- application IAM roles

Those operations are performed by CloudFormation using the execution role.

CloudFormation Execution Role Responsibilities

The CloudFormation execution role is trusted only by:

cloudformation.amazonaws.com

It contains the permissions required to create, modify, and delete the application infrastructure defined by the SAM and CloudFormation templates.

This includes permissions for services such as:

- Lambda
- IAM
- EC2 networking
- ElastiCache
- DynamoDB
- CloudWatch
- CloudWatch Logs
- SNS

The exact permissions should be scoped as narrowly as practical for the resources managed by the application.

Separating this role from the GitHub deployment role reduces the permissions directly available to a GitHub Actions workflow.

## SAM Artifact Bucket

The bootstrap stack creates a dedicated S3 bucket for SAM deployment artifacts.

The GitHub deployment role is granted object-level permissions such as:

- s3:GetObject
- s3:GetObjectVersion
- s3:PutObject
- s3:DeleteObject

against objects in that bucket.

Bucket-level permissions such as:

- s3:GetBucketLocation
- s3:ListBucket

are granted separately against the bucket ARN.

Using a bootstrap-managed bucket avoids relying on an account-specific SAM CLI managed bucket name and makes deployment configuration portable between AWS accounts.

## Bootstrap Process

Deployment prerequisites are provisioned through a separate bootstrap CloudFormation stack.

The bootstrap stack creates or configures:

- GitHub OIDC provider
- GitHub deployment role
- CloudFormation execution role
- SAM artifact bucket

A bootstrap shell script provides the user-facing setup process.

The script:

determines the GitHub repository owner and repository name from the local Git origin;
reads the desired AWS region from configuration;
checks whether the AWS account already contains the GitHub Actions OIDC provider;
reuses the provider if present or instructs CloudFormation to create it;
deploys the bootstrap stack;
reads the resulting stack outputs; and
configures GitHub repository variables using the GitHub CLI when available.

The intended installation flow is:
```
clone repository
      │
      ▼
configure AWS credentials locally
      │
      ▼
run bootstrap.sh
      │
      ├── detect GitHub repository
      ├── detect/reuse OIDC provider
      ├── create deployment roles
      ├── create artifact bucket
      └── configure GitHub variables
      │
      ▼
GitHub Actions ready to deploy
```
## Repository Variables

Deployment-specific configuration is stored as GitHub repository variables rather than hard-coded into workflow files.

The bootstrap process configures values including:

- AWS_REGION
- AWS_DEPLOY_ROLE_ARN
- CLOUDFORMATION_EXECUTION_ROLE_ARN
- SAM_ARTIFACT_BUCKET
- APPLICATION_STACK_NAME

These values are configuration, not credentials.

Temporary AWS credentials are obtained at workflow runtime through GitHub OIDC.

The deployment workflow therefore remains portable across AWS accounts, regions, and GitHub organizations.

## Consequences
### Positive
- **No long-lived AWS credentials in GitHub.** Deployment workflows use temporary AWS credentials obtained through OIDC.
- **No credential rotation burden.** There are no stored CI/CD access keys that need periodic replacement.
- **Repository-scoped trust.** The deployment role can restrict access to a specific GitHub repository and branch.
- **Separation of responsibilities.** GitHub performs deployment orchestration while CloudFormation performs infrastructure provisioning.
- **Reduced GitHub privileges.** The GitHub role does not require direct permission to provision every application resource.
- **Auditable identity.** AWS actions performed by CI/CD occur through an explicit assumed role rather than a shared IAM user.
- **Portable deployment.** Account IDs, repository owners, regions, bucket names, and role ARNs are resolved during bootstrap rather than embedded in source files.
- **Reusable OIDC provider.** Existing GitHub OIDC providers in an AWS account can be reused.
- **Infrastructure as code.** CI/CD prerequisites are created through CloudFormation rather than manual IAM setup.
### Negative
- **Bootstrap privileges are required.** The person initially installing the project must have enough AWS permissions to create IAM roles, an OIDC provider when necessary, and the artifact bucket.
- **More IAM resources.** The deployment model contains two roles instead of a single deployment identity.
- **Policy design is more complex.** Permissions must be divided correctly between the GitHub role and CloudFormation execution role.
- **iam:PassRole must be configured carefully.** The GitHub role must be able to pass the execution role, but only to CloudFormation.
- **GitHub OIDC trust configuration is security-sensitive.** An overly broad sub condition could permit unintended repositories or branches to assume the role.
- **Bootstrap and application infrastructure have separate lifecycles.** The deployment roles and artifact bucket are intentionally managed outside the main application stack.
## Alternatives Considered
IAM user with GitHub repository secrets

Rejected because it requires long-lived AWS access keys.

Those credentials would need to be stored in GitHub, rotated periodically, and revoked if compromised.

OIDC provides temporary credentials without requiring a stored AWS secret.

Single GitHub deployment role with full infrastructure permissions

A single role could be granted permission to both invoke CloudFormation and directly create every AWS resource used by the application.

This was rejected because the GitHub workflow itself does not need those permissions.

Using a CloudFormation execution role creates a clearer trust boundary:
```
GitHub role
    │
    │ deployment orchestration
    ▼
CloudFormation role
    │
    │ resource provisioning
    ▼
AWS infrastructure
```
### Use the developer's AWS credentials in GitHub

Rejected.

Developer credentials should not be copied into CI/CD systems, and deployment should not depend on an individual's AWS identity.

Hard-code repository and AWS configuration

Rejected because the project is intended to be reusable.

Hard-coded values such as:

- AWS account ID
- GitHub organization
- GitHub repository
- AWS region
- role ARN
- S3 bucket name

would require source changes for each installation and could result in incorrect trust relationships.

The bootstrap process resolves or generates these values instead.

### Require users to configure IAM manually

Manual setup would reduce bootstrap infrastructure but increase installation complexity and the likelihood of permissions errors.

A repeatable CloudFormation bootstrap stack documents the required IAM model and makes installation more deterministic.

## Security Model

The deployment trust chain is:
```
GitHub repository + branch
          │
          │ GitHub OIDC token
          ▼
AWS STS AssumeRoleWithWebIdentity
          │
          ▼
   GitHubDeployRole
          │
          │ iam:PassRole
          ▼
CloudFormationExecutionRole
          │
          ▼
     Application stack
```
Each boundary has a distinct control:

GitHub OIDC trust policy controls which repository and branch may assume the deployment role.
GitHub deployment permissions control what the workflow may do directly.
iam:PassRole restricts which execution role GitHub may give to CloudFormation.
CloudFormation execution permissions control which infrastructure resources CloudFormation may manage.

The GitHub Actions workflow must explicitly request OIDC token access:
```
permissions:
  id-token: write
  contents: read
```
and assumes the role using the repository-configured role ARN and AWS region.

## Failure Modes

OIDC and deployment failures are distinguished by where they occur.

Examples include:
```
GitHub cannot obtain OIDC token
        │
        └── workflow permission/configuration problem

AWS rejects AssumeRoleWithWebIdentity
        │
        └── trust policy or OIDC provider problem

SAM cannot upload artifact
        │
        └── GitHub role S3 permission problem

CloudFormation cannot assume execution role
        │
        └── PassRole or trust-policy problem

CloudFormation cannot create resource
        │
        └── execution-role permission problem
        
```
This separation makes deployment failures easier to diagnose than a model where all operations use one highly privileged identity.

##  Notes

The deployment roles are infrastructure bootstrap resources rather than application runtime resources.

They are intentionally created separately from the application stack because the GitHub role must already exist before GitHub Actions can deploy that stack.

The resulting lifecycle is:
```
one-time bootstrap
       │
       ▼
GitHub/AWS deployment trust established
       │
       ▼
repeatable CI/CD deployments
       │
       ▼
application stacks
```
The bootstrap process should generally be rerun only when deployment configuration changes, such as:

- moving the repository;
- changing the trusted branch;
- changing the AWS region;
- recreating deployment roles; or
- changing the SAM artifact configuration.

Application deployments themselves continue through the normal GitHub Actions workflow.