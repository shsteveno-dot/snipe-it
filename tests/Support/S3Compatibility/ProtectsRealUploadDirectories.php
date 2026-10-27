<?php

namespace Tests\Support\S3Compatibility;

use App\Console\Commands\RestoreFromBackup;
use App\Enums\FileStorage;
use Illuminate\Support\Facades\File;

/**
 * For tests that run snipeit:restore or snipeit:move-uploads against the local upload directories of this
 * checkout. Those commands prune or delete everything in the directories, so the test refuses to run (it
 * is skipped) when they hold anything but placeholder files, and takes a lock so that two test processes
 * do not use the directories at the same time.
 */
trait ProtectsRealUploadDirectories
{
    /** Files that are part of the repository; commands under test may move or prune them, so they are put back. */
    private const SHIPPED_FILES = [
        'public/uploads/barcodes/invalid_barcode.gif',
        'public/uploads/companies/company-image-test.png',
        'public/uploads/default.png',
        'public/uploads/snipe-logo.png',
    ];

    /** @var resource|null */
    private $uploadDirectoriesLock = null;

    /**
     * Tracked files that snipeit:move-uploads --delete-local would delete from the checkout. They are put
     * back when the test ends.
     *
     * @var array<string, string>
     */
    private array $trackedUploadFiles = [];

    protected function protectRealUploadDirectories(): void
    {
        $lock = fopen(sys_get_temp_dir().'/snipeit-upload-directories.lock', 'c');
        if ($lock !== false) {
            flock($lock, LOCK_EX);
            $this->uploadDirectoriesLock = $lock;
        }

        $leftover = array_values(array_filter(
            $this->uploadFilesInThisCheckout(),
            fn (string $found) => ! in_array($found, self::SHIPPED_FILES, true),
        ));
        if ($leftover !== []) {
            $this->releaseRealUploadDirectories();
            $this->markTestSkipped('This checkout has uploaded files ('.$leftover[0].' and '.(count($leftover) - 1).' more) in the directories the command prunes or moves. Run this test in a clean checkout or CI.');
        }

        foreach (self::SHIPPED_FILES as $relative) {
            if (is_file(base_path($relative))) {
                $this->trackedUploadFiles[$relative] = (string) file_get_contents(base_path($relative));
            }
        }
    }

    protected function releaseRealUploadDirectories(): void
    {
        foreach ($this->trackedUploadFiles as $relative => $contents) {
            if (! is_file(base_path($relative)) || file_get_contents(base_path($relative)) !== $contents) {
                File::ensureDirectoryExists(dirname(base_path($relative)));
                file_put_contents(base_path($relative), $contents);
            }
        }
        $this->trackedUploadFiles = [];

        if ($this->uploadDirectoriesLock !== null) {
            flock($this->uploadDirectoriesLock, LOCK_UN);
            fclose($this->uploadDirectoriesLock);
            $this->uploadDirectoriesLock = null;
        }
    }

    /** @return array<int, string> */
    private function uploadFilesInThisCheckout(): array
    {
        $directories = array_merge(
            FileStorage::publicDirsForRestore(),
            array_values(FileStorage::privateDirsForRestore()),
            array_filter(array_keys(FileStorage::privateDirsForRestore()), 'is_string'),
            [FileStorage::Backups->privateDir()],
        );

        $found = [];
        foreach (array_unique($directories) as $relative) {
            $directory = base_path($relative);
            if (! is_dir($directory)) {
                continue;
            }
            $files = new \RecursiveIteratorIterator(new \RecursiveDirectoryIterator($directory, \FilesystemIterator::SKIP_DOTS));
            foreach ($files as $file) {
                if ($file->isFile() && ! in_array($file->getFilename(), ['.gitkeep', '.gitignore', '.DS_Store'], true)) {
                    $found[] = $relative.'/'.substr($file->getPathname(), strlen($directory) + 1);
                }
            }
        }
        foreach (RestoreFromBackup::PUBLIC_FILES as $pattern) {
            foreach (glob(base_path($pattern)) ?: [] as $path) {
                $found[] = $pattern.' => '.basename($path);
            }
        }

        return $found;
    }
}
