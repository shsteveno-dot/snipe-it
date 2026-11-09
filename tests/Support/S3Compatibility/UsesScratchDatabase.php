<?php

namespace Tests\Support\S3Compatibility;

use Illuminate\Database\Connection;
use Illuminate\Support\Facades\DB;

/**
 * For tests that run snipeit:restore, which wipes and rewrites the tables of the configured database.
 *
 * The restore is pointed at a scratch database. Never run DDL (CREATE/DROP DATABASE, CREATE TABLE) or a
 * purge on the test connection: MySQL commits on DDL, RefreshDatabase then finds no open transaction and
 * the next test reruns every migration. The scratch database is created, changed and dropped through a
 * second connection; the test connection stays open on the test database, and only its config points at
 * the scratch database, which is what the restore command hands to the mysql client.
 */
trait UsesScratchDatabase
{
    private const SCRATCH_CONNECTION = 's3compat_scratch_admin';

    private string $scratchDatabase = '';

    private ?string $databaseBeforeScratch = null;

    protected function useScratchDatabase(string $prefix): string
    {
        $clientDirectory = $this->mysqlClientDirectory();

        // In parallel runs this is the worker's own database (<name>_test_<N>), not env('DB_DATABASE').
        $this->databaseBeforeScratch = (string) config('database.connections.mysql.database');
        config(['database.connections.'.self::SCRATCH_CONNECTION => config('database.connections.mysql')]);

        $this->scratchDatabase = $prefix.bin2hex(random_bytes(4));
        $this->scratchConnection()->statement('CREATE DATABASE `'.$this->scratchDatabase.'`');
        config([
            'database.connections.mysql.database' => $this->scratchDatabase,
            'database.connections.mysql.dump.dump_binary_path' => $clientDirectory,
        ]);

        return $this->scratchDatabase;
    }

    protected function scratchConnection(): Connection
    {
        return DB::connection(self::SCRATCH_CONNECTION);
    }

    protected function dropScratchDatabase(): void
    {
        if ($this->scratchDatabase === '') {
            return;
        }

        config(['database.connections.mysql.database' => $this->databaseBeforeScratch]);
        $this->scratchConnection()->statement('DROP DATABASE IF EXISTS `'.$this->scratchDatabase.'`');
        DB::purge(self::SCRATCH_CONNECTION);
        $this->scratchDatabase = '';
    }

    /**
     * The directory holding the mysql and mysqldump clients: the configured DB_DUMP_PATH when it has them,
     * otherwise the usual install locations or the PATH. The test is skipped when there is none.
     */
    protected function mysqlClientDirectory(): string
    {
        $candidates = [
            (string) config('database.connections.mysql.dump.dump_binary_path'),
            '/usr/bin',
            '/usr/local/bin',
            '/opt/homebrew/bin',
        ];
        foreach ($candidates as $directory) {
            if ($directory !== '' && is_executable(rtrim($directory, '/').'/mysql')) {
                return rtrim($directory, '/');
            }
        }

        $found = trim((string) @shell_exec('command -v mysql 2>/dev/null'));
        if ($found !== '' && is_executable($found)) {
            return dirname($found);
        }

        $this->markTestSkipped('The restore tests need the mysql client.');
    }
}
