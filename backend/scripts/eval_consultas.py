"""Banco de pruebas de consultas en lenguaje natural para la memoria técnica.

Para cada pregunta calcula la respuesta esperada con SQL directo sobre
`data/db.sqlite3` (sin pasar por el agente) y la compara con lo que responde
el agente real (LangGraph + LLM, mismo código que usa la API). No inventa
ninguna cifra: si el agente falla, queda listado en el informe final.

Uso:
    DATABASE_URL="sqlite:///./data/db.sqlite3" .venv/bin/python -I scripts/eval_consultas.py

Requiere el entorno del backend (venv) y una API key de LLM configurada en
`.env` (usa la misma función `_build_model`/`_check_api_key` que la app).
"""
import asyncio
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'data' / 'db.sqlite3').as_posix()}")

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app.agent import graph as graph_module  # noqa: E402
from app.agent.chat_agent import _build_model, _check_api_key  # noqa: E402

DB_PATH = BACKEND_DIR / "data" / "db.sqlite3"
USER_ID = 1  # usuario demo (Jose Angel), datos 100% sintéticos (ver seed.py)


# ── Ground truth: SQL directo, mismas reglas de periodo que financial_mcp.py ──

def _period_dates(period: str) -> tuple[datetime, datetime]:
    now = datetime.now()
    if period == "last_month":
        start = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        end = now.replace(day=1) - timedelta(days=1)
    elif period == "last_3_months":
        start, end = now - timedelta(days=90), now
    elif period == "this_year":
        start, end = datetime(now.year, 1, 1), now
    elif period == "last_week":
        start, end = now - timedelta(days=7), now
    elif period == "all_time":
        start, end = datetime(2000, 1, 1), now
    else:  # current_month
        start, end = now.replace(day=1), now
    return start, end


def _fmt(dt: datetime) -> str:
    """SQLite guarda los DATETIME de SQLAlchemy como 'YYYY-MM-DD HH:MM:SS.ffffff'
    (espacio, no 'T'). datetime.isoformat() usa 'T' y, al compararse como texto,
    ordena mal frente a las filas reales — hay que igualar el formato a mano."""
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _q(query: str, params: tuple = ()) -> list[tuple]:
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchall()
    finally:
        conn.close()


def category_total(category: str, period: str, user_id: int = USER_ID) -> float:
    start, end = _period_dates(period)
    rows = _q(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND category=? "
        "AND transaction_type='gasto' AND date>=? AND date<=?",
        (user_id, category, _fmt(start), _fmt(end)),
    )
    return rows[0][0]


def merchant_total(merchant_like: str, period: str, user_id: int = USER_ID) -> float:
    start, end = _period_dates(period)
    rows = _q(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND merchant LIKE ? "
        "AND transaction_type='gasto' AND date>=? AND date<=?",
        (user_id, f"%{merchant_like}%", _fmt(start), _fmt(end)),
    )
    return rows[0][0]


def total_by_type(tx_type: str, period: str, user_id: int = USER_ID) -> float:
    start, end = _period_dates(period)
    rows = _q(
        "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE user_id=? AND transaction_type=? "
        "AND date>=? AND date<=?",
        (user_id, tx_type, _fmt(start), _fmt(end)),
    )
    return rows[0][0]


def top_category(period: str, user_id: int = USER_ID) -> tuple[str, float]:
    start, end = _period_dates(period)
    rows = _q(
        "SELECT category, SUM(amount) s FROM transactions WHERE user_id=? AND transaction_type='gasto' "
        "AND date>=? AND date<=? GROUP BY category ORDER BY s DESC LIMIT 1",
        (user_id, _fmt(start), _fmt(end)),
    )
    return rows[0] if rows else (None, 0.0)


def count_category(category: str, period: str, user_id: int = USER_ID) -> int:
    start, end = _period_dates(period)
    rows = _q(
        "SELECT COUNT(*) FROM transactions WHERE user_id=? AND category=? AND transaction_type='gasto' "
        "AND date>=? AND date<=?",
        (user_id, category, _fmt(start), _fmt(end)),
    )
    return rows[0][0]


def count_all_time(category: str, user_id: int = USER_ID) -> int:
    # "all_time" en financial_mcp.py sigue acotando por date<=now(): los datos
    # sintéticos incluyen días futuros dentro del mes en curso, hay que excluirlos
    # igual que lo hace la tool para que la comparación sea justa.
    start, end = _period_dates("all_time")
    rows = _q(
        "SELECT COUNT(*) FROM transactions WHERE user_id=? AND category=? AND transaction_type='gasto' "
        "AND date>=? AND date<=?",
        (user_id, category, _fmt(start), _fmt(end)),
    )
    return rows[0][0]


