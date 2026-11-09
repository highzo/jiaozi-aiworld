# 饺子AIWorld · Windows 防火墙放行
#
# 手机连不上，十次有八次是这一步没做：Windows 默认不让外面的设备
# 访问本机的 Python 进程。这里一次性把要用的端口和程序都放行。
#
# 用法（必须管理员）：
#   右键「以管理员身份运行 PowerShell」，然后：
#     cd 到仓库目录
#     powershell -ExecutionPolicy Bypass -File scripts\win-firewall.ps1
#
# 只想放行别的端口：
#     powershell -ExecutionPolicy Bypass -File scripts\win-firewall.ps1 -Port 9000
#
# 卸载（删掉这些规则）：
#     powershell -ExecutionPolicy Bypass -File scripts\win-firewall.ps1 -Remove

param(
    [int]$Port = 8787,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$Tag = 'JiaoziAIWorld'

function Test-Admin {
    $p = New-Object Security.Principal.WindowsPrincipal(
        [Security.Principal.WindowsIdentity]::GetCurrent())
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Host '需要管理员权限。请右键 PowerShell -> 以管理员身份运行，再执行一次。' -ForegroundColor Red
    exit 1
}

if ($Remove) {
    $existing = Get-NetFirewallRule -DisplayName "$Tag*" -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Host "没有找到 $Tag 开头的规则，无需清理。" -ForegroundColor Yellow
        exit 0
    }
    $existing | Remove-NetFirewallRule
    Write-Host "已删除 $($existing.Count) 条规则。" -ForegroundColor Green
    exit 0
}

# 8788 = 设备互认，8789 = 家电发现，都是 UDP
$specs = @(
    @{ Name = "$Tag HTTP";   Proto = 'TCP'; Ports = @($Port) },
    @{ Name = "$Tag 互认";   Proto = 'UDP'; Ports = @(8788) },
    @{ Name = "$Tag 家电";   Proto = 'UDP'; Ports = @(8789) }
)

foreach ($s in $specs) {
    $old = Get-NetFirewallRule -DisplayName $s.Name -ErrorAction SilentlyContinue
    if ($old) { $old | Remove-NetFirewallRule }
    $portArg = ($s.Ports -join ',')
    New-NetFirewallRule -DisplayName $s.Name -Direction Inbound -Action Allow `
        -Protocol $s.Proto -LocalPort $portArg -Profile Private, Domain `
        -Description '饺子AIWorld：允许手机/平板/开发板访问本机桌面' | Out-Null
    Write-Host ("已放行 {0,-6} {1} ({2})" -f $s.Proto, $portArg, $s.Name) -ForegroundColor Green
}

# 有些机器上端口规则够了、程序规则被单独拦；顺手把当前 Python 也放行
$py = (Get-Command python -ErrorAction SilentlyContinue).Source
if ($py) {
    $name = "$Tag Python"
    $old = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
    if ($old) { $old | Remove-NetFirewallRule }
    New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow `
        -Program $py -Profile Private, Domain `
        -Description '饺子AIWorld：允许本机 Python 进程被局域网访问' | Out-Null
    Write-Host "已放行程序 $py" -ForegroundColor Green
}

Write-Host ''
Write-Host '只对「专用网络 / 域网络」放行，咖啡馆那种公用 WiFi 不会被打开。' -ForegroundColor Cyan
Write-Host '检查是否生效：' -ForegroundColor Cyan
Write-Host "  Get-NetFirewallRule -DisplayName '$Tag*' | Select DisplayName,Enabled,Direction"
Write-Host '撤销全部放行：' -ForegroundColor Cyan
Write-Host '  powershell -ExecutionPolicy Bypass -File scripts\win-firewall.ps1 -Remove'
