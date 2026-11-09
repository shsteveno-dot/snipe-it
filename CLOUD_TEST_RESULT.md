# 雲端測試結果（第 6 輪：chiseled image 建置與驗收）

**結論：image 建置成功，三個驗收都 `pass`，最後的 image 裡沒有代理 CA 或代理設定。** 有兩個需要注意的地方：

1. composer 在這個環境下不能從 GitHub 下載 dist（`api.github.com`、`codeload.github.com` 都是 403），所以我用 `git archive` 從同一個 commit 產生 dist zip，放進 build 專用階段的 Composer 快取（見 1.2）。
2. `regression.py --self-test` 的斷言寫反了，所以它回 exit 1；matcher 本身的行為是正確的（見 4.3）。

分支 `cloud-test` `4c561c3`（程式碼 = `all-changes` `930b3456cc`），基準為上游 develop `f9f3a6067c`。完整輸出見 `cloud-test-output.txt`，驗收 json 在 `cloud-verify/round6/`。

## 1. 環境、build 與耗時

| 項目 | 值 |
| --- | --- |
| 主機 | x86_64，4 核心，15 GB RAM，Firecracker VM（kernel 6.18.44），root，capabilities 齊全 |
| Docker | dockerd 29.9.2（自己啟動，帶 `HTTP(S)_PROXY=http://127.0.0.1:42555` 和 sandbox 的 `NO_PROXY`），storage driver overlayfs（containerd snapshotter），cgroup v1；buildx 0.38.1 |
| `docker run --rm hello-world` | 成功 |
| `repin_app_inputs.py --check` | `locks are up to date` |
| 磁碟 | 開始時剩 12 GB。照說明檔刪掉了 `vendor/`（9.5 GB，第 3 輪用 `--prefer-source` 裝的），刪完剩 21 GB。MariaDB 沒有停（只佔 200 MB）。之後要跑 PHPUnit 需要重新 `composer install`；`~/.cache/composer`（8.5 GB 的 git mirror）有保留，重裝會比較快 |

| 階段 | 耗時 |
| --- | --- |
| 啟動 dockerd ＋ hello-world | 不到 1 分鐘 |
| 第 1 次 build（只加代理 CA） | 319 秒後在 `composer install` 失敗。各步驟：`install-build-php.py` 139 秒、`fetch_inputs.py` 98 秒、`build-cut.py` 29 秒、Go 編譯 5 秒 |
| 產生 167 個 dist zip（`git archive`，本機，不用連網） | 約 10 秒 |
| 第 2 次 build（前面的階段用快取） | **38 秒**。沒有快取時估計約 6 分鐘（319 秒加上 composer 和組裝約 40 秒） |
| `check_sapi` / `check_invariants --boot` / `regression` | 45 秒 / 35 秒 / 34 秒（第一次要 pull `mysql:8.4` 和 `python:3.12-slim`） |
| 分析、清理、寫報告 | 約 15 分鐘 |

**Image：** `snipeit-chiseled:round6`，ID `sha256:ac5ade27d1eb097d6d50261f338b500361ff08070b129d01995568404acbfd2f`，磁碟上 545 MB（`Size` = 545,434,735 bytes），壓縮後 110 MB。Entrypoint 是 `/snipeit-supervisor`，使用者 `10000:50`。

### 1.1 build 指令

```bash
docker buildx build -f Dockerfile.chiseled --platform linux/amd64 -t snipeit-chiseled:round6 --load \
  --network host --progress plain \
  --build-arg HTTPS_PROXY=http://127.0.0.1:42555 --build-arg https_proxy=http://127.0.0.1:42555 \
  --build-arg NO_PROXY=... --build-arg no_proxy=... \
  --build-context proxyca=<只含 agent-proxy-ca.crt 的目錄> \
  --build-context composercache=<167 個 dist zip> .
```

- 只傳 `HTTPS_PROXY`：這個代理不轉送純 HTTP（`curl -x … http://archive.ubuntu.com` 回 405），但直接連 `http://archive.ubuntu.com` 可以，`tools` 階段第一次 `apt-get` 用的就是 http。
- `HTTPS_PROXY` 這類 build arg 是 BuildKit 預先定義的，不會寫進 image 的設定或 history（已在第 5 節確認）。
- 為了避免把這個容器裡的本機檔案（`.env.testing`、log 等，見建議 1）帶進 image，build context 用的是 `git worktree add --detach … HEAD` 建出來的乾淨 checkout，和 CI 的情況相同。做完已刪除 worktree。

### 1.2 暫時調整（沒有 commit，做完已還原，worktree 已刪除）

