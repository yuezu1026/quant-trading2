.PHONY: help install test test-cov test-int lint clean run web docker-build docker-up docker-down data-sync

# ============================================================================
# Quant Trading — Makefile
# ============================================================================

help:  ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------
# 开发
# ------------------------------------------------------------------

install:  ## 安装依赖
	pip install -r requirements.txt
	pip install -r requirements-dev.txt 2>/dev/null || true

test:  ## 运行单元测试
	python -m pytest tests/ -v --tb=short

test-cov:  ## 运行测试并生成覆盖率报告
	python -m pytest tests/ -v --cov=. --cov-report=html --cov-report=term

test-int:  ## 运行集成测试
	python -m pytest tests/ -v -m integration --tb=short 2>/dev/null || python -m pytest tests/ -v -k "test_integration" --tb=short

lint:  ## 代码检查
	ruff check . 2>/dev/null || echo "ruff not installed, skip"

format:  ## 代码格式化
	ruff format . 2>/dev/null || black . 2>/dev/null || echo "no formatter installed"

clean:  ## 清理临时文件
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .coverage htmlcov dist build *.egg-info

# ------------------------------------------------------------------
# 运行
# ------------------------------------------------------------------

run:  ## 启动 Web 服务（开发模式）
	uvicorn web.app:app --host 0.0.0.0 --port 8000 --reload

demo:  ## 运行回测演示
	python demo.py

# ------------------------------------------------------------------
# Docker
# ------------------------------------------------------------------

docker-build:  ## 构建 Docker 镜像
	docker build -t quant-trading .

docker-up:  ## 启动所有 Docker 服务
	docker-compose up -d

docker-down:  ## 停止所有 Docker 服务
	docker-compose down

docker-logs:  ## 查看应用日志
	docker-compose logs -f app

docker-shell:  ## 进入容器
	docker-compose exec app bash

# ------------------------------------------------------------------
# 数据库
# ------------------------------------------------------------------

db-init:  ## 初始化数据库
	python -c "from data.storage.models import Base; from sqlalchemy import create_engine; Base.metadata.create_all(create_engine('sqlite:///quant.db'))"

db-migrate:  ## 数据库迁移（预留）
	@echo "Alembic migration not configured yet"

# ------------------------------------------------------------------
# 数据
# ------------------------------------------------------------------

data-sync:  ## 同步交易日历和股票列表
	python -c "from data.calendar import TradingCalendar; c = TradingCalendar(); c.load(); print(f'交易日历: {len(c.all_dates)}天')"
