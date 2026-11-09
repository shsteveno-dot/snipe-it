# 雲端測試結果（第 4 輪）

分支 `cloud-test` `7565dee`（程式碼 = `all-changes` `3820445291`），基準為上游 develop `f9f3a6067c`。完整輸出見 `cloud-test-output.txt`。

## 1. 環境與耗時

| 項目 | 值 |
| --- | --- |
| PHP | 8.3.6 (CLI, NTS)，要求的擴充套件都有 |
| 資料庫 | MariaDB 10.11.14 |
| CPU | 4 核心（Intel Xeon @ 2.10GHz），15 GB RAM |
| 模式 | 平行模式，ParaTest 7.8.5 / PHPUnit 11.5.55，4 個 process（另外有幾次單一 process 的針對性測試） |
| `.env.testing` | 和第 3 輪相同（照範本，`APP_TIMEZONE='UTC'`、`IMPORT_MEMORY_LIMIT=2G`、`LDAP_MEM_LIM=2G`） |

| 階段 | 耗時 |
| --- | --- |
| 安裝 | 0（同一個容器、`composer.lock` 沒變，沿用 `vendor/` 和 Passport 金鑰；只重建 `snipeit_test` 並 `migrate`，不到 1 分鐘） |
| restore 測試單一 process ＋ general log | 7 秒 |
| S3 目錄平行跑 10 次 | 每次 11 秒，共約 2 分鐘 |
| 平行全套（1 次） | 7 分 3 秒 |
| 順序檢查（單一 process，650 個測試） | 2 分 16 秒 |
| 分析與寫報告 | 約 10 分鐘 |

已照說明檔設定 `git config core.fileMode false`。

## 2. 測試數量

| | 總數 | 通過 | 失敗 | 錯誤 | 略過 | 未完成 |
| --- | --- | --- | --- | --- | --- | --- |
| 這次（`7565dee`） | 6061 | 5991 | 14 | 0 | 3 | 53 |
| 第 3 輪（`a01207d`） | 6061 | 5991 | 14 | 0 | 3 | 53 |

- 數字和第 3 輪完全一樣。14 個失敗**就是「已知狀況」列的那 14 個 `ExternalUrl`／DNS 測試**，沒有其他失敗。
- 3 個略過都是程式碼本來就標記跳過的（`ApiRateLimitTest` 兩個、`DeleteAssetsTest::test_cannot_delete_asset_that_is_checked_out`）。**S3 測試 0 略過。**

## 3. 失敗與可疑的略過

### 14 個 `ExternalUrl` 測試（已知的環境問題，上游也有）

這個容器仍然解析不到公開網域（`getent ahosts example.com` 沒有輸出）。失敗的測試和第 3 輪一樣：`GroupCompanyMappingTest` 2、`IntuneSettingsPageTest` 3、`KandjiSettingsPageTest` 1、`AssetTagPatternTest` 2、`FleetLicenseTierTest` 3、`FleetSettingsPageTest` 1、`CompanyWebhooksTest` 1、`WebhookEndpointSsrfTest` 1。

照「已知狀況」的方法，在 `/etc/hosts` 暫時補上 5 個主機後再跑這 8 個檔：**70 個全過**（跑完已還原）。第 3 輪已經確認上游 develop 也是 14 個失敗，這次沒有再對照上游。

沒有其他失敗或可疑的略過。

## 4. 「這次的重點」逐項回答

### 4.1 `RestoreToRemoteDiskTest` 不再每個測試重跑 migration：**是**

單一 process 跑 `RestoreToRemoteDiskTest` ＋ `StagingAssumptionsTest`（26 個，全過），同時開 MariaDB general log：

| | 第 3 輪 | 這次 |
| --- | --- | --- |
| `drop table snipeit_test.accessories, …`（`migrate:fresh`）次數 | 每個測試 1 次 | **整個執行只有 1 次**（process 開始時） |
| `RestoreToRemoteDiskTest` 每個測試耗時 | 3.5–4.3 秒 | 中位數 **0.09 秒**（0.07–0.11 秒）；只有第一個測試要付開頭那次 migration，約 4.0 秒 |
| `StagingAssumptionsTest` 每個測試耗時 | — | 0.08–0.20 秒 |
| `RestoreToRemoteDiskTest` 類別總耗時（平行，junit） | 86.1 秒 | **2.2–2.5 秒** |
| S3 目錄平行總耗時 | 84–99 秒（平均 91.5） | **11 秒**（10 次都是） |

