# 雲端測試結果：第 15 輪（rebase 到官方 develop `581d564e2c` 之後的 all-changes）

**第 15 輪通過。**

- runner 原樣執行 `bash cloud-verify/review-fixes/run.sh "$PWD" B`：exit **0**，`errors` 是 `[]`，222 個通過，唯一的失敗是預期中的 FR-9 突變版。0 略過、0 incomplete。FR-2、FR-8、FR-9、`candidate_proxy_ca_absent`、input lock 都通過，結果和第 14 輪完全相同。
- 在同一個測試 image 裡跑完整的 `tests/`：共 7086 個測試（和 `phpunit --list-tests` 的數量一致）。結果是 27 個 failure、14 個 error、3 個略過、54 個 incomplete。**每一個失敗都找到了原因，沒有任何一個是我們的改動或這次 rebase 造成的程式錯誤**：
  - 已知：缺 `intl` 的 8 個、沒有 DNS 的 14 個。
  - 測試環境造成：14 個 error 是測試 volume 裡少了 `private_uploads/imports`。另外 3 個 `ShelllessOptInTest` 失敗，是因為 chiseled image 預設 `SNIPEIT_SHELLLESS=true`。條件改正後重跑都通過。
  - 上游本來就有：`ImportAssetsTest::will_encrypt_custom_fields`，以及在 MySQL 8.4 上的 `ListLicensesToolTest::test_offset_skips_results_for_pagination`。這兩個在上游 develop `581d564e2c` 也會失敗。

有一點要先說明：`ShelllessOptInTest` 是我們自己的測試，它在 chiseled image 裡會失敗。這是測試對環境的假設造成的，不是程式錯誤，修改建議見第 5 節第 1 點。

被測的 commit 是 `cloud-test` `aa0f654b45`。其中 `all-changes` 是 `30d08be111`，是 `581d564e2c` 加上 53 個 commit。因為 clone 是 shallow，我先 `--deepen` 再確認祖先關係：`581d564e2c` 確實是祖先，`f9f3a6067c..581d564e2c` 是 181 個 commit。`composer.lock` 和上游完全相同。完整輸出見 `cloud-test-output.txt`。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核，磁碟剩約 30 GB。全新容器，沒有 `~/.cache/review-fixes`，mirror 由 runner 重建 |
| Docker | dockerd 29.9.2，用 root 啟動，帶當下的 `HTTP(S)_PROXY=$HTTPS_PROXY`。`hello-world` 成功。拉 base image 時 Docker Hub 回過幾次 429，runner 的退避重試都撐過去了 |
| candidate image | `sha256:7c233b3d43d8adb99bc2c2883bf5a32454c415db8dda1c924c83fffdc98e15aa` |
| 測試 image | `sha256:8c9f9cccf896c162933a270c7c5ed3a5739878300dd82180bc939590c6b09054`。全套測試用的就是這個 image：runner 建好時我另外 tag 成 `round15-full:test`，image ID 相同 |
| PHP | chiseled 的 `/usr/bin/php` 是 8.3.6。`php_comparison` 的 version、modules、sha256 都相同，sha256 是 `7f1ac2fe89d2…a67d7`，和第 10–14 輪相同 |
| 資料庫 | runner 用自己網路裡的 `mysql:8.4`。全套測試另外開了一個 `mysql:8.4`，每個 shard 有自己的資料庫和 `/var/lib/snipeit` volume |
| 上游對照 | 主機 PHP 8.3.6 + MariaDB 10.11，也連到同一個 mysql:8.4 容器。上游 worktree 用 `581d564e2c`。vendor 從測試 image 複製過來，因為兩邊的 lock 完全相同 |

| 階段 | 時間（UTC） |
| --- | --- |
| 讀說明、啟動 dockerd | 02:50–02:53 |
| runner | 02:53:07–03:09:40，約 16.5 分鐘 |
| 全套測試：4 個 shard 平行，加上 SyncAdapters 分開跑 | 03:02–04:04。shard 耗時分別是 2117、178（拆分後重跑）、882、1393 秒。SyncAdapters 其餘部分 386 秒，ABM 8 個檔案平行跑、最久 1232 秒 |
| 重跑、上游對照、分析 | 03:25–04:20 |
| 清理、報告 | worker 中途重啟一次，dockerd 和 MariaDB 被停掉；重新啟動 dockerd 後才做清理 |

