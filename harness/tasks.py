"""Task generation + deterministic grading for DeepSeek-direct vs OpenCode-Go benchmark.

Every task returns dict(id, cat, messages, max_tokens, grade). `grade(resp)` gets the
normalized response dict and returns (passed: bool, detail: str).
"""
import json
import random
import re

# ---------------------------------------------------------------- helpers

def _strip_fences(text):
    t = (text or "").strip()
    m = re.search(r"```(?:json|python|py)?\s*(.*?)```", t, re.S)
    return m.group(1).strip() if m else t


def _norm(text):
    return re.sub(r"[*_`]", "", (text or "").strip())


def _safe_json(text):
    return json.loads(_strip_fences(text))


def _json_obj(text):
    t = _strip_fences(text)
    i, j = t.find("{"), t.rfind("}")
    if i == -1 or j == -1:
        raise ValueError("no braces")
    return json.loads(t[i:j + 1])


# ---------------------------------------------------------------- math

def t_math(rng, i):
    a, b, c, d = (rng.randint(11, 97) for _ in range(4))
    expr = f"(({a} * {b}) + {c}) * {d} - {a}"
    ans = ((a * b) + c) * d - a
    return dict(
        id=f"math-{i}", cat="math", max_tokens=2000,
        messages=[{"role": "user", "content":
                   f"Calcula: {expr}\nResponde SOLO con el número entero, sin explicación ni símbolos."}],
        grade=lambda r, ans=ans: _grade_number(r, ans),
    )


def _grade_number(r, ans):
    txt = _norm(r["content"])
    nums = re.findall(r"-?\d[\d,]*", txt.replace(" ", ""))
    if not nums:
        return False, "no number"
    last = int(nums[-1].replace(",", ""))
    return (last == ans, f"got {last} want {ans}")


def t_count(rng, i):
    n = rng.randint(500, 4000)
    a, b, c = rng.sample([2, 3, 4, 5, 7, 9, 11], 3)
    ans = sum(1 for k in range(1, n + 1) if (k % a == 0 or k % b == 0) and k % c != 0)
    return dict(
        id=f"logic-{i}", cat="logic", max_tokens=3000,
        messages=[{"role": "user", "content":
                   f"¿Cuántos enteros entre 1 y {n} (inclusive) son divisibles por {a} o por {b}, "
                   f"pero NO por {c}?\nResponde SOLO el número."}],
        grade=lambda r, ans=ans: _grade_number(r, ans),
    )


def t_code(rng, i):
    specs = [
        dict(
            prompt="Escribe una función Python `solve(nums)` que devuelva una lista con los elementos "
                   "de `nums` sin duplicados, conservando el orden de primera aparición.",
            name="solve", tests=[([1, 2, 1, 3, 2, 4], [1, 2, 3, 4]), ([], []), ([5, 5, 5], [5]),
                                 (["a", "b", "a"], ["a", "b"])],
        ),
        dict(
            prompt="Escribe una función Python `solve(s)` que devuelva True si `s` es un palíndromo "
                   "ignorando mayúsculas, espacios y signos de puntuación.",
            name="solve", tests=[("Anita lava la tina", True), ("Hola", False), ("A man, a plan, a canal: Panama", True),
                                 ("", True)],
        ),
        dict(
            prompt="Escribe una función Python `solve(nums)` que devuelva la suma de los números pares "
                   "multiplicada por la cantidad de impares. Si no hay impares, devuelve 0.",
            name="solve", tests=[([1, 2, 3, 4], 12), ([2, 4], 0), ([], 0), ([1, 1, 3], 0)],
        ),
        dict(
            prompt="Escribe una función Python `solve(d)` que reciba un dict y devuelva una lista de sus "
                   "claves ordenadas por valor descendente; empates ordenados alfabéticamente.",
            name="solve", tests=[({"b": 1, "a": 2}, ["a", "b"]), ({"z": 3, "y": 3, "x": 1}, ["y", "z", "x"]),
                                 ({}, [])],
        ),
        dict(
            prompt="Escribe una función Python `solve(n)` que devuelva la lista de primos menores que n, "
                   "usando criba de Eratóstenes.",
            name="solve", tests=[(10, [2, 3, 5, 7]), (2, []), (20, [2, 3, 5, 7, 11, 13, 17, 19])],
        ),
        dict(
            prompt="Escribe una función Python `solve(s)` que devuelva la palabra más frecuente de `s` "
                   "(sin distinguir mayúsculas). En empate, la que aparece primero. Ignora puntuación.",
            name="solve", tests=[("el gato y el perro", "el"), ("A b a", "a"), ("uno", "uno")],
        ),
        dict(
            prompt="Escribe una función Python `solve(a, b)` que devuelva el máximo común divisor usando "
                   "el algoritmo de Euclides, sin usar math.gcd.",
            name="solve", tests=[((12, 18), 6), ((7, 13), 1), ((0, 5), 5)]),
        dict(
            prompt="Escribe una función Python `solve(m)` que reciba una matriz (lista de listas) y devuelva "
                   "su transpuesta.",
            name="solve", tests=[([[1, 2], [3, 4]], [[1, 3], [2, 4]]), ([[1, 2, 3]], [[1], [2], [3]])]),
    ]
    s = specs[i % len(specs)]
    tests = s["tests"]
    return dict(
        id=f"code-{i}", cat="code", max_tokens=3000,
        messages=[{"role": "user", "content": s["prompt"] + "\nResponde solo con el bloque de código Python."}],
        grade=lambda r, name=s["name"], tests=tests: _grade_code(r, name, tests),
    )


