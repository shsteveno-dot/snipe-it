# 雲端測試結果：第 20 輪（確認第 19 輪的兩個修正，只跑相關的測試）

**第 20 輪通過。**

- **第 2 步（Go）**：在 `docker/snipeit-runtime` 執行 `gofmt -l .`，**沒有輸出**；`go vet ./...` exit 0；`go test ./...` 全部 ok（`cmd/init`、`internal/handoff`、`internal/startup`、`internal/supervisor`），`TestKeyPermissionsAt` PASS。`startup.go` 第 169 行現在是一行，結尾是 `%v\n"`。
- **第 3 步（runner，原樣執行，沒有關 `exec`）**：exit **0**，`errors` 是 **`[]`**。267 個通過，唯一的失敗是預期的 FR-9 突變版（`Finding 9: safety backup omitted remote files.`），0 略過。新的 **`go_checks` 通過**。`shellless_order` 45/45，FR-2、FR-8、FR-9、`candidate_proxy_ca_absent`、input lock 都通過。
- **第 4 步（snapshot 這組，`PHPUNIT_PHP_ARGS` 和 `PHPUNIT_INI` 都沒有設定）**：exit 0，8 個測試，**0 失敗、0 error、3 略過**。略過的是單元測試的「MySQL with both tools」和「MariaDB with both tools」（`Snapshot support requires /bin/sh.`），以及 Feature 的 `test_restoring_the_baseline…`。單元測試其他 4 個 data set 和 Feature 的 `test_file_cache_locks_do_not_leak_into_a_new_test_cache` 都通過。這次也沒有 `exec()` 的 PHP 警告，因為沒有 shell 時檢查會在 `ExecutableFinder` 之前就回傳。

被測的 commit 是 `cloud-test` `12edd151d6`（包含 `all-changes` `d667502e3c`）。工具、程式碼和 Dockerfile 都沒有修改。完整輸出見 `cloud-test-output.txt`。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| 主機 | Linux 6.18，4 核，15 GB RAM。`~/.cache/review-fixes/mirrors` 是之前留下的 |
| Docker | dockerd 29.10.0，用 root 啟動，帶當下的 `HTTP(S)_PROXY=$HTTPS_PROXY`。第一次 pull `hello-world` 時 Docker Hub 回 **429 Too Many Requests**，幾秒後重試就成功了，runner 自己的 pull 沒有遇到 |
| Go（第 2 步） | 主機的 `go`，toolchain 是 `go.mod` 指定的 go1.26.10（第 19 輪自動下載的，這次沒有重新下載） |
| runner | candidate `sha256:98f152036b52…`、測試 image `sha256:b6d8436bf878…`。`go_checks` 用的是固定 digest 的 golang image（`672c944cfd07…`），`--network none` |
| PHP | chiseled `/usr/bin/php` 8.3.6，sha256 `7f1ac2fe89d2…a67d7`，和之前相同。candidate 和測試 image 的 `php -v`、`php -m`、sha256 都相同 |
| 資料庫 | runner 和 snapshot 這組都用 `mysql:8.4` |

| 階段 | 時間（UTC） |
| --- | --- |
| fetch、checkout（HEAD `12edd151d6`）、讀說明、啟動 dockerd、Go 檢查 | 07:52–07:53 |
| runner | 07:53:44–08:07:46（exit 0，背景時限 2 小時） |
| snapshot 這組（runner 的測試 image 一建好就開始） | 08:01:01–08:01:31（phpunit 15 秒） |
| 清理、報告 | 08:08– |

## 2. 測試數量

| 執行 | 第 20 輪 | 第 19 輪 |
| --- | --- | --- |
| runner exit / `errors` | **0 / `[]`** | 1（candidate build 失敗）；診斷版 0 / `[]` |
| runner `counts` | passed 267、failure 1（FR-9 突變版） | `{}`；診斷版相同 |
| `LdapTest` selected / 全套 | 7 / 35 | — |
| `S3Compatibility` selected / 全套 | 16 / 103 | — |
| `LdapWizardTest` selected / 全套 | 3 / 57 | — |
| `shellless_order` | 45 / 45 | — |
| FR-9 原版 / 突變版 | 通過 / 失敗（預期） | — |
| snapshot 這組 | 8 個：5 通過、3 略過、0 F、0 E | 單元測試 2 F |

