"""
Quant Trading — FastAPI Web 服务

启动方式:
    uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload

API 文档:
    http://localhost:8000/docs
    http://localhost:8000/redoc
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from .api import strategy, backtest, dashboard
from .ws import manager as ws_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期"""
    logger.info("Quant Trading API 启动")
    # 启动仪表盘模拟器
    from .api.dashboard import start_simulator
    start_simulator()
    logger.info("仪表盘模拟器已启动")
    yield
    logger.info("Quant Trading API 关闭")


app = FastAPI(
    title="Quant Trading API",
    description="A股量化交易系统 — 回测/模拟/实盘",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(strategy.router)
app.include_router(backtest.router)
app.include_router(dashboard.router)


# ============================================================================
# 首页
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def index():
    """仪表盘首页（简易HTML）"""
    return """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant Trading Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.5.0/dist/echarts.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; }
        .header { background: #1e293b; padding: 16px 24px; border-bottom: 1px solid #334155; }
        .header h1 { font-size: 20px; color: #38bdf8; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; padding: 24px; }
        .card { background: #1e293b; border-radius: 12px; padding: 20px; border: 1px solid #334155; }
        .card h3 { font-size: 14px; color: #94a3b8; margin-bottom: 8px; }
        .card .value { font-size: 28px; font-weight: bold; color: #f1f5f9; }
        .positive { color: #22c55e; }
        .negative { color: #ef4444; }
        .chart-container { background: #1e293b; border-radius: 12px; padding: 20px; margin: 0 24px 24px; border: 1px solid #334155; }
        .chart-container h3 { font-size: 14px; color: #94a3b8; margin-bottom: 12px; }
        .chart { width: 100%; height: 400px; }
        .status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
        .status-dot.running { background: #22c55e; }
        .status-dot.stopped { background: #64748b; }
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Quant Trading Dashboard</h1>
    </div>

    <div class="grid" id="cards">
        <div class="card">
            <h3>总资产</h3>
            <div class="value" id="total_asset">¥--</div>
        </div>
        <div class="card">
            <h3>可用资金</h3>
            <div class="value" id="cash">¥--</div>
        </div>
        <div class="card">
            <h3>已实现盈亏</h3>
            <div class="value" id="pnl">¥--</div>
        </div>
        <div class="card">
            <h3>浮动盈亏</h3>
            <div class="value" id="unrealized_pnl">¥--</div>
        </div>
        <div class="card">
            <h3>系统状态</h3>
            <div class="value" id="status"><span class="status-dot stopped"></span>--</div>
        </div>
        <div class="card">
            <h3>数据源</h3>
            <div class="value" id="data_source" style="font-size:14px;">--</div>
        </div>
        <div class="card">
            <h3>当前策略</h3>
            <div class="value" id="strategy_info" style="font-size:14px;">--</div>
        </div>
    </div>

    <div class="chart-container">
        <h3>资产曲线</h3>
        <div class="chart" id="equity_chart"></div>
    </div>

    <script>
        // 资产曲线数据缓存（保留最近 120 个点）
        const MAX_POINTS = 120;
        const dates = [];
        const values = [];

        const chart = echarts.init(document.getElementById('equity_chart'));
        chart.setOption({
            backgroundColor: 'transparent',
            grid: { left: 65, right: 20, top: 20, bottom: 30 },
            xAxis: { type: 'category', data: dates,
                axisLine: { lineStyle: { color: '#475569' } },
                axisLabel: { color: '#94a3b8', fontSize: 10 }
            },
            yAxis: { type: 'value',
                axisLine: { lineStyle: { color: '#475569' } },
                axisLabel: { color: '#94a3b8' },
                splitLine: { lineStyle: { color: '#1e293b' } }
            },
            series: [{
                type: 'line',
                data: values,
                smooth: true,
                lineStyle: { color: '#38bdf8', width: 2 },
                areaStyle: { color: 'rgba(56,189,248,0.1)' },
                showSymbol: false,
            }],
            animation: true,
        });

        function addDataPoint(asset) {
            const now = new Date();
            const time = now.getHours().toString().padStart(2,'0') + ':'
                       + now.getMinutes().toString().padStart(2,'0') + ':'
                       + now.getSeconds().toString().padStart(2,'0');
            dates.push(time);
            values.push(asset);
            if (dates.length > MAX_POINTS) { dates.shift(); values.shift(); }
            chart.setOption({
                xAxis: { data: dates },
                series: [{ data: values }]
            });
        }

        // 加载系统配置（策略 + 数据源）
        async function loadConfig() {
            try {
                const res = await fetch('/api/dashboard/config');
                const cfg = await res.json();
                // 数据源
                const dsEl = document.getElementById('data_source');
                const dsIcon = cfg.tushare_configured ? '✅' : '⚠️';
                const envLabel = cfg.environment === 'docker' ? '🐳 Docker' : '💻 本地';
                dsEl.innerHTML = dsIcon + ' ' + cfg.data_source + '<br><small style="color:#94a3b8;">' + envLabel + '</small>';
                // 策略
                const sEl = document.getElementById('strategy_info');
                if (cfg.strategies && cfg.strategies.length > 0) {
                    const s = cfg.strategies[0];
                    const dot = s.is_running ? '<span class="status-dot running"></span>' : '<span class="status-dot stopped"></span>';
                    sEl.innerHTML = dot + ' ' + s.class_name + '<br><small style="color:#94a3b8;">' + s.name + ' | params: ' + JSON.stringify(s.params) + '</small>';
                } else {
                    sEl.innerHTML = '未配置策略';
                }
            } catch(e) {}
        }
        loadConfig();
        setInterval(loadConfig, 30000);

        // WebSocket 连接
        const ws = new WebSocket(`ws://${location.host}/api/dashboard/ws`);
        ws.onmessage = (e) => {
            const msg = JSON.parse(e.data);
            if (msg.channel === 'account' && msg.data.total_asset !== undefined) {
                document.getElementById('total_asset').innerText = '¥' + (msg.data.total_asset || 0).toLocaleString();
                document.getElementById('cash').innerText = '¥' + (msg.data.cash || 0).toLocaleString();
                const pnl = msg.data.realized_pnl || 0;
                const pnlEl = document.getElementById('pnl');
                pnlEl.innerText = (pnl >= 0 ? '+' : '') + '¥' + pnl.toLocaleString();
                pnlEl.className = 'value ' + (pnl >= 0 ? 'positive' : 'negative');
                const upnl = msg.data.unrealized_pnl || 0;
                const upnlEl = document.getElementById('unrealized_pnl');
                upnlEl.innerText = (upnl >= 0 ? '+' : '') + '¥' + upnl.toLocaleString();
                upnlEl.className = 'value ' + (upnl >= 0 ? 'positive' : 'negative');
                // 更新资产曲线
                addDataPoint(msg.data.total_asset);
            }
        };
        ws.onopen = () => {
            document.getElementById('status').innerHTML = '<span class="status-dot running"></span>已连接';
        };
        ws.onclose = () => {
            document.getElementById('status').innerHTML = '<span class="status-dot stopped"></span>已断开';
        };

        // 定时拉取概览 + 更新曲线 (每3秒)
        setInterval(async () => {
            try {
                const res = await fetch('/api/dashboard/overview');
                const data = await res.json();
                document.getElementById('total_asset').innerText = '¥' + (data.total_asset || 0).toLocaleString();
                document.getElementById('cash').innerText = '¥' + (data.cash || 0).toLocaleString();
                const pnl2 = data.realized_pnl || 0;
                const pnlEl2 = document.getElementById('pnl');
                pnlEl2.innerText = (pnl2 >= 0 ? '+' : '') + '¥' + pnl2.toLocaleString();
                pnlEl2.className = 'value ' + (pnl2 >= 0 ? 'positive' : 'negative');
                const upnl2 = data.unrealized_pnl || 0;
                const upnlEl2 = document.getElementById('unrealized_pnl');
                upnlEl2.innerText = (upnl2 >= 0 ? '+' : '') + '¥' + upnl2.toLocaleString();
                upnlEl2.className = 'value ' + (upnl2 >= 0 ? 'positive' : 'negative');
                document.getElementById('status').innerHTML =
                    '<span class="status-dot ' + (data.is_running ? 'running' : 'stopped') + '"></span>' +
                    (data.is_running ? '运行中' : '已停止');
                // 直接更新资产曲线
                addDataPoint(data.total_asset);
            } catch(e) {}
        }, 3000);
    </script>
</body>
</html>
    """


# ============================================================================
# 健康检查
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "websocket_connections": ws_manager.active_count,
    }
