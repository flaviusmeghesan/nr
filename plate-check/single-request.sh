#!/usr/bin/env bash
# Un singur call, cu token dat manual - pentru verificarea payload-ului.
#
#   ./single-request.sh MS77WWW "0cAFcWeA..."
#
# Tokenul se ia din DevTools -> Network -> plate-status -> Payload -> reCaptchaKey.
# Este de unica folosinta: pentru al doilea call ai nevoie de altul.

set -euo pipefail

PLATE="${1:?Utilizare: $0 <PLACUTA> <RECAPTCHA_TOKEN>}"
TOKEN="${2:?Utilizare: $0 <PLACUTA> <RECAPTCHA_TOKEN>}"

curl -sS -X POST 'https://dgpci.mai.gov.ro/drpciv-forms-api/plate-status' \
  -H 'Accept: application/json' \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://dgpci.mai.gov.ro' \
  -H 'Referer: https://dgpci.mai.gov.ro/' \
  --data-binary "$(printf '{"plateNumber":"%s","userEmail":"","language":"RO","reCaptchaKey":"%s"}' "$PLATE" "$TOKEN")" \
  | sed -e 's/$/\n/'