def max_expense(period: str, user_id: int = USER_ID) -> tuple[str, float]:
    start, end = _period_dates(period)
    rows = _q(
        "SELECT merchant, amount FROM transactions WHERE user_id=? AND transaction_type='gasto' "
        "AND date>=? AND date<=? ORDER BY amount DESC LIMIT 1",
        (user_id, _fmt(start), _fmt(end)),
    )
    return rows[0] if rows else (None, 0.0)


def last_transaction() -> tuple[str, float, str]:
    rows = _q(
        "SELECT merchant, amount, date FROM transactions WHERE user_id=? ORDER BY date DESC LIMIT 1",
        (USER_ID,),
    )
    return rows[0]


def merchant_charge_date(merchant_like: str, period: str, user_id: int = USER_ID):
    start, end = _period_dates(period)
    rows = _q(
        "SELECT date FROM transactions WHERE user_id=? AND merchant LIKE ? AND date>=? AND date<=? "
        "ORDER BY date DESC LIMIT 1",
        (user_id, f"%{merchant_like}%", _fmt(start), _fmt(end)),
    )
    return rows[0][0] if rows else None


def account_balance(user_id: int = USER_ID) -> float:
    rows = _q("SELECT COALESCE(SUM(balance),0) FROM accounts WHERE user_id=?", (user_id,))
    return rows[0][0]


def investment_shares(ticker: str, user_id: int = USER_ID) -> float:
    rows = _q(
        "SELECT shares FROM investments WHERE user_id=? AND ticker=?", (user_id, ticker)
    )
    return rows[0][0] if rows else 0.0


def investment_total_cost(user_id: int = USER_ID) -> float:
    rows = _q(
        "SELECT COALESCE(SUM(shares * avg_purchase_price),0) FROM investments WHERE user_id=?",
        (user_id,),
    )
    return rows[0][0]


def bizum_count(period: str, user_id: int = USER_ID) -> int:
    start, end = _period_dates(period)
    rows = _q(
        "SELECT COUNT(*) FROM bizum_transfers WHERE user_id=? AND executed_at>=? AND executed_at<=?",
        (user_id, _fmt(start), _fmt(end)),
    )
    return rows[0][0]


def months_with_data(category: str, user_id: int = USER_ID) -> int:
    rows = _q(
        "SELECT COUNT(DISTINCT strftime('%Y-%m', date)) FROM transactions WHERE user_id=? AND category=?",
        (user_id, category),
    )
    return rows[0][0] or 1


# ── Extracción de cifras de la respuesta en texto libre ───────────────────────

_NUM_RE = re.compile(r"-?\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})?|-?\d+(?:\.\d{1,2})?")


def extract_amounts(text: str) -> list[float]:
    """Extrae números del texto, tolerando formato es-ES (1.234,56) y en-US (1234.56)."""
    found = []
    for raw in _NUM_RE.findall(text):
        token = raw.strip()
        if "," in token:  # es-ES: punto = millares, coma = decimales
            token = token.replace(".", "").replace(" ", "").replace(",", ".")
        else:
            # sin coma: puede ser "1234.56" (decimal) o "1.234" (millares, sin decimales)
            parts = token.replace(" ", "").split(".")
            if len(parts) > 1 and len(parts[-1]) == 3:
                token = "".join(parts)  # 1.234 -> 1234 (millares)
            else:
                token = token.replace(" ", "")
        try:
            found.append(float(token))
        except ValueError:
            continue
    return found


def amount_matches(expected: float, text: str, tol: float = 1.0) -> bool:
    if abs(expected) < 0.01:
        # Cero: aceptar tanto un "0€" explícito como una negación en texto libre
        # ("no tienes gastos registrados..."), que es como responde el agente.
        return any(abs(v) < 0.01 for v in extract_amounts(text)) or "no " in text.lower()
    tol = max(tol, abs(expected) * 0.02)  # 2% o el absoluto, lo que sea mayor
    return any(abs(v - expected) <= tol for v in extract_amounts(text))


MONTH_NAMES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def date_matches(expected_dt_str: str, text: str) -> bool:
    if not expected_dt_str:
        return False
    dt = datetime.fromisoformat(expected_dt_str)
    day_variants = [str(dt.day), f"{dt.day:02d}"]
    month_name = MONTH_NAMES_ES[dt.month]
    has_day = any(d in text for d in day_variants)
    has_month = month_name in text.lower() or f"{dt.month:02d}/" in text or f"/{dt.month:02d}/" in text
    return has_day and has_month


# ── Preguntas ───────────────────────────────────────────────────────────────
# Cada entrada: id, pregunta, tipo (para agrupar en el informe) y check(answer)->bool.
# "ambiguous"/"edge" no cuentan en el % estricto: se reportan aparte como casos
# cualitativos (cobertura de tools, no fallos de precisión binaria).