## 3. 失敗和可疑項目

沒有。runner 唯一的失敗是預期的 FR-9 突變版。snapshot 這組的 3 個略過都是第 20 輪說明裡預期的，原因也對（沒有 `/bin/sh`；沒有 `mysql` client）。

## 4. 「這次的重點」逐項回答

1. **dockerd**：用當下的 `$HTTPS_PROXY` 啟動。runner 用 2 小時的背景時限，沒有被中斷。第一次 pull 遇到 Docker Hub 429，重試就好了。
2. **Go**：`gofmt -l .` 沒有輸出，`go vet ./...` 和 `go test ./...` 都通過。第 19 輪寫壞的字串已經修好。
3. **runner**：全部符合要求，見開頭。
   - 新的 `go_checks` probe 在 candidate build 之前執行，記錄成 `{"passed": true, "exit_code": 0}`。debug log 裡的指令是 `gofmt -l`（有輸出就失敗）→ `go vet ./...` → `go test ./...`，輸出 4 個 package 都 ok。
   - 這次沒有任何指令失敗，所以「附上第一個像錯誤的行」這個新功能沒有被用到。
   - `results-B.json` 沒有 `docker.sock`。runner 跑完後 `git status` 只有 `results-B.json` 有變動。
4. **snapshot 這組**：符合預期，見開頭。`full-suite:test` 和 `results-B.json` 的 `test_image_id` 是同一個 image。
   - 注意：這組用到的 `full/init.php` 是第 19 輪執行 `prep.py` 時留下的檔案（被 gitignore）。我確認過它和在 `12edd151d6` 上重新執行 `prep.py` 產生的檔案完全相同，所以不影響結果。但如果在全新的 checkout 上照第 4 步的指令做，就不會有這個檔案，見修改建議 1。
5. **清理**：
   - 刪掉 `r17o-db`、`r17o-vol-snapshot`、網路和 `full-suite:test`。
   - 執行了 `docker image prune -af`、`docker buildx prune -af`（10.78 GB）、`docker system prune -af --volumes`，之後 `docker system df` 全部是 0。
   - dockerd 已停止。`out-snapshot/` 已經從 checkout 刪掉（scratchpad 有一份副本）。`/tmp/review-*` 沒有殘留。
   - repo 裡只有 `results-B.json` 和兩個報告檔有變動。

## 5. 修改建議（依重要性排序）

這次沒有需要修的程式錯誤。

1. **`cloud-verify/full-suite`（流程，建議）**：`run-order.sh` 和 `run-full.sh` 會把 `full/init.php` 唯讀掛進容器，但這個檔案是 `prep.py` 產生的，而且被 gitignore。全新的 checkout 只執行第 20 輪第 4 步的指令（tag 之後直接 `run-order.sh … snapshot`）時，就沒有這個檔案。docker 會在那個路徑建立一個空目錄，`init.php` 會執行失敗，接著 migration 也會出錯。建議：
   - 腳本開始時檢查 `full/init.php` 是一般檔案，不是的話就報錯並提示先執行 `prep.py`（和 `PHPUNIT_INI` 不存在時的處理方式一樣）；或是
   - 說明檔的第 4 步加上 `python3 -I prep.py ../.. full`。
   - `prep.py` 不會動到已經 commit 的 `full/snapshot.xml`，我確認過。
2. **測試工具 `runner.py`（第 19 輪建議 3 還沒做的兩點，不急）**：分組時只用訊息的第一行，並先遮蔽數字和連線資訊；摘要也計算 failure 和略過。這次沒有失敗，所以沒有新的資料可以看。
3. **上游問題（同前幾輪）**：`ListLicensesTool` 應該再加 `->orderBy('licenses.id', 'desc')` 作為第二排序欄位。
