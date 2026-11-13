# 雲端測試結果：第 10 輪（review-fixes 第 A 輪，只有測試、預期 RED）

**總結：工具要先在本機改 6 個地方才跑得完（沒有 commit，見 5.1）。最後一次執行（第 6 次）exit 0，`errors: []`，結果和第 4 次完全相同。**
新測試裡，**問題 1、5 和問題 3、4 的部分測試失敗，而且失敗原因就是它們要抓的問題**；FR-2 三個探測、FR-8 valid 也一樣。**但有 3 類失敗原因不對**：

- **問題 6（5 個測試）**：phpmock 用法錯，測試在 mock 設定時就 `Error`，根本沒執行到 LDAP 的邏輯。
- **問題 3、4 的 6 個 restore 測試**：chiseled image 只有 `/usr/bin/mariadb`、沒有 `/usr/bin/mysql`，`UsesScratchDatabase::mysqlClientDirectory()` 只找 `mysql`，所以 6 個新測試（加上 24 個既有的 restore 測試）都被**略過**。
- **問題 9 和問題 4（web）**：`Artisan::partialMock()` 建出來的 Console Kernel 沒有經過建構子，controller 先呼叫的 `snipeit:restore --validate-only` 傳到真正的 `Kernel::call()`，`$app` 是 null，結果是 **500**。所以 **FR-9 的「突變版失敗」是假的**：原本的版本也失敗。

我另外做了一次**診斷執行**（只在同一個測試 image 上套用最小的測試修正，**沒有放進 `results-A.json`**，見第 4.5 節）。修正後，問題 6 的測試、問題 3 和 4 的其中一個 restore 測試、web 版問題 4，還有 FR-9 的突變測試，都會因為正確的原因 RED；原本的 FR-9 端點測試會通過。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核、15 GB RAM；磁碟開始時剩 30 GB |
| Docker | dockerd 29.9.2（root，自己啟動，帶 `HTTP(S)_PROXY=$HTTPS_PROXY` 和 sandbox 的 `NO_PROXY`），containerd snapshotter；buildx 0.38.1；`docker run --rm hello-world` 成功 |
| 被測的 commit | `e56c46ccc1`（`cloud-test`，含 `review-fixes`） |
| candidate image ID（第 6 次） | `sha256:f734477317e7e6d1d75ab82bc1e197627e5efdb27d920ac7d3e51905e57b1a17` |
| 測試 image ID（第 6 次） | `sha256:9d63b10ccbfd425a8704683c6a728bf90f659669f5793ce50125b47b60dc9b2a` |
| PHP（兩個 image 都是同一個 `/usr/bin/php`） | PHP 8.3.6，PHPUnit 11.5.55；`php -v`、`php -m` 相同，`/usr/bin/php` sha256 `7f1ac2fe89d267364311651c0e7e6651d32ea006c9a701c0cab68eb2394a67d7` 相同 |
| 資料庫 | `mysql:8.4`（runner 自己建立的內部網路） |
| 執行方式 | 單一 process，用 JUnit 輸出 |

| 階段 | 耗時 |
| --- | --- |
| 讀說明和工具、啟動 dockerd | 約 5 分鐘 |
| 第 1 次（`git clone --mirror` 246 個套件，在 phpstan 失敗） | 約 4 分鐘 |
| 第 2 次（重新 clone，composer 13 秒，candidate build 時 Docker Hub 回 429） | 約 6 分鐘 |
| 預先依 digest pull base image | 約 1 分鐘 |
| 第 3 次（第一次跑完整流程，沒有快取的 chiseled build 約 2.5 分鐘；全部測試都是 error） | 8 分 16 秒 |
| 第 4 次（第一次得到有效的結果） | 5 分 13 秒 |
| 第 5 次（在 FR-9 階段遇到 worker 重啟，dockerd 被停掉；中間又碰到使用量上限，停了約 1.5 小時） | — |
| 第 6 次（最後一次，有 build 快取） | 7 分 29 秒 |
| 診斷執行、清理、寫報告 | 約 20 分鐘 |

## 2. 測試數量（第 6 次，`results-A.json` 的 `counts`）

