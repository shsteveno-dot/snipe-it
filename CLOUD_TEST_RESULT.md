# 雲端測試結果（第 3 輪）

分支 `cloud-test` `a01207d`（程式碼 = `all-changes` `e9ff762908`），基準為上游 develop `f9f3a6067c`。完整輸出見 `cloud-test-output.txt`。

## 1. 環境與耗時

| 項目 | 值 |
| --- | --- |
| PHP | 8.3.6 (CLI, NTS)。`bcmath`、`ldap` 原本沒有，用 apt 裝了 `php8.3-bcmath`、`php8.3-ldap`；其他要求的擴充套件原本就有 |
| 資料庫 | MariaDB 10.11.14（apt 安裝） |
| CPU | 4 核心（Intel Xeon @ 2.10GHz），15 GB RAM |
| 模式 | 平行模式，ParaTest 7.8.5 / PHPUnit 11.5.55，4 個 process |
| `.env.testing` | 照範本，`APP_TIMEZONE='UTC'`、`IMPORT_MEMORY_LIMIT=2G`、`LDAP_MEM_LIM=2G`；`cp .env.testing .env` |

這次是全新的容器，`vendor/` 和資料庫都要從頭裝。

| 階段 | 耗時 |
| --- | --- |
| 安裝（apt 裝 MariaDB 和 PHP 擴充套件、`composer install --prefer-source`、`key:generate`、`migrate`、`passport:install`） | 約 14 分鐘，其中 composer 佔 12 分 48 秒 |
| 平行全套（1 次） | 7 分 16 秒 |
| S3 目錄平行跑 10 次 | 15 分 15 秒（每次 84–99 秒） |
| 分析（DNS 失敗對照上游、耗時分析） | 約 10 分鐘 |

安裝備註：
- 照說明檔的方法測 zip 下載，`api.github.com` 回 403，所以用 `--prefer-source`。
- `phpstan/phpstan` 只有 dist：我從 github.com 的 git repo fetch lock 檔指定的 commit（`9eaac38`），用 `git archive` 打包，放進 Composer 快取（`~/.cache/composer/files/phpstan/phpstan/<sha1(dist url)>.zip`）。`composer.lock` 沒有改。
- `--prefer-source` 會把 `league/flysystem` 這類 monorepo 的完整原始碼 clone 下來，所以 autoload 時出現 `Ambiguous class resolution` 警告，不影響測試。
- Passport 金鑰在開跑前就產生了，這次沒有出現 `Invalid key supplied`。

## 2. 測試數量

| | 總數 | 通過 | 失敗 | 錯誤 | 略過 | 未完成 |
| --- | --- | --- | --- | --- | --- | --- |
| 這次（`a01207d`） | 6061 | 5991 | **14** | 0 | 3 | 53 |
| 第 2 輪（`4399781`） | 6061 | 6004 | 1 | 0 | 3 | 53 |

差異：
- 第 2 輪失敗的 `EulaDownloadTest` 這次通過。
- 新出現的 14 個失敗都是**這個容器解析不到公開網域的 DNS**造成的環境問題，與程式碼無關（見第 3 節）。排除這 14 個後，就是 0 失敗。
- 3 個略過和上游一樣，都是程式碼本來就標記跳過的：`ApiRateLimitTest` 兩個（"This test is flappy…"）、`DeleteAssetsTest::test_cannot_delete_asset_that_is_checked_out`（"This behavior is not functioning yet."）。**S3 測試 0 略過。**

## 3. 失敗與可疑的略過

### 14 個失敗：`ExternalUrl` 驗證查不到 DNS（環境問題，上游也一樣）

| 測試 | 數量 |
| --- | --- |
| `SyncAdapters\GroupCompanyMappingTest` | 2 |
| `SyncAdapters\Intune\IntuneSettingsPageTest` | 3 |
| `SyncAdapters\Kandji\KandjiSettingsPageTest` | 1 |
| `SyncAdapters\AssetTagPatternTest` | 2 |
| `SyncAdapters\Fleet\FleetLicenseTierTest` | 3 |
| `SyncAdapters\Fleet\FleetSettingsPageTest` | 1 |
| `Companies\Api\CompanyWebhooksTest::test_can_filter_companies_with_webhooks` | 1 |
| `Companies\Api\WebhookEndpointSsrfTest::test_api_accepts_a_public_https_webhook_endpoint_from_superuser` | 1 |

