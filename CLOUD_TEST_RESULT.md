# 雲端測試結果：第 13 輪（review-fixes 第 B 輪，修正程式碼，預期 GREEN）

**第 B 輪未通過。** 工具原樣執行（`bash cloud-verify/review-fixes/run.sh "$PWD" B`，沒有修改工具或程式碼），**runner exit 1**，`errors` 有 4 項，都來自 `RestoreToRemoteDiskTest` 的 2 個測試：

1. `validate_only_checks_crc_of_stale_copy_even_when_it_would_be_skipped`（問題 4 的新測試）：**是測試的錯**。程式碼已經正確拒絕；測試呼叫了兩次 `Artisan::output()`，第二次拿到空字串。
2. `validate_only_rejects_a_corrupted_database_dump`（既有測試）：**是修正改變了錯誤訊息**。新加的全 zip CRC 檢查比較早攔下損壞的 SQL dump，印出 `Archive integrity check failed for entry: db-dumps/mysql-test.sql`，不是測試要的 `Could not read the complete database dump: …`。restore 還是拒絕了，資料庫也沒變。

在同一個測試 image 裡，把這兩個測試照下面第 5 節的 diff 改好後掛載進去跑（暫時副本，沒有 commit），`RestoreToRemoteDiskTest` 31/31、`S3Compatibility` 103/103 全部通過。

其他項目都符合：所有 LDAP、Wizard 測試和其他 S3 測試都通過，0 略過；FR-2 三個探測都**看不到** marker；FR-8 的 valid、empty、unset、invalid 和 Go 單元測試都通過；FR-9 原版通過、突變版因為指定的 assertion 失敗；`candidate_proxy_ca_absent` 通過；input lock 是最新的。

被測的 commit 是 `cloud-test` `bfa60db91d`。完整輸出見 `cloud-test-output.txt`。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核；磁碟開始時剩 30 GB；全新容器，`~/.cache/review-fixes` mirror 不存在，由 runner 重建 |
| Docker | dockerd 29.9.2（root，自己啟動，帶當下的 `HTTP(S)_PROXY=$HTTPS_PROXY` 和 `NO_PROXY`）；`docker run --rm hello-world` 成功 |
| candidate image ID | `sha256:21261e78453cae1148cdcd0b736001d70c704c509bfe09c35c82070aa899038b` |
| 測試 image ID | `sha256:7fda9a570eca66362ca5f4182a4404a9efa85316a0ce171d047d86f4342d858b` |
| PHP | 8.3.6；`php_comparison` 的 version、modules、sha256 都相同；`/usr/bin/php` sha256 `7f1ac2fe89d2…a67d7`（和第 10–12 輪相同） |
| 資料庫 | `mysql:8.4`（runner 自己的內部網路） |
| 執行方式 | 單一 process，JUnit |

| 階段 | 耗時 |
| --- | --- |
| 讀說明、啟動 dockerd | 約 3 分鐘 |
| runner（重建 mirror、pull、candidate、測試 image、Go 測試、6 組 phpunit、FR-2、FR-8、FR-9） | 08:19–08:37 UTC，約 18 分鐘 |
| 額外測試（第 4 項：重建 image，Settings／Importing／Importer／Unit／修正版 S3；Unit 因為工具副本的 UTF-8 問題重跑一次；再跑一次編碼探測） | 08:39–08:58 UTC，約 19 分鐘 |
| 分析、清理、寫報告 | 約 8 分鐘 |

## 2. 測試數量（`results-B.json`）

`counts`：passed 219、failure 4（含預期失敗的 FR-9 突變版 1 個）、**error 0、skipped 0**。

| 執行 | 通過 | 失敗 | 錯誤 | 略過 |
| --- | --- | --- | --- | --- |
| `LdapTest` selected / 全套 | 7 / 35 | 0 / 0 | 0 | 0 |
| `S3Compatibility` selected / 全套 | 15 / 101 | **1 / 2** | 0 | 0 |
| `LdapWizardTest` selected / 全套 | 3 / 57 | 0 / 0 | 0 | 0 |
| FR-9 原版 | 1 | 0 | 0 | 0 |
| FR-9 突變版 | 0 | 1（預期） | 0 | 0 |

和第 12 輪（第 A 輪）比：第 A 輪 29 個 failure 全部是預期的 RED。這輪除了上面 2 個測試以外全部轉綠，所以第 B 輪的修正大致生效。

## 3. 失敗分析

### 3.1 `validate_only_checks_crc_of_stale_copy_even_when_it_would_be_skipped`（新測試，問題 4）—— 測試的錯

```
Failed asserting that '' [ASCII](length: 0) contains "storage/private_uploads/eula-pdfs/rst4aeeab.pdf"
RestoreToRemoteDiskTest.php:746
```