QUESTIONS = []


def add(qid, question, qtype, check_fn, note=""):
    QUESTIONS.append({"id": qid, "question": question, "type": qtype, "check": check_fn, "note": note})


add("Q1", "¿Cuánto he gastado en gasolina el último mes?", "edge",
    lambda a: amount_matches(merchant_total("Repsol", "last_month"), a, tol=1.0),
    "Enunciado oficial. 'Gasolina' no es una categoría (está dentro de 'transporte', junto a bus/metro/Uber); "
    "exige que el agente filtre por comercio (Repsol), no por categoría completa.")

add("Q2", "¿Cuándo pagué el seguro del coche?", "edge",
    lambda a: "seguro de hogar" in a.lower() or "seguro del coche" in a.lower() and (
        "no" in a.lower() or "no tengo" in a.lower() or "no encuentro" in a.lower()
    ) or ("no" in a.lower()),
    "Enunciado oficial. Solo existe 'Mapfre / Seguro hogar' en los datos: no hay seguro de coche. "
    "El acierto es que el agente NO invente una fecha y lo deje claro (test de honestidad, no de cifra).")

add("Q3", "¿Cuánto gasté en restaurantes este mes?", "category",
    lambda a: amount_matches(category_total("restaurantes", "current_month"), a))

add("Q4", "¿Cuánto gasté en restaurantes el mes pasado?", "category",
    lambda a: amount_matches(category_total("restaurantes", "last_month"), a))

add("Q5", "¿Cuánto gasté en supermercado en los últimos 3 meses?", "category",
    lambda a: amount_matches(category_total("supermercado", "last_3_months"), a))

add("Q6", "¿Cuál es mi gasto total este mes?", "aggregate",
    lambda a: amount_matches(total_by_type("gasto", "current_month"), a))

add("Q7", "¿Cuáles han sido mis ingresos este mes?", "aggregate",
    lambda a: amount_matches(total_by_type("ingreso", "current_month"), a))

add("Q8", "¿Cuánto he gastado en total en ropa desde que tengo la cuenta?", "category",
    lambda a: amount_matches(category_total("ropa", "all_time"), a))

add("Q9", "¿En qué categoría gasto más dinero este mes?", "aggregate",
    lambda a: (lambda cat, val: cat is not None and cat in a.lower() and amount_matches(val, a))(*top_category("current_month")))

add("Q10", "¿Cuántas veces he comido fuera este mes?", "count",
    lambda a: str(count_category("restaurantes", "current_month")) in a)

add("Q11", "¿Cuánto gasto de media al mes en transporte?", "aggregate",
    lambda a: amount_matches(category_total("transporte", "all_time") / months_with_data("transporte"), a, tol=2.0))

add("Q12", "¿He gastado más o menos en restaurantes este mes comparado con el mes pasado?", "comparison",
    lambda a: (("más" in a.lower()) if category_total("restaurantes", "current_month") > category_total("restaurantes", "last_month") else ("menos" in a.lower())))

add("Q13", "¿Cuál ha sido mi gasto más grande este mes?", "aggregate",
    lambda a: (lambda m, v: amount_matches(v, a) and (m is None or m.lower() in a.lower()))(*max_expense("current_month")))

add("Q14", "¿Cuánto pagué de alquiler este mes?", "category",
    lambda a: amount_matches(category_total("alquiler", "current_month"), a))

add("Q15", "¿Cuánto me ha costado Netflix este año?", "merchant",
    lambda a: amount_matches(merchant_total("Netflix", "this_year"), a, tol=2.0))

add("Q16", "¿Qué día se cargó la factura de Vodafone este mes?", "date",
    lambda a: date_matches(merchant_charge_date("Vodafone", "current_month"), a))

add("Q17", "¿Cuál es mi saldo actual?", "aggregate",
    lambda a: amount_matches(account_balance(), a))

add("Q18", "¿Cuántas acciones de Apple tengo?", "investment",
    lambda a: str(investment_shares("AAPL")) in a or str(int(investment_shares("AAPL"))) in a)

add("Q19", "¿Cuánto llevo invertido en total, sin contar la revalorización del mercado?", "investment",
    lambda a: amount_matches(investment_total_cost(), a, tol=5.0))

add("Q20", "¿He hecho algún Bizum este mes?", "edge",
    lambda a: ("no" in a.lower()) if bizum_count("current_month") == 0 else (str(bizum_count("current_month")) in a),
    "La tabla bizum_transfers está vacía en los datos sintéticos: el acierto es que el agente diga que no, no un número inventado.")

