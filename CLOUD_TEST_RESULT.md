# 雲端測試結果（第 2 輪）

分支 `cloud-test` `4399781`（= `all-changes` `50443fc6bd` + 說明檔），基準為上游 develop `f9f3a6067c`。完整輸出見 `cloud-test-output.txt`。

## 1. 環境與耗時

| 項目 | 值 |
| --- | --- |
| PHP | 8.3.6 (CLI, NTS)，要求的擴充套件都有 |
| 資料庫 | MariaDB 10.11.14 |
| CPU | 4 核心（Intel Xeon @ 2.10GHz） |
| 模式 | 平行模式，ParaTest 7.8.5 / PHPUnit 11.5.55，4 個 process |
| `.env.testing` | 照範本，`APP_TIMEZONE='UTC'`、`IMPORT_MEMORY_LIMIT=2G`、`LDAP_MEM_LIM=2G` |

| 階段 | 耗時 |
| --- | --- |
| 安裝與設定（啟動 MariaDB、`composer install`、`key:generate`、`migrate`、`passport:install`、清 file cache） | 約 1 分鐘（同一個容器，`vendor/` 和 `composer.lock` 都沒變，沒有東西要裝） |
| 平行全套（1 次） | 8 分 18 秒 |
| 分析（含 S3 目錄平行跑 5 次，每次約 1.5–2 分鐘） | 約 15 分鐘 |
| 合計 | 約 25 分鐘 |

備註：api.github.com 的 zip 仍然是 403。這次 `vendor/` 已經裝好，所以沒有用到 `--prefer-source` 的補救步驟。

## 2. 測試數量

| | 總數 | 通過 | 失敗 | 錯誤 | 略過 | 未完成 |
| --- | --- | --- | --- | --- | --- | --- |
| 這次（`4399781`） | 6061 | 6004 | 1 | 0 | **3** | 53 |
| 上次（`a361110`） | 6061 | 5969 | 1 | 0 | 38 | 53 |
| 上游 develop（上次測的） | 5916 | 5860 | 0 | 0 | 3 | 53 |

差異：
- 略過從 38 降到 3，35 個 S3 測試這次都有執行。
- 剩下 3 個略過和上游一樣，都是程式碼裡本來就標記要跳過的：
  - `ApiRateLimitTest::test_rate_limit_decreases_remaining`、`ApiRateLimitTest::test_rate_limit_decreases_remaining_over_sixty`："This test is flappy…"
  - `DeleteAssetsTest::test_cannot_delete_asset_that_is_checked_out`："This behavior is not functioning yet."
- 失敗的測試換了一個：上次是 `ImporterMutexTest`（這次通過），這次是 `EulaDownloadTest`（見下面）。

## 3. 失敗與可疑的略過

### `Tests\Feature\S3Compatibility\EulaDownloadTest::inline_request_on_local_disk_still_serves_the_file_inline` — **我們的改動造成**

```
Expected response status code [200] but received 302.
Failed asserting that 302 is identical to 200.
tests/Feature/S3Compatibility/EulaDownloadTest.php:136
```

- 上游 develop：沒有這個測試（`850b501`、`c4f56a0` 新增的），所以無法對照。
- 單獨跑（單一 process）3 次都通過。
- **原因：平行模式下的檔案競爭。** `EulaDownloadTest` 有兩個測試（第 112、131 行）把 `accepted-<8 碼 hex>.pdf` 寫進**真實的** `storage/private_uploads/eula-pdfs/`，結束時在 `tearDown` 刪掉。`MoveUploadsToNewDiskTest`、`RestoreToRemoteDiskTest`、`StagingAssumptionsTest` 則會搬移或清空這些目錄。這三個測試用 `ProtectsRealUploadDirectories` 的 flock 互相排隊，但 `EulaDownloadTest` 沒有拿這個鎖。
  - S3 測試在別的 process 清掉了 PDF → 下載路由找不到檔案 → 302。
  - 反過來也會發生：S3 測試列出檔案後，`EulaDownloadTest` 把檔案刪掉 → 搬移命令出錯。
