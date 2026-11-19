# Staging security checklist

Run `zap-scan.sh` first, then confirm these findings from the 2026-11
audit by hand on **staging**, using two browsers (an owner and a cashier)
and `curl`. Each step says what you should see now that it is fixed.
Write down anything that behaves differently, along with ZAP's
High/Medium alerts.

Set up: one shop with an owner (who has a phone number), a store manager
and a cashier; `SMS_BACKEND` sending real SMS to a phone you hold;
`shop-security-alerts.timer` enabled.

## H1: manager approval at the till
1. As the cashier, start a void and type the manager's username with a
   wrong password 5 times. → 403 each time.
2. The 6th try, even with the right password → *"Too many wrong
   passwords"* (429).
3. Sign in as the manager from the same till → also refused for 15 minutes.
4. Within 5 minutes the owner gets an SMS: *"manager" locked out after 5
   wrong passwords*. The Activity log shows each failure with the cashier
   as the user.

## H2: offline sale over a limit
Send this as the cashier (token from the browser's localStorage,
`duka_erp_token`):
```bash
curl -X POST "$STAGING_URL/api/pos/sales/record/" -H "Authorization: Token $T" \
  -H 'Content-Type: application/json' -d '{"id":"<new uuid>","store":"<store id>",
  "items":[{"product":"<id>","qty":"1","unit_price":"0"}],
  "payment_method":"<cash id>","amount_tendered":"0","completed_at":"2026-01-01T08:00:00Z"}'
```
→ 201 (offline sales are never refused). Within 5 minutes the owner gets
an SMS naming the sale: the price charged versus the store's price, and a
date outside its shift and long before it arrived. The Activity log shows
*Offline sale over a limit* in red.

## H3: no codes on screen
On staging (DEBUG=False), *Forgot password?* for the owner's number →
the code arrives by SMS only. The browser's network tab shows no
`debug_code` in the answer.

## M1: sign-in limits
1. From one network, 5 wrong passwords for the owner → locked there.
   From another network (mobile data), the owner signs in fine.
2. Try one wrong password against 30 different usernames from one network →
   the 31st attempt is refused for every username, and `ADMINS` gets an
   email naming the address.
3. 31 quick sign-in requests in a minute from one address → 429.
4. Adding `X-Forwarded-For: 1.2.3.4` to the requests changes none of the above.

## M6: SMS code guesses
Send 10 wrong codes **at the same time** for one password reset (e.g.
`xargs -P10 curl ...`). → At most 5 are checked (PHONE_CODE_ATTEMPTS),
and then the right code is refused too until a new one is requested.

## M2: platform administrator
(Two-step sign-in is planned for later; until then:)
1. `/admin/` → five wrong passwords there → locked (the Activity log shows
   them).
2. A superuser session ends after `SUPERUSER_TOKEN_TTL_HOURS` (4).

## M3: a stolen session
1. In *My profile*, change the mobile number without the current password →
   refused. With the wrong password 5 times → locked.
2. Sign out, then send the old token: `curl -H "Authorization: Token $T"
   $STAGING_URL/api/core/users/me/` → 401.

## M4: staff details
As a cashier and as a store manager: `GET /api/core/users/` → 403.
`GET /api/core/users/me/` → their own details only.

## M5: browser headers
1. `curl -sI $STAGING_URL/ | grep -iE 'content-security|strict-transport|x-frame'`
   → all three present. Also on `/assets/<any file>`.
2. With the browser console open, use every main screen (till, stock,
   reports, analytics with a chart download, Admin > Shop profile logo
   upload, printing a receipt) → no CSP "Refused to..." errors. If one
   appears, add exactly that source to `deploy/nginx/security-headers.conf`.
3. ZAP's baseline report has no "CSP: Header Not Set" or "Missing
   Anti-clickjacking Header" alerts for the app pages.

## Afterwards
Reset the scan user's password (this signs out its token), and delete the
staging shop's junk records if you need clean data.
