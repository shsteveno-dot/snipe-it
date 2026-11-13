# 雲端測試任務

`cloud-test` 分支 = `all-changes`（我們的改動，rebase 在上游 `grokability/snipe-it` 的 develop 上）+ 這個說明檔。每次有新改動都會推到這裡，請你測試並提出修改建議。

**不要修改程式碼。** 唯一允許的 push 是最後把結果檔推回 `cloud-test`（見「回報」和「這次的重點」）。

**一路做完，不要中途結束回應。** 等背景工作時，每次等待不超過 5 分鐘，每 5 分鐘在對話裡寫一行進度（目前步驟、第幾次測試、已知的失敗和略過數字），然後繼續做。

## 這次的重點

第 10 輪：**review-fixes 第 A 輪（只寫測試，還沒修）**。分支 `review-fixes`（從 `all-changes` `04a07b3584` 開出）只加了測試和 `cloud-verify/review-fixes/` 測試工具，**沒有任何修正程式碼**，所以新測試照理應該**失敗**（RED）。第 9 輪結果在 `984a0f7347`。

背景：程式碼審查找到 9 個問題（LDAP OU 排除可被本機密碼繞過、`backup-staging` 可能進 image、還原時舊的本機副本蓋掉暫存副本、`--validate-only` 沒檢查整個 zip、DN 拆分不符 RFC 4514、LDAP 搜尋不完整被當完整、遠端 CSV 被截斷照樣匯入、chiseled 不支援 `REMOTE_LOGIN_FORWARDED_HEADER`、還原安全備份的測試只是對原始碼做 regex）。規定：**所有測試都要在 chiseled image 裡跑**（從 chiseled image 的 digest 衍生出只多了測試檔和 dev 套件的測試 image，用同一個 `/usr/bin/php`）。

要做的：
1. 啟動 dockerd（同第 6 輪：root、代理設定、`docker run --rm hello-world` 確認），用當下的 `$HTTPS_PROXY`。
2. 讀 `cloud-verify/review-fixes/README.md` 和 `runner.py`，然後執行：
   `bash cloud-verify/review-fixes/run.sh "$PWD" A`
   它會建 chiseled candidate、測試 image、MySQL 8.4，跑測試、FR-2（staging marker）和 FR-8（Apache header）探測、FR-9 突變測試，結果寫到 `cloud-verify/review-fixes/results-A.json`。**這是第一次跑這個工具，很可能有設定上的錯誤。** 遇到工具本身的錯（composer 快取路徑、build 參數、代理 CA、Dockerfile.test、MySQL 連線、權限等），可以在本機暫時修改工具讓它跑下去（**不要 commit 工具的修改**），把每個修改的 diff 和原因寫進報告的「修改建議」，我會轉給作者修正。不准改 `app/`、`docker/`、Dockerfile 或測試的判斷邏輯來讓測試通過或失敗。
3. 逐一判斷每個新測試和探測：是否**失敗**、失敗的**原因是否就是它要抓的問題**（而不是設定錯誤、fixture 錯、mock 錯）。預期：
   - 問題 1、3、4（CRC 損壞的舊副本）、5、6、7 的新測試失敗；FR-4 的對照組（正常 zip 通過、截斷 zip 被拒）可能本來就會通過或失敗，照實寫。
   - FR-2 三個探測（chiseled、regular、prepare-app fixture）都看到 marker（失敗）。
   - FR-8 valid header 的探測失敗；unset、empty 的探測應該通過；invalid 的情況照實記錄。
   - FR-9：原本的端點測試通過，突變版（拿掉 `--with-remote-files`）失敗。
   - 既有測試（`LdapTest`、`S3Compatibility`、`LdapWizardTest` 全套）除了新測試以外不應該失敗；有失敗就列出來分析。
4. 也確認：測試 image 和 candidate 的 `php -v`、`php -m`、`/usr/bin/php` sha256 相同；沒有任何容器掛 docker socket；跑完後這輪建立的容器、volume、網路、image 都清掉（`docker buildx prune -af`），停掉 dockerd。

回報：把 `cloud-verify/review-fixes/results-A.json` 一起 commit，加上 `CLOUD_TEST_RESULT.md`、`cloud-test-output.txt`（runner 的錯誤訊息、每個失敗測試的訊息、對工具做的暫時修改的 diff）。「修改建議」分成兩類：測試工具（cloud-verify/review-fixes）和測試本身（哪個測試失敗原因不對、該怎麼改）。

---

第 9 輪：**只驗證第 8 輪新測試的修正**（短的一輪，不重建 chiseled、不跑全套）。程式碼和 `all-changes` `04a07b3584` 相同。第 8 輪結果在 `cloud-verify/round8/`（commit `2e55131084`），以下第 8 輪的說明保留作參考。

新改動（第 8 輪建議 1）：
- `db13e6c4b2`：`missing_include_paths_are_left_out_and_named_instead_of_failing_the_backup` 改成 `$command->assertExitCode(0)->run()`，先執行再讀 `calls()`。
- `e2ac9efc4b`：兩個新測試的暫存目錄改在 `tearDown` 刪除（`$missingRoot`），測試失敗時也不會留在 `/tmp`。
- `04a07b3584`：建立斷掉的 symlink 失敗時不再靜默略過：Windows 上 `markTestSkipped`，其他系統直接 `fail`；`$missing` 一定是兩個路徑。