`results-A.json` 裡同一個測試在 `*_selected` 和 `*_suite` 會各記一次，所以總數有重複：passed 154、failure 15、error 10、skipped 37，總共 216 筆。

| 執行 | tests | 通過 | 失敗 | 錯誤 | 略過 |
| --- | --- | --- | --- | --- | --- |
| `LdapTest` 全套 | 35 | 30 | 3 | 2 | 0 |
| `S3Compatibility` 全套 | 100 | 66 | 4 | 0 | 30 |
| `LdapWizardTest` 全套 | 57 | 54 | 0 | 3 | 0 |
| FR-9 突變版（1 個測試） | 1 | 0 | 1 | 0 | 0 |

**既有測試沒有失敗**：三個全套裡的失敗和錯誤都是新測試。但既有的 restore 測試有 24 個被略過（原因見 3.3），和第 9 輪（主機環境、MariaDB、0 略過）不能直接比較。

## 3. 每個新測試和探測

| 問題 | 測試 / 探測 | 結果 | 失敗原因是不是要抓的問題 |
| --- | --- | --- | --- |
| 1 | `LdapTest::test_login_endpoint_does_not_fall_back_to_synced_password_after_ou_rejection` | **failure**：`The user is authenticated` | **是**。OU 排除讓 `loginViaLdap` 丟出例外，`LoginController` 接著用本機（同步過的）密碼 `Auth::attempt` 成功登入 |
| 1 | `test_finding1_local_non_ldap_user_can_still_log_in` | passed | 對照組，應該通過 |
| 5 | `test_dn_separator_after_even_backslashes_cannot_skip_a_deselected_ou` | **failure**：`true is false` | **是**。`splitDn()` 的 `(?<!\\),` 把 `\\,`（跳脫的反斜線＋分隔符號）當成跳脫的逗號，parent 變成 `DC=example,DC=com` |
| 5 | `test_finding5_odd_backslashes_and_escaped_hex_preserve_parent_ou` | **failure**：`false is true` | **是**。前兩個斷言（`\\\,`、`\2C`）通過，在第三個斷言（`\\,OU=Allowed`）失敗，原因同上 |
| 6 | `LdapTest::test_ou_search_rejects_a_partial_limited_result`（2 個資料組） | **error**：`Call to undefined method phpmock\phpunit\MockObjectProxyReturnTypes100::willReturn()` | **否**，是 mock 寫錯。修正後（4.5）變成 failure：`Failed asserting that exception of type "Exception" is thrown`，原因正確（`findDns()` 忽略 `ldap_parse_result` 的 errcode 3/4） |
| 6 | `LdapWizardTest::test_finding6_…`（3 個資料組） | **error**：同上 | **否**。修正後：time limit、size limit 都失敗（`testStatus` 是 null，預期 `'error'`），原因正確；`complete paginated` 通過（對照組） |
| 7 | `import_locations_rejects_a_truncated_remote_csv_before_importing` | **failure**：`Expected status code 1 but received 0` | **是**。`StorageHelper::readablePath()` 複製遠端檔案時不檢查讀到的長度，截斷的內容照樣匯入 |
| 7 | `finding7_…_abort_location_import`（read failure） | passed | 讀取失敗本來就會中止 |
| 7 | `finding7_…`（unavailable size） | **failure**：`Expected status code 1 but received 0` | **是**。拿不到大小時沒有中止 |
| 3 | `local_destination_prefers_manifest_staged_copy_when_stale_copy_follows` | **skipped**（沒有 mysql client） | 正式結果無法判斷。診斷：failure，`'STAGED'` 和 `'STALE!'` 不同，**原因正確** |
| 3 | `finding3_stale_first_local_and_remote_destinations_restore_staged_and_unrelated_files` | **skipped** | 診斷：**通過**。舊副本放在前面時，後面的暫存副本會蓋掉它，所以這個順序**抓不到**問題 3（見建議 B4） |
| 4 | `validate_only_checks_crc_of_stale_copy_even_when_it_would_be_skipped` | **skipped** | 診斷：failure，`The backup file passed validation`，**原因正確** |
| 4 | `finding4_validate_only_rejects_a_broken_central_directory` | **skipped** | 診斷：通過（現有程式碼已經會拒絕） |
| 4 | `finding4_validate_only_checks_manifest_size_and_sha256` | **skipped** | 診斷：通過（已經會檢查） |
| 4 對照組 | `validate_only_rejects_a_truncated_zip_without_changing_the_database` | **skipped** | 診斷：通過（截斷的 zip 被拒） |
| 4 對照組 | `validate_only_accepts_a_good_archive_and_changes_nothing`（既有） | **skipped** | 診斷：通過（正常 zip 通過） |
| 4（web） | `finding4_web_restore_rejects_a_corrupted_stale_entry_before_wipe` | **failure**：500 | **否**，是 partialMock 造成的 500（`Call to a member function hasBeenBootstrapped() on null`，`Console/Kernel.php:493`，從 `SettingsController.php:1253` 的 validate-only 呼叫進去）。修正 mock 後：`assertSessionHas('error', …)` 失敗，錯誤訊息裡沒有那個 entry，也就是 CRC 損壞沒被發現，**原因正確** |
| 9 | `web_restore_calls_the_safety_backup_with_remote_files_before_wiping`（原版） | **failure**：500 | **否**，同上，是 mock 造成的。修正後：**通過** |
| 9 | 同一個測試（突變版，拿掉 `--with-remote-files`） | failure：500 → `fr9_mutation_red.passed = true` | **假陽性**：原版也 500。修正後的突變版：failure，重新導向到 `/login`（預期 `/admin/backups`）。safety backup 的期望沒有符合，所以真的去 wipe 和還原了，**原因正確** |
| 2 | `fr2_chiseled`、`fr2_regular`、`fr2_prepare_app` | 三個都 `passed: false`（看到 marker） | **是**。`.dockerignore` 沒有排除 `storage/framework/backup-staging`，`COPY . /var/www/html` 會帶進去，`prepare-app.py` 也沒有清掉 |
| 8 | `fr8_valid` | `passed: false`（exit 1：`REMOTE_USER did not match`） | **是**。Apache 回 `200 OK`，`Content-Length: 0`，REMOTE_USER 是空的：chiseled 不處理 `REMOTE_LOGIN_FORWARDED_HEADER`（`startup.sh` 才有） |
| 8 | `fr8_empty`、`fr8_unset` | `passed: true` | 符合預期 |
| 8 | `fr8_invalid`（`Bad Header`） | `passed: false`：20 秒後還在執行（`Running=true`，exit 0），log 裡沒有任何關於這個變數的訊息 | 照實記錄：chiseled 完全忽略這個變數，所以不會因為不合法的值而啟動失敗 |