```diff
--- a/Dockerfile.chiseled
+++ b/Dockerfile.chiseled
@@ -21,6 +21,9 @@ ENV DEBIAN_FRONTEND=noninteractive
 COPY --from=entrypoint /snipeit-init /snipeit-supervisor /project-binaries/
 RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git python3 \
     && rm -rf /var/lib/apt/lists /var/cache/apt
+# TEMPORARY (cloud round 6, not committed): trust the sandbox HTTPS proxy in build-only stages.
+COPY --from=proxyca agent-proxy-ca.crt /usr/local/share/ca-certificates/agent-proxy-ca.crt
+RUN update-ca-certificates
 COPY docker/chiseled/ /chisel-inputs/
 COPY composer.lock /application-composer.lock
 COPY docker/snipeit-runtime/go.mod /application-go.mod
@@ -41,6 +44,9 @@ RUN python3 /chisel-inputs/prepare-app.py
 WORKDIR /var/www/html
 USER 10000:50
 ENV COMPOSER_CACHE_DIR=/tmp/composer-cache COMPOSER_HOME=/tmp/composer-home
+# TEMPORARY (cloud round 6, not committed): api.github.com and codeload.github.com answer 403 here, so the
+# dist archives come from `git archive` of the locked commits, pre-seeded into Composer's file cache.
+COPY --from=composercache --chown=10000:50 . /tmp/composer-cache/files/
 RUN php /usr/bin/composer install --no-dev --no-interaction --working-dir=/var/www/html
 USER root
 RUN python3 /patch-dumper.py /var/www/html/vendor/spatie/db-dumper/src/Databases/MySql.php
```

- **代理 CA**：只加在 `tools` 階段，`inputs`、`chisel`、`application`、`assemble` 這些 build 用的階段會繼承它。`candidate` 是從 `scratch` 只複製 `/rootfs/`，而 `/rootfs` 是 chisel 從鎖定的 Ubuntu 套件切出來的，`/var/www/html` 只是應用程式的目錄樹，所以代理 CA 不會進到最後的 image（第 5 節已驗證）。
- **Composer 快取（超出「只調整代理」的範圍，特別說明）：**
  - 第 1 次 build 失敗時，composer 印出 `Failed to download … from dist: Could not authenticate against github.com`，接著是 `Source fallback is disabled. Not trying alternative sources.`。也就是說，說明檔預期的「自動改用 git clone」**沒有發生**：composer 把 403 當成驗證失敗，不會再試 source。
  - `composer.lock` 裡 167 個套件的 dist 都在 `api.github.com`，`codeload.github.com` 也是 403。
  - 我用第 3 輪留下的 git mirror（`~/.cache/composer/vcs`），對每個套件 lock 裡的 `dist.reference` 執行 `git archive --format=zip`，放在 `files/<name>/<sha1(dist url)>.zip`。167 個套件的 source reference 和 dist reference 全部相同。build log 顯示 167 個都是「Extracting archive」。
  - 和真正的 GitHub zipball 的差別：同一個 commit，`git archive` 一樣會套用 `.gitattributes` 的 `export-ignore`/`export-subst`，所以 vendor 的檔案內容應該相同，但 zip 檔本身不是 GitHub 產生的那一份（lock 的 `shasum` 是空的，composer 本來就不會驗證）。
  - 改用 `--prefer-source` 會讓 `vendor/*/.git` 進到 image，改變最後的內容，所以沒有用。

## 2. 驗收結果

| 腳本 | exit | 結果 | 耗時 |
| --- | --- | --- | --- |
| `check_sapi.py snipeit-chiseled:round6 --out cloud-verify/round6/sapi.json --label round6` | 0 | **pass** | 45 秒 |
| `check_invariants.py snipeit-chiseled:round6 --boot --out cloud-verify/round6/invariants.json --label round6` | 0 | **pass** | 35 秒 |
| `regression.py --self-test` | **1** | 腳本的斷言寫反了，見 4.3 | 0 秒 |
| `regression.py snipeit-chiseled:round6 --out cloud-verify/round6/regression.json --label round6` | 0 | **pass** | 34 秒 |

全部用 `python3 -I` 執行，腳本沒有修改。

## 3. 和 `previous-run/` 的差異

`result` 都是 `pass` → `pass`，**所有 checks 的值都一樣**，`check_invariants` 的 `forbidden_present` 也一樣是 `[]`。不同的只有下面這些：

| 檔案 | 項目 | 上次（`rebase-develop-330a2a34`） | 這次（`round6`） | 說明 |
| --- | --- | --- | --- | --- |
| 全部 | `image` | `snipeit-chiseled:rebase-develop-330a2a34` | `snipeit-chiseled:round6` | 標籤不同 |
| sapi | `image_id` | `sha256:4d396eb4…` | `sha256:ac5ade27…` | 程式碼不同，預期會變 |
| regression | `details.backup.latest_zip_bytes` | 26536 | 26524 | 一樣是 29 個檔案；差 12 bytes 是 dump 的時間戳和資料差異 |
| regression | `details.backup.output_tail` | `Size is 25.91 KB` | `Size is 25.9 KB` | 同上 |
| regression | `details.backup.zips` 的檔名、`details.mail.marker`、`details.web.*` 的主機名稱 | — | — | 時間戳和隨機名稱 |

