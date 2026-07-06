# Clear local MITAKO demo ports before regression or package smoke tests.
$ports = @(8000, 8001, 8002, 8003, 7861, 8790)
foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $conns) {
        $procId = $conn.OwningProcess
        if ($procId -and $procId -ne 0) {
            Write-Host "[kill] port $port pid $procId"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "[done] MITAKO ports cleared"
