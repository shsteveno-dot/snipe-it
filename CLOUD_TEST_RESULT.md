# 雲端測試結果（第 7 輪：本機檔案不進 image）

**結論：修正有效。** 用放了假檔案的「髒」checkout 建出的 `snipeit-chiseled:round7` 裡，搜尋 `FAKE-LOCAL-FILE` 是 0 筆；該保留的目錄和 `.gitignore` 都在；四個驗收（含 `--self-test`）全部 exit 0；跑完沒有留下匿名 volume。新的 `.dockerignore` 規則只排除本機產生的檔案，沒有擋到任何 git 追蹤的檔案。

分支 `cloud-test` `d041068`（程式碼 = `all-changes` `65ecdf0ab4`），基準為上游 develop `f9f3a6067c`。完整輸出見 `cloud-test-output.txt`，驗收 json 在 `cloud-verify/round7/`。

## 1. 環境、build 與耗時

| 項目 | 值 |
| --- | --- |
| 主機 | 和第 6 輪同一個容器（x86_64，4 核心）。`vendor/` 在第 6 輪已刪除，這輪不需要；磁碟剩 21 GB |
| `repin_app_inputs.py --check` | `locks are up to date` |
| Docker | dockerd 29.9.2，root，帶代理的環境變數；`hello-world` 成功 |
| 代理 | **port 從 42555 變成 37359**。第一次用舊 port 啟動 dockerd，pull 失敗（`proxyconnect … 42555: connection refused`），改用目前的 `$HTTPS_PROXY` 重啟後就好了。代理 CA 的指紋和第 6 輪相同 |

| 階段 | 耗時 |
| --- | --- |
| 啟動 dockerd ＋ hello-world | 約 1 分鐘（含 port 變更重啟） |
| build 第 1 次 | 3 秒就失敗：Docker Hub 回 `429 Too Many Requests`（匿名 pull 頻率限制） |
| `docker pull` 三個 base image | 一次就成功，約 30 秒 |
| build 第 2 次（沒有快取） | **182 秒**：`install-build-php.py` 39 秒、`fetch_inputs.py` 44 秒、`build-cut.py` 27 秒、composer 6 秒（167 個都是「Extracting archive」） |
| export 檢查、`prepare-app.py` 單獨測試 | 約 2 分鐘 |
| 四個驗收 | 42 秒 / 35 秒 / 0 秒 / 34 秒 |
| `.dockerignore` context 檢查 | 約 1 分鐘 |

**Image：** `snipeit-chiseled:round7`，ID `sha256:d02ae35f18058c6fba6e42c995a27d7d53275962a8fe5f5739416c95458eb18a`，磁碟上 545 MB（545,180,780 bytes，比第 6 輪少約 250 KB），壓縮後 110 MB。Env 和 history 都沒有代理相關的字串。

**暫時調整**：和第 6 輪完全相同，在 worktree 裡做，沒有 commit，worktree 已刪除：
- `tools` 階段加入代理 CA；
- `application` 階段放入 `git archive` 產生的 Composer 快取（第 6 輪做的 167 個 zip，`composer.lock` 沒變所以直接沿用）；
- 用 `--network host` ＋ `HTTPS_PROXY` build arg。

diff 見 `cloud-test-output.txt` 第 2 段。

## 2. 髒 checkout

用 `git worktree add --detach … HEAD` 建立，放入說明檔列的 10 個假檔案，內容都是 `FAKE-LOCAL-FILE <路徑>`：`.env.testing`、`.phpunit.cache/test-results`、`.phpunit.result.cache`、`storage/logs/laravel.log`、`storage/framework/views/0123abcd.php`、`storage/framework/sessions/fakesession`、`storage/framework/testing/disks/x.txt`、`storage/app/backup-temp/x.txt`、`bootstrap/cache/services.php`、`bootstrap/cache/packages.php`。

