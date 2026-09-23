FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-writer fonts-liberation \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY app ./app
RUN useradd --create-home --uid 10001 bidreview && mkdir /data && chown bidreview:bidreview /data
USER bidreview
ENV APP_MODE=production BID_FACTORY_DB=/data/bid-factory.sqlite3
EXPOSE 8765
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8765", "--workers", "1", "--no-proxy-headers"]
