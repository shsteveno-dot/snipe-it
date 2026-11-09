# 雲端測試結果（第 5 輪）

**結論：穩定。** 除了已知狀況外沒有新問題。補上 `/etc/hosts` 後，平行全套 0 失敗；S3 目錄平行跑 10 次，全部 0 失敗、0 略過；「這次的重點」6 項都符合預期。

分支 `cloud-test` `b34ae8d`（程式碼 = `all-changes` `930b3456cc`），基準為上游 develop `f9f3a6067c`。完整輸出見 `cloud-test-output.txt`。

## 1. 環境與耗時

| 項目 | 值 |
| --- | --- |
| PHP | 8.3.6 (CLI, NTS)，要求的擴充套件都有 |
| 資料庫 | MariaDB 10.11.14（`/usr/bin/mysql` 是指向 `mariadb` 的 symlink） |
| CPU | 4 核心（Intel Xeon @ 2.10GHz），15 GB RAM |
| 模式 | 平行模式，ParaTest 7.8.5 / PHPUnit 11.5.55，4 個 process（另外有幾次單一 process 的針對性測試） |
| `.env.testing` | 和第 3、4 輪相同；`DB_DUMP_PATH` 未設 |

| 階段 | 耗時 |
| --- | --- |
| 安裝 | 0（沿用同一個容器，`composer.lock` 沒變；只重建 `snipeit_test` 並 `migrate`，不到 1 分鐘） |
| 第 1、2、4 項的針對性測試 | 約 2 分鐘 |
| S3 目錄平行跑 10 次 | 每次 11–12 秒，共約 2 分鐘 |
| 平行全套（1 次，已補 `/etc/hosts`） | 6 分 48 秒 |
| 分析與寫報告 | 約 8 分鐘 |

## 2. 測試數量

| | 總數 | 通過 | 失敗 | 錯誤 | 略過 | 未完成 |
| --- | --- | --- | --- | --- | --- | --- |
| 這次（`b34ae8d`，已補 `/etc/hosts`） | 6061 | 6005 | **0** | 0 | 3 | 53 |
| 第 4 輪（`7565dee`，沒有補 `/etc/hosts`） | 6061 | 5991 | 14 | 0 | 3 | 53 |

- 這次照「已知狀況」先補了 `/etc/hosts`，所以第 4 輪那 14 個 DNS 測試也通過了。跑完已還原，`getent ahosts example.com` 恢復成沒有輸出。
- 3 個略過都是程式碼本來就標記跳過的（`ApiRateLimitTest` 兩個、`DeleteAssetsTest::test_cannot_delete_asset_that_is_checked_out`）。**S3 測試 0 略過。**
- `ImporterMutexTest` 這次也通過。

## 3. 失敗與可疑的略過

沒有。

## 4. 「這次的重點」逐項回答

### 4.1 兩個 restore 測試類別全過、0 略過，每個測試仍約 0.1 秒：**是**

| | 單一 process | 平行（S3 目錄 10 次 / 全套） |
| --- | --- | --- |
| `RestoreToRemoteDiskTest`（23 個） | 全過，0 略過；每個測試中位數 0.100 秒（0.073–0.11 秒，第一個測試含開頭的 migration 4.2 秒） | 全過，0 略過；整個類別 2.2–2.4 秒 / 2.45 秒 |
| `StagingAssumptionsTest`（3 個） | 全過，0 略過；0.12–0.18 秒 | 全過，0 略過；全套裡 0.43 秒 |

和第 4 輪相同，沒有回到每個測試重跑 migration。

### 4.2 平行模式下 `tearDown` 之後 `mysql.database` 是 worker 自己的資料庫：**是**

暫時在 `UsesScratchDatabase::dropScratchDatabase()` 結尾加一行觀察，寫進檔案，平行跑整個 S3 目錄（87 個全過）。觀察完已還原，沒有 commit，`git status` 是乾淨的。

| 次數 | `TEST_TOKEN` | `mysql.database`（設定） | 預設連線實際的資料庫 | `dump_path` |
| --- | --- | --- | --- | --- |
| 23（`RestoreToRemoteDiskTest`） | 4 | `snipeit_test_test_4` | `snipeit_test_test_4` | `/usr/bin` |
| 1（`StagingAssumptionsTest::restore_recognises_…`） | 2 | `snipeit_test_test_2` | `snipeit_test_test_2` | `/usr/bin` |