- 第一個 assertion `assertNotSame(0, $exit, Artisan::output())` 已經通過，表示 restore 有拒絕。
- 第二個 assertion 又呼叫一次 `Artisan::output()`。Laravel 的 `Application::output()` 會呼叫 `BufferedOutput::fetch()`，而 `fetch()` 會把緩衝清空，所以第二次一定是空字串。第 A 輪 exit 是 0，測試在第一個 assertion 就失敗了，所以當時沒有發現這個問題。
- 修正程式碼的錯誤訊息是 `Archive integrity check failed for entry: <name>`，會帶出路徑。把輸出存到變數後，這個測試就通過了（見第 5 節）。

### 3.2 `validate_only_rejects_a_corrupted_database_dump`（既有測試）—— 修正後訊息不同

```
Failed asserting that 'Archive integrity check failed for entry: db-dumps/mysql-test.sql\n'
contains "Could not read the complete database dump: db-dumps/mysql-test.sql"
RestoreToRemoteDiskTest.php:454
```

- `0890c9f`（Validate every archive entry before restore）在 `--validate-only` 一開始就逐一讀取每個 entry，檢查 CRC 和大小。損壞的 DEFLATE SQL dump 在這裡就被攔下，所以後面 `RestoreFromBackup.php:562` 的 `Could not read the complete database dump` 不會再執行。
- 行為是對的：exit ≠ 0，`probeValues()` 還是 `[99]`（修正版測試三個 assertion 都通過）。這不是安全或資料問題，只是使用者看到的訊息變得比較籠統。
- 這個測試只在 `s3_suite` 跑（`selected` 的 filter 沒選到），runner 把它歸類為 `existing`。

## 4. 「這次的重點」逐項回答

1. **dockerd**：可以，用當下的 `$HTTPS_PROXY`，`hello-world` 成功。
2. **原樣執行**：沒有修改工具或程式碼。runner 自己重建了全部 Composer mirror 和 `pearweb_phars`。
3. **確認項目**：
   - runner exit **1**、`errors` **不是空的**（見第 3 節）。
   - 新測試和對照組：除了 3.1 以外全部通過。既有的 `LdapTest`、`LdapWizardTest` 全部通過；`S3Compatibility` 除了 3.2 以外全部通過。**0 略過**（`skipped_summary` 全部是空的）。
   - FR-2：`fr2_chiseled`、`fr2_regular` exit 0；`fr2_prepare_app` 的 `marker_directory_present: false`。三個都**看不到** marker。
   - FR-8：`fr8_valid` exit 0（`REMOTE_USER` 正確）；`fr8_empty`、`fr8_unset` exit 0（沒有對應）；`fr8_invalid` 容器啟動失敗（`running: false`、exit 1）；`fr8_go_unit`（`TestForwardedHeaderConfig` 在 candidate 衍生的 image 裡跑）exit 0。
   - FR-9：原版通過；突變版因為 `Finding 9: safety backup omitted remote files.` 失敗，`fr9_mutation_red.passed = true`。
   - `candidate_proxy_ca_absent` 通過。
   - input lock：`chiseled_input_locks` `passed: true`、exit 0，lock 是最新的。
   - `results-B.json` 和 debug log 都沒有 `docker.sock`。
4. **失敗判斷**：3.1 是測試的錯；3.2 是修正改變了訊息，建議改測試（也可以改程式碼），兩種做法見第 5 節。
5. **其他相關的既有測試**：用同一個 commit 和同樣的步驟重建 candidate 和測試 image，`/usr/bin/php` sha256 相同（`7f1ac2fe…a67d7`）。runner 結束時會刪掉 image，所以 image ID 不同（label 帶了不同的 run id）。使用的 runner 副本放在 scratchpad，diff 附在 output 裡，沒有 commit。

   | 路徑 | 結果 |
   | --- | --- |
   | `tests/Feature/Settings` | 171 個：166 通過、**5 incomplete**、0 失敗 |
   | `tests/Feature/Importing` | 239 個全部通過 |
   | `tests/Feature/Importer` | 5 個全部通過 |
   | `tests/Unit` | 736 個：728 通過、**8 失敗**、0 略過 |

   - 5 個 incomplete 都是程式碼裡寫死的 `markTestIncomplete`（`BrandingSettingsTest` favicon ×2、`PostRestoreDataLossGuardsTest` ×2、`ShowSetUpPageTest` TLS ×1），和這輪修正無關。
   - Unit 的 8 個失敗：`CustomFieldTest::test_db_name_*`（chinese、japanese、korean、non_latin_euro、turkish、arabic）和 `Importer\ImporterEncodingTest` 的 `non_utf8`、`gbk`。這輪沒有改這些測試或它們測的程式碼（`git diff 87fe5250a6..bfa60db` 只改到 `tests/Unit/LdapTest.php`）。探測結果：chiseled runtime **沒有載入 `intl`**（`extension_loaded('intl') = false`），所以 `CustomField::convertUnicodeDbSlug()` 走了沒有 `transliterator_transliterate` 的 fallback。上游一般的 `Dockerfile` 也沒有裝 `php8.3-intl`，CI（`tests-mysql.yml`）則有。在這個 image 裡直接呼叫 glibc iconv 轉 GBK、CP1252 都正常，`gconv` 模組都在；`ImporterEncodingTest` 的失敗應該是在偵測編碼那一步（Onnov／`mb_detect_encoding`），我沒有再往下追。這屬於「在 chiseled／正式 runtime 裡跑整個 Unit」才會出現的環境差異，**不是這輪修正造成的**。
   - DNS／`ExternalUrl` 相關的已知失敗沒有出現在這幾個路徑。
