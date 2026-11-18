# 雲端測試結果：第 18 輪（rebase 到官方 master `0a9db6d485` 之後的 `all-changes`）

**第 18 輪沒有通過。** 失敗只有一個原因，而且已經找到。

- **原因**：上游 `a9e8743cfe`（MySQL 測試快取初始 schema）新增了 `MySqlDatabaseSnapshot::isSupported()`。它用 Symfony `ExecutableFinder` 找 `mysql`，PATH 裡找不到時會改成執行 `exec('command -v -- mysql')`。chiseled image 沒有 shell，所以 `exec()` 會發出 `exec(): Unable to fork` 警告，Laravel 把警告轉成 `ErrorException`。結果是**每個會用到資料庫的測試**都在 `TestCase::migrateDatabases()` 出錯。chiseled 有 `mariadb` 和 `mysqldump`，但沒有叫 `mysql` 的檔案，所以一定會走到 `exec()`。
  - `tests/TestCase.php` 和 `tests/Support/MySqlDatabaseSnapshot.php` 和官方 master `0a9db6d485` 完全相同。**問題出在上游的程式碼，但只有在我們沒有 shell 的 chiseled 測試環境才會出錯。** 上游在一般有 shell 的環境裡 `exec()` 可以正常執行，這段程式碼不會出錯。
  - 只影響測試，不影響正式環境的程式碼。
- **第 2 步（原樣執行 runner）**：exit **1**。258 個 error，只有 9 個通過。其中 243 個是上面這個 `ErrorException`，另外 15 個是連帶造成的 duplicate key（setUp 在建立交易之前就出錯，上一個測試的資料沒有被 rollback）。`shellless_order` 是 8 個通過、37 個 error（`ShelllessSchedulerTest` 8 個不碰資料庫，所以通過）。因為 FR-9 原版沒有通過，突變測試沒有執行。不用 phpunit 的探測都通過：FR-2、FR-8、`candidate_proxy_ca_absent`、input lock、PHP identity。
- **第 3 步（原樣執行全套）**：7169 個測試，7134 個 error（7095 個是同一個 `ErrorException`，39 個是連帶的 duplicate key），只有 35 個不碰資料庫的通過。
- **診斷執行**：為了確認除了這個問題以外沒有別的問題，我在 scratchpad 的副本裡只加了 `php -d disable_functions=exec`，重跑 runner 和全套。`exec` 不存在時，`ExecutableFinder` 直接回傳 null，`isSupported()` 回 false，改用一般的 migration，結果等於在一般有 shell 但沒有 `mysql` 的主機上跑。repo、程式碼、工具和 image 都沒有修改。
  - **runner：exit 0，`errors` 是 `[]`**。267 個通過，唯一的失敗是預期的 FR-9 突變版。**`shellless_order` 45/45 通過**，順序符合參數順序。FR-2、FR-8、FR-9、`candidate_proxy_ca_absent`、input lock 全部通過，結果和第 14–17 輪相同。
  - **全套：7169 個，9 個 failure，1 個 error，4 個略過，54 個 incomplete。**
    - 9 個 failure 都是已知的：缺 `intl` 的 8 個，加上上游的 `ListLicensesToolTest`。
    - **`will_encrypt_custom_fields` 這次通過了**，上游 `b1515e794d` 修好了。
    - 1 個 error 是 `LdapFunctionMockingTest`（上游新增）。它用 `#[RunInSeparateProcess]`，子 process 不會繼承 `-d`，所以又碰到同一個 `exec()` 問題。改用 `PHP_INI_SCAN_DIR` 放 ini 重跑後 1/1 通過。
    - 新的第 4 個略過是上游新增的 `MySqlDatabaseSnapshotTest`（`Snapshot restoration requires MySQL/MariaDB and the MySQL client tools.`）。在 chiseled 裡略過是合理的。
  - 順序驗證（診斷版）：`ShelllessSchedulerTest` → `RestoreToRemoteDiskTest` 39/39 通過，加上 `ShelllessOptInTest` 的三檔順序 45/45 通過。

**結論**：除了 `a9e8743cfe` 在沒有 shell 的環境出錯以外，沒有其他未解釋的失敗。rebase、我們的改動、上游的 kernel/middleware 改動和 LDAP mock 都沒有造成問題。修正方式見第 5 節第 1 點（建議 `all-changes` 加一個很小的測試支援修正，或對上游提 PR）。

