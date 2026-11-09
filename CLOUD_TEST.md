# 雲端測試任務

`cloud-test` 分支 = `all-changes`（我們的改動，rebase 在上游 `grokability/snipe-it` 的 develop 上）+ 這個說明檔。每次有新改動都會推到這裡，請你測試並提出修改建議。

**不要修改程式碼。** 唯一允許的 push 是最後把結果檔推回 `cloud-test`（見「回報」和「這次的重點」）。

**一路做完，不要中途結束回應。** 等背景工作時，每次等待不超過 5 分鐘，每 5 分鐘在對話裡寫一行進度（目前步驟、第幾次測試、已知的失敗和略過數字），然後繼續做。

## 這次的重點

第 7 輪：**chiseled image 的「本機檔案不進 image」修正**（這輪不跑 PHPUnit）。程式碼和 `all-changes` `65ecdf0ab4` 相同，基準上游 develop `f9f3a6067c`。上一輪（第 6 輪，`6bfd75f067`）的結果在 `cloud-verify/round6/`。

新改動：
- `65ecdf0ab4`（第 6 輪建議 1、3）：`.dockerignore` 排除 `.env.testing`、`.phpunit.cache`、`storage/logs/*.log`、編譯過的 view、session、`storage/framework/testing`、`storage/app/backup-temp`、`bootstrap/cache/*.php`。`docker/chiseled/prepare-app.py` 另外刪掉這些檔案，以及 `.ai`、`.claude`、`cloud-verify`、`CLOUD_TEST*.md`；目錄和 `.gitignore` 保留。
- `cloud-verify/` 的兩個腳本（第 6 輪建議 2、4）：`regression.py --self-test` 的斷言改成 `assert not hit`；`check_invariants.py` 刪容器時加 `-v`。

這輪的做法：**刻意用「髒」的 checkout 建 image**，證明修正有效。
1. 照第 6 輪的方式啟動 dockerd、`repin_app_inputs.py --check`。
2. 建一個 worktree 當 build context，在裡面放這些假檔案（內容用無害的假字串，例如 `FAKE-LOCAL-FILE`）：`.env.testing`、`.phpunit.cache/test-results`、`.phpunit.result.cache`、`storage/logs/laravel.log`、`storage/framework/views/0123abcd.php`、`storage/framework/sessions/fakesession`、`storage/framework/testing/disks/x.txt`、`storage/app/backup-temp/x.txt`、`bootstrap/cache/services.php`、`bootstrap/cache/packages.php`。`CLOUD_TEST.md` 和 `cloud-verify/` 本來就在這個分支上。
3. 照第 6 輪的做法建 image（代理 CA、composer 用 `git archive` 預先放進快取的暫時調整一樣允許，不要 commit），tag 用 `snipeit-chiseled:round7`。
4. `docker create` → `docker export`，確認：
   - 上面的假檔案、`.ai/`、`.claude/`、`cloud-verify/`、`CLOUD_TEST.md` **都不在** `/var/www/html` 裡（搜尋 `FAKE-LOCAL-FILE` 應該是 0 筆）；
   - `storage/logs`、`storage/framework/views`、`storage/framework/sessions`、`storage/framework/cache`、`bootstrap/cache` 這些目錄**還在**；
   - `bootstrap/cache/packages.php` 是 composer 在 build 時重新產生的（內容不是假字串）。
5. 跑四個驗收（`check_sapi`、`check_invariants --boot`、`regression --self-test`、`regression`），**全部都要 exit 0**（self-test 這次應該通過）。和 `cloud-verify/round6/*.json` 比較。
6. 跑完確認沒有留下匿名 volume（`docker volume ls -q` 是空的）。
7. 清理：image、容器、網路、volume、build cache 都刪掉，停掉 dockerd，刪掉 worktree。
8. 另外用上游原本的 `Dockerfile`（不是 chiseled）只做到 `COPY . /var/www/html` 這一步就夠，確認 `.dockerignore` 的新規則不會擋掉 build 需要的檔案。如果完整 build 太花時間或空間，可以只用 `docker buildx build --target` 或一個只有 `COPY .` 的暫時 Dockerfile 檢查 context 內容，在報告裡說明。

回報時把驗收 json commit 成 `cloud-verify/round7/*.json`，加上 `CLOUD_TEST_RESULT.md`、`cloud-test-output.txt`。

---

以下是第 6 輪的背景說明，做法相同時可以參考：

背景：`Dockerfile.chiseled` 建出一個沒有 shell、沒有套件管理器的 Ubuntu chiseled image（說明在 `docker/chiseled/README.md`）。之前在本機用舊的 develop（`73323cb76d`，分支頭 `330a2a3439`）建過一次，三個驗收腳本都通過，結果在 `cloud-verify/previous-run/*.json`。

