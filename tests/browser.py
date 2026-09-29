"""Control mínimo de Microsoft Edge (modo invisible) por el protocolo DevTools, para probar la interfaz."""
import base64
import itertools
import json
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SCRATCH = Path(__file__).resolve().parent / ".tmp"
SCRATCH.mkdir(exist_ok=True)
SHOTS = SCRATCH / "shots"


class Browser:
    def __init__(self, port=9223, width=1400, height=900):
        profile = SCRATCH / "edge-profile"
        shutil.rmtree(profile, ignore_errors=True)
        SHOTS.mkdir(exist_ok=True)
        self.proc = subprocess.Popen([
            EDGE, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
            f"--window-size={width},{height}", "--no-first-run", "--disable-extensions", "about:blank"])
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                page = next(t for t in targets if t["type"] == "page")
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        self.ws = connect(page["webSocketDebuggerUrl"], max_size=50_000_000)
        self.ids = itertools.count(1)
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        self.prompt_text = ""  # respuesta que se dará a los prompt()
        for domain in ("Page", "Runtime", "Log"):
            self.send(f"{domain}.enable")
        self.send("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1, mobile=False)

    def _handle_event(self, msg):
        method = msg.get("method")
        if method == "Runtime.exceptionThrown":
            d = msg["params"]["exceptionDetails"]
            self.errors.append(f"Excepción JS: {d.get('exception', {}).get('description') or d.get('text')}")
        elif method == "Runtime.consoleAPICalled" and msg["params"]["type"] == "error":
            self.errors.append("console.error: " + " ".join(str(a.get("value", a.get("description"))) for a in msg["params"]["args"]))
        elif method == "Page.javascriptDialogOpening":
            # Un alert()/confirm() bloquea la página: se acepta y, si no se esperaba, cuenta como incidencia.
            p = msg["params"]
            self.dialogs.append(f"{p['type']}: {p['message']}")
            if p["type"] == "alert":
                self.errors.append(f"alert() inesperado: {p['message']}")
            self.send("Page.handleJavaScriptDialog", accept=True, promptText=self.prompt_text)
        elif method == "Log.entryAdded" and msg["params"]["entry"]["level"] == "error":
            e = msg["params"]["entry"]
            self.errors.append(f"Log: {e['text']} {e.get('url', '')}")

    def send(self, method, **params):
        mid = next(self.ids)
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self._handle_event(msg)

    def pump(self, seconds=0.3):
        """Procesa eventos pendientes (errores de consola) durante un rato."""
        end = time.time() + seconds
        while time.time() < end:
            try:
                self._handle_event(json.loads(self.ws.recv(timeout=max(0.01, end - time.time()))))
            except TimeoutError:
                break

    def js(self, expression, await_promise=True):
        r = self.send("Runtime.evaluate", expression=expression, awaitPromise=await_promise, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(f"JS: {r['exceptionDetails'].get('exception', {}).get('description')}")
        return r.get("result", {}).get("value")

    def goto(self, url):
        self.send("Page.navigate", url=url)
        self.wait("document.readyState === 'complete'")

    def wait(self, expression, timeout=10):
        end = time.time() + timeout
        while time.time() < end:
            try:
                if self.js(f"!!({expression})"):
                    return True
            except RuntimeError:
                pass
            self.pump(0.15)
        raise TimeoutError(f"No se cumplió: {expression}")

    def click(self, selector):
        self.js(f"document.querySelector({json.dumps(selector)}).click()")
        self.pump(0.3)

    def fill(self, selector, value):
        self.js(f"""(() => {{ const el = document.querySelector({json.dumps(selector)});
                   el.value = {json.dumps(value)}; el.dispatchEvent(new Event('input', {{bubbles: true}})); }})()""")

    def shot(self, name):
        self.pump(0.4)
        data = self.send("Page.captureScreenshot", format="png")["data"]
        path = SHOTS / f"{name}.png"
        path.write_bytes(base64.b64decode(data))
        return path

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()
