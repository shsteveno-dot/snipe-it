<?php

namespace Tests\Feature\S3Compatibility;

use App\Models\User;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\File;
use Illuminate\Support\Facades\Storage;
use PHPUnit\Framework\Attributes\Test;
use Tests\Support\S3Compatibility\UsesFakeRemoteDisks;
use Tests\TestCase;
use ZipArchive;

/**
 * FR-11a / FR-13: the backup page offers "with / without S3 files" (default: without) only when a disk is
 * remote, labels each backup, and states the limits.
 */
class BackupPageTest extends TestCase
{
    use UsesFakeRemoteDisks;

    private string $backupRoot;

    protected function setUp(): void
    {
        parent::setUp();

        $this->backupRoot = sys_get_temp_dir().'/s3compat-page-'.bin2hex(random_bytes(4));
        File::ensureDirectoryExists($this->backupRoot.'/backups');
        config(['filesystems.disks.backup' => ['driver' => 'local', 'root' => $this->backupRoot]]);
        Storage::forgetDisk('backup');
    }

    protected function tearDown(): void
    {
        File::deleteDirectory($this->backupRoot);
        $this->cleanUpFakeRemoteDisks();

        parent::tearDown();
    }

    private function remoteDisks(): void
    {
        $this->fakeRemoteDisk('public');
        $this->fakeRemoteDisk('custom_private');
        config(['filesystems.default' => 'custom_private']);
        Storage::forgetDisk('custom_private');
    }

    private function page()
    {
        return $this->actingAs(User::factory()->superuser()->create())->get(route('settings.backups.index'));
    }

    private function zip(string $name, ?array $manifest): void
    {
        $zip = new ZipArchive;
        $zip->open($this->backupRoot.'/backups/'.$name, ZipArchive::CREATE);
        $zip->addFromString('db-dumps/mysql-test.sql', 'SELECT 1;');
        if ($manifest !== null) {
            $zip->addFromString('storage/framework/backup-staging/x/snipeit-remote-manifest.json', json_encode($manifest));
        }
        $zip->close();
    }

    #[Test]
    public function remote_disks_show_both_choices_with_without_preselected_and_the_limits(): void
    {
        $this->remoteDisks();

        $response = $this->page()->assertOk();

        $response->assertSee('name="include_remote_files"', false);
        $response->assertSee(trans('admin/settings/general.backups_remote_without'), false);
        $response->assertSee(trans('admin/settings/general.backups_remote_with'), false);
        $html = $response->getContent();
        $this->assertMatchesRegularExpression('/<input[^>]*name="include_remote_files"[^>]*value="0"[^>]*checked/s', $html);
        $this->assertDoesNotMatchRegularExpression('/<input[^>]*name="include_remote_files"[^>]*value="1"[^>]*checked/s', $html);
        $response->assertSee(trans('admin/settings/general.backups_remote_not_included'), false);
        $response->assertSee(trans('admin/settings/general.backups_remote_limits'), false);
        $response->assertSee(trans('admin/settings/general.backups_remote_quiesce'), false);
    }

    #[Test]
    public function all_local_installs_see_no_new_option_or_notice(): void
    {
        config(['filesystems.default' => 'local']);
        Storage::forgetDisk('local');

        $response = $this->page()->assertOk();

        $response->assertDontSee('include_remote_files', false);
        $response->assertDontSee(trans('admin/settings/general.backups_remote_limits'), false);
    }

    #[Test]
    public function marked_backups_keep_their_label_after_uploads_move_back_to_local_disks(): void
    {
        config(['filesystems.default' => 'local']);
        Storage::forgetDisk('local');
        $this->zip('snipe-it-legacy.zip', null);

        $this->page()->assertOk()->assertDontSee('<th scope="col">'.trans('admin/settings/general.backups_remote_label').'</th>', false);

        $this->zip('snipe-it-a-with-s3.zip', null);

        $response = $this->page()->assertOk();
        $response->assertSee('<th scope="col">'.trans('admin/settings/general.backups_remote_label').'</th>', false);
        $response->assertSee('<td>'.trans('admin/settings/general.backups_remote_label_included').'</td>', false);
        $response->assertDontSee('include_remote_files', false);
    }