def _grade_code(r, name, tests):
    code = _strip_fences(r["content"])
    if f"def {name}" not in code:
        return False, "no function"
    harness = (code + "\n\nimport json\n"
               "CASES=" + repr(tests) + "\n"
               "out=[]\nfor args,exp in CASES:\n"
               "    try:\n        got=" + name + "(*args) if isinstance(args,tuple) else " + name + "(args)\n"
               "        out.append(got==exp)\n    except Exception:\n        out.append(False)\n"
               "print(json.dumps(out))\n")
    import subprocess, tempfile, os
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(harness)
        path = f.name
    try:
        p = subprocess.run(["python3", path], capture_output=True, text=True, timeout=10)
        res = json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else []
    except Exception as e:
        return False, f"exec error {e}"
    finally:
        os.unlink(path)
    ok = sum(1 for x in res if x)
    return (ok == len(tests), f"{ok}/{len(tests)} tests")


# ---------------------------------------------------------------- instruction following

def _if_tasks():
    T = []
    T.append(dict(prompt="Responde en español con EXACTAMENTE 12 palabras sobre el mar. Sin comillas ni listas.",
                  check=lambda c: (len(c.split()) == 12, f"{len(c.split())} palabras")))
    T.append(dict(prompt="Escribe una sola frase en minúsculas, de 20 palabras o menos, que contenga la palabra "
                         "'zanahoria' exactamente dos veces y no use puntos ni comas.",
                  check=lambda c: (c == c.lower() and "zanahoria" in c and c.count("zanahoria") == 2
                                   and "." not in c and "," not in c and len(c.split()) <= 20,
                                   f"lower={c==c.lower()} zan={c.count('zanahoria')} words={len(c.split())}")))
    T.append(dict(prompt="Explica en 25 palabras o menos por qué el cielo es azul, sin usar NINGÚN dígito.",
                  check=lambda c: (not re.search(r"\d", c) and len(c.split()) <= 25, f"digits={bool(re.search(r'[0-9]', c))} words={len(c.split())}")))
    T.append(dict(prompt='Responde SOLO con un objeto JSON con las claves "ok" (booleano true) y "n" (número 7).',
                  check=lambda c: (_json_obj(c) == {"ok": True, "n": 7}, "json mismatch")))
    T.append(dict(prompt="Devuelve exactamente tres líneas. Cada línea con el formato 'A: <número>' y los números "
                         "deben ser 3, 1 y 2 en ese orden.",
                  check=lambda c: ([l.strip() for l in c.strip().splitlines()] == ["A: 3", "A: 1", "A: 2"], repr(c[:80]))))
    T.append(dict(prompt="Responde únicamente con la palabra SI o la palabra NO, en mayúsculas, sin puntuación. "
                         "¿Es 91 un número primo?",
                  check=lambda c: (c.strip() in ("SI", "NO") and c.strip() == "NO", c.strip()[:20])))
    T.append(dict(prompt="Escribe una lista numerada del 1 al 4 con los nombres de cuatro planetas, uno por línea, "
                         "sin texto adicional.",
                  check=lambda c: (len([l for l in c.strip().splitlines() if l.strip()]) == 4, "line count")))
    T.append(dict(prompt="Traduce al inglés y responde SOLO la traducción, sin comillas: 'mañana temprano'.",
                  check=lambda c: (c.strip().lower() in ("early tomorrow", "tomorrow early",
                                                        "early in the morning tomorrow", "early tomorrow morning",
                                                        "tomorrow morning early"), c.strip()[:40])))
    T.append(dict(prompt="Responde con una sola palabra que empiece con 'p' y termine con 'z'.",
                  check=lambda c: (len(c.split()) == 1 and c.strip().lower().startswith("p") and c.strip().lower().endswith("z"), c.strip()[:30])))
    T.append(dict(prompt='Responde SOLO con JSON válido: una lista de 3 objetos, cada uno con la clave "id" y '
                         'valores 10, 20, 30 en ese orden.',
                  check=lambda c: (_safe_json(c) == [{"id": 10}, {"id": 20}, {"id": 30}], "json mismatch")))
    return T


