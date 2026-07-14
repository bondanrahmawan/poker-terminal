@echo off
REM Double-click to start the long-lived Cloudflare tunnel (stable public URL).
REM Leave this window open, then run backend.bat in a second window.
python "%~dp0run_tunnel.py" %*
pause
