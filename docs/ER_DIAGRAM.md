# Database ER Diagram

This diagram reflects the SQLAlchemy models currently defined in `app/db/models.py`.

```mermaid
erDiagram
    USERS {
        uuid id PK
        string email UK
        datetime created_at
        datetime updated_at
    }
    GOOGLE_CREDENTIALS {
        uuid id PK
        uuid user_id FK,UK
        text encrypted_access_token
        text encrypted_refresh_token
        text_array granted_scopes
        datetime token_expiry
    }
    CONVERSATIONS {
        uuid id PK
        uuid user_id FK
        datetime created_at
        datetime updated_at
    }
    MESSAGES {
        uuid id PK
        uuid conversation_id FK
        string role
        text content
        datetime created_at
    }
    EXECUTIONS {
        uuid id PK
        uuid user_id FK
        uuid conversation_id FK
        string status
        jsonb intent
        jsonb execution_plan
        datetime created_at
        datetime updated_at
    }
    EXECUTION_STEPS {
        uuid id PK
        uuid execution_id FK
        string step_id
        string service
        string operation
        string status
        jsonb arguments
        jsonb result
        jsonb error_details
    }
    ACTION_APPROVALS {
        uuid id PK
        uuid execution_id FK
        string step_id
        uuid user_id FK
        string status
        jsonb proposed_action
        datetime created_at
        datetime updated_at
    }
    AUDIT_LOGS {
        uuid id PK
        uuid user_id FK
        uuid execution_id FK
        string action
        jsonb details
        datetime created_at
    }
    WORKSPACE_ITEMS {
        uuid id PK
        uuid user_id FK
        string service
        string external_resource_id
        text title
        text searchable_text
        jsonb metadata
        datetime source_created_at
        datetime source_updated_at
        datetime indexed_at
        datetime deleted_at
    }
    DOCUMENT_CHUNKS {
        uuid id PK
        uuid workspace_item_id FK
        uuid user_id FK
        int chunk_index
        text text
        vector_384 embedding
    }
    SYNC_STATE {
        uuid id PK
        uuid user_id FK
        string service
        text sync_cursor
        datetime last_successful_sync
        datetime last_attempted_sync
        string status
        jsonb error_details
    }

    USERS ||--o| GOOGLE_CREDENTIALS : owns
    USERS ||--o{ CONVERSATIONS : owns
    CONVERSATIONS ||--o{ MESSAGES : contains
    USERS ||--o{ EXECUTIONS : owns
    CONVERSATIONS ||--o{ EXECUTIONS : groups
    EXECUTIONS ||--o{ EXECUTION_STEPS : contains
    EXECUTIONS ||--o{ ACTION_APPROVALS : requests
    USERS ||--o{ ACTION_APPROVALS : owns
    USERS ||--o{ AUDIT_LOGS : owns
    EXECUTIONS o|--o{ AUDIT_LOGS : records
    USERS ||--o{ WORKSPACE_ITEMS : indexes
    WORKSPACE_ITEMS ||--o{ DOCUMENT_CHUNKS : contains
    USERS ||--o{ DOCUMENT_CHUNKS : scopes
    USERS ||--o{ SYNC_STATE : tracks
```

## Important constraints

- `users.email` and `google_credentials.user_id` are unique.
- Workspace identities are unique on `(user_id, service, external_resource_id)`, so two users can safely index the same provider identifier without collision.
- Chunk positions are unique on `(workspace_item_id, chunk_index)`. Chunks also carry `user_id` for direct tenant filtering.
- `document_chunks.embedding` is exactly 384 dimensions and has an HNSW cosine index.
- Execution step IDs are unique within an execution: `(execution_id, step_id)`.
- One approval can exist for an execution step: `(execution_id, step_id)`.
- Sync state is unique per `(user_id, service)`.
- Most user-owned operational data cascades on user/execution deletion. Audit-log foreign keys intentionally do not declare cascade deletion.
