# 雲端測試結果（第 8 輪：沒有金鑰檔時的備份）

**結論：程式修正有效，但新測試 `missing_include_paths_are_left_out_and_named_instead_of_failing_the_backup` 本身寫錯了，每次都會失敗。**

- 程式修正：
  - 用真的 Spatie 測，含斷掉的 symlink 時 `snipeit:backup` 是 exit 0、印出 `Skipping`、產生 zip；同樣的 include 直接交給 Spatie 的 `backup:run`，會重現正式環境的錯誤。
  - chiseled 的四個驗收全部 exit 0，`backup_without_key_files` 是 `true`。
- 新測試的問題：`$command = $this->artisan(...)` 拿到的 `PendingCommand` 要到解構時才會執行，但測試在那之前就讀 `calls()[0]`，結果是 `ErrorException: Undefined array key 0`。只要加上 `->run()`，19 個全過，反證也成立（見 5.1）。
- 這個測試以外：S3 目錄和全套都沒有其他失敗或可疑的略過。

分支 `cloud-test` `8659978`（程式碼 = `all-changes` `57e3245981`），基準為上游 develop `f9f3a6067c`。完整輸出見 `cloud-test-output.txt`，驗收 json 在 `cloud-verify/round8/`。

## 1. 環境與耗時

| 項目 | 值 |
| --- | --- |
| 主機 | 同一個容器（x86_64，4 核心）。容器有重啟過：MariaDB 沒在跑（`service mariadb start` 後重建 `snipeit_test`），代理 port 變成 37581 |
| PHP / DB | PHP 8.3.6、MariaDB 10.11.14、ParaTest 4 個 process |
| `vendor/` | `composer install --prefer-source --no-scripts`，用 `~/.cache/composer` 的 mirror，**618 秒**。`composer.lock` 沒變 |
| Docker | dockerd 29.9.2（用當下的 `$HTTPS_PROXY`）。Docker Hub 這輪多次回 `429`：composer、ubuntu、python 的 image 都重試 1–3 次（每次間隔約 45–60 秒）才拉到 |

| 階段 | 耗時 |
| --- | --- |
| composer install（和 chiseled build 同時跑） | 10 分 18 秒 |
| chiseled build（沒有快取） | 259 秒 |
| 四個驗收 | 93 秒 / 33 秒 / 1 秒 / 35 秒（`regression` 第一次因為 429 沒開始，重試後完成） |
| pint、新測試、symlink 探針、反證、真的 Spatie | 約 5 分鐘 |
| S3 目錄平行 5 次 ＋ 2 次對照 | 每次 10–11 秒 |
| 平行全套 | 6 分 30 秒 |
| 分析與寫報告 | 約 10 分鐘 |

## 2. 測試數量

| | 總數 | 通過 | 失敗 | 錯誤 | 略過 | 未完成 |
| --- | --- | --- | --- | --- | --- | --- |
| 這次（`8659978`，已補 `/etc/hosts`） | 6064 | 6007 | 0 | **1** | 3 | 53 |
| 第 5 輪（`b34ae8d`，已補 `/etc/hosts`） | 6061 | 6005 | 0 | 0 | 3 | 53 |

- 多出來的 3 個是新測試。其中 2 個通過，1 個錯誤，原因見 5.1。
- 3 個略過是程式碼本來就標記跳過的（`ApiRateLimitTest` 兩個、`DeleteAssetsTest`）。**S3 測試 0 略過。**

## 3. 失敗

### `BackupRemoteOptionTest::missing_include_paths_are_left_out_and_named_instead_of_failing_the_backup` — **我們新增的測試寫錯了**

```
ErrorException: Undefined array key 0
tests/Feature/S3Compatibility/BackupRemoteOptionTest.php:240
```

- 單一 process、平行 S3 目錄 5 次、平行全套，每次都失敗，而且是穩定失敗，不是競爭造成的。上游沒有這個測試。
- 原因：
  - 第 230 行 `$command = $this->artisan(...)` 回傳的是 `PendingCommand`；
  - `expectsOutputToContain()`、`assertExitCode()` 只是設定期望值；
  - 命令要到 `PendingCommand::__destruct()`（或明確呼叫 `run()`）才會執行；
  - 但 `$command` 這個變數要到方法結束才會解構，所以第 240 行讀 `$this->calls()[0]` 時，stub 的 `backup:run` 一次都還沒被呼叫。
- 另一個新測試 `missing_include_paths_are_left_out_on_an_all_local_install_too` 寫的是 `$this->artisan(...)->assertExitCode(0);`。暫時物件在那一行結束時就解構了，所以不會有這個問題。
- 驗證：暫時把第 234 行改成 `$command->assertExitCode(0)->run();`，`BackupRemoteOptionTest` 19 個全過（72 個斷言）；S3 目錄平行跑 2 次，90 個全過。
- 副作用：這個測試失敗時，最後一行的 `File::deleteDirectory($root)` 執行不到，會在 `/tmp` 留下 `s3compat-missing-*`。這輪累積了 9 個，已經刪掉。

