# Boss直聘自动投递脚本 - 环境安装
# 在 PowerShell 中运行

Write-Host "=== 安装 Boss直聘自动投递脚本依赖 ===" -ForegroundColor Cyan

# 检查是否有 .venv
if (-not (Test-Path ".\.venv")) {
    Write-Host "创建虚拟环境..." -ForegroundColor Yellow
    python -m venv .venv
}

# 激活虚拟环境
Write-Host "激活虚拟环境..." -ForegroundColor Yellow
.\.venv\Scripts\Activate.ps1

# 安装依赖
Write-Host "安装 Python 依赖..." -ForegroundColor Yellow
pip install -r automation\requirements_zhipin.txt

# 安装 Playwright 浏览器
Write-Host "安装 Playwright Chromium 浏览器..." -ForegroundColor Yellow
playwright install chromium

Write-Host "=== 安装完成！===" -ForegroundColor Green
Write-Host ""
Write-Host "运行脚本：" -ForegroundColor Cyan
Write-Host "  .\.venv\Scripts\python.exe automation\zhipin_apply.py" -ForegroundColor White
