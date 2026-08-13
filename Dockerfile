# The MTProto proxy binary is lifted from the upstream mtg image (a
# `scratch` image containing a single static binary at /mtg). mtg is the
# well-known, battle-tested Go implementation of Telegram's MTProto proxy —
# using it instead of a from-scratch reimplementation is what makes the
# MTProto feature reliable out of the box.
FROM nineseconds/mtg:2.2.8 AS mtg

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    MTPROXY_BIN=/usr/local/bin/mtg

WORKDIR /app

COPY --from=mtg /mtg /usr/local/bin/mtg

COPY requirements.txt .
RUN pip install --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data && /usr/local/bin/mtg --version

# 8080 serves the panel over HTTP (Railway/Render override this via $PORT);
# 443 is the default internal MTProto port — point a Railway TCP Proxy (or
# equivalent) at it to expose MTProto publicly. See README.md's "MTProto
# Proxy" section.
EXPOSE 8080 443

CMD ["python", "main.py"]
