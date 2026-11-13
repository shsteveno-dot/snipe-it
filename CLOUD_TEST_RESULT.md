# 雲端測試結果：第 11 輪（重跑 review-fixes 第 A 輪，只有測試、預期 RED）

**總結：工具這次不需要任何本機修改就跑完了（原樣執行 `run.sh "$PWD" A`）。runner exit 1，`errors` 有 5 筆，所以還不能寫「第 A 輪通過」。** 這 5 筆都來自**測試本身**的兩個問題，不是工具或環境的問題：

1. **問題 3 的 `remote stale last control` 不是對照組，而是 RED**：遠端目的地一樣被舊副本蓋掉（`'STAGED'` → `'STALE!'`），失敗原因就是問題 3。測試的標籤（和 runner 的 `round_a_expectation`）要改成 RED。
2. **問題 6 的 `LdapWizardTest::test_finding6_…` 在全套裡會依執行順序翻轉**：單獨跑（`wizard_selected`）時 time/size limit 失敗、complete 通過，原因正確；跑全套時前面的 `test_step2*` 已經呼叫過真正的 `ldap_*`，php-mock 的函式 mock 之後就不會生效，結果反過來變成 time/size「通過」（原因錯）、complete 失敗。我在 scratchpad 做了診斷（第 4.2 節），在 `setUpBeforeClass()` 用 `defineFunctionMock()` 預先定義就能修好。

其他項目都符合預期：問題 1、3（local）、4、5、6（LdapTest）、7 的 RED 都是因為它們要抓的問題；對照組都通過；既有測試 **0 失敗、0 略過**（S3 103 個測試全部執行，restore 測試這次有跑）；FR-2 三個探測、FR-8 四種情況、FR-9（原版通過、突變版因 `Finding 9: safety backup omitted remote files.` 失敗）、`candidate_proxy_ca_absent` 都符合。

分支 `cloud-test` `82a82e4`。完整輸出見 `cloud-test-output.txt`。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核；磁碟開始時剩 30 GB |
| Docker | dockerd 29.9.2（root，自己啟動，帶 `HTTP(S)_PROXY=$HTTPS_PROXY` 和 sandbox 的 `NO_PROXY`）；`docker run --rm hello-world` 成功 |
| 被測的 commit | `82a82e435b`（`cloud-test`，含 `review-fixes` `620b5a6655`） |
| candidate image ID | `sha256:3bf2a7d425fb12f2ec9cafbaf698f52cc5d4bd30a4a897a728c39d1d85799284` |
| 測試 image ID | `sha256:18b80252baa4f84b985d267ff28671534fdcee463bb245de87f6520a2552dcce` |
| PHP | 兩個 image 同一個 `/usr/bin/php`：`php -v`、`php -m` 相同，sha256 `7f1ac2fe89d267364311651c0e7e6651d32ea006c9a701c0cab68eb2394a67d7`（和第 10 輪相同）。marked、mutated 衍生 image 也通過同樣檢查 |
| 資料庫 | `mysql:8.4`（runner 自己的內部網路） |
| 執行方式 | 單一 process，JUnit |

| 階段 | 耗時 |
| --- | --- |
| 讀說明和工具、啟動 dockerd | 約 4 分鐘 |
| runner（`git clone --mirror` 全部套件、pull base image、candidate、測試 image、6 組 phpunit、FR-2、FR-8、FR-9） | 06:32–06:51，約 19 分鐘 |
| 診斷執行（重用 mirror 和 build cache） | 約 3 分鐘 |
| 分析、清理、寫報告 | 約 15 分鐘 |

過程中 Docker Hub 對 `ubuntu:24.04` 回了一次 429，`pull_with_backoff` 重試後成功（第 10 輪建議 6 有效）。

## 2. 測試數量（`results-A.json`）

`counts`：passed 195、failure 28、**error 0、skipped 0**（同一個測試在 `*_selected` 和 `*_suite` 各記一次）。

