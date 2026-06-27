#!/usr/bin/env bash
# UNILAG mounting dry-run — Phase G smoke tests (mounting guide §5).
# Runs against the production replica stack.
#
# NOTE on cookies: the app sets SESSION_COOKIE_SECURE=True in production, so the
# session cookie is only sent over HTTPS. All authenticated flows therefore go
# through the nginx TLS reverse proxy (https://localhost:8443, -k = self-signed),
# which is the real production request path anyway. Unauthenticated checks use
# the direct gunicorn port (18080) to prove the app itself is hardened.
set -u

APP=http://localhost:18080          # gunicorn app (direct, bypasses nginx)
TLS=https://localhost:8443          # nginx TLS reverse proxy (prod path)
J=/tmp/uraas_cookies.txt
PASS=0; FAIL=0
ok(){ echo "  PASS: $1"; PASS=$((PASS+1)); }
no(){ echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
CURL="curl -sk"                     # -k: trust the self-signed dry-run cert

echo "=== 1. /health returns 200 (app direct + nginx TLS) ==="
code=$($CURL -o /dev/null -w '%{http_code}' $APP/health)
[ "$code" = "200" ] && ok "app /health = 200" || no "app /health = $code"
code=$($CURL -o /dev/null -w '%{http_code}' $TLS/health)
[ "$code" = "200" ] && ok "nginx TLS /health = 200" || no "nginx TLS /health = $code"

echo "=== 2. HTTP -> HTTPS redirect (nginx :8081) ==="
loc=$($CURL -o /dev/null -w '%{http_code} %{redirect_url}' http://localhost:8081/)
echo "    $loc"
echo "$loc" | grep -q "301" && ok "HTTP returns 301 redirect to https" || no "no 301 redirect: $loc"

echo "=== 3. Anonymous API control route -> 401 ==="
code=$($CURL -o /dev/null -w '%{http_code}' $APP/api/crawler/status)
[ "$code" = "401" ] && ok "anon /api/crawler/status = 401" || no "anon crawler status = $code"
code=$($CURL -o /dev/null -w '%{http_code}' $APP/api/analytics/overview)
[ "$code" = "401" ] && ok "anon /api/analytics/overview = 401" || no "anon analytics = $code"
code=$($CURL -o /dev/null -w '%{http_code}' $APP/api/staff/directory)
echo "    (staff directory PII, anon): $code"
[ "$code" = "401" ] && ok "anon staff directory (PII) = 401" || no "anon staff directory = $code"

echo "=== 4. Anonymous HTML route -> redirect to /login ==="
loc=$($CURL -o /dev/null -w '%{http_code} %{redirect_url}' "$APP/")
echo "    $loc"
echo "$loc" | grep -qE "302.*/login" && ok "anon / redirects to /login" || no "anon / = $loc"

echo "=== 5. Security headers (CSP, XFO, nosniff, HSTS over TLS) ==="
h=$($CURL -D - -o /dev/null $APP/login)
echo "$h" | grep -qi "Content-Security-Policy" && ok "CSP header present" || no "CSP missing"
echo "$h" | grep -qi "X-Frame-Options: DENY" && ok "X-Frame-Options DENY" || no "XFO missing"
echo "$h" | grep -qi "X-Content-Type-Options: nosniff" && ok "nosniff present" || no "nosniff missing"
echo "$h" | grep -qi "Strict-Transport-Security" && ok "HSTS present (prod)" || no "HSTS missing"
ht=$($CURL -D - -o /dev/null $TLS/login)
echo "$ht" | grep -qi "Strict-Transport-Security" && ok "HSTS present via nginx TLS" || no "HSTS via nginx missing"

echo "=== 6. Bad login -> 401, no session granted ==="
code=$($CURL -o /dev/null -w '%{http_code}' -d "username=admin&password=wrong" $TLS/login)
[ "$code" = "401" ] && ok "bad login = 401" || no "bad login = $code"

echo "=== 7. Admin login works + reaches admin-only route (over TLS) ==="
rm -f $J
code=$($CURL -o /dev/null -w '%{http_code}' -c $J -d "username=admin&password=UnilagAdmin#2026" $TLS/login)
echo "    admin login status (302 expected): $code"
[ "$code" = "302" ] && ok "admin login = 302" || no "admin login = $code"
code=$($CURL -o /dev/null -w '%{http_code}' -b $J $TLS/api/crawler/status)
[ "$code" = "200" ] && ok "admin reaches crawler status (200)" || no "admin crawler status = $code"

echo "=== 8. Viewer login works but is NOT admin (crawler -> 403) ==="
rm -f $J
$CURL -o /dev/null -c $J -d "username=viewer&password=UnilagView#2026" $TLS/login
code=$($CURL -o /dev/null -w '%{http_code}' -b $J $TLS/api/crawler/status)
[ "$code" = "403" ] && ok "viewer crawler status = 403 (admin-only)" || no "viewer crawler status = $code"
code=$($CURL -o /dev/null -w '%{http_code}' -b $J $TLS/api/analytics/overview)
[ "$code" = "200" ] && ok "viewer reads analytics (200)" || no "viewer analytics = $code"
code=$($CURL -o /dev/null -w '%{http_code}' -b $J $TLS/api/staff/directory)
[ "$code" = "403" ] && ok "viewer staff directory (PII) = 403" || no "viewer staff directory = $code"

echo
echo "================= SMOKE TEST SUMMARY ================="
echo "  PASSED: $PASS    FAILED: $FAIL"
echo "====================================================="
[ "$FAIL" = "0" ] && exit 0 || exit 1