### 3.1 預期和實際的對照

- 問題 1、5、7：**符合**（失敗，原因正確）。
- 問題 3、4（CRC 損壞的舊副本）：正式結果是**略過**，不符合。診斷時符合，但問題 3 的兩個測試只有一個會失敗。
- 問題 6：正式結果是 **error**（mock 寫錯），不符合；診斷時符合。
- FR-4 對照組：診斷時「正常 zip 通過、截斷 zip 被拒」都通過；另外 central directory 損壞、manifest size/sha 這兩個新測試現在就會通過（程式碼已經會處理）。
- FR-2 三個探測都看到 marker：**符合**。
- FR-8：valid 失敗、unset 和 empty 通過，**符合**；invalid 容器繼續執行。
- FR-9：**不符合**。原版的端點測試沒有通過（500），突變版的 RED 沒有意義。

### 3.2 其他確認

- 測試 image 和 candidate 的 `php -v`、`php -m`、`/usr/bin/php` sha256 都相同（`php_comparison` 三項都是 `equal: true`）。marked 和 mutated 的衍生 image 也有同樣的檢查，都通過。
- 沒有任何容器掛 docker socket：`results-A.json` 的 `commands` 和全部 debug log 裡都沒有 `docker.sock`；診斷用的容器也沒有。
- 清理：這輪的容器、volume、網路、image（含預先 pull 的 base image 和診斷 image）都已刪除，跑了 `docker buildx prune -af` 和 `docker system prune -af --volumes`，最後是 0 個容器、0 個 image、0 個 volume，build cache 0 B。`/tmp/review-*` 沒有殘留，dockerd 已停止。checkout 沒有被改動（`git status` 只有新的結果檔）。

