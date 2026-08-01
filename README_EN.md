# Dify Pitfalls

> Real-world Dify pitfalls from production, all personally tested and fixed.

## Introduction

This project documents **63 real bugs** we encountered while deploying and operating the Dify platform in production, plus **29 in-depth topic documents** (knowledge base upload, Nginx config, plugin debugging, model integration, etc.).

Every pitfall follows a four-part structure: **Symptom → Diagnosis → Root Cause → Fix** — you can follow along directly without re-discovering the same traps.

## Structure

```
difycaikeng/
├── SKILL.md                    # Core: 63 bug records (Bug1 ~ Bug55+)
├── references/                 # 29 in-depth topic documents
│   ├── Knowledge base upload: dify-upload-md-workflow / json-reupload-workflow / md-json-dify-upload-workflow ...
│   ├── Deployment & ops: dify-inplace-upgrade / dify-custom-basepath-build / weaviate-version-upgrade ...
│   ├── Nginx: nginx-config-rewrite-rule / nginx-joint-chat-routing / nginx-two-instances ...
│   ├── Plugins: plugin-credential-debug-workflow / custom-model-add-workflow ...
│   ├── Models: chain-diagnosis-116 / hybrid-search-weights-issue / token-mismatch-diagnosis-playbook ...
│   └── Business integration: starsower-dify-integration / qa-conversion-workflow / kb-rebuild-workflow ...
└── scripts/                    # Utility scripts (health check, etc.)
```

## Category Overview

| Category | Typical Pitfall | Related Bugs |
|----------|----------------|--------------|
| **Deployment & Upgrade** | Route lost after container restart, in-place upgrade failure | Bug1/3/15+ |
| **Knowledge Base Upload** | Wrong upload format, JSON re-upload, zero retrieval quality | Bug24/25+ |
| **Model Integration** | Custom model setup, dimension mismatch, token mismatch | Topic docs |
| **Nginx Routing** | Sub-path proxy, rewrite rules, dual instances | Topic docs |
| **Plugin Debugging** | Credential encryption, debug workflow | Topic docs |
| **Business Integration** | Connecting to business systems, joint consultation routing | Topic docs |

## Usage

1. Search bug titles in `SKILL.md` by symptom keywords
2. If not found, browse the category-specific documents under `references/`
3. Each bug is a complete chain: Symptom → Diagnosis → Root Cause → Fix

## Who It's For

- Teams deploying/operating Dify on **China-based servers** (highest value)
- Developers building RAG apps with Dify knowledge bases
- Engineers integrating Dify with business systems (WeChat, payments, agents)

## Contributing

PRs welcome — follow the four-part format in `SKILL.md` (Symptom/Diagnosis/Root Cause/Fix).

## License

[MIT](LICENSE)
