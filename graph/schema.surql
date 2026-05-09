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
DEFINE FIELD IF NOT EXISTS source          ON Issue TYPE string;       -- 'jira' | 'github' | 'note'
DEFINE FIELD IF NOT EXISTS external_key    ON Issue TYPE string;       -- 'SYS-123' or 'ToySin/repo#42'
DEFINE FIELD IF NOT EXISTS title           ON Issue TYPE string;
-- `status` is the source's display label ("In Progress", "완료", "Won't Do") —
-- localized, custom-workflow-dependent. For filter logic use `status_category`,
-- which maps to Atlassian's universal vocabulary plus our additions:
--   new           — backlog / todo / not started
--   indeterminate — in progress / in review / actively worked on
--   done          — closed / resolved / won't-do / cancelled
--   undefined     — stub or unknown (e.g. Issue created via cross-reference
--                   from a PR whose source project we don't fetch)
DEFINE FIELD IF NOT EXISTS status          ON Issue TYPE string;
DEFINE FIELD IF NOT EXISTS status_category ON Issue TYPE string DEFAULT "undefined";
DEFINE FIELD IF NOT EXISTS body            ON Issue TYPE option<string>;
DEFINE FIELD IF NOT EXISTS embedding       ON Issue TYPE option<array<float>>;
DEFINE INDEX IF NOT EXISTS issue_external ON Issue FIELDS source, external_key UNIQUE;
DEFINE INDEX IF NOT EXISTS issue_status_category ON Issue FIELDS status_category;

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

-- Notes are raw inputs (Markdown files, Notion pages, Obsidian vault entries).
-- They are not work items themselves; L2 enrichment distills action items
-- out of their bodies into Issue nodes, linked back via extracted_from.
DEFINE TABLE IF NOT EXISTS Note SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS source      ON Note TYPE string;          -- 'markdown_dirs' | 'notion' | 'obsidian'
DEFINE FIELD IF NOT EXISTS path        ON Note TYPE string;          -- absolute file path or external id
DEFINE FIELD IF NOT EXISTS title       ON Note TYPE string;
DEFINE FIELD IF NOT EXISTS body        ON Note TYPE option<string>;
DEFINE FIELD IF NOT EXISTS modified_at ON Note TYPE option<string>;  -- ISO-8601 UTC
DEFINE INDEX IF NOT EXISTS note_path ON Note FIELDS source, path UNIQUE;

DEFINE TABLE IF NOT EXISTS assigned_to TYPE RELATION FROM Person   TO Issue    SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS authored    TYPE RELATION FROM Person   TO GitHubPR SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS implements  TYPE RELATION FROM GitHubPR TO Issue    SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS belongs_to  TYPE RELATION FROM Issue    TO Project  SCHEMAFULL;
DEFINE TABLE IF NOT EXISTS blocked_by  TYPE RELATION FROM Issue    TO Issue    SCHEMAFULL;

DEFINE TABLE IF NOT EXISTS mentions    TYPE RELATION FROM Issue    TO Concept  SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS confidence   ON mentions TYPE float;
DEFINE FIELD IF NOT EXISTS provenance   ON mentions TYPE string;
DEFINE FIELD IF NOT EXISTS extracted_by ON mentions TYPE string;

-- L2 provenance: Issues synthesized from a Note's body link back to that Note.
DEFINE TABLE IF NOT EXISTS extracted_from TYPE RELATION FROM Issue TO Note SCHEMAFULL;
DEFINE FIELD IF NOT EXISTS confidence   ON extracted_from TYPE float;
DEFINE FIELD IF NOT EXISTS extracted_by ON extracted_from TYPE string;

DEFINE INDEX IF NOT EXISTS issue_embedding_hnsw ON Issue
    FIELDS embedding HNSW DIMENSION 8 DIST COSINE TYPE F32;
