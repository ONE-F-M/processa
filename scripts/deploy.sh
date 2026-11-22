#!/usr/bin/env bash
# Deploys processa to a bench. The deploy workflows fetch this file from the branch they deploy and run it.
# Usage: bash deploy.sh <bench-dir> <branch>
# A bench still on the one_bpmn folder moves to processa on its first run, together with the apps that import it.
set -eo pipefail

BENCH="${1:?bench directory}"
BRANCH="${2:?branch}"
NAME="$(basename "$BENCH")"
SIBLINGS="one_fm frappe_agile onefm_mcp"
PROSALLY_QUEUE="bpmn_ai_prosally"

export PATH="$HOME/.local/bin:$PATH"
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=8192}"
command -v bench && bench --version
command -v node && node --version
command -v yarn && yarn --version

cd "$BENCH"
SITE="$(jq -r .default_site sites/common_site_config.json)"
PORT="$(jq -r .webserver_port sites/common_site_config.json)"

# One deploy at a time per bench, across one_fm, processa and frappe_agile.
exec 9>"$BENCH/config/deploy.lock"
flock -w 1500 9

# A running long job holds the worker stop below for up to stopwaitsecs with every worker down.
REDIS_QUEUE="$(jq -r .redis_queue sites/common_site_config.json)"
LONG_RUNNING="rq:wip:$(echo "${BENCH#/}" | tr / -):long"
for attempt in $(seq 1 40); do
	JOB="$(redis-cli -u "$REDIS_QUEUE" zrangebyscore "$LONG_RUNNING" "$(date +%s)" +inf limit 0 1)"
	if [ -z "$JOB" ]; then break; fi
	echo "Long job $JOB running: $(redis-cli -u "$REDIS_QUEUE" hget "rq:job:$JOB" description | cut -c1-160)"
	if [ "$attempt" -eq 40 ]; then echo "Deploy stopped: the long job did not finish in 20 minutes. Nothing was changed."; exit 1; fi
	sleep 30
done

# supervisorctl status exits non-zero when any program is stopped, so read it once.
PROGRAMS="$(sudo supervisorctl status || true)"
WORKERS=""
for g in "$NAME-workers" "$NAME-bpmn-workers"; do
	if grep -q "^$g:" <<<"$PROGRAMS"; then WORKERS="$WORKERS $g:"; fi
done
restart_on_error() {
	status=$?
	if [ $status -ne 0 ]; then
		sudo supervisorctl start $WORKERS || true
		sudo supervisorctl restart "$NAME-web:" || true
	fi
}
trap restart_on_error EXIT

# Workers stop before the pull: a job on old code fails against the new files, and migrate needs them stopped.
sudo supervisorctl stop $WORKERS
# A scheduler orphaned by an earlier stop holds the lock supervisor's scheduler needs; [s] keeps pkill off this script.
pkill -f "$BENCH/env/bin/python -m frappe.utils.bench_helper frappe [s]chedule" || true

APP_DIR="$BENCH/apps/processa"
[ -d "$APP_DIR" ] || APP_DIR="$BENCH/apps/one_bpmn"
# The frontend build rewrites this tracked file, and a pull refuses to overwrite it.
if git -C "$APP_DIR" ls-files --error-unmatch spiff/components.d.ts >/dev/null 2>&1; then
	git -C "$APP_DIR" checkout -- spiff/components.d.ts
fi
git -C "$APP_DIR" pull --no-rebase upstream "$BRANCH"

if [ ! -f "$APP_DIR/processa/hooks.py" ]; then
	echo "Branch $BRANCH still has the one_bpmn package; deploying it under apps/one_bpmn."
	cd "$APP_DIR/spiff"
	yarn install
	yarn build
	cd "$BENCH"
	APP=one_bpmn
else
	APP=processa
	# Apps that still import one_bpmn move with processa, before anything on the bench changes.
	PULLED=""
	for a in $SIBLINGS; do
		[ -d "apps/$a" ] || continue
		if git -C "apps/$a" grep -qE "^[[:space:]]*(from|import) one_bpmn" HEAD -- '*.py'; then
			if [ -z "$(git -C "apps/$a" branch --show-current)" ]; then git -C "apps/$a" checkout "$BRANCH"; fi
			git -C "apps/$a" pull --no-rebase upstream "$BRANCH"
			if git -C "apps/$a" grep -qE "^[[:space:]]*(from|import) one_bpmn" HEAD -- '*.py'; then
				echo "Deploy stopped: $a on $BRANCH still imports one_bpmn. Release it with processa first."
				exit 1
			fi
			PULLED="$PULLED $a"
		fi
	done
	if [ "$APP_DIR" = "$BENCH/apps/one_bpmn" ]; then
		mv "$APP_DIR" "$BENCH/apps/processa"
		APP_DIR="$BENCH/apps/processa"
		sed -i 's/^one_bpmn$/processa/' sites/apps.txt
	fi
	# Ignored build output left under the old package folder.
	for old in one_bpmn spiff; do
		if [ -d "$APP_DIR/$old" ] && [ -z "$(git -C "$APP_DIR" ls-files "$old")" ]; then rm -rf "${APP_DIR:?}/$old"; fi
	done
	if env/bin/pip show one_bpmn >/dev/null 2>&1; then env/bin/pip uninstall -y one_bpmn; fi
	env/bin/pip install -q -e "$APP_DIR"
	cd "$APP_DIR/frontend"
	yarn install
	# Old build output would shadow www/processa.html.
	rm -rf ../processa/public/processa ../processa/www/processa
	yarn build
	cd "$BENCH"
fi


if [ "$APP" = processa ]; then
	(cd sites && ../env/bin/python -c "from processa.cutover import run; run()")
fi
bench migrate
bench build --app "$APP"
for a in $PULLED; do bench build --app "$a"; done
bench clear-cache

if [ "$APP" = processa ]; then
	# ProsAlly turns run on their own queue; frappe refuses to enqueue on a queue the config does not list.
	env/bin/python - "$PROSALLY_QUEUE" <<'EOF'
import json, sys
path, queue = "sites/common_site_config.json", sys.argv[1]
config = json.load(open(path))
workers = config.setdefault("workers", {})
if queue not in workers:
	workers[queue] = {"background_workers": 1, "timeout": 1800}
	with open(path, "w") as f:
		json.dump(config, f, indent=1)
	print(f"Added the {queue} queue to common_site_config.json")
EOF
	PROGRAM="$NAME-frappe-bpmn-prosally-worker"
	# supervisorctl lists every bench on the server, so only this bench's programs count.
	if ! grep -qE "^$NAME-[^ ]*prosally" <<<"$PROGRAMS"; then
		CONF="$(readlink -f "/etc/supervisor/conf.d/$NAME.conf")"
		GROUP="$NAME-bpmn-workers"
		grep -q "^\[group:$GROUP\]" "$CONF" || GROUP="$NAME-workers"
		cp "$CONF" "$CONF.$(date +%Y%m%d%H%M%S).bak"
		sed -i "/^\[group:$GROUP\]/,/^programs=/ s/^programs=.*/&,$PROGRAM/" "$CONF"
		cat >>"$CONF" <<EOF

[program:$PROGRAM]
command=$HOME/.local/bin/bench worker --queue $PROSALLY_QUEUE
priority=4
autostart=true
autorestart=true
stdout_logfile=$BENCH/logs/worker-bpmn-prosally.log
stderr_logfile=$BENCH/logs/worker-bpmn-prosally.error.log
user=$(whoami)
stopwaitsecs=1860
directory=$BENCH
killasgroup=true
numprocs=1
process_name=%(program_name)s-%(process_num)d
startretries=10
EOF
		sudo supervisorctl reread
		sudo supervisorctl update "$GROUP"
		case " $WORKERS " in *" $GROUP: "*) ;; *) WORKERS="$WORKERS $GROUP:" ;; esac
	fi
