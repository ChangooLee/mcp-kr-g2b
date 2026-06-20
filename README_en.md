[한국어](README.md) | English

# MCP KR-G2B (Korea Public Procurement Service / 나라장터)

![License](https://img.shields.io/badge/license-CC%20BY--NC%204.0-red)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)

A Model Context Protocol (MCP) server for the **Korea Public Procurement Service (PPS / 조달청)** open APIs — the **나라장터 (G2B / KONEPS)** national e-procurement system and **누리장터** private-procurement services, delivered through the public data portal (data.go.kr). It exposes **14 services / 156 operations** so AI assistants can query bid notices, pre-standards, successful bids, contracts, order plans, price information, and procurement statistics in natural language.

## What you can ask

- "Find construction bid notices posted in January 2024"
- "Summarize recent goods award (낙찰) results for a given demand institution"
- "Show service contracts concluded last month"
- "Look up facility material (civil engineering) price information"
- "Give me public procurement statistics by institution type"

## Services

Each service is called via a single `get_<module>_data` tool; the `operation` argument selects the specific operation.

| Group | Service | Tool | Ops |
|-------|---------|------|:---:|
| 나라장터 | Bid notices | `get_bid_data` | 25 |
| | Pre-standards | `get_prestd_data` | 20 |
| | Successful bids (낙찰) | `get_scsbid_data` | 23 |
| | Contracts | `get_contract_data` | 21 |
| | Integrated contract-process disclosure | `get_contract_process_data` | 4 |
| | Order plans | `get_order_plan_data` | 8 |
| | Price information | `get_price_data` | 11 |
| | Open-data standard | `get_data_standard_data` | 3 |
| | Industry & legal basis | `get_industry_data` | 1 |
| | User information | `get_user_info_data` | 5 |
| 공공조달 | Procurement statistics | `get_stats_data` | 14 |
| 누리장터 | Private bid notices | `get_nuri_bid_data` | 10 |
| | Private successful bids | `get_nuri_scsbid_data` | 7 |
| | Private contracts | `get_nuri_contract_data` | 4 |

Discovery/cache helpers: `list_g2b_services`, `get_g2b_operation_info`, `get_g2b_cache_data`.

## Recommended flow

```
1. list_g2b_services()                       → see services & operations
2. get_g2b_operation_info(module, operation) → exact request params (required/optional)
3. get_<module>_data(operation, params={…})  → paginated fetch + cache + summary
4. get_g2b_cache_data(cache_file, …)         → drill into the cached full result
```

Large results return a **summary + 5-row preview + cache file path** to protect LLM context; the full data is stored in the cache file.

## Quick start

```bash
git clone https://github.com/ChangooLee/mcp-kr-g2b.git
cd mcp-kr-g2b
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install --upgrade pip
pip install -e .
cp .env.example .env   # set PUBLIC_DATA_API_KEY_ENCODED (Encoding key from data.go.kr)
```

### Claude Desktop

```json
{
  "mcpServers": {
    "mcp-kr-g2b": {
      "command": "YOUR_LOCATION/.venv/bin/mcp-kr-g2b",
      "env": {
        "PUBLIC_DATA_API_KEY_ENCODED": "your-encoded-service-key",
        "TRANSPORT": "stdio",
        "LOG_LEVEL": "INFO",
        "MCP_SERVER_NAME": "mcp-kr-g2b"
      }
    }
  }
}
```

## Authentication notes

- Get the key from [data.go.kr](https://www.data.go.kr); each service requires **usage approval** (otherwise error `20` is returned).
- Use the **Encoding** (URL-encoded) key as-is; the client appends it without re-encoding.

## Architecture

Combines `mcp-opendart`'s modular structure (per-service modules, global context, registry, ctx helpers) with `mcp-kr-realestate`'s data.go.kr calling/caching strategy (curl-first + requests fallback, pagination, raw→cache files). See [README.md](README.md) for the full diagram.

## License

CC BY-NC 4.0 — non-commercial use only. Not an official PPS product. See [LICENSE](LICENSE).