| 執行 | tests | 通過 | 失敗 | 錯誤 | 略過 |
| --- | --- | --- | --- | --- | --- |
| `LdapTest` 全套 | 35 | 30 | 5 | 0 | 0 |
| `S3Compatibility` 全套 | 103 | 96 | 7 | 0 | 0 |
| `LdapWizardTest` 全套 | 57 | 56 | 1 | 0 | 0 |
| FR-9 原版 | 1 | 1 | 0 | 0 | 0 |
| FR-9 突變版 | 1 | 0 | 1 | 0 | 0 |

和第 10 輪比：error 10 → 0（B2、B3 修好了）、skipped 37 → 0（B1 修好了，`mariadb` 可以用），S3 測試數 100 → 103（問題 3 改成 4 個資料組）。**既有（`existing`）測試全部通過。**

## 3. 每個新測試和探測

| 問題 | 測試 / 探測 | 預期 | 結果 | 原因是不是要抓的問題 |
| --- | --- | --- | --- | --- |
| 1 | `test_login_endpoint_does_not_fall_back_to_synced_password_after_ou_rejection` | RED | failure：`The user is authenticated` | **是** |
| 1 | `test_finding1_local_non_ldap_user_can_still_log_in` | 對照 | passed | 符合 |
| 5 | `test_dn_separator_after_even_backslashes_cannot_skip_a_deselected_ou` | RED | failure：`true is false` | **是** |
| 5 | `test_finding5_odd_backslashes_and_escaped_hex_preserve_parent_ou` | RED | failure：`false is true` | **是** |
| 6 | `LdapTest::test_ou_search_rejects_a_partial_limited_result`（time、size） | RED | failure：`exception of type "Exception" is thrown` | **是**（`findDns()` 忽略 errcode 3/4） |
| 6 | `LdapWizardTest::test_finding6_…`（`wizard_selected`） | time/size RED、complete 對照 | time/size failure：`null matches expected 'error'`；complete passed | **是** |
| 6 | 同上（`wizard_suite`） | 同上 | **time/size passed、complete failure**（`assertSee('partial')` 失敗） | **否**，順序相依的 mock 失效，見 4.2 |
| 7 | `import_locations_rejects_a_truncated_remote_csv_before_importing` | RED | failure：`Expected status code 1 but received 0` | **是** |
| 7 | `finding7_…`（`read failure control`） | 對照 | passed | 符合 |
| 7 | `finding7_…`（`unavailable size`） | RED | failure：同上 | **是** |
| 3 | `local_destination_prefers_manifest_staged_copy_when_stale_copy_follows` | RED | failure：`'STAGED'` ≠ `'STALE!'` | **是** |
| 3 | `finding3_…`（`local stale last`） | RED | failure：同上 | **是** |
| 3 | `finding3_…`（`remote stale last control`） | 對照 | **failure**：`'STAGED'` ≠ `'STALE!'`（`RestoreToRemoteDiskTest.php:649`） | **是，問題 3 本身**；標籤錯了，見 4.1 |
| 3 | `finding3_…`（`local stale first control`、`remote stale first control`） | 對照 | passed | 符合（後寫的暫存副本蓋掉舊的） |
| 4 | `validate_only_checks_crc_of_stale_copy_even_when_it_would_be_skipped` | RED | failure：`The backup file passed validation. Nothing was changed.` | **是** |
| 4 | `finding4_web_restore_rejects_a_corrupted_stale_entry_before_wipe` | RED | failure：`Finding 4: CRC entry was not reported before wipe.` | **是**（第 10 輪的 500 沒了） |
| 4 對照 | `finding4_validate_only_rejects_a_broken_central_directory`、`finding4_validate_only_checks_manifest_size_and_sha256`、`validate_only_rejects_a_truncated_zip_without_changing_the_database`、既有的 `validate_only_accepts_a_good_archive_and_changes_nothing` | 對照 | 全部 passed | 符合（正常 zip 通過、截斷 zip 被拒） |
| 9 | `web_restore_calls_the_safety_backup_with_remote_files_before_wiping`（`s3_*` 和 `fr9_original`） | 對照 | passed | 符合 |
| 9 | 同一個測試（突變版，拿掉 `--with-remote-files`） | RED | failure：`Finding 9: safety backup omitted remote files.` | **是**；`fr9_mutation_red.passed = true` |
| 2 | `fr2_chiseled`、`fr2_regular`、`fr2_prepare_app` | RED | 三個都看到 marker（exit 1／`marker_directory_present: true`） | **是** |
| 8 | `fr8_valid` | RED | exit 1（REMOTE_USER 沒有對上） | **是** |
| 8 | `fr8_empty`、`fr8_unset` | 通過 | exit 0 | 符合 |
| 8 | `fr8_invalid` | 照實記錄 | 20 秒後仍在執行（`running: true`，exit 0） | 和第 10 輪一樣：chiseled 完全忽略這個變數 |
| — | `candidate_proxy_ca_absent` | 通過 | exit 0 | 符合：代理 CA 沒進 candidate |

