# 雲端測試結果（第 9 輪：新備份測試的修正）

**結論：穩定。** 第 8 輪建議 1 的修正有效：

- pint 通過；
- `BackupRemoteOptionTest` 19 個、`BackupPageTest` 8 個全過，0 略過；
- 反證時兩個新測試都失敗，還原後通過，失敗時 `/tmp` 沒有留下目錄；
- S3 目錄平行跑 5 次，全部 0 失敗、0 略過、沒有殘留。

分支 `cloud-test` `7a430fa`（程式碼 = `all-changes` `04a07b3584`）。完整輸出見 `cloud-test-output.txt`。

## 1. 環境與耗時

沿用同一個容器：PHP 8.3.6、MariaDB 10.11.14（這次本來就在跑）、ParaTest 4 個 process。`vendor/` 是第 8 輪裝的，`composer.lock` 沒變，所以沒有重裝。照說明檔，這輪不重建 chiseled、不跑全套。

| 階段 | 耗時 |
| --- | --- |
| 重建 `snipeit_test` ＋ `migrate` | 不到 1 分鐘 |
| pint、兩個測試類別、反證 | 約 1 分鐘 |
| S3 目錄平行 5 次 | 每次 10–11 秒 |
| 分析與寫報告 | 約 3 分鐘 |

## 2. 逐項結果

### 2.1 pint：**通過**

`vendor/bin/pint --test tests/Feature/S3Compatibility/BackupRemoteOptionTest.php` → `{"tool":"pint","result":"passed"}`

### 2.2 兩個測試類別（單一 process）：**全過，0 略過**

| 類別 | 結果 |
| --- | --- |
| `BackupRemoteOptionTest` | OK（19 個，72 個斷言），包含 `✔ Missing include paths are left out and named instead of failing the backup`、`✔ Missing include paths are left out on an all local install too` |
| `BackupPageTest` | OK（8 個，39 個斷言），包含 `✔ A failed backup shows the reason rather than a progress line` |

第 8 輪的 `Undefined array key 0` 已經不會出現。斷掉的 symlink 現在建立失敗時會 `fail`（Windows 上是 `markTestSkipped`），而這次 0 略過、0 失敗，表示 symlink 有建立，`$missing` 一定是兩個路徑。

### 2.3 反證：**成立**

暫時把 `SystemBackup::handle()` 的兩處 `$existing` 改回 `$include`（`array_merge($include, [$extra])` 和 `useIncludes($include)`），只跑兩個新測試：

| 測試 | 結果 |
| --- | --- |
| `missing_include_paths_are_left_out_and_named_instead_of_failing_the_backup` | **失敗**：`only the S3 manifest directory is added — Failed asserting that actual size 5 matches expected size 3.` |
| `missing_include_paths_are_left_out_on_an_all_local_install_too` | **失敗**：`Failed asserting that two arrays are identical.` |

- 這次是斷言失敗，不是第 8 輪的 `Undefined array key 0`，所以測試確實在檢查修正。
- 故意讓測試失敗之後，`ls -d /tmp/s3compat-missing-*` 是 **0 個**，`tearDown` 的清理有效。
- 還原後再跑：OK（2 個，9 個斷言）。`git status` 乾淨。

### 2.4 S3 目錄平行 5 次：**全部 0 失敗、0 略過**

| 次 | 結果 | 耗時 | `/tmp/s3compat-missing-*` | scratch 資料庫 |
| --- | --- | --- | --- | --- |
| 1 | OK（90 個，346 個斷言） | 10 秒 | 0 | 0 |
| 2 | OK（90 個，346 個斷言） | 10 秒 | 0 | 0 |
| 3 | OK（90 個，346 個斷言） | 11 秒 | 0 | 0 |
| 4 | OK（90 個，346 個斷言） | 11 秒 | 0 | 0 |
| 5 | OK（90 個，346 個斷言） | 10 秒 | 0 | 0 |

上傳目錄和 `storage/app/backups` 都沒有殘留（只有原本就有的 `env-backups`）。

## 3. 清理

測試資料庫（`snipeit_test`、`_test_1..4`）已刪除。這輪沒有啟動 dockerd，也沒有建 worktree。程式和測試的暫時修改都已還原。

## 4. 修改建議

沒有。
