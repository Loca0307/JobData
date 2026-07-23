# Architectural Choices

This document records meaningful decisions that are reflected in the
implementation. Each future entry must identify the chosen option, its
rationale, the relevant files, alternatives and their trade-offs, and the
conditions under which the decision should be revisited.

## 1. Application-Managed Infrastructure Boundary

- **Choice:** Keep infrastructure provisioning outside this repository. The
  application will consume an owner-provisioned DynamoDB table through
  configuration.
- **Why:** The project owner will personally configure DynamoDB and explicitly
  does not want Terraform in this project.
- **Relevant files:** `AGENTS.md`
- **Other possibilities:**
  - Terraform could make environments reproducible, but it is explicitly
    outside this repository's scope.
  - AWS CDK or CloudFormation could provision the same resources, but would
    violate the same application/infrastructure boundary.
  - Automatic table creation at application startup would simplify initial
    setup, but risks mutating production infrastructure unexpectedly.
- **Revisit when:** Only if the owner explicitly changes the infrastructure
  policy. Until then, code may document requirements but must not provision
  cloud resources.

## 2. Data-First Private Platform

- **Choice:** Prioritize collection, provenance, normalization, and durable
  storage before user-facing search, recommendations, or analytics.
- **Why:** The first project phase is intended to build a broad job dataset for
  analysis that will be defined later.
- **Relevant files:** `AGENTS.md`
- **Other possibilities:**
  - A user-facing live search could deliver immediate interaction, but would
    optimize for request latency rather than dataset completeness.
  - Building analytics first could validate presentation ideas, but without a
    stable ingestion layer the analysis would rest on incomplete data.
  - Adding AI enrichment during ingestion could produce richer fields, but
    would increase cost and make raw collection harder to reproduce.
- **Revisit when:** A dependable ingestion pipeline and representative dataset
  exist and the owner defines the first analysis workflow.