## 4. 「這次的重點」逐項回答

### 4.1 pint：**通過**

`vendor/bin/pint --test` 檢查 4 個檔案：`{"tool":"pint","result":"passed"}`，沒有格式問題。

### 4.2 新測試和相關類別：**`BackupPageTest` 8 個全過；`BackupRemoteOptionTest` 19 個裡有 1 個錯誤（測試寫錯，見第 3 節）**

- `BackupPageTest::a_failed_backup_shows_the_reason_rather_than_a_progress_line`：通過。
- **斷掉的 symlink 有建立。** 我暫時在 `includeWithMissingPaths()` 加了 `assertCount(2, $missing)` 和 `is_link(...) && ! file_exists(...)` 的斷言，並把結果寫到檔案（已還原）。兩個 `missing_include_paths_*` 測試都記錄到：
  `missing=[".../oauth-private.key", ".../oauth-public.key"] is_link=true target=.../nowhere/oauth-public.key`
  也就是說，`@symlink` 沒有失敗，`$missing` 裡有 2 個路徑，其中一個是真正斷掉的 symlink。

### 4.3 反證：**成立，但要先修好測試**

- 用 commit 的測試做反證**沒有意義**：不管程式對不對，它都會因為 `Undefined array key 0` 失敗。
- 所以我在加了 `->run()` 的測試上做：把 `handle()` 裡的兩處 `$existing` 改回 `$include`（`array_merge($include, [$extra])` 和 `useIncludes($include)`），結果：
  - `missing_include_paths_are_left_out_and_named_instead_of_failing_the_backup`：**失敗**，`only the S3 manifest directory is added — Failed asserting that actual size 5 matches expected size 3.`
  - `missing_include_paths_are_left_out_on_an_all_local_install_too`：**失敗**，`Failed asserting that two arrays are identical.`
- 改回去之後兩個都通過。程式和測試都已還原（`git status` 乾淨）。

### 4.4 真的 Spatie（不是 stub）：**修正有效，而且對照重現了原本的 bug**

用 tinker 設定 include：一個存在的檔案、一個指向不存在路徑的 symlink（`oauth-private.key`）、一個不存在的路徑（`missing-public.key`）；`exclude` 設成空的；`dump_binary_path` 設成 `/usr/bin`；資料庫是 MariaDB 的 `snipeit_test`。

| | 指令 | 結果 |
| --- | --- | --- |
| 修正後 | `Artisan::call('snipeit:backup', ['--without-remote-files' => true, '--filename' => 'round8-real-spatie'])` | **exit 0**；輸出兩行 `Skipping …: it does not exist.`，接著 `Zipping 2 files and directories…`、`Backup completed!`；zip 裡有 `db-dumps/mysql-snipeit_test.sql`（111 KB）和 `real.txt`；之後 include 設定已還原（`INCLUDE_RESTORED=true`） |
| 對照：直接用 Spatie | 同一份設定，`app()->forgetInstance(Spatie\Backup\Config\Config::class)` 後直接執行 `Spatie\Backup\Commands\BackupCommand` | **exit 1**：`Backup failed because: The "…/oauth-private.key" directory does not exist..`，和正式環境的訊息一樣 |

zip、暫存目錄、tinker 的設定都已清掉，`storage/app/backups` 只剩 `env-backups`。

另外發現：直接改 `config()` 不會影響已經解析過的 Spatie `Config` 單例，所以第一次對照時，Spatie 用的是預設的 include（打包了 69 個檔案）。`SystemBackup::useIncludes()` 裡的 `forgetInstance(Config::class)` 和重新註冊 `backup:run` 是必要的，這點我已驗證。

### 4.5 S3 目錄平行 5 次 ＋ 平行全套

| 次 | 結果 |
| --- | --- |
| 1–5（commit 的程式碼） | 每次都是 90 個測試、**0 略過**、**1 個錯誤**（第 3 節那個測試），10–11 秒；沒有殘留的 scratch 資料庫 |
| 對照 1–2（暫時加 `->run()`） | **OK（90 個，346 個斷言）**，0 失敗、0 略過 |

平行全套（已補 `/etc/hosts`，跑完已還原）：6064 個測試，1 個錯誤（同一個），0 個失敗，3 個略過（都是本來就標記跳過的），53 個未完成，6 分 30 秒。之後的檢查：
- 沒有 `s3compat%` 資料庫；
- 5 個測試資料庫都是 63 張表；
- `s3compat_probe` 是 0；
- 上傳目錄和 `storage/app/backups` 沒有殘留；
- `/tmp/s3compat-missing-*` 又多了 1 個（失敗的測試留下的，已刪除）。

### 4.6 chiseled：**四個驗收全部 exit 0，`backup_without_key_files` 是 `true`**

- Build：暫時調整和第 6、7 輪相同（代理 CA、`git archive` 產生的 Composer 快取），沒有 commit，worktree 已刪除。沒有快取時 259 秒。
- Image：`snipeit-chiseled:round8`，ID `sha256:27554c39edd2a34c8ce91c2759de355f4925c5d97ee9adccb7d594cd09d20259`，545 MB。Env 沒有代理相關的變數。

