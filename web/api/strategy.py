"""
策略管理 API
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/strategy", tags=["strategy"])

# 全局策略注册表（实际项目可持久化到DB）
_strategies: dict[str, dict] = {}


class StrategyConfig(BaseModel):
    name: str
    class_name: str
    params: dict = {}


class StrategyStatus(BaseModel):
    name: str
    is_running: bool
    params: dict
    stats: dict = {}


@router.get("/")
async def list_strategies() -> list[StrategyStatus]:
    """列出所有已注册的策略"""
    return [
        StrategyStatus(
            name=v["name"],
            is_running=v.get("running", False),
            params=v.get("params", {}),
        )
        for v in _strategies.values()
    ]


@router.post("/")
async def register_strategy(config: StrategyConfig) -> dict:
    """注册策略"""
    if config.name in _strategies:
        raise HTTPException(409, f"策略 '{config.name}' 已存在")

    _strategies[config.name] = {
        "name": config.name,
        "class_name": config.class_name,
        "params": config.params,
        "running": False,
        "stats": {},
    }
    return {"status": "ok", "name": config.name}


@router.put("/{name}/params")
async def update_params(name: str, params: dict) -> dict:
    """更新策略参数（运行中也可调）"""
    if name not in _strategies:
        raise HTTPException(404, f"策略 '{name}' 不存在")

    _strategies[name]["params"].update(params)
    return {"status": "ok", "name": name, "params": _strategies[name]["params"]}


@router.post("/{name}/start")
async def start_strategy(name: str) -> dict:
    """启动策略"""
    if name not in _strategies:
        raise HTTPException(404, f"策略 '{name}' 不存在")

    _strategies[name]["running"] = True
    return {"status": "ok", "name": name, "running": True}


@router.post("/{name}/stop")
async def stop_strategy(name: str) -> dict:
    """停止策略"""
    if name not in _strategies:
        raise HTTPException(404, f"策略 '{name}' 不存在")

    _strategies[name]["running"] = False
    return {"status": "ok", "name": name, "running": False}


@router.delete("/{name}")
async def remove_strategy(name: str) -> dict:
    """删除策略"""
    if name not in _strategies:
        raise HTTPException(404, f"策略 '{name}' 不存在")

    del _strategies[name]
    return {"status": "ok"}
