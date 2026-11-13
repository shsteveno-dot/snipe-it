# 雲端測試結果：第 12 輪（再跑 review-fixes 第 A 輪，只有測試、預期 RED）

**第 A 輪通過，可以進第 B 輪。**

工具原樣執行（`bash cloud-verify/review-fixes/run.sh "$PWD" A`，沒有任何本機修改），**runner exit 0、`errors` 是空的**。第 11 輪的 T1、T2、W1–W4 都生效：

- 每個預期 RED 的新測試都失敗，而且失敗原因就是它要抓的問題（`matches_expectation` 全部 true）。
- Wizard 問題 6 跑全套（`wizard_suite`）時，time/size 兩個 RED、complete 通過，和單獨跑時一致，第 11 輪的順序相依問題已經解決。
- 問題 3 的 `remote stale last` 是 RED。
- 對照組和既有測試 **0 失敗、0 錯誤、0 略過**。
- FR-2、FR-8、FR-9、`candidate_proxy_ca_absent` 和第 11 輪相同。

被測的 commit 是 `cloud-test` `b0dede21e2`。完整輸出見 `cloud-test-output.txt`。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核；磁碟開始時剩 30 GB |
| Docker | dockerd 29.9.2（root，自己啟動，帶當下的 `HTTP(S)_PROXY=$HTTPS_PROXY` 和 `NO_PROXY`）；`docker run --rm hello-world` 成功 |
| candidate image ID | `sha256:020db144eef9039cd45db6da98154aa6a5af0436ffa7bb070062eea795ef51c8` |
| 測試 image ID | `sha256:ce8eb4f7fe00c6ea1e45fffe48babfbcf46544659ed817488c3bd362c3067192` |
| PHP | `php_comparison`：version、modules、sha256 都相同；`/usr/bin/php` sha256 `7f1ac2fe89d2…a67d7`（和第 10、11 輪相同） |
| 資料庫 | `mysql:8.4`（runner 自己的內部網路） |
| 執行方式 | 單一 process，JUnit |

| 階段 | 耗時 |
| --- | --- |
| 讀說明、啟動 dockerd | 約 3 分鐘 |
| runner（mirror 重用、pull、candidate、測試 image、6 組 phpunit、FR-2、FR-8、FR-9） | 07:05:30–07:21:37 UTC，約 16 分鐘 |
| 分析、清理、寫報告 | 約 5 分鐘 |

## 2. 測試數量（`results-A.json`）

`counts`：passed 194、failure 29、**error 0、skipped 0**（同一個測試在 `*_selected` 和 `*_suite` 各記一次）。

| 執行 | 通過 | 失敗（都是預期 RED） | 錯誤 | 略過 |
| --- | --- | --- | --- | --- |
| `LdapTest` 全套 | 30 | 5 | 0 | 0 |
| `S3Compatibility` 全套 | 96 | 7 | 0 | 0 |
| `LdapWizardTest` 全套 | 55 | 2 | 0 | 0 |
| FR-9 原版 | 1 | 0 | 0 | 0 |
| FR-9 突變版 | 0 | 1 | 0 | 0 |

和第 11 輪比：failure 28 → 29、passed 195 → 194。S3 的 failure 數不變，因為 `remote stale last` 從「錯的對照」變成「正確的 RED」，計數一樣。差別在 wizard：第 11 輪全套是 1 個錯誤失敗（complete），這輪是 2 個正確的 RED（time、size），所以 failure 多 1、passed 少 1。每個執行裡，「existing」和「control」的測試全部通過。

## 3. 每個新測試和探測

