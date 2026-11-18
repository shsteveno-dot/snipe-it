# 雲端測試結果：第 17 輪（確認 `ShelllessSchedulerTest` 的隔離修正）

**第 17 輪通過。**

- **第 2 步**：原樣執行 `bash cloud-verify/review-fixes/run.sh "$PWD" B`。runner exit **0**，`errors` 是 `[]`。222 個通過，唯一的失敗是預期的 FR-9 突變版。0 略過、0 incomplete。FR-2、FR-8、FR-9、`candidate_proxy_ca_absent`、input lock 都通過，結果和第 14–16 輪相同。
- **第 3 步**：全套 `tests/` 共 7086 個（和第 16 輪相同），結果是 10 個 failure、**0 個 error**、3 個略過、54 個 incomplete。
  - 第 16 輪 `RestoreToRemoteDiskTest` 的 **18 個 error 消失了**。shard0 和第 16 輪一樣，`ShelllessSchedulerTest` 排在 `RestoreToRemoteDiskTest` 前面，這次 31/31 通過。
  - 順序驗證：`ShelllessSchedulerTest` → `RestoreToRemoteDiskTest` 39/39 通過。再加上 `ShelllessOptInTest` 的三個檔案順序 45/45 通過。
  - **反證**：同樣的順序，把修正前的測試檔（`4525efb^`）唯讀掛進容器取代 image 裡的檔案，重現 18 個 `posix_spawn` error。所以這個順序驗證確實抓得到這個問題，修正確實有效。
  - 10 個 failure 都是已知的：缺 `intl` 的 8 個，加上上游的 `will_encrypt_custom_fields` 和 `ListLicensesToolTest`。DNS 的 14 個用 `--add-host` 讓它們通過。

沒有未解釋的失敗。被測的 commit 是 `cloud-test` `5f701047c4`（merge commit，包含 `all-changes` `4525efb404`）。工具、程式碼和 Dockerfile 都沒有修改。完整輸出見 `cloud-test-output.txt`。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核，15 GB RAM，磁碟剩約 30 GB。`~/.cache/review-fixes/mirrors` 已經存在 |
| Docker | dockerd 29.10.0，用 root 啟動，帶當下的 `HTTP(S)_PROXY=$HTTPS_PROXY`。`hello-world` 成功，沒有遇到 Docker Hub 429 |
| runner（`results-B.json`） | candidate `sha256:ce2171cc427d…`、測試 image `sha256:50b7b81319fa…` |
| 全套測試用的 image | runner 這次建的測試 image（建好時另外 tag 成 `round17-full:test`，所以 runner 結束時只刪掉它自己的 tag）。和 `results-B.json` 的 `test_image_id` 是同一個 image。確認過 image 裡的 `ShelllessSchedulerTest.php` 是新版（`setUp()` 記錄原狀態，`tearDown()` 還原） |
| PHP | chiseled `/usr/bin/php` 8.3.6。sha256 `7f1ac2fe89d2…a67d7`，和第 10–16 輪相同。`php -v`、`php -m`、sha256 都相同。image 的 Env 有 `SNIPEIT_SHELLLESS=true` |
| 資料庫 | runner 用自己的 `mysql:8.4`。全套測試另外開一個 `mysql:8.4`，每個 shard 有自己的資料庫和 `/var/lib/snipeit` volume |

**背景時限**：runner 和全套測試都用 2 小時的背景時限（`timeout 7200000`），這次都沒有被中斷。

| 階段 | 時間（UTC） |
| --- | --- |
| 讀說明、啟動 dockerd | 01:35–01:37 |
| runner | 01:37:59–約 01:59（build cache 是冷的，約 21 分鐘） |
| 全套測試：13 個容器平行跑（測試 image 一建好就開始，和 runner 後半段同時跑） | 01:48:34–02:36:48。shard 耗時分別是 2350、2716、2025、1681 秒；syncrest 1758 秒；ABM 213–1382 秒 |
| 順序驗證、反證（另外的 DB 和 volume） | 01:52–01:56 |
| 分析、清理、報告 | 02:37– |

## 2. 測試數量

### runner（`results-B.json`）

`counts` 是 passed 222、failure 1（預期的 FR-9 突變版），和第 14–16 輪相同。

| 執行 | 通過 | 失敗 |
| --- | --- | --- |
| `LdapTest` selected / 全套 | 7 / 35 | 0 / 0 |
| `S3Compatibility` selected / 全套 | 16 / 103 | 0 / 0 |
| `LdapWizardTest` selected / 全套 | 3 / 57 | 0 / 0 |
| FR-9 原版 / 突變版 | 1 / 0 | 0 / 1（預期） |