被測的 commit 是 `cloud-test` `5b12a09a27`（merge commit，包含 `all-changes` `d39f54466f`）。原樣執行的 `results-B.json` 已經 commit。診斷執行的結果放在 `cloud-test-output.txt` 第 3–6 節，沒有另外 commit。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核，15 GB RAM，磁碟剩約 30 GB。這是新的容器，`~/.cache/review-fixes/mirrors` 一開始不存在，由 runner 建立 |
| Docker | dockerd 29.10.0，用 root 啟動，帶當下的 `HTTP(S)_PROXY=$HTTPS_PROXY`。`hello-world` 成功 |
| runner（原樣執行，`results-B.json`） | candidate `sha256:65b143922272…`、測試 image `sha256:170a5f7c9088…` |
| runner（診斷） | candidate `sha256:28c7c82ed901…`、測試 image `sha256:31d09e7ac59b…`。同一個 commit 重新 build 的，image ID 不同，可能是 build 不能完全重現（時間戳之類）。全套診斷用的是這個測試 image |
| PHP | chiseled `/usr/bin/php` 8.3.6，sha256 `7f1ac2fe89d2…a67d7`，和第 10–17 輪相同。candidate 和測試 image 的 `php -v`、`php -m`、sha256 都相同。image 的 Env 有 `SNIPEIT_SHELLLESS=true` |
| 資料庫 | runner 用自己的 `mysql:8.4`。全套測試另外開一個 `mysql:8.4`，每個 shard 有自己的資料庫和 `/var/lib/snipeit` volume |

**背景時限**：runner 都用 2 小時，全套測試都用 3 小時，沒有被時限中斷。但是在 **約 03:53 UTC，這個 session 的容器被重啟了一次**（不是我的指令造成的），dockerd 和診斷全套測試因此中斷。重啟之後 image 和檔案都還在。我把已經跑完的 7 個 ABM 結果留下，其他 shard（shard0–3、syncrest、abm3）從 03:55:47 開始重跑。

| 階段 | 時間（UTC） |
| --- | --- |
| 讀說明、啟動 dockerd | 03:10–03:13 |
| runner 原樣執行 | 03:13–03:28（exit 1） |
| 全套原樣執行（runner 的測試 image 一建好就開始） | 03:23:33–03:27:58（幾乎都是很快就出錯，所以很短） |
| 找原因 | 03:25–03:29 |
| runner 診斷執行 | 03:29–03:37（exit 0） |
| 全套診斷執行 | 03:30:37 開始，約 03:53 因容器重啟中斷，03:55:47–04:38:57 重跑。重跑時各 shard 的耗時：shard0 1844 秒、shard1 1997 秒、shard2 1232 秒、shard3 2527 秒、syncrest 1360 秒、abm3 1215 秒；重啟前跑完的 ABM 是 139–916 秒 |
| 順序驗證（診斷）、清理、報告 | 04:39– |

## 2. 測試數量

### runner

| 執行 | 原樣執行（`results-B.json`） | 診斷（`-d disable_functions=exec`） | 第 17 輪 |
| --- | --- | --- | --- |
| `LdapTest` selected / 全套 | 0 / 0 通過（7 / 35 個 error） | 7 / 35 通過 | 7 / 35 |
| `S3Compatibility` selected / 全套 | 0 / 1 通過（16 / 102 個 error） | 16 / 103 通過 | 16 / 103 |
| `LdapWizardTest` selected / 全套 | 0 / 0 通過（3 / 57 個 error） | 3 / 57 通過 | 3 / 57 |
| `shellless_order`（新） | 8 個通過、37 個 error | **45 / 45 通過** | — |
| FR-9 原版 / 突變版 | error / 沒有執行 | 通過 / 失敗（預期） | 通過 / 失敗 |
| `counts` | error 258、passed 9 | passed 267、failure 1 | passed 222、failure 1 |
| exit / `errors` | 1 / 270 行 | **0 / `[]`** | 0 / `[]` |

診斷版比第 17 輪多的 45 個就是新的 `shellless_order`。

### 全套 `tests/`

分成 13 個容器平行跑，方式和第 17 輪相同（用 `cloud-verify/full-suite/`）。

| | 原樣執行 | 診斷 | 第 17 輪 |
| --- | --- | --- | --- |
| 測試 | 7169 | **7169** | 7086 |
| assertions | 59 | 22340 | 22087 |
| failure | 0 | 9 | 10 |
| error | 7134 | 1 | 0 |
| 略過 | 0 | 4 | 3 |
| incomplete | 0 | 54 | 54 |

