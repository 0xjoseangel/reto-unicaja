# Diagramas

Fuentes Graphviz (`.dot`) de los diagramas usados en `docs/README.md` y `docs/memoria.pdf`.

Regenerar los PNG tras editar un `.dot`:

```bash
dot -Tpng esquema-bd.dot -o esquema-bd.png
dot -Tpng arquitectura.dot -o arquitectura.png
dot -Tpng grafo-langgraph.dot -o grafo-langgraph.png
```

- `esquema-bd.dot` — tablas del modelo de datos (`app/models/financial.py`) y sus relaciones.
- `arquitectura.dot` — frontend ↔ backend ↔ agente ↔ litellm ↔ proveedores de IA ↔ SQLite.
- `grafo-langgraph.dot` — nodos y aristas reales de `build_graph()` en `app/agent/graph.py`.
