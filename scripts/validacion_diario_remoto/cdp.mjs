// SOLO PRUEBA (P0.6): evalúa una expresión en la ventana principal de un
// Atlas Viajes REAL lanzado con --remote-debugging-port (protocolo CDP).
//   node cdp.mjs <puerto> <expresion>
// Imprime una línea JSON: {"valor": ...} o {"error": "..."}.
const [puerto, expresion] = process.argv.slice(2);
try {
  const lista = await (await fetch(`http://127.0.0.1:${puerto}/json/list`)).json();
  const pagina = lista.find((t) => t.type === "page" && t.url.includes("atlas_viajes.html"));
  if (!pagina) throw new Error("sin ventana principal");
  const ws = new WebSocket(pagina.webSocketDebuggerUrl);
  await new Promise((ok, mal) => { ws.onopen = ok; ws.onerror = () => mal(new Error("websocket")); });
  ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: { expression: expresion, awaitPromise: true, returnByValue: true } }));
  const m = await new Promise((ok) => { ws.onmessage = (e) => { const d = JSON.parse(e.data); if (d.id === 1) ok(d); }; });
  ws.close();
  const r = m.result || {};
  if (r.exceptionDetails) console.log(JSON.stringify({ error: r.exceptionDetails.exception?.description || r.exceptionDetails.text }));
  else console.log(JSON.stringify({ valor: r.result?.value ?? null }));
} catch (error) {
  console.log(JSON.stringify({ error: String(error?.message || error) }));
}
process.exit(0);
