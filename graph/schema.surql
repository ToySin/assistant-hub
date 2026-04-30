-- Workspace graph schema.
-- Layer 1: structured ETL (typed nodes from Jira/GitHub APIs)
-- Layer 2: LLM enrichment (open ontology with provenance on edges)
--
-- Issue is unified across sources — Jira tickets and GitHub issues are
-- both Issue rows distinguished by `source`. Pull requests stay
-- separate (GitHubPR) because a PR is a code change, not an issue.
--
-- Idempotent: safe to apply on an existing DB.

DEFINE TABLE IF NOT EXISTS Person SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name ON Person TYPE string;
DEFINE INDEX IF NOT EXISTS person_name ON Person FIELDS name UNIQUE;

DEFINE TABLE IF NOT EXISTS Issue SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS source       ON Issue TYPE string;          -- 'jira' | 'github'
DEFINE FIELD IF NOT EXISTS external_key ON Issue TYPE string;          -- 'SYS-123' or 'ToySin/repo#42'
DEFINE FIELD IF NOT EXISTS title        ON Issue TYPE string;
DEFINE FIELD IF NOT EXISTS status       ON Issue TYPE string;
DEFINE FIELD IF NOT EXISTS body         ON Issue TYPE option<string>;
DEFINE FIELD IF NOT EXISTS embedding    ON Issue TYPE option<array<float>>;
DEFINE INDEX IF NOT EXISTS issue_external ON Issue FIELDS source, external_key UNIQUE;

DEFINE TABLE IF NOT EXISTS GitHubPR SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS uid   ON GitHubPR TYPE string;
DEFINE FIELD IF NOT EXISTS title ON GitHubPR TYPE string;
DEFINE FIELD IF NOT EXISTS state ON GitHubPR TYPE string;
DEFINE INDEX IF NOT EXISTS pr_uid ON GitHubPR FIELDS uid UNIQUE;

DEFINE TABLE IF NOT EXISTS Project SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS key  ON Project TYPE string;
DEFINE FIELD IF NOT EXISTS name ON Project TYPE string;
DEFINE INDEX IF NOT EXISTS project_key ON Project FIELDS key UNIQUE;

DEFINE TABLE IF NOT EXISTS Concept SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS name ON Concept TYPE string;
DEFINE INDEX IF NOT EXISTS concept_name ON Concept FIELDS name UNIQUE;

DEFINE TABLE IF NOT EXISTS assigned_to TYPE RELATION FROM Person   TO Issue    SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS authored    TYPE RELATION FROM Person   TO GitHubPR SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS implements  TYPE RELATION FROM GitHubPR TO Issue    SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS belongs_to  TYPE RELATION FROM Issue    TO Project  SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS blocked_by  TYPE RELATION FROM Issue    TO Issue    SCHEMAFULL;

DEFINE TABLE IF NOT EXISTS mentions    TYPE RELATION FROM Issue    TO Concept  SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS confidence   ON mentions TYPE float;
DEFINE FIELD IF NOT EXISTS provenance   ON mentions TYPE string;
DEFINE FIELD IF NOT EXISTS extracted_by ON mentions TYPE string;

DEFINE INDEX IF NOT EXISTS issue_embedding_hnsw ON Issue
    FIELDS embedding HNSW DIMENSION 8 DIST COSINE TYPE F32;
