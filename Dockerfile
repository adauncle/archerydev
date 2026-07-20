FROM python:3.11-slim

# 防止 Python 写入 .pyc
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_NO_CACHE_DIR=1

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        default-libmysqlclient-dev \
        pkg-config \
        default-mysql-client \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# 复制代码
COPY . .

EXPOSE 9123

# 默认启动命令（docker-compose 中可覆盖）
CMD ["gunicorn", "archery.wsgi:application", "-w", "4", "-b", "0.0.0.0:9123", "--access-logfile", "-"]
