# Dockge on TrueNAS SCALE

This stack is separate from the existing TrueNAS Spoolman catalog app.

## Deployment

Option 1: clone the repository into Dockge's stack directory, create a private `.env` from `.env.example`, and deploy `compose.yaml` with Build enabled.

Option 2: paste a Compose stack with a Git URL as `build.context`, pointing to a reviewed branch or, preferably, its final commit. Docker Compose/BuildKit must support remote Git build contexts.

Configure `SPOOLMAN_URL` for the existing Spoolman API, `MCP_PROXY_API_KEY` as a fresh 64-character random hex secret, `MCP_BIND_IP` (default `127.0.0.1`), and `MCP_PORT` (default `18788`). Keep real values outside version control.

The endpoints are `http://127.0.0.1:18788/mcp` and `http://127.0.0.1:18788/ping`. Test them from the TrueNAS host:

```bash
curl -i http://127.0.0.1:18788/ping
curl -i -X POST http://127.0.0.1:18788/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"check","version":"1"}}}'
```

Expected: health 200; unauthorized MCP 401/403. Access the MCP transport as a programmable client only by supplying the `X-API-Key` header, plus resource-scoped Pangolin access-token headers when going through Pangolin.

For a host-network Newt on the same NAS, set the Pangolin HTTP target to `127.0.0.1:18788` and leave all paths intact. When Newt runs elsewhere, localhost points to THAT machine, so bind to a private IP only after restricting inbound port access and reviewing encryption for that hop. Do not make the bind public.

Read [the authentication caveat](SECURITY.md) before attempting to connect ChatGPT.