沒有任何一次是 `snipeit_test`。說明檔建議用 `fwrite(STDERR, …)`，但 ParaTest 不會轉送 worker 的 STDERR（輸出裡什麼都看不到），所以改成寫檔。

### 4.3 資料庫檢查（S3 目錄跑完、全套跑完各一次）：**兩次都符合**

| 檢查 | S3 目錄 10 次之後 | 全套之後 |
| --- | --- | --- |
| `SHOW DATABASES LIKE 's3compat%'` | 沒有結果 | 沒有結果 |
| 各 `snipeit_test%` 資料庫的表數量 | 5 個都是 63 | 5 個都是 63 |
| `s3compat_probe` 表的數量 | 0 | 0 |
| 上傳目錄殘留（`git status --ignored --untracked-files=all`） | 沒有 | 沒有 |

### 4.4 `mysqlClientDirectory()`：**預設會找到 `/usr/bin`；找不到時是「跳過」而不是失敗**

- 預設設定：`DB_DUMP_PATH` 未設，所以 `dump_binary_path` 是 `config/database.php` 的預設值 `/usr/local/bin`，但那裡沒有 `mysql`。4.2 的觀察顯示，實際用的是 `/usr/bin`。
- 找不到的情況：暫時把 `/usr/bin/mysql`（symlink）改名，確認 `command -v mysql` 沒有結果（`/bin` 是 `/usr/bin` 的 symlink，所以也一起找不到）：
  - 單一 process 跑兩個 restore 類別：26 個裡 **25 個略過**，訊息是 `The restore tests need the mysql client.`，**0 失敗**。另外 1 個（`StagingAssumptionsTest` 裡不需要 mysql 的測試）通過。
  - 平行跑整個 S3 目錄：87 個，**25 個略過、0 失敗**，沒有卡住。這也代表 `setUp` 裡跳過時，上傳目錄的鎖有在 `tearDown` 被釋放。
  - 跑完已還原 `/usr/bin/mysql`。

### 4.5 平行模式跑 S3 目錄 10 次：**全部 0 失敗、0 略過**

| 次 | 結果 | 總耗時 | `RestoreToRemoteDiskTest` |
| --- | --- | --- | --- |
| 1 | OK（87 個，334 個斷言） | 11 秒 | 2.3 秒 |
| 2 | OK（87 個，334 個斷言） | 11 秒 | 2.2 秒 |
| 3 | OK（87 個，334 個斷言） | 12 秒 | 2.3 秒 |
| 4 | OK（87 個，334 個斷言） | 11 秒 | 2.4 秒 |
| 5 | OK（87 個，334 個斷言） | 11 秒 | 2.2 秒 |
| 6 | OK（87 個，334 個斷言） | 11 秒 | 2.3 秒 |
| 7 | OK（87 個，334 個斷言） | 11 秒 | 2.2 秒 |
| 8 | OK（87 個，334 個斷言） | 11 秒 | 2.3 秒 |
| 9 | OK（87 個，334 個斷言） | 11 秒 | 2.2 秒 |
| 10 | OK（87 個，334 個斷言） | 11 秒 | 2.2 秒 |

### 4.6 平行全套一次：**0 失敗**

這次先補了 `/etc/hosts`：6061 個測試，6005 通過、0 失敗、0 錯誤、3 略過（都是本來就標記跳過的）、53 未完成，用了 6 分 48 秒。跑完已還原 `/etc/hosts`。

## 5. 修改建議

**程式碼：沒有值得做的建議。**

可以考慮的小地方（不影響結果，不改也可以）：

- `CLOUD_TEST.md` 第 2 項建議用 `fwrite(STDERR, …)` 觀察，但 ParaTest 不會轉送 worker 的 STDERR，平行模式下看不到輸出。另外 `php artisan test --parallel` 只接受一個路徑，不能同時指定兩個測試檔。如果以後還要做類似的觀察，建議說明檔改成「寫到暫存檔，例如 `file_put_contents('/tmp/probe.log', …, FILE_APPEND)`，並跑整個 S3 目錄」。
