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
        $this->assertFalse(config('app.shellless'));
    }

    public function test_scheduler_is_the_framework_one_by_default(): void
    {
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