要做的（沿用現有容器；MariaDB 沒在跑就先 `service mariadb start`，用當下的 `$HTTPS_PROXY`）：
1. `vendor/bin/pint --test tests/Feature/S3Compatibility/BackupRemoteOptionTest.php`。
2. 單一 process 跑 `BackupRemoteOptionTest` 和 `BackupPageTest`：全過、0 略過。
3. 反證：暫時把 `SystemBackup::handle()` 的 `$existing` 改回 `$include`，兩個新測試都要失敗，還原後通過（不要 commit）。故意讓測試失敗時，確認 `/tmp/s3compat-missing-*` 沒有留下來。
4. 平行模式跑 `tests/Feature/S3Compatibility` 5 次，全部 0 失敗、0 略過，`/tmp/s3compat-missing-*` 沒有殘留。
5. 如果全部符合，報告開頭寫「穩定」。

回報：`CLOUD_TEST_RESULT.md`、`cloud-test-output.txt`（不用 json）。

---

第 8 輪：**備份遇到不存在的路徑會整個失敗**（正式環境的 bug）。程式碼和 `all-changes` `57e3245981` 相同，基準上游 develop `f9f3a6067c`。第 7 輪結果在 `cloud-verify/round7/`（commit `f72e861960`）。

正式環境（k8s、chiseled image、`/var/lib/snipeit` 沒有掛 volume、沒用 Passport）在網頁按備份失敗，`snipeit:backup --without-remote-files` 的輸出是：
`Backup failed because: The "/var/www/html/storage/oauth-private.key" directory does not exist..`（`FileSelection.php(85): Finder->in()`）。
原因：`config/backup.php` 一定會打包 `storage/oauth-*.key`；chiseled image 裡這兩個是指到 `/var/lib/snipeit/keys/` 的 symlink，那裡沒有檔案時，Spatie 把它當資料夾交給 Finder 就失敗。網頁只顯示輸出的第 3 段，所以使用者只看到「Determining files to backup」。

新改動 `57e3245981`：
- `app/Console/Commands/SystemBackup.php`：`existingPaths()` 把不存在的路徑（含斷掉的 symlink）從這次的 include 拿掉，印 `Skipping <path>: it does not exist.`；全本機安裝（沒有 S3）也一樣處理；設定在 `finally` 還原。
- `app/Http/Controllers/SettingsController.php`：失敗時優先顯示 `Backup failed because: ...` 那一行。
- 測試：`BackupRemoteOptionTest` 兩個新測試（含斷掉的 symlink），`BackupPageTest::a_failed_backup_shows_the_reason_rather_than_a_progress_line`。
- `cloud-verify/.../regression.py` 新增檢查 `backup_without_key_files`：正常備份後刪掉 `/var/lib/snipeit/keys/oauth-*.key`，再跑一次 `snipeit:backup`，要 exit 0 且沒有 `Backup failed`。

要做的（`vendor/` 在第 6 輪刪掉了，要重新 `composer install --prefer-source`；`~/.cache/composer` 的 mirror 還在，應該比較快）：
1. `vendor/bin/pint --test app/Console/Commands/SystemBackup.php app/Http/Controllers/SettingsController.php tests/Feature/S3Compatibility/BackupRemoteOptionTest.php tests/Feature/S3Compatibility/BackupPageTest.php`，有格式問題列在報告裡（不要改檔）。
2. 新測試和相關類別：`BackupRemoteOptionTest`、`BackupPageTest` 全過；確認斷掉的 symlink 那段真的有建立（不是被 `@symlink` 失敗略過）。
3. **反證**：暫時把 `SystemBackup::handle()` 裡的 `$existing` 改回 `$include`（只在本機改，不要 commit），確認 `missing_include_paths_are_left_out_and_named_instead_of_failing_the_backup` 會失敗，然後還原。
4. 真的 Spatie（不是 stub）：在 MariaDB 測試環境下，把 `backup.backup.source.files.include` 設成含一個斷掉 symlink 的清單，跑一次真正的 `php artisan snipeit:backup --without-remote-files`（可以用 tinker 或暫時的設定），要 exit 0、輸出有 `Skipping`、產生 zip。做完還原。
5. 平行模式跑 `tests/Feature/S3Compatibility` 5 次，0 失敗、0 略過；平行全套一次（DNS 不通就照「已知狀況」補 `/etc/hosts`）。
6. chiseled：照第 6、7 輪的方式（代理、composer 用 `git archive` 預先放快取的暫時調整，不要 commit）建 `snipeit-chiseled:round8`，跑四個驗收（`check_sapi`、`check_invariants --boot`、`regression --self-test`、`regression`），全部 exit 0，`regression` 的 `backup_without_key_files` 要是 true。和 `cloud-verify/round7/*.json` 比較。
7. 清理：image、容器、volume、build cache、worktree，停掉 dockerd。

回報時把驗收 json commit 成 `cloud-verify/round8/*.json`，加上 `CLOUD_TEST_RESULT.md`、`cloud-test-output.txt`。

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

之前的結果在這個分支的歷史裡：第 1–8 輪 `a3611109df`、`ed51bd3f4f`、`8e930e5a00`、`ea0fc2c737`、`ea5bed8301`、`6bfd75f067`、`f72e861960`、`2e55131084`（`CLOUD_TEST_RESULT.md`）。

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
