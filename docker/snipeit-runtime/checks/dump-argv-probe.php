<?php

require '/var/www/html/vendor/autoload.php';
function fixtureEnv(string $assignment): void
{
    putenv($assignment);
    [$key,$value] = array_pad(explode('=', $assignment, 2), 2, null);
    if ($value === null) {
        unset($_ENV[$key],$_SERVER[$key]);
    } else {
        $_ENV[$key] = $value;
        $_SERVER[$key] = $value;
    }
}
function checkDump(bool $condition, string $message): void
{
    if (! $condition) {
        throw new RuntimeException($message);
    }
}
function fixtureDumper(string $directory, string $class = Spatie\DbDumper\Databases\MySql::class): object
{
    return $class::create()->setHost('fixture-host')->setPort(3307)->setDbName('fixture')->setUserName('fixture-user')->setPassword('fixture-password')->setDumpBinaryPath($directory);
}
function readCapture(string $capture): array
{
    return json_decode(file_get_contents($capture), true, flags: JSON_THROW_ON_ERROR);
}
function cleanDumpFixture(string $directory): void
{
    foreach (scandir($directory) as $file) {
        if ($file === '.' || $file === '..') {
            continue;
        }$p = $directory.'/'.$file;
        if (is_dir($p)) {
            cleanDumpFixture($p);
        } else {
            unlink($p);
        }
    }
    rmdir($directory);
}
function makeDumpFixture(): array
{
    $root = '/tmp/dump argv '.bin2hex(random_bytes(5));
    mkdir($root);
    $capture = $root.'/capture.json';
    fixtureEnv('DUMP_CAPTURE='.$capture);
    fixtureEnv('DUMP_MODE=success');
    $client = <<<'PHP'
<?php
$credentials=null;$output=null;
foreach(array_slice($argv,1) as $arg){
 if(str_starts_with($arg,'--defaults-extra-file='))$credentials=substr($arg,22);
 if(str_starts_with($arg,'--result-file='))$output=substr($arg,14);
}
$contents=$credentials!==null?file_get_contents($credentials):'';
$capture=['script'=>$argv[0],'argv'=>array_slice($argv,1),'credentials_valid'=>str_contains($contents,"password = 'fixture-password'")&&str_contains($contents,"user = 'fixture-user'"),'environment'=>getenv('DUMP_MARKER')];
file_put_contents(getenv('DUMP_CAPTURE'),json_encode($capture,JSON_THROW_ON_ERROR));
fwrite(STDOUT,"fixture stdout\n");fwrite(STDERR,"fixture stderr\n");
$mode=getenv('DUMP_MODE');if($mode==='timeout')usleep(2500000);if($mode==='nonzero')exit(23);if($mode==='missing')exit(0);
if($output!==null)file_put_contents($output,$mode==='empty'?'':"CREATE TABLE fixture (id INT);\nINSERT INTO fixture VALUES (42);\n");
PHP;
    foreach (['mysqldump', 'mariadb-dump'] as $binary) {
        file_put_contents($root.'/'.$binary, '#!'.PHP_BINARY."\n".$client);
        chmod($root.'/'.$binary, 0755);
    }

    return [$root, $capture];
}
function exactDump(): void
{
    [$root,$capture] = makeDumpFixture();
    try {
        $control = new Symfony\Component\Process\Process([$root.'/mysqldump', '--result-file='.$root.'/control.sql']);
        $control->mustRun();
        checkDump(is_file($root.'/control.sql'), 'direct-array executable control');
        unlink($capture);
        fixtureDumper($root)->dumpToFile($root.'/output.sql');
        $seen = readCapture($capture);
        checkDump($seen['script'] === $root.'/mysqldump', 'exact executable path');
        $args = $seen['argv'];
        checkDump(str_starts_with(array_shift($args), '--defaults-extra-file='), 'credentials option first');
        checkDump($args === ['--skip-comments', '--extended-insert', 'fixture', '--result-file='.$root.'/output.sql'], 'exact default argv');
        checkDump($seen['credentials_valid'], 'credentials preserved');
        checkDump(! str_contains(json_encode($seen['argv']), 'fixture-password'), 'password absent from argv');
        checkDump(! file_exists(substr($seen['argv'][0], 22)), 'temporary credentials closed and removed');
        checkDump(str_contains(file_get_contents($root.'/output.sql'), 'VALUES (42)'), 'intended dump output');
        echo 'observed_default_argv=',json_encode($seen['argv']),"\n";
    } finally {
        cleanDumpFixture($root);
    }
}
function structuredDump(): void
{
    [$root,$capture] = makeDumpFixture();
    try {
        $literal = 'name "double" \'single\' $HOME `touch sentinel` $(touch sentinel) ; | > * ?';
        fixtureEnv('DUMP_MARKER=environment-preserved');
        $output = $root.'/out "quoted" file.sql';
        fixtureDumper($root)->setDbName($literal)->setSocket('/tmp/socket with "quotes"')->setDefaultCharacterSet('charset with spaces')->setGtidPurged('')->includeTables([$literal, ''])->dumpToFile($output);
        $seen = readCapture($capture);
        $args = $seen['argv'];
        array_shift($args);
        checkDump($args === ['--skip-comments', '--extended-insert', '--socket=/tmp/socket with "quotes"', '--default-character-set=charset with spaces', '--set-gtid-purged=', $literal, '--tables', $literal, '', '--result-file='.$output], 'structured quotes/empty/metacharacters preserved');
        checkDump($seen['environment'] === 'environment-preserved', 'environment propagation');
        fixtureDumper($root)->setDbName($literal)->excludeTables([$literal])->dumpToFile($output);
        $args = readCapture($capture)['argv'];
        checkDump(in_array('--ignore-table='.$literal.'.'.$literal, $args, true), 'exclude table preserved');
        fixtureDumper($root)->doNotCreateTables()->doNotDumpData()->dontSkipComments()->dontUseExtendedInserts()->useSingleTransaction()->skipLockTables()->doNotUseColumnStatistics()->useQuick()->setGtidPurged('OFF')->dumpToFile($root.'/flags');
        $flags = readCapture($capture)['argv'];
        array_shift($flags);
        checkDump($flags === ['--no-create-info', '--no-data', '--skip-extended-insert', '--single-transaction', '--skip-lock-tables', '--column-statistics=0', '--quick', '--set-gtid-purged=OFF', 'fixture', '--result-file='.$root.'/flags'], 'flag order and values');
        $caught = false;
        try {
            fixtureDumper($root)->setDbName("bad\0name")->dumpToFile($root.'/nul');
        } catch (InvalidArgumentException $e) {
            $caught = true;
        }
        checkDump($caught, 'NUL rejected before spawn');
        checkDump(! file_exists('/var/www/html/sentinel'), 'no command side effect');
        echo 'observed_structured_argv=',json_encode($seen['argv']),"\n";
    } finally {
        cleanDumpFixture($root);
        fixtureEnv('DUMP_MARKER');
    }
}
function legacyDump(): void
{
    [$root,$capture] = makeDumpFixture();
    try {
        $fragment = <<<'OPTIONS'
--label="two words" --quote='say "hello"' --escaped="say \"hello\"" --empty="" "" '$HOME' '`touch sentinel`' '$(touch sentinel)' ';' '|' '>' '*' '?'
OPTIONS;
        fixtureDumper($root)->addExtraOption($fragment)->addExtraOption('')->addExtraOptionAfterDbName('--after="tail words"')->dumpToFile($root.'/out');
        $args = readCapture($capture)['argv'];
        array_shift($args);
        checkDump($args === ['--skip-comments', '--extended-insert', '--label=two words', '--quote=say "hello"', '--escaped=say "hello"', '--empty=', '', '$HOME', '`touch sentinel`', '$(touch sentinel)', ';', '|', '>', '*', '?', 'fixture', '--after=tail words', '--result-file='.$root.'/out'], 'legacy lexical exact tokens');
        echo 'observed_legacy_argv=',json_encode($args),"\n";
        foreach (['--databases first second', '--all-databases'] as $fragment) {
            fixtureDumper($root)->addExtraOption($fragment)->dumpToFile($root.'/out');
            $args = readCapture($capture)['argv'];
            checkDump(! in_array('fixture', $args, true), 'vendor db-name state preserved');
            foreach (explode(' ', $fragment) as $token) {
                checkDump(in_array($token, $args, true), 'legacy database tokens');
            }
        }
        unlink($capture);
        $caught = false;
        try {
            fixtureDumper($root)->addExtraOption('--broken="unclosed')->dumpToFile($root.'/out');
        } catch (Throwable $e) {
            $caught = true;
        }
        checkDump($caught && ! file_exists($capture), 'malformed grouping rejected before child');
        checkDump(! file_exists('/var/www/html/sentinel'), 'legacy no command side effect');
    } finally {
        cleanDumpFixture($root);
    }
}
function failedDump(): void
{
    [$root,$capture] = makeDumpFixture();
    try {
        foreach (['nonzero', 'missing', 'empty'] as $mode) {
            fixtureEnv('DUMP_MODE='.$mode);
            $caught = null;
            try {
                fixtureDumper($root)->dumpToFile($root.'/'.$mode);
            } catch (Throwable $e) {
                $caught = $e;
            }
            checkDump($caught !== null, 'rejected '.$mode);
            if ($mode === 'nonzero') {
                checkDump(str_contains($caught->getMessage(), 'fixture stderr') && str_contains($caught->getMessage(), 'fixture stdout') && str_contains($caught->getMessage(), '23'), 'stdout/stderr/nonzero exit preserved');
            }
            echo 'rejected_mode=',$mode,' error_class=',get_class($caught),"\n";
        }
        $caught = false;
        try {
            fixtureDumper($root.'/nonexistent')->dumpToFile($root.'/launch');
        } catch (Throwable $e) {
            $caught = true;
            echo 'launch_error=',get_class($e),"\n";
        }
        checkDump($caught, 'natural launch failure rejected');
        fixtureEnv('DUMP_MODE=timeout');
        $caught = null;
        try {
            fixtureDumper($root)->setTimeout(1)->dumpToFile($root.'/timeout');
        } catch (Throwable $e) {
            $caught = $e;
        }
        checkDump($caught instanceof Symfony\Component\Process\Exception\ProcessTimedOutException, 'configured timeout enforced');
    } finally {
        cleanDumpFixture($root);
        fixtureEnv('DUMP_MODE');
    }
}
function appendDump(): void
{
    [$root,$capture] = makeDumpFixture();
    try {
        $out = $root.'/append output';
        file_put_contents($out, 'PREFIX\n');
        fixtureDumper($root)->useAppendMode()->dumpToFile($out);
        checkDump(file_get_contents($out) === 'PREFIX\n'."CREATE TABLE fixture (id INT);\nINSERT INTO fixture VALUES (42);\n", 'append bytes');
        checkDump(glob($root.'/snipeit-dump-*') === [], 'append temporary output cleaned');
        mkdir($root.'/directory-target');
        $caught = false;
        try {
            fixtureDumper($root)->useAppendMode()->dumpToFile($root.'/directory-target');
        } catch (Throwable $e) {
            $caught = true;
        }
        checkDump($caught, 'append destination I/O failure');
        checkDump(glob($root.'/snipeit-dump-*') === [], 'append failure temporary cleaned');
    } finally {
        cleanDumpFixture($root);
    }
}
function excludedDump(): void
{
    [$root,$capture] = makeDumpFixture();
    try {
        $caught = false;
        try {
            fixtureDumper($root)->skipAutoIncrement()->dumpToFile($root.'/out');
        } catch (Throwable $e) {
            $caught = true;
        }
        checkDump($caught && ! file_exists($capture), 'pipeline rejected before child');
        foreach ([fixtureDumper($root)->useCompressor(new Spatie\DbDumper\Compressors\GzipCompressor), fixtureDumper($root, Spatie\DbDumper\Databases\MariaDb::class)->withoutSandboxMode()] as $dumper) {
            $caught = false;
            try {
                $dumper->dumpToFile($root.'/out');
            } catch (Throwable $e) {
                $caught = true;
            }
            checkDump($caught && ! file_exists($capture), 'other shell pipeline rejected before child');
        }
        fixtureDumper($root, Spatie\DbDumper\Databases\MariaDb::class)->dumpToFile($root.'/maria');
        checkDump(readCapture($capture)['script'] === $root.'/mariadb-dump', 'MariaDB executable selected');
    } finally {
        cleanDumpFixture($root);
    }
}
if (realpath($_SERVER['SCRIPT_FILENAME']) === __FILE__) {
    try {
        $cases = ($argv[1] ?? 'exact') === 'suite' ? ['exact', 'structured', 'legacy', 'failure', 'append', 'exclusions'] : [$argv[1] ?? 'exact'];
        foreach ($cases as $case) {
            match ($case) {
                'exact' => exactDump(),'structured' => structuredDump(),'legacy' => legacyDump(),'failure' => failedDump(),'append' => appendDump(),'exclusions' => excludedDump()
            };
            echo "PASS $case\n";
        }
    } catch (Throwable $e) {
        fwrite(STDERR,get_class($e).': '.$e->getMessage()."\n");
        exit(1);
    }
}