### 全套 `tests/`

分成 4 個 shard（SyncAdapters 以外的部分，依檔案大小平均分配，shard 內依路徑排序）、syncrest（SyncAdapters 去掉 ABM）和 ABM 8 個檔案，共 13 個容器平行跑。方式和第 16 輪相同。

| | 第 17 輪 | 第 16 輪 |
| --- | --- | --- |
| 測試 | **7086** | 7086 |
| assertions | 22087 | 22023 |
| failure | 10 | 10 |
| error | **0** | 18 |
| 略過 | 3（程式碼本來就標記的：`ApiRateLimitTest` 2、`DeleteAssetsTest` 1） | 3 |
| incomplete | 54（`markTestIncomplete`，上游也一樣） | 54 |

JUnit 的 `skipped` 是 57，這是 3 個略過加上 54 個 incomplete。assertions 多了 64 個，是因為 `RestoreToRemoteDiskTest` 這次有跑完（第 16 輪的 error 都在中途結束）。

| shard | 結果 |
| --- | --- |
| shard0（含 `ShelllessSchedulerTest` → `RestoreToRemoteDiskTest`） | OK，1596 個，2 略過，8 incomplete |
| shard1 | 1761 個，8 F（intl），1 略過，24 incomplete |
| shard2 | 1619 個，2 F（上游），6 incomplete |
| shard3 | OK，1560 個，16 incomplete |
| syncrest | OK，486 個 |
| ABM 0–7 | 全部 OK（5–14 個） |

## 3. 失敗和可疑項目

| # | 測試 | 數量 | 原因 | 上游 |
| --- | --- | --- | --- | --- |
| A | `Unit\CustomFieldTest` 6 個（chinese、japanese、korean、non_latin_euro、turkish、arabic）、`Unit\Importer\ImporterEncodingTest` 2 個 | 8 F | chiseled 沒有 `intl`（已知） | 已知的環境差異 |
| B | `Importing\Api\ImportAssetsTest::will_encrypt_custom_fields` | 1 F | `Failed asserting that '25:A5:2D:50:F2:5B' is not equal to '25:A5:2D:50:F2:5B'`，和第 15、16 輪相同 | 「已知狀況」列為上游問題 |
| C | `Mcp\ListLicensesToolTest::test_offset_skips_results_for_pagination` | 1 F | `Failed asserting that an array is empty.`，MySQL 8.4 上的排序不固定 | 「已知狀況」列為上游問題 |
| D | DNS 的 14 個 `ExternalUrl` 測試 | 0 | 加了 `--add-host` 後全部通過：`CompanyWebhooksTest` 1、`WebhookEndpointSsrfTest` 32、Intune 5、Kandji 2、`AssetTagPatternTest` 10、`FleetLicenseTierTest` 4、`FleetSettingsPageTest` 7、`GroupCompanyMappingTest` 9，全部 0 失敗 | — |
| E | 第 16 輪的 18 個 `RestoreToRemoteDiskTest` error | **0** | 修正有效，見第 4 節 | — |

合計：failure 8 + 1 + 1 = 10，error 0，和 junit 的數字一致。略過的 3 個是程式碼本來就標記的，沒有可疑的略過。54 個 incomplete 大多是 `Custom Fields tests do not work on MySQL`，和第 15、16 輪相同。

## 4. 「這次的重點」逐項回答

1. **dockerd**：用當下的 `$HTTPS_PROXY` 啟動，`hello-world` 成功。runner 和全套測試都用 2 小時的背景時限，都沒有被中斷。
2. **原樣執行 runner**：工具、程式碼和 Dockerfile 都沒有修改。結果和第 16 輪的要求一致：
   - exit **0**，`errors` 是 **`[]`**。
   - 除了 FR-9 突變版之外 **0 失敗**；`skipped_summary` 全部是空的，所以 **0 略過**。
   - FR-2：`fr2_chiseled`、`fr2_regular` exit 0，`fr2_prepare_app` 是 `marker_directory_present: false`。
   - FR-8：valid、empty、unset 都 exit 0；invalid 容器啟動失敗（exit 1），符合預期；`fr8_go_unit` exit 0。
   - FR-9：原版 exit 0。突變版失敗，訊息是 `Finding 9: safety backup omitted remote files.`，`fr9_mutation_red.passed = true`。
   - `candidate_proxy_ca_absent`、`chiseled_input_locks` 都通過。
   - `results-B.json` 和我的全套測試指令裡都沒有 `docker.sock`。runner 跑完後 `git status` 只有 `results-B.json` 有變動。
