# 雲端測試結果：第 14 輪（review-fixes 第 B 輪最終確認）

**第 B 輪通過。**

工具和程式碼都沒有修改，原樣執行 `bash cloud-verify/review-fixes/run.sh "$PWD" B`。結果是 runner exit 0，`errors` 是空的，0 個非預期失敗、0 錯誤、0 略過、0 incomplete。第 13 輪失敗的 2 個 `RestoreToRemoteDiskTest` 測試現在都通過了。FR-2、FR-8、FR-9、`candidate_proxy_ca_absent` 和 input lock 的結果都和第 13 輪相同。

被測的 commit 是 `cloud-test` `cd8b1a6197`，包含 `d0a80b2ce3` 和 `6b68a6f131`。完整輸出見 `cloud-test-output.txt`。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核，磁碟剩約 30 GB。這是全新容器，沒有 `~/.cache/review-fixes`，由 runner 重建 |
| Docker | dockerd 29.9.2，用 root 自己啟動，帶當下的 `HTTP(S)_PROXY=$HTTPS_PROXY`。`docker run --rm hello-world` 成功 |
| candidate image ID | `sha256:23accb37ba66eefa7679b14f6d5de75fa232bf45338fa1e2f6cd62505b9639b7` |
| 測試 image ID | `sha256:8facabfde499b7e9c632dc8b4685d4f597a41f9612e14cb613c548923f0072dd` |
| PHP | `php_comparison` 的 version、modules、sha256 都相同。`/usr/bin/php` 的 sha256 是 `7f1ac2fe89d2…a67d7`，和第 10–13 輪相同 |
| 資料庫 | `mysql:8.4`，在 runner 自己的內部網路裡 |
| 執行方式 | 單一 process，JUnit |

image ID 和第 13 輪不同，因為 label 帶了不同的 run id，`/usr/bin/php` 本身沒有變。

| 階段 | 耗時 |
| --- | --- |
| 讀說明、啟動 dockerd | 約 3 分鐘 |
| runner（重建 mirror、pull、candidate、測試 image、Go 測試、6 組 phpunit、FR-2、FR-8、FR-9） | 09:05–09:23 UTC，約 18 分鐘 |
| 分析、清理、寫報告 | 約 5 分鐘 |

## 2. 測試數量（`results-B.json`）

`counts`：passed 222、failure 1。這 1 個 failure 是預期會失敗的 FR-9 突變版。error 0、skipped 0。

| 執行 | 通過 | 失敗 | 第 13 輪 |
| --- | --- | --- | --- |
| `LdapTest` selected / 全套 | 7 / 35 | 0 / 0 | 相同 |
| `S3Compatibility` selected / 全套 | **16 / 103** | **0 / 0** | 15 / 101，失敗 1 / 2 |
| `LdapWizardTest` selected / 全套 | 3 / 57 | 0 / 0 | 相同 |
| FR-9 原版 | 1 | 0 | 相同 |
| FR-9 突變版 | 0 | 1（預期） | 相同 |

phpunit 加上 `--display-incomplete` 之後，6 組都是 `OK (...)`，沒有 incomplete。

## 3. 失敗或可疑項目

無。第 13 輪失敗的 2 個測試現在的狀態：

- `validate_only_checks_crc_of_stale_copy_even_when_it_would_be_skipped`：在 `s3_selected` 和 `s3_suite` 都通過，`matches_expectation: true`。
- `validate_only_rejects_a_corrupted_database_dump`：在 `s3_suite` 通過。

`d0a80b2ce3` 的 diff 和第 13 輪建議的完全相同：`Artisan::output()` 只讀一次，另一個測試只檢查訊息裡有 `db-dumps/mysql-test.sql`。

## 4. 「這次的重點」逐項回答

1. **dockerd**：可以啟動，用當下的 `$HTTPS_PROXY`，`hello-world` 成功。
2. **原樣執行**：工具、程式碼和 Dockerfile 都沒有修改。跑完後 `git status` 只有 `results-B.json` 有變動。
3. **確認項目**：
   - runner exit **0**，`errors` 是 **`[]`**。
   - 除了預期的 FR-9 突變版，**0 失敗**；`skipped_summary` 全部是空的，所以 **0 略過**。
   - FR-2：`fr2_chiseled`、`fr2_regular` 都 exit 0，`fr2_prepare_app` 的 `marker_directory_present: false`。三個探測都看不到 marker，和第 13 輪相同。
   - FR-8：`fr8_valid`、`fr8_empty`、`fr8_unset` 都 exit 0；`fr8_invalid` 容器啟動失敗（`running: false`、exit 1），這是預期結果；`fr8_go_unit` exit 0。全部和第 13 輪相同。
   - FR-9：原版 exit 0。突變版 exit 1，原因是 `Finding 9: safety backup omitted remote files.`，`fr9_mutation_red.passed = true`。和第 13 輪相同。
   - `candidate_proxy_ca_absent`：通過，和第 13 輪相同。
   - input lock：`chiseled_input_locks` 是 `passed: true`、exit 0，和第 13 輪相同。
   - 逐一比較 `probes`，只有 `s3_selected_exit` 和 `s3_suite_exit` 不同，都從 1 變成 0。
   - `results-B.json` 和 debug log 都沒有出現 `docker.sock`。輸出檔裡也沒有代理位址或密碼，runner 已經把這些遮蔽了。
4. **沒有重跑第 13 輪第 5 步的額外測試**：照指示略過。
5. **清理**：runner 自己移除了這輪的容器、volume、網路和 image，`/tmp/review-*` 沒有殘留。之後執行 `docker image prune -af` 和 `docker buildx prune -af`，`docker system df` 全部是 0。dockerd 已停止。`~/.cache/review-fixes/mirrors` 是工具設計上要重複使用的快取，所以保留。

## 5. 修改建議

### 測試工具（cloud-verify/review-fixes）

沒有必修項目。`6b68a6f131` 的兩個改動都有作用：
- `errors='replace'`：這輪沒有遇到解碼錯誤。
- `--display-incomplete`：已經出現在每組 phpunit 的參數裡。

### 測試本身

沒有必修項目。

（這輪沒有涵蓋：第 13 輪在 chiseled 裡跑整個 `tests/Unit` 時，有 8 個測試因為沒有 `intl` 而失敗。這是已知的環境差異，照說明另外處理。）