6. **清理**：runner 和我的額外執行都移除了自己的容器、volume、網路和 image，`/tmp/review-*` 沒有殘留。之後執行 `docker image prune -af`，刪掉剩下的 base image，再 `docker buildx prune -af`。`docker system df` 全部是 0，dockerd 已停止。`~/.cache/review-fixes/mirrors` 是工具設計上要重用的快取，所以留著。

## 5. 修改建議

### 測試本身（依重要性排序）

1. **（我們的改動，必修）`RestoreToRemoteDiskTest::validate_only_checks_crc_of_stale_copy_even_when_it_would_be_skipped`**：`Artisan::output()` 只能讀一次。改成先存到變數：

   ```diff
            $exit = Artisan::call('snipeit:restore', ['filename' => $zip, '--validate-only' => true, '--no-progress' => true]);
   +        $output = Artisan::output();

   -        $this->assertNotSame(0, $exit, Artisan::output());
   -        $this->assertStringContainsString($path, Artisan::output());
   +        $this->assertNotSame(0, $exit, $output);
   +        $this->assertStringContainsString($path, $output);
   ```

   修正後在 chiseled 測試 image 裡通過。

2. **（我們的改動，必修，二擇一）`validate_only_rejects_a_corrupted_database_dump` 和新的 CRC 檢查衝突**：
   - **A（建議）改測試**：只檢查 entry 名稱，訊息改由新的檢查負責：
     ```diff
     -        $this->assertStringContainsString('Could not read the complete database dump: db-dumps/mysql-test.sql', $output);
     +        $this->assertStringContainsString('db-dumps/mysql-test.sql', $output);
     ```
     修正後在 chiseled 測試 image 裡通過。也可以改成檢查 `Archive integrity check failed for entry: db-dumps/mysql-test.sql`，訊息會更明確。
   - **B 改程式碼**：如果想保留比較好懂的 SQL 訊息，就在 `RestoreFromBackup` 的 CRC 迴圈裡，遇到 `db-dumps/*.sql` 時印 `Could not read the complete database dump: <name>`。這樣 `RestoreFromBackup.php:562` 那段大概就不會再走到了。

   不管選哪一個，都要把 `RestoreFromBackup.php:562` 的檢查留著或註明為什麼還需要，避免之後被當成不會執行的程式碼刪掉。

3. **（環境差異，不是這輪造成的）在 chiseled 裡跑 Unit 全套會有 8 個失敗**，因為沒有 `intl`。如果以後要求「所有測試都在 chiseled image 裡跑」並擴大到 Unit，就要決定：在 chiseled（和一般的 `Dockerfile`）加 `php8.3-intl`（會改到正式 image，需要評估），或是讓 `CustomFieldTest` 的非拉丁字元案例在沒有 `transliterator_transliterate` 時 `markTestSkipped`／改用 fallback 的期望值。`ImporterEncodingTest` 要再追查偵測編碼的那一步。上游的官方 Docker image 應該也有同樣的狀況。

### 測試工具（cloud-verify/review-fixes）

1. **`runner.py` `call()` 用 `text=True` 但沒有指定 `errors`**：如果 phpunit 的輸出含非 UTF-8 位元組（例如 `ImporterEncodingTest` 失敗訊息裡的 GBK 原始位元組），`subprocess.run` 會丟 `UnicodeDecodeError`，整個 runner 就中止了。這輪的 B 測試範圍沒有碰到，是我跑 Unit 全套時遇到的。建議：
   ```diff
   -    p = subprocess.run(args, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
   +    p = subprocess.run(args, cwd=cwd, env=env, text=True, errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
   ```
2. **`phpunit()` 只加 `--display-skipped`**：incomplete 的測試在 JUnit 裡記成 `skipped`，但沒有顯示原因。建議加 `--display-incomplete`，`skipped_summary` 的 regex 也要能抓到 incomplete。
3. 這輪沒有其他工具上的問題：mirror 從零重建、代理 CA、Go 測試、FR-2、FR-8、FR-9 都一次成功。