| 問題 | 測試 / 探測 | 預期 | 結果 | 原因符合 |
| --- | --- | --- | --- | --- |
| 1 | `test_login_endpoint_does_not_fall_back_to_synced_password_after_ou_rejection` | RED | `The user is authenticated` | 是 |
| 1 | `test_finding1_local_non_ldap_user_can_still_log_in` | 對照 | passed | 是 |
| 5 | `test_dn_separator_after_even_backslashes_cannot_skip_a_deselected_ou` | RED | `true is false` | 是 |
| 5 | `test_finding5_odd_backslashes_and_escaped_hex_preserve_parent_ou` | RED | `false is true` | 是 |
| 6 | `LdapTest::test_ou_search_rejects_a_partial_limited_result`（time、size） | RED | `exception of type "Exception" is thrown` | 是 |
| 6 | `LdapWizardTest::test_finding6_…`（selected **和 suite**） | time/size RED、complete 對照 | time/size：`null matches expected 'error'`；complete passed | **是（第 11 輪 suite 不符，已修好）** |
| 7 | `import_locations_rejects_a_truncated_remote_csv_before_importing` | RED | `Expected status code 1 but received 0` | 是 |
| 7 | `finding7_…`（`read failure control`／`unavailable size`） | 對照／RED | passed／`Expected status code 1 but received 0` | 是 |
| 3 | `local_destination_prefers_manifest_staged_copy_when_stale_copy_follows` | RED | 兩個字串不同（`STAGED` ≠ `STALE!`） | 是 |
| 3 | `finding3_…`（`local stale last`、**`remote stale last`**） | RED | 兩個字串不同 | **是（remote 這輪改成 RED）** |
| 3 | `finding3_…`（`local/remote stale first control`） | 對照 | passed | 是 |
| 4 | `validate_only_checks_crc_of_stale_copy_even_when_it_would_be_skipped` | RED | `The backup file passed validation. Nothing was changed.` | 是 |
| 4 | `finding4_web_restore_rejects_a_corrupted_stale_entry_before_wipe` | RED | `Finding 4: CRC entry was not reported before wipe.` | 是 |
| 4 對照 | broken central directory、manifest size/sha256、truncated zip、good archive | 對照 | 全部 passed | 是 |
| 9 | `web_restore_calls_the_safety_backup_with_remote_files_before_wiping`（s3、`fr9_original`） | 對照 | passed | 是 |
| 9 | 同一個測試（突變版） | RED | `Finding 9: safety backup omitted remote files.`；`fr9_mutation_red.passed = true` | 是 |
| 2 | `fr2_chiseled`、`fr2_regular`、`fr2_prepare_app` | RED | 三個都看到 marker | 是，和第 11 輪相同 |
| 8 | `fr8_valid` | RED | exit 1 | 是，和第 11 輪相同 |
| 8 | `fr8_empty`、`fr8_unset` | 通過 | exit 0 | 是，和第 11 輪相同 |
| 8 | `fr8_invalid` | 照實記錄 | 仍在執行（`running: true`） | 和第 11 輪相同（chiseled 忽略這個變數） |
| — | `candidate_proxy_ca_absent` | 通過 | exit 0 | 是，和第 11 輪相同 |

## 4. 「這次的重點」逐項回答

1. **dockerd**：可以，用當下的 `$HTTPS_PROXY`，`hello-world` 成功。
2. **原樣執行工具**：成功，沒有修改工具。檢查乾淨狀態時，已追蹤的 `results-A.json` 被排除了（W2）；debug log 寫到 `~/.cache/review-fixes/runner-debug-A.log`，不在 checkout 裡（W3）。
3. **確認項目**：runner exit 0，`errors` 是 `[]`。所有預期 RED 的測試都因它要抓的問題失敗；對照組和既有測試 0 失敗、0 略過（`skipped_summary` 全部空白）；FR-2、FR-8、FR-9、`candidate_proxy_ca_absent` 和上一輪一樣。測試 image 和 candidate 的 `php -v`、`php -m`、`/usr/bin/php` sha256 相同。`results-A.json` 和 debug log 都沒有 `docker.sock`。
4. **清理**：runner 的容器、volume、網路都移除了，`/tmp/review-*` 沒有殘留。之後我刪掉所有 image（含 base image 和 `hello-world`），執行 `docker buildx prune -af`，`docker system df` 全部是 0，並停掉 dockerd。`~/.cache/review-fixes/mirrors` 是工具設計上要重用的快取，所以留著。

## 5. 修改建議

這輪沒有不符合的地方，不需要修改測試或工具。只有一點小觀察（低優先，不影響第 B 輪）：

- **工具（低）**：runner 只移除它自己加上 label 的資源。它 pull 的 base image（`ubuntu`、`golang`、`composer`、`mysql`、`docker/dockerfile`）和 build cache 會留在主機上，README 也寫明不做全主機清理。如果希望 runner 執行完就符合「這輪的 image 都清掉」，可以在 `CLOUD_TEST.md` 的清理步驟明寫「`docker image prune -af` + `docker buildx prune -af`」。這一輪就是這樣手動清掉的。
