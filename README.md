# 🏷️ TagTeam

A universal annotation tool for images, PDFs, Word documents, texts, and spreadsheets designed for seamless team collaboration and structured taxonomies.

## 🚀 Quick Start

### Setup environment
```bash
cp env.example .env
```

**Important**: Generate a strong JWT_SECRET BEFORE starting containers:
```bash
# Generate random secret
sed -i '' "s/^#[[:space:]]*JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" .env
sed -i '' "s/^#[[:space:]]*ADMIN_PASSWORD=.*/ADMIN_PASSWORD=changeme123/" .env
```

### Start production locally
```bash
docker compose up
```

Then access:
- Frontend: http://localhost:3000
- Login: `admin` / `changeme123` (from `.env`)

## 🔧 Local Development

### Option A: Pure local (fastest - no Docker)

**Backend** (one terminal):
```bash
cd backend
uv sync
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

This uses [uv](https://docs.astral.sh/uv/) for dependency management. `uv sync`
creates a `.venv` and installs everything from `pyproject.toml` /
`uv.lock`. No need to manually create or activate a virtualenv — `uv run`
handles that for you.

**Frontend** (another terminal):
```bash
cd frontend
npm install
npm run dev
```

Then open:
- Frontend: http://localhost:5173
- Backend: http://localhost:8000

This provides instant hot reload for both frontend and backend code changes.

### Option B: Docker with hot reload

If you prefer containers with hot reload:
```bash
docker compose -f docker-compose.dev.yml up
```

This starts:
- Frontend dev server: http://localhost:5173 (hot reload enabled)
- Backend: http://localhost:8000 (uvicorn --reload, dependencies managed via uv)


## ✨ Core Features

- **Multi-Format Visual Workspace**: Streamlined annotation interface with instant preview support for Images, PDFs, Word documents, Plain Text, and Tabular data (CSV/TSV/XLSX).
- **Smart Hierarchical Taxonomies**: Support for both flat lists and multi-level hierarchies with fast autocompletion and automatic parent-ancestor tagging.
- **Collaborative Workflows**: Flexible task distribution among annotators, featuring a **Cross-Validation Mode** to assign identical data to multiple team members for quality control.
- **Conflict Resolution (Merge Mode)**: A dedicated admin review interface to easily track team progress, inspect annotator disagreements, and merge conflicting labels into a finalized output.

## ⚙️ Configuration & Setup

TagTeam is fully configured using environment variables. Before starting the containers, create your `.env` file from the template:

```bash
cp env.example .env
```

### Key Environment Variables (`.env`)

* `DATABASE_URL`: Connection string for the primary database (PostgreSQL recommended for production, SQLite for local dev).
* `REDIS_URL`: Optional cache layer. If unset, caching is disabled and the app reads/writes the database directly.
* `ADMIN_USERNAME`: Username of the initial bootstrap administrator account (Default: `admin`).
* `ADMIN_PASSWORD`: **Change this immediately** to secure your deployment. This password is bootstrapped into the persistent layer on the very first container initialization.
* `JWT_SECRET`: A long, random secret key utilized to sign secure JSON Web Tokens for user authentication.

### Supported File Types

Uploaded files are classified by inspecting their actual content (not just
the extension):

| Category   | Formats                                  | Preview                          |
|------------|-------------------------------------------|-----------------------------------|
| `image`    | PNG, JPEG, GIF, WEBP, BMP, TIFF, ...       | Inline image                      |
| `pdf`      | PDF                                        | Inline embedded viewer            |
| `document` | Word (`.docx`)                            | Download link (no inline preview) |
| `table`    | CSV, TSV, XLSX, XLS                        | Per-row annotation view           |
| `text`     | TXT, MD, JSON, YAML                        | Inline text view                  |

### Taxonomy Label Formats

When creating a project, you can import labels using either a flat or a hierarchical list:

#### 1. Flat Taxonomy (Plain Text `.txt`)

A simple line-by-line list for un-nested, standard labeling:

```text
bird
dog
cat
```

#### 2. Hierarchical Taxonomy (Delimited CSV/TSV)

A multi-level matrix where columns represent structural taxonomy depth. Selecting a deeper tier automatically maps higher-level ancestors:

```csv
Tier 1;Tier 2;Tier 3
Attractions;Amusement and Theme Parks;
Automotive;Auto Body Styles;Convertible
Automotive;Auto Body Styles;Coupe
```

## 🏗️ Building from Source
If you have made custom changes to the source code or need to build the production Docker images locally before deploying (e.g., if the remote images do not exist yet), you can explicitly force Docker Compose to build them.

```bash
# Force Docker to build backend and frontend production images from source code
docker compose build

# Start the newly built local stack
docker compose up
```