### 3.3 略過的原因

30 個 S3 略過全部是 `The restore tests need the mysql client.`（`tests/Support/S3Compatibility/UsesScratchDatabase.php:83`）。chiseled 的 `mariadb-client-core_client` slice 只有 `/usr/bin/mariadb`；`mariadb-client_dump` 有 `mysqldump` 和 `mariadb-dump`，但沒有 `mysql`。`RestoreFromBackup` 本身在 driver 是 mysql 時會改用 `mariadb`（`RestoreFromBackup.php:238-239`），所以產品沒問題，是測試的輔助函式找不到。`command -v` 的備案在沒有 shell 的 image 裡也不能用。

## 4. 「這次的重點」逐項回答

1. **dockerd**：可以。代理的 port 和上幾輪不同，用當下的 `$HTTPS_PROXY`；worker 重啟後又用新的 port 重新啟動一次。`hello-world` 成功。
2. **`run.sh "$PWD" A`**：原樣執行，第一次就在 `prepare_cache` 失敗。因為 runner 要求 checkout 是乾淨的，我把 `runner.py` 複製到 scratchpad 修改後，用 `python3 -I <副本> "$PWD" A` 執行（被測的 checkout 和工具都沒動）。共 6 個修改，見 5.1。第 6 次 exit 0，`errors: []`，結果寫到 `cloud-verify/review-fixes/results-A.json`。
3. **逐一判斷**：見第 3 節。既有測試（`LdapTest`、`S3Compatibility`、`LdapWizardTest` 全套）**沒有失敗**，但有 24 個既有的 restore 測試被略過。
4. **PHP 身分、socket、清理**：見 3.2，全部符合。

### 4.5 診斷執行（不在 `results-A.json` 裡）

在第 6 次的測試 image 上只加了一層，蓋掉 4 個測試檔，修改見 `cloud-test-output.txt` 第 6 節：

- `UsesScratchDatabase::mysqlClientDirectory()`：`mysql` **或** `mariadb` 可以執行都算。
- 問題 6 的兩個測試：每個 `getFunctionMock(...)` 後面先加 `->expects($this->any())`，再接 `willReturn*`。
- `WebRestoreValidatesBeforeWipeTest` 兩個新測試：`Artisan::partialMock()` 改成 `Mockery::mock(\App\Console\Kernel::class, [app(), app('events')])->makePartial()` 加上 `Artisan::swap()`。

另外建一個內部網路和 MySQL 8.4，跑 `migrate`、`passport:keys` 之後執行，結果如下：

| 執行 | 結果 |
| --- | --- |
| `LdapTest --filter ou_search` | 2 failure（沒有丟出例外），原因正確 |
| `LdapWizardTest --filter finding6` | time/size limit failure（`testStatus` 是 null），complete 通過 |
| `RestoreToRemoteDiskTest` 全部 28 個 | **26 通過，2 failure**（`local_destination_prefers_…`、`validate_only_checks_crc_…`），原因正確；其餘（含 22 個既有的）都通過 |
| `StagingAssumptionsTest` | 3 個都通過 |
| `WebRestoreValidatesBeforeWipeTest` | FR-9 原版**通過**；web 版問題 4 failure，原因正確；既有的 1 個通過 |
| 突變 image 的 FR-9 測試 | failure（重新導向到 `/login`），原因正確；另外被標成 risky：`did not remove its own error handlers` |

## 5. 修改建議

### 5.1 測試工具（`cloud-verify/review-fixes`），依重要性排序

完整的 diff 在 `cloud-test-output.txt` 第 5 節。標 ★ 的是沒改就跑不下去的。

