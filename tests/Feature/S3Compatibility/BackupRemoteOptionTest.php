<?php

namespace Tests\Feature\S3Compatibility;

use App\Console\Commands\SystemBackup;
use App\Models\User;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\File;
use Illuminate\Support\Facades\Storage;
use PHPUnit\Framework\Attributes\Test;
use Tests\Support\S3Compatibility\FakeRemoteAdapter;
use Tests\Support\S3Compatibility\UsesFakeRemoteDisks;
use Tests\TestCase;

/**
 * FR-11 / FR-11a: snipeit:backup includes S3 hosted upload files only when asked to (default: not),
 * and only then reads them.
 */
class BackupRemoteOptionTest extends TestCase
{
    use UsesFakeRemoteDisks;

    /** @var array<int, array<string, mixed>> what the stubbed backup:run saw */
    private array $calls = [];

    private string $backupRoot = '';

    private string $missingRoot = '';

    protected function setUp(): void
    {
        parent::setUp();

        $this->fakeRemoteDisk('public');
        $this->fakeRemoteDisk('custom_private');
        config(['filesystems.default' => 'custom_private']);
        Storage::forgetDisk('custom_private');
        config(['backup.include_remote_files' => false]);

        Storage::disk('custom_private')->put('private_uploads/eula-pdfs/e.pdf', 'PDF-BYTES');
        Storage::disk('public')->put('avatars/a.png', 'PNG-BYTES');
        FakeRemoteAdapter::$log = [];

        $this->stubBackupRun(0);
    }

    protected function tearDown(): void
    {
        if ($this->backupRoot !== '') {
            File::deleteDirectory($this->backupRoot);
        }
        if ($this->missingRoot !== '') {
            File::deleteDirectory($this->missingRoot);
        }
        $this->cleanUpFakeRemoteDisks();

        parent::tearDown();
    }

    private function stubBackupRun(int $exitCode, bool $leavesPartialZip = false): void
    {
        $this->calls = [];
        Artisan::command('backup:run {--filename=}', function () use ($exitCode, $leavesPartialZip) {
            if ($leavesPartialZip) {
                Storage::disk('backup')->put(config('backup.backup.name').'/'.config('backup.backup.destination.filename_prefix').$this->option('filename'), 'PARTIAL');
            }
            $extra = [];
            foreach (config('backup.backup.source.files.include') as $path) {
                $manifest = $path.'/snipeit-remote-manifest.json';
                if (is_file($manifest)) {
                    $extra[] = [
                        'dir' => $path,
                        'manifest' => json_decode(file_get_contents($manifest), true),
                        'files' => array_map(
                            fn ($f) => str_replace('\\', '/', substr($f->getPathname(), strlen($path) + 1)),
                            File::allFiles($path, true),
                        ),
                    ];
                }
            }
            app()->instance('s3compat.backup-run-calls', array_merge(app('s3compat.backup-run-calls') ?? [], [[
                'extra' => $extra,
                'filename' => $this->option('filename'),
                'include' => config('backup.backup.source.files.include'),
            ]]));

            return $exitCode;
        })->purpose('stub');
        app()->instance('s3compat.backup-run-calls', []);
    }

    private function calls(): array
    {
        return app('s3compat.backup-run-calls');
    }

    private function remoteUploadReads(): array
    {
        return array_values(array_filter(
            FakeRemoteAdapter::$log,
            fn ($e) => in_array($e[0], ['read', 'list'], true)
                && (str_starts_with($e[1], 'public:') || str_starts_with($e[1], 'custom_private:')),
        ));
    }

    #[Test]
    public function by_default_remote_files_are_neither_listed_nor_read_and_the_manifest_says_excluded(): void
    {
        $this->artisan('snipeit:backup')->assertExitCode(0);

        $this->assertSame([], $this->remoteUploadReads());
        $calls = $this->calls();
        $this->assertCount(1, $calls);
        $this->assertCount(1, $calls[0]['extra']);
        $this->assertSame('excluded', $calls[0]['extra'][0]['manifest']['remote_files']);
        $this->assertSame([], $calls[0]['extra'][0]['manifest']['files']);
        $this->assertSame(['snipeit-remote-manifest.json'], $calls[0]['extra'][0]['files']);
        $this->assertDirectoryDoesNotExist($calls[0]['extra'][0]['dir'], 'the marker directory is removed afterwards');
    }

