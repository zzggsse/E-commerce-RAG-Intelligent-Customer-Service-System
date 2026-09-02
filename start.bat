@echo off
chcp 936 >nul
setlocal enabledelayedexpansion
cd /d %~dp0

echo ============================================
echo   电商 RAG 智能客服系统  一键启动
echo ============================================
echo.

REM ---------- 0. 检查 .env ----------
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [提示] 已生成 .env，请先打开填写 LLM_API_KEY，然后重新运行本脚本。
        notepad .env
        pause
        exit /b 0
    )
)
findstr /C:"你的key" .env >nul 2>&1
if not errorlevel 1 (
    echo [警告] .env 中的 LLM_API_KEY 尚未填写，大模型将无法调用。
    echo         现在打开文件填写，保存后关闭记事本继续。
    notepad .env
)

REM ---------- 1. 检查 Docker ----------
where docker >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Docker，请先安装 Docker Desktop 并启动。
    pause
    exit /b 1
)
docker info >nul 2>&1
if errorlevel 1 (
    echo [错误] Docker 未运行，请先启动 Docker Desktop。
    pause
    exit /b 1
)

REM ---------- 2. 启动 Milvus ----------
echo [1/5] 启动 Milvus 向量库（etcd + minio + milvus）...
docker compose up -d etcd minio milvus
if errorlevel 1 (
    echo [错误] Milvus 启动失败，请查看 docker compose logs。
    pause
    exit /b 1
)

echo [2/5] 等待 Milvus 就绪（首次启动约 1-2 分钟）...
set /a tries=0
:waitloop
set /a tries+=1
curl -s -f http://localhost:9091/healthz >nul 2>&1
if not errorlevel 1 goto ready
if %tries% GEQ 60 (
    echo [错误] Milvus 健康检查超时，请执行 docker compose logs milvus 排查。
    pause
    exit /b 1
)
timeout /t 3 /nobreak >nul
goto waitloop
:ready
echo       Milvus 已就绪。

REM ---------- 3. Python 环境 ----------
REM 依赖包（torch/pydantic 等）暂无 Python 3.13+ 预编译版本，优先挑选 3.10-3.12
set "PYEXE="
call :pick_py 3.12
call :pick_py 3.11
call :pick_py 3.10
if not defined PYEXE call :pick_default
if not defined PYEXE (
    echo [错误] 未找到可用的 Python 3.10 / 3.11 / 3.12。
    echo         Python 3.13+ 缺少依赖包预编译版本，安装会失败。
    echo         请到 https://www.python.org/downloads/ 安装 3.12 并勾选 Add to PATH。
    pause
    exit /b 1
)
echo       使用 Python: %PYEXE%
if not exist ".venv" (
    echo [3/5] 创建虚拟环境 .venv ...
    %PYEXE% -m venv .venv
    if errorlevel 1 (
        echo [错误] 虚拟环境创建失败。
        pause
        exit /b 1
    )
)

call .venv\Scripts\activate.bat

if not exist ".venv\.deps_ok" (
    echo [4/5] 安装依赖（首次约 3-8 分钟）...
    python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
    python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络。
        pause
        exit /b 1
    )
    echo ok > ".venv\.deps_ok"
) else (
    echo [4/5] 依赖已安装，跳过。
)

REM ---------- 4. 初始化知识库（不内置示例） ----------
if not exist "logs\.ingested" (
    echo [5/5] 初始化空知识库（默认不内置任何测试数据）...
    python -m scripts.ensure_kb
    if errorlevel 1 (
        echo [警告] 知识库初始化失败，请确认 Docker 与 Milvus 已启动。
    ) else (
        if not exist "logs" mkdir logs
        echo ok > "logs\.ingested"
    )
    echo        当前知识库为空，可选：
    echo          - 运行 generate_test_data.bat 一键生成测试内容
    echo          - 在知识库管理页直接上传自己的文档
) else (
    echo [5/5] 知识库已初始化，跳过。
)

echo.
echo ============================================
echo   启动 API 服务
echo   接口文档: http://127.0.0.1:8001/docs
echo   按 Ctrl+C 停止服务
echo ============================================
echo.
start "" http://127.0.0.1:8001/docs
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001

pause

exit /b 0

:pick_py
if defined PYEXE goto :eof
py -%1 -c "import sys" >nul 2>&1
if errorlevel 1 goto :eof
set "PYEXE=py -%1"
goto :eof

:pick_default
where python >nul 2>&1
if errorlevel 1 goto :eof
for /f "delims=" %%O in ('python -c "import sys;print(1 if (3,10)<=sys.version_info<(3,13) else 0)" 2^>nul') do if "%%O"=="1" set "PYEXE=python"
goto :eof