<?php

namespace Tests\Feature\S3Compatibility;

use App\Models\User;
use Illuminate\Support\Facades\File;
use Illuminate\Support\Facades\Storage;
use PHPUnit\Framework\Attributes\Test;
use Tests\TestCase;
use ZipArchive;

/**
 * The web restore wipes the database before it runs snipeit:restore, so it has to know beforehand that the
 * archive (manifest, sizes, checksums) will be accepted. A backup that fails that check must leave the
 * database as it was and say so.
 */
class WebRestoreValidatesBeforeWipeTest extends TestCase
{
    private string $workDir = '';

    protected function setUp(): void
    {
        parent::setUp();

        $this->workDir = sys_get_temp_dir().'/s3compat-webrestore-'.bin2hex(random_bytes(4));
        File::ensureDirectoryExists($this->workDir.'/backup-disk/'.config('backup.backup.name', 'backups'));
        config(['filesystems.disks.backup' => ['driver' => 'local', 'root' => $this->workDir.'/backup-disk']]);
        Storage::forgetDisk('backup');
    }

    protected function tearDown(): void
    {
        if ($this->workDir !== '') {
            File::deleteDirectory($this->workDir);
        }

        parent::tearDown();
    }

    private function plantBackup(string $manifestSha): string
    {
        $filename = 'webrestore-'.bin2hex(random_bytes(3)).'.zip';
        $stage = 'storage/framework/backup-staging/'.bin2hex(random_bytes(6));
        $bytes = 'AVATAR-BYTES';

        $zip = new ZipArchive;
        $zip->open($this->workDir.'/backup-disk/'.config('backup.backup.name', 'backups').'/'.$filename, ZipArchive::CREATE);
        $zip->addFromString('db-dumps/mysql-test.sql', "DROP TABLE IF EXISTS `s3compat_probe`;\nCREATE TABLE `s3compat_probe` (`id` int);\n");
        $zip->addFromString($stage.'/public/uploads/avatars/x.png', $bytes);
        $zip->addFromString($stage.'/snipeit-remote-manifest.json', json_encode([
            'version' => 1,
            'created_at' => date('c'),
            'remote_files' => 'included',
            'files' => [[
                'role' => 'public',
                'key' => 'avatars/x.png',
                'archive_path' => 'public/uploads/avatars/x.png',
                'bytes' => strlen($bytes),
                'sha256' => $manifestSha,
            ]],
        ]));
        $zip->close();

        return $filename;
    }

    #[Test]
    public function an_archive_whose_manifest_does_not_match_is_refused_before_the_database_is_touched(): void
    {
        $admin = User::factory()->superuser()->create();
        $filename = $this->plantBackup(str_repeat('0', 64));

        $this->actingAs($admin)
            ->post(route('settings.backups.restore', $filename))
            ->assertRedirect(route('settings.backups.index'))
            ->assertSessionHas('error', fn ($message) => str_contains($message, 'Restore aborted before touching the database'));

        $this->assertDatabaseHas('users', ['id' => $admin->id]);
    }
}