    #[Test]
    public function the_generate_button_passes_the_choice_on(): void
    {
        $this->remoteDisks();
        $seen = [];
        Artisan::command('snipeit:backup {--filename=} {--force} {--with-remote-files} {--without-remote-files}', function () use (&$seen) {
            $seen[] = [
                'with' => (bool) $this->option('with-remote-files'),
                'without' => (bool) $this->option('without-remote-files'),
            ];

            return 0;
        })->purpose('stub');
        $admin = User::factory()->superuser()->create();

        $this->actingAs($admin)->post(route('settings.backups.create'), ['include_remote_files' => '1']);
        $this->actingAs($admin)->post(route('settings.backups.create'), ['include_remote_files' => '0']);
        $this->actingAs($admin)->post(route('settings.backups.create'), []);

        $this->assertSame([true, false], [$seen[0]['with'], $seen[0]['without']]);
        $this->assertSame([false, true], [$seen[1]['with'], $seen[1]['without']]);
        $this->assertSame([false, true], [$seen[2]['with'], $seen[2]['without']], 'no choice means the default: without');
    }

    #[Test]
    public function a_failed_backup_shows_the_reason_rather_than_a_progress_line(): void
    {
        Artisan::command('snipeit:backup {--filename=} {--force} {--with-remote-files} {--without-remote-files}', function () {
            $this->line('Starting backup...');
            $this->line('Dumping database snipeit...');
            $this->line('Determining files to backup...');
            $this->line('Backup failed because: The "/var/www/html/storage/oauth-private.key" directory does not exist..');
            $this->line('#0 /var/www/html/vendor/spatie/laravel-backup/src/Tasks/Backup/FileSelection.php(85)');

            return 1;
        })->purpose('stub');

        $this->actingAs(User::factory()->superuser()->create())
            ->post(route('settings.backups.create'), ['include_remote_files' => '0'])
            ->assertRedirect(route('settings.backups.index'))
            ->assertSessionHas('error', 'Backup failed because: The "/var/www/html/storage/oauth-private.key" directory does not exist..');
    }

    #[Test]
    public function backups_on_a_local_backup_disk_are_labelled_from_the_name_not_the_manifest(): void
    {
        $this->remoteDisks();
        $this->zip('snipe-it-a-with-s3.zip', ['version' => 1, 'remote_files' => 'excluded', 'files' => []]);
        $this->zip('snipe-it-b-without-s3.zip', ['version' => 1, 'remote_files' => 'included', 'files' => []]);
        $this->zip('snipe-it-legacy.zip', ['version' => 1, 'remote_files' => 'included', 'files' => []]);

        $response = $this->page()->assertOk();
        $files = collect($response->viewData('files'))->keyBy('filename');

        $this->assertSame('included', $files['snipe-it-a-with-s3.zip']['remote_files']);
        $this->assertSame('excluded', $files['snipe-it-b-without-s3.zip']['remote_files']);
        $this->assertSame('unknown', $files['snipe-it-legacy.zip']['remote_files']);
        $response->assertSee('<td>'.trans('admin/settings/general.backups_remote_label_included').'</td>', false);
        $response->assertSee('<td>'.trans('admin/settings/general.backups_remote_label_excluded').'</td>', false);
        $response->assertSee('<td>'.trans('admin/settings/general.backups_remote_label_unknown').'</td>', false);
    }

    #[Test]
    public function backups_on_a_remote_backup_disk_are_labelled_from_the_name_without_downloading_them(): void
    {
        $this->remoteDisks();
        $this->fakeRemoteDisk('backup');
        Storage::disk('backup')->put('backups/snipe-it-a-with-s3.zip', 'zipbytes');
        Storage::disk('backup')->put('backups/snipe-it-b-without-s3.zip', 'zipbytes');
        Storage::disk('backup')->put('backups/snipe-it-legacy.zip', 'zipbytes');
        \Tests\Support\S3Compatibility\FakeRemoteAdapter::$log = [];

        $files = collect($this->page()->assertOk()->viewData('files'))->keyBy('filename');

        $this->assertSame('included', $files['snipe-it-a-with-s3.zip']['remote_files']);
        $this->assertSame('excluded', $files['snipe-it-b-without-s3.zip']['remote_files']);
        $this->assertSame('unknown', $files['snipe-it-legacy.zip']['remote_files']);
        $this->assertSame([], \Tests\Support\S3Compatibility\FakeRemoteAdapter::keysFor('read'), 'listing must not read backup contents');
    }

    #[Test]
    public function an_uploaded_copy_keeps_its_label(): void
    {
        $this->remoteDisks();
        $this->zip('uploaded-1790000000-snipe-it-a-without-s3.zip', null);
        $this->zip('uploaded-1790000001-snipe-it-b-with-s3-1.zip', null);

        $files = collect($this->page()->assertOk()->viewData('files'))->keyBy('filename');

        $this->assertSame('excluded', $files['uploaded-1790000000-snipe-it-a-without-s3.zip']['remote_files']);
        $this->assertSame('included', $files['uploaded-1790000001-snipe-it-b-with-s3-1.zip']['remote_files']);
    }
}
