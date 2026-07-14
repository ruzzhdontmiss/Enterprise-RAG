# Deploy Walkthrough — EnterpriseRAG on Render

This guide walks you through deploying the multi-tenant EnterpriseRAG stack to Render using Qdrant Cloud.

---

## 1. Setup Managed Qdrant Cloud (Free Tier)
We use Qdrant Cloud's free managed tier instead of hosting a custom vector database instance.
1. Sign up or log in at the [Qdrant Cloud Console](https://cloud.qdrant.io/).
2. Create a free cluster (select your preferred cloud provider and region).
3. Once the cluster is active, copy the **Cluster URL** (e.g. `https://xxx.gcp.qdrant.io:6333`).
4. Generate an **API Key** under the "Credentials" tab and copy it.

You will need these values for the environment variables:
- `QDRANT_URL`: The Cluster URL
- `QDRANT_API_KEY`: The generated API Key

---

## 2. Deploy to Render via Blueprint
Render Blueprints automate the deployment of multi-service stacks using the `render.yaml` configuration.

1. Commit your codebase changes and push them to your GitHub repository.
2. Log in to your [Render Dashboard](https://dashboard.render.com/).
3. Click **New** -> **Blueprint**.
4. Select your pushed repository.
5. Render will detect the `render.yaml` blueprint. Specify a group name for the blueprint configuration.
6. Provide values for the required environment variables in the Render console:
   - `MISTRAL_API_KEY`: Your Mistral developer API key.
   - `QDRANT_URL`: The Qdrant Cloud endpoint URL.
   - `QDRANT_API_KEY`: The Qdrant Cloud API key.
7. Click **Apply**. Render will launch:
   - A free-tier Postgres database.
   - The FastAPI backend service.
   - The Next.js frontend web service.

---

## 3. Database Migrations
Render automatically executes migrations on service startup. In `render.yaml`, the backend service `startCommand` is:
```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT
```
This ensures the schema tables (`tenants`, `users`, `documents`, `chat_messages`, `query_traces`) are fully initialized or updated before backend requests are accepted.

---

## 4. Render Postgres Expiration & Upgrade

> [!WARNING]
> Render's **Free Tier** PostgreSQL databases expire and are automatically deleted **30 days after creation**.

To prevent data loss, you must upgrade the database plan to a paid tier. The **Starter** tier ($7/month) is the recommended path for production or long-term portfolio demos.

### Upgrade Steps:
1. Open the [Render Dashboard](https://dashboard.render.com/).
2. Select your PostgreSQL database service (e.g. `enterprise-rag-db`).
3. Click the **Settings** tab on the left sidebar.
4. Scroll down to the **Database Instance Type** section.
5. Click **Edit** or **Change Plan**.
6. Select the **Starter** instance type ($7/month, 1 GB RAM, 1 shared CPU).
7. Confirm the upgrade. Render will perform a rolling restart of the database with zero data loss or migrations required.
