/**
 * src/index.js — Cloudflare Worker entry point for CAO 48.1 Compliance API.
 *
 * This Worker acts as a thin proxy, routing all incoming HTTP requests
 * to the FastAPI container running alongside it. The container runs
 * the CAO 48.1 Compliance API on port 8000.
 *
 * For a stateless API, we load-balance across container instances
 * using a simple random selection from a pool.
 *
 * Deploy:
 *   npx wrangler deploy
 *
 * Set secrets:
 *   npx wrangler secret put RAPIDAPI_PROXY_SECRET
 */

import { Container, getContainer } from "@cloudflare/containers";

/**
 * CAO481Container — Container class configuration.
 *
 * Extends the Cloudflare Container base class to configure:
 *   - defaultPort: The port FastAPI/uvicorn listens on (8000)
 *   - sleepAfter: Idle timeout before the container scales to zero
 *   - envVars: Environment variables passed into the container
 */
export class CAO481Container extends Container {
  // Port that uvicorn listens on inside the container
  defaultPort = 8000;

  // Scale to zero after 10 minutes of inactivity.
  // Keeps costs minimal for a low-traffic API.
  // Adjust upward if cold starts become an issue.
  sleepAfter = "10m";

  // Environment variables injected into the container.
  // RAPIDAPI_PROXY_SECRET should be set as a Wrangler secret
  // rather than hardcoded here.
  envVars = {
    ENVIRONMENT: "production",
    LOG_LEVEL: "info",
  };

  // ─── Lifecycle hooks ────────────────────────────────────────────────

  onStart() {
    console.log("CAO 48.1 API container started");
  }

  onStop() {
    console.log("CAO 48.1 API container stopped (idle timeout)");
  }

  onError(error) {
    console.error("CAO 48.1 API container error:", error);
  }
}

/**
 * Helper — pick a random container instance from a pool.
 *
 * For a stateless API, any instance can handle any request.
 * This distributes load across the pool evenly.
 *
 * @param {Object} binding - The Durable Object binding (env.CAO481_CONTAINER)
 * @param {number} poolSize - Number of container instances in the pool
 * @returns {Object} A container instance to route the request to
 */
function getRandomInstance(binding, poolSize) {
  const index = Math.floor(Math.random() * poolSize);
  const id = binding.idFromName(`cao481-instance-${index}`);
  return binding.get(id);
}

// ─── Number of stateless container instances in the pool ──────────────
// For low traffic, 2 instances provides basic redundancy.
// Increase for higher throughput.
const POOL_SIZE = 2;

/**
 * Worker fetch handler — routes all requests to the container.
 *
 * The Worker is the entry point for all HTTP requests. It forwards
 * them to one of the stateless FastAPI container instances.
 *
 * The OpenAPI spec, docs, and health endpoints are all served by
 * the container — the Worker just proxies.
 */
export default {
  async fetch(request, env) {
    const container = getRandomInstance(env.CAO481_CONTAINER, POOL_SIZE);
    return await container.fetch(request);
  },
};
