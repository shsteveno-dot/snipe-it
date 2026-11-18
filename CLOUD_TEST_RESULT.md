# 雲端測試結果：第 19 輪（確認第 18 輪的修正）

**第 19 輪沒有通過。** 有兩個問題，都出在 `all-changes` `4c18a78d0b` 新加的修正：

1. **【阻擋】`docker/snipeit-runtime/internal/startup/startup.go` 編譯不過。** 新的 `KeyPermissionsAt()` 第 169 行的 `fmt.Fprintf(os.Stderr, "warning: … %v\n", …)` 裡，`\n` 變成了真的換行（字串被斷成兩行），Go 報 `newline in string`。`Dockerfile.chiseled` 的第一個階段會編譯 `./cmd/init`，所以 **chiseled candidate build 失敗**。runner 在 2 分鐘內就 exit 1，沒有任何測試結果，也沒有測試 image，所以第 3 步不能照原樣執行。`go test ./...` 也一樣是 build failed。`4c18a78d0b` 和 cloud-test 上的 `4b80906a21` 這個檔案的內容相同，兩邊都是壞的。
2. **【會失敗】新的 `/bin/sh` 檢查讓上游的 `Tests\Unit\Support\MySqlDatabaseSnapshotTest` 在 chiseled 裡失敗 2 個。** 上游這個單元測試會在 PATH 放假的 `mysql` 和 `mysqldump`，然後預期 `isSupported()` 回傳 true。在沒有 shell 的環境，我們的檢查會先回 false，所以「MySQL with both tools」和「MariaDB with both tools」這兩個 data set 失敗。在同一個 image 換成官方 master 的 `MySqlDatabaseSnapshot.php`，6/6 通過（只有 `exec()` 的 PHP 警告，不算失敗）。**這是我在第 18 輪建議的改法沒有考慮到這個上游測試**，改法見第 5 節第 2 點。

**除了這兩點，修正都有效。** 為了確認，我做了一次診斷執行：在 scratchpad 的 git worktree 只把那個換行改回 `\n`（本機 commit，沒有 push，做完已刪除），然後**原樣**跑 runner 和全套。**`exec` 沒有關，也沒有設定 `PHPUNIT_PHP_ARGS` 或 `PHPUNIT_INI`。**

- **runner：exit 0，`errors` 是 `[]`**。267 個通過，唯一的失敗是預期的 FR-9 突變版，0 略過。`shellless_order` 45/45 通過。FR-2、FR-8、FR-9、`candidate_proxy_ca_absent`、input lock 都通過。第 18 輪的 `exec()` 問題沒有再出現，所以 `/bin/sh` 檢查讓 `TestCase` 正常改用 migration。
- **全套：7169 個，11 個 failure，0 個 error，4 個略過，54 個 incomplete。**
  - 9 個是預期的：intl 8 個，加上 `ListLicensesToolTest`。
  - 另外 2 個是上面的問題 2。
  - **`LdapFunctionMockingTest` 通過了。**
  - 略過的 4 個符合預期：`ApiRateLimitTest` 2 個、`DeleteAssetsTest` 1 個、`MySqlDatabaseSnapshotTest` 1 個。
- **順序驗證**（`run-order.sh` 原樣執行）：39/39、45/45 通過。
- **Go**：修好那一個字元之後，`go vet` 沒有輸出，`go test ./...` 全部 ok，`TestKeyPermissionsAt` 通過。在 chiseled 實際的 supervisor/init 流程裡，`644` 的金鑰會被改成 private `600`、public `660`。root 擁有的金鑰只會印一行警告，啟動會繼續。

修完這兩點，下一輪應該可以通過。被測的 commit 是 `cloud-test` `a360f7022f`（包含 `all-changes` `4c18a78d0b`）。commit 的 `results-B.json` 是**原樣執行**的結果（build 失敗）。診斷執行的結果放在 `cloud-test-output.txt` 第 3–9 節。工具、程式碼和 Dockerfile 都沒有修改。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核，15 GB RAM。`~/.cache/review-fixes/mirrors` 還在（第 18 輪留下的） |
| Docker | dockerd 29.10.0，用 root 啟動，帶當下的 `HTTP(S)_PROXY=$HTTPS_PROXY`。`hello-world` 成功 |
| Go | 容器裡有 `/usr/local/go`（go1.24.7）。`go.mod` 要求 go1.26.10，`GOTOOLCHAIN=auto` 自動下載了 go1.26.10 toolchain。這是 Go 預設的行為，我沒有另外安裝任何東西，但這樣算是有從網路下載 |
| runner（原樣執行） | build 失敗，所以沒有 candidate 或測試 image |
| runner（診斷） | commit `421a6f39a5`（= `a360f7022f` 加上改一個字元，只在本機）。candidate `sha256:ade178396867…`、測試 image `sha256:287fe33c67be…`，全套用的就是這個測試 image |
| PHP | chiseled `/usr/bin/php` 8.3.6，sha256 `7f1ac2fe89d2…a67d7`，和之前相同。`php -v`、`php -m`、sha256 都相同 |
| 資料庫 | `mysql:8.4`，和之前的方式相同 |

