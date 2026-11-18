# 雲端測試結果：第 16 輪（rebase 到官方 master `9f32b39aea` 之後的 all-changes）

**第 16 輪通過**，但有一個新的測試隔離問題要修（見第 3 節 F、第 5 節第 1 點）。

- **第 2 步**：原樣執行 `bash cloud-verify/review-fixes/run.sh "$PWD" B`。runner exit **0**，`errors` 是 `[]`。222 個通過，唯一的失敗是預期的 FR-9 突變版。0 略過、0 incomplete。FR-2、FR-8、FR-9、`candidate_proxy_ca_absent`、input lock 都通過，結果和第 14、15 輪相同。
- **第 3 步**：全套 `tests/` 共 7086 個（和第 15 輪相同），結果是 10 個 failure、18 個 error、3 個略過、54 個 incomplete。
  - 第 15 輪的兩個問題確認已修好：`ShelllessOptInTest` 6/6 通過；volume 少目錄造成的 14 個 error 消失了，`ImportAssetHistoryTest`、`ImporterTest`、`GeneralImportTest` 全部通過。
  - 10 個 failure 都是已知的：缺 `intl` 的 8 個，加上上游本來就有的 2 個（`will_encrypt_custom_fields`、`ListLicensesToolTest`）。
  - DNS 的 14 個：跑之前加了 `--add-host`，全部通過。
  - **18 個 error 是新出現的**，全在 `S3Compatibility\RestoreToRemoteDiskTest`。原因已經確認：我們自己的 `ShelllessSchedulerTest::tearDown()` 會無條件清掉 `SNIPEIT_SHELLLESS`。在 chiseled image 裡，同一個 process 之後跑的測試因此變成 shellless 關閉，restore 改走 `/bin/sh`，而 image 裡沒有 `/bin/sh`。這不是程式錯誤。單獨跑 31/31 通過；接在 `ShelllessOptInTest` 後面跑也通過；接在 `ShelllessSchedulerTest` 後面跑就重現 18 個 error。

所以沒有未解釋的失敗，也沒有程式錯誤，但第 5 節第 1 點應該修。

被測的 commit 是 `cloud-test` `f286a9d352`，它是 merge commit，包含 `all-changes` `4c1f2c64f8`、`97e9f47944` 和官方 master `9f32b39aea`。工具、程式碼和 Dockerfile 都沒有修改。完整輸出見 `cloud-test-output.txt`。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核，15 GB RAM，磁碟剩約 30 GB。`~/.cache/review-fixes/mirrors` 已經存在 |
| Docker | dockerd 29.9.2，用 root 啟動，帶當下的 `HTTP(S)_PROXY=$HTTPS_PROXY`。`hello-world` 成功，這次沒有遇到 Docker Hub 429 |
| runner（第 2 次，`results-B.json`） | candidate `sha256:328ff444b81f…`、測試 image `sha256:4d6c75f5048a…` |
| 全套測試用的 image | runner 第 1 次建的測試 image `sha256:7a53415a204f…`（tag 成 `round16-full:test`）。commit 相同，`/usr/bin/php` sha256 也相同 |
| PHP | chiseled `/usr/bin/php` 8.3.6。sha256 `7f1ac2fe89d2…a67d7`，和第 10–15 輪相同。`php -v`、`php -m`、sha256 都相同 |
| 資料庫 | runner 用自己的 `mysql:8.4`。全套測試另外開一個 `mysql:8.4`，每個 shard 有自己的資料庫和 `/var/lib/snipeit` volume |

**runner 跑了兩次，原因是我這邊的操作錯誤，不是工具的問題。** 第 1 次 runner（08:31 開始）放在背景執行時，沒有設定較長的時限，大約 09:01 被這個 session 的 30 分鐘背景時限中斷了。

- 中斷時，第 1 次已經完成：input lock 檢查、candidate 和測試 image 的建置、PHP 比對、Go unit，以及 7 個 phpunit 執行（222 個測試全部通過，0 略過），正在跑 FR-8 的 Apache 探測。
- 留下來的容器、volume、網路和暫存目錄，我照名稱手動清掉了。
- 全套測試跑完後，我用 2 小時的時限重跑 runner（09:41:49–09:48:45，build cache 都命中，約 7 分鐘）。commit 的 `results-B.json` 是第 2 次完整執行的結果。
- 兩次建出的 image ID 不同，因為 build 不是逐位元可重現的。兩次的 commit 和 PHP binary 都相同。