驗收腳本在 `cloud-verify/`（從本機的 verification 目錄複製過來，**只拿來執行，不要修改**）：
- `cloud-verify/verification/chiseled-opcache/check_sapi.py <image> --out <json> --label round6`：CLI 和 Apache 的 OPcache 狀態。
- `cloud-verify/verification/chiseled-opcache/check_invariants.py <image> --boot --out <json> --label round6`：沒有 shell、沒有套件管理器和編譯器、使用者、entrypoint；`--boot` 會用正式的安全選項在內部網路啟動，要求 init 成功、`/health` 回 ok。
- `cloud-verify/verification/chiseled-opcache/regression.py --self-test`，然後 `regression.py <image> --out <json> --label round6`：網頁安裝和登入、`schedule:run`、SMTP 寄信、備份、1536m 記憶體上限下不 OOM、沒有 OPcache 檔案寫進應用目錄。會用到 `mysql:8.4`、`python:3.12-slim` 和 `cloud-verify/s3mock/server.py`、`cloud-verify/verification/compatibility-closure/smtp-fixture.py`。
- 一律用 `python3 -I` 執行。腳本會自己建立和移除容器、網路和 volume。

第 6 輪步驟（參考用）：
1. 啟動 dockerd（root，帶代理設定讓 dockerd 能 pull image），跑 `docker run --rm hello-world` 確認可用。磁碟只有約 12 GB：需要的話可以刪掉 `vendor/`、停掉 MariaDB 騰空間，在報告裡說明。
2. `python3 -I docker/chiseled/repin_app_inputs.py --check`，要回 `locks are up to date`。
3. 建 image：`docker buildx build -f Dockerfile.chiseled --platform linux/amd64 -t snipeit-chiseled:round6 --load .`（README 的指令加上 `--load`）。build 裡的 `apt-get`、`fetch_inputs.py`、composer 都要連網，這個環境要用 `--network host` 並傳入代理設定和代理的 CA。
   - **允許的暫時調整**：只為了讓 build 能透過代理連網，例如 `--build-arg HTTPS_PROXY=...`、在 `tools` 階段暫時加入代理 CA。不能改到最後 image 的內容（`candidate` 階段從 `scratch` 組出來，代理 CA 不能出現在裡面）。所有調整寫進報告（附 diff），**不要 commit**，做完還原。
   - `api.github.com` 和 `codeload.github.com` 都是 403，composer 不會自動改用 git clone（`Source fallback is disabled`）。第 6 輪的解法：對 `~/.cache/composer/vcs` 的 mirror 用 `git archive --format=zip -o <cache>/files/<name>/$(php -r 'echo sha1("<dist url>");').zip <dist reference>` 產生 dist zip，用 `--build-context composercache=<cache>` 搭配 `application` 階段暫時的 `COPY` 放進 Composer 快取（diff 見第 6 輪報告 1.2）。mirror 不見的話要先在主機跑一次 `composer install --prefer-source`。
   - 記錄 build 耗時、image 大小和 image ID。
4. 跑三個驗收腳本（順序：`check_sapi`、`check_invariants --boot`、`regression --self-test`、`regression`），每個都要 exit 0、結果 `pass`。把輸出的 json 和 `previous-run/` 比較，列出不同的項目。
5. 另外確認：最後的 image 裡沒有代理 CA 或代理設定（例如 `docker image inspect` 的 Env、`docker create` 後 `docker export` 搜尋 `/root/.ccr` 或代理 CA 的檔名）。
6. 結束後刪掉這輪建立的 image、容器、網路、volume 和 build cache（`docker buildx prune -af`），停掉 dockerd。

回報時把三個驗收 json 一起 commit 成 `cloud-verify/round6/*.json`（加上 `CLOUD_TEST_RESULT.md`、`cloud-test-output.txt`；`cloud-test-output.txt` 放 build 的最後 200 行和三個腳本的輸出）。「修改建議」只寫和 chiseled image 有關、真正值得做的。

之前的結果在這個分支的歷史裡：第 1–6 輪 `a3611109df`、`ed51bd3f4f`、`8e930e5a00`、`ea0fc2c737`、`ea5bed8301`、`6bfd75f067`（`CLOUD_TEST_RESULT.md`）。

## 步驟

先做這三件事，可以省掉上次浪費的約 15 分鐘：

