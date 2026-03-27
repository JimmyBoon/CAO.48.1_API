# Cloudflare Containers Deployment Guide

## Files to Add to Your Project

Place these files in your project root alongside the existing files:

```
cao481-api/
├── src/
│   └── index.js          ← NEW: Cloudflare Worker entry point
├── wrangler.jsonc         ← NEW: Cloudflare config
├── package.json           ← NEW: Worker dependencies
├── Dockerfile             ← EXISTING (may need platform tweak)
├── app/                   ← EXISTING: FastAPI application
│   ├── main.py
│   ├── config.py
│   ├── middleware.py
│   └── models/
├── docker-compose.yml     ← EXISTING: local dev only
├── requirements.txt       ← EXISTING
└── ...
```

## M1 Mac: Dockerfile Platform Fix

Cloudflare Containers require `linux/amd64` images. Since you're building
on an Apple M1, update the first line of your Dockerfile:

```dockerfile
# Change this:
FROM python:3.12-slim AS base

# To this:
FROM --platform=linux/amd64 python:3.12-slim AS base
```

This ensures the image is built for the correct architecture even though
your local machine is ARM-based.

## Deployment Steps

### 1. Install Wrangler and dependencies

```bash
npm install
```

### 2. Authenticate with Cloudflare

```bash
npx wrangler login
```

### 3. Set the RapidAPI proxy secret

```bash
npx wrangler secret put RAPIDAPI_PROXY_SECRET
# Paste your secret when prompted
```

### 4. Deploy

```bash
npx wrangler deploy
```

On first deploy, this will:
- Build the Docker image (linux/amd64)
- Push it to Cloudflare's container registry
- Deploy the Worker
- Provision container instances

**First deploy takes a few minutes.** Subsequent deploys are faster
due to cached image layers.

### 5. Check status

```bash
npx wrangler containers list
```

### 6. Test

Your API will be available at:
```
https://cao481-api.<YOUR_SUBDOMAIN>.workers.dev/api/v1/cao481/health
```

### 7. Register on RapidAPI

1. Go to rapidapi.com/studio → Add API Project
2. Set the Base URL to your Workers URL:
   `https://cao481-api.<YOUR_SUBDOMAIN>.workers.dev`
3. Import OpenAPI spec from:
   `https://cao481-api.<YOUR_SUBDOMAIN>.workers.dev/openapi.json`
4. Copy the X-RapidAPI-Proxy-Secret from the RapidAPI Security tab
5. Update the Wrangler secret:
   `npx wrangler secret put RAPIDAPI_PROXY_SECRET`

## Configuration Notes

### Scale to Zero
The container sleeps after 10 minutes of inactivity (`sleepAfter: "10m"`
in src/index.js). First request after sleep takes a few seconds for
cold start. Adjust this value if needed.

### Pool Size
The Worker load-balances across 2 container instances by default
(`POOL_SIZE = 2` in src/index.js). For a low-traffic API this provides
basic redundancy. Increase for higher throughput.

### Max Instances
`max_instances: 3` in wrangler.jsonc caps the maximum simultaneous
containers. This keeps costs predictable during beta.

### Secrets vs Vars
- `vars` in wrangler.jsonc are for non-sensitive values (visible in config)
- `secrets` are for sensitive values like RAPIDAPI_PROXY_SECRET
  (set via `wrangler secret put`)

### Local Development
Cloudflare Containers support local dev:
```bash
npx wrangler dev
# Press "R" to rebuild the container
```

But for day-to-day development, `docker compose up` is probably easier
since it doesn't require the Worker proxy layer.

## Costs

Cloudflare Containers are billed per 10ms of active runtime and scale
to zero when idle. For a low-traffic stateless API, costs should be
minimal — potentially under $1/month depending on usage.
