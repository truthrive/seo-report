@echo off
rem Nhap dup de mo SEO Report tren may nay. Tool chay nen (task "SEO Report web"): file nay chi mo trinh duyet,
rem neu tool chua chay thi bat len truoc. Cung mot ban voi ban tren ten mien, du lieu dung chung.
powershell -NoProfile -Command "try { $null = Invoke-WebRequest http://127.0.0.1:8080/login -UseBasicParsing -TimeoutSec 3 } catch { Write-Host 'Dang bat tool...'; Start-ScheduledTask -TaskName 'SEO Report web'; $i = 0; while ($i -lt 45) { Start-Sleep 1; $i++; try { $null = Invoke-WebRequest http://127.0.0.1:8080/login -UseBasicParsing -TimeoutSec 3; break } catch {} } }"
start "" http://127.0.0.1:8080
