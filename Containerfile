FROM docker.io/library/caddy:2.10.2-alpine AS caddy

FROM docker.io/library/python:3.14.0-alpine3.22
ARG APP_VERSION=0.1.0-dev
LABEL org.opencontainers.image.title="Wise Route Manager" \
      org.opencontainers.image.description="Coordinated LAN and Pangolin route management for Unraid" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.licenses="Apache-2.0"

COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
RUN apk add --no-cache libcap \
    && setcap cap_net_bind_service=+ep /usr/local/bin/caddy \
    && addgroup -S -g 1000 wiseroute && adduser -S -D -H -u 1000 -G wiseroute wiseroute \
    && mkdir -p /app /config /run/wise-route-manager \
    && chown -R wiseroute:wiseroute /app /config /run/wise-route-manager
COPY --chown=wiseroute:wiseroute app /app/app
COPY --chown=wiseroute:wiseroute container /app/container
COPY --chown=wiseroute:wiseroute requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
ENV PYTHONPATH=/app PYTHONUNBUFFERED=1 WISE_MASTER_KEY_FILE=/config/master.key \
    XDG_CONFIG_HOME=/config/xdg/config XDG_DATA_HOME=/config/xdg/data
USER wiseroute
VOLUME ["/config"]
EXPOSE 80 443 9080
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9080/healthz', timeout=2)"]
ENTRYPOINT ["/app/container/entrypoint.sh"]
