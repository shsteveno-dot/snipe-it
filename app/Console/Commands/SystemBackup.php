<?php

namespace App\Console\Commands;

use App\Services\RemoteUploadsException;
use App\Services\RemoteUploadsStager;
use Illuminate\Console\Command;
use Illuminate\Support\Facades\Storage;
use Spatie\Backup\Commands\BackupCommand;
use Spatie\Backup\Config\Config;

class SystemBackup extends Command
{
    /**
     * The console command name.
     *
     * @var string
     */
    // --force is accepted for parity with other Laravel commands that require
    // it (migrate, db:seed, etc.); it doesn't gate anything here but external
    // automations were passing it and crashing on the "option does not exist"
    // error.
    protected $signature = 'snipeit:backup {--filename=} {--force} {--with-remote-files : Also copy files that are stored on S3 into the backup} {--without-remote-files : Leave files that are stored on S3 out of the backup}';

    /**
     * The console command description.
     *
     * @var string
     */
    protected $description = 'This command creates a database dump and zips up all of the uploaded files in the upload directories.';

    /**
     * Create a new command instance.
     *
     * @return void
     */
    public function __construct()
    {
        parent::__construct();
    }

    /**
     * Execute the console command.
     *
     * @return mixed
     */
    public function handle()
    {
        ini_set('max_execution_time', config('backup.time_limit')); // 600 seconds = 10 minutes

        if ($this->option('with-remote-files') && $this->option('without-remote-files')) {
            $this->error('Use either --with-remote-files or --without-remote-files, not both.');

            return self::FAILURE;
        }

        // The flags win over BACKUP_INCLUDE_REMOTE_FILES, which is what scheduled backups use.
        $includeRemote = $this->option('with-remote-files')
            ? true
            : ($this->option('without-remote-files') ? false : (bool) config('backup.include_remote_files'));

        $stager = new RemoteUploadsStager(RemoteUploadsStager::defaultBase());
        $include = config('backup.backup.source.files.include');
        $existing = $this->existingPaths($include);
        $filename = self::filenameForRun($stager, $this->option('filename') ?: null, $includeRemote);
        $arguments = $filename === null ? [] : ['--filename' => $filename];

        try {
            if ($stager->needsStaging()) {
                if ($includeRemote) {
                    $this->info('Copying the files stored on S3 for the backup...');
                    $extra = $stager->stage()['root'];
                } else {
                    $this->warn('S3 files are not part of this backup. Use --with-remote-files to include them.');
                    $extra = $stager->markExcluded();
                }

                // Spatie reads this directory like any other include, so the copies end up in the zip.
                $this->useIncludes(array_merge($existing, [$extra]));
            } elseif ($existing !== $include) {
                $this->useIncludes($existing);
            }

            // Pass the exit code on, so a failed backup is not reported as a success.
            $exitCode = $this->call('backup:run', $arguments);

            if ($exitCode !== self::SUCCESS && $filename !== null && $stager->needsStaging()) {
                $this->removeIncompleteBackup($filename);
            }

            return $exitCode;
        } catch (RemoteUploadsException $e) {
            $this->error($e->getMessage());
            $this->error('The backup was not created.');

            return self::FAILURE;
        } finally {
            $this->useIncludes($include);
            $stager->cleanup();
        }
    }

    /**
     * The name the backup is stored under on the backup disk, prefix included, for callers that tell the
     * operator where to find it. Without a flag, the backup follows BACKUP_INCLUDE_REMOTE_FILES.
     */
    public static function storedFilename(string $filename, ?bool $includeRemote = null): string
    {
        $stager = new RemoteUploadsStager(RemoteUploadsStager::defaultBase());

        return config('backup.backup.destination.filename_prefix', '')
            .self::filenameForRun($stager, $filename, $includeRemote ?? (bool) config('backup.include_remote_files'));
    }

    /**
     * The --filename handed to backup:run: always ending in a lowercase .zip, with the S3 marker when a disk
     * is remote. Null lets spatie pick its dated default on all-local installs.
     */
    private static function filenameForRun(RemoteUploadsStager $stager, ?string $filename, bool $includeRemote): ?string
    {
        if ($filename === null && ! $stager->needsStaging()) {
            return null;
        }

        return $stager->backupFilename($filename ?? now()->format('Y-m-d-H-i-s'), $includeRemote);
    }

    /**
     * Spatie hands every include that is not a file to Finder as a directory, so one missing path fails the
     * whole backup ("The ... directory does not exist"). The OAuth keys are the usual case: when Passport
     * reads them from PASSPORT_PRIVATE_KEY/PASSPORT_PUBLIC_KEY there are no key files, and in the Chiseled
     * image storage/oauth-*.key are then symlinks to nothing. Missing paths are left out and named.
     *
     * @param  array<int, string>  $include
     * @return array<int, string>
     */
    private function existingPaths(array $include): array
    {
        $existing = [];
        foreach ($include as $path) {
            // file_exists() follows symlinks, so a link to a missing target counts as missing.
            if (file_exists($path)) {
                $existing[] = $path;
            } else {
                $this->warn("Skipping {$path}: it does not exist.");
            }
        }

        return $existing;
    }

    /**
     * Spatie writes straight to the final name, so a copy that fails half way leaves a broken zip behind that
     * the backup page would label from its name. Only local disks can hold such a partial file; an object
     * store either has the whole upload or nothing.
     */
    private function removeIncompleteBackup(string $filename): void
    {
        $path = config('backup.backup.name').'/'.config('backup.backup.destination.filename_prefix', '').$filename;

        foreach (config('backup.backup.destination.disks', []) as $diskName) {
            if (config("filesystems.disks.{$diskName}.driver") !== 'local') {
                continue;
            }

            $disk = Storage::disk($diskName);
            if ($disk->exists($path)) {
                $disk->delete($path);
                $this->warn("Removed the incomplete backup {$path} from the {$diskName} disk.");
            }
        }
    }

    /**
     * Spatie builds its settings object once from the config and hands it to the backup:run command when
     * the console starts, so a changed include list only counts after that object is rebuilt and the
     * command is created again.
     *
     * @param  array<int, string>  $include
     */
    private function useIncludes(array $include): void
    {
        config(['backup.backup.source.files.include' => $include]);
        app()->forgetInstance(Config::class);

        $application = $this->getApplication();
        if ($application !== null && $application->has('backup:run') && $application->find('backup:run') instanceof BackupCommand) {
            $application->add(app(BackupCommand::class));
        }
    }
}
