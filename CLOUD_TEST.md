# 雲端測試任務

`cloud-test` 分支 = `all-changes`（我們的改動，rebase 在上游 `grokability/snipe-it` 的 develop 上）+ 這個說明檔。每次有新改動都會推到這裡，請你測試並提出修改建議。

**不要修改程式碼。** 唯一允許的 push 是最後把結果檔推回 `cloud-test`（見「回報」）。

## 這次的重點

- 基準：上游 develop `f9f3a6067c`；程式碼和 `all-changes` `e9ff762908` 相同。
- 新改動（第 2 輪建議 1）：`e9ff762908` 把 `ProtectsRealUploadDirectories` 的鎖拆成 `lockRealUploadDirectories()`。`EulaDownloadTest` 和 `AcceptanceAttachmentTest`（後者第 2 輪報告沒提到，但一樣會在真實的 `eula-pdfs` 寫暫存 PDF）在寫檔前先拿鎖，`tearDown` 刪檔後放鎖。
- 要確認：
  1. **用平行模式只跑 `tests/Feature/S3Compatibility` 至少 10 次，每次都加 `--display-skipped`**：應該都是 0 失敗、0 略過。列出每次的結果。
  2. 平行全套一次：S3 測試 0 略過，`EulaDownloadTest` 和 `MoveUploadsToNewDiskTest` 沒有失敗，`storage/private_uploads` 和 `public/uploads` 沒有留下檔案。
  3. 加鎖會讓這幾個測試排隊，請比較 S3 目錄平行跑的耗時和上次（約 1.5–2 分鐘）。
- 第 2 輪的建議 2（破壞性測試分組或隔離目錄）和 3（`ImporterMutexTest`）這次沒有做。如果第 1 項還是不穩定，請說明是哪個測試在競爭，並重新評估建議 2。
- 之前的結果在這個分支的歷史裡：第 1 輪 `a3611109df`、第 2 輪 `ed51bd3f4f`（`CLOUD_TEST_RESULT.md`）。

## 步驟

先做這三件事，可以省掉上次浪費的約 15 分鐘：

- 讀 `.github/workflows/tests-mysql.yml`，照它的初始化步驟做（`key:generate`、`passport:install` 等），**金鑰要在開跑前就產生**。
- 用 `curl -s -o /dev/null -w '%{http_code}\n' -L https://api.github.com/repos/laravel/framework/zipball` 測能不能下載 zip，回 200 才算可以（經過 proxy 時 `curl -sI` 會誤報 200 Connection Established）。不能的話直接用 `composer install --prefer-source`，並提早處理只有 dist 的套件（上次是 `phpstan/phpstan`）。不要修改 `composer.lock`。
- 跑測試一律加 `--display-skipped`，跑完先看略過的原因。

接著：

1. 環境：PHP 8.3，擴充套件 `pdo_mysql pdo_sqlite zip gd bcmath ldap exif intl mbstring xml curl`，Composer 2，MariaDB 10.11。
2. `cp .env.testing.example .env.testing`，填入資料庫設定（使用者要有 CREATE DATABASE 權限，平行模式會建 `<db>_test_N`）。確認有 `IMPORT_MEMORY_LIMIT=2G`、`LDAP_MEM_LIM=2G`。`cp .env.testing .env`。
3. 平行全套：`php -d memory_limit=2G artisan test --parallel --display-skipped --colors=never 2>&1 | tee /tmp/branch.txt`
4. 有失敗或可疑的略過時，到上游 develop 對照（`git fetch https://github.com/grokability/snipe-it.git develop` 後 `git worktree add /tmp/dev FETCH_HEAD`），只需要重跑相關的測試檔；確定是新的問題才跑上游全套。我們新增的測試上游沒有，直接分析即可。
   平行競爭只跑一次全套不一定抓得到，有改到 S3 測試或上傳目錄時，另外用平行模式重複跑 `tests/Feature/S3Compatibility`（每次不到 2 分鐘）。
5. 結束後刪掉 `/tmp/dev` 和測試資料庫。

## 已知狀況

- `Tests\Feature\Livewire\ImporterMutexTest::test_locks_are_scoped_per_file_so_a_second_file_can_still_start`：平行模式下偶發失敗（共用 file cache + 各 process 的 Import ID 重複），上游也有同樣風險。乾淨 cache 單獨跑會過。第 2 輪通過。
- 程式碼本來就標記跳過的 3 個（上游也有）：`ApiRateLimitTest` 兩個、`DeleteAssetsTest::test_cannot_delete_asset_that_is_checked_out`。
- 本機（非 UTC 時區、不同 intl 版本）才會失敗的 `CustomFieldTest` 和 `ExtraFieldMappingTest`，在 UTC 的雲端環境應該會過。

## 回報

把結果寫成 `CLOUD_TEST_RESULT.md`，完整輸出存成 `cloud-test-output.txt`，只 commit 這兩個檔案，push 到 `cloud-test`。推不到的話推到你自己的分支，並在對話裡說名稱。對話裡也貼一份摘要。

內容：

1. 環境：PHP、資料庫版本、CPU 核心數、平行或單程序、各階段耗時（安裝、每次全套、分析）。
2. 測試數量：總數、通過、失敗、錯誤、略過、未完成，以及和上次結果的差異。
3. 每個失敗或可疑略過：名稱、錯誤摘要、上游 develop 是否也有。
4. 「這次的重點」逐項回答。
5. **修改建議**：你認為該改的地方（程式碼、測試、這份說明檔），寫出檔案、原因和建議的改法（可以附 diff），但不要 commit 到程式碼。依重要性排序，並標明是我們的改動造成的，還是上游本來就有的問題。