## 2. 測試數量

### runner（`results-B.json`）

`counts` 是 passed 222、failure 1，那 1 個是預期的 FR-9 突變版。和第 14 輪相同。

| 執行 | 通過 | 失敗 |
| --- | --- | --- |
| `LdapTest` selected / 全套 | 7 / 35 | 0 / 0 |
| `S3Compatibility` selected / 全套 | 16 / 103 | 0 / 0 |
| `LdapWizardTest` selected / 全套 | 3 / 57 | 0 / 0 |
| FR-9 原版 / 突變版 | 1 / 0 | 0 / 1（預期） |

### 全套 `tests/`（chiseled 測試 image，mysql:8.4，第一次跑）

| | 數量 |
| --- | --- |
| 測試 | **7086**（Unit 加 Feature，和 `--list-tests` 相同） |
| assertions | 22014 |
| failure | 27 |
| error | 14 |
| 略過 | 3。全是程式碼本來就標記的：`ApiRateLimitTest` 2 個、`DeleteAssetsTest::test_cannot_delete_asset_that_is_checked_out` |
| incomplete | 54。全是 `markTestIncomplete`，上游也一樣（「Custom Fields tests do not work on MySQL」45 個等等） |

第 13 輪只在 chiseled 裡跑過 `tests/Unit`，所以全套沒有可以直接比較的舊數字。Unit 部分的失敗和第 13 輪相同，就是那 8 個 `intl` 測試。

## 3. 失敗和可疑項目

| # | 測試 | 數量 | 原因 | 修正條件後重跑 | 上游 develop `581d564e2c` |
| --- | --- | --- | --- | --- | --- |
| A | `Unit\CustomFieldTest` 6 個、`Unit\Importer\ImporterEncodingTest` 2 個 | 8 F | chiseled 沒有 `intl`（已知） | — | 已知 |
| B | `CompanyWebhooksTest::test_can_filter_companies_with_webhooks`、`WebhookEndpointSsrfTest::test_api_accepts_a_public_https_webhook_endpoint_from_superuser`、`Fleet\FleetLicenseTierTest` 3 個、`Fleet\FleetSettingsPageTest` 1 個、`Intune\IntuneSettingsPageTest` 3 個、`Kandji\KandjiSettingsPageTest` 1 個、`AssetTagPatternTest` 2 個、`GroupCompanyMappingTest` 2 個 | 14 F | 沒有 DNS，`ExternalUrl` 驗證失敗（已知） | 加上 `--add-host`（「已知狀況」列的 5 個主機）後：Companies 2/2、SyncAdapters 37/37 **通過** | 已知 |
| C | `Assets\Ui\ImportAssetHistoryTest` 10 個、`Livewire\ImporterTest` 3 個、`Importing\Api\GeneralImportTest::processing_another_users_import_does_not_overwrite_created_by` | 14 E | `fopen(.../storage/private_uploads/imports/...): No such file or directory`。chiseled 的 `storage/private_uploads` 是指向 `/var/lib/snipeit/data/private_uploads` 的 symlink。runner 和我的 volume 初始化只建了上層目錄，正式 init（`startup.go` 的 `dataDirs`）會建 `imports` 等子目錄 | 改用和 `startup.go` 相同的目錄清單後重跑 Importing 全目錄加上這兩個檔案，292 個裡 **291 個通過**，剩下的就是 D | 測試環境造成，和程式無關 |
| D | `Importing\Api\ImportAssetsTest::will_encrypt_custom_fields` | 1 F | 讀出的原始值和明文相同（`Failed asserting that 'B2:99:…' is not equal to 'B2:99:…'`） | 仍然失敗 | **上游也失敗**（主機 MariaDB）。我們沒有改 `tests/Feature/Importing` 和 `app/Importer` |
| E | `Mcp\ListLicensesToolTest::test_offset_skips_results_for_pagination` | 1 F | `ListLicensesTool` 只用 `licenses.created_at desc` 排序，10 筆在同一秒建立，`skip/take` 的結果在 MySQL 8.4 上不固定，兩頁會重複 | 容器（MySQL 8.4）裡重跑仍然失敗；主機 MariaDB 上分支和上游各跑 3 次都通過 | **上游在 mysql:8.4 上 3/3 失敗**。上游新加的 MCP，我們沒有改 `app/Mcp` |
| F | `Console\ShelllessOptInTest` 的 `test_shellless_is_off_by_default`、`test_scheduler_is_the_framework_one_by_default`、`test_restore_uses_a_shell_command_line_by_default` | 3 F | **我們的測試**。這 3 個測試假設 `app.shellless` 是預設值，但 chiseled image 的 Env 本來就有 `SNIPEIT_SHELLLESS=true` | 容器裡加 `-e SNIPEIT_SHELLLESS=false` 後 6/6 通過；主機一般環境 6/6 通過；主機加 `SNIPEIT_SHELLLESS=true` 就重現這 3 個失敗 | 上游沒有這個測試 |