錯誤摘要：`The intune url field must be a valid external URL (http:// or https://) that does not point at a private or local address.`，表單被退回，所以後面的斷言失敗（`null is identical to '209'`、`0 is identical to 1` 之類）。

原因：`app/Rules/ExternalUrl.php` 用 `gethostbynamel()` / `dns_get_record()` 解析主機。這個容器只能經過 proxy 連外，`getent ahosts` 查 `example.com`、`graph.microsoft.com`、`example.api.kandji.io`、`hooks.slack.com` 都沒有結果，所以這些網址被當成「解析不到」而拒絕。

驗證（輸出檔第 2 段）：
- 本分支單一 process 跑這 8 個檔：14 個失敗、56 個通過，所以不是平行競爭。
- 在 `/etc/hosts` 暫時加上這些主機的公開 IP 後再跑：70 個全過（跑完已還原 `/etc/hosts`）。
- 上游 develop `f9f3a6067c` 跑同樣 8 個檔：一樣 14 個失敗。
- `app/Rules/ExternalUrl.php` 在本分支和上游是同一個版本（最後一次修改都是 `886bd48`）。

結論：上游本來就有，原因是環境。第 2 輪沒出現，是因為那個容器的 DNS 可以解析。修改建議見第 5 節第 2 點。

## 4. 「這次的重點」逐項回答

### 4.1 平行模式只跑 `tests/Feature/S3Compatibility` 10 次（每次都加 `--display-skipped`）

| 次 | 結果 | 耗時 |
| --- | --- | --- |
| 1 | OK（87 個，334 個斷言），0 略過 | 87 秒 |
| 2 | OK（87 個，334 個斷言），0 略過 | 86 秒 |
| 3 | OK（87 個，334 個斷言），0 略過 | 84 秒 |
| 4 | OK（87 個，334 個斷言），0 略過 | 87 秒 |
| 5 | OK（87 個，334 個斷言），0 略過 | 88 秒 |
| 6 | OK（87 個，334 個斷言），0 略過 | 97 秒 |
| 7 | OK（87 個，334 個斷言），0 略過 | 94 秒 |
| 8 | OK（87 個，334 個斷言），0 略過 | 99 秒 |
| 9 | OK（87 個，334 個斷言），0 略過 | 97 秒 |
| 10 | OK（87 個，334 個斷言），0 略過 | 96 秒 |

第 11 次（加 `--log-junit` 量耗時）也是 OK。**11 次全部 0 失敗、0 略過**，`e9ff762908` 修好了第 2 輪的競爭。因為第 1 項已經穩定，不需要重新評估建議 2（見 5.4）。

### 4.2 平行全套一次

- S3 測試 0 略過：**是**（全套只有 3 個略過，都不是 S3 測試）。
- `EulaDownloadTest`、`MoveUploadsToNewDiskTest` 沒有失敗：**是**。
- `storage/private_uploads` 和 `public/uploads` 沒有留下檔案：**是**。全套跑完、S3 跑完 10 次之後，`git status --short --ignored --untracked-files=all public/uploads storage/private_uploads` 都沒有未追蹤或被忽略的檔案。
  - 唯一的輸出是 4 個 `.gitignore`/`.gitkeep` 的權限變動（644 → 755），是 CI 步驟裡的 `chmod -R 777 storage bootstrap/cache` 造成的，已經改回來，沒有 commit。

### 4.3 加鎖後 S3 目錄的平行耗時

