<?php

namespace Tests\Feature\Console;

use App\Console\Commands\RestoreFromBackup;
use App\Console\Kernel;
use App\Console\Scheduling\ShelllessSchedule;
use ReflectionMethod;
use Tests\TestCase;

/** The shell-less code paths are only used when app.shellless is on. */
class ShelllessOptInTest extends TestCase
{
    private array $connection = [
        'host' => 'db.example', 'username' => 'u', 'port' => 3306, 'unix_socket' => '', 'database' => 'snipeit',
    ];

    private function clientCommand(): array|string
    {
        $method = new ReflectionMethod(RestoreFromBackup::class, 'dbClientCommand');

        return $method->invoke(new RestoreFromBackup, '/usr/bin/mysql', $this->connection);
    }

    public function test_shellless_is_off_by_default(): void
    {
        $value = getenv('SNIPEIT_SHELLLESS');
        $hasEnv = array_key_exists('SNIPEIT_SHELLLESS', $_ENV);
        $hasServer = array_key_exists('SNIPEIT_SHELLLESS', $_SERVER);
        $env = $_ENV['SNIPEIT_SHELLLESS'] ?? null;
        $server = $_SERVER['SNIPEIT_SHELLLESS'] ?? null;

        try {
            putenv('SNIPEIT_SHELLLESS');
            unset($_ENV['SNIPEIT_SHELLLESS'], $_SERVER['SNIPEIT_SHELLLESS']);

            $config = require config_path('app.php');
            $this->assertFalse($config['shellless']);
        } finally {
            $value === false ? putenv('SNIPEIT_SHELLLESS') : putenv('SNIPEIT_SHELLLESS='.$value);
            if ($hasEnv) {
                $_ENV['SNIPEIT_SHELLLESS'] = $env;
            }
            if ($hasServer) {
                $_SERVER['SNIPEIT_SHELLLESS'] = $server;
            }
        }
    }

    public function test_scheduler_is_the_framework_one_by_default(): void
    {
        config(['app.shellless' => false]);

        $schedule = $this->app->make(Kernel::class)->resolveConsoleSchedule();

        $this->assertNotInstanceOf(ShelllessSchedule::class, $schedule);
    }

    public function test_scheduler_is_shellless_when_enabled(): void
    {
        config(['app.shellless' => true]);

        $schedule = $this->app->make(Kernel::class)->resolveConsoleSchedule();

        $this->assertInstanceOf(ShelllessSchedule::class, $schedule);
    }

    public function test_restore_uses_a_shell_command_line_by_default(): void
    {
        config(['app.shellless' => false]);

        $command = $this->clientCommand();

        $this->assertIsString($command);
        $this->assertStringContainsString("'/usr/bin/mysql'", $command);
        $this->assertStringContainsString("'snipeit'", $command);
    }

    public function test_restore_uses_an_argument_array_when_shellless(): void
    {
        config(['app.shellless' => true]);

        $this->assertSame(
            ['/usr/bin/mysql', '-h', 'db.example', '--batch', '--binary-mode', '-u', 'u', '-P', '3306', 'snipeit'],
            $this->clientCommand()
        );
    }

    public function test_restore_argument_array_uses_the_socket_when_configured(): void
    {
        config(['app.shellless' => true]);
        $this->connection['unix_socket'] = '/run/mysqld.sock';

        $this->assertSame(
            ['/usr/bin/mysql', '-h', 'db.example', '--batch', '--binary-mode', '-u', 'u', '-S', '/run/mysqld.sock', 'snipeit'],
            $this->clientCommand()
        );
    }
}
