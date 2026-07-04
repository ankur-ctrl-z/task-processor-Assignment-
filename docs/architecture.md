# Architecture Document — AI Task Processing Platform

## 1. Overall System Architecture 

The platform is a MERN application with an async Python worker tier, split into
five deployable units: **frontend** (React SPA served by Nginx), **backend**
(Node/Express REST API), **worker** (Python, horizontally scalable), **MongoDB**,
and **Redis**.

Request flow:

1. The React SPA calls the Express API over HTTPS (`/api/*`), authenticating
   with a JWT stored client-side after login/register.
2. The backend validates the JWT, writes task documents to MongoDB, and — on
   "Run Task" — pushes the task's Mongo `_id` onto a Redis list (`LPUSH`).
   The backend never executes task logic itself; it only ever produces onto
   the queue.
3. One or more Python worker replicas block on `BRPOP` against the same list.
   Redis guarantees each queued id is delivered to exactly one consumer, so
   scaling workers horizontally requires zero coordination logic.
4. A worker reads the full task document from MongoDB, flips status to
   `RUNNING`, executes the requested string operation in-process (all four
   supported operations are O(n) and CPU-only — no external calls), and
   writes `SUCCESS`/`FAILED` plus the result and logs back to MongoDB.
5. The frontend polls `GET /api/tasks` every 3s to reflect status changes.
   A production iteration would replace polling with Server-Sent Events or a
   WebSocket channel to cut API load, but polling is deliberately simple and
   correct for the assignment's scope.

The backend and worker are stateless with respect to each other — MongoDB is
the single source of truth for task state, and Redis is purely a transient
work queue, not a data store. This means either tier can crash and restart
without losing task history (Redis persistence is a durability *backstop*,
covered in section 5, not the system of record).

Traffic reaches the cluster through a single Ingress (`ai-tasks.example.com`)
that routes `/api/*` to the backend Service and everything else to the
frontend Service, terminating TLS via cert-manager + Let's Encrypt.

## 2. Worker Scaling Strategy

The included manifest (`k8s/06-worker.yaml`) scales workers on CPU
utilization via a standard HorizontalPodAutoscaler (2–20 replicas, 70%
target). This is a reasonable default but it is the **wrong signal** for a
queue consumer: CPU usage tells you how hard workers are working, not how
much work is *waiting*. A worker pool can sit at 70% CPU with 50,000 tasks
queued or with zero — CPU doesn't distinguish those cases.