- **重現：** 只用平行模式跑 `tests/Feature/S3Compatibility` 5 次（輸出檔第 3 段）：

  | 次 | 結果 |
  | --- | --- |
  | 1 | 87 個全過 |
  | 2 | 1 個略過 |
  | 3 | 1 個略過 |
  | 4 | **錯誤**：`MoveUploadsToNewDiskTest::files_land_on_the_keys_the_application_reads` — `ErrorException: filesize(): stat failed for storage/private_uploads/eula-pdfs/accepted-1987503d.pdf`（`app/Console/Commands/MoveUploadsToNewDisk.php:193`）。這個檔名就是 `EulaDownloadTest` 產生的格式。 |
  | 5 | **失敗**：和全套一樣，`EulaDownloadTest` 拿到 302 |

  第 2、3 次的略過：這 5 次沒加 `--display-skipped`，所以看不到訊息。依時機判斷，應該是保護機制剛好看到 `EulaDownloadTest` 寫入的檔案而跳過（推測，未驗證）。
- 為什麼上次沒出現：上次那 35 個 S3 測試全被跳過，沒有東西去碰這個目錄。`50443fc` 修好了略過，所以這個原本就存在的競爭露出來了。

### `ImporterMutexTest::test_locks_are_scoped_per_file_so_a_second_file_can_still_start`

這次通過。上游的已知問題，見修改建議 3。

## 4. 「這次的重點」逐項回答

| 項目 | 結果 |
| --- | --- |
| 平行全套後，三個 S3 測試檔 0 個跳過 | **是。** 全套只有 3 個略過，都不是 S3 測試，而是程式碼本來就標記跳過的測試。 |
| `eula-pdfs` 裡沒有留下檔案 | **是。** 跑完只有 `.gitignore`。`git status --ignored public/uploads storage/private_uploads` 沒有輸出。 |
| 還有跳過的話，列出訊息和造成的檔案 | 全套沒有。不過只跑 S3 目錄時，5 次裡有 2 次出現 1 個略過，原因很可能是上面的競爭（`EulaDownloadTest` 的暫存 PDF）。 |

`50443fc` 的修正有效。但它讓 S3 測試真正開始執行後，暴露出我們自己測試之間的平行競爭，所以目前全套**還不穩定**。

## 5. 修改建議（依重要性排序）

### 1.（高，我們的改動）讓 `EulaDownloadTest` 和 S3 搬移／還原測試共用同一把鎖

檔案：`tests/Support/S3Compatibility/ProtectsRealUploadDirectories.php`、`tests/Feature/S3Compatibility/EulaDownloadTest.php`

原因：`EulaDownloadTest` 在真實的上傳目錄裡寫入和刪除檔案時沒有拿鎖，所以會和會清空這些目錄的測試互相干擾（上面已重現兩種方向）。

建議改法：把「拿鎖」從 `protectRealUploadDirectories()` 拆出來，讓只寫一個暫存檔的測試也能排隊，而且不必做「有殘留就跳過」的檢查。

```diff
--- a/tests/Support/S3Compatibility/ProtectsRealUploadDirectories.php
+++ b/tests/Support/S3Compatibility/ProtectsRealUploadDirectories.php
@@
     protected function protectRealUploadDirectories(): void
     {
-        $lock = fopen(sys_get_temp_dir().'/snipeit-upload-directories.lock', 'c');
-        if ($lock !== false) {
-            flock($lock, LOCK_EX);
-            $this->uploadDirectoriesLock = $lock;
-        }
+        $this->lockRealUploadDirectories();
 
         $leftover = array_values(array_filter(
@@
+    /**
+     * Takes only the cross-process lock, for tests that put a temporary file into the real upload
+     * directories and must not race the tests that prune or move them.
+     */
+    protected function lockRealUploadDirectories(): void
+    {
+        if ($this->uploadDirectoriesLock !== null) {
+            return;
+        }
+        $lock = fopen(sys_get_temp_dir().'/snipeit-upload-directories.lock', 'c');
+        if ($lock !== false) {
+            flock($lock, LOCK_EX);
+            $this->uploadDirectoriesLock = $lock;
+        }
+    }
```

