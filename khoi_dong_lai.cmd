@echo off
rem Nhap dup sau khi sua code hoac config.toml: khoi dong lai tool chay nen (task "SEO Report web")
rem de ban tren ten mien (Cloudflare Tunnel) dung code moi. Nguoi dang mo tool bi ngat vai giay roi tu noi lai.
powershell -NoProfile -Command "Stop-ScheduledTask -TaskName 'SEO Report web'; Start-Sleep 2; Start-ScheduledTask -TaskName 'SEO Report web'; Write-Host 'Dang khoi dong lai...'; $ok = $false; for ($i = 0; $i -lt 45 -and -not $ok; $i++) { Start-Sleep 1; try { $null = Invoke-WebRequest http://127.0.0.1:8080/login -UseBasicParsing -TimeoutSec 3; $ok = $true } catch {} }; if ($ok) { Write-Host 'Da khoi dong lai: tool dang chay o cong 8080.' -ForegroundColor Green } else { Write-Host 'Tool chua len sau 45 giay: xem data\web.log' -ForegroundColor Red }"
pause
