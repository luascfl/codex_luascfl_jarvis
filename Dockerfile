FROM python:3.11-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Instala dependências de sistema e Node.js 20 (LTS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ffmpeg \
    ca-certificates \
    procps \
    gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list \
    && apt-get update && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Instala Go 1.23+ manualmente (Debian padrão é muito antigo para o SDK do Speedgrapher)
RUN curl -fsSL https://golang.org/dl/go1.23.4.linux-amd64.tar.gz | tar -C /usr/local -xz
ENV PATH=$PATH:/usr/local/go/bin

WORKDIR /app
RUN chown -R 1000:1000 /app

# Compila Speedgrapher do repositório oficial (GCP Devrel Demos)
RUN git clone --depth 1 https://codehost.com/GoogleCloudPlatform/devrel-demos.git /tmp/devrel-demos \
    && cd /tmp/devrel-demos/ai-ml/mcp-servers/speedgrapher \
    && go build -o /usr/local/bin/speedgrapher ./cmd/speedgrapher \
    && rm -rf /tmp/devrel-demos

# Instalação Python (mcp-proxy + dependências do Jarvis)
COPY requirements.txt .
RUN pip install --no-cache-dir mcp-proxy fastmcp uvicorn[standard] starlette httpx requests python-multipart aiofiles
RUN pip install --no-cache-dir -r requirements.txt

# Instala dependências Node.js (Proxy Stdio -> SSE)
COPY package.json .
RUN npm install

COPY --chown=1000:1000 . .

USER 1000
EXPOSE 7860

# Inicia o Jarvis diretamente (Configurado para HTTP Streamable em /mcp)
CMD ["python", "jarvis.py"]
