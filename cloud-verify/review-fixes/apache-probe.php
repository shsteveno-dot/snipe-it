<?php
/* Run inside the candidate-derived test image, with the diagnostic endpoint
 * mounted only into the separate production candidate container. */
$url = getenv('REVIEW_APACHE_URL');
if (! $url) {
    fwrite(STDERR, "REVIEW_APACHE_URL is required\n");
    exit(2);
}
$context = stream_context_create(['http' => [
    'header' => "X-Review-User: review-user@example.invalid\r\n",
    'timeout' => 10,
    'ignore_errors' => true,
]]);
$body = @file_get_contents($url, false, $context);
if ($body === false || trim($body) !== 'review-user@example.invalid') {
    fwrite(STDERR, "Forwarded header was not promoted to REMOTE_USER\n");
    exit(1);
}
echo "Forwarded header promoted to REMOTE_USER\n";