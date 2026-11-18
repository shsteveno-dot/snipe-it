#!/usr/bin/env bash
# usage: run-full.sh IMAGE OUTDIR SHARD... ; runs each shard in its own container in parallel
set -u
IMG=$1; OUT=$2; shift 2
HERE=$(cd "$(dirname "$0")" && pwd)
php_ini_args=()
if [[ -n "${PHPUNIT_INI:-}" ]]; then
  if [[ ! -f "$PHPUNIT_INI" ]]; then
    printf 'PHPUNIT_INI file does not exist: %s\n' "$PHPUNIT_INI" >&2
    exit 1
  fi
  php_ini_dir=$(cd "$(dirname "$PHPUNIT_INI")" && pwd) || exit 1
  php_ini_args=(-v "$php_ini_dir:/php-extra:ro" -e PHP_INI_SCAN_DIR=:/php-extra)
fi
if [[ ! -f "$HERE/full/init.php" ]]; then
  printf 'full/init.php is missing; run: python3 -I prep.py ../.. full\n' >&2
  exit 1
fi
for shard in "$@"; do
  if [[ ! -f "$HERE/full/$shard.xml" ]]; then
    printf 'full/%s.xml is missing; run prep.py or check the shard name\n' "$shard" >&2
    exit 1
  fi
done
NET=r17-net; DB=r17-db; PASS=$(head -c16 /dev/urandom | od -An -tx1 | tr -d ' \n'); KEY="base64:$(head -c32 /dev/urandom | base64)"
mkdir -p "$OUT"; chmod 777 "$OUT"
docker network inspect $NET >/dev/null 2>&1 || docker network create --internal $NET >/dev/null
docker rm -f $DB >/dev/null 2>&1
docker run -d --name $DB --network $NET --tmpfs /var/lib/mysql:rw -e MYSQL_ROOT_PASSWORD=$PASS -e MYSQL_ROOT_HOST=% mysql:8.4 >/dev/null
for i in $(seq 120); do docker exec $DB mysqladmin ping -h127.0.0.1 -uroot -p$PASS --silent >/dev/null 2>&1 && break; sleep 3; done
sleep 5
HOSTS=""; for h in example.com graph.microsoft.com graph.microsoft.us example.api.kandji.io hooks.slack.com; do HOSTS="$HOSTS --add-host $h:93.184.215.14"; done
run_shard() {
  s=$1; db="t_$s"; vol="r17-vol-$s"
  docker exec $DB mysql -uroot -p$PASS -e "DROP DATABASE IF EXISTS $db; CREATE DATABASE $db" 2>/dev/null
  docker volume rm $vol >/dev/null 2>&1; docker volume create $vol >/dev/null
  common="--rm --network $NET $HOSTS -v $vol:/var/lib/snipeit -v $OUT:/results -v $HERE/full/$s.xml:/var/www/html/phpunit-shard.xml:ro -v $HERE/full/init.php:/probe/init.php:ro
   -e APP_KEY=$KEY -e APP_ENV=testing -e APP_DEBUG=false -e APP_URL=http://localhost -e DB_CONNECTION=mysql -e DB_HOST=$DB -e DB_PORT=3306 -e DB_DATABASE=$db -e DB_USERNAME=root -e DB_PASSWORD=$PASS -e DB_DUMP_PATH=/usr/bin -e CACHE_DRIVER=array -e SESSION_DRIVER=array -e QUEUE_CONNECTION=sync -e MAIL_MAILER=array -e IMPORT_MEMORY_LIMIT=2G -e LDAP_MEM_LIM=2G --entrypoint /usr/bin/php"
  docker run "${php_ini_args[@]}" $common --user 0:0 $IMG /probe/init.php
  docker run "${php_ini_args[@]}" $common $IMG artisan migrate --force --no-interaction >/dev/null
  docker run "${php_ini_args[@]}" $common $IMG artisan passport:keys --force --no-interaction >/dev/null
  t0=$(date +%s)
  docker run --name r17-$s "${php_ini_args[@]}" $common $IMG -d memory_limit=2G ${PHPUNIT_PHP_ARGS:-} vendor/bin/phpunit -c phpunit-shard.xml --colors=never --display-skipped --display-incomplete --log-junit /results/$s.xml > "$OUT/$s.txt" 2>&1
  rc=$?
  echo "$s exit=$rc seconds=$(( $(date +%s) - t0 ))" | tee -a "$OUT/summary.txt"
}
date -u +"Started %H:%M:%S UTC" | tee -a "$OUT/summary.txt"
for s in "$@"; do run_shard $s & done
wait
date -u +"Finished %H:%M:%S UTC" | tee -a "$OUT/summary.txt"
