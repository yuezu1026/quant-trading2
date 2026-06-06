# 量化交易程序 — 需求与设计方案

## 1. 项目概述

构建一个面向 **A股市场** 的量化交易系统，覆盖 **回测 → 模拟交易 → 实盘交易** 的完整闭环。
- **目标市场**：沪深A股（可扩展至ETF、可转债）
- **技术栈**：Python
- **用户**：个人资深开发者

## 2. 需求分析

### 2.1 功能性需求

| 模块 | 需求 | 优先级 |
|------|------|--------|
| 数据采集 | 日线/分钟线历史数据 + 实时行情订阅 | P0 |
| 数据存储 | 本地数据库，统一数据格式，增量更新 | P0 |
| 策略引擎 | 策略基类、信号生成、仓位计算 | P0 |
| 回测引擎 | 事件驱动回测，含手续费/滑点/T+1/涨跌停 | P0 |
| 模拟交易 | 接入实时行情，虚拟资金，模拟撮合 | P1 |
| 实盘接口 | 对接券商API，下单/撤单/查持仓 | P2 |
| 风控模块 | 仓位限制、止损止盈、最大回撤控制 | P0 |
| 监控面板 | Web界面，查看策略状态/收益曲线/持仓 | P1 |
| 日志告警 | 交易日志、异常告警（钉钉/微信通知） | P1 |

### 2.2 非功能性需求

- **性能**：回测引擎需支持5年以上日线数据秒级完成
- **可靠性**：实盘交易需保证接口重连、订单状态同步
- **扩展性**：策略以插件形式加载，核心引擎与策略解耦
- **可测试性**：核心模块单元测试覆盖率 > 80%

## 3. 技术选型

### 3.1 推荐技术栈

| 层次 | 技术 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | 量化生态最完善 |
| 数据获取 | AkShare + Efinance | 免费开源，覆盖A股历史/实时数据 |
| 数据库 | SQLite (开发) / PostgreSQL (生产) | 轻量起步，可升级 |
| 回测框架 | **自研事件驱动引擎** | A股特性（T+1/涨跌停）需要定制 |
| Web框架 | FastAPI + Vue3 | 轻量高性能，API + 前端分离 |
| 任务调度 | APScheduler | 定时任务（收盘作业、策略运行） |
| 消息队列 | Redis | 实时行情广播、任务队列 |
| 可视化 | Plotly + ECharts | 收益曲线、K线图 |
| 实盘接口 | QMT（迅投）或 XTP | 个人投资者可用的A股量化接口 |
| 部署 | Docker + docker-compose | 一键部署 |

### 3.2 为什么不选现成框架

| 框架 | 问题 |
|------|------|
| Backtrader | 不原生支持T+1、涨跌停，A股适配成本高 |
| Vnpy | 过于庞大，学习曲线陡，定制困难 |
| Zipline | 美股生态，A股数据适配麻烦 |

**推荐方案**：借鉴这些框架的架构思想，自研一个轻量级事件驱动引擎。

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                     Web 监控面板 (Vue3)                    │
└───────────────────────────┬─────────────────────────────┘
                            │ FastAPI REST
┌───────────────────────────┴─────────────────────────────┐
│                    核心交易引擎                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ 策略引擎  │  │ 回测引擎  │  │ 模拟引擎  │  │ 实盘引擎  │ │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘  └────┬────┘ │
│        │              │              │             │      │
│  ┌─────┴──────────────┴──────────────┴─────────────┴────┐ │
│  │                    事件总线 (Event Bus)               │ │
│  └──────────────────────────────────────────────────────┘ │
└───────────────────────────┬─────────────────────────────┘
                            │
┌───────────────────────────┴─────────────────────────────┐
│                    基础设施层                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ 数据采集  │  │ 数据存储  │  │ 风控模块  │  │ 日志告警  │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 核心模块说明

#### 4.1 事件总线 (`core/event_bus.py`)
事件驱动架构的核心，所有模块通过事件通信：

```python
EventTypes = [
    MARKET_DATA,      # 行情数据更新
    SIGNAL,            # 策略信号
    ORDER,             # 订单事件
    FILL,              # 成交事件
    POSITION_UPDATE,   # 持仓更新
    RISK_ALERT,        # 风控告警
]
```