# ---------------------------------------------------------------- json extraction

_PEOPLE = ["Ana Ruiz", "Camilo Pérez", "Diana Ospina"]


def t_json(rng, i):
    name = _PEOPLE[i % 3]
    amount = rng.randint(1200, 98000)
    day = rng.randint(1, 28)
    doc = (f"ACTA DE REUNIÓN. Asistentes: {name} y Jorge Medina. Se acordó aprobar un presupuesto de "
           f"${amount:,} para el proyecto Halcón. La fecha límite de entrega queda fijada para el {day} de "
           f"noviembre del 2026. El responsable técnico será {name}, correo {name.split()[0].lower()}@ejemplo.co. "
           f"Queda pendiente la firma del acta. Se autorizó pagar en dos cuotas iguales.")
    prompt = (doc + "\n\nExtrae un JSON con exactamente estas claves: \"monto\" (entero, sin símbolos), "
                    "\"dia\" (entero), \"responsable\" (string completo), \"email\" (string), "
                    "\"aprobado\" (booleano true). Responde solo el JSON.")
    def g(r, amount=amount, day=day, name=name):
        try:
            o = _json_obj(r["content"])
        except Exception as e:
            return False, f"bad json {e}"
        exp = {"monto": amount, "dia": day, "responsable": name, "email": name.split()[0].lower() + "@ejemplo.co", "aprobado": True}
        bad = {k: (o.get(k), v) for k, v in exp.items() if o.get(k) != v}
        return (not bad, json.dumps(bad, ensure_ascii=False)[:150])
    return dict(id=f"json-{i}", cat="json", max_tokens=800,
                messages=[{"role": "user", "content": prompt}], grade=g)


# ---------------------------------------------------------------- tools

TOOLS = [
    {"type": "function", "function": {"name": "get_weather", "description": "Clima actual de una ciudad",
     "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {"name": "search_web", "description": "Buscar en la web",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "create_calendar_event", "description": "Crear un evento de calendario",
     "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "date": {"type": "string"},
                                                    "time": {"type": "string"}}, "required": ["title", "date", "time"]}}},
    {"type": "function", "function": {"name": "send_email", "description": "Enviar un correo",
     "parameters": {"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"},
                                                    "body": {"type": "string"}}, "required": ["to", "subject", "body"]}}},
]

_TOOL_CASES = [
    ("¿Qué clima hace ahora en Medellín?", "get_weather", {"city": "Medellín"}),
    ("Busca en internet quién ganó el Balón de Oro 2026", "search_web", {"query": None}),
    ("Agenda una reunión con Ana el martes 10 de noviembre de 2026 a las 15:00", "create_calendar_event", {"title": None, "date": None, "time": "15:00"}),
    ("Mándale un correo a jorge@ejemplo.co con asunto 'Reunión movida' diciendo que la reunión pasa al 12 de noviembre a las 10:00", "send_email", {"to": "jorge@ejemplo.co", "subject": "Reunión movida", "body": None}),
    ("Necesito saber la temperatura en Bogotá antes de salir", "get_weather", {"city": "Bogotá"}),
    ("Busca precios de vuelos a Madrid en diciembre", "search_web", {"query": None}),
    ("Crea el evento 'Demo con cliente' el 12 de noviembre a las 09:30", "create_calendar_event", {"time": "09:30"}),
    ("Escribe a ana@ejemplo.co con asunto 'Pendientes' y recuérdale la entrega", "send_email", {"to": "ana@ejemplo.co", "subject": "Pendientes"}),
    ("¿Cuál es el clima en Ciudad de México?", "get_weather", {"city": None}),
    ("Agenda 'Revisión trimestral' el 3 de diciembre a las 16:00", "create_calendar_event", {"time": "16:00"}),
]