另外加了 `.claude/settings.local.json`：這個 repo 沒有 `.claude/`，但用 Claude Code 的開發者通常會有，也可以藉此測到 `prepare-app.py` 的刪除。`.ai/`、`cloud-verify/`、`CLOUD_TEST.md` 本來就在分支上。

## 3. 「這次的重點」逐項回答

### 3.1 假檔案和開發用目錄都不在 image 裡：**是**

`docker create` → `docker export` 解開後：

| 項目 | 結果 |
| --- | --- |
| 整個 rootfs 搜尋 `FAKE-LOCAL-FILE` | **0 筆** |
| `.env.testing`、`.phpunit.cache`、`.phpunit.result.cache`、`storage/logs/laravel.log`、`storage/framework/views/0123abcd.php`、`storage/framework/sessions/fakesession`、`storage/framework/testing`、`storage/app/backup-temp` | 都不存在 |
| `.ai/`、`.claude/`、`cloud-verify/`、`CLOUD_TEST.md`、`CLOUD_TEST_RESULT.md`、`cloud-test-output.txt` | 都不存在 |

### 3.2 目錄還在：**是**

| 目錄 | 內容 | 擁有者／權限 |
| --- | --- | --- |
| `storage/logs` | `.gitignore` | 10000:50 755 |
| `storage/framework/views` | `.gitignore` | 10000:50 755 |
| `storage/framework/sessions` | `.gitignore` | 10000:50 755 |
| `storage/framework/cache` | （空的，見建議 1） | 10000:50 755 |
| `bootstrap/cache` | `.gitignore`、`packages.php`、`services.php` | 10000:50 755 |

### 3.3 `bootstrap/cache/packages.php` 是 build 時重新產生的：**是**

時間戳是 build 的時間（08:38），內容是正常的 `<?php return array ( 'arietimmerman/laravel-scim-server' => …`，共 82 個 `=>`，不是假字串。`services.php` 也在同一時間產生，同樣不是假檔案：composer 執行 `package:discover`／`vendor:publish` 時會啟動 app，順便寫出這個檔案，而那時用的是 `--no-dev` 的 provider。

### 3.4 第二道防護 `prepare-app.py`（額外測試）

假檔案大多在 `.dockerignore` 這一層就被擋掉了，真正進到 build context、靠 `prepare-app.py` 刪掉的只有 `.ai/`、`.claude/`、`cloud-verify/`、`CLOUD_TEST.md`。為了確認「萬一 `.dockerignore` 漏掉」時第二道防護也有效，我把髒 worktree 的副本掛到 `python:3.12-slim` 的 `/var/www/html`，用 `--network none` 直接執行 `prepare-app.py`，另外多放了 `storage/framework/cache/data/ab/cd`：

- 執行前 13 個假檔案，**執行後 0 個**；
- `storage/logs`、`storage/framework/views`、`storage/framework/sessions`、`bootstrap/cache` 只剩 `.gitignore`；`storage/framework/cache` 剩 `.gitignore` 和空的 `data/`；
- `.ai`、`.claude`、`cloud-verify`、`CLOUD_TEST.md`、`.env.testing` 都被刪掉。

### 3.5 四個驗收：**全部 exit 0**

| 腳本 | exit | 結果 |
| --- | --- | --- |
| `check_sapi.py snipeit-chiseled:round7 --out cloud-verify/round7/sapi.json --label round7` | 0 | pass |
| `check_invariants.py snipeit-chiseled:round7 --boot --out cloud-verify/round7/invariants.json --label round7` | 0 | pass |
| `regression.py --self-test` | **0** | `{"self_test_matches_for_unsent_marker": 0}`，這次通過了 |
| `regression.py snipeit-chiseled:round7 --out cloud-verify/round7/regression.json --label round7` | 0 | pass |

和 `cloud-verify/round6/*.json` 比：**所有 checks 的值都一樣**，`forbidden_present` 都是 `[]`，`apache_probe.hits` 都是 23。不同的只有：

