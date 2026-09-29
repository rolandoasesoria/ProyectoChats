"""Comprueba la sintaxis de los .js del frontend con QuickJS (ES2020), sin ejecutarlos.

Además carga todos los scripts de index.html en orden en un entorno con un DOM simulado mínimo, para detectar
nombres duplicados entre archivos (p. ej. dos `const` iguales) o referencias rotas al cargar.
"""
import re
import sys
from pathlib import Path

import quickjs  # pip install -r backend/requirements-dev.txt

FRONT = Path(__file__).resolve().parents[1] / "frontend"
ok = True

for js in sorted(FRONT.glob("*.js")):
    src = js.read_text(encoding="utf-8")
    ctx = quickjs.Context()
    try:
        # Envolver en una función que no se llama: solo se analiza la sintaxis.
        ctx.eval("(function(){\n" + src + "\n})")
        print(f"OK   sintaxis {js.name}")
    except quickjs.JSException as e:
        ok = False
        print(f"FAIL sintaxis {js.name}: {e}")

# Carga de todos los scripts de la página principal en el mismo ámbito global, en orden.
html = (FRONT / "index.html").read_text(encoding="utf-8")
scripts = re.findall(r'<script src="([^"]+)"', html)
stub = """
const _el = () => new Proxy(function(){}, { get: (t, k) => k === Symbol.toPrimitive ? () => "" : _el(), apply: () => _el(), set: () => true });
var document = _el(), window = _el(), localStorage = _el(), navigator = _el(), location = _el();
var setInterval = () => 0, setTimeout = () => 0, clearInterval = () => {}, fetch = () => new Promise(() => {});
var console = { log() {}, error() {} };
"""
ctx = quickjs.Context()
ctx.eval(stub)
for name in scripts:
    try:
        ctx.eval((FRONT / name).read_text(encoding="utf-8"))
        print(f"OK   carga {name}")
    except quickjs.JSException as e:
        ok = False
        print(f"FAIL carga {name}: {e}")
sys.exit(0 if ok else 1)
