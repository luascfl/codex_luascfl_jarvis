# Graph Report - ploomes  (2026-05-06)

## Corpus Check
- 2 files · ~5,777 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 32 nodes · 60 edges · 10 communities detected
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]

## God Nodes (most connected - your core abstractions)
1. `main()` - 10 edges
2. `main()` - 9 edges
3. `list_contacts()` - 5 edges
4. `list_linked_contacts()` - 4 edges
5. `build_candidates()` - 4 edges
6. `list_people()` - 4 edges
7. `parse_args()` - 3 edges
8. `build_root_company_filter()` - 3 edges
9. `contact_id()` - 3 edges
10. `parse_args()` - 3 edges

## Surprising Connections (you probably didn't know these)
- `main()` --calls--> `parse_args()`  [EXTRACTED]
  delete_ploomes_empresas.py → delete_ploomes_empresas.py  _Bridges community 5 → community 2_
- `main()` --calls--> `build_root_company_filter()`  [EXTRACTED]
  delete_ploomes_empresas.py → delete_ploomes_empresas.py  _Bridges community 6 → community 2_
- `main()` --calls--> `list_contacts()`  [EXTRACTED]
  delete_ploomes_empresas.py → delete_ploomes_empresas.py  _Bridges community 0 → community 2_
- `main()` --calls--> `contact_id()`  [EXTRACTED]
  delete_ploomes_empresas.py → delete_ploomes_empresas.py  _Bridges community 4 → community 2_
- `main()` --calls--> `parse_args()`  [EXTRACTED]
  delete_ploomes_pessoas.py → delete_ploomes_pessoas.py  _Bridges community 9 → community 1_

## Communities

### Community 0 - "Community 0"
Cohesion: 0.6
Nodes (5): build_query(), chunks(), list_contacts(), list_linked_contacts(), request_json()

### Community 1 - "Community 1"
Cohesion: 0.4
Nodes (5): build_people_filter(), contact_id(), delete_resource(), deletion_url(), main()

### Community 2 - "Community 2"
Cohesion: 0.5
Nodes (4): delete_resource(), deletion_url(), main(), print_preview()

### Community 3 - "Community 3"
Cohesion: 0.83
Nodes (3): build_query(), list_people(), request_json()

### Community 4 - "Community 4"
Cohesion: 0.67
Nodes (3): build_candidates(), company_id(), contact_id()

### Community 5 - "Community 5"
Cohesion: 1.0
Nodes (2): dotenv_api_key(), parse_args()

### Community 6 - "Community 6"
Cohesion: 1.0
Nodes (2): build_root_company_filter(), odata_escape()

### Community 7 - "Community 7"
Cohesion: 1.0
Nodes (2): print_preview(), summarize()

### Community 8 - "Community 8"
Cohesion: 1.0
Nodes (2): apply_local_filters(), normalized_text()

### Community 9 - "Community 9"
Cohesion: 1.0
Nodes (2): dotenv_api_key(), parse_args()

## Knowledge Gaps
- **Thin community `Community 5`** (2 nodes): `dotenv_api_key()`, `parse_args()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 6`** (2 nodes): `build_root_company_filter()`, `odata_escape()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 7`** (2 nodes): `print_preview()`, `summarize()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 8`** (2 nodes): `apply_local_filters()`, `normalized_text()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 9`** (2 nodes): `dotenv_api_key()`, `parse_args()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `main()` connect `Community 2` to `Community 0`, `Community 4`, `Community 5`, `Community 6`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **Why does `main()` connect `Community 1` to `Community 8`, `Community 9`, `Community 3`, `Community 7`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
- **Why does `list_contacts()` connect `Community 0` to `Community 2`?**
  _High betweenness centrality (0.005) - this node is a cross-community bridge._