<?php
/* Test-only endpoint. Mount read-only into a disposable candidate, never ship. */
header('Content-Type: text/plain');
echo $_SERVER['REMOTE_USER'] ?? '';