fi

sudo supervisorctl start $WORKERS
sudo supervisorctl restart "$NAME-web:"

if [ "$APP" = processa ]; then
	# bench prints its own notices on stdout, so keep only the check lines.
	LEFT="$(bench mariadb -N <<'EOF' | grep -E '^(installed_apps|Patch Log|Scheduled Job Type|Server Script|BPMN Process Model|Module ONE BPMN)' || true
SELECT CONCAT('installed_apps: ', defvalue) FROM tabDefaultValue
	WHERE parent = '__global' AND defkey = 'installed_apps' AND (defvalue LIKE '%"one\_bpmn"%' OR defvalue NOT LIKE '%"processa"%')
UNION ALL SELECT CONCAT('Patch Log: ', COUNT(*)) FROM `tabPatch Log` WHERE patch LIKE 'one\_bpmn%' HAVING COUNT(*) > 0
UNION ALL SELECT CONCAT('Scheduled Job Type: ', COUNT(*)) FROM `tabScheduled Job Type` WHERE method LIKE 'one\_bpmn%' HAVING COUNT(*) > 0
UNION ALL SELECT CONCAT('Server Script: ', COUNT(*)) FROM `tabServer Script` WHERE REPLACE(script, 'delete_one_bpmn_module', '') LIKE '%one\_bpmn%' HAVING COUNT(*) > 0
UNION ALL SELECT CONCAT('BPMN Process Model: ', COUNT(*)) FROM `tabBPMN Process Model` WHERE bpmn_xml LIKE '%one\_bpmn%' HAVING COUNT(*) > 0
UNION ALL SELECT CONCAT('Module ONE BPMN DocType: ', COUNT(*)) FROM `tabDocType` WHERE module = 'ONE BPMN' HAVING COUNT(*) > 0;
EOF
)"
	if [ -n "$LEFT" ]; then
		echo "Deploy finished but these records still name one_bpmn:"
		echo "$LEFT"
		exit 1
	fi
fi

for attempt in $(seq 1 30); do
	if curl -sf -o /dev/null -H "Host: $SITE" "http://127.0.0.1:$PORT/api/method/ping"; then echo "$SITE answers on port $PORT."; exit 0; fi
	sleep 2
done
echo "Deploy finished but $SITE does not answer /api/method/ping on port $PORT."
exit 1