多了 83 個測試，都來自上游新增的測試，例如 `MySqlDatabaseSnapshotTest`、`LdapFunctionMockingTest`、MCP 相關的測試。JUnit 的 `skipped` 是 58，也就是 4 個略過加 54 個 incomplete。

| shard（診斷） | 結果 |
| --- | --- |
| shard0 | 1608 個，1 F（`ListLicensesToolTest`），2 略過，6 incomplete |
| shard1 | 1668 個，1 E（`LdapFunctionMockingTest`，診斷方式造成的，見下面），1 略過，16 incomplete |
| shard2（含 `ShelllessSchedulerTest` → `RestoreToRemoteDiskTest`，兩個都通過） | OK，1629 個，18 incomplete |
| shard3 | 1712 個，8 F（intl），1 略過（`MySqlDatabaseSnapshotTest`），14 incomplete |
| syncrest | OK，488 個 |
| ABM 0–7 | 全部 OK（5–14 個） |

## 3. 失敗和可疑項目

| # | 測試 | 數量 | 原因 | 上游 |
| --- | --- | --- | --- | --- |
| **X** | **所有會用到資料庫的測試**（原樣執行） | 7095 E + 39 E（全套），243 E + 15 E（runner） | `ErrorException: exec(): Unable to fork [command -v -- 'mysql']`，出錯位置是 `ExecutableFinder.php:95` ← `MySqlDatabaseSnapshot.php:23` ← `TestCase.php:148`。duplicate key 是連帶造成的 | **上游 `a9e8743cfe` 的程式碼**（和 master 完全相同），只在我們沒有 shell 的 chiseled 環境出錯。上游一般的環境不會出錯 |
| A | `Unit\CustomFieldTest` 6 個、`Unit\Importer\ImporterEncodingTest` 2 個 | 8 F | chiseled 沒有 `intl`（已知） | 已知的環境差異 |
| C | `Mcp\ListLicensesToolTest::test_offset_skips_results_for_pagination` | 1 F | `Failed asserting that an array is empty.`（已知） | 上游的問題 |
| D | `Unit\LdapFunctionMockingTest::test_ldap_error_can_be_mocked_after_an_unmocked_call`（上游新增） | 1 E（診斷） | 和 X 相同。它用 `#[RunInSeparateProcess]`，子 process 沒有拿到 `-d disable_functions=exec`。用 `PHP_INI_SCAN_DIR` 放 ini 再跑：**OK（1 個測試，3 assertions）**；不加 ini 時重現 X | 和 X 相同 |
| E | `Support\MySqlDatabaseSnapshotTest` 的 1 個略過（上游新增） | 1 S | chiseled 沒有 `mysql` client，略過是設計好的。同一個檔案其他 7 個通過 | 上游的測試 |
| B | `ImportAssetsTest::will_encrypt_custom_fields` | **0** | **通過了**，上游 `b1515e794d` 修好了 | — |
| F | DNS 的 14 個 `ExternalUrl` 測試 | 0 | 加了 `--add-host` 之後全部通過：`CompanyWebhooksTest` 1、`WebhookEndpointSsrfTest` 32、Intune 5、Kandji 2、`AssetTagPatternTest` 10、`FleetLicenseTierTest` 4、`FleetSettingsPageTest` 7、`GroupCompanyMappingTest` 9 | — |

**到官方 master 對照**：X 和 D 的程式碼（`tests/TestCase.php`、`tests/Support/MySqlDatabaseSnapshot.php`、`tests/Unit/LdapFunctionMockingTest.php`）都和 `0a9db6d485` 完全相同，`git diff 0a9db6d485 d39f54466f -- tests/TestCase.php` 是空的。原因（找不到檔案時改用 `exec`，而 chiseled 沒有 shell）可以直接從呼叫堆疊和在 image 裡的探測確認，見 `cloud-test-output.txt` 第 8 節。所以沒有另外在一般 PHP 環境重跑上游，因為那邊有 shell，不會走到出錯的這條路。A、C 是「已知狀況」列的項目。

## 4. 「這次的重點」逐項回答

