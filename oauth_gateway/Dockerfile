FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 FASTMCP_HOME=/data
WORKDIR /srv
COPY oauth_gateway/requirements.txt /srv/requirements.txt
RUN pip install --no-cache-dir -r /srv/requirements.txt \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin mcp \
    && mkdir -p /data \
    && chown 10001:10001 /data
COPY --chown=10001:10001 oauth_gateway /srv/oauth_gateway
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "oauth_gateway.app"]