## 4. 「這次的重點」逐項回答

1. **dockerd**：可以，用當下的 `$HTTPS_PROXY`（port 和上一輪不同），`hello-world` 成功。
2. **原樣執行工具**：**成功，不需要任何本機修改**。第 10 輪建議的 12 項都生效（`.env.testing`、`name:tag@digest`、phpstan 推導 source、代理 CA 自動偵測、regular Dockerfile 調整、預先 pull 並重試、JUnit 錯誤訊息、debug log、mirror 快取、label 清理）。
3. **逐一判斷**：見第 3 節。兩個不符合預期的地方都是測試本身的問題（4.1、4.2）。既有測試全部通過、**0 略過**。
4. **exit code 和 `errors`**：**正確反映結果**。exit 1，`errors` 剛好是那 5 筆不符合預期的結果（s3 兩次 + wizard_suite 三次），沒有多報也沒有漏報；其他項目的 `matches_expectation` 都是 true。
5. **清理**：容器、volume、網路、image（含 base image）、`docker buildx prune -af` 都清掉了，`docker system df` 全部 0；`/tmp/review-*` 沒有殘留；dockerd 已停止。沒有任何容器掛 docker socket（`results-A.json` 和 debug log 都沒有 `docker.sock`）。`~/.cache/review-fixes/mirrors` 留著（工具設計上要重用的快取）。

### 4.1 問題 3 的遠端目的地也會被舊副本蓋掉

`RestoreFromBackup::skipStaleLocalCopies()` 只在 `remoteObjectExists()` 為 true 時跳過非暫存的舊副本，但這是在**寫入之前**判斷的。測試的遠端 disk 一開始是空的，所以舊副本不會被跳過；舊副本在 zip 裡排在暫存副本**後面**時，就會在之後寫入、蓋掉 `STAGED`。這和 local 的情況是同一個問題（問題 3），測試把它當對照組是錯的。舊副本在前面時，後寫的暫存副本會蓋回來，所以兩個 `stale first` 對照組通過。

### 4.2 Wizard 問題 6 的順序相依（診斷，不在 `results-A.json` 裡）

php-mock 的限制：namespace 函式必須在該 namespace 第一次呼叫那個沒加限定名稱的函式**之前**定義，否則 PHP 會把呼叫點解析到全域函式並快取起來。`LdapWizardTest` 裡前面的 `test_step2*` 會從 `App\Livewire\LdapSettings` 呼叫真正的 `ldap_connect` 等函式，之後 finding6 的 `getFunctionMock()` 就沒有效果，真的去連 `ldap://127.0.0.1`，結果是 `testStatus = 'error'`。

我用 scratchpad 的 runner 副本（只改結果檔和 log 的路徑，並在 migrate 之後插入幾個 phpunit 執行；`ROOT` 指向一個乾淨的 `82a82e4` worktree，因為剛跑完時 checkout 裡已追蹤的 `results-A.json` 被改寫，不算乾淨）做了診斷，同樣的 chiseled candidate/測試 image：

