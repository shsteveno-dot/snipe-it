<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Database\Schema\Blueprint;
use Illuminate\Support\Facades\Schema;

return new class extends Migration
{
    /**
     * JSON list of the OU DNs picked in the LDAP wizard. NULL means every OU
     * under the base DN, so existing installs keep their current behavior.
     */
    public function up(): void
    {
        Schema::table('settings', function (Blueprint $table) {
            $table->text('ldap_selected_ous')->nullable()->after('ldap_filter');
        });
    }

    public function down(): void
    {
        Schema::table('settings', function (Blueprint $table) {
            $table->dropColumn('ldap_selected_ous');
        });
    }
};
