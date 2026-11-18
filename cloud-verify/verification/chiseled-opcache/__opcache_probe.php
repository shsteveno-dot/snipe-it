<?php
// Test-only probe, bind-mounted read-only into a disposable container; never part of the image.
header('Content-Type: application/json');
$status = function_exists('opcache_get_status') ? opcache_get_status(false) : false;
echo json_encode([
    'sapi' => PHP_SAPI,
    'loaded' => extension_loaded('Zend OPcache'),
    'enabled' => is_array($status) ? (bool) $status['opcache_enabled'] : false,
    'hits' => is_array($status) ? $status['opcache_statistics']['hits'] : null,
    'jit' => ini_get('opcache.jit'),
    'file_cache' => ini_get('opcache.file_cache'),
    'memory_consumption' => ini_get('opcache.memory_consumption'),
]);