1. ★ **測試 image 沒有 `.env.testing`**：`tests/TestCase.php::guardAgainstMissingEnv()` 會讓每個測試都丟 `RuntimeException`（第 3 次 216/216 都是 error）。**改法**：在 `Dockerfile.test` 加 `COPY --chown=10000:50 .env.testing.example /var/www/html/.env.testing`（和 CI 的 `tests-mysql.yml` 一樣；真正的值由 `-e` 覆蓋）。
2. ★ **`FROM ${CANDIDATE}` 用 image ID 不行**：BuildKit 把 `sha256:<id>` 當成 `docker.io/library/sha256:<id>` 去 pull，會失敗。**改法**：傳 `name:tag@sha256:<id>`。在 containerd image store 上，ID 就是 digest，local build 出來的也可以用，而且一樣固定不變。我的修改是在 `build()` 記錄 `PINNED[id] = tag + '@' + id`，`test_image()` 改用它。
3. ★ **`phpstan/phpstan` 只有 dist、沒有 `source`**：`prepare_cache` 丟出 `locked package lacks source/reference`。**改法**：沒有 source 時，從 `https://api.github.com/repos/<owner>/<repo>/zipball/<ref>` 推出 `https://github.com/<owner>/<repo>.git`。
4. ★ **build 的 `tools` 階段沒有代理 CA**：第 6 輪就需要。**改法**：`cached_dockerfile()` 在 `COPY docker/chiseled/ /chisel-inputs/` 前插入 `COPY --from=proxyca …` 和 `RUN update-ca-certificates`，`build()` 加 `--build-context proxyca=<只含 /root/.ccr/agent-proxy-ca.crt 的目錄>`。candidate 階段是從 `scratch` 組出來的，CA 不會進去。建議 runner 自己偵測 `/root/.ccr/agent-proxy-ca.crt`。
5. ★ **一般的 `Dockerfile`（FR-2 regular）在這裡 build 不起來**：`curl -L -O https://github.com/pear/.../go-pear.phar` 回 403（`curl` 沒加 `-f`，會把錯誤頁存成 phar），composer 用 `COMPOSER_CACHE_DIR=/dev/null` 也會撞到 GitHub dist 的 403。**改法**（只在暫存的 context 裡改，不影響 `.dockerignore` 和 `COPY .`，所以不影響 marker 判斷）：go-pear 改用 `git clone pear/pearweb_phars`（`72aa5f771f`）之後 `COPY`；composer 那行前面加上 `COPY --from=composercache`，並改成 `COMPOSER_CACHE_DIR=/tmp/composer-cache`。
6. **Docker Hub 429**（第 2 次）：共用的出口 IP 每小時只有 100 次，當時剩 16 次。**改法**：開始前用 `docker pull` 依 digest 先抓 `docker/dockerfile:1@…`、`golang@…`、`composer:2.10.3@…`、`ubuntu:24.04@…`、`mysql:8.4`、`ubuntu:24.04`、`composer:latest`，失敗就退避重試。本機有的 image，BuildKit 會直接使用，不會再去 registry。
7. **round A 在所有測試都是 `error` 時仍然 exit 0**（第 3 次就是這樣）。**改法**：round A 也要把 JUnit 的 `error`（相對於 `failure`）、非新測試的失敗或略過，還有 phpunit exit 2，記到 `errors`。至少要求 `*_suite` 裡不是 `finding|…` selector 的測試全部通過、沒有略過。
8. **FR-9 只看突變版是否 RED**：沒有先確認原版通過，所以這次是假陽性。**改法**：先在原本的 test image 跑同一個 filter，要求通過，再看突變版。
9. **`parse_junit` 記錄的訊息是測試名稱**：PHPUnit 的 `<failure>`、`<error>` 沒有 `message` 屬性，text 的第一行是測試名稱。**改法**：略過以 `::<name>` 結尾的那一行，取下一行（我的副本這樣改，`results-A.json` 的 message 是真正的錯誤）。略過的原因沒有寫在 JUnit 裡，建議另外存 phpunit 的 stdout 摘要（`There were N skipped tests` 那段）。
10. **完全不保留指令輸出**，第一次跑遇到設定錯誤時很難除錯。**建議**：在本機（不進結果檔）存一份去掉秘密的 log。我的副本存在 scratchpad 的 `runner-debug.log`。
11. **mirror 放在每次的 `TMP`**：每次重試都要重新 clone 246 個 repo（約 4 分鐘）。建議放在可以重用的快取目錄。
12. 次要：被中斷時（第 5 次 worker 重啟）`finally` 沒機會執行，會留下容器、volume、網路和 8 個 image。建議開始時先清掉帶 `review-fixes.run` label 的舊資源。`tarfile.extractall` 在 Python 3.12 有 DeprecationWarning（加 `filter='data'`）。