- **rebase 到 `0a9db6d485`、SMTP commit 被略過、`composer.lock` repin**：`0a9db6d485` 是 `d39f54466f` 的祖先，中間有 55 個我們的 commit。input lock 檢查（`chiseled_input_locks`）通過，表示 repin 是對的。PHP identity 相同。
- **`shellless_order`（第一次在雲端跑）**：工具本身是正常的。PHPUnit 11.5.55 接受多個檔案參數，加上 `--order-by default,no-depends` 之後照參數順序執行（`ShelllessSchedulerTest` 8 個 → `ShelllessOptInTest` 6 個 → `RestoreToRemoteDiskTest` 31 個）。原樣執行時因為 X，37 個出錯；診斷時 **45/45 通過**。
- **`94e5c754b4`（kernel/middleware 改成新的自動載入方式）**：`ShelllessSchedulerTest` 會載入 `bootstrap/app.php`，8 個都通過（原樣執行時也通過，因為它不碰資料庫）。`ShelllessOptInTest` 6 個在診斷時都通過，包括「預設用 framework scheduler、開啟 shellless 後換成 `ShelllessScheduleRunCommand`」，所以 `AppServiceProvider` 的綁定還正常。全套的 HTTP 測試（middleware）診斷時沒有新的失敗。FR-8 的 Apache 探測正常。
- **`0cc4341a9b`（Passport 13 的金鑰權限）**：這個 commit 只改了 bash 的 `startup*.sh` 和 `snipeit.sh`，加了 `chmod 660/600`。Passport 本來就是 13.7.6，`validateKeyPermissions = true` 不是這次才有的。在 chiseled 測試 image 裡實測：
  - `artisan passport:keys`（uid 10000）透過 symlink 寫到 `/var/lib/snipeit/keys/`，結果是 private `600`、public `660`，擁有者都是 10000。`League\OAuth2\Server\CryptKey` 檢查權限後可以正常載入。
  - 把 private 改成 `644` 後，會出現 `Key file ... permissions are not correct, recommend changing to 600 or 660 instead of 644` 的 notice。Laravel 正常執行時會把它轉成例外。
  - chiseled 的 Go init（`startup.go`）只建立 `keys` 目錄，沒有對應上游 `chmod` 的步驟。用 `passport:keys` 產生的金鑰沒有問題；手動放進去或從舊安裝搬過來的 `644` 金鑰會讓 OAuth/API 失敗。這是建議，不是失敗，見第 5 節第 3 點。
- **`2ddfd10b5c`、`b7fa94e9a7`（共用 LDAP mock helper）**：沒有衝突。`MocksLdap` 在 `#[BeforeClass]` 用 `Mock::define()` 預先定義 `App\Models` 的 LDAP 函式，但沒有 enable。我們的 `LdapTest` 用 `getFunctionMock()`（35/35）、`LdapWizardTest`（57/57），以及上游的 `LdapSyncMutexTest`（5/5），在診斷的 runner 和全套都通過。`LdapFunctionMockingTest` 見第 3 節 D。
- **`b1515e794d`**：**修好了**。`will_encrypt_custom_fields` 在診斷全套通過（2 assertions）。「已知狀況」可以把它拿掉。
- **`a9e8743cfe`（MySQL schema 快取）**：**這次失敗的原因**，見第 3 節 X。另外，就算修好了，在 chiseled 裡 `isSupported()` 也會回 false（沒有 `mysql` client，dump 和 load 也都要用 shell 執行指令），所以**全套測試不會因此變快**。這次診斷全套的耗時（shard 1232–2527 秒）和第 17 輪差不多（1681–2716 秒），瓶頸仍然是 MySQL（CPU 275%，test process 約 2%）。

步驟：
1. **dockerd**：用當下的 `$HTTPS_PROXY` 啟動。時限是 runner 2 小時、全套 3 小時。容器重啟後重新啟動 dockerd。
2. **runner 原樣執行**：exit 1，**不符合要求**，原因是 X。用診斷方式重跑後，所有要求都符合，`shellless_order` 也全部通過。
3. **全套**：原樣執行時幾乎全部是 X。診斷時只剩已知的失敗（intl 8 個、`ListLicensesToolTest`），以及 X 在 separate process 測試的 1 個 error。
4. **清理**：刪掉所有容器、volume、自訂網路（`r17-*`、`r17o-*`、探測用的 volume）和 `full-suite:test` tag。執行了 `docker image prune -af`、`docker buildx prune -af`、`docker system prune -af --volumes`，之後 `docker system df` 全部是 0。dockerd 已停止，診斷用的 git worktree 已刪除，`/tmp/review-*` 沒有殘留。`~/.cache/review-fixes/mirrors` 是工具設計上要重複使用的快取，所以保留。工具、程式碼和 Dockerfile 都沒有修改。repo 裡只有 `results-B.json`（原樣執行的結果）和兩個報告檔有變動。