The correct production approach is **queue-depth-based scaling**, using
[KEDA](https://keda.sh) with its Redis list scaler:

```yaml
triggers:
  - type: redis
    metadata:
      address: redis:6379
      listName: ai_task_queue
      listLength: "20"   # target ~20 pending items per replica
```

This scales workers directly against `LLEN ai_task_queue`, which is the
actual backlog. Combined with `minReplicaCount: 2` (always-warm baseline) and
`maxReplicaCount` capped to protect MongoDB connection limits, this responds
to load spikes in seconds rather than waiting for CPU to climb.

Each operation (uppercase, lowercase, reverse, word count) is O(n) on input
length with no I/O beyond two Mongo writes, so workers are cheap: sub-100ms
per task in the common case, meaning a handful of replicas can clear large
backlogs quickly once queue-depth scaling is in place.

## 3. Handling High Task Volume (~100,000 tasks/day)

100k tasks/day averages to ~1.16 tasks/second, which is trivial — the real
engineering problem is **peak-to-average ratio**, not raw daily volume. If
80% of tasks arrive in a 4-hour window, peak throughput is closer to 5-6
tasks/second, and if a single customer script fires 10,000 tasks in a burst,
it's higher still.

Mitigations, in priority order:

- **Decoupling via Redis already solves the core problem.** The API accepts
  a task and returns immediately; it never blocks waiting for processing.
  Bursts queue up in Redis rather than causing HTTP timeouts.
- **Queue-depth autoscaling** (section 2) absorbs bursts by adding worker
  replicas proportional to backlog, not proportional to guesswork.
- **Rate limiting per user** (already implemented via `express-rate-limit`)
  prevents a single misbehaving client from monopolizing the queue at the
  expense of other users.
- **MongoDB write capacity**: at this volume, two writes per task (status
  transitions) is ~200k writes/day — well within a single replica set's
  capacity, but connection pool size on the backend/worker (`maxPoolSize`)
  should be tuned rather than left at driver defaults once replica counts
  climb into double digits, to avoid exhausting Mongo's `maxConns`.
- **Redis memory**: list entries are just ObjectId strings (~24 bytes), so
  even a 100k-deep backlog is a few MB — memory is not a constraint at this
  scale. The constraint is worker throughput, which queue-depth scaling
  addresses directly.

## 4. MongoDB Indexing Strategy

Two collections, two access patterns:

**`users`**: a unique index on `email` (already declared in the Mongoose
schema) supports both the uniqueness constraint at registration and the
login lookup — the single most frequent read against this collection.

**`tasks`**: the dashboard's dominant query is "this user's tasks, newest
first, optionally filtered by status." The schema declares:

```js
taskSchema.index({ user: 1, createdAt: -1 });          // task list view
taskSchema.index({ user: 1, status: 1, createdAt: -1 }); // filtered list view
taskSchema.index({ status: 1, createdAt: 1 });          // ops/reconciliation queries
```

The compound `{user, createdAt}` index covers the unfiltered list (the
common case) without a separate sort step. The `{user, status, createdAt}`
index covers the filtered case. The third index supports an operational
fallback: if a task is ever stuck in `PENDING` because a Redis push failed
after the Mongo write succeeded, a periodic reconciliation job can scan
`status=PENDING` tasks older than N minutes and re-queue them — this index
makes that scan cheap instead of a full collection scan. At 100k tasks/day,
after 30 days that's ~3M documents; without these indexes, list queries
degrade from index scans to collection scans well before that point.

## 5. Redis Failure Handling and Recovery Strategy

Redis is a **queue, not a database**, but losing queued task IDs still means
a user's task silently never runs — so failure handling matters even without
Redis being a system of record.

- **Persistence**: the deployment runs Redis with `--appendonly yes` (AOF),
  so a pod restart replays the log instead of losing an in-flight queue.
  This is already configured in `docker-compose.yml` and `k8s/04-redis.yaml`.
- **Worker-side resilience**: `worker.py` retries the initial Redis
  connection with exponential backoff (`connect_redis()`), and if `BRPOP`
  fails mid-run (connection drop), it logs, sleeps 3s, and retries the loop
  rather than crashing the pod — see the `except redis.exceptions.RedisError`
  block in the main loop.
- **The real gap**: if the backend's `LPUSH` fails after a task's Mongo
  document was already created with `status=PENDING`, that task is stuck —
  it exists in Mongo but was never queued. This is the standard
  "dual-write" problem (write to DB, then to queue, with no atomicity
  between the two). The fix is a reconciliation job (a Kubernetes CronJob)
  that periodically finds `PENDING` tasks older than a threshold and
  re-pushes them to Redis. This is simpler and more robust than trying to
  make the two writes transactional.
- **At scale**, a single Redis pod is a single point of failure. Production
  should run Redis Sentinel (managed HA) or a managed Redis service (e.g.
  AWS ElastiCache, Upstash) instead of the bare single-replica Deployment
  used here for assignment scope — a self-managed single pod is fine for a
  take-home, not for a system with an SLA.

## 6. Deployment Strategy

**Staging** (`k8s-kustomize/overlays/staging`): single replica per component,
own namespace (`ai-task-platform-staging`), separate ingress host
(`staging.ai-tasks.example.com`), lower resource requests. Every merge to
`main` deploys here automatically via CI/CD + Argo CD auto-sync — staging is
meant to be disposable and always reflect the tip of `main`.

**Production** (`k8s-kustomize/overlays/production`): higher replica counts
(3 backend / 5 worker / 3 frontend), pinned semantic-version image tags
(`v1.0.0`, not `latest`) so a rollback is a one-line git revert rather than a
guess about which `latest` was actually running, and the primary ingress
host. Promotion to production is a deliberate, separate action — bumping the
image tag in `overlays/production/kustomization.yaml` via a reviewed PR —
rather than automatic on every commit, so a bad merge to `main` only ever
breaks staging.

Both environments are driven by the same Kustomize base
(`k8s-kustomize/base`), so staging and production only differ in the small,
explicit set of patches each overlay applies — replica counts, image tags,
and ingress hosts. This is the actual point of Kustomize here: it eliminates
drift between environments that inevitably creeps in when staging and
production manifests are maintained as separate, hand-edited copies.

Argo CD watches the infra repo with `automated: {prune: true, selfHeal:
true}`, meaning: (a) resources removed from git are removed from the
cluster, and (b) any manual `kubectl edit` against the live cluster gets
reverted back to match git on the next sync. Git is the only accepted source
of truth for cluster state — this is the actual definition of GitOps, not
just "we use Argo CD."