### 5.2 測試本身

| # | 檔案 / 測試 | 問題 | 建議改法 |
| --- | --- | --- | --- |
| B1（高） | `tests/Support/S3Compatibility/UsesScratchDatabase.php::mysqlClientDirectory()` | 只找 `mysql`，chiseled 只有 `mariadb`，所以 30 個 restore 測試（含 6 個新的）在規定的 chiseled 環境下全部略過 | `mysql` 或 `mariadb` 可以執行都接受（診斷時這樣改，28 個 restore 測試都跑了）。`shell_exec('command -v …')` 在沒有 shell 的 image 裡也不能用 |
| B2（高） | `LdapTest::test_ou_search_rejects_a_partial_limited_result`、`LdapWizardTest::test_finding6_…` | php-mock-phpunit 的 `getFunctionMock()` 回傳的 proxy 不能直接 `->willReturn()`/`->willReturnCallback()` | 先 `->expects($this->any())`（和檔案裡既有的 `mockLdapLoginFoundAt` 一樣）；`LdapTest` 只有 `ldap_get_entries` 那行要改，Wizard 的 8 個都要改 |
| B3（高） | `WebRestoreValidatesBeforeWipeTest` 兩個新測試 | `Artisan::partialMock()` 沒有經過建構子，沒被 mock 的 `Artisan::call('snipeit:restore', ['--validate-only'…])` 進到真正的 `Kernel::call()`，結果是 500。FR-9 因此無法判斷 | 用 `Mockery::mock(\App\Console\Kernel::class, [app(), app('events')])->makePartial()` 加上 `Artisan::swap($mock)`。修正後原版通過、突變版失敗，web 版問題 4 也因為正確的原因失敗。另外有 risky（`did not remove its own error handlers`），可以順便處理 |
| B4（中） | `RestoreToRemoteDiskTest::finding3_stale_first_local_and_remote_destinations_restore_staged_and_unrelated_files` | 舊副本放在 manifest 副本**前面**，在現在的程式碼下就會通過（後寫的暫存副本蓋掉舊的），抓不到問題 3。真正會失敗的是舊副本放在**後面**的 `local_destination_prefers_…` | 如果想同時涵蓋遠端目的地，改成舊副本放在**後面**，並且 local 和 remote 都要測；或者把它說明成順序無關的回歸測試 |
| B5（低） | `finding4_validate_only_rejects_a_broken_central_directory`、`finding4_validate_only_checks_manifest_size_and_sha256` | 現在的程式碼就會通過，不是 RED | 如果問題 4 指的只是「沒檢查 CRC」，這兩個可以當回歸測試保留，但說明裡不應該期待它們 RED |
| B6（低） | `finding7_…`（read failure） | 現在就會通過 | 同上，可以當對照組 |

### 5.3 給說明檔（`CLOUD_TEST.md`）

- 「預期」寫的是問題 6 的新測試會失敗，但只有在 B2 修正後，才會是因為問題本身而失敗；問題 3、4 只有在 B1 修正後才會執行。建議在第 B 輪之前先修 B1–B3，再重跑一次 A。
- FR-2 regular 的探測在這個環境一定要做 5.1 的第 5 項修改。建議 runner 內建，或把它列為允許的暫時調整。

## 6. 檔案

- `cloud-verify/review-fixes/results-A.json`：第 6 次的正式結果（使用 5.1 修改過的 runner 副本產生）。
- `cloud-test-output.txt`：每次執行的錯誤、最後一次每個失敗、錯誤、略過的訊息、探測的證據、診斷執行的輸出、runner 暫時修改的 diff、診斷用測試修改的 diff。
