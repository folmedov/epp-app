#!/bin/bash
# EEPP endpoint diagnostic tests
# Run: bash scripts/test_eepp_endpoints.sh

set -e

echo "=== EEPP Endpoint Diagnostic Tests ==="
echo ""

OLD_POST="https://www.empleospublicos.cl/data/convocatorias2_nueva.txt"
OLD_EVAL="https://www.empleospublicos.cl/data/convocatorias_evaluacion_nueva.txt"
NEW_URL="https://www.empleospublicos.cl/apiConvocatorias.ashx"

echo "--- 1. Default curl (no custom headers) ---"
echo "POSTULACION:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" "$OLD_POST"
echo "EVALUACION:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" "$OLD_EVAL"
echo "NUEVO:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" "$NEW_URL"
echo ""

echo "--- 2. Browser User-Agent (Chrome) ---"
UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
echo "POSTULACION:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" -H "User-Agent: $UA" "$OLD_POST"
echo "EVALUACION:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" -H "User-Agent: $UA" "$OLD_EVAL"
echo "NUEVO:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" -H "User-Agent: $UA" "$NEW_URL"
echo ""

echo "--- 3. Full browser headers ---"
echo "POSTULACION:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" \
  -H "User-Agent: $UA" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -H "Accept-Language: es-CL,es;q=0.9,en;q=0.8" \
  -H "Accept-Encoding: gzip, deflate, br" \
  -H "Referer: https://www.empleospublicos.cl/" \
  "$OLD_POST"
echo "EVALUACION:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" \
  -H "User-Agent: $UA" \
  -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
  -H "Accept-Language: es-CL,es;q=0.9,en;q=0.8" \
  -H "Accept-Encoding: gzip, deflate, br" \
  -H "Referer: https://www.empleospublicos.cl/" \
  "$OLD_EVAL"
echo "NUEVO:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" \
  -H "User-Agent: $UA" \
  -H "Accept: application/json" \
  -H "Accept-Language: es-CL,es;q=0.9,en;q=0.8" \
  -H "Referer: https://www.empleospublicos.cl/" \
  "$NEW_URL"
echo ""

echo "--- 4. python-httpx default User-Agent ---"
echo "POSTULACION:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" \
  -H "User-Agent: python-httpx/0.27.0" \
  "$OLD_POST"
echo "EVALUACION:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" \
  -H "User-Agent: python-httpx/0.27.0" \
  "$OLD_EVAL"
echo "NUEVO:"
curl -s -o /dev/null -w "HTTP %{http_code} | Size: %{size_download} bytes\n" \
  -H "User-Agent: python-httpx/0.27.0" \
  "$NEW_URL"
echo ""

echo "--- 5. Response headers (POSTULACION, browser UA) ---"
curl -sI -H "User-Agent: $UA" "$OLD_POST" | head -20
echo ""

echo "--- 6. Response headers (POSTULACION, python httpx UA) ---"
curl -sI -H "User-Agent: python-httpx/0.27.0" "$OLD_POST" | head -20
echo ""

echo "=== Done ==="
