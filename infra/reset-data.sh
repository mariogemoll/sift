#!/usr/bin/env bash
# Empty sift's production tables (papers, batches, items, texts, judgments,
# verdicts). Schema, migration revision and secrets are untouched. Runs as a
# one-off Fargate task on the service's current task definition, in its network,
# the way the deploy workflow runs migrations.
set -euo pipefail

REGION=eu-west-2
CLUSTER=sift
SERVICE=sift

taskdef=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --region "$REGION" \
  --query 'services[0].taskDefinition' --output text)
network=$(aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --region "$REGION" \
  --query 'services[0].networkConfiguration.awsvpcConfiguration' --output json)
subnets=$(python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["subnets"]))' <<<"$network")
groups=$(python3 -c 'import json,sys; print(",".join(json.load(sys.stdin)["securityGroups"]))' <<<"$network")

read -r -d '' script <<'PY' || true
import asyncio, os, asyncpg

async def main():
    url = os.environ["SIFT_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://", 1)
    connection = await asyncpg.connect(url)
    before = await connection.fetchval("select count(*) from papers")
    await connection.execute(
        "truncate table verdicts, judgments, paper_texts, batch_items, batches, papers"
        " restart identity cascade"
    )
    after = await connection.fetchval("select count(*) from papers")
    revision = await connection.fetchval("select version_num from alembic_version")
    print(f"papers before={before} after={after} revision={revision}")
    await connection.close()

asyncio.run(main())
PY

overrides=$(python3 -c 'import json,sys; print(json.dumps({"containerOverrides": [{"name": "api", "command": ["python", "-c", sys.argv[1]]}]}))' "$script")

task=$(aws ecs run-task --cluster "$CLUSTER" --region "$REGION" --task-definition "$taskdef" \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[$subnets],securityGroups=[$groups],assignPublicIp=ENABLED}" \
  --overrides "$overrides" --query 'tasks[0].taskArn' --output text)
echo "task ${task##*/} on ${taskdef##*/}; waiting for it to stop"

aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$task" --region "$REGION"
echo "exit code: $(aws ecs describe-tasks --cluster "$CLUSTER" --tasks "$task" --region "$REGION" \
  --query 'tasks[0].containers[0].exitCode' --output text)"
aws logs get-log-events --region "$REGION" --log-group-name /ecs/sift \
  --log-stream-name "api/api/${task##*/}" --query 'events[].message' --output text