| 執行 | time limit | size limit | complete paginated |
| --- | --- | --- | --- |
| `--filter finding6` | failure（正確） | failure（正確） | passed |
| `--filter 'test_step1\|finding6'` | failure | failure | passed |
| `--filter 'test_step2\|finding6'` | **passed（錯）** | **passed（錯）** | **failure** |
| 全套，掛載修正版測試檔 | failure（正確） | failure（正確） | passed；其他 55 個全部通過 |
| 只跑 finding6，修正版 | failure | failure | passed |

修正版的 diff 在 `cloud-test-output.txt` 第 4 節（建議 T1）。

## 5. 修改建議

### 5.1 測試本身（依重要性排序；都是我們新增的測試）

| # | 檔案 / 測試 | 問題 | 建議改法 |
| --- | --- | --- | --- |
| T1（高） | `tests/Feature/Settings/LdapWizardTest.php::test_finding6_ou_search_preserves_selection_and_reports_incomplete_results` | 在全套裡 mock 失效（4.2），time/size 會因為真的連線失敗而「通過」，第 B 輪修好之後也一樣會假綠；complete 在全套裡會失敗 | 在類別加上 `setUpBeforeClass()`，對 `App\Livewire` 的 `ldap_connect`、`ldap_set_option`、`ldap_bind`、`ldap_unbind` 和 `App\Models` 的 `ldap_search`、`ldap_parse_result`、`ldap_get_entries` 呼叫 `self::defineFunctionMock()`（diff 見 `cloud-test-output.txt`；診斷時全套驗證過）。也建議檢查 `LdapTest` 是否有同樣的風險（這次 `LdapTest` 全套結果和單獨跑一致） |
| T2（高） | `tests/Feature/S3Compatibility/RestoreToRemoteDiskTest.php::finding3ArchiveOrders` 的 `remote stale last control` | 遠端目的地同樣受問題 3 影響，這筆資料組會 RED（4.1） | 改名為 `remote stale last`（不是 control），docblock 改成「local 和 remote stale-last 都是 RED」；同時改 runner（W1） |

### 5.2 測試工具（`cloud-verify/review-fixes`）

| # | 地方 | 問題 | 建議改法 |
| --- | --- | --- | --- |
| W1（高，配合 T2） | `runner.py::round_a_expectation()` | `finding3_restore_destination_prefers_staged` 只有 `local stale last` 被當成 RED | 條件改成 `'stale last' in name and 'control' not in name`（T2 把 control 從名稱拿掉之後，local、remote 兩個都會是 RED） |
| W2（中） | `runner.py::main()` 開頭的乾淨檢查 + `RESULT` | `results-A.json` 是已追蹤的檔案，跑完一次之後 checkout 就不乾淨，第二次執行（例如重試）會直接 `checkout must be clean before starting`。我這次就是因此改用 worktree 做診斷 | 檢查時排除 `cloud-verify/review-fixes/results-*.json`（`git status --porcelain --untracked-files=no -- . ':!cloud-verify/review-fixes/results-*.json'`），或先寫到暫存檔、最後才搬過去並說明 |
| W3（低） | `DEBUG_LOG` | debug log 寫在 checkout 裡（`cloud-verify/review-fixes/runner-debug-A.log`），沒有被 `.gitignore`，容易被誤 commit | 放到 `CACHE_ROOT` 或加進 `.gitignore` |
| W4（低） | `redact_output()` | 只要整行有 `password` 就整行換掉，所以所有 `docker run … -e DB_PASSWORD=…` 的指令行（包括每次 phpunit）在 debug log 裡都變成 `[redacted sensitive line]`，看不出是哪一次執行 | 只遮蔽值（`(?i)(password|secret|…)=\S+` → `\1=[redacted]`），保留其餘參數 |
| W5（低） | `Dockerfile.test` | BuildKit 警告 `InvalidDefaultArgInFrom`（`ARG CANDIDATE` 沒有預設值） | 可以忽略；或加 `# check=skip=InvalidDefaultArgInFrom` |

### 5.3 說明檔

- `CLOUD_TEST.md` 對問題 3 的預期可以寫清楚：遠端目的地在舊副本排在後面時也是 RED。
