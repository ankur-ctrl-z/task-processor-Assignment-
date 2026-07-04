# AI Task Processing Platform

MERN stack app + async Python worker for text-processing tasks
(uppercase / lowercase / reverse / word count), containerized, deployed to
Kubernetes via Argo CD, built/pushed by GitHub Actions.

## Repo layout

```
backend/     Express API (auth, tasks) — Node 20
worker/      Python consumer that processes queued tasks
frontend/    React (Vite) SPA
k8s/         Raw Kubernetes manifests (quick "kubectl apply -f k8s/" path)
infra-repo/  What actually goes in the SEPARATE infra repo Argo CD watches
             (k8s-kustomize/base + overlays/staging + overlays/production)
argocd/      Argo CD Application manifests (staging + production)
.github/     CI/CD pipeline (lint → build → push → bump infra repo)
docs/        Architecture document
```

**Note on repo structure:** this assignment requires two separate git
repositories — an application repo and an infrastructure repo. Everything
above except `infra-repo/` and `argocd/` belongs in the **application repo**.
`infra-repo/` is what you push as the *contents* of a second, separate repo
(e.g. `ai-task-platform-infra`) — that's the repo Argo CD is actually
configured to watch.

## 1. Run it locally (fastest path)

Prerequisites: Docker + Docker Compose.

```bash
git clone <your-app-repo-url>
cd ai-task-platform
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:5000/api
- MongoDB: localhost:27017
- Redis: localhost:6379

Register a user, create a task, click "Run Task," watch status flip
PENDING → RUNNING → SUCCESS within a few seconds (dashboard polls every 3s).

To run without Docker (e.g. for active development):

```bash
# Backend
cd backend && cp .env.example .env && npm install && npm run dev

# Worker (needs MONGO_URI / REDIS_URL env vars set, see .env.example)
cd worker && pip install -r requirements.txt && python worker.py

# Frontend
cd frontend && npm install && npm run dev
```

## 2. Build and push images manually

```bash
docker build -t YOUR_DOCKERHUB_USERNAME/ai-task-backend:latest ./backend
docker build -t YOUR_DOCKERHUB_USERNAME/ai-task-worker:latest ./worker
docker build -t YOUR_DOCKERHUB_USERNAME/ai-task-frontend:latest ./frontend

docker push YOUR_DOCKERHUB_USERNAME/ai-task-backend:latest
docker push YOUR_DOCKERHUB_USERNAME/ai-task-worker:latest
docker push YOUR_DOCKERHUB_USERNAME/ai-task-frontend:latest
```

Replace `YOUR_DOCKERHUB_USERNAME` everywhere it appears in `k8s/*.yaml` and
`infra-repo/k8s-kustomize/**` before deploying.

## 3. Deploy to Kubernetes — two paths

### Path A: quick manual deploy (no GitOps, for sanity-checking manifests)

```bash
kubectl apply -f k8s/
kubectl -n ai-task-platform get pods -w
```

### Path B: the actual GitOps path this assignment wants

1. Create a **second, separate** GitHub repo, e.g. `ai-task-platform-infra`.
2. Push the contents of this repo's `infra-repo/` folder to it (so the infra
   repo's root contains `k8s-kustomize/`).
3. Install k3s (if you don't have a cluster):
   ```bash
   curl -sfL https://get.k3s.io | sh -
   ```
4. Install Argo CD:
   ```bash
   kubectl create namespace argocd
   kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
   ```
5. Get the initial admin password and open the UI:
   ```bash
   kubectl -n argocd get secret argocd-initial-admin-secret \
     -o jsonpath="{.data.password}" | base64 -d
   kubectl -n argocd port-forward svc/argocd-server 8080:443
   # open https://localhost:8080, log in as admin
   ```
6. Edit `repoURL` in `argocd/application-staging.yaml` and
   `argocd/application-production.yaml` to point at your infra repo, then:
   ```bash
   kubectl apply -f argocd/application-staging.yaml
   kubectl apply -f argocd/application-production.yaml
   ```
7. Argo CD will auto-sync (it's configured with `automated: {prune: true,
   selfHeal: true}`) — no manual `kubectl apply` needed after this. Take your
   dashboard screenshot from the Argo CD UI here (this is the required
   submission screenshot).

## 4. CI/CD (GitHub Actions)

`.github/workflows/ci-cd.yaml` runs on every push to `main`:
1. Lints backend, frontend, worker.
2. Builds and pushes all three Docker images to Docker Hub (tagged `latest`
   and short-SHA).
3. Checks out the **infra repo**, bumps the staging overlay's image tags via
   `kustomize edit set image`, commits, and pushes — which Argo CD then
   picks up automatically.

Required GitHub Actions secrets (set in the **application repo**):

| Secret | Purpose |
|---|---|
| `DOCKERHUB_USERNAME` | Docker Hub username |
| `DOCKERHUB_TOKEN` | Docker Hub access token (not your password) |
| `INFRA_REPO_PAT` | GitHub PAT with `repo` scope, allowed to push to the infra repo |

Also replace `YOUR_GH_USERNAME` in the workflow file with your actual infra
repo owner/name.

## 5. Environment variables

See `backend/.env.example`. Never commit a real `.env` file — it's already
gitignored.

## 6. Security notes / assumptions made

- `k8s/02-secrets.yaml` ships with placeholder base64 values and is meant to
  be regenerated before any real deployment — see the comment at the top of
  that file. It should never contain production values in git; use Sealed
  Secrets or an External Secrets Operator for real deployments (see
  `docs/architecture.md`).
- MongoDB and Redis here run as single-replica in-cluster Deployments for
  assignment scope. Production should use managed services (MongoDB Atlas /
  a Mongo replica set, managed Redis with Sentinel) — called out explicitly
  in `docs/architecture.md`.
- The worker HPA scales on CPU, which I explain in the architecture doc is
  the wrong signal for a queue consumer — the correct fix (KEDA + Redis
  queue-depth scaling) is documented but not implemented, since it requires
  installing KEDA as an additional cluster component beyond assignment scope.
- Domain names (`ai-tasks.example.com`) and `YOUR_DOCKERHUB_USERNAME` /
  `YOUR_GH_USERNAME` placeholders throughout the manifests need to be
  replaced with real values before anything will actually deploy.

## 7. What's NOT included, on purpose

I'm not going to pretend this is deployed somewhere — it isn't, because that
requires your Docker Hub account, your GitHub repos, and either your own k3s
box or a cloud VM, none of which I have access to. Everything above is
written to be copy-paste-runnable once you plug in those three things. Budget
realistically: ~30–60 minutes if you already have a cloud VM or local
machine that can run k3s, longer if you're provisioning infrastructure from
scratch.