| 階段 | 時間（UTC） |
| --- | --- |
| fetch、checkout（HEAD `a360f7022f`）、讀說明、啟動 dockerd | 06:30–06:32 |
| runner 原樣執行 | 06:32:19–06:34:22（exit 1，candidate build 失敗） |
| `go test ./...`、找原因 | 06:33–06:35 |
| runner 診斷執行 | 06:34:57–06:47:07（exit 0） |
| 全套診斷執行（runner 的測試 image 一建好就開始，時限 3 小時） | 06:38:50–07:20:43。shard0 1827 秒、shard1 1997 秒、shard2 1305 秒、shard3 2364 秒、syncrest 1379 秒、ABM 114–1291 秒 |
| 順序驗證、金鑰權限實測、清理、報告 | 07:21– |

這次沒有容器重啟，也沒有被時限中斷。

## 2. 測試數量

### runner

| | 原樣執行（`results-B.json`） | 診斷 | 第 18 輪診斷 |
| --- | --- | --- | --- |
| exit / `errors` | 1 / 3 行 | **0 / `[]`** | 0 / `[]` |
| `counts` | `{}`（0 個測試） | passed 267、failure 1（FR-9 突變版） | 相同 |
| `shellless_order` | 沒有執行 | 45/45 | 45/45 |
| `exec` | 沒有關 | **沒有關** | 關掉 |

### 全套 `tests/`（診斷，`PHPUNIT_*` 都沒有設定）

| | 第 19 輪 | 第 18 輪診斷（關掉 `exec`） | 第 17 輪 |
| --- | --- | --- | --- |
| 測試 | 7169 | 7169 | 7086 |
| assertions | 22343 | 22340 | 22087 |
| failure | 11 | 9 | 10 |
| error | **0** | 1 | 0 |
| 略過 | 4 | 4 | 3 |
| incomplete | 54 | 54 | 54 |

| shard | 結果 |
| --- | --- |
| shard0 | 1608 個，3 F（`ListLicensesToolTest` 1 個、`MySqlDatabaseSnapshotTest` 單元測試 2 個），2 略過，6 incomplete |
| shard1 | **OK**，1668 個（含 `LdapTest` 35、`LdapFunctionMockingTest` 1），1 略過，16 incomplete |
| shard2 | OK，1629 個（`ShelllessSchedulerTest` 排在 `RestoreToRemoteDiskTest` 前面，兩個都通過），18 incomplete |
| shard3 | 1712 個，8 F（intl），1 略過（`MySqlDatabaseSnapshotTest`），14 incomplete |
| syncrest | OK，488 個 |
| ABM 0–7 | 全部 OK |

## 3. 失敗和可疑項目

| # | 測試 | 數量 | 原因 | 上游 / 官方 master `0a9db6d485` |
| --- | --- | --- | --- | --- |
| **G** | chiseled candidate build（runner 原樣執行）、`go test ./...` | build 失敗 | `startup.go:169:68: newline in string`。`Fprintf` 字串裡的 `\n` 變成了真的換行 | **我們的改動（`4c18a78d0b`）** |
| **S** | `Unit\Support\MySqlDatabaseSnapshotTest::test_snapshot_support_requires_a_supported_driver_and_both_clients`，data set「MySQL with both tools」和「MariaDB with both tools」 | 2 F | `Failed asserting that false is identical to true.`。chiseled 沒有 `/bin/sh`，新的檢查比假的 `mysql`/`mysqldump` 還早回傳 false | **我們的改動**。在同一個 image 掛上 master 的 `tests/Support/MySqlDatabaseSnapshot.php`：6/6 通過（3 個 data set 有 `exec()` PHP 警告，不算失敗） |
| A | `Unit\CustomFieldTest` 6 個、`Unit\Importer\ImporterEncodingTest` 2 個 | 8 F | chiseled 沒有 `intl`（已知） | 已知的環境差異 |
| C | `Mcp\ListLicensesToolTest::test_offset_skips_results_for_pagination` | 1 F | 已知 | 上游的問題 |
| — | `LdapFunctionMockingTest` | 0 | 第 18 輪的 1 個 error 消失了，沒有關 `exec` 也會通過 | — |
| — | 略過 | 4 | `ApiRateLimitTest` 2、`DeleteAssetsTest::test_cannot_delete_asset_that_is_checked_out` 1、`Feature\Support\MySqlDatabaseSnapshotTest::test_restoring_the_baseline…` 1（`Snapshot restoration requires MySQL/MariaDB and the MySQL client tools.`），符合預期 | — |
| — | DNS 的 14 個 `ExternalUrl` 測試、`will_encrypt_custom_fields` | 0 | 都通過（`WebhookEndpointSsrfTest` 32/32、`GroupCompanyMappingTest` 9/9、`ImportAssetsTest` 30/30 等） | — |

合計：failure 8 + 1 + 2 = 11，error 0，和 JUnit 的數字一致。

## 4. 「這次的重點」逐項回答

1. **dockerd**：用當下的 `$HTTPS_PROXY` 啟動。時限是 runner 2 小時、全套 3 小時，都沒有被中斷。
2. **runner 原樣執行（不關 `exec`）**：**不符合要求**。exit 1，因為 candidate build 失敗（G）。`errors` 是 `command failed: docker buildx (exit 1)`、`FR-9 mutation skipped because the unmodified FR-9 test did not pass`、`fr9_mutation_red probe failed`。build 之前的 `chiseled_input_locks` 通過。用只改一個字元的診斷 checkout 重跑後，所有要求都符合：exit 0、`errors` 是 `[]`、0 失敗（除了 FR-9 突變版）、0 略過，`shellless_order` 45/45，FR-2、FR-8、FR-9、`candidate_proxy_ca_absent`、input lock 都通過。
3. **全套（`PHPUNIT_PHP_ARGS` 和 `PHPUNIT_INI` 都沒有設定）**：原樣執行時因為 G 沒有 image 可以用。用診斷 image 跑的結果：
   - **確認不需要關掉 `exec`**：0 個 error，`LdapFunctionMockingTest` 通過。
   - 略過 4 個，符合預期。
   - 除了預期的 9 個失敗，還有 **2 個沒有預期到的失敗（S）**。原因是我們的修正，已經到官方 master 對照過。
4. **Go**：容器裡有 Go。`go test ./...` 在 `a360f7022f` 上 **build failed**：`cmd/init` 和 `internal/startup` 失敗，`internal/handoff` 和 `internal/supervisor` ok。在診斷 checkout 上全部 ok，`TestKeyPermissionsAt` PASS，`go vet` 沒有輸出。另外在 chiseled 實際的 `/snipeit-supervisor` → init 流程實測（沒有資料庫，所以 init 最後停在連資料庫那一步，這是預期的）：
   - uid 10000 擁有的 `644` 金鑰被改成 private `600`、public `660`。
   - root 擁有的 private key 會印出 `warning: cannot set mode 0600 on /var/lib/snipeit/keys/oauth-private.key: … operation not permitted`，然後繼續跑 migrate，和設計相同。
   - 注意：`TestKeyPermissionsAt` 沒有測到這個警告的分支，剛好就是寫壞的那一行。不過字串語法錯誤不管有沒有測都會造成編譯失敗，所以只要作者在本機跑過一次 `go test` 或 `go vet` 就會發現。
5. **清理**：
   - 刪掉所有容器（`r17-db`、`r17o-db`、`r19-*`）、volume 和自訂網路，以及 `full-suite:test` tag。
   - 執行了 `docker image prune -af`、`docker buildx prune -af`（10.78 GB）、`docker system prune -af --volumes`，之後 `docker system df` 全部是 0。
   - dockerd 已停止。診斷用的 worktree 已刪除，本機的 commit `421a6f39a5` 不在任何分支上。`/tmp/review-*` 沒有殘留。
   - repo 裡只有 `results-B.json` 和兩個報告檔有變動。全套的輸出寫在 scratchpad，沒有寫進 repo。

**新的 `errors` 摘要格式**：
- 這次原樣執行只有 3 行，可以看懂，但第一行 `command failed: docker buildx (exit 1)` 沒有說原因。要到 debug log 才能看到 `newline in string`。
- 把第 18 輪原樣執行的 `results-B.json` 用新的分組程式重新跑一次（`cloud-test-output.txt` 第 5 節）：從 270 行變成 11 行，第一行是 `summary: 258 of 267 tests errored; most common (243): ErrorException: exec(): Unable to fork [command -v -- 'mysql']`，一眼就看得出原因，**好讀很多**。
- 可以再改進的地方見第 5 節第 3 點。

## 5. 修改建議（依重要性排序）

