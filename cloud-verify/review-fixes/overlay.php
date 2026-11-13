<?php
/* Build-time only: copy development files missing from the candidate and the
 * Composer-generated autoload metadata. Production package files are never
 * copied over the candidate, including its patched database dumper. */
$source = '/dev-vendor';
$existing = '/candidate-vendor';
$destination = '/overlay';
$metadata = [
    'autoload.php', 'composer/autoload_classmap.php', 'composer/autoload_files.php',
    'composer/autoload_namespaces.php', 'composer/autoload_psr4.php',
    'composer/autoload_real.php', 'composer/autoload_static.php',
    'composer/installed.json', 'composer/installed.php', 'composer/platform_check.php',
];
$iterator = new RecursiveIteratorIterator(
    new RecursiveDirectoryIterator($source, FilesystemIterator::SKIP_DOTS),
    RecursiveIteratorIterator::SELF_FIRST
);
foreach ($iterator as $item) {
    $relative = substr($item->getPathname(), strlen($source) + 1);
    $target = $destination.'/'.$relative;
    if ($item->isDir() && ! $item->isLink()) {
        if (! is_dir($target) && ! mkdir($target, 0755, true)) {
            throw new RuntimeException('Cannot create overlay directory');
        }
        continue;
    }
    if (file_exists($existing.'/'.$relative) || is_link($existing.'/'.$relative)) {
        if (! in_array($relative, $metadata, true)) {
            continue;
        }
    }
    if (! is_dir(dirname($target))) {
        mkdir(dirname($target), 0755, true);
    }
    if ($item->isLink()) {
        if (! symlink(readlink($item->getPathname()), $target)) {
            throw new RuntimeException('Cannot copy overlay symlink');
        }
    } elseif (! copy($item->getPathname(), $target)) {
        throw new RuntimeException('Cannot copy overlay file');
    }
}