#!/usr/bin/env bash
set -euo pipefail

repo_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
yc_bin=${YC_BIN:-yc}
yc_profile=${YC_PROFILE:-default}
function_name=${FUNCTION_NAME:-nest-environment-collector}
trigger_name=${TRIGGER_NAME:-nest-environment-collector-5m}

: "${SERVICE_ACCOUNT_ID:?Set SERVICE_ACCOUNT_ID}"
: "${NEST_SECRET_ID:?Set NEST_SECRET_ID}"
: "${NEST_DEVICE_ACCESS_PROJECT_ID:?Set NEST_DEVICE_ACCESS_PROJECT_ID}"
: "${YDB_DATABASE:?Set YDB_DATABASE}"

package_dir=$(mktemp -d)
trap 'rm -rf -- "$package_dir"' EXIT
install -d "$package_dir/nest_climate"
install -m 0644 "$repo_dir/nest_climate/"*.py "$package_dir/nest_climate/"
install -m 0644 "$repo_dir/deployments/yandex_function/index.py" "$package_dir/index.py"
install -m 0644 "$repo_dir/deployments/yandex_function/requirements.txt" "$package_dir/requirements.txt"

if ! "$yc_bin" --profile "$yc_profile" serverless function get \
    --name "$function_name" >/dev/null 2>&1; then
    "$yc_bin" --profile "$yc_profile" serverless function create \
        --name "$function_name" \
        --description "Collect Nest thermostat climate readings into YDB"
fi

"$yc_bin" --profile "$yc_profile" serverless function version create \
    --function-name "$function_name" \
    --runtime python312 \
    --entrypoint index.handler \
    --memory 256MB \
    --execution-timeout 30s \
    --service-account-id "$SERVICE_ACCOUNT_ID" \
    --source-path "$package_dir" \
    --environment "NEST_DEVICE_ACCESS_PROJECT_ID=$NEST_DEVICE_ACCESS_PROJECT_ID" \
    --environment "YDB_ENDPOINT=grpcs://ydb.serverless.yandexcloud.net:2135" \
    --environment "YDB_DATABASE=$YDB_DATABASE" \
    --environment "YDB_TABLE=nest_environment_readings" \
    --secret "environment-variable=NEST_OAUTH_CLIENT_ID,id=$NEST_SECRET_ID,key=client-id" \
    --secret "environment-variable=NEST_OAUTH_CLIENT_SECRET,id=$NEST_SECRET_ID,key=client-secret" \
    --secret "environment-variable=NEST_OAUTH_REFRESH_TOKEN,id=$NEST_SECRET_ID,key=refresh-token"

"$yc_bin" --profile "$yc_profile" serverless function invoke \
    "$function_name" --data '{"action":"create-schema"}'
"$yc_bin" --profile "$yc_profile" serverless function invoke "$function_name"

if ! "$yc_bin" --profile "$yc_profile" serverless trigger get \
    --name "$trigger_name" >/dev/null 2>&1; then
    "$yc_bin" --profile "$yc_profile" serverless trigger create timer \
        --name "$trigger_name" \
        --description "Collect both Nest thermostats every five minutes" \
        --cron-expression '0/5 * ? * * *' \
        --invoke-function-name "$function_name" \
        --invoke-function-service-account-id "$SERVICE_ACCOUNT_ID"
fi
