# 雲端測試結果

分支 `cloud-test`（`2f8af3a`）= 上游 develop `f9f3a6067c` + 我們的 commit。上游 develop 目前仍是 `f9f3a6067c`。完整輸出見 `cloud-test-output.txt`。

## 1. 環境

| 項目 | 值 |
| --- | --- |
| PHP | 8.3.6 (CLI, NTS)，擴充套件 pdo_mysql pdo_sqlite zip gd bcmath ldap exif intl mbstring xml curl 都有 |
| 資料庫 | MariaDB 10.11.14 |
| CPU | 4 核心（Intel Xeon @ 2.10GHz） |
| 模式 | 平行模式，`php -d memory_limit=2G artisan test --parallel --colors=never`（ParaTest 7.8.5 / PHPUnit 11.5.55，4 個 process） |
| 總耗時 | 7 分 42 秒（分支），7 分 32 秒（上游 develop） |
| `.env.testing` | 照範本，`APP_TIMEZONE='UTC'`、`IMPORT_MEMORY_LIMIT=2G`、`LDAP_MEM_LIM=2G` |

環境備註：

- 這個 session 無法從 api.github.com 下載 zip，所以 `composer install` 改用 `--prefer-source`（git clone）。`phpstan/phpstan` 在 lock 裡只有 dist，我從它的 git repo 的同一個 commit 打包成 zip，放進 Composer 快取。`composer.lock` 沒有改。
- 第一次跑全套時，Passport 金鑰（`storage/oauth-*.key`）在跑到一半才產生，所以 824 個 API 測試出現 `LogicException: Invalid key supplied`。那次的結果不算數（摘要放在輸出檔第 4 段）。上游 CI 會在測試前先跑 `passport:install`。金鑰產生後重跑，下面的數字都是重跑的結果。

## 2. 測試數量

| | 總數 | 通過 | 失敗 | 錯誤 | 略過 | 未完成 (Incomplete) |
| --- | --- | --- | --- | --- | --- | --- |
| 分支 `cloud-test` | 6061 | 5969 | 1 | 0 | 38 | 53 |
| 上游 develop `f9f3a6067c` | 5916 | 5860 | 0 | 0 | 3 | 53 |

分支多了 145 個測試，都是我們新增的。

**略過的測試：** 分支多出的 35 個略過，全部是我們的 S3 測試（`MoveUploadsToNewDiskTest`、`RestoreToRemoteDiskTest`、`StagingAssumptionsTest`）。它們有保護機制：`storage/private_uploads` 裡有真實檔案時就拒絕執行。原因是有一個**上游**測試在每次全套執行時都會留下 2 個 `storage/private_uploads/eula-pdfs/accepted-*.pdf`，上游 develop 也會留下這兩個檔案。我把那幾個 PDF 移開之後，用單一 process 重跑 `tests/Feature/S3Compatibility`、`tests/Unit/S3Compatibility`、`tests/Feature/Console`：**375 個測試全部通過，0 略過，0 失敗**（輸出檔第 3 段）。

## 3. 失敗的測試

### `Tests\Feature\Livewire\ImporterMutexTest::test_locks_are_scoped_per_file_so_a_second_file_can_still_start`

```
Failed asserting that false matches expected true.

vendor/livewire/livewire/src/Features/SupportTesting/MakesAssertions.php:164
tests/Feature/Livewire/ImporterMutexTest.php:69
```

- **上游 develop 是否也失敗：** 這次上游的平行全套沒有失敗，清掉 file cache 後單獨跑也是 3 次都通過。
- **但這看起來是不穩定的測試（flaky），和我們的改動無關：**
  - 鎖的 key 是 `import:{id}:running`（`app/Models/Import.php:42`），存在**共用的 file cache**（`storage/framework/cache`），TTL 30 分鐘。平行模式下每個 process 有自己的資料庫，會發出一樣的 Import ID，所以不同 process 的測試會互相看到對方的鎖，一個 process 留下的鎖也會影響下一次執行。
  - 全套跑完後，我在分支上單獨跑這個檔案：第 1 次失敗（file cache 裡有全套留下的鎖），第 2、3 次通過。清掉 file cache 後，分支上單獨跑 3 次都通過，和上游一樣。
  - 我們的 commit 沒有修改 `app/Livewire/Importer.php`、`app/Models/Import.php`、`tests/Feature/Livewire/ImporterMutexTest.php`、`config/cache.php` 任何一個檔案。

### CLOUD_TEST.md 列出的 6 個已知失敗

在這個環境**都通過**：`CustomFieldTest::test_db_name_{chinese,japanese,korean,arabic}`（這裡的 intl 版本音譯結果符合預期）、`ExtraFieldMappingTest::test_{purchase,eol}_date_accepts_iso_8601_datetime`（`APP_TIMEZONE` 是 UTC）。

## 4. 結論

**沒有因為我們的改動而失敗的測試。** 唯一的失敗是 `ImporterMutexTest` 的平行模式競爭（共用 file cache 加上重複的 Import ID）。這個測試在分支和上游上，用乾淨的 cache 都會通過，而且我們沒有碰任何相關檔案。

兩件值得追蹤的事（都沒有修改程式碼）：

1. 有一個上游測試會在 `storage/private_uploads/eula-pdfs` 留下 acceptance PDF，導致我們 35 個 S3 測試在全套裡被略過。也就是說，**在全套執行時，S3 搬移／還原的測試其實沒有跑到**（這次兩組 PDF 都是在 S3 測試之前產生的，所以乾淨的 CI checkout 很可能也一樣，但要看測試執行順序）。可能的來源是沒有 `Storage::fake()` 的 checkout acceptance 測試（例如 `tests/Feature/CheckoutAcceptances/`、`tests/Feature/Notifications/Email/*UponCheckoutTest.php`）。可以考慮讓 S3 測試的保護機制（`tests/Support/S3Compatibility/ProtectsRealUploadDirectories.php`）忽略 `eula-pdfs`，或是修正那個會留下檔案的測試。
2. `ImporterMutexTest` 在平行模式下不穩定。上游也有同樣的風險（不是我們造成的）。