    #[Test]
    public function without_remote_files_flag_behaves_like_the_default(): void
    {
        $this->artisan('snipeit:backup', ['--without-remote-files' => true])->assertExitCode(0);

        $this->assertSame([], $this->remoteUploadReads());
        $this->assertSame('excluded', $this->calls()[0]['extra'][0]['manifest']['remote_files']);
    }

    #[Test]
    public function with_remote_files_flag_stages_the_objects_and_cleans_up(): void
    {
        $this->artisan('snipeit:backup', ['--with-remote-files' => true])->assertExitCode(0);

        $extra = $this->calls()[0]['extra'];
        $this->assertCount(1, $extra);
        $this->assertSame('included', $extra[0]['manifest']['remote_files']);
        $this->assertEqualsCanonicalizing(
            ['public/uploads/avatars/a.png', 'storage/private_uploads/eula-pdfs/e.pdf', 'snipeit-remote-manifest.json'],
            $extra[0]['files'],
        );
        $this->assertDirectoryDoesNotExist($extra[0]['dir']);
    }

    #[Test]
    public function the_environment_setting_turns_remote_files_on_for_scheduled_backups(): void
    {
        config(['backup.include_remote_files' => true]);

        $this->artisan('snipeit:backup')->assertExitCode(0);

        $this->assertSame('included', $this->calls()[0]['extra'][0]['manifest']['remote_files']);
    }

    #[Test]
    public function the_flags_override_the_environment_setting(): void
    {
        config(['backup.include_remote_files' => true]);

        $this->artisan('snipeit:backup', ['--without-remote-files' => true])->assertExitCode(0);

        $this->assertSame('excluded', $this->calls()[0]['extra'][0]['manifest']['remote_files']);
    }

    #[Test]
    public function the_two_flags_together_are_rejected(): void
    {
        $this->artisan('snipeit:backup', ['--with-remote-files' => true, '--without-remote-files' => true])
            ->assertExitCode(1);

        $this->assertSame([], $this->calls(), 'backup:run must not run');
    }

    #[Test]
    public function a_failure_while_staging_stops_the_backup_and_leaves_nothing_behind(): void
    {
        FakeRemoteAdapter::$failReads = ['private_uploads/eula-pdfs/e.pdf'];

        $this->artisan('snipeit:backup', ['--with-remote-files' => true])->assertExitCode(1);

        $this->assertSame([], $this->calls(), 'no archive may be produced when an object cannot be read');
        $this->assertSame([], glob(storage_path('framework/backup-staging/*')) ?: []);
    }

    #[Test]
    public function a_failing_backup_run_fails_the_command_and_still_cleans_up(): void
    {
        $this->stubBackupRun(1);

        $this->artisan('snipeit:backup', ['--with-remote-files' => true])->assertExitCode(1);

        $this->assertSame([], glob(storage_path('framework/backup-staging/*')) ?: []);
    }

    #[Test]
    public function with_only_local_disks_nothing_changes(): void
    {
        config(['filesystems.disks.public' => ['driver' => 'local', 'root' => sys_get_temp_dir()]]);
        config(['filesystems.default' => 'local']);
        Storage::forgetDisk('public');
        Storage::forgetDisk('local');

        $before = config('backup.backup.source.files.include');
        $this->artisan('snipeit:backup', ['--with-remote-files' => true])->assertExitCode(0);

        $this->assertSame([], $this->calls()[0]['extra'], 'no manifest directory is added for all-local installs');
        $this->assertSame($before, config('backup.backup.source.files.include'));
    }

    /**
     * @return array{0: array<int, string>, 1: array<int, string>} existing paths, missing paths
     */
    private function includeWithMissingPaths(): array
    {
        $root = $this->missingRoot = sys_get_temp_dir().'/s3compat-missing-'.bin2hex(random_bytes(4));
        File::ensureDirectoryExists($root.'/uploads');
        file_put_contents($root.'/present.key', 'KEY');
        $missing = [$root.'/oauth-private.key'];
        // A key file the Chiseled image links to a volume that does not have it.
        if (@symlink($root.'/nowhere/oauth-public.key', $root.'/oauth-public.key')) {
            $missing[] = $root.'/oauth-public.key';
        }
        $existing = [$root.'/uploads', $root.'/present.key'];
        config(['backup.backup.source.files.include' => array_merge($existing, $missing)]);

        return [$existing, $missing];
    }