| 階段 | 時間（UTC） |
| --- | --- |
| 讀說明、啟動 dockerd | 08:28–08:31 |
| runner 第 1 次（中斷） | 08:31–約 09:01 |
| 全套測試：13 個容器平行跑 | 08:53–09:39。shard 耗時分別是 2257、2734、1178、1435 秒；syncrest 1452 秒；ABM 146–1288 秒 |
| 分析、二分法定位 | 09:35–09:41 |
| runner 第 2 次 | 09:41:49–09:48:45 |
| 清理、報告 | 09:50– |

## 2. 測試數量

### runner（`results-B.json`）

`counts` 是 passed 222、failure 1（預期的 FR-9 突變版），和第 14、15 輪相同。

| 執行 | 通過 | 失敗 |
| --- | --- | --- |
| `LdapTest` selected / 全套 | 7 / 35 | 0 / 0 |
| `S3Compatibility` selected / 全套 | 16 / 103 | 0 / 0 |
| `LdapWizardTest` selected / 全套 | 3 / 57 | 0 / 0 |
| FR-9 原版 / 突變版 | 1 / 0 | 0 / 1（預期） |

### 全套 `tests/`

分成 4 個 shard（SyncAdapters 以外的部分，依檔案大小平均分配）、syncrest（SyncAdapters 去掉 ABM）和 ABM 8 個檔案，共 13 個容器平行跑。volume 的初始化和 runner 一樣，用 `startup.go` 的 `dataDirs` 產生。

| | 第 16 輪 | 第 15 輪 |
| --- | --- | --- |
| 測試 | **7086** | 7086 |
| assertions | 22023 | 22014 |
| failure | 10 | 27 |
| error | 18 | 14 |
| 略過 | 3（程式碼本來就標記的：`ApiRateLimitTest` 2、`DeleteAssetsTest` 1） | 3 |
| incomplete | 54（`markTestIncomplete`，上游也一樣） | 54 |

和第 15 輪的差異：

- failure 少了 17 個：DNS 的 14 個這次用 `--add-host` 讓它們通過，`ShelllessOptInTest` 的 3 個已修好。
- error：原本的 14 個消失了，新出現 18 個（F）。

## 3. 失敗和可疑項目

| # | 測試 | 數量 | 原因 | 上游 |
| --- | --- | --- | --- | --- |
| A | `Unit\CustomFieldTest` 6 個、`Unit\Importer\ImporterEncodingTest` 2 個 | 8 F | chiseled 沒有 `intl`（已知） | 已知的環境差異 |
| B | DNS 的 14 個 `ExternalUrl` 測試 | 0 | 這次跑之前加了 `--add-host`（「已知狀況」列的 5 個主機），全部通過。`CompanyWebhooksTest`、`WebhookEndpointSsrfTest`、Fleet、Intune、Kandji、`AssetTagPatternTest`、`GroupCompanyMappingTest` 0 失敗 | — |
| C | 第 15 輪 volume 少目錄造成的 14 個 error | 0 | 照 `dataDirs` 初始化後消失了 | — |
| D | `Importing\Api\ImportAssetsTest::will_encrypt_custom_fields` | 1 F | `Failed asserting that 'D5:20:…' is not equal to 'D5:20:…'`，和第 15 輪相同 | 「已知狀況」列為上游問題 |
| E | `Mcp\ListLicensesToolTest::test_offset_skips_results_for_pagination` | 1 F | `Failed asserting that an array is empty.`，MySQL 8.4 上的排序不固定，和第 15 輪相同 | 「已知狀況」列為上游問題 |
| F | `S3Compatibility\RestoreToRemoteDiskTest`，整個類別 18 個測試（包括 finding3 的 4 個資料集和 `local_destination_prefers_manifest_staged_copy_when_stale_copy_follows`） | **18 E** | `ErrorException: proc_open(): posix_spawn() failed: No such file or directory`，發生在 `RestoreFromBackup.php:602`。說明見下方 | 上游沒有這些測試，是我們的測試 |

F 的原因：