- 這次：84–99 秒，平均 91.5 秒。第 2 輪約 1.5–2 分鐘（90–120 秒）。**沒有變慢。**
- 原因：S3 目錄的總耗時取決於 `RestoreToRemoteDiskTest` 這個測試類別。它有 23 個測試、單獨就花了 86.1 秒，而且整個類別只在一個 process 裡跑。其他會拿鎖的類別加起來只有約 14 秒（`AcceptanceAttachmentTest` 7.0 秒、`StagingAssumptionsTest` 4.8 秒、`EulaDownloadTest` 1.6 秒、`MoveUploadsToNewDiskTest` 0.9 秒），所以排隊的時間被 `RestoreToRemoteDiskTest` 蓋過去了。
- 但 `RestoreToRemoteDiskTest` 慢，是因為**每個測試都重跑一次 `migrate:fresh`**，不是 restore 本身慢。量測（輸出檔第 4、5 段）：
  - 每個測試約 3.5–4.3 秒，連「讀不到 zip 就結束」的測試也一樣。直接執行 `php artisan snipeit:restore <非 zip>` 只要 0.3 秒，`CREATE/DROP DATABASE` 各約 0.01 秒。
  - MariaDB general log 顯示：每個測試開始前都會 `drop table snipeit_test.accessories, …` 再建 128 張表。
  - 原因：`setUp` 裡的 `CREATE DATABASE` 會在 MySQL 隱含 commit，`tearDown` 又執行 `DB::purge('mysql')`。Laravel 的 `RefreshDatabase::beginDatabaseTransaction()` 在收尾時發現連線不在交易裡，就把 `RefreshDatabaseState::$migrated` 設成 `false`，所以下一個測試（在全套裡就是同一個 process 的下一個測試）會重跑全部 migration。
  - 改法見 5.1。可以把 S3 目錄的耗時從約 90 秒降到約 20 秒，全套也會快約 80 秒的單一 process 時間。

## 5. 修改建議（依重要性排序）

### 1.（中，我們的改動）`RestoreToRemoteDiskTest` 每個測試都觸發 `migrate:fresh`

檔案：`tests/Feature/S3Compatibility/RestoreToRemoteDiskTest.php`

原因：見 4.3。23 個測試 × 約 3.5 秒的 migration，佔 S3 目錄約 90% 的時間。在全套裡，跑到這個類別的那個 process 也會多花約 80 秒，而且之後的測試會在剛重建的資料庫上執行。第 2 輪建議 2 提到的「破壞性測試分組」，如果要再單獨跑一次這個 group，這也會是那次的主要成本。

建議改法（擇一）：

a. 建立和刪除 scratch 資料庫時，改用另一條獨立的 PDO 連線（例如 `mysql_scratch_admin`），讓主連線 `mysql` 的測試交易不受 DDL 影響；restore 命令改用另一個連線名稱指向 scratch 資料庫，就不需要 `DB::purge('mysql')`。這需要 `snipeit:restore` 可以指定連線（例如讀 `config('database.default')`），所以要先確認命令的寫法。

b. 改動最小的做法：接受每個類別重跑一次，但不要每個測試都重跑。在 `setUpBeforeClass` 用原生 PDO 建立一個 scratch 資料庫，`tearDownAfterClass` 刪掉；每個測試只在 scratch 資料庫裡 `DROP TABLE IF EXISTS s3compat_probe`，並且 `tearDown` 只做 `config([... => env('DB_DATABASE')])` 加上 `DB::purge`。注意 `DB::purge` 本身就會讓 `inTransaction()` 變成 false，所以 b 只能減少 DDL 的次數，`$migrated` 還是會被重設，**效果有限**。

c. 明確承認這個類別需要乾淨的資料庫：改成 `use DatabaseMigrations;`，或者在 `tearDown` 結尾自己設 `RefreshDatabaseState::$migrated = false`。耗時不會改善，但行為會變得明確，也不會讓下一個測試「意外地」在重建後的資料庫上執行。

建議先試 a。如果 restore 命令沒辦法換連線，就用 c 把行為寫明，並在 CI 文件記錄這個類別約佔 90 秒。

### 2.（中，上游本來就有，環境相關）`ExternalUrl` 的測試依賴真實的 DNS

