#!/bin/bash
# 拿 wf#4803 真实 SQL 内容 (从 110 prod API)
set -e
curl -sS -c /tmp/cookie.txt -b /tmp/cookie.txt -X POST http://prodarchery.ahggwl.com:9123/login/ -d 'username=archery&password=archery123' 2>&1 | head -5
echo "--- wf#4803 ---"
curl -sS -b /tmp/cookie.txt http://prodarchery.ahggwl.com:9123/detail/4803/ 2>&1 | grep -A 3 'pre.*ALTER\|<pre\|<code\|<textarea' | head -50
