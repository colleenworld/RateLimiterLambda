#!/usr/bin/env bash

set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
BOOTSTRAP_STACK_NAME="${BOOTSTRAP_STACK_NAME:-payment-demo-bootstrap}"
APPLICATION_STACK_NAME="${APPLICATION_STACK_NAME:-paymentDemoStack}"
GITHUB_BRANCH="${GITHUB_BRANCH:-main}"
BOOTSTRAP_TEMPLATE="${BOOTSTRAP_TEMPLATE:-bootstrap.yaml}"

###########################################################
# Resolve GitHub repository
###########################################################

REMOTE_URL="$(git remote get-url origin)"

if [[ "$REMOTE_URL" =~ github\.com[:/]([^/]+)/([^/.]+)(\.git)?$ ]]; then
    GITHUB_OWNER="${BASH_REMATCH[1]}"
    GITHUB_REPOSITORY="${BASH_REMATCH[2]}"
else
    echo "Unable to determine GitHub repository from origin:"
    echo "  $REMOTE_URL"
    echo
    echo "Expected an origin such as:"
    echo "  git@github.com:owner/repository.git"
    echo "  https://github.com/owner/repository.git"
    exit 1
fi

GITHUB_REPOSITORY_FULL="${GITHUB_OWNER}/${GITHUB_REPOSITORY}"

###########################################################
# Detect GitHub OIDC provider
###########################################################

echo "Checking for existing GitHub OIDC provider..."

OIDC_PROVIDER_ARN="$(
    aws iam list-open-id-connect-providers \
        --query "OpenIDConnectProviderList[?ends_with(Arn, 'token.actions.githubusercontent.com')].Arn | [0]" \
        --output text
)"

if [[ -z "$OIDC_PROVIDER_ARN" || "$OIDC_PROVIDER_ARN" == "None" ]]; then
    CREATE_OIDC_PROVIDER="true"
    OIDC_PROVIDER_ARN=""

    echo "No GitHub OIDC provider found."
    echo "The bootstrap stack will create one."
else
    CREATE_OIDC_PROVIDER="false"

    echo "Existing GitHub OIDC provider found:"
    echo "  $OIDC_PROVIDER_ARN"
fi

###########################################################
# Show configuration
###########################################################

echo
echo "Bootstrap configuration"
echo "-----------------------"
echo "AWS region:          $AWS_REGION"
echo "Bootstrap stack:     $BOOTSTRAP_STACK_NAME"
echo "Application stack:   $APPLICATION_STACK_NAME"
echo "GitHub repository:   $GITHUB_REPOSITORY_FULL"
echo "GitHub branch:       $GITHUB_BRANCH"
echo "Create OIDC:         $CREATE_OIDC_PROVIDER"

if [[ -n "$OIDC_PROVIDER_ARN" ]]; then
    echo "OIDC provider ARN:   $OIDC_PROVIDER_ARN"
fi

echo

###########################################################
# Deploy bootstrap stack
###########################################################

aws cloudformation deploy \
    --template-file "$BOOTSTRAP_TEMPLATE" \
    --stack-name "$BOOTSTRAP_STACK_NAME" \
    --region "$AWS_REGION" \
    --capabilities CAPABILITY_NAMED_IAM \
    --parameter-overrides \
        GitHubRepositoryOwner="$GITHUB_OWNER" \
        GitHubRepository="$GITHUB_REPOSITORY" \
        GitHubBranch="$GITHUB_BRANCH" \
        ApplicationStackName="$APPLICATION_STACK_NAME" \
        CreateGitHubOidcProvider="$CREATE_OIDC_PROVIDER" \
        ExistingGitHubOidcProviderArn="$OIDC_PROVIDER_ARN"

###########################################################
# Read stack outputs
###########################################################

echo
echo "Reading bootstrap outputs..."

GITHUB_DEPLOY_ROLE_ARN="$(
    aws cloudformation describe-stacks \
        --stack-name "$BOOTSTRAP_STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='GitHubDeployRoleArn'].OutputValue | [0]" \
        --output text
)"

CLOUDFORMATION_EXECUTION_ROLE_ARN="$(
    aws cloudformation describe-stacks \
        --stack-name "$BOOTSTRAP_STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='CloudFormationExecutionRoleArn'].OutputValue | [0]" \
        --output text
)"