#### 4.2 数据层 (`data/`)
```
data/
├── providers/          # 数据源适配器
│   ├── base.py         # 抽象基类
│   ├── akshare.py      # AkShare 适配器
│   └── efinance.py     # Efinance 适配器
├── storage/            # 数据存储
│   ├── models.py       # SQLAlchemy 数据模型
│   └── repository.py   # 数据仓库
├── calendar.py         # A股交易日历
└── ticker.py           # 股票代码标准化
```

数据模型设计：
- `daily_kline`：日K线（code, date, open, high, low, close, volume, amount）
- `minute_kline`：分钟K线
- `stock_info`：股票基本信息（名称、行业、市值、ST状态等）
- `trade_calendar`：交易日历

#### 4.3 策略层 (`strategy/`)
```
strategy/
├── base.py             # 策略基类 (Strategy)
├── indicators.py       # 技术指标库（基于pandas/numpy）
├── signal.py           # 信号定义
├── portfolio.py        # 组合管理（仓位分配）
└── examples/
    ├── ma_cross.py     # 双均线策略
    └── mean_revert.py  # 均值回归
```

策略基类接口：
```python
class Strategy(ABC):
    @abstractmethod
    def on_bar(self, bar: Bar, portfolio: Portfolio) -> List[Signal]: ...
    @abstractmethod
    def on_order_filled(self, fill: Fill) -> None: ...
    def on_risk_alert(self, alert: RiskAlert) -> None: ...
```

#### 4.4 回测引擎 (`backtest/`)
```
backtest/
├── engine.py           # 回测引擎主循环
├── broker.py           # 模拟券商（撮合引擎）
├── recorder.py         # 回测结果记录
├── analyzer.py         # 绩效分析（夏普比、最大回撤、胜率等）
└── report.py           # 回测报告生成
```

回测引擎核心逻辑：
1. 按时间顺序遍历历史行情数据
2. 每个 Bar 通知策略 `on_bar()`
3. 策略生成信号 → 转为订单
4. 撮合引擎模拟成交（考虑 T+1、涨跌停、滑点、手续费）
5. 更新持仓和资金
6. 记录每笔交易和资产曲线

**A股特性处理：**
- T+1：当日买入次日可卖
- 涨跌停：超过涨跌停价订单无法成交
- 印花税：卖出 0.1%，买入免
- 佣金：万2.5，最低5元
- 最小交易单位：100股（1手）

#### 4.5 模拟交易 (`paper/`)
```
paper/
├── engine.py           # 模拟交易引擎
├── broker.py           # 模拟撮合（用实时行情）
└── account.py          # 虚拟账户
```

模拟 = 回测引擎 + 实时行情 + 虚拟资金。能验证策略在真实行情中的表现，但无实际成交。

#### 4.6 实盘交易 (`live/`)
```
live/
├── engine.py           # 实盘交易引擎
├── gateways/           # 券商网关
│   ├── base.py         # 网关抽象基类
│   └── qmt.py          # 迅投 QMT 网关
├── order_manager.py    # 订单管理（状态同步、重试）
└── position_manager.py # 持仓管理
```

#### 4.7 风控模块 (`risk/`)
```
risk/
├── rules.py            # 风控规则
│   ├── MaxPositionRule # 单票最大仓位
│   ├── StopLossRule    # 止损规则
│   ├── DailyLossRule   # 日内最大亏损
│   └── BlacklistRule   # 黑名单（ST、高风险）
└── manager.py          # 风控管理器
```

风控规则在订单发出前校验，不通过则拦截。

#### 4.8 Web 监控 (`web/`)
```
web/
├── api/                # FastAPI 接口
│   ├── strategy.py     # 策略CRUD
│   ├── backtest.py     # 回测任务
│   ├── position.py     # 持仓查询
│   └── dashboard.py    # 仪表盘数据
├── static/             # 前端静态文件
└── ws.py               # WebSocket 实时推送
```

## 5. 项目目录结构