## 5. 修改建議（依重要性排序）

1. **【必要】測試支援程式碼 `tests/Support/MySqlDatabaseSnapshot.php`（上游的程式碼，在我們的 chiseled 測試環境出錯）**：沒有 shell 時直接回傳 false，不要讓 `ExecutableFinder` 改用 `exec()`。snapshot 的 dump 和 load（`MySqlSchemaState`）本來就要透過 shell 執行指令，所以沒有 shell 時本來就不能用，回 false 是正確的行為：

   ```diff
        public static function isSupported(Connection $connection): bool
        {
            if (! in_array($connection->getDriverName(), ['mysql', 'mariadb'], true)) {
                return false;
            }
   +
   +        // Dumping and loading run through a shell command line, and
   +        // ExecutableFinder falls back to exec('command -v'), which warns
   +        // (and fails the test) where there is no /bin/sh, e.g. Chiseled.
   +        if (! is_executable('/bin/sh')) {
   +            return false;
   +        }
   ```

   上游 Windows 的路徑不受影響（那邊不會走到 `exec('command -v')`，而且 Windows 也沒有 `/bin/sh`。如果要讓 Windows 上的 MySQL 也能用快取，可以改成 `DIRECTORY_SEPARATOR === '/' && ! is_executable('/bin/sh')`）。另一個做法是用 `config('app.shellless')` 判斷，但 `ShelllessOptInTest` 會切換這個設定，用 `/bin/sh` 判斷比較直接。這是上游的測試程式碼，建議先放進 `all-changes`，同時可以對上游提 PR，因為沒有 shell 的 CI 或容器都會遇到。修完後應該會是：runner exit 0、全套只剩 intl 8 個和 `ListLicensesToolTest`，`LdapFunctionMockingTest` 也會通過。
2. **測試工具 `cloud-verify/review-fixes/runner.py`（我們的工具，建議）**：這次所有 phpunit 都失敗，但 runner 的 `errors` 寫了 270 行，大多是每個測試一行的 `JUnit error in ...`，很難看出真正的原因。建議在 `errors` 加一行最常見訊息的摘要，例如「258 個測試中有 243 個是 `ErrorException: exec(): Unable to fork …`」，或是把相同訊息合併。另外，FR-9 原版失敗時，`FR-9 mutation produced no test result` 這行是連帶造成的，可以標成「因為原版失敗而略過」。
3. **chiseled Go init（我們的改動，建議，和上游 `0cc4341a9b` 對齊）**：`docker/snipeit-runtime/internal/startup/startup.go` 在建立 `keys` 之後，對已經存在的 `oauth-public.key` 和 `oauth-private.key` 做 `os.Chmod(…, 0660)` 和 `os.Chmod(…, 0600)`，不存在就略過，並在 `startup_test.go` 加一個測試。上游在 bash 版的 `startup.sh` 已經這樣做了。目前 chiseled 只有用 `passport:keys` 產生的金鑰權限是對的。
4. **全套測試腳本 `cloud-verify/full-suite/`（建議）**：
   - `run-full.sh` 和 `run-order.sh` 可以支援把額外的 PHP 參數傳給 phpunit（例如 `PHPUNIT_PHP_ARGS`），這次的診斷就不需要複製腳本。要讓 separate process 的測試也拿到同樣的設定，要用 `PHP_INI_SCAN_DIR` 掛一個 ini，因為 `-d` 不會傳給子 process。
   - README 的「注意」可以補一句：在全套還在跑的時候重跑 runner，runner 開始時的清理（`cleanup_previous_runs`）也會刪掉 `full-suite:test` 這個 tag，因為它是同一個帶 label 的 image。這次重跑診斷 runner 時就遇到了，之後從新的測試 image 重新 tag。
5. **說明檔（CLOUD_TEST.md）**：
   - 「已知狀況」可以把 `will_encrypt_custom_fields` 拿掉（上游 `b1515e794d` 修好了），補上 chiseled 會略過 `MySqlDatabaseSnapshotTest` 1 個。
   - 預期的略過數字從 3 個改成 4 個。
6. **上游問題（同第 15–17 輪）**：`ListLicensesTool` 應該再加 `->orderBy('licenses.id', 'desc')` 作為第二排序欄位。
