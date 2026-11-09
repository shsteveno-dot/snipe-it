# 雲端測試任務

`cloud-test` 分支 = `all-changes`（我們的改動，rebase 在上游 `grokability/snipe-it` 的 develop 上）+ 這個說明檔。每次有新改動都會推到這裡，請你測試並提出修改建議。

**不要修改程式碼。** 唯一允許的 push 是最後把結果檔推回 `cloud-test`（見「回報」）。

**一路做完，不要中途結束回應。** 等背景工作時，每次等待不超過 5 分鐘，每 5 分鐘在對話裡寫一行進度（目前步驟、第幾次測試、已知的失敗和略過數字），然後繼續做。

## 這次的重點

第 4 輪。基準：上游 develop `f9f3a6067c`；程式碼和 `all-changes` `3820445291` 相同。如果你是接著上一輪的同一個 session，容器裡已經有 `vendor/` 和 MariaDB，`git pull` 後跳過安裝，直接跑測試。

- 新改動 `3820445291`（第 3 輪建議 1 的 a 方案，建議 3、4 的小改動）：
  - `RestoreToRemoteDiskTest` 和 `StagingAssumptionsTest` 改用第二條連線 `s3compat_scratch_admin` 建立、寫入、刪除 scratch 資料庫，不再對測試連線做 DDL，也不再 `DB::purge('mysql')`。測試連線保持在原本的測試資料庫和交易裡，只把 `database.connections.mysql.database` 的設定指到 scratch，restore 命令照設定呼叫 mysql client。
  - 鎖檔名稱加上 `md5(base_path())`，跳過訊息改成列出全部殘留檔。
- 要確認：
  1. **`RestoreToRemoteDiskTest` 不再每個測試重跑 migration**：用 `--log-junit` 看每個測試的耗時（上次每個約 3.5–4.3 秒），必要時用 MariaDB general log 確認不再出現 `drop table ... accessories`。S3 目錄平行耗時和上次（84–99 秒）比較。
  2. restore 測試本身仍然正確：`RestoreToRemoteDiskTest` 和 `StagingAssumptionsTest` 全過，scratch 資料庫（`s3compat_restore_*`、`s3compat_assume_*`）跑完後都已刪除（`SHOW DATABASES LIKE 's3compat%'` 沒有結果），測試資料庫 `snipeit_test*` 的資料沒有被 restore 改掉。
  3. 平行模式跑 `tests/Feature/S3Compatibility` 至少 5 次，全部 0 失敗、0 略過。
  4. 平行全套一次：除了已知的環境問題（見「已知狀況」）外 0 失敗，S3 測試 0 略過，上傳目錄沒有殘留。也請確認跑在 `RestoreToRemoteDiskTest` 之後的測試沒有因為資料庫狀態而失敗。
- 第 3 輪建議 2（`ExternalUrl` 依賴 DNS）是上游程式碼，這次不改，只在「已知狀況」記錄。
- 之前的結果在這個分支的歷史裡：第 1 輪 `a3611109df`、第 2 輪 `ed51bd3f4f`、第 3 輪 `8e930e5a00`（`CLOUD_TEST_RESULT.md`）。

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
   平行競爭只跑一次全套不一定抓得到，有改到 S3 測試或上傳目錄時，另外用平行模式重複跑 `tests/Feature/S3Compatibility`（每次不到 2 分鐘）。比較耗時看 `--log-junit` 裡各測試類別的時間，不要只看總耗時。
5. 結束後刪掉 `/tmp/dev` 和測試資料庫。

## 已知狀況

- `Tests\Feature\Livewire\ImporterMutexTest::test_locks_are_scoped_per_file_so_a_second_file_can_still_start`：平行模式下偶發失敗（共用 file cache + 各 process 的 Import ID 重複），上游也有同樣風險。乾淨 cache 單獨跑會過。第 2 輪通過。
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