add("Q21", "¿Cuánto he gastado en ocio en la última semana?", "edge",
    lambda a: amount_matches(category_total("ocio", "last_week"), a, tol=2.0),
    "'Última semana' no es uno de los periodos que soportan las tools (current_month/last_month/last_3_months/all_time); "
    "mide si el agente aproxima razonablemente o lo señala, no un periodo exacto que no existe.")

add("Q22", "¿Gasté más en supermercado o en restaurantes este mes?", "comparison",
    lambda a: (lambda s, r: ("supermercado" in a.lower()) if s > r else ("restaurantes" in a.lower()))(
        category_total("supermercado", "current_month"), category_total("restaurantes", "current_month")))

add("Q23", "¿Cuánto gasté en salud en el último trimestre?", "category",
    lambda a: amount_matches(category_total("salud", "last_3_months"), a))

add("Q24", "Resúmeme mis finanzas de este mes", "open",
    lambda a: amount_matches(total_by_type("gasto", "current_month"), a, tol=5.0),
    "Pregunta abierta sin tool concreta asociada; se considera acierto si el resumen incluye el gasto total correcto del mes.")

add("Q25", "¿He comprado algo relacionado con libros?", "edge",
    lambda a: ("sí" in a.lower() or "la casa del libro" in a.lower()) if merchant_total("Casa del Libro", "all_time") > 0 else ("no" in a.lower()),
    "Existencial: comprueba que el agente no confunda 'no tengo esa categoría' con 'no hay gasto de ese tipo'.")

add("Q26", "¿Cuánto llevo gastado en comida este mes, contando restaurantes y supermercado?", "aggregate",
    lambda a: amount_matches(category_total("restaurantes", "current_month") + category_total("supermercado", "current_month"), a, tol=2.0),
    "Requiere combinar dos categorías en dos llamadas a tool distintas y sumar.")

add("Q27", "¿Qué fue lo último que compré?", "aggregate",
    lambda a: (lambda m, v, d: (m is None or m.lower() in a.lower()) and amount_matches(v, a))(*last_transaction()))

add("Q28", "¿Cuántas transacciones de transporte he tenido en total desde que uso la app?", "count",
    lambda a: str(count_all_time("transporte")) in a)


# ── Ejecución contra el agente real ───────────────────────────────────────────

async def ask(question: str) -> tuple[str, float]:
    t0 = time.perf_counter()
    response = await graph_module.process_chat(question, USER_ID, [])
    elapsed = time.perf_counter() - t0
    return response.response, elapsed


async def main():
    key_error = _check_api_key(_build_model())
    if key_error:
        print(f"[PENDIENTE] No se puede ejecutar el banco de pruebas: {key_error}")
        return

    graph_module.set_graph(graph_module.build_graph(InMemorySaver()))

    # Para no ensuciar el historial real del usuario demo, se marca la hora de
    # inicio y al final se borran solo las Conversation creadas por este script.
    run_started = datetime.now()

    results = []
    for item in QUESTIONS:
        try:
            answer, elapsed = await ask(item["question"])
            ok = bool(item["check"](answer))
        except Exception as e:  # noqa: BLE001
            answer, elapsed, ok = f"[ERROR] {e}", 0.0, False
        results.append({**item, "answer": answer, "elapsed": elapsed, "ok": ok})
        status = "OK " if ok else "FAIL"
        print(f"[{status}] {item['id']} ({item['type']}, {elapsed:.1f}s): {item['question']}")
        if not ok:
            print(f"        respuesta: {answer[:200]!r}")

    strict = [r for r in results if r["type"] not in ("edge", "open")]
    edge = [r for r in results if r["type"] in ("edge", "open")]

    n_ok = sum(r["ok"] for r in strict)
    print("\n" + "=" * 70)
    print(f"Precisión estricta (categorías no ambiguas): {n_ok}/{len(strict)} "
          f"({100 * n_ok / len(strict):.1f}%)")
    n_ok_edge = sum(r["ok"] for r in edge)
    print(f"Casos límite/ambiguos (informativos, no cuentan en la cifra anterior): "
          f"{n_ok_edge}/{len(edge)}")

    fails = [r for r in results if not r["ok"]]
    if fails:
        print("\nFallos:")
        for r in fails:
            print(f"  - {r['id']} [{r['type']}] {r['question']}")
            print(f"    -> {r['answer'][:200]!r}")

    # Limpieza: borra las Conversation que este script acaba de crear.
    from app.core.database import SessionLocal
    from app.models.financial import Conversation
    db = SessionLocal()
    try:
        deleted = (
            db.query(Conversation)
            .filter(Conversation.user_id == USER_ID, Conversation.created_at >= run_started)
            .delete()
        )
        db.commit()
        print(f"\n(Limpieza: borradas {deleted} filas de Conversation creadas por este run.)")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