```diff
--- a/tests/Feature/S3Compatibility/EulaDownloadTest.php
+++ b/tests/Feature/S3Compatibility/EulaDownloadTest.php
@@
 class EulaDownloadTest extends TestCase
 {
+    use \Tests\Support\S3Compatibility\ProtectsRealUploadDirectories;
+
     private string $localFile = '';
 
     protected function tearDown(): void
     {
         if ($this->localFile !== '' && file_exists($this->localFile)) {
             unlink($this->localFile);
         }
+        $this->releaseRealUploadDirectories();
 
         parent::tearDown();
     }
@@ (第 112 行與第 131 行的 Storage::disk('local')->put(...) 之前各加一行)
+        $this->lockRealUploadDirectories();
         Storage::disk('local')->put($key, ...);
```

驗證方式：用平行模式跑 `tests/Feature/S3Compatibility` 至少 5–10 次，應該都是 0 失敗、0 略過。

另一個做法（更乾淨但改動較大）：在這兩個測試裡把 `filesystems.disks.local.root` 和 `app.private_uploads` 指到每個 process 自己的暫存目錄（例如 `storage/framework/testing/eula-<TEST_TOKEN>`）。這樣完全不碰真實目錄，也不用鎖。要注意第 114 行的路徑斷言也要跟著改。

### 2.（中，我們的改動，範圍較大）會清空真實上傳目錄的 S3 測試，在平行模式下本來就有風險

原因：`tests/TestCase.php` 在平行模式下只把 `public` 磁碟換成假的，預設磁碟仍是真的（註解說 import 流程需要）。所以任何上游或我們的測試，只要在平行模式下寫入 `storage/private_uploads`，都可能和這三個 S3 測試互相干擾。建議 1 只處理了已知的 `EulaDownloadTest`。

建議改法（擇一）：
- 把三個破壞性的 S3 測試檔標成 `#[Group('destructive-uploads')]`。平行跑全套時用 `--exclude-group destructive-uploads` 排除，再用單一 process 另外跑一次這個 group。CI workflow 也要跟著改。
- 或者讓 `ProtectsRealUploadDirectories` 在平行模式下把 `app.private_uploads`、`public` 根目錄整個指到每個 process 自己的暫存副本，命令只在副本上操作。

### 3.（低，上游本來就有）`ImporterMutexTest` 在平行模式下偶發失敗

檔案：`tests/TestCase.php`（上游檔案，我們沒有改過）

原因：Importer 的鎖存在共用的 file cache（`import:{id}:running`），各 process 的 Import ID 會重複。

建議改法：在 `TestCase::setUp()` 的平行模式分支，讓 file cache 依 process 分開存放：

```diff
         if ($this->isRunningInParallel()) {
             Storage::fake('public');
+            // Importer/SyncAdapter locks live in the file cache and are keyed by DB id, which repeats
+            // across per-worker databases; give each worker its own cache directory.
+            config(['cache.stores.file.path' => storage_path('framework/cache/data-test-'.env('TEST_TOKEN'))]);
         } else {
```

這個改法未經驗證：如果 `Cache::store('file')` 在 setUp 之前已經被解析過，還要再呼叫 `Cache::forgetDriver('file')`。這是上游的問題，可以考慮回饋給上游，不一定要放在我們的分支。

### 4.（低）`CLOUD_TEST.md` 說明檔

- `curl -sI https://api.github.com/...` 經過 proxy 時，只會回 `HTTP/1.1 200 Connection Established`，看起來像是可以下載。實際上是 403。建議改成：
  `curl -s -o /dev/null -w '%{http_code}\n' -L https://api.github.com/repos/laravel/framework/zipball`（200 才代表可以下載）。
- 建議加一個針對性的檢查：用平行模式跑 `tests/Feature/S3Compatibility` 5 次以上。這類競爭只跑一次全套不一定抓得到，跑這個目錄每次不到 2 分鐘。
- 「已知狀況」可以補上：`EulaDownloadTest` 和 S3 搬移／還原測試在平行模式下的競爭（直到建議 1 合併為止）。
- 步驟 4 的「上游對照」，對我們新增的測試沒有意義（上游沒有這些測試），可以註明「新測試直接分析即可」。
