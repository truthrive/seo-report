# Gỡ task "SEO Report web" do cai-dat-may-chu.ps1 tạo (tool không còn tự chạy nền nữa).
# Cài đặt chế độ ngủ không đổi lại tự động: chỉnh trong Settings > System > Power nếu cần.

$name = "SEO Report web"
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    Write-Host "Đã gỡ task '$name'." -ForegroundColor Green
} else {
    Write-Host "Không có task '$name'."
}