- `image`、`image_id`（`ac5ade27…` → `d02ae35f…`）；
- `backup.latest_zip_bytes`（26524 → 26521，一樣是 29 個檔案）；
- 備份 zip 的檔名、mail marker、主機名稱（時間戳和隨機值）。

### 3.6 沒有留下匿名 volume：**是**

每個驗收跑完後 `docker volume ls -q` 都是 0。四個都跑完後，容器 0 個，網路只剩 `bridge`/`host`/`none`。第 6 輪 `check_invariants.py` 留下 volume 的問題已經修好。我自己的 `docker create` 這次也加了 `rm -v`。

### 3.7 清理：**完成**

image、容器、volume 都已刪除；`docker buildx prune -af` 清掉 4.31 GB；`docker system df` 全部是 0；dockerd 已停；worktree 已刪除；`__pycache__` 已刪除。

### 3.8 `.dockerignore` 沒有擋到上游 `Dockerfile` 需要的檔案：**是**

上游 `Dockerfile` 是單一階段，沒有可以用 `--target` 停下的地方，而 `COPY . /var/www/html` 之前的 `apt-get` 很花時間和空間。所以照說明檔，用只有 `FROM scratch` ＋ `COPY . /var/www/html` 的暫時 Dockerfile，以同一個髒 worktree 當 context，比較新舊兩份 `.dockerignore`：

| | 檔案數 |
| --- | --- |
| git 追蹤的檔案 | 9709 |
| 新規則的 context | 9689 |
| 舊規則（`6bfd75f` 的 `.dockerignore`）的 context | 9699 |

- **只被新規則排除的 10 個檔案，剛好就是那 10 個假檔案**，其中被 git 追蹤的：0 個。
- git 追蹤但不在 context 裡的 20 個檔案，全是原本就排除的：`.dockerignore`、`.gitattributes`、`.gitignore`、`.github/` 底下 18 個，以及 `storage/framework/cache/.gitignore`（被原有的 `storage/framework/cache/*` 排除，見建議 1）。
- 上游 `Dockerfile` 在 `COPY` 之後會操作的 `storage/private_uploads`、`storage/app/backups`、`storage/oauth-*.key`（建 symlink）、`docker/docker.env`，在 context 裡都還在，或者是由 `Dockerfile` 自己產生的。
- 在 context 裡但不被 git 追蹤的只有 `.claude/settings.local.json`，見建議 2。

## 4. 修改建議（只列和 image 有關、值得做的）

### 1.（低，原本就有）`storage/framework/cache/.gitignore` 被 `.dockerignore` 排除

`.dockerignore` 原有的 `storage/framework/cache/*` 會連 `.gitignore` 一起排除。所以 image 裡的 `storage/framework/cache` 是空的，而 `views`、`sessions` 都有保留 `.gitignore`。目前不影響執行（驗收全過，Laravel 的 file cache 會自己建子目錄），但和這次修正「目錄和 `.gitignore` 保留」的原則不一致。建議加一行例外：

```diff
 storage/framework/cache/*
+!storage/framework/cache/.gitignore
```

### 2.（低，我們的改動）`.claude/` 沒有列進 `.dockerignore`

`prepare-app.py` 會刪 `.claude/`，所以 chiseled image 沒有問題。但上游 `Dockerfile` 沒有這一步，用 Claude Code 的開發者的 `.claude/settings.local.json`（可能有本機路徑或權限設定）會被 `COPY .` 帶進 image。建議在 `.dockerignore` 加上 `.claude/`，和 `.vagrant`、`.idea` 一樣處理。

### 3.（低，說明檔）`CLOUD_TEST.md` 的環境說明

- 代理的 port 會變（這次從 42555 變成 37359）。建議寫成「用當下的 `$HTTPS_PROXY` 啟動 dockerd，並傳給 `--build-arg`」，不要寫死 port。
- Docker Hub 的匿名 pull 可能回 `429`。遇到時先 `docker pull` 三個 base image（golang、composer、ubuntu 的固定 digest）再 build。這次 pull 一次就成功了。
