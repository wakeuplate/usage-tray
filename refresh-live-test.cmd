@echo off
cd /d D:\claude-projects\limit-lens
set PYTHONIOENCODING=utf-8
python collectors\collect_limit_lens.py --skip-codex --timeout-sec 20 > refresh-live-test-result.json 2> refresh-live-test-result.err
