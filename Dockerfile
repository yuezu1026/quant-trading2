# Quant Trading — Docker 镜像
#
# 构建:
#   docker build -t quant-trading .
#
# 运行:
#   docker run -p 8000:8000 quant-trading

FROM python:3.11-slim

LABEL maintainer="quant-trading"
LABEL description="A股量化交易系统 — 回测/模拟/实盘"

# 环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai

WORKDIR /app

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        curl \
        tzdata \
        && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖 (分层缓存)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY . .

# 创建数据目录
RUN mkdir -p /app/data/cache /app/logs

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 默认启动命令
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
