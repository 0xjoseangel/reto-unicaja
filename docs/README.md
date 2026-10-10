# Documentación técnica 

## Capítulos

1. **[Visión general y arranque](DOCUMENTACION.md)** — qué hace la app de principio
   a fin, cómo levantarla (Docker o local) y el resumen de la stack tecnológica.
2. **Modelo de datos** — las 10 tablas (`User`, `Account`, `Transaction`,
   `Investment`, `BizumTransfer`, `PendingAction`, `Goal`, `Alert`, `Conversation`,
   `UserProfileVector`) y sus relaciones: ver [`diagramas/esquema-bd.png`](diagramas/esquema-bd.png)
   (fuente: [`diagramas/esquema-bd.dot`](diagramas/esquema-bd.dot)).
3. **[Autenticación](auth.md)** — JWT, registro, login, cómo viaja el `user_id` en
   cada petición.
4. **[El agente de IA](agente-ia.md)** — litellm, tool calling, prompts del sistema,
   multi-proveedor (Anthropic/Gemini/Groq/Mistral/Ollama).
5. **[El grafo de LangGraph](acciones-langgraph.md)** — propuesta, validación
   determinista, aprobación humana (`interrupt`) y ejecución idempotente. Diagrama:
   [`diagramas/grafo-langgraph.png`](diagramas/grafo-langgraph.png) (fuente:
   [`diagramas/grafo-langgraph.dot`](diagramas/grafo-langgraph.dot)).
6. **[Dashboard proactivo](dashboard-proactivo.md)** — tarjetas generadas por IA
   cada noche a partir del contexto financiero de cada usuario.
7. **[Memoria de usuario / RAG casero](memoria-usuario.md)** — extracción de hechos
   del historial de chat, embeddings, similitud coseno, inyección en el prompt.
8. **[Voz](voz.md)** — transcripción con faster-whisper y síntesis con Piper.
9. **Historial de conversaciones** — `GET /chat/history` y `GET /chat/history/{day}`,
   documentado en la [§3.5 de memoria-usuario.md](memoria-usuario.md#35-leer-el-historial--get-chathistory-y-get-chathistoryday).
10. **[Usuarios de prueba](usuarios-prueba.md)** — credenciales y perfil de cada
    usuario del seed, qué probar con cada uno.

## Arquitectura general

Vista completa de cómo se interconectan frontend, backend, agente, litellm,
proveedores de IA y la base de datos:
[`diagramas/arquitectura.png`](diagramas/arquitectura.png) (fuente:
[`diagramas/arquitectura.dot`](diagramas/arquitectura.dot)).

Cómo desplegarlo con Docker: [DOCKER.md](DOCKER.md).
