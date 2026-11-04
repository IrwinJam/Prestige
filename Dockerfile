# The Prestige gateway as a container.
#   docker build -t prestige .
#   docker run --rm -p 127.0.0.1:8787:8787 -e HARNESS_API_KEY -v prestige-data:/data prestige \
#     serve --labels banking --muse --policies cache,reason --set reason.escalate=false --max-total 20
# With no arguments it starts a simulated gateway, which needs no key and spends nothing.

FROM python:3.12-slim

# git is only needed to install the pinned cost harness, then it goes
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY prestige ./prestige
RUN pip install --no-cache-dir . \
    && apt-get purge -y git && apt-get autoremove -y

RUN useradd --create-home prestige && mkdir /data && chown prestige /data
USER prestige
VOLUME /data

# Inside a container the gateway has to listen on every interface. Publish it to 127.0.0.1 on the host,
# as above, unless it sits behind your own auth.
ENV HARNESS_HOST=0.0.0.0
EXPOSE 8787

ENTRYPOINT ["prestige"]
CMD ["serve", "--simulate", "--labels", "banking", "--db", "/data/prestige.sqlite"]
