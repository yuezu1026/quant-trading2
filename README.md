# 📊 Quant Trading — A股量化交易系统

事件驱动架构的 A 股量化交易系统，覆盖 **回测 → 模拟交易 → 实盘交易** 完整闭环。

## ✨ 特性

- 🧩 **事件驱动架构** — 回测代码直接复用到模拟和实盘，策略行为一致
- 🇨🇳 **A 股原生支持** — T+1、涨跌停、印花税(0.1%)、佣金(万2.5)、1手=100股
- 📈 **完整回测** — 夏普比率、最大回撤、卡玛比率、胜率、盈亏比
- 🔌 **券商实盘** — QMT(迅投) 网关，MiniQMT 个人可用
- 🌐 **Web 仪表盘** — FastAPI + WebSocket 实时推送 + ECharts 可视化
- 🛡️ **多层风控** — 仓位限制、止损、日内亏损、黑名单
- 🚨 **多渠道告警** — 钉钉、企业微信机器人
- 🐳 **Docker 部署** — 一键启动，PostgreSQL + Redis

## 🚀 快速开始

### 环境要求

- Python 3.11+
- (可选) Docker & Docker Compose

### 安装

```bash
cd quant-trading
pip install -r requirements.txt
```

### 5分钟体验

```bash
# 1. 运行回测演示
python demo.py

# 2. 启动 Web 仪表盘
uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload

# 3. 浏览器打开
#    仪表盘:  http://localhost:8000
#    API文档: http://localhost:8000/docs
```

### Docker 部署

```bash
docker-compose up -d
# 访问 http://localhost:8000
```

## 📖 架构

```
┌──────────────────────────────────────────┐
│           Web Dashboard (Vue3/ECharts)    │
└─────────────────┬────────────────────────┘
                  │ FastAPI + WebSocket
┌─────────────────┴────────────────────────┐
│            Trading Engines                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│  │Backtest  │ │  Paper   │ │  Live    │ │
│  │Engine    │ │  Engine  │ │  Engine  │ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ │
│       └─────────────┼────────────┘       │
│              ┌──────┴──────┐             │
│              │ Event Bus   │             │
│              └──────┬──────┘             │
│        ┌────────────┼────────────┐       │
│   ┌────┴────┐  ┌────┴────┐  ┌───┴────┐  │
│   │Strategy │  │  Risk   │  │  Alert │  │
│   └─────────┘  └─────────┘  └────────┘  │
└─────────────────┬────────────────────────┘
                  │
┌─────────────────┴────────────────────────┐
│          Infrastructure                   │
│  ┌────────┐ ┌────────┐ ┌──────────────┐ │
│  │  Data  │ │Gateway │ │Order/Position│ │
│  │Providers│ │ (QMT)  │ │  Manager     │ │
│  └────────┘ └────────┘ └──────────────┘ │
└──────────────────────────────────────────┘
```

## 📁 项目结构

```
quant-trading/
├── core/                  # 核心：数据类型 + 事件总线
│   ├── types.py           # Bar/Order/Fill/Account 等
│   └── event_bus.py       # 发布/订阅事件总线
├── data/                  # 数据层
│   ├── providers/         # 数据源适配 (AkShare)
│   ├── storage/           # ORM 存储 (SQLite/PostgreSQL)
│   └── calendar.py        # A股交易日历
├── strategy/              # 策略层
│   ├── base.py            # 策略基类
│   ├── indicators.py      # 技术指标库
│   └── examples/          # 示例策略
├── backtest/              # 回测引擎
│   ├── engine.py          # 事件驱动回测主循环
│   ├── broker.py          # 模拟券商撮合
│   ├── analyzer.py        # 绩效分析
│   └── recorder.py        # 结果记录
├── paper/                 # 模拟交易
│   ├── engine.py          # 实时行情模拟引擎
│   └── account.py         # 虚拟账户
├── live/                  # 实盘交易
│   ├── engine.py          # 实盘引擎
│   ├── gateways/qmt.py    # QMT 网关
│   ├── order_manager.py   # 订单状态机
│   └── position_manager.py # 持仓管理+对账
├── risk/                  # 风控
│   └── manager.py         # 仓位/止损/日内/黑名单
├── web/                   # Web 服务
│   ├── app.py             # FastAPI 应用
│   ├── ws.py              # WebSocket 推送
│   └── api/               # REST API
├── alert.py               # 告警系统 (钉钉/企微)
├── tests/                 # 测试
├── config/settings.yaml   # 配置文件
├── docker-compose.yml     # Docker 部署
├── Dockerfile
├── Makefile
└── requirements.txt
```

## 🔧 配置

编辑 `config/settings.yaml`:

```yaml
backtest:
  initial_cash: 100000.0
  commission_rate: 0.00025    # 万2.5
  stamp_tax_rate: 0.001       # 0.1%

live:
  gateway: qmt
  qmt:
    mini: true
    path: "D:\\QMT\\userdata_mini"

alert:
  dingtalk_webhook: "https://oapi.dingtalk.com/robot/send?access_token=xxx"
```

## 📝 编写策略

只需继承 `Strategy` 并实现 `on_bar()`:

```python
from strategy.base import Strategy
from strategy.indicators import sma, cross_up

class MyStrategy(Strategy):
    def __init__(self):
        super().__init__(name="my_strategy")
        self._prices = []

    def on_bar(self, bar, account):
        self._prices.append(bar.close)

        if len(self._prices) < 20:
            return []

        ma5 = sma(pd.Series(self._prices), 5).iloc[-1]
        ma20 = sma(pd.Series(self._prices), 20).iloc[-1]

        if ma5 > ma20 and not self.has_position(bar.code, account):
            return [self.buy(bar.code, 1000, reason="金叉")]

        if ma5 < ma20 and self.has_position(bar.code, account):
            pos = self.position_for(bar.code, account)
            return [self.sell(bar.code, pos.quantity, reason="死叉")]

        return []
```

## 🧪 测试

```bash
# 单元测试
pytest tests/ -v

# 集成测试
pytest tests/ -v -k "integration"

# 覆盖率
pytest tests/ -v --cov=. --cov-report=html
```

## 📊 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 仪表盘首页 |
| GET | `/health` | 健康检查 |
| GET | `/api/strategy/` | 策略列表 |
| POST | `/api/strategy/` | 注册策略 |
| POST | `/api/strategy/{name}/start` | 启动策略 |
| POST | `/api/strategy/{name}/stop` | 停止策略 |
| POST | `/api/backtest/run` | 提交回测任务 |
| GET | `/api/backtest/tasks/{id}` | 查询回测状态 |
| GET | `/api/dashboard/overview` | 账户概览 |
| GET | `/api/dashboard/positions` | 持仓列表 |
| WS | `/api/dashboard/ws` | WebSocket 实时推送 |

## ⚠️ 风险提示

- 本系统仅供学习和研究使用
- 量化交易存在风险，历史回测不代表未来收益
- 实盘交易前请充分测试，建议先模拟运行
- 注意交易所程序化交易报备要求
- 数据源 (AkShare) 免费但稳定性有限，实盘建议使用付费数据

## 📄 License

MIT
