FROM python:3.12-slim
WORKDIR /app
COPY requirements-tested.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-tested.txt
COPY wind_forecast ./wind_forecast
COPY config.json ./config.json
RUN pip install --no-cache-dir --no-deps .
USER 65532:65532
EXPOSE 8000
ENV ML_HTTP_ADDR=:8000
CMD ["python", "-m", "wind_forecast.backend_api"]