合計：failure 8 + 14 + 1 + 1 + 3 = 27，error 14，和 junit 的數字一致。

**另一個發現（不是失敗，但很耗時間）**：上游 `SyncAdapters\AppleBusinessManager` 的測試會真的對 `api-business.apple.com` 發出請求，有些請求沒有被 `Http::fake` 擋住。在沒有網路的容器裡，每個請求都會走 `RetriesTransientHttpErrors` 的 8 次指數退避，等 0.5 秒、1 秒一直到 32 秒，所以每個測試大約要 64 秒。測試最後還是會通過，但整個目錄 64 個測試要跑 1 小時以上。

- 上游一樣：上游 develop 在沒有代理環境變數時跑 `ActivationLockEnrichmentTest`，5 個測試花了 5 分 26 秒，每個約 64 秒。
- 主機上有 `HTTPS_PROXY`，請求會從代理拿到 HTTP 回應，不是 ConnectionException，不會重試，所以 55 秒就跑完。

這次我把 SyncAdapters 拆成 ABM 每個檔案一個容器、其餘一個容器平行跑，最後全部通過：ABM 64/64，其餘只有 B 列的 12 個 DNS 失敗。

## 4. 「這次的重點」逐項回答

1. **dockerd**：用當下的 `$HTTPS_PROXY` 啟動，`hello-world` 成功。
2. **原樣執行 runner**：工具、程式碼和 Dockerfile 都沒有修改。
   - runner exit **0**，`errors` 是 **`[]`**。
   - 除了 FR-9 突變版之外 **0 失敗**；`skipped_summary` 全部是空的，所以 **0 略過**。
   - FR-2：`fr2_chiseled`、`fr2_regular` 都 exit 0，`fr2_prepare_app` 是 `marker_directory_present: false`。
   - FR-8：`fr8_valid`、`fr8_empty`、`fr8_unset` 都 exit 0；`fr8_invalid` 容器啟動失敗（exit 1），這是預期結果；`fr8_go_unit` exit 0。
   - FR-9：原版 exit 0。突變版失敗的訊息是 `Finding 9: safety backup omitted remote files.`，`fr9_mutation_red.passed = true`。
   - `candidate_proxy_ca_absent` 和 `chiseled_input_locks` 都通過。
   - 所有 probe 都和第 14 輪相同。`results-B.json` 和 debug log 裡都沒有 `docker.sock`。runner 跑完時 `git status` 只有 `results-B.json` 有變動。
3. **全套測試**：在同一個測試 image（image ID 相同）裡跑完整的 `tests/`，共 7086 個。已知的失敗（A、B）之外，其他失敗（C、D、E、F）都在第 3 節逐一分析，也到上游 develop `581d564e2c` 對照過。這次 rebase 唯一的衝突在 `AppServiceProvider` 的 shell-less scheduler 綁定，`ShelllessOptInTest` 在一般環境下 6/6 通過，表示 rebase 後綁定仍然正確。上游新增的 MCP 測試（`tests/Feature/Mcp`，778 個）只有 E 一個失敗，而且上游也失敗。
4. **清理**：
   - runner 自己移除了它建立的資源。
   - 我刪掉了全套測試用的容器、volume、網路和 tag，並執行 `docker image prune -af`、`docker buildx prune -af`、`docker system prune -af --volumes`，之後 `docker system df` 全部是 0。dockerd 已停止。
   - `/tmp/dev` worktree、上游和分支的測試資料庫，以及工作目錄裡暫時放的 `vendor/`、`.env`、`.env.testing` 都已刪除。MariaDB 已停止。
   - `~/.cache/review-fixes/mirrors` 是工具設計上要重複使用的快取，所以保留。
   - 在主機上跑測試時，有測試刪掉了 `public/uploads/**` 和 `storage/private_uploads/**` 裡被 git 追蹤的 `.gitignore`、`.gitkeep` 等檔案（`git status` 出現 37 個 D）。我用 `git checkout` 還原了，沒有 commit 進去。這可能和上游有些測試會清理上傳目錄有關，第 5 節第 5 點有說明。

## 5. 修改建議（依重要性排序）

1. **`tests/Feature/Console/ShelllessOptInTest.php`（我們的改動）**：「預設是關閉」的 3 個測試直接讀目前的設定，在 chiseled image（Env 有 `SNIPEIT_SHELLLESS=true`）或任何設了這個變數的環境裡都會失敗。建議改成不依賴執行環境：在每個測試開頭先固定設定，`config(['app.shellless' => false]);`，或者在 `setUp()` 裡做。「預設值是 false」這件事，改成檢查 `config/app.php` 的原始碼裡 `env('SNIPEIT_SHELLLESS', false)` 的預設參數，或用 `putenv('SNIPEIT_SHELLLESS')` 清掉變數後重新載入設定。另一個選擇是在 `phpunit.xml` 加 `<env name="SNIPEIT_SHELLLESS" value="false" force="true"/>`，但這樣就會遮住 chiseled 的真實設定，所以比較建議前一種做法。
2. **測試工具 `cloud-verify/review-fixes/runner.py` 的 volume 初始化（`init`）**：目前只建 `data`、`data/private_uploads`、`data/uploads` 等上層目錄，和正式 init（`docker/snipeit-runtime/internal/startup/startup.go` 的 `dataDirs`）不一致。runner 目前跑的 3 組測試剛好沒用到 `imports`，但以後要在 chiseled 裡跑全套，或加入 import 相關的測試時，就會出現第 3 節 C 列的 14 個假失敗。建議直接用和 `dataDirs` 相同的清單，最好由同一份資料產生。
3. **說明檔（CLOUD_TEST.md）**：之後如果還要在 chiseled 裡跑全套，建議寫明：
   - volume 要照 `dataDirs` 初始化（同第 2 點）。
   - 要用 `-e SNIPEIT_SHELLLESS=false` 跑 `ShelllessOptInTest`，或等第 1 點修好。
   - SyncAdapters 在沒有網路的容器裡會因為上游 ABM 測試漏掉的真實請求而跑 1 小時以上，要拆開平行跑，或標記成已知的慢測試。
   - 「已知狀況」要補上 `ListLicensesToolTest`（MySQL 8.4）和 `will_encrypt_custom_fields`（上游本來就失敗）。
4. **上游 `app/Mcp/Tools/ListLicensesTool.php`（上游的問題）**：`orderBy('licenses.created_at', 'desc')` 之後應該再加一個不會重複的排序欄位，例如 `->orderBy('licenses.id', 'desc')`。否則分頁在 MySQL 8.x 上會重複或漏掉資料，這不只是測試的問題，實際使用也會受影響。其他 `List*Tool` 可能也有同樣的寫法，可以一起檢查。這可以考慮對上游發 PR。
5. **上游 `tests/Feature/SyncAdapters/AppleBusinessManager/*`（上游的問題）**：測試會漏出真實的 HTTPS 請求到 `api-business.apple.com`。建議在這些測試（或 `TestCase`）裡加上 `Http::preventStrayRequests()`，並把漏掉的端點 fake 起來。這樣測試不會依賴網路，也不會在 CI 有網路時真的打到 Apple。另外，主機上跑完測試後被 git 追蹤的上傳目錄檔案被刪掉了（見第 4 節第 4 點），這次沒有時間找出是哪個測試做的，建議之後確認一下。
6. **`ImportAssetsTest::will_encrypt_custom_fields`（上游的問題）**：上游 develop 本身就失敗，原始值沒有被加密。這可能是上游加密欄位匯入的回歸，也可能是測試裡 `firstOrNew` 加上 `field_encrypted` 改變之後，欄位的 cast 沒有更新。不是我們的改動造成的，可以向上游回報。
