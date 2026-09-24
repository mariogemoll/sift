#!/usr/bin/env bash
# Forward a local port to sift's production database, through a running API
# task over Session Manager (ECS Exec). The database accepts connections from
# the service's tasks only, so a task is the one place a tunnel can start from.
# Needs the Session Manager plugin for the AWS CLI. Runs until interrupted, or
# until the task is replaced by a deploy.
#
#   ./db-tunnel.sh [local-port]     # default 15432
set -euo pipefail

REGION=eu-west-2
CLUSTER=sift
SERVICE=sift
DATABASE=sift
CONTAINER=api
LOCAL_PORT=${1:-15432}

command -v session-manager-plugin >/dev/null || {
  echo "session-manager-plugin not found: brew install --cask session-manager-plugin" >&2
  exit 1
}

task=$(aws ecs list-tasks --cluster "$CLUSTER" --service-name "$SERVICE" --desired-status RUNNING \
  --region "$REGION" --query 'taskArns[0]' --output text)
[[ "$task" != "None" ]] || { echo "no running task in service $SERVICE" >&2; exit 1; }
task_id=${task##*/}

read -r runtime exec_status < <(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" --region "$REGION" \
  --query "tasks[0].containers[?name=='$CONTAINER'] | [0].[runtimeId, managedAgents[?name=='ExecuteCommandAgent'] | [0].lastStatus]" \
  --output text)
[[ "$exec_status" == "RUNNING" ]] || {
  echo "ECS Exec is not running in task $task_id (agent: $exec_status); tasks started before it was" \
    "enabled need replacing: aws ecs update-service --cluster $CLUSTER --service $SERVICE --force-new-deployment" >&2
  exit 1
}

read -r host port < <(aws rds describe-db-instances --db-instance-identifier "$DATABASE" --region "$REGION" \
  --query 'DBInstances[0].Endpoint.[Address, Port]' --output text)

cat <<EOF
Tunnel to $host:$port via task $task_id

  host localhost   port $LOCAL_PORT   database $DATABASE   user $DATABASE
  password: aws secretsmanager get-secret-value --region $REGION --secret-id $DATABASE/database-url \\
              --query SecretString --output text | sed -E 's|.*://[^:]+:([^@]+)@.*|\\1|'

Ctrl-C to close.
EOF

aws ssm start-session --region "$REGION" \
  --target "ecs:${CLUSTER}_${task_id}_${runtime}" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "host=$host,portNumber=$port,localPortNumber=$LOCAL_PORT"
