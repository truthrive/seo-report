# Biến máy này thành máy chủ cho tool SEO Report.
#
#   1. Tạo task "SEO Report web": tool chạy nền (không cửa sổ) mỗi khi bạn đăng nhập Windows, tự bật lại nếu bị tắt.
#   2. (Hỏi trước) Không cho máy tự ngủ khi đang cắm sạc, để người khác luôn mở được báo cáo.
#
# Chạy: bấm chuột phải file này > "Run with PowerShell", hoặc trong PowerShell:
#   powershell -ExecutionPolicy Bypass -File .\scripts\cai-dat-may-chu.ps1
# Gỡ: chạy .\scripts\go-may-chu.ps1
#
# Tool chỉ nghe ở 127.0.0.1 (không mở cổng ra mạng). Người ngoài vào qua Cloudflare Tunnel hoặc Tailscale (README mục 11).

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $pythonw)) {
    Write-Host "Không thấy $pythonw. Cài môi trường theo README mục 2 trước." -ForegroundColor Red
    exit 1
}

$name = "SEO Report web"
$action = New-ScheduledTaskAction -Execute $pythonw -Argument "-m seo_report web --port 8080 --no-open" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
}
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Description "Giao diện SEO Report ở http://127.0.0.1:8080 (chạy nền)" | Out-Null
Start-ScheduledTask -TaskName $name
Write-Host "Đã tạo và bật task '$name'. Mở thử: http://127.0.0.1:8080" -ForegroundColor Green

$ans = Read-Host "Không cho máy tự ngủ khi đang cắm sạc (màn hình vẫn tự tắt)? [y/N]"
if ($ans -match '^[yY]') {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host "Đã tắt chế độ ngủ khi cắm sạc." -ForegroundColor Green
} else {
    Write-Host "Giữ nguyên cài đặt nguồn. Lưu ý: máy ngủ thì người khác không mở được báo cáo." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Ghi nhớ: tool chỉ chạy khi bạn đã đăng nhập Windows. Rời máy thì khóa màn hình (Win + L), đừng Sign out."
Write-Host "Sửa code hoặc config.toml xong: Stop-ScheduledTask '$name'; Start-ScheduledTask '$name'"
