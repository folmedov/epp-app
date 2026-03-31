# Story: 1.5 Database Connectivity V1

## Objective
Build the first database connectivity layer for Neon using SQLAlchemy Async, so the project can open sessions and validate connection readiness for later loading steps.

## Scope
Includes:
- create the async SQLAlchemy engine
- create a reusable async session factory
- expose a small helper to obtain database sessions
- validate that the Neon connection can be initialized from config
- keep the implementation aligned with the current data models

Does not include:
- upsert logic
- repository layer
- fingerprint generation
- migration tooling
- automatic schema creation in production
- TEEE-related persistence logic

## Inputs / Sources
- requirement.md
- architecture.md
- docs/design/development_approach.md
- src/core/config.py
- src/database/models.py

## Expected Output
- a database session module for async engine and session management
- configuration wired to DATABASE_URL
- a minimal way to verify that the application can connect to Neon
- code that is reusable by the upcoming loading step

## Rules / Constraints
- use SQLAlchemy 2.0 Async API
- use asyncpg as the PostgreSQL driver
- use DATABASE_URL from config
- use logging instead of print
- keep the design minimal and replaceable
- do not implement business logic in this sprint

## Acceptance Criteria
- the project can initialize an async SQLAlchemy engine
- the project can create async sessions from a shared session factory
- the connection configuration is read from application settings
- a minimal connectivity check can run successfully against the configured database
- the implementation is compatible with the current JobOffer model

## Open Questions
- whether migration setup should happen in this sprint or later
- whether a simple connectivity check script is enough, or if a test should also be added

## Definition of Done
A minimal async database connectivity layer exists, can connect using the configured Neon URL, and is ready to support later loading logic.