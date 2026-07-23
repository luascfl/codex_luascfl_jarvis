---
name: pp-leads-generic-enrichment
description: "How to run and debug the generic use-case enrichment pipeline in pp-leads-brasil (company, goat scripts, output schemas)"
---

## Origem
Criada a partir do contexto: `/home/lucas/Downloads/pp-leads-brasil`

# Generic Use Case Enrichment Workflow

This repository (`pp-leads-brasil`) separates its generic data enrichment core from specific commercial workflows (like OrganizeJr). Follow this process when generating or refreshing lead data for a structured use case:

1. **Locate the use-case config**: 
   The specific use-case definitions live inside `.context/use-cases/<name>/use-case.json`. This config maps source columns (`field_map`), specifies output directories (`output_dir`), and defines text rules (like `message_field`).

2. **Authenticate external services**: 
   Ensure you have credentials for API endpoints (like Casa dos Dados) and Goat services. Use the wrapper:
   ```bash
   scripts/setup-external-enrichment-auth.sh
   ```
   Or the use-case specific wrapper if present (e.g. `.context/use-cases/<name>/setup-auth.sh`).

3. **Run the generic batch pipeline**: 
   Pass the config to the runner script. The runner will spawn a background local server if needed, iterate over the CSV defined in `use-case.json`, and run the sequence `company -> company-goat -> contact-goat -> enrich` on each CNPJ/Name pair:
   ```bash
   scripts/run-use-case-enrichment.sh --config .context/use-cases/<name>/use-case.json
   ```
   Add `--limit N` to test one or two rows, or `--dry-run` to preview the commands.

4. **Verify artifacts**: 
   Inspect the JSON files in the `output_dir` (e.g., `outputs/enrichment/*-enrich.json`). You can use a short Python/jq script to extract and measure metrics like `email` or `link_whatsapp_pronto` coverages.

5. **Modify Outputs (if necessary)**:
   The enrichment shapes (e.g., injecting `mailto:` or `wa.me` links) are computed dynamically via Go code inside `internal/client/pp/client.go` (`ProspectingLinks` func). If you need to change the final JSON shape, alter the Go client, rebuild (`go build -o server_bin ./cmd/server`), and rerun the pipeline.
