import { spawn } from 'child_process';
import express from 'express';
import cors from 'cors';
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";

const argvPort = process.argv[2];
const isPortArg = !!(argvPort && /^[0-9]+$/.test(argvPort));
const PORT = isPortArg ? Number(argvPort) : Number(process.env.PORT || 7860);
const COMMAND = isPortArg ? (process.argv[3] || 'python') : (argvPort || 'python');
const ARGS = isPortArg ? process.argv.slice(4) : process.argv.slice(3);
const HOST = process.env.PROXY_HOST || '0.0.0.0';

if (!ARGS.length && COMMAND === 'python') {
    ARGS.push('jarvis.py');
}

console.error(`🚀 [Proxy] Starting SDK-based Proxy on port ${PORT} for: ${COMMAND} ${ARGS.join(" ")}`);

const app = express();
app.use(cors());
app.use(express.json());

// ABRIR A PORTA IMEDIATAMENTE
app.listen(PORT, HOST, () => {
  console.error(`✅ [Proxy] HTTP Server listening on ${HOST}:${PORT} (READY FOR POLLING)`);
});

// Initialize Stdio Client
console.error("[Proxy] Initializing StdioClientTransport...");
let clientTransport;
try {
    clientTransport = new StdioClientTransport({
      command: COMMAND,
      args: ARGS,
      env: { ...process.env, MCP_MODE: 'stdio' }
    });
    console.error("[Proxy] Transport initialized.");
} catch (e) {
    console.error(`❌ [Proxy] Failed to initialize transport: ${e.message}`);
    process.exit(1);
}

const client = new Client(
  { name: "jarvis-proxy-client", version: "1.0.0" },
  { capabilities: {} }
);

// Initialize SSE Server
const server = new McpServer({
  name: "Jarvis Super Server (Proxy)",
  version: "6.0.0",
}, {
  capabilities: {
    tools: {},
    // Desativando resources e prompts para evitar erros de validação no Mistral
    // resources: {},
    // prompts: {}
  }
});

let isConnected = false;

async function connectToBackend() {
    console.error("[Proxy] Connecting to Stdio backend...");
    try {
        await client.connect(clientTransport, { timeout: 60000 });
        console.error("[Proxy] Connected to backend successfully.");

        const tools = await client.listTools();
        console.error(`[Proxy] Forwarding ${tools.tools.length} tools...`);

        for (const tool of tools.tools) {
            server.tool(tool.name, tool.inputSchema, async (args) => {
                console.error(`[Proxy] Executing tool ${tool.name}`);
                return await client.callTool({
                    name: tool.name,
                    arguments: args
                });
            });
        }
        isConnected = true;
        console.error("✅ [Proxy] Backend tools mapped and ready.");
    } catch (e) {
        console.error(`❌ [Proxy] Connection failed: ${e.message}`);
        // Tenta reconectar após 5 segundos
        setTimeout(connectToBackend, 5000);
    }
}

connectToBackend();

// Custom Transport for Stateless HTTP
class StatelessHttpTransport {
  constructor(res) {
    this.res = res;
    this.onmessage = undefined;
    this.onclose = undefined;
    this.onerror = undefined;
    this.sent = false;
  }
  async start() {}
  async send(message) {
    if (this.sent || this.res.headersSent) return;
    if (message.id !== undefined || message.error) {
        this.sent = true;
        this.res.setHeader("Content-Type", "application/json");
        this.res.json(message);
    }
  }
  async close() { if (this.onclose) this.onclose(); }
  async handlePostMessage(message) { if (this.onmessage) await this.onmessage(message); }
}

function normalizeInitializeParams(message) {
  if (!message || typeof message !== "object") return message;
  if (message.method !== "initialize") return message;
  const params = message.params && typeof message.params === "object" ? message.params : {};
  if (typeof params.protocolVersion !== "string") {
    params.protocolVersion = "2024-11-05";
  }
  if (!params.capabilities || typeof params.capabilities !== "object") {
    params.capabilities = {};
  }
  if (!params.clientInfo || typeof params.clientInfo !== "object") {
    params.clientInfo = { name: "mistral-connector", version: "0.0.0" };
  }
  message.params = params;
  return message;
}

function normalizeMessagePayload(payload) {
  if (Array.isArray(payload)) {
    return payload.map(normalizeInitializeParams);
  }
  return normalizeInitializeParams(payload);
}

// SSE Endpoints
let transports = new Map();

app.get("/mcp", async (req, res) => {
  console.error("[Proxy] New SSE connection on /mcp");

  const transport = new SSEServerTransport("/mcp", res);
  transports.set(transport.sessionId, transport);
  res.on("close", () => transports.delete(transport.sessionId));

  // Conecta ao backend de forma assíncrona (sem bloquear a resposta inicial)
  server.connect(transport).catch(e => console.error(`[Proxy] Connection error: ${e}`));
});

app.post("/mcp", async (req, res) => {
  if (!isConnected) {
      return res.status(503).json({ error: "Initializing", message: "Backend tools still loading..." });
  }
  if (req.body) {
      req.body = normalizeMessagePayload(req.body);
  }
  const sessionId = req.query.sessionId;
  const transport = sessionId ? transports.get(sessionId) : null;
  if (transport && sessionId) {
      await transport.handlePostMessage(req, res);
  } else {
    const statelessTransport = new StatelessHttpTransport(res);
    await server.connect(statelessTransport);
    await statelessTransport.handlePostMessage(normalizeMessagePayload(req.body));
  }
});

app.get("/sse", async (req, res) => {
    const transport = new SSEServerTransport("/messages", res);
    transports.set('messages-legacy', transport);
    await server.connect(transport);
});
app.post("/messages", async (req, res) => {
    const transport = transports.get('messages-legacy');
    if (transport) await transport.handlePostMessage(req, res);
    else res.status(400).send("No session");
});

app.get("/debug/tools", async (req, res) => {
    if (!isConnected) return res.json({ status: "connecting" });
    const tools = await client.listTools();
    res.json({ status: "connected", tools: tools.tools.map(t => t.name) });
});

app.get("/", (req, res) => {
    res.json({ status: isConnected ? "online" : "connecting", proxy: "Jarvis SDK Proxy v6" });
});