| 腳本 | exit | 結果 |
| --- | --- | --- |
| `check_sapi` | 0 | pass |
| `check_invariants --boot` | 0 | pass |
| `regression --self-test` | 0 | `{"self_test_matches_for_unsent_marker": 0}` |
| `regression` | 0 | pass，`backup_without_key_files: true` |

`backup_without_key_files` 的細節：`key_files_present: [false, false]`，`exit: 0`，輸出是：

```
Skipping /var/www/html/storage/oauth-private.key: it does not exist.
Skipping /var/www/html/storage/oauth-public.key: it does not exist.
S3 files are not part of this backup. Use --with-remote-files to include them.
… Zipping 27 files and directories … Backup completed!
```

正常備份是 29 個檔案，少的 2 個就是這兩個金鑰。

和 `cloud-verify/round7/*.json` 比：原有的 checks 值全部相同，只多了 `backup_without_key_files: true` 和它的 `details`。其他差異只有 image 名稱和 ID、備份 zip 的大小（26521 → 26530）與檔名、mail marker、主機名稱。

每個驗收跑完後，匿名 volume 都是 0。

### 4.7 清理：**完成**

- Docker：image、volume 全刪，`docker buildx prune -af` 清掉 4.18 GB，`docker system df` 全部是 0，dockerd 已停，worktree 已刪除。
- 測試資料庫（`snipeit_test`、`_test_1..4`）已刪除，`/etc/hosts` 已還原。
- `vendor/` 保留（約 9.5 GB，下一輪跑 PHPUnit 可以直接用）。

## 5. 修改建議

### 1.（高，我們的改動）修正 `missing_include_paths_are_left_out_and_named_instead_of_failing_the_backup`

檔案：`tests/Feature/S3Compatibility/BackupRemoteOptionTest.php`

原因：見第 3 節。測試現在每次都失敗，而且就算程式壞掉，它也只會用同一個 `Undefined array key 0` 失敗，完全驗證不到修正。順便把清理放進 `finally`，失敗時才不會在 `/tmp` 留目錄。

```diff
     #[Test]
     public function missing_include_paths_are_left_out_and_named_instead_of_failing_the_backup(): void
     {
         [$existing, $root, $missing] = $this->includeWithMissingPaths();
         $before = config('backup.backup.source.files.include');
 
-        $command = $this->artisan('snipeit:backup', ['--without-remote-files' => true]);
-        foreach ($missing as $path) {
-            $command->expectsOutputToContain("Skipping {$path}: it does not exist.");
-        }
-        $command->assertExitCode(0);
-
-        $include = $this->calls()[0]['include'];
-        $this->assertSame($existing, array_slice($include, 0, count($existing)));
-        $this->assertCount(count($existing) + 1, $include, 'only the S3 manifest directory is added');
-        $this->assertSame([], array_values(array_intersect($missing, $include)));
-        $this->assertSame($before, config('backup.backup.source.files.include'), 'the configured list is put back');
-        File::deleteDirectory($root);
+        try {
+            $command = $this->artisan('snipeit:backup', ['--without-remote-files' => true]);
+            foreach ($missing as $path) {
+                $command->expectsOutputToContain("Skipping {$path}: it does not exist.");
+            }
+            // PendingCommand runs on destruct; run it now so the stub's calls can be read below.
+            $command->assertExitCode(0)->run();
+
+            $include = $this->calls()[0]['include'];
+            $this->assertSame($existing, array_slice($include, 0, count($existing)));
+            $this->assertCount(count($existing) + 1, $include, 'only the S3 manifest directory is added');
+            $this->assertSame([], array_values(array_intersect($missing, $include)));
+            $this->assertSame($before, config('backup.backup.source.files.include'), 'the configured list is put back');
+        } finally {
+            File::deleteDirectory($root);
+        }
     }
```

`missing_include_paths_are_left_out_on_an_all_local_install_too` 的 `File::deleteDirectory($root)` 也建議放進 `finally`。

另外，`includeWithMissingPaths()` 裡的 `if (@symlink(...))` 讓 symlink 建立失敗時測試照樣通過，等於少測了「斷掉的 symlink」這個正式環境的情況。這次在 Linux 上確認有建立，但比較穩的寫法是：建立失敗時 `markTestSkipped('symlinks are not available')`，或者直接斷言 `$missing` 有 2 個，不要靜默略過。

### 2.（低，說明檔）`CLOUD_TEST.md`

- Docker Hub 匿名 pull 的 `429` 這輪出現很多次，`regression` 用的 `python:3.12-slim`、`mysql:8.4` 也會遇到。建議在 build 和驗收之前，先用重試迴圈 pull 六個 image（golang、composer、ubuntu 的固定 digest，加上 `mysql:8.4`、`python:3.12-slim`、`hello-world`）。
- 容器可能重啟，MariaDB 會停掉，代理 port 也會變。建議在步驟開頭加上 `service mariadb start`，並且一律使用當下的 `$HTTPS_PROXY`。
