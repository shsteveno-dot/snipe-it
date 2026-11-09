# 雲端測試任務

這個分支是 `all-changes`（commit `330a2a3439`）再加上這一個說明檔。請在這個 repo 跑完整的 PHPUnit 測試，並和上游 develop 比較，**不要修改程式碼，也不要 push 任何東西**。

## 背景

- `all-changes` = 上游 `grokability/snipe-it` 的 develop（`73323cb76d`）+ 我們 17 個 commit（S3 相容、LDAP OU 篩選、chiseled image、備份檔名標記等）。
- 目標：確認我們的改動沒有讓任何測試失敗。只在我們分支失敗、上游 develop 沒失敗的測試才算問題。

## 步驟

1. 環境：PHP 8.3（8.2 也可以），擴充套件 `pdo_mysql pdo_sqlite zip gd bcmath ldap exif intl mbstring xml curl`，Composer 2，MariaDB 10.11 或 MySQL 8。
   沒有的話用 apt 安裝（例如 `php8.3-cli php8.3-mysql php8.3-sqlite3 php8.3-zip php8.3-gd php8.3-bcmath php8.3-ldap php8.3-intl php8.3-mbstring php8.3-xml php8.3-curl mariadb-server composer`）。
2. `composer install --no-interaction --prefer-dist`
3. 設定測試環境：
   - `cp .env.testing.example .env.testing`，把 DB_DATABASE / DB_USERNAME / DB_PASSWORD 改成本機 MariaDB 的值（例如建一個 `snipeit_test` 資料庫，使用者要有 CREATE DATABASE 權限，因為平行測試會另外建 `snipeit_test_test_N`）。
   - 確認 `.env.testing` 有 `IMPORT_MEMORY_LIMIT=2G` 和 `LDAP_MEM_LIM=2G`（範本裡已經有）。少了這兩行，全套測試會在大約第 3600 個測試時因為記憶體上限 500M 當掉。
   - `cp .env.testing .env`
4. 跑全套（和上游 CI 一樣用平行模式）：
   `php -d memory_limit=2G artisan test --parallel --colors=never 2>&1 | tee /tmp/branch.txt`
   平行模式有問題的話，改用 `php -d memory_limit=2G vendor/bin/phpunit --colors=never`。
5. 有失敗的話，到上游 develop 跑同一批失敗的測試檔做比較：
   ```
   git fetch https://github.com/grokability/snipe-it.git develop
   git worktree add /tmp/dev FETCH_HEAD
   ```
   在 `/tmp/dev` 重做步驟 2–3（同一個資料庫設定），只跑失敗的測試檔。
6. 結束後刪掉 `/tmp/dev` worktree 和測試資料庫。

## 已知與環境有關的失敗（上游 develop 也會失敗）

- `Tests\Unit\CustomFieldTest::test_db_name_{chinese,japanese,korean,arabic}`：`intl` 的音譯結果因版本不同而不同。
- `Tests\Feature\SyncAdapters\ExtraFieldMappingTest::test_{purchase,eol}_date_accepts_iso_8601_datetime`：`APP_TIMEZONE` 不是 UTC 時，午夜 UTC 的日期會存成前一天（範本是 UTC 的話應該會過）。

在本機上一次跑的結果：6029 個測試、6 個失敗，就是上面這 6 個，上游 develop 也一樣。

## 回報內容

1. 環境：PHP 版本、資料庫版本、CPU 核心數、平行或單程序、總耗時。
2. 測試總數、通過、失敗、略過。
3. 每個失敗的測試：名稱、錯誤摘要（前幾行），以及在上游 develop 是否也失敗。
4. 結論：有沒有只在 `all-changes` 失敗的測試。有的話，指出可能相關的 commit 和檔案，但不要修改。