def t_tool(rng, i):
    q, name, args = _TOOL_CASES[i % len(_TOOL_CASES)]
    def g(r, name=name, args=args):
        calls = r.get("tool_calls") or []
        if not calls:
            return False, "no tool call"
        fn = calls[0].get("function", {})
        if fn.get("name") != name:
            return False, f"called {fn.get('name')}"
        try:
            a = json.loads(fn.get("arguments") or "{}")
        except Exception:
            return False, "args not json"
        for k, v in args.items():
            if k not in a or not str(a[k]).strip():
                return False, f"missing {k}"
            if v is not None and str(v).lower() not in str(a[k]).lower():
                return False, f"{k}={a[k]!r} != {v!r}"
        return True, json.dumps(a, ensure_ascii=False)[:120]
    return dict(id=f"tool-{i}", cat="tool", max_tokens=600, tools=TOOLS,
                messages=[{"role": "user", "content": q}], grade=g)


# ---------------------------------------------------------------- long context

_FILLER = [
    "La logística portuaria requiere coordinación entre aduanas, transportistas y almacenes fiscales.",
    "El mantenimiento preventivo de compresores reduce paradas no programadas en planta.",
    "Los protocolos de seguridad industrial se revisan cada trimestre con el comité paritario.",
    "La trazabilidad de lotes permite reconstruir la cadena de frío en menos de una hora.",
]


def _doc(rng, tokens_target, needles):
    parts, n = [], 0
    while n < tokens_target:
        parts.append(rng.choice(_FILLER))
        n += 14
    # place needles at pseudo-random positions
    for pos, nid, text in needles:
        parts.insert(int(len(parts) * pos), text)
    return " ".join(parts)


def t_longctx(rng, i):
    code = f"CLAVE-{rng.randint(1000,9999)}"
    city = rng.choice(["Tarapacá", "Villaverde", "Karakorum", "Argelia"])
    needles = [(0.31, "a", f"NOTA INTERNA: el código de la bóveda es {code} y no debe compartirse."),
               (0.72, "b", f"NOTA INTERNA: la ciudad de origen del envío es {city}.")]
    doc = _doc(rng, 12000, needles)
    q = "Según el documento, ¿cuál es el código de la bóveda? Responde SOLO el código." if i % 2 == 0 else \
        "Según el documento, ¿cuál es la ciudad de origen del envío? Responde SOLO la ciudad."
    want = code if i % 2 == 0 else city
    return dict(id=f"longctx-{i}", cat="longctx", max_tokens=600,
                messages=[{"role": "user", "content": doc + "\n\n" + q}],
                grade=lambda r, want=want: (want.lower() in _norm(r["content"]).lower(), f"want {want}"))


# ---------------------------------------------------------------- registry

def build_all(seed=20261102):
    rng = random.Random(seed)
    tasks = []
    for i in range(20):
        tasks.append(t_math(rng, i))
    for i in range(10):
        tasks.append(t_count(rng, i))
    for i, s in enumerate(_if_tasks()):
        tasks.append(dict(id=f"ifollow-{i}", cat="ifollow", max_tokens=800,
                          messages=[{"role": "user", "content": s["prompt"]}],
                          grade=lambda r, chk=s["check"]: chk(_norm(r["content"]))))
    for i in range(10):
        tasks.append(t_json(rng, i))
    for i in range(8):
        tasks.append(t_code(rng, i))
    for i in range(10):
        tasks.append(t_tool(rng, i))
    for i in range(4):
        tasks.append(t_longctx(rng, i))
    return tasks


if __name__ == "__main__":
    ts = build_all()
    from collections import Counter
    print(len(ts), Counter(t["cat"] for t in ts))
    for t in ts[:3]:
        print(t["id"], t["messages"][0]["content"][:90])