SAM_ARTIFACT_BUCKET="$(
    aws cloudformation describe-stacks \
        --stack-name "$BOOTSTRAP_STACK_NAME" \
        --region "$AWS_REGION" \
        --query "Stacks[0].Outputs[?OutputKey=='SamArtifactBucketName'].OutputValue | [0]" \
        --output text
)"

###########################################################
# Validate outputs
###########################################################

if [[ -z "$GITHUB_DEPLOY_ROLE_ARN" || "$GITHUB_DEPLOY_ROLE_ARN" == "None" ]]; then
    echo "Unable to read GitHubDeployRoleArn from bootstrap stack."
    exit 1
fi

if [[ -z "$CLOUDFORMATION_EXECUTION_ROLE_ARN" || "$CLOUDFORMATION_EXECUTION_ROLE_ARN" == "None" ]]; then
    echo "Unable to read CloudFormationExecutionRoleArn from bootstrap stack."
    exit 1
fi

if [[ -z "$SAM_ARTIFACT_BUCKET" || "$SAM_ARTIFACT_BUCKET" == "None" ]]; then
    echo "Unable to read SamArtifactBucketName from bootstrap stack."
    exit 1
fi

echo
echo "Bootstrap outputs"
echo "-----------------"
echo "AWS deploy role:                $GITHUB_DEPLOY_ROLE_ARN"
echo "CloudFormation execution role:  $CLOUDFORMATION_EXECUTION_ROLE_ARN"
echo "SAM artifact bucket:            $SAM_ARTIFACT_BUCKET"

###########################################################
# Configure GitHub repository variables
###########################################################

echo
echo "Configuring GitHub repository variables..."

if ! command -v gh >/dev/null 2>&1; then
    echo
    echo "GitHub CLI (gh) is not installed."
    echo "Skipping automatic GitHub variable configuration."
    echo
    echo "Set these repository variables manually:"
    echo
    echo "  AWS_REGION=$AWS_REGION"
    echo "  AWS_DEPLOY_ROLE_ARN=$GITHUB_DEPLOY_ROLE_ARN"
    echo "  CLOUDFORMATION_EXECUTION_ROLE_ARN=$CLOUDFORMATION_EXECUTION_ROLE_ARN"
    echo "  SAM_ARTIFACT_BUCKET=$SAM_ARTIFACT_BUCKET"
    echo "  APPLICATION_STACK_NAME=$APPLICATION_STACK_NAME"

    exit 0
fi

if ! gh auth status >/dev/null 2>&1; then
    echo
    echo "GitHub CLI is installed but not authenticated."
    echo
    echo "Run:"
    echo "  gh auth login"
    echo
    echo "Then rerun this script to configure repository variables."

    exit 0
fi

gh variable set \
    AWS_REGION \
    --repo "$GITHUB_REPOSITORY_FULL" \
    --body "$AWS_REGION"

gh variable set \
    AWS_DEPLOY_ROLE_ARN \
    --repo "$GITHUB_REPOSITORY_FULL" \
    --body "$GITHUB_DEPLOY_ROLE_ARN"

gh variable set \
    CLOUDFORMATION_EXECUTION_ROLE_ARN \
    --repo "$GITHUB_REPOSITORY_FULL" \
    --body "$CLOUDFORMATION_EXECUTION_ROLE_ARN"

gh variable set \
    SAM_ARTIFACT_BUCKET \
    --repo "$GITHUB_REPOSITORY_FULL" \
    --body "$SAM_ARTIFACT_BUCKET"

gh variable set \
    APPLICATION_STACK_NAME \
    --repo "$GITHUB_REPOSITORY_FULL" \
    --body "$APPLICATION_STACK_NAME"

###########################################################
# Complete
###########################################################

echo
echo "GitHub repository variables configured successfully."
echo
echo "Repository:"
echo "  $GITHUB_REPOSITORY_FULL"
echo
echo "Variables:"
echo "  AWS_REGION"
echo "  AWS_DEPLOY_ROLE_ARN"
echo "  CLOUDFORMATION_EXECUTION_ROLE_ARN"
echo "  SAM_ARTIFACT_BUCKET"
echo "  APPLICATION_STACK_NAME"
echo
echo "Bootstrap complete."