    #[Test]
    public function missing_include_paths_are_left_out_and_named_instead_of_failing_the_backup(): void
    {
        [$existing, $missing] = $this->includeWithMissingPaths();
        $before = config('backup.backup.source.files.include');

        $command = $this->artisan('snipeit:backup', ['--without-remote-files' => true]);
        foreach ($missing as $path) {
            $command->expectsOutputToContain("Skipping {$path}: it does not exist.");
        }
        // A PendingCommand only runs when it is destroyed or run() is called; the calls are read right after.
        $command->assertExitCode(0)->run();

        $include = $this->calls()[0]['include'];
        $this->assertSame($existing, array_slice($include, 0, count($existing)));
        $this->assertCount(count($existing) + 1, $include, 'only the S3 manifest directory is added');
        $this->assertSame([], array_values(array_intersect($missing, $include)));
        $this->assertSame($before, config('backup.backup.source.files.include'), 'the configured list is put back');
    }

    #[Test]
    public function missing_include_paths_are_left_out_on_an_all_local_install_too(): void
    {
        config(['filesystems.disks.public' => ['driver' => 'local', 'root' => sys_get_temp_dir()]]);
        config(['filesystems.default' => 'local']);
        Storage::forgetDisk('public');
        Storage::forgetDisk('local');
        [$existing, $missing] = $this->includeWithMissingPaths();

        $this->artisan('snipeit:backup')->assertExitCode(0);

        $this->assertSame($existing, $this->calls()[0]['include']);
    }

    #[Test]
    public function a_scheduled_backup_gets_a_dated_name_with_the_marker(): void
    {
        $this->artisan('snipeit:backup')->assertExitCode(0);
        $this->assertMatchesRegularExpression('/^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-without-s3\.zip$/', $this->calls()[0]['filename']);

        config(['backup.include_remote_files' => true]);
        $this->stubBackupRun(0);
        $this->artisan('snipeit:backup')->assertExitCode(0);
        $this->assertMatchesRegularExpression('/^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}-with-s3\.zip$/', $this->calls()[0]['filename']);
    }

    #[Test]
    public function a_given_filename_gets_the_marker_and_a_wrong_marker_is_replaced(): void
    {
        $this->artisan('snipeit:backup', ['--filename' => 'manual-backup-1', '--without-remote-files' => true])->assertExitCode(0);
        $this->assertSame('manual-backup-1-without-s3.zip', $this->calls()[0]['filename']);

        $this->stubBackupRun(0);
        $this->artisan('snipeit:backup', ['--filename' => 'x-without-s3.zip', '--with-remote-files' => true])->assertExitCode(0);
        $this->assertSame('x-with-s3.zip', $this->calls()[0]['filename']);

        $this->stubBackupRun(0);
        $this->artisan('snipeit:backup', ['--filename' => 'y-without-s3.ZIP', '--with-remote-files' => true])->assertExitCode(0);
        $this->assertSame('y-with-s3.zip', $this->calls()[0]['filename'], 'an uppercase extension is normalised before the marker is replaced');
    }

    #[Test]
    public function callers_are_told_the_name_the_backup_is_stored_under(): void
    {
        config(['backup.backup.destination.filename_prefix' => 'snipe-it-']);

        $this->artisan('snipeit:backup', ['--filename' => 'before-bulk-delete'])->assertExitCode(0);

        $this->assertSame('snipe-it-'.$this->calls()[0]['filename'], SystemBackup::storedFilename('before-bulk-delete'));
        $this->assertSame('snipe-it-before-bulk-delete-without-s3.zip', SystemBackup::storedFilename('before-bulk-delete'));
    }

    #[Test]
    public function a_failed_run_removes_its_incomplete_zip_from_a_local_backup_disk(): void
    {
        $this->backupRoot = sys_get_temp_dir().'/s3compat-partial-'.bin2hex(random_bytes(4));
        config([
            'filesystems.disks.backup' => ['driver' => 'local', 'root' => $this->backupRoot],
            'backup.backup.name' => 'backups',
            'backup.backup.destination.filename_prefix' => 'snipe-it-',
            'backup.backup.destination.disks' => ['backup'],
        ]);
        Storage::forgetDisk('backup');
        Storage::disk('backup')->put('backups/snipe-it-older-with-s3.zip', 'GOOD');
        $this->stubBackupRun(1, leavesPartialZip: true);

        $this->artisan('snipeit:backup', ['--filename' => 'broken', '--with-remote-files' => true])->assertExitCode(1);

        $this->assertFalse(Storage::disk('backup')->exists('backups/snipe-it-broken-with-s3.zip'), 'the broken zip must not be listed as Included');
        $this->assertTrue(Storage::disk('backup')->exists('backups/snipe-it-older-with-s3.zip'), 'other backups are left alone');
    }

    #[Test]
    public function an_all_local_install_keeps_its_filenames(): void
    {
        config(['filesystems.disks.public' => ['driver' => 'local', 'root' => sys_get_temp_dir()]]);
        config(['filesystems.default' => 'local']);
        Storage::forgetDisk('public');
        Storage::forgetDisk('local');

        $this->artisan('snipeit:backup', ['--filename' => 'manual-backup-1'])->assertExitCode(0);
        $this->assertSame('manual-backup-1.zip', $this->calls()[0]['filename']);

        $this->stubBackupRun(0);
        $this->artisan('snipeit:backup')->assertExitCode(0);
        $this->assertNull($this->calls()[0]['filename'], 'spatie picks the default name');
    }

    #[Test]
    public function the_pre_restore_check_finds_the_marked_backup_and_the_restore_goes_on(): void
    {
        $response = $this->restoreThroughTheWebWithStubbedCommands();

        $response->assertSessionHas('error', fn ($message) => str_contains($message, '-with-s3.zip'));
        $response->assertSessionMissing('success');
        $this->assertNotSame(trans('admin/settings/message.restore.pre_backup_failed'), session('error'));
        $this->assertSame(1, app('s3compat.db-wipes'), 'the restore must get past the pre-restore check');
        $this->assertCount(1, glob($this->backupRoot.'/backups/snipe-it-pre-restore-*-with-s3.zip'));
    }

    #[Test]
    public function the_pre_restore_check_still_works_on_an_all_local_install(): void
    {
        config(['filesystems.disks.public' => ['driver' => 'local', 'root' => sys_get_temp_dir()]]);
        config(['filesystems.default' => 'local']);
        Storage::forgetDisk('public');
        Storage::forgetDisk('local');

        $this->restoreThroughTheWebWithStubbedCommands();

        $this->assertSame(1, app('s3compat.db-wipes'), 'the restore must get past the pre-restore check');
        $this->assertCount(1, glob($this->backupRoot.'/backups/snipe-it-pre-restore-*[0-9].zip'));
    }

    /**
     * Runs the real snipeit:backup inside the web restore. backup:run writes the file it was asked for, and
     * the database wipe and the restore are stubbed so the test database survives; the restore "fails" at
     * its last step so the controller stops right after the part being tested.
     */
    private function restoreThroughTheWebWithStubbedCommands(): \Illuminate\Testing\TestResponse
    {
        $this->backupRoot = sys_get_temp_dir().'/s3compat-prerestore-'.bin2hex(random_bytes(4));
        File::ensureDirectoryExists($this->backupRoot.'/backups');
        config(['filesystems.disks.backup' => ['driver' => 'local', 'root' => $this->backupRoot]]);
        config(['backup.backup.name' => 'backups', 'backup.backup.destination.filename_prefix' => 'snipe-it-']);
        Storage::forgetDisk('backup');

        $zip = new \ZipArchive;
        $zip->open($this->backupRoot.'/backups/source.zip', \ZipArchive::CREATE);
        $zip->addFromString('db-dumps/mysql-test.sql', 'SELECT 1;');
        $zip->close();

        $root = $this->backupRoot;
        app()->instance('s3compat.db-wipes', 0);
        Artisan::command('backup:run {--filename=}', function () use ($root) {
            file_put_contents($root.'/backups/'.config('backup.backup.destination.filename_prefix').($this->option('filename') ?? 'default.zip'), 'zip');

            return 0;
        })->purpose('stub');
        Artisan::command('db:wipe {--force}', function () {
            app()->instance('s3compat.db-wipes', app('s3compat.db-wipes') + 1);

            return 0;
        })->purpose('stub');
        Artisan::command('snipeit:restore {filename?} {--validate-only} {--force} {--no-progress}', function () {
            return $this->option('validate-only') ? 0 : 1;
        })->purpose('stub');

        return $this->actingAs(User::factory()->superuser()->create())
            ->post(route('settings.backups.restore', 'source.zip'));
    }

    #[Test]
    public function callers_that_used_backup_run_directly_now_include_remote_files(): void
    {
        foreach (['app/Http/Controllers/SettingsController.php', 'app/Console/Commands/RegenerateAssetTags.php', 'app/Console/Commands/RestoreDeletedUsers.php'] as $file) {
            $source = file_get_contents(base_path($file));
            $this->assertStringNotContainsString("'backup:run'", $source, $file.' must call snipeit:backup');
            $this->assertStringContainsString('--with-remote-files', $source, $file);
        }
    }
}