現在 S3 目錄最慢的是 `BackupRemoteOptionTest` 7.2 秒、`BackupPageTest` 7.0 秒、`BackupDiskConsistencyTest` 6.6 秒、`AcceptanceAttachmentTest` 6.2 秒。這幾乎都是各 process 第一個測試的 migration 時間，屬於正常成本。

### 4.2 restore 測試本身仍然正確：**是**

- `RestoreToRemoteDiskTest`（23 個）和 `StagingAssumptionsTest`（3 個）在單一 process、S3 目錄 10 次平行、平行全套裡都全過（全套 junit：失敗 0、錯誤 0、略過 0）。
- scratch 資料庫：general log 裡 `CREATE DATABASE s3compat_*` 24 次、`DROP DATABASE IF EXISTS s3compat_*` 24 次，數量一致。每次 S3 平行跑完和全套跑完後，`SHOW DATABASES LIKE 's3compat%'` 都沒有結果。
- 測試資料庫沒有被 restore 改掉：
  - 全套跑完後，`snipeit_test` 和 `snipeit_test_test_1..4` 各有 63 張表，數量一致。
  - `information_schema` 裡任何資料庫都沒有 `s3compat_probe`（restore 用的 SQL dump 會建這張表）。
  - `s3compat_probe` 的寫入和讀取都經過 scratch 連線，並且明確寫成 `` `s3compat_restore_xxx`.`s3compat_probe` ``。

### 4.3 平行模式跑 S3 目錄至少 5 次：**10 次，全部 0 失敗、0 略過**

| 次 | 結果 | 總耗時 | `RestoreToRemoteDiskTest` |
| --- | --- | --- | --- |
| 1 | OK（87 個，334 個斷言） | 11 秒 | 2.3 秒 |
| 2 | OK（87 個，334 個斷言） | 11 秒 | 2.3 秒 |
| 3 | OK（87 個，334 個斷言） | 11 秒 | 2.3 秒 |
| 4 | OK（87 個，334 個斷言） | 11 秒 | 2.2 秒 |
| 5 | OK（87 個，334 個斷言） | 11 秒 | 2.3 秒 |
| 6 | OK（87 個，334 個斷言） | 11 秒 | 2.2 秒 |
| 7 | OK（87 個，334 個斷言） | 11 秒 | 2.5 秒 |
| 8 | OK（87 個，334 個斷言） | 11 秒 | 2.3 秒 |
| 9 | OK（87 個，334 個斷言） | 11 秒 | 2.3 秒 |
| 10 | OK（87 個，334 個斷言） | 11 秒 | 2.2 秒 |

每次跑完都沒有殘留的 scratch 資料庫，上傳目錄也沒有殘留。

### 4.4 平行全套一次：**除了已知的 14 個 DNS 測試外，0 失敗**

- S3 測試 0 略過。
- 上傳目錄沒有殘留：`git status --short --ignored --untracked-files=all public/uploads storage/private_uploads` 沒有輸出。
- 跑在 `RestoreToRemoteDiskTest` 之後的測試：
  - 全套裡沒有任何和資料庫狀態有關的失敗。
  - 平行模式看不到每個 process 的執行順序，所以另外用單一 process 依序跑 `RestoreToRemoteDiskTest` → `StagingAssumptionsTest` → `tests/Feature/Assets` → `tests/Feature/Checkouts`（junit 確認順序）。650 個測試全過，唯一的略過是已知的 `DeleteAssetsTest`。
  - 第 3 輪是因為「每個測試都重建資料庫」才剛好沒有出問題，現在則是真的維持在原本的測試交易裡。

## 5. 修改建議（依重要性排序）

### 1.（低到中，我們的改動，原本就存在）`tearDown` 用 `env('DB_DATABASE')` 還原資料庫名稱，在平行模式下會指到錯的資料庫

檔案：`tests/Feature/S3Compatibility/RestoreToRemoteDiskTest.php`、`tests/Feature/S3Compatibility/StagingAssumptionsTest.php`

