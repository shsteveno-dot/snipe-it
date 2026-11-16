<?php
// Test-only: send one marker mail through the configured SMTP mailer (mock on an internal network).
require '/var/www/html/vendor/autoload.php';
$app = require '/var/www/html/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$app['config']->set('mail.reply_to', ['address' => 'test@example.invalid', 'name' => 'Test']);
$marker = $argv[1];
Illuminate\Support\Facades\Mail::mailer('smtp')->raw($marker, function ($message) use ($marker) {
    $message->to('sink@example.invalid')->subject($marker);
});
echo "sent $marker\n";
