# The Prestige gateway as a container.
#   docker build -t prestige .
#   docker run --rm --network host -e HARNESS_API_KEY -v prestige-data:/data prestige \
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

# The gateway only ever listens on localhost, a rule the cost harness enforces. Run the container with
# host networking, as above, so that's localhost on the host and nothing else can reach it.
EXPOSE 8787

ENTRYPOINT ["prestige"]
CMD ["serve", "--simulate", "--labels", "banking", "--db", "/data/prestige.sqlite"]
