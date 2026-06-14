# ALPHA Advisor — container image for Azure Container Apps (or any OCI runtime).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Install deps first for layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt fastapi "uvicorn[standard]"

# App code.
COPY src ./src

# Non-root for least privilege.
RUN useradd -m appuser
USER appuser

EXPOSE 8200
# Provider/secrets come from the environment (Azure Container Apps secrets / Key Vault).
CMD ["uvicorn", "alpha.api:app", "--host", "0.0.0.0", "--port", "8200"]