`check_sapi` 的 `apache_probe.hits` 兩次都是 23，`memory_consumption` 都是 128。

## 4. 「這次的重點」逐項回答

### 4.1 啟動 dockerd、hello-world：**可以**

以 root 直接執行 `dockerd`（帶代理的環境變數），幾秒內就可以用了。`docker run --rm hello-world` 成功（透過代理從 Docker Hub pull）。

### 4.2 `repin_app_inputs.py --check`：**`locks are up to date`**

### 4.3 三個驗收腳本：`check_sapi`、`check_invariants --boot`、`regression` 都是 exit 0、`pass`；**`regression --self-test` 是 exit 1**

`--self-test` 的輸出：

```
{"self_test_matches_for_unsent_marker": 0}
AssertionError: matcher found no message for an unsent marker (expected for RED)
```

`regression.py` 第 86–91 行：

```python
if args.self_test:
    messages = [{'recipient': 'RCPT TO:<sink@example.invalid>', 'data': 'Subject: other-marker'}]
    hit = delivered(messages, 'never-sent-marker')
    print(json.dumps({'self_test_matches_for_unsent_marker': len(hit)}))
    assert hit, 'matcher found no message for an unsent marker (expected for RED)'
    return 0
```

- docstring 寫的是「`--self-test  # matcher must reject an unsent marker`」，所以正確的結果是 `hit == []`。matcher 這次確實回了 0 筆。
- 但斷言是 `assert hit`，只有 matcher **錯誤地**匹配到時才會通過。看起來是 TDD「RED」階段的斷言沒有改回來。
- 這不是 image 的問題。照說明檔，腳本只執行、不修改。修法見建議 2。

### 4.4 最後的 image 裡沒有代理 CA 或代理設定：**是**

| 檢查 | 結果 |
| --- | --- |
| `docker image inspect` 的 `Config.Env` | 只有 `PATH`、`SNIPEIT_SHELLLESS`、`APACHE_*`、`PHP_INI_SCAN_DIR`、`OPENSSL_CONF`、`SSL_CERT_FILE`，沒有任何 proxy 變數 |
| `docker history --no-trunc` 裡的 `proxy`／`ccr`／`42555` | 沒有 |
| `docker create` → `docker export` 解開後，找 `agent-proxy-ca.crt` 和 `/usr/local/share/ca-certificates/` | 都不存在 |
| 用代理 CA 的第一行 base64 搜尋整個 rootfs | 0 個檔案 |
| `/etc/ssl/certs/ca-certificates.crt` 裡的憑證，和代理 CA 的 SHA-256 指紋（`EB:F2:2B:4E:…:84:39`）比對 | 120 張，相符 0 張 |
| 搜尋 `127.0.0.1:42555` 和 `/root/.ccr` | 只有 `/var/www/html/CLOUD_TEST.md`（這份說明檔本身的文字，見建議 3） |

### 4.5 清理：**完成**

- 已刪除全部 image（`snipeit-chiseled:round6`、`mysql:8.4`、`python:3.12-slim`、`hello-world`）、volume、build cache（`docker buildx prune -af` 清掉 4.55 GB）。`docker system df` 全部是 0。
- dockerd 已停止，build 用的 worktree 已刪除。
- 驗收跑完時有 2 個匿名 volume 沒被清掉：一個是我 `docker export` 前 `docker create` 留下的（`docker rm` 沒加 `-v`）；另一個是 `check_invariants.py` 留下的（見建議 4）。

## 5. 修改建議（只列和 chiseled image 有關、值得做的）

### 1.（中，我們的改動）`.dockerignore` 沒有排除本機產生的檔案，`COPY . /var/www/html` 會把它們帶進 image

檔案：`.dockerignore`（也可以在 `docker/chiseled/prepare-app.py` 加一道防護）

原因：`.dockerignore` 只排除 `.git`、`vendor/*`、`node_modules` 等少數幾項。在這個容器的 checkout 上，用只有 `COPY . /var/www/html` 的 Dockerfile 實測，context 會帶進下面這些：

