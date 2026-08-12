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

  /**
   * Wire environment variables into the container at construction time.
   *
   * `envVars` is set here (rather than as a static class field) so we can
   * pull RAPIDAPI_PROXY_SECRET off the Durable Object's bindings — it is a
   * Wrangler secret bound to the Worker/DO, set via:
   *   npx wrangler secret put RAPIDAPI_PROXY_SECRET
   *
   * Passing it through is REQUIRED in production: the FastAPI middleware
   * fails closed (HTTP 500) when ENVIRONMENT=production but no secret is
   * present, so the flag and the secret must travel together.
   *
   * @param {DurableObjectState} ctx - Durable Object execution context.
   * @param {Object} env - Worker/DO bindings, including the secret.
   */
  constructor(ctx, env) {
    super(ctx, env);

    this.envVars = {
      // Production mode activates the RapidAPI proxy-secret check in the
      // FastAPI middleware. In "development" that check is skipped entirely,
      // which would leave the origin open.
      ENVIRONMENT: "production",
      LOG_LEVEL: "info",
      // The shared secret RapidAPI stamps on every request as the
      // X-RapidAPI-Proxy-Secret header. Empty string if unset — which makes
      // the middleware refuse all traffic rather than admit everyone.
      RAPIDAPI_PROXY_SECRET: env.RAPIDAPI_PROXY_SECRET ?? "",
    };
  }

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
  // Bump this version suffix (v7 → v8 → …) whenever the container's env vars
  // change. Container env is only read on a COLD start, so reusing the same
  // instance name keeps a warm container running its old env after a deploy.
  // A new name forces brand-new instances that pick up the current envVars.
  const id = binding.idFromName(`cao481-v10-${index}`);
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
    // Allow OpenAPI spec and docs through without auth
    const url = new URL(request.url);
    const publicPaths = ["/openapi.json", "/docs", "/redoc", "/api/v1/cao481/health"];
    const isPublic = publicPaths.some(p => url.pathname === p);

    // Validate RapidAPI proxy secret (skip for public paths)
    // if (!isPublic) {
    //   const proxySecret = request.headers.get("X-RapidAPI-Proxy-Secret");
    //   if (env.RAPIDAPI_PROXY_SECRET && proxySecret !== env.RAPIDAPI_PROXY_SECRET) {
    //     return new Response(
    //       JSON.stringify({
    //         error: "forbidden",
    //         message: "Invalid or missing RapidAPI proxy secret.",
    //       }),
    //       { status: 403, headers: { "Content-Type": "application/json" } }
    //     );
    //   }
    // }

    const container = getRandomInstance(env.CAO481_CONTAINER, POOL_SIZE);
    return await container.fetch(request);
  },
};
