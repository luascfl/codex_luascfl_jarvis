Objetivo: implementar opção (3) "tool contract" forte: validar JSON retornado pelo LLM com schema interno (Pydantic) + tentativa de reparo (1 retry) antes de cair no fallback básico.

Pontos atuais:
- Extrai JSON por split em ```json ... ``` e faz json.loads.
- Se falhar, cai direto em _fallback_basic.

Mudanças propostas:
- Adicionar Pydantic models internos: ReclaimTaskItem, ReclaimTaskList.
- Funções auxiliares:
  - _extract_json_block(text)->str
  - _parse_tasks_json(text)->list[dict]
  - _validate_tasks_payload(obj)->list[dict] (normaliza e valida title/due/notes)
  - _repair_json_with_llm(original_text, error)->content (chama llm com instrução de devolver somente ```json ...```)
- Fluxo:
  1) parse+validate
  2) se falhar: retry repair
  3) se falhar: fallback_basic

Regras de validação:
- array não vazio
- cada item: title str não vazia
- notes opcional (default "Jarvis")
- due opcional, mas se presente deve ser ISO 8601 com Z (YYYY-MM-DDT00:00:00Z) e ser parseável.
- remover campos extras.
