"""Harder probes: 60K-token needle-in-haystack and 20-tool selection."""
import json
import os
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tasks as T  # noqa: E402
import run as R  # noqa: E402

FILLER = [
    "El comité revisó los indicadores de producción y ajustó el calendario de mantenimiento.",
    "La trazabilidad de cada lote se documenta en el sistema y se audita cada trimestre.",
    "Los operarios recibieron capacitación sobre el protocolo de seguridad y evacuación.",
    "El inventario de repuestos se actualizó con las referencias del proveedor principal.",
    "La cadena de frío se monitorea con sensores calibrados y registros horarios.",
    "El área de despacho coordina con transporte para cumplir las ventanas de entrega.",
]


def doc(rng, approx_tokens, needles):
    parts, n = [], 0
    while n < approx_tokens:
        parts.append(rng.choice(FILLER))
        n += 16
    for frac, text in needles:
        parts.insert(int(len(parts) * frac), text)
    return " ".join(parts)


def long_tasks(seed=99):
    rng = random.Random(seed)
    out = []
    for i in range(6):
        code = f"BOV-{rng.randint(10000, 99999)}"
        frac = [0.05, 0.5, 0.95][i % 3]
        d = doc(rng, 58000, [(frac, f"REGISTRO CONFIDENCIAL: el código de la bóveda es {code}.")])
        out.append(dict(id=f"xlong-{i}", cat="xlong", max_tokens=400,
                        messages=[{"role": "user", "content": d + "\n\n¿Cuál es el código de la bóveda? Responde solo el código."}],
                        grade=lambda r, code=code: (code.lower() in (r["content"] or "").lower(), f"want {code}")))
    return out


def _tool(name, desc, props):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": {p: {"type": "string"} for p in props}, "required": props}}}


TOOLS20 = [
    _tool("get_weather_current", "Clima actual de una ciudad", ["city"]),
    _tool("get_weather_forecast", "Pronóstico del clima a varios días", ["city", "days"]),
    _tool("search_flights", "Buscar vuelos disponibles", ["origin", "destination", "date"]),
    _tool("book_flight", "Reservar un vuelo ya seleccionado", ["flight_id"]),
    _tool("search_hotels", "Buscar hoteles en una ciudad", ["city", "checkin", "checkout"]),
    _tool("book_hotel", "Reservar un hotel", ["hotel_id", "nights"]),
    _tool("send_email", "Enviar un correo electrónico", ["to", "subject", "body"]),
    _tool("read_inbox", "Leer los últimos correos", ["folder"]),
    _tool("create_calendar_event", "Crear un evento en el calendario", ["title", "date", "time"]),
    _tool("list_calendar_events", "Listar eventos de un día", ["date"]),
    _tool("convert_currency", "Convertir montos entre monedas", ["amount", "from_currency", "to_currency"]),
    _tool("get_stock_price", "Precio de una acción", ["ticker"]),
    _tool("translate_text", "Traducir texto", ["text", "target_language"]),
    _tool("summarize_document", "Resumir un documento largo", ["document_id"]),
    _tool("create_invoice", "Crear una factura", ["client", "amount"]),
    _tool("list_invoices", "Listar facturas de un cliente", ["client"]),
    _tool("restart_server", "Reiniciar un servidor", ["host"]),
    _tool("check_server_status", "Estado de un servidor", ["host"]),
    _tool("upload_file", "Subir un archivo a la nube", ["path", "destination"]),
    _tool("delete_file", "Borrar un archivo", ["path"]),
]

TOOL_CASES20 = [
    ("¿Va a llover mañana en Bogotá?", "get_weather_forecast"),
    ("Reserva el vuelo AV123 para el martes", "book_flight"),
    ("¿A cuántos pesos equivalen 250 dólares?", "convert_currency"),
    ("Reinicia el servidor prod-01", "restart_server"),
    ("Resume el documento doc-8891", "summarize_document"),
    ("¿Cuántos correos hay en la bandeja de entrada?", "read_inbox"),
]


def tool_tasks():
    out = []
    for i, (q, want) in enumerate(TOOL_CASES20):
        def g(r, want=want):
            calls = r.get("tool_calls") or []
            if not calls:
                return False, "no tool call"
            names = [c["function"]["name"] for c in calls]
            # aceptar secuencia de verificación previa (check -> acción)
            return want in names, f"got {names}"
        out.append(dict(id=f"tool20-{i}", cat="tool20", max_tokens=500, tools=TOOLS20,
                        messages=[{"role": "user", "content": q}], grade=g))
    return out


def run_batch(tag, tasks, workers=4):
    path = os.path.join(R.RESULTS, f"{tag}.jsonl")
    jobs = [(p, t) for p in ("go", "direct") for t in tasks]
    print(f"[{tag}] {len(jobs)} calls", flush=True)
    with open(path, "w") as f, ThreadPoolExecutor(max_workers=workers) as ex:
        for rec in ex.map(lambda a: R.run_task(*a), jobs):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    rows = [json.loads(l) for l in open(path)]
    for p in ("direct", "go"):
        rs = [r for r in rows if r["provider"] == p]
        print(p, f"{sum(r['passed'] for r in rs)}/{len(rs)}", "tin", sum(r["tokens_in"] for r in rs),
              "lat_med", round(sorted(r["latency"] for r in rs)[len(rs) // 2], 2))
    return rows


if __name__ == "__main__":
    run_batch("xlong", long_tasks())
    run_batch("tool20", tool_tasks())