- 讀 `.github/workflows/tests-mysql.yml`，照它的初始化步驟做（`key:generate`、`passport:install` 等），**金鑰要在開跑前就產生**。
- 用 `curl -s -o /dev/null -w '%{http_code}\n' -L https://api.github.com/repos/laravel/framework/zipball` 測能不能下載 zip，回 200 才算可以（經過 proxy 時 `curl -sI` 會誤報 200 Connection Established）。不能的話直接用 `composer install --prefer-source`，並提早處理只有 dist 的套件 `phpstan/phpstan`：`git fetch --depth 1 https://github.com/phpstan/phpstan.git <lock 裡的 reference>` → `git archive --prefix=phpstan/ -o x.zip FETCH_HEAD` → 複製到 `~/.cache/composer/files/phpstan/phpstan/$(php -r 'echo sha1("<lock 裡的 dist url>");').zip`。不要修改 `composer.lock`。
- 跑測試一律加 `--display-skipped`，跑完先看略過的原因。

接著：

1. 環境：PHP 8.3，擴充套件 `pdo_mysql pdo_sqlite zip gd bcmath ldap exif intl mbstring xml curl`，Composer 2，MariaDB 10.11。全新容器可能缺 `php8.3-bcmath php8.3-ldap mariadb-server`，用 apt 補。CI 步驟的 `chmod -R 777 storage bootstrap/cache` 會讓 git 顯示權限變動，先 `git config core.fileMode false`，不要 commit 這些變動。
2. `cp .env.testing.example .env.testing`，填入資料庫設定（使用者要有 CREATE DATABASE 權限，平行模式會建 `<db>_test_N`）。確認有 `IMPORT_MEMORY_LIMIT=2G`、`LDAP_MEM_LIM=2G`。`cp .env.testing .env`。
3. 平行全套：`php -d memory_limit=2G artisan test --parallel --display-skipped --colors=never 2>&1 | tee /tmp/branch.txt`
4. 有失敗或可疑的略過時，到上游 develop 對照（`git fetch https://github.com/grokability/snipe-it.git develop` 後 `git worktree add /tmp/dev FETCH_HEAD`），只需要重跑相關的測試檔；確定是新的問題才跑上游全套。我們新增的測試上游沒有，直接分析即可。
   平行競爭只跑一次全套不一定抓得到，有改到 S3 測試或上傳目錄時，另外用平行模式重複跑 `tests/Feature/S3Compatibility`（每次約 10–15 秒，建議 10 次）。比較耗時看 `--log-junit` 裡各測試類別的時間，不要只看總耗時。
5. 結束後刪掉 `/tmp/dev` 和測試資料庫。

## 已知狀況

- `Tests\Feature\Livewire\ImporterMutexTest::test_locks_are_scoped_per_file_so_a_second_file_can_still_start`：平行模式下偶發失敗（共用 file cache + 各 process 的 Import ID 重複），上游也有同樣風險。乾淨 cache 單獨跑會過。第 2–4 輪都沒有重現。
- 程式碼本來就標記跳過的 3 個（上游也有）：`ApiRateLimitTest` 兩個、`DeleteAssetsTest::test_cannot_delete_asset_that_is_checked_out`。
- 容器沒有 DNS 時（`getent ahosts example.com` 沒有輸出），`ExternalUrl` 相關的 14 個測試會失敗，上游也一樣：`SyncAdapters\GroupCompanyMappingTest`、`Intune\IntuneSettingsPageTest`、`Kandji\KandjiSettingsPageTest`、`AssetTagPatternTest`、`Fleet\FleetLicenseTierTest`、`Fleet\FleetSettingsPageTest`、`CompanyWebhooksTest::test_can_filter_companies_with_webhooks`、`WebhookEndpointSsrfTest::test_api_accepts_a_public_https_webhook_endpoint_from_superuser`。要讓它們通過，跑測試前暫時把 `example.com graph.microsoft.com graph.microsoft.us example.api.kandji.io hooks.slack.com` 加進 `/etc/hosts`（對應任一公開 IP），跑完還原。
- 本機（非 UTC 時區、不同 intl 版本）才會失敗的 `CustomFieldTest` 和 `ExtraFieldMappingTest`，在 UTC 的雲端環境應該會過。

## 回報

把結果寫成 `CLOUD_TEST_RESULT.md`，完整輸出存成 `cloud-test-output.txt`，只 commit 這兩個檔案，push 到 `cloud-test`。推不到的話推到你自己的分支，並在對話裡說名稱。對話裡也貼一份摘要。

內容：

1. 環境：PHP、資料庫版本、CPU 核心數、平行或單程序、各階段耗時（安裝、每次全套、分析）。
2. 測試數量：總數、通過、失敗、錯誤、略過、未完成，以及和上次結果的差異。
3. 每個失敗或可疑略過：名稱、錯誤摘要、上游 develop 是否也有。
4. 「這次的重點」逐項回答。
5. **修改建議**：你認為該改的地方（程式碼、測試、這份說明檔），寫出檔案、原因和建議的改法（可以附 diff），但不要 commit 到程式碼。依重要性排序，並標明是我們的改動造成的，還是上游本來就有的問題。