檔案：`app/Rules/ExternalUrl.php`（上游）、上面 8 個測試檔（上游）

原因：沒有 DNS（或只能經過 proxy 連外）的環境，會讓 14 個測試失敗。這次的雲端容器就是這樣，離線開發環境也會。

建議改法：讓解析的部分可以在測試裡替換，例如把 `resolveHost()` 抽成可以注入的 resolver（`app()->bind(HostResolver::class, …)`），在 `TestCase::setUp()` 裡綁定一個 fake：`example.com`、`graph.microsoft.com` 之類的主機回傳固定的公開 IP，`localhost`、`metadata.google.internal` 回傳私有 IP。這樣 SSRF 的測試也不必依賴外部 DNS 的結果。這是上游程式碼，可以考慮回饋給上游，不一定要放在我們的分支。

暫時的替代方案：在 `CLOUD_TEST.md` 加一行，說明 DNS 不通時這 14 個失敗是預期的；或者用 `/etc/hosts` 補上這些主機（見 5.5）。

### 3.（低，我們的改動）`lockRealUploadDirectories()` 的小細節

檔案：`tests/Support/S3Compatibility/ProtectsRealUploadDirectories.php`

- 鎖檔放在 `sys_get_temp_dir()/snipeit-upload-directories.lock`，同一台機器上的**不同 checkout**（例如步驟 4 的 `/tmp/dev` 上游 worktree，或兩個開發目錄）會互相排隊，但它們保護的其實是不同的目錄。影響只是多等一下，不會出錯。如果要修正，可以在鎖檔名稱裡加上 `md5(base_path())`。
- `flock($lock, LOCK_EX)` 沒有逾時。process 結束時作業系統會自動放鎖，所以不會永久卡住，可以不改。

### 4.（低，我們的改動）重新評估第 2 輪的建議 2

第 1 項已經穩定，目前**不需要**做破壞性測試分組或隔離目錄。剩下的風險是：上游或我們以後新增的測試，如果在平行模式下寫入真實的 `storage/private_uploads`，又沒有拿鎖，S3 測試就可能看到殘留檔而跳過，或者出現跟第 2 輪一樣的競爭。可以做一個低成本的防護：在 `ProtectsRealUploadDirectories` 跳過測試的訊息裡印出殘留檔的完整清單（目前只印第一個加數量），出事時比較好追是哪個測試寫的。第 2 輪建議 3（`ImporterMutexTest`）這次通過，維持低優先。

### 5.（低）`CLOUD_TEST.md` 說明檔

- 「已知狀況」補上：容器沒有 DNS 時，`ExternalUrl` 相關的 14 個測試（上面的 8 個檔）會失敗，上游也一樣。快速確認：`getent ahosts example.com` 沒有輸出，就是這個狀況。如果想讓它們通過，可以在跑測試前暫時把 `example.com graph.microsoft.com graph.microsoft.us example.api.kandji.io hooks.slack.com` 加進 `/etc/hosts`，對應到任一公開 IP，跑完再還原。
- 「步驟」補上：全新容器可能沒有 `bcmath`、`ldap`，`apt-get install php8.3-bcmath php8.3-ldap`；也可能沒有 MariaDB，`apt-get install mariadb-server`。
- phpstan 的補救方法寫具體一點：`git fetch --depth 1 https://github.com/phpstan/phpstan.git <lock 裡的 reference>` → `git archive --prefix=phpstan/ -o x.zip FETCH_HEAD` → 複製到 `~/.cache/composer/files/phpstan/phpstan/$(php -r 'echo sha1("<lock 裡的 dist url>");').zip`，再執行 `composer install --prefer-source`。
- `chmod -R 777 storage bootstrap/cache` 會讓 git 顯示 4 個檔案的權限變動，提醒不要 commit 這些變動（或者先 `git config core.fileMode false`）。
- 第 3 項（耗時比較）建議改成看 `--log-junit` 裡各測試類別的時間，總耗時看不出加鎖的影響（見 4.3）。