1. **【阻擋】`docker/snipeit-runtime/internal/startup/startup.go`（我們的改動）**：把字串裡真的換行改回 `\n`：

   ```diff
   -				fmt.Fprintf(os.Stderr, "warning: cannot set mode %04o on %s: %v
   -", key.mode, path, err)
   +				fmt.Fprintf(os.Stderr, "warning: cannot set mode %04o on %s: %v\n", key.mode, path, err)
   ```

   建議 commit 之前在 `docker/snipeit-runtime` 跑一次 `gofmt -l . && go vet ./... && go test ./...`。`gofmt` 遇到這個錯誤也會直接報錯。看起來這個 `\n` 是在產生 patch 的過程中被轉成了真的換行。另外 cloud-test 上的 `4b80906a21` 也帶了一份同樣的改動，要一起修，或是下次只從 `all-changes` merge 進來。
2. **【會失敗】`tests/Support/MySqlDatabaseSnapshot.php` 和 `tests/TestCase.php`（我們的改動。這是我在第 18 輪建議的改法的疏忽）**：把 `/bin/sh` 的檢查從 `isSupported()` 移到 `TestCase::migrateDatabases()`，`MySqlDatabaseSnapshot.php` 改回和官方 master 相同。這樣上游的單元測試在 chiseled 也會通過（實測換成 master 版本後 6/6 通過，只有 `exec()` 的警告），`TestCase` 也還是不會在沒有 shell 時呼叫 `ExecutableFinder`：

   ```diff
    // tests/TestCase.php, migrateDatabases()
   -        if (! MySqlDatabaseSnapshot::isSupported($connection) || $this->shouldSeed() || $this->seeder()) {
   +        // Dump/load run through a shell command line, and ExecutableFinder falls back to
   +        // exec('command -v'), which fails the test where there is no /bin/sh (Chiseled).
   +        $hasShell = DIRECTORY_SEPARATOR !== '/' || is_executable('/bin/sh');
   +        if (! $hasShell || ! MySqlDatabaseSnapshot::isSupported($connection) || $this->shouldSeed() || $this->seeder()) {
   ```

   要注意 `$hasShell` 必須在 `isSupported()` **之前**判斷（`||` 會短路），否則又會走到 `exec()`。另一個做法是保留目前的 `isSupported()`，在上游的單元測試裡沒有 `/bin/sh` 時把那兩個 data set 標成略過。但這樣要改上游的測試，而且預期的略過數字也會變，所以不建議。
3. **測試工具 `cloud-verify/review-fixes/runner.py`（我們的工具）**：
   - 指令失敗時，`errors` 只有 `command failed: docker buildx (exit 1)`。建議附上輸出裡第一個像錯誤的行（例如符合 `ERROR|error:|newline in string|syntax error` 的第一行，或是 `ERROR: failed to solve` 前面的 5 行，記得先遮蔽秘密值）。這次光看 `results-B.json` 看不出是 Go 編譯錯誤。
   - candidate build 失敗、根本沒有跑任何測試時，`FR-9 mutation skipped because the unmodified FR-9 test did not pass` 會讓人誤以為 FR-9 原版有跑而且失敗了。建議 `fr9_original` 不存在時寫成 `… because the unmodified FR-9 test did not run`，而且 `fr9_mutation_red probe failed` 這一行是重複的，可以省略。
   - 分組時用整個訊息（截到 500 字）當 key，會把同一種錯誤拆成好幾組。第 18 輪的資料裡，duplicate key 被拆成 12 個和 3 個兩組，因為訊息裡有各自不同的 SQL 和主機名稱。建議只用訊息的第一行，而且先把數字或括號裡的連線資訊遮蔽掉再分組。
   - 摘要只算 error。如果主要是 failure（例如 assertion 失敗），摘要不會出現。建議也算 failure 和 skipped（`run` 不是 `fr9_mutation` 的）。
   - 可以在 build candidate 之前，先在 `golang` image 裡跑一次 `go vet ./...` 和 `go test ./...`。runner 已經會 pull 這個 image 來做 FR-8 的 Go 測試。這樣 Go 的錯誤會在 30 秒內就清楚地顯示出來。
4. **說明檔（CLOUD_TEST.md）**：第 19 輪說「`startup_test.go` 加了 `TestKeyPermissionsAt`」，但它沒有測到警告的分支。如果要測，可以在非 root 時建一個唯讀目錄裡的檔案，或是用一個 `chmod` 函式變數注入 `os.ErrPermission`。這只是補強，不是必要的。
5. **上游問題（同前幾輪）**：`ListLicensesTool` 應該再加 `->orderBy('licenses.id', 'desc')` 作為第二排序欄位。