- `tests/Feature/Console/ShelllessSchedulerTest.php` 的 `setUp()` 設 `SNIPEIT_SHELLLESS=true`，`tearDown()` 則**無條件**執行 `putenv('SNIPEIT_SHELLLESS')` 和 `unset($_SERVER[...], $_ENV[...])`，沒有恢復成原本的值。
- chiseled image 的 Env 本來就是 `SNIPEIT_SHELLLESS=true`。這個測試跑完之後，同一個 phpunit process 裡後面的測試都會讀到 `app.shellless = false`。
- `dbClientCommand()` 因此回傳字串，`proc_open` 用字串時會經過 `/bin/sh -c`，而 chiseled image 沒有 `/bin/sh`。
- 這次 shard0 的檔案順序剛好是 `Console/ShelllessSchedulerTest` 在 `S3Compatibility/RestoreToRemoteDiskTest` 前面。第 15 輪的分配不同，所以沒有遇到。runner 只跑 `tests/Feature/S3Compatibility`，所以也不會遇到。
- 一般環境（CI、主機）沒有設這個變數，清掉也不影響，所以 CI 看不到這個問題。

二分法驗證（同一個 image，每次都用新的資料庫和 volume）：

| 檔案順序 | 結果 |
| --- | --- |
| `RestoreToRemoteDiskTest` 單獨跑 | OK（31 個測試） |
| `ShelllessOptInTest` → `RestoreToRemoteDiskTest` | OK（37 個測試）。新的 `4c1f2c64f8` 有正確還原環境變數 |
| `ShelllessSchedulerTest` → `RestoreToRemoteDiskTest` | **18 個 error**，完全重現 |

結論：這是我們測試的隔離問題，不是程式錯誤。正式環境的 restore 在 chiseled 裡走 shell-less 路徑，runner 的 S3 全套（103 個）和第 1 次的結果都通過。

合計：failure 8 + 1 + 1 = 10，error 18，和 junit 的數字一致。

## 4. 「這次的重點」逐項回答

1. **dockerd**：用當下的 `$HTTPS_PROXY` 啟動，`hello-world` 成功。
2. **原樣執行 runner**：工具、程式碼和 Dockerfile 都沒有修改。
   - 第 2 次完整執行的結果：exit **0**，`errors` 是 **`[]`**。
   - 除了 FR-9 突變版之外 **0 失敗**；`skipped_summary` 全部是空的，所以 **0 略過**。
   - FR-2：`fr2_chiseled`、`fr2_regular` exit 0，`fr2_prepare_app` 是 `marker_directory_present: false`。
   - FR-8：valid、empty、unset 都 exit 0；invalid 容器啟動失敗（exit 1），符合預期；`fr8_go_unit` exit 0。
   - FR-9：原版 exit 0。突變版失敗，訊息是 `Finding 9: safety backup omitted remote files.`，`fr9_mutation_red.passed = true`。
   - `candidate_proxy_ca_absent`、`chiseled_input_locks`（`locks are up to date`）都通過。
   - `results-B.json`、debug log 和我的全套測試指令裡都沒有 `docker.sock`。runner 跑完後 `git status` 只有 `results-B.json` 有變動。
   - runner 第 1 次被我這邊的背景時限中斷了，見第 1 節。
3. **全套測試**：見第 2、3 節。
   - `ShelllessOptInTest` 3 個（整個類別 6 個）**通過**。
   - 第 15 輪的 14 個 volume error **消失了**。
   - 已知的失敗：intl 8 個，以及上游的 `will_encrypt_custom_fields` 和 `ListLicensesToolTest`。DNS 的 14 個用 `--add-host` 讓它們通過。
   - 其他失敗只有 F 的 18 個 error，原因已定位到我們的 `ShelllessSchedulerTest`，不是上游的問題，所以不需要到官方 master 對照。
4. **清理**：
   - 刪掉 runner 中斷後留下的資源，以及全套測試的容器、volume、網路和資料庫容器。
   - 執行了 `docker image prune -af`、`docker buildx prune -af`、`docker system prune -af --volumes`，之後 `docker system df` 全部是 0。
   - dockerd 已停止。`/tmp/review-*` 沒有殘留。
   - `~/.cache/review-fixes/mirrors` 是工具設計上要重複使用的快取，所以保留。

