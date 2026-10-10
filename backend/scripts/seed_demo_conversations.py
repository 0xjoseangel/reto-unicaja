"""
Script puntual (no forma parte de la app) para enriquecer la demo: genera conversaciones
reales de chat (vía process_chat, con Haiku real) para cada usuario de prueba, con
preguntas adaptadas a su perfil financiero. Se queda fuera de app/ a propósito —no es
código de producción, es un generador de datos de demo que se ejecuta una vez.

Cada "sesión" se persiste de verdad (Conversation vía graph.py), y luego se le
retrasa el created_at a un día concreto para que la vista de "Historial" muestre
varias conversaciones repartidas en el tiempo en vez de todas hoy mismo.

Uso (dentro del contenedor backend, que ya tiene las credenciales de litellm en env):
    docker compose exec backend python scripts/seed_demo_conversations.py
"""
import asyncio
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "/app")

from app.agent.graph import close_graph, init_graph, process_chat
from app.core.database import SessionLocal
from app.models.financial import Conversation, User

# (email, [(días_atrás, [turnos de usuario])])
SESSIONS: dict[str, list[tuple[int, list[str]]]] = {
    "joseangelcarretero300@gmail.com": [
        (4, [
            "¿Cómo va mi cartera de inversión este año?",
            "¿Debería plantearme vender algo de Apple para asegurar beneficios?",
        ]),
        (0, [
            "¿Cuánto llevo ahorrado para la entrada de la vivienda?",
            "Resúmeme en qué he gastado más este mes",
        ]),
    ],
    "maria.garcia@test.com": [
        (5, [
            "¿Cuánto me queda para llegar a mi meta del coche nuevo?",
            "A este ritmo de ahorro, ¿para cuándo lo tendría?",
        ]),
        (1, [
            "¿En qué categoría estoy gastando más este mes?",
            "Dame un gráfico de mis gastos por categoría",
        ]),
    ],
    "carlos.ruiz@test.com": [
        (6, [
            "¿Voy bien con el fondo para la universidad de mis hijos?",
            "Con lo que ahorro al mes, ¿cuándo llegaría a los 50000€?",
        ]),
        (2, [
            "¿Me puedo permitir adelantar la reforma de la cocina este año?",
            "¿Cómo afectaría eso a mi fondo de emergencia?",
        ]),
    ],
    "ana.lopez@test.com": [
        (3, [
            "¿Cuánto llevo ahorrado para el viaje a Japón?",
            "¿En qué puedo recortar gastos este mes para ahorrar más rápido?",
        ]),
        (0, [
            "¿Cuál es mi saldo actual entre las dos cuentas?",
        ]),
    ],
    "alejandro.fernandez@test.com": [
        (7, [
            "Dame un resumen de cómo está mi cartera de inversión",
            "¿Tiene sentido meter más dinero en el fondo indexado pensando en la jubilación anticipada?",
        ]),
        (1, [
            "¿Cómo va el ahorro para la segunda vivienda en la costa?",
            "¿Cuánto gasté el mes pasado en restaurantes y ocio?",
        ]),
    ],
    "lucia.moreno@test.com": [
        (2, [
            "Me preocupa que se me acabe el dinero este mes, ¿cómo lo llevo?",
            "¿Cuánto me falta para el portátil nuevo?",
        ]),
        (0, [
            "¿Cuánto tengo disponible ahora mismo en la cuenta?",
        ]),
    ],
    "manuel.torres@test.com": [
        (4, [
            "¿Cómo van mis gastos de salud este mes comparados con otros meses?",
            "¿Me puedo permitir ya el crucero por el Mediterráneo?",
        ]),
        (0, [
            "Resúmeme mis ingresos y gastos de este mes",
        ]),
    ],
}


async def _run_session(user_id: int, turns: list[str]) -> None:
    history: list[dict] = []
    for message in turns:
        response = await process_chat(message, user_id, history)
        history.append({"role": "user", "content": message})
        history.append({"role": "assistant", "content": response.response})


def _backdate(db, user_id: int, since_id: int, days_ago: int) -> None:
    if days_ago == 0:
        return
    rows = db.query(Conversation).filter(Conversation.user_id == user_id, Conversation.id > since_id).all()
    base = datetime.now() - timedelta(days=days_ago)
    for i, row in enumerate(rows):
        row.created_at = base.replace(hour=10, minute=0) + timedelta(minutes=i * 2)
    db.commit()


async def main() -> None:
    await init_graph()
    db = SessionLocal()
    try:
        for email, sessions in SESSIONS.items():
            user = db.query(User).filter(User.email == email).first()
            if not user:
                print(f"  (saltado: {email} no existe)")
                continue
            print(f"--- {user.name} <{email}>")
            for days_ago, turns in sessions:
                last_id = db.query(Conversation.id).order_by(Conversation.id.desc()).first()
                since_id = last_id[0] if last_id else 0
                await _run_session(user.id, turns)
                _backdate(db, user.id, since_id, days_ago)
                print(f"   sesión de hace {days_ago} día(s): {len(turns)} turno(s) -> ok")
    finally:
        db.close()
        await close_graph()


if __name__ == "__main__":
    asyncio.run(main())
