# 🏷️ TagTeam

A universal annotation tool for images, PDFs, texts, and spreadsheets designed for seamless team collaboration and structured taxonomies.

## 🚀 Quick Start

1. **Setup Environment**:
```bash
   cp env.example .env
```

Open `.env` to configure your settings. Change the default admin password (`ADMIN_PASSWORD`) used for automatic admin account bootstrapping on first startup.

2. **Launch with Docker**:
```bash
docker compose up
```


3. **Access the App**:  
Open your browser and navigate to http://localhost:3000


## ✨ Core Features

- **Multi-Format Visual Workspace**: Streamlined annotation interface with instant preview support for Images, PDFs, Plain Text, and Tabular data (CSV/XLSX).
- **Smart Hierarchical Taxonomies**: Support for both flat lists and multi-level hierarchies with fast autocompletion and automatic parent-ancestor tagging.
- **Collaborative Workflows**: Flexible task distribution among annotators, featuring a **Cross-Validation Mode** to assign identical data to multiple team members for quality control.
- **Conflict Resolution (Merge Mode)**: A dedicated admin review interface to easily track team progress, inspect annotator disagreements, and merge conflicting labels into a finalized output.

## ⚙️ Configuration & Setup

TagTeam is fully configured using environment variables. Before starting the containers, create your `.env` file from the template:

```bash
cp env.example .env
```

### Key Environment Variables (`.env`)

* `ADMIN_USERNAME`: Username of the initial bootstrap administrator account (Default: `admin`).
* `ADMIN_PASSWORD`: **Change this immediately** to secure your deployment. This password is bootstrapped into the persistent layer on the very first container initialization.
* `JWT_SECRET`: A long, random secret key utilized to sign secure JSON Web Tokens for user authentication.

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