## 5. 修改建議（依重要性排序）

1. **`tests/Feature/Console/ShelllessSchedulerTest.php`（我們的改動，測試隔離）**：`tearDown()` 應該把 `SNIPEIT_SHELLLESS` 恢復成 `setUp()` 之前的狀態，不要直接清掉。否則在 chiseled 裡（或任何設了 `SNIPEIT_SHELLLESS=true` 的環境）跑全套時，後面的測試會改走 shell 路徑，像 F 那樣失敗。或者更糟的情況是：測試通過了，實際上卻沒有測到 shell-less 路徑。做法和 `4c1f2c64f8` 對 `ShelllessOptInTest` 的處理一樣：

   ```diff
   +    private string|false $previousShellless;
   +    private array $previousShelllessGlobals = [];
   +
        protected function setUp(): void
        {
            parent::setUp();
   +        $this->previousShellless = getenv('SNIPEIT_SHELLLESS');
   +        foreach (['_ENV', '_SERVER'] as $global) {
   +            if (array_key_exists('SNIPEIT_SHELLLESS', $GLOBALS[$global])) {
   +                $this->previousShelllessGlobals[$global] = $GLOBALS[$global]['SNIPEIT_SHELLLESS'];
   +            }
   +        }
            // Must be set before the application is created: the provider reads it while registering.
            putenv('SNIPEIT_SHELLLESS=true');
   ...
        protected function tearDown(): void
        {
   ...
   -        putenv('SNIPEIT_SHELLLESS');
   -        unset($_SERVER['SNIPEIT_SHELLLESS'], $_ENV['SNIPEIT_SHELLLESS']);
   +        $this->previousShellless === false
   +            ? putenv('SNIPEIT_SHELLLESS')
   +            : putenv('SNIPEIT_SHELLLESS='.$this->previousShellless);
   +        unset($_SERVER['SNIPEIT_SHELLLESS'], $_ENV['SNIPEIT_SHELLLESS']);
   +        foreach ($this->previousShelllessGlobals as $global => $value) {
   +            $GLOBALS[$global]['SNIPEIT_SHELLLESS'] = $value;
   +        }
   ```

   `$_ENV` 和 `$_SERVER` 在函式裡透過 `$GLOBALS` 改寫是可以的。如果想避免用 `$GLOBALS`，也可以像 `ShelllessOptInTest` 那樣，分開記錄 `$hasEnv`、`$hasServer`。改完後可以用第 3 節的順序（`ShelllessSchedulerTest` → `RestoreToRemoteDiskTest`）在 chiseled 測試 image 裡驗證。
2. **測試工具 `cloud-verify/review-fixes/runner.py`（建議）**：runner 只跑 `S3Compatibility` 這個目錄，所以抓不到跨目錄的狀態污染。可以考慮在 runner 裡加一個固定順序的執行：先跑 `tests/Feature/Console/Shellless*` 再跑 `tests/Feature/S3Compatibility`（一個 phpunit config 列出這些檔案），預期 0 失敗。這樣第 1 點的回歸以後會在 runner 裡被抓到，不用依賴全套 shard 剛好排到這個順序。
3. **說明檔（CLOUD_TEST.md）**：
   - 「已知狀況」可以補上：在 chiseled 裡跑全套時，修好第 1 點之前，`RestoreToRemoteDiskTest` 可能因為測試順序出現 18 個 `posix_spawn` error。
   - 全套測試的方式（shard 分配、`--add-host`、volume 照 `dataDirs` 初始化、ABM 每個檔案一個容器）可以寫成固定的腳本放進 `cloud-verify/`，每輪結果才能比較。這次的腳本是 scratchpad 裡的 `prep.py` 和 `run.sh`，沒有 commit。
   - runner 和全套測試不能同時重跑。runner 開始時會刪掉帶 `review-fixes.run` label 的容器，而從它的測試 image 啟動的容器會繼承這個 label，所以重跑 runner 會殺掉正在跑全套的容器。
4. **上游問題（同第 15 輪）**：`ListLicensesTool` 應該再加 `->orderBy('licenses.id', 'desc')` 作為第二排序欄位；`will_encrypt_custom_fields` 在上游本來就失敗。