3. **全套測試**：
   - **`RestoreToRemoteDiskTest` 的 18 個 error 消失了**。shard0 的檔案順序和第 16 輪一樣，`Console/ShelllessSchedulerTest`（8 個通過）排在 `S3Compatibility/RestoreToRemoteDiskTest` 前面，在同一個 phpunit process 裡跑，`RestoreToRemoteDiskTest` 31/31 通過。
   - **順序驗證**（同一個 image，每次都用新的 `mysql:8.4` 資料庫和 volume）：

     | 檔案順序 | 結果 |
     | --- | --- |
     | `ShelllessSchedulerTest` → `RestoreToRemoteDiskTest` | **OK（39 個測試，164 assertions）** |
     | `ShelllessSchedulerTest` → `ShelllessOptInTest` → `RestoreToRemoteDiskTest` | OK（45 個測試） |
     | 反證：同樣兩個檔案，但把修正前的 `ShelllessSchedulerTest.php`（`git show 4525efb^:…`）唯讀掛進容器 | **18 個 error**（`proc_open(): posix_spawn() failed`），和第 16 輪完全一樣 |

     反證只是在容器裡掛了一個測試檔，checkout 和 image 都沒有修改。
   - 只剩已知的失敗：缺 `intl` 的 8 個，以及上游的 `will_encrypt_custom_fields` 和 `ListLicensesToolTest`。沒有其他失敗，所以不需要到官方 master 對照。
4. **清理**：
   - 刪掉全套測試、順序驗證和反證的容器、volume、網路和資料庫容器，以及 `round17-full:test` 這個 tag。
   - 執行了 `docker image prune -af`、`docker buildx prune -af`、`docker system prune -af --volumes`，之後 `docker system df` 全部是 0，沒有留下容器、volume 或自訂網路。
   - dockerd 已停止。`/tmp/review-*` 沒有殘留。
   - `~/.cache/review-fixes/mirrors` 是工具設計上要重複使用的快取，所以保留。

## 5. 修改建議（依重要性排序）

這次沒有需要修的程式錯誤。以下都是測試工具和流程上的建議。

1. **測試工具 `cloud-verify/review-fixes/runner.py`（我們的工具，建議，同第 16 輪第 2 點）**：把這次的順序驗證放進 runner，例如加一個固定順序的 phpunit 執行（`tests/Feature/Console/ShelllessSchedulerTest.php`、`ShelllessOptInTest.php`、`tests/Feature/S3Compatibility/RestoreToRemoteDiskTest.php`），預期 0 失敗。這次的反證證明這個順序抓得到第 16 輪的問題。runner 現在只跑 `S3Compatibility` 目錄，所以如果以後又有測試在 chiseled 裡改壞 `SNIPEIT_SHELLLESS`，runner 也抓不到。
2. **全套測試腳本（流程，同第 16 輪第 3 點）**：這次的 `prep.py`、`run-full.sh`、`run-order.sh` 是照第 16 輪的說明重寫的，放在 scratchpad，沒有 commit。建議放進 `cloud-verify/`，每輪結果才能直接比較。另外有兩點：
   - 全套最慢的不是 ABM，而是跑 migration 的測試類別：`CustomFieldValidationTest` 983 秒、`CustomFieldDefaultsTest` 840 秒、`CustomFieldValuesTest` 602 秒。5 個 shard 同時對同一個 MySQL 做 `ALTER TABLE` 時，DB 的 CPU 到 250%，test process 只有 1–2%。測試用的 MySQL 可以加 `--innodb-flush-log-at-trx-commit=2 --skip-log-bin`，或把資料目錄放在 tmpfs，應該能明顯縮短 shard0、shard1 的時間（約 40–45 分鐘）。這只影響測試用的資料庫，不影響被測的 image。
   - 在 runner 的測試 image 建好時，另外 tag 一份給全套測試用，runner 結束時就只刪掉它自己的 tag，全套測試可以和 runner 後半段同時跑。從這個 image 啟動的容器會繼承 `review-fixes.run` label，所以全套測試還在跑的時候不能重跑 runner（同第 16 輪的說明）。
3. **說明檔（CLOUD_TEST.md）**：「已知狀況」不需要再寫 `RestoreToRemoteDiskTest` 的順序問題，已經修好。可以補一句：phpunit JUnit 的 `skipped` 包含 incomplete（3 + 54 = 57），比較數字時要分開看。
4. **上游問題（同第 15、16 輪）**：`ListLicensesTool` 應該再加 `->orderBy('licenses.id', 'desc')` 作為第二排序欄位；`will_encrypt_custom_fields` 在上游本來就失敗。
