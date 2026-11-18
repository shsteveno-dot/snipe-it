# 全套測試（chiseled 測試 image）

這些是第 16、17 輪跑完整 `tests/` 用的腳本，第 17 輪原樣使用過。測試要在 `review-fixes` runner 建出的測試 image 裡跑，用同一個 chiseled `/usr/bin/php`。

## 檔案

- `prep.py CHECKOUT OUTDIR`：在 `OUTDIR` 產生每個 shard 的 phpunit 設定和 `init.php`。
  - 4 個 shard：SyncAdapters 以外的測試檔，依檔案大小平均分配，shard 內依路徑排序。
  - `syncrest`：SyncAdapters，不含 AppleBusinessManager。
  - `abm0`–`abm7`：AppleBusinessManager 每個檔案一個。
  - 一定把 `ShelllessSchedulerTest` 和 `RestoreToRemoteDiskTest` 放在同一個 shard，前者排在前面。
  - `init.php` 從 `docker/snipeit-runtime/internal/startup/startup.go` 的 `dataDirs` 產生 `/var/lib/snipeit` 的目錄（解析方式和 `runner.py` 相同），擁有者是 10000:50。
- `run-full.sh IMAGE OUTDIR SHARD...`：每個 shard 一個容器，全部平行跑。
  - 一個 `--internal` 網路和一個 `mysql:8.4`，每個 shard 有自己的資料庫和 volume。
  - 每個 shard 依序執行：用 root 跑 `init.php`、`artisan migrate`、`artisan passport:keys`，然後跑 phpunit（`--display-skipped --display-incomplete --log-junit`）。
  - 用 `--add-host` 把 `example.com graph.microsoft.com graph.microsoft.us example.api.kandji.io hooks.slack.com` 指到一個公開 IP，讓 14 個 `ExternalUrl` 測試可以通過。
  - 資料庫密碼和 `APP_KEY` 每次執行時隨機產生，不會寫進檔案。
  - 輸出寫到 `OUTDIR/<shard>.txt`、`OUTDIR/<shard>.xml` 和 `OUTDIR/summary.txt`。
- `run-order.sh IMAGE OUTDIR order order3`：順序驗證，使用自己的網路、資料庫和 volume（`r17o-*`）。
  - `full/order.xml`：`ShelllessSchedulerTest` → `RestoreToRemoteDiskTest`。
  - `full/order3.xml`：`ShelllessSchedulerTest` → `ShelllessOptInTest` → `RestoreToRemoteDiskTest`。
- `run-control.sh IMAGE OUTDIR order`：反證。和 `run-order.sh` 相同，但會把 `old-ShelllessSchedulerTest.php` 唯讀掛進容器，取代 image 裡的測試檔。預期出現 18 個 `posix_spawn` error。

## 用法

先確認 dockerd 已經啟動。等 runner（`bash cloud-verify/review-fixes/run.sh "$PWD" B`）建好測試 image 後，另外 tag 一份。這樣 runner 結束時只會刪掉它自己的 tag：

```bash
docker tag "$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E '^review-[0-9a-f]+:test$')" full-suite:test
```

```bash
cd cloud-verify/full-suite && python3 -I prep.py ../.. full
```

全套大約 45 分鐘。放在背景執行時，時限至少要設 2 小時：

```bash
cd cloud-verify/full-suite && ./run-full.sh full-suite:test "$PWD/out" shard0 shard1 shard2 shard3 syncrest abm0 abm1 abm2 abm3 abm4 abm5 abm6 abm7
```

```bash
cd cloud-verify/full-suite && ./run-order.sh full-suite:test "$PWD/out-order" order order3
```

反證（選擇性）：

```bash
cd cloud-verify/full-suite && git show 4525efb^:tests/Feature/Console/ShelllessSchedulerTest.php > old-ShelllessSchedulerTest.php && ./run-control.sh full-suite:test "$PWD/out-control" order
```

三個執行腳本都支援以下選用環境變數，未設定時維持原本的指令：

- `PHPUNIT_PHP_ARGS`：額外的 PHP 參數，插在 `-d memory_limit=2G` 之後、`vendor/bin/phpunit` 之前；刻意以空白分割。例如：

  ```bash
  PHPUNIT_PHP_ARGS="-d disable_functions=exec" ./run-order.sh full-suite:test "$PWD/out-order" order order3
  ```

- `PHPUNIT_INI`：主機上的 `.ini` 檔案路徑；檔案不存在時，腳本會在啟動任何容器前報錯退出。檔案所在目錄會唯讀掛載到 `/php-extra`，每個 shard 的所有 PHP 容器都會設定 `PHP_INI_SCAN_DIR=:/php-extra`。開頭的 `:` 保留 PHP 編譯時的預設掃描目錄；該目錄內所有 `.ini` 都會載入。例如先在專用目錄建立設定檔：

  ```bash
  mkdir -p "$PWD/php-extra"
  printf 'disable_functions=exec\n' > "$PWD/php-extra/99-disable-exec.ini"
  PHPUNIT_INI="$PWD/php-extra/99-disable-exec.ini" ./run-order.sh full-suite:test "$PWD/out-order" order order3
  ```

`-d` 參數不會傳給 `#[RunInSeparateProcess]` 測試啟動的 PHP 子程序；`PHPUNIT_INI` 透過環境變數讓這些子程序也載入設定。需要讓獨立程序測試同樣停用 `exec` 時，請使用 `PHPUNIT_INI`。

## 注意

- 腳本結束後會留下資料庫容器、網路和 volume，要手動刪除：`r17-db`、`r17-net`、`r17-vol-*`；順序驗證用的是 `r17o-*`。phpunit 容器用 `--rm` 啟動，跑完會自動刪除。
- 從 runner 的測試 image 啟動的容器會繼承 `review-fixes.run` label。runner 開始時會刪掉帶這個 label 的容器，所以全套還在跑的時候不要重跑 runner。
- 全套執行期間重跑 runner 也會刪掉 `full-suite:test` tag，因為啟動清理 `cleanup_previous_runs` 會移除帶有該 label 的 image。之後需從新 runner 建出的測試 image 重新加上 `full-suite:test` tag。
- JUnit 的 `skipped` 包含 incomplete。第 17 輪是 3 個略過加 54 個 incomplete，共 57 個。
- 最慢的是跑 migration 的 CustomField 測試，瓶頸在資料庫。
