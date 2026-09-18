FROM python:3.10-slim

WORKDIR /opt/render/project/src

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev && rm -rf /var/lib/apt/lists/*

# Python 依赖 — 先复制 requirements.txt 利用缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY . .

# 创建数据目录
RUN mkdir -p data/papers data/figures data/db/chroma

# Render 要求绑定 0.0.0.0，端口从 PORT 环境变量读取
ENV HOST=0.0.0.0
ENV PORT=10000

EXPOSE 10000

CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