原因：平行模式下，Laravel 會把 `database.connections.mysql.database` 設成 `snipeit_test_test_<N>`（`Illuminate/Testing/Concerns/TestDatabases.php:187,208`），但 `env('DB_DATABASE')` 還是 `snipeit_test`。所以 `tearDown` 之後，這條連線的設定會指到**所有 process 共用的基底資料庫**。

目前不會出事，因為 `tearDown` 不再 `DB::purge('mysql')`，現有的連線也不會重連，而下一個測試會重建 app。不過只要以後有人在 `tearDown` 裡加了重連的動作（例如 `DB::purge`、`DB::reconnect`），或者讓 `Artisan::call('up')` 碰到資料庫，就會在共用的 `snipeit_test` 上執行。第 3 輪以前的版本其實就是這樣：`purge` 之後的 `DROP DATABASE` 跑在 `snipeit_test` 上，只是剛好無害。

建議改法：在 `setUp` 記下原本的名稱，`tearDown` 還原它。

```diff
+    private string $originalDatabase = '';
@@ setUp()
+        $this->originalDatabase = (string) config('database.connections.mysql.database');
         config(['database.connections.'.self::SCRATCH_CONNECTION => config('database.connections.mysql')]);
@@ tearDown()
-            config(['database.connections.mysql.database' => env('DB_DATABASE')]);
+            config(['database.connections.mysql.database' => $this->originalDatabase]);
```

`StagingAssumptionsTest` 也一樣（它在測試方法裡才切換，所以要在切換前記下）。

### 2.（低，我們的改動）把 scratch 資料庫的處理抽成共用的 trait

檔案：上面兩個測試、新增例如 `tests/Support/S3Compatibility/UsesScratchDatabase.php`

原因：兩個類別各自定義了 `SCRATCH_CONNECTION`、複製連線設定、`CREATE`/`DROP DATABASE`、切換和還原 `mysql.database`、`dump_binary_path`，而且 `tearDown` 的順序不同。抽成一個 trait（例如 `useScratchDatabase(string $prefix): string` 和 `dropScratchDatabase()`），建議 1 的修正只需要改一處，以後新增 restore 測試也不容易又在測試連線上做 DDL。trait 的註解可以寫明「不要在測試連線上做 DDL 或 purge，否則 `RefreshDatabase` 會重跑全部 migration」。

### 3.（低，我們的改動）`dump_binary_path` 寫死 `/usr/bin`

檔案：同上兩個測試

原因：macOS（Homebrew 的 `/opt/homebrew/bin`）或 Herd 這類環境的 `mysql` 不在 `/usr/bin`，restore 測試會失敗，而不是跳過。這次的容器在 `/usr/bin`，所以沒有影響。建議：用 `dirname((string) shell_exec('command -v mysql'))` 取得路徑，找不到就 `markTestSkipped('The restore tests need the mysql client.')`；或者先讀 `config('database.connections.mysql.dump.dump_binary_path')`，沒有設定時才用上面的方法。

### 4.（低，上游本來就有）`ExternalUrl` 依賴 DNS

照說明檔，這次不改。已記錄在「已知狀況」，`/etc/hosts` 的方法這次驗證有效（70 個全過）。

### 5.（低）`CLOUD_TEST.md` 說明檔

- 步驟 4 寫「重複跑 `tests/Feature/S3Compatibility`（每次不到 2 分鐘）」，現在是約 11 秒，可以改成「每次約 10–15 秒，建議 10 次」。
- 「這次的重點」第 2 項，建議把具體的檢查方法寫進去，下一輪可以直接照做：
  - `SHOW DATABASES LIKE 's3compat%'`；
  - `SELECT table_schema, COUNT(*) FROM information_schema.tables WHERE table_schema LIKE 'snipeit_test%' GROUP BY table_schema`（數量應該一致）；
  - `SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 's3compat_probe'`（應該是 0）。
- 如果希望全套結果是 0 失敗，可以在「步驟 3」之前加一個可選步驟：DNS 不通時先把 5 個主機加進 `/etc/hosts`，跑完還原。這樣報告比較不會被已知的 14 個失敗干擾。
- 「已知狀況」的 `ImporterMutexTest` 這輪和上輪都通過，可以註明最近 3 輪都沒有重現。