| 檔案 | 在 chiseled image 裡的下場 |
| --- | --- |
| `.env` | 被 `docker/docker.env` 蓋掉（沒有問題） |
| `storage/oauth-*.key` | 被 `prepare-app.py` 換成 symlink（沒有問題） |
| `bootstrap/cache/packages.php` | 被 composer 的 `package:discover` 重新產生（沒有問題） |
| `.env.testing`（含資料庫帳號密碼） | **留在 image 裡** |
| `storage/logs/laravel.log`、`admin-*.log` | **留在 image 裡**（`storage/logs` 沒有被換成 symlink） |
| `storage/framework/views/*.php`（551 個編譯過的 view） | **留在 image 裡** |
| `.phpunit.cache/`、`bootstrap/cache/services.php`、`storage/framework/testing/`、`storage/app/backup-temp/` | **留在 image 裡** |

CI 用的是乾淨的 checkout，所以不受影響。但開發者照 README 在自己的工作目錄執行 `docker buildx build … .`，就會把本機的 log（可能含個資或錯誤細節）和測試設定打包進 image。這次我用乾淨的 worktree 建，所以 `round6` image 沒有這個問題。

建議改法：

```diff
--- a/.dockerignore
+++ b/.dockerignore
@@
 vendor/*
 storage/framework/cache/*
 node_modules
 .vagrant
 .idea
+.env
+.env.testing
+.env.dusk*
+.phpunit.cache
+.phpunit.result.cache
+bootstrap/cache/*.php
+storage/logs/*
+!storage/logs/.gitignore
+storage/framework/views/*
+storage/framework/sessions/*
+storage/framework/testing
+storage/app/backup-temp
+storage/*.key
+storage/private_uploads/*
+public/uploads/*
+!public/uploads/default.png
+!public/uploads/snipe-logo.png
```

`public/uploads`、`storage/private_uploads` 在 chiseled image 裡會被 `prepare-app.py` 換成 symlink，但另一個 `Dockerfile` 也會讀同一份 `.dockerignore`，所以要確認 repo 裡追蹤的 placeholder 檔不會被排除；用 `!` 列出例外即可，或者乾脆不加這兩行。

如果不想動共用的 `.dockerignore`，也可以在 `prepare-app.py` 刪掉 `.env.testing`、`.phpunit.cache`、`storage/logs/*.log`、`storage/framework/{views,testing,sessions}/*`、`bootstrap/cache/services.php`。

### 2.（中，驗收腳本）`regression.py --self-test` 的斷言寫反了

檔案：`cloud-verify/verification/chiseled-opcache/regression.py` 第 90 行（以及本機 verification 目錄的原始檔）

```diff
-        assert hit, 'matcher found no message for an unsent marker (expected for RED)'
+        assert not hit, 'matcher matched a message for a marker that was never sent'
```

修正前，matcher 正確時 self-test 會失敗，matcher 壞掉時反而會通過，完全失去自我檢查的意義。上一輪的 `previous-run/` 沒有記錄 self-test 的結果，可能就是因為這樣才沒有發現。

### 3.（低，我們的改動）把只用於開發和驗收的檔案排除在 image 外

`/var/www/html` 裡目前有 `cloud-verify/`、`CLOUD_TEST.md`、`.ai/`、`AGENTS.md`、`CLAUDE.md`。`cloud-verify/` 和 `CLOUD_TEST.md` 只存在 `cloud-test` 分支，其他是 repo 裡追蹤的檔案。它們不影響執行，但會讓 image 裡出現 `127.0.0.1:42555` 這類文字，也增加之後稽核的雜訊。可以在 `prepare-app.py` 原本刪 `tests`、`.github` 的那個清單裡加上 `cloud-verify`、`.ai`，或者寫進 `.dockerignore`。

### 4.（低，驗收腳本）`check_invariants.py` 會留下匿名 volume

檔案：`cloud-verify/verification/chiseled-opcache/check_invariants.py` 第 24–28 行

原因：image 宣告了 `VOLUME ["/var/lib/snipeit"]`，`docker create` 會建立一個匿名 volume，而 `docker rm -f` 沒有加 `-v`。這次在它執行期間（08:20:02）留下了 1 個。`stack.py` 本身用的是 `rm -f -v`，所以沒有這個問題。

```diff
-        docker('rm', '-f', container, check=False)
+        docker('rm', '-f', '-v', container, check=False)
```

### 5.（低，說明檔）`CLOUD_TEST.md` 的 composer 說明

「composer 下載 dist 失敗時會自動改用 git clone」在這個環境不成立：composer 把 403 當成驗證失敗，然後停止，訊息是 `Source fallback is disabled`。建議把 1.2 的做法寫進說明檔：

```bash
git archive --format=zip -o <cache>/files/<name>/$(php -r 'echo sha1("<dist url>");').zip <dist reference>
```

用 `--build-context composercache=<cache>` 搭配 `tools`/`application` 階段的暫時 `COPY` 傳進去。這需要 `~/.cache/composer/vcs` 已經有 mirror（例如先在主機跑過一次 `composer install --prefer-source`）。
