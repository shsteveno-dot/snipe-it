<?php
/* Execute in a test image derived from the marker-built candidate. */
$path = '/var/www/html/storage/framework/backup-staging';
if (file_exists($path) || is_link($path)) {
    fwrite(STDERR, "Backup staging exists in the candidate image\n");
    exit(1);
}
echo "Backup staging is absent from the candidate image\n";