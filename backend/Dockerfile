FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_PATH=/opt/models

RUN groupadd -g 1000 app && useradd -u 1000 -g app -m -s /usr/sbin/nologin app

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# The embedding model is part of the image, so the app needs no download at runtime.
RUN python -c "from fastembed import TextEmbedding; m = TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models'); print(len(list(m.embed(['warm up']))[0]))" \
    && chmod -R a+rX /opt/models

# Mount folders owned by the app user, so a new named volume gets this owner.
RUN mkdir -p /secrets/app /secrets/db /secrets/gw /scopes /datasets /data/raw \
    && chown -R app:app /secrets /scopes /datasets \
    && chmod 700 /secrets/app /secrets/db /secrets/gw

COPY --chown=app:app . .

# BUILD_ID: a hash of the source. It is part of the cache keys and the RAG corpus hash.
RUN find app migrations eval -type f \( -name '*.py' -o -name '*.md' -o -name '*.yaml' -o -name '*.json' \) -print0 \
      | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12 > /app/BUILD_ID \
    && cat /app/BUILD_ID

ENV HF_HUB_OFFLINE=1
USER app
EXPOSE 8000
