<?php

namespace Tests\Unit;

use App\Models\Ldap;
use App\Models\Setting;
use phpmock\phpunit\PHPMock;
use PHPUnit\Framework\Attributes\Group;
use Tests\TestCase;

#[Group('ldap')]
class LdapTest extends TestCase
{
    use PHPMock;

    public function test_connect()
    {
        $this->settings->enableLdap();

        $ldap_connect = $this->getFunctionMock('App\\Models', 'ldap_connect');
        $ldap_connect->expects($this->once())->willReturn('hello');

        $ldap_set_option = $this->getFunctionMock('App\\Models', 'ldap_set_option');
        $ldap_set_option->expects($this->exactly(4));

        $blah = Ldap::connectToLdap();
        $this->assertEquals('hello', $blah, "LDAP_connect should return 'hello'");
    }

    // other test cases - with/without client-side certs?
    // with/without LDAP version 3?
    // with/without ignore cert validation?
    // test (and mock) ldap_start_tls() ?

    public function test_bind_admin()
    {
        $this->settings->enableLdap();
        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->once())->willReturn(true);
        $this->assertNull(Ldap::bindAdminToLdap('dummy'));
    }

    public function test_bind_bad()
    {
        $this->settings->enableLdap();
        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->once())->willReturn(false);
        $this->getFunctionMock('App\\Models', 'ldap_error')->expects($this->once())->willReturn('exception');
        // bindError now also queries LDAP_OPT_DIAGNOSTIC_MESSAGE to surface
        // the server's real reason (see #19519). Mocked as returning true
        // without populating the by-ref $diag arg so the composed error
        // stays just the ldap_error message.
        $this->getFunctionMock('App\\Models', 'ldap_get_option')->expects($this->once())->willReturn(true);
        $this->expectExceptionMessage('Could not bind to LDAP:');

        $this->assertNull(Ldap::bindAdminToLdap('dummy'));
    }

    public function test_bind_error_returns_just_ldap_error_when_diagnostic_is_empty()
    {
        // Regression for #19519 secondary issue: bindError should NEVER
        // suppress ldap_error; if no diagnostic is present, the composed
        // string is just the ldap_error text.
        $this->getFunctionMock('App\\Models', 'ldap_error')->expects($this->once())->willReturn('Server Down');
        $this->getFunctionMock('App\\Models', 'ldap_get_option')->expects($this->once())->willReturn(true);

        $this->assertSame('Server Down', Ldap::bindError('dummy'));
    }
    // other test cases - test donked password?

    public function test_anonymous_bind()
    {
        // todo - would be nice to introspect somehow to make sure the right parameters were passed?
        $this->settings->enableAnonymousLdap();
        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->once())->willReturn(true);
        $this->assertNull(Ldap::bindAdminToLdap('dummy'));
    }

    public function test_bad_anonymous_bind()
    {
        $this->settings->enableAnonymousLdap();
        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->once())->willReturn(false);
        $this->getFunctionMock('App\\Models', 'ldap_error')->expects($this->once())->willReturn('exception');
        // bindError now also queries LDAP_OPT_DIAGNOSTIC_MESSAGE; see test_bind_bad.
        $this->getFunctionMock('App\\Models', 'ldap_get_option')->expects($this->once())->willReturn(true);
        $this->expectExceptionMessage('Could not bind to LDAP:');

        $this->assertNull(Ldap::bindAdminToLdap('dummy'));
    }

    public function test_bad_encrypted_password()
    {
        $this->settings->enableBadPasswordLdap();

        $this->expectExceptionMessage('Your app key has changed');
        $this->assertNull(Ldap::bindAdminToLdap('dummy'));
    }

    /**
     * Simulate a PHP build that has SASL support compiled in. Herd's
     * default macOS PHP and some Docker images don't, and the fix for
     * the "no SASL, hard crash" case gates shouldUseSaslExternal() on
     * function_exists('ldap_sasl_bind'). The mock has to intercept that
     * check so the SASL branch fires regardless of the CI PHP build.
     */
    private function mockSaslExternalAvailable(): void
    {
        // The Ldap model gates shouldUseSaslExternal() on
        // function_exists('ldap_sasl_bind'), which php-mock can't
        // reliably intercept in this namespace. Use the class's test
        // seam instead to force availability on regardless of what
        // the CI PHP build actually supports.
        Ldap::setSaslExternalOverride(true);
    }

    private ?string $originalStoragePath = null;

    private ?string $tempStoragePath = null;

    /**
     * Redirect storage_path() to a per-test scratch directory.
     */
    private function useTempStoragePath(): void
    {
        $this->originalStoragePath = storage_path();
        $this->tempStoragePath = sys_get_temp_dir() . '/snipeit-ldap-' . uniqid('', true);
        mkdir($this->tempStoragePath, 0755, true);
        $this->app->useStoragePath($this->tempStoragePath);
    }

    protected function tearDown(): void
    {
        Ldap::setSaslExternalOverride(null);

        if ($this->originalStoragePath !== null) {
            $this->app->useStoragePath($this->originalStoragePath);

            if ($this->tempStoragePath !== null && is_dir($this->tempStoragePath)) {
                foreach (glob($this->tempStoragePath . '/*') as $file) {
                    @unlink($file);
                }
                @rmdir($this->tempStoragePath);
            }

            $this->originalStoragePath = null;
            $this->tempStoragePath = null;
        }

        parent::tearDown();
    }

    public function test_sasl_external_bind_when_cert_and_key_present_without_credentials()
    {
        // GH #19518: SASL EXTERNAL bind (auth via client TLS cert)
        // must route through ldap_sasl_bind, not ldap_bind. Auto-detect
        // fires when cert + key are populated AND both bind DN and
        // bind password are blank.
        $this->settings->enableLdap();
        $this->settings->set([
            'ldap_client_tls_cert' => 'CERT PEM',
            'ldap_client_tls_key' => 'KEY PEM',
            'ldap_uname' => '',
            'ldap_pword' => '',
        ]);

        $this->mockSaslExternalAvailable();
        $this->getFunctionMock('App\\Models', 'ldap_sasl_bind')
            ->expects($this->once())
            ->with('dummy', null, null, 'EXTERNAL')
            ->willReturn(true);
        $this->getFunctionMock('App\\Models', 'ldap_bind')
            ->expects($this->never());

        $this->assertNull(Ldap::bindAdminToLdap('dummy'));
    }

    public function test_sasl_external_bind_failure_surfaces_error()
    {
        $this->settings->enableLdap();
        $this->settings->set([
            'ldap_client_tls_cert' => 'CERT PEM',
            'ldap_client_tls_key' => 'KEY PEM',
            'ldap_uname' => '',
            'ldap_pword' => '',
        ]);

        $this->mockSaslExternalAvailable();
        $this->getFunctionMock('App\\Models', 'ldap_sasl_bind')
            ->expects($this->once())
            ->willReturn(false);
        $this->getFunctionMock('App\\Models', 'ldap_error')
            ->expects($this->once())
            ->willReturn('cert rejected');
        // bindError also queries LDAP_OPT_DIAGNOSTIC_MESSAGE (see #19519).
        $this->getFunctionMock('App\\Models', 'ldap_get_option')
            ->expects($this->once())
            ->willReturn(true);
        $this->expectExceptionMessage('Could not bind to LDAP via SASL EXTERNAL');

        $this->assertNull(Ldap::bindAdminToLdap('dummy'));
    }

    public function test_sasl_external_falls_back_to_simple_bind_when_php_lacks_sasl_support()
    {
        // Guard against a PHP build compiled without SASL support (Herd's
        // default, some Docker images). shouldUseSaslExternal() has to
        // return false when ldap_sasl_bind is unavailable so the runtime
        // doesn't hit a "Call to undefined function ldap_sasl_bind()"
        // fatal. The wizard's warning banner covers the discoverability
        // side. This test covers the runtime-guard side.
        $this->settings->enableLdap();
        $this->settings->set([
            'ldap_client_tls_cert' => 'CERT PEM',
            'ldap_client_tls_key' => 'KEY PEM',
            'ldap_uname' => '',
            'ldap_pword' => '',
        ]);

        Ldap::setSaslExternalOverride(false);

        $this->getFunctionMock('App\\Models', 'ldap_sasl_bind')
            ->expects($this->never());

        $this->assertFalse(Ldap::shouldUseSaslExternal(Setting::getSettings()));
        $this->assertFalse(Ldap::saslExternalAvailable());
    }

    public function test_simple_bind_still_used_when_credentials_are_present()
    {
        // Regression guard: cert + key populated but the user has ALSO
        // filled in bind DN / password picks the simple-bind path, not
        // SASL EXTERNAL. Also the default configuration case for every
        // pre-#19518 install.
        $this->settings->enableLdap();

        $this->getFunctionMock('App\\Models', 'ldap_bind')
            ->expects($this->once())
            ->willReturn(true);
        $this->getFunctionMock('App\\Models', 'ldap_sasl_bind')
            ->expects($this->never());

        $this->assertNull(Ldap::bindAdminToLdap('dummy'));
    }

    public function test_find_and_bind()
    {
        $this->settings->enableLdap();

        $ldap_connect = $this->getFunctionMock('App\\Models', 'ldap_connect');
        $ldap_connect->expects($this->exactly(3))->willReturn('hello');

        $ldap_set_option = $this->getFunctionMock('App\\Models', 'ldap_set_option');
        $ldap_set_option->expects($this->exactly(12));

        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->exactly(2))->willReturn(true);

        $this->getFunctionMock('App\\Models', 'ldap_search')->expects($this->exactly(1))->willReturn(true);

        $this->getFunctionMock('App\\Models', 'ldap_first_entry')->expects($this->exactly(1))->willReturn(true);
        $this->getFunctionMock('App\\Models', 'ldap_unbind')->expects($this->exactly(2));
        $this->getFunctionMock('App\\Models', 'ldap_count_entries')->expects($this->once())->willReturn(1);
        $this->getFunctionMock('App\\Models', 'ldap_get_dn')->expects($this->once())->willReturn('dn=FirstName Surname,ou=Org,dc=example,dc=com');

        $this->getFunctionMock('App\\Models', 'ldap_get_attributes')->expects($this->exactly(1))->willReturn(
            [
                'count' => 1,
                0 => [
                    'sn' => 'Surname',
                    'firstname' => 'FirstName',
                ],
            ]
        );

        $results = Ldap::findAndBindUserLdap('username', 'password');
        $this->assertEqualsCanonicalizing(['count' => 1, 0 => ['sn' => 'Surname', 'firstname' => 'FirstName']], $results);
    }

    public function test_find_and_bind_bad_password()
    {
        $this->settings->enableLdap();

        $ldap_connect = $this->getFunctionMock('App\\Models', 'ldap_connect');
        $ldap_connect->expects($this->exactly(3))->willReturn('hello');

        $ldap_set_option = $this->getFunctionMock('App\\Models', 'ldap_set_option');
        $ldap_set_option->expects($this->exactly(12));

        //
        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->exactly(3))->willReturn(
            true, /* initial admin connection for 'fast path' */
            false, /* the actual login for the user */
            false, /* the direct login for the user binding-as-themselves in the legacy path */
            true /* the admin login afterwards (which is weird and doesn't make sense) */
        );
        $this->getFunctionMock('App\\Models', 'ldap_unbind')->expects($this->exactly(2));
        $this->getFunctionMock('App\\Models', 'ldap_error')->expects($this->never())->willReturn('exception');
        $this->getFunctionMock('App\\Models', 'ldap_search')->expects($this->exactly(1))->willReturn(false); // uhm?
        $this->getFunctionMock('App\\Models', 'ldap_count_entries')->expects($this->exactly(1))->willReturn(1);
        $this->getFunctionMock('App\\Models', 'ldap_first_entry')->expects($this->exactly(1))->willReturn(true);
        $this->getFunctionMock('App\\Models', 'ldap_get_attributes')->expects($this->exactly(1))->willReturn(1);
        $this->getFunctionMock('App\\Models', 'ldap_get_dn')->expects($this->exactly(1))->willReturn('dn=FirstName Surname,ou=Org,dc=example,dc=com');

        //        $this->getFunctionMock("App\\Models","ldap_error")->expects($this->once())->willReturn("exception");

        //        $this->expectExceptionMessage("exception");
        $results = Ldap::findAndBindUserLdap('username', 'password');
        $this->assertFalse($results);
    }

    public function test_find_and_bind_cannot_find_self()
    {
        $this->settings->enableLdap();

        $ldap_connect = $this->getFunctionMock('App\\Models', 'ldap_connect');
        $ldap_connect->expects($this->exactly(2))->willReturn('hello');

        $ldap_set_option = $this->getFunctionMock('App\\Models', 'ldap_set_option');
        $ldap_set_option->expects($this->exactly(8));

        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->exactly(2))->willReturn(true); // I think this is OK

        $this->getFunctionMock('App\\Models', 'ldap_search')->expects($this->exactly(2))->willReturn(false); // uhm?
        $this->getFunctionMock('App\\Models', 'ldap_unbind')->expects($this->once());
        $this->getFunctionMock('App\\Models', 'ldap_count_entries')->expects($this->once())->willReturn(0);

        $this->expectExceptionMessage('Could not search LDAP:');
        $results = Ldap::findAndBindUserLdap('username', 'password');
        $this->assertFalse($results);
    }

    // maybe should do an AD test as well?

    public function test_find_ldap_users()
    {
        $this->settings->enableLdap();

        $ldap_connect = $this->getFunctionMock('App\\Models', 'ldap_connect');
        $ldap_connect->expects($this->once())->willReturn('hello');

        $ldap_set_option = $this->getFunctionMock('App\\Models', 'ldap_set_option');
        $ldap_set_option->expects($this->exactly(4));

        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->once())->willReturn(true);

        $this->getFunctionMock('App\\Models', 'ldap_search')->expects($this->once())->willReturn(['stuff']);

        $this->getFunctionMock('App\\Models', 'ldap_parse_result')->expects($this->once())->willReturn(true);

        $this->getFunctionMock('App\\Models', 'ldap_get_entries')->expects($this->once())->willReturn(['count' => 1]);

        $results = Ldap::findLdapUsers();

        $this->assertEqualsCanonicalizing(['count' => 1], $results);
    }

    public function test_find_ldap_users_paginated()
    {
        $this->settings->enableLdap();

        $ldap_connect = $this->getFunctionMock('App\\Models', 'ldap_connect');
        $ldap_connect->expects($this->once())->willReturn('hello');

        $ldap_set_option = $this->getFunctionMock('App\\Models', 'ldap_set_option');
        $ldap_set_option->expects($this->exactly(4));

        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->once())->willReturn(true);

        $this->getFunctionMock('App\\Models', 'ldap_search')->expects($this->exactly(2))->willReturn(['stuff']);

        $this->getFunctionMock('App\\Models', 'ldap_parse_result')->expects($this->exactly(2))->willReturnCallback(
            function ($ldapconn, $search_results, $errcode, $matcheddn, $errmsg, $referrals, &$controls) {
                static $count = 0;
                if ($count == 0) {
                    $count++;
                    $controls[LDAP_CONTROL_PAGEDRESULTS]['value']['cookie'] = 'cookie';

                    return ['count' => 1];
                } else {
                    $controls = [];

                    return ['count' => 1];
                }

            }
        );

        $this->getFunctionMock('App\\Models', 'ldap_get_entries')->expects($this->exactly(2))->willReturn(['count' => 1]);

        $results = Ldap::findLdapUsers();

        $this->assertEqualsCanonicalizing(['count' => 2], $results);
    }

    public function test_nonexistent_tls_file()
    {
        $this->useTempStoragePath();
        $this->settings->enableLdap()->set(['ldap_client_tls_cert' => 'SAMPLE CERT TEXT']);
        $certfile = Setting::get_client_side_cert_path();
        $this->assertStringEqualsFile($certfile, 'SAMPLE CERT TEXT');
    }

    public function test_stale_tls_file()
    {
        $this->useTempStoragePath();
        file_put_contents(Setting::get_client_side_cert_path(), 'STALE CERT FILE');
        sleep(1); // FIXME - this is going to slow down tests
        $this->settings->enableLdap()->set(['ldap_client_tls_cert' => 'SAMPLE CERT TEXT']);
        $certfile = Setting::get_client_side_cert_path();
        $this->assertStringEqualsFile($certfile, 'SAMPLE CERT TEXT');
    }

    public function test_fresh_tls_file()
    {
        $this->useTempStoragePath();
        $this->settings->enableLdap()->set(['ldap_client_tls_cert' => 'SAMPLE CERT TEXT']);
        $client_side_cert_path = Setting::get_client_side_cert_path();
        file_put_contents($client_side_cert_path, 'WEIRDLY UPDATED CERT FILE');
        clearstatcache();
        // the system should respect our cache-file, since the settings haven't been updated
        $possibly_recached_cert_file = Setting::get_client_side_cert_path(); // this should *NOT* re-cache from the Settings
        $this->assertStringEqualsFile($possibly_recached_cert_file, 'WEIRDLY UPDATED CERT FILE');
    }

    public function test_selected_ous_is_null_when_every_ou_is_in_scope()
    {
        $this->settings->set(['ldap_selected_ous' => null]);

        $this->assertNull(Ldap::selectedOus());
        $this->assertTrue(Ldap::isDnInSelectedOus('CN=Someone,OU=Anything,DC=gogoro,DC=com'));
    }

    public function test_unreadable_selected_ous_select_nothing()
    {
        $this->settings->set(['ldap_selected_ous' => 'not json']);

        $this->assertSame([], Ldap::selectedOus());
        $this->assertFalse(Ldap::isDnInSelectedOus('CN=Someone,OU=G1,DC=gogoro,DC=com'));
    }

    public function test_dn_must_sit_directly_in_a_selected_ou()
    {
        $ous = ['OU=G1,OU=GogoroUsers,DC=gogoro,DC=com', 'ou=Test Users, ou=GogoroUsers, dc=gogoro, dc=com'];

        $this->assertTrue(Ldap::isDnDirectlyInOus('CN=Someone,OU=G1,OU=GogoroUsers,DC=gogoro,DC=com', $ous));
        $this->assertTrue(Ldap::isDnDirectlyInOus('cn=someone,ou=g1,ou=gogorousers,dc=gogoro,dc=com', $ous));
        $this->assertTrue(Ldap::isDnDirectlyInOus('CN=Someone,OU=Test Users,OU=GogoroUsers,DC=gogoro,DC=com', $ous));

        $this->assertFalse(Ldap::isDnDirectlyInOus('CN=Someone,OU=New,OU=G1,OU=GogoroUsers,DC=gogoro,DC=com', $ous));
        $this->assertFalse(Ldap::isDnDirectlyInOus('CN=Someone,OU=NotG1,OU=GogoroUsers,DC=gogoro,DC=com', $ous));
        $this->assertFalse(Ldap::isDnDirectlyInOus('CN=Someone,OU=GogoroUsers,DC=gogoro,DC=com', $ous));
    }

    public function test_an_escaped_comma_in_a_name_is_not_a_dn_separator()
    {
        $name_with_comma = 'CN=Wu'.chr(92).', Rosa,OU=G1,DC=gogoro,DC=com';

        $this->assertTrue(Ldap::isDnDirectlyInOus($name_with_comma, ['OU=G1,DC=gogoro,DC=com']));
        $this->assertFalse(Ldap::isDnDirectlyInOus($name_with_comma, ['Rosa,OU=G1,DC=gogoro,DC=com']));
    }

    public function test_dn_separator_after_even_backslashes_cannot_skip_a_deselected_ou(): void
    {
        $dn = 'CN=Alice'.str_repeat(chr(92), 2).',OU=Blocked,DC=example,DC=com';
        $this->assertFalse(Ldap::isDnDirectlyInOus($dn, ['DC=example,DC=com']));
        $this->assertTrue(Ldap::isDnDirectlyInOus($dn, ['OU=Blocked,DC=example,DC=com']));
    }

    public function test_ou_tree_is_depth_first_with_the_base_dn_on_top()
    {
        $tree = Ldap::buildOuTree('OU=GogoroUsers,DC=gogoro,DC=com', [
            'OU=TPE,OU=GogoroUsers,DC=gogoro,DC=com',
            'OU=GogoroUsers,DC=gogoro,DC=com',
            'OU=Team2,OU=G1,OU=GogoroUsers,DC=gogoro,DC=com',
            'OU=G1,OU=GogoroUsers,DC=gogoro,DC=com',
            'OU=Deep,OU=Team2,OU=G1,OU=GogoroUsers,DC=gogoro,DC=com',
            'OU=Elsewhere,DC=gogoro,DC=com',
        ]);

        $this->assertSame(
            ['OU=GogoroUsers,DC=gogoro,DC=com', 'G1', 'Team2', 'Deep', 'TPE'],
            array_column($tree, 'name'),
        );
        $this->assertSame([0, 1, 2, 3, 1], array_column($tree, 'depth'));
        $this->assertSame([], $tree[0]['ancestors']);
        $this->assertSame([0, 1, 2], $tree[3]['ancestors']);
        $this->assertSame([0], $tree[4]['ancestors']);
    }

    public function test_find_ldap_users_keeps_only_entries_in_selected_ous()
    {
        $this->settings->set(['ldap_selected_ous' => json_encode(['OU=G1,DC=gogoro,DC=com', 'OU=TPE,DC=gogoro,DC=com'])]);
        $this->mockLdapSearchReturning([
            'count' => 3,
            0 => ['dn' => 'CN=Unselected,OU=IT,DC=gogoro,DC=com'],
            1 => ['dn' => 'CN=KeptOne,OU=G1,DC=gogoro,DC=com'],
            2 => ['dn' => 'CN=KeptTwo,OU=TPE,DC=gogoro,DC=com'],
        ]);

        $results = Ldap::findLdapUsers();

        $this->assertSame(2, $results['count']);
        $this->assertSame('CN=KeptOne,OU=G1,DC=gogoro,DC=com', $results[0]['dn']);
        $this->assertSame('CN=KeptTwo,OU=TPE,DC=gogoro,DC=com', $results[1]['dn']);
        $this->assertArrayNotHasKey(2, $results);
    }

    public function test_find_ldap_users_keeps_every_entry_when_every_ou_is_in_scope()
    {
        $this->settings->set(['ldap_selected_ous' => null]);
        $this->mockLdapSearchReturning([
            'count' => 1,
            0 => ['dn' => 'CN=Someone,OU=IT,DC=gogoro,DC=com'],
        ]);

        $this->assertSame(1, Ldap::findLdapUsers()['count']);
    }

    public function test_login_is_refused_for_a_user_outside_the_selected_ous()
    {
        $this->settings->enableLdap()->set(['ldap_selected_ous' => json_encode(['OU=G1,DC=gogoro,DC=com'])]);
        $this->mockLdapLoginFoundAt('CN=Someone,OU=IT,DC=gogoro,DC=com');

        $this->assertFalse(Ldap::findAndBindUserLdap('username', 'password'));
    }

    public function test_login_is_refused_for_a_user_outside_the_selected_ous_on_the_legacy_path()
    {
        // No bind DN configured, so the fast find-and-bind is skipped entirely.
        $this->settings->enableAnonymousLdap()->set(['ldap_selected_ous' => json_encode(['OU=G1,DC=gogoro,DC=com'])]);
        $this->mockLdapLoginFoundAt('CN=Someone,OU=IT,DC=gogoro,DC=com');

        $this->assertFalse(Ldap::findAndBindUserLdap('username', 'password'));
    }

    public function test_login_works_for_a_user_in_a_selected_ou()
    {
        $this->settings->enableLdap()->set(['ldap_selected_ous' => json_encode(['OU=G1,DC=gogoro,DC=com'])]);
        $this->mockLdapLoginFoundAt('CN=Someone,OU=G1,DC=gogoro,DC=com');

        $this->assertSame(['sn' => 'Surname'], Ldap::findAndBindUserLdap('username', 'password'));
    }

    private function mockLdapSearchReturning(array $entries): void
    {
        $this->settings->enableLdap();
        $this->getFunctionMock('App\\Models', 'ldap_connect')->expects($this->once())->willReturn('hello');
        $this->getFunctionMock('App\\Models', 'ldap_set_option')->expects($this->any());
        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->once())->willReturn(true);
        $this->getFunctionMock('App\\Models', 'ldap_search')->expects($this->once())->willReturn(['stuff']);
        $this->getFunctionMock('App\\Models', 'ldap_parse_result')->expects($this->once())->willReturn(true);
        $this->getFunctionMock('App\\Models', 'ldap_get_entries')->expects($this->once())->willReturn($entries);
    }

    private function mockLdapLoginFoundAt(string $dn): void
    {
        $this->getFunctionMock('App\\Models', 'ldap_connect')->expects($this->any())->willReturn('hello');
        $this->getFunctionMock('App\\Models', 'ldap_set_option')->expects($this->any());
        $this->getFunctionMock('App\\Models', 'ldap_bind')->expects($this->any())->willReturn(true);
        $this->getFunctionMock('App\\Models', 'ldap_unbind')->expects($this->any());
        $this->getFunctionMock('App\\Models', 'ldap_search')->expects($this->any())->willReturn('results');
        $this->getFunctionMock('App\\Models', 'ldap_count_entries')->expects($this->any())->willReturn(1);
        $this->getFunctionMock('App\\Models', 'ldap_first_entry')->expects($this->any())->willReturn('entry');
        $this->getFunctionMock('App\\Models', 'ldap_get_dn')->expects($this->any())->willReturn($dn);
        $this->getFunctionMock('App\\Models', 'ldap_get_attributes')->expects($this->any())->willReturn(['SN' => 'Surname']);
    }
}
