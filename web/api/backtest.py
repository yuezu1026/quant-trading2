"""
回测 API
"""
from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backtest", tags=["backtest"])

_backtest_tasks: dict[str, dict] = {}


class BacktestRequest(BaseModel):
    name: str
    codes: list[str]
    start_date: date
    end_date: date
    strategy_class: str = "MACrossStrategy"
    strategy_params: dict = {}
    initial_cash: float = 100_000.0


class BacktestStatus(BaseModel):
    task_id: str
    name: str
    status: str  # pending / running / done / error
    progress: float = 0.0
    stats: dict | None = None
    error: str | None = None


@router.post("/run")
async def run_backtest(req: BacktestRequest, tasks: BackgroundTasks) -> dict:
    """启动回测任务"""
    import uuid

    task_id = f"bt_{uuid.uuid4().hex[:8]}"
    _backtest_tasks[task_id] = {
        "name": req.name,
        "status": "pending",
        "progress": 0.0,
        "stats": None,
        "error": None,
    }

    # 后台运行回测
    tasks.add_task(_run_backtest_task, task_id, req)

    return {"task_id": task_id, "status": "pending"}


@router.get("/tasks")
async def list_tasks() -> list[BacktestStatus]:
    """列出所有回测任务"""
    return [
        BacktestStatus(
            task_id=tid,
            name=t["name"],
            status=t["status"],
            progress=t["progress"],
            stats=t.get("stats"),
            error=t.get("error"),
        )
        for tid, t in _backtest_tasks.items()
    ]


@router.get("/tasks/{task_id}")
async def get_task(task_id: str) -> BacktestStatus:
    """查询回测任务状态"""
    t = _backtest_tasks.get(task_id)
    if not t:
        raise HTTPException(404, "任务不存在")

    return BacktestStatus(
        task_id=task_id,
        name=t["name"],
        status=t["status"],
        progress=t["progress"],
        stats=t.get("stats"),
        error=t.get("error"),
    )


async def _run_backtest_task(task_id: str, req: BacktestRequest) -> None:
    """后台运行回测"""
    try:
        _backtest_tasks[task_id]["status"] = "running"

        from strategy import MACrossStrategy, StrategyWrapper
        from backtest import BacktestEngine, Analyzer
        from data.providers.tushare import TuShareProvider
        from data.providers.akshare import AkShareProvider

        # 动态选择策略
        if req.strategy_class == "MACrossStrategy":
            s = MACrossStrategy(**req.strategy_params)
        else:
            raise ValueError(f"未知策略: {req.strategy_class}")

        wrapper = StrategyWrapper(s)

        # 优先 TuShare，回退 AkShare
        try:
            provider = TuShareProvider()
            provider.get_daily(req.codes[0], req.start_date, req.start_date)
        except Exception:
            provider = AkShareProvider()

        engine = BacktestEngine(
            strategy=wrapper,
            data_provider=provider,
            initial_cash=req.initial_cash,
        )

        recorder = engine.run(codes=req.codes, start=req.start_date, end=req.end_date)
        stats = Analyzer.analyze(recorder)

        _backtest_tasks[task_id]["status"] = "done"
        _backtest_tasks[task_id]["progress"] = 100.0
        _backtest_tasks[task_id]["stats"] = {
            "total_return": stats.total_return,
            "annual_return": stats.annual_return,
            "sharpe_ratio": stats.sharpe_ratio,
            "max_drawdown": stats.max_drawdown,
            "volatility": stats.volatility,
            "trade_count": stats.trade_count,
            "win_rate": stats.win_rate,
            "profit_factor": stats.profit_factor,
        }

    except Exception as e:
        logger.exception(f"回测任务失败: {task_id}")
        _backtest_tasks[task_id]["status"] = "error"
        _backtest_tasks[task_id]["error"] = str(e)
