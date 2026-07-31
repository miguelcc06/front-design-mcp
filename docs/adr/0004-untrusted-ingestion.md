# ADR 0004 — Untrusted ingestion

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Orchestrator (Opus) / Implementer (Grok 4.5 High)

## Context

Docs y registries de terceros pueden contener texto adversarial (prompt injection) o frases que imitan instrucciones de sistema. Los agentes consumidores no deben interpretar ese contenido como directives.

## Decision

Tratar **todo** contenido ingerido como **datos no confiables**, nunca como instrucciones:

1. Sanitizar / neutralizar frases de control en summaries (`security/sanitize.py`)
2. Truncar longitud máxima
3. Prefijar / marcar outputs derivados como untrusted
4. Separar en tool envelopes los campos `facts` vs `inferences` donde aplique
5. No ejecutar ni seguir instrucciones embebidas en chunks indexados

## Consequences

- Summaries pueden perder frases legítimas que coincidan con patrones de control (aceptable)
- Tools deben citar fuentes sin copiar ciegamente instrucciones upstream
- Fixtures y network payloads pasan por el mismo pipeline
