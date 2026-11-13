<?php
/* Execute in the candidate-derived image against the disposable candidate. */
if ($argc !== 4) {
    fwrite(STDERR, "usage: apache-probe.php URL EXPECTED HEADER_VALUE\n");
    exit(2);
}
[, $url, $expected, $header] = $argv;
$context = stream_context_create(['http' => [
    'header' => "X-Review-User: ".$header."\r\n",
    'timeout' => 10,
    'ignore_errors' => true,
]]);
$body = @file_get_contents($url, false, $context);
if ($body === false) {
    fwrite(STDERR, "Apache endpoint is unavailable\n");
    exit(2);
}
if (trim($body) !== $expected) {
    fwrite(STDERR, "REMOTE_USER did not match the expected value\n");
    exit(1);
}
echo "REMOTE_USER matched\n";