```
quant-trading/
├── config/                  # 配置文件
│   ├── settings.yaml        # 主配置
│   └── strategies.yaml      # 策略参数
├── core/                    # 核心模块
│   ├── __init__.py
│   ├── event_bus.py         # 事件总线
│   └── types.py             # 核心数据类型
├── data/                    # 数据层
│   ├── __init__.py
│   ├── providers/
│   ├── storage/
│   ├── calendar.py
│   └── ticker.py
├── strategy/                # 策略层
│   ├── __init__.py
│   ├── base.py
│   ├── indicators.py
│   ├── signal.py
│   ├── portfolio.py
│   └── examples/
├── backtest/                # 回测
│   ├── __init__.py
│   ├── engine.py
│   ├── broker.py
│   ├── recorder.py
│   └── analyzer.py
├── paper/                   # 模拟交易
│   ├── __init__.py
│   ├── engine.py
│   ├── broker.py
│   └── account.py
├── live/                    # 实盘交易
│   ├── __init__.py
│   ├── engine.py
│   ├── gateways/
│   ├── order_manager.py
│   └── position_manager.py
├── risk/                    # 风控
│   ├── __init__.py
│   ├── rules.py
│   └── manager.py
├── web/                     # Web服务
│   ├── __init__.py
│   ├── api/
│   ├── ws.py
│   └── app.py
├── tests/                   # 测试
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── Makefile
└── README.md
```

## 6. 实施路线图

### Phase 1：基础设施 + 回测 MVP（2-3周）
1. 项目骨架搭建（目录结构、配置管理、依赖安装）
2. 数据层：AkShare适配器 + SQLite存储 + 交易日历
3. 事件总线 + 核心类型定义
4. 策略基类 + 一个简单策略示例（双均线）
5. 回测引擎（含A股规则）
6. 绩效分析 + 简单回测报告
7. 单元测试

### Phase 2：模拟交易 + Web界面（2-3周）
1. 模拟交易引擎（实时行情 + 虚拟撮合）
2. Web API（FastAPI）
3. 前端仪表盘（Vue3 + ECharts）
4. WebSocket实时推送
5. 策略管理界面

### Phase 3：实盘接入 + 风控完善（2-3周）
1. 券商网关层设计
2. QMT/XTP 实盘接口实现
3. 风控模块完善
4. 订单管理与状态同步
5. 日志 + 告警（钉钉/微信）

### Phase 4：生产化（1-2周）
1. Docker 容器化部署
2. 集成测试 + 压力测试
3. 文档完善
4. 监控与运维

## 7. 关键设计决策

### 7.1 为什么选择事件驱动而非向量化回测？

| 维度 | 事件驱动 | 向量化 |
|------|----------|--------|
| 实现难度 | 中 | 低 |
| A股规则适配 | ✅ 容易（T+1、涨跌停天然适配） | ❌ 困难（需后处理） |
| 实盘复用 | ✅ 代码几乎直接复用 | ❌ 需完全重写 |
| 回测速度 | 较慢（但仍可接受） | 极快 |

选择事件驱动的核心原因：**回测代码可以最大程度复用到模拟和实盘**，保证策略行为一致性。

### 7.2 策略与引擎完全解耦

策略只需实现 `on_bar()` 方法，接收行情返回信号，不关心是回测还是实盘。通过依赖注入切换引擎：

```python
# 回测
engine = BacktestEngine(strategy, data_provider=HistoryDataProvider())
# 模拟
engine = PaperEngine(strategy, data_provider=RealTimeDataProvider())
# 实盘
engine = LiveEngine(strategy, data_provider=RealTimeDataProvider(), gateway=QMTGateway())
```

### 7.3 数据标准化

所有数据源统一输出 Pandas DataFrame，列名标准化：
- `code`, `date`, `open`, `high`, `low`, `close`, `volume`, `amount`
- 这样可以随时切换数据源（AkShare → Wind → Tushare）而不影响上层逻辑

## 8. 依赖清单 (`requirements.txt`)

```
# 核心
numpy>=1.24
pandas>=2.0
pydantic>=2.0
pyyaml>=6.0

# 数据
akshare>=1.12
efinance>=0.4

# 数据库
sqlalchemy>=2.0
aiosqlite>=0.19

# Web
fastapi>=0.100
uvicorn>=0.23
websockets>=11

# 任务调度
apscheduler>=3.10

# 可视化（可选）
plotly>=5.15

# 测试
pytest>=7.4
pytest-asyncio>=0.21
```

## 9. 风险与注意事项

1. **数据质量**：AkShare 免费但稳定性一般，需处理断连和缺失数据
2. **实盘门槛**：A股实盘需要证券账户 + API权限，QMT有资金门槛
3. **合规性**：程序化交易可能需要报备，注意交易所规则
4. **回测过拟合**：策略在回测表现好不代表实盘有效，需要多周期多品种验证
5. **网络延迟**：日内策略对延迟敏感，日线策略影响较小
