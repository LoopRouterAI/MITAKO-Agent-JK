# 释放 MITAKO 常用端口（8000-8003）上的 Python/uvicorn 进程
$ports = 8000..8003
foreach ($port in $ports) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $procId = $c.OwningProcess
        if ($procId -and $procId -ne 0) {
            Write-Host "[kill] port $port pid $procId"
            Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        }
    }
}
Write-Host "[done] MITAKO ports cleared"
