// Prueba de contrato cruzada: ejecuta el Worker Cloud REAL (copia de solo
// lectura indicada por argumento) con D1 SQLite y R2 en memoria de su propio
// arnés de pruebas. Sin red, sin Cloudflare, sin credenciales reales.
// Uso: node cruce_generaciones.mjs <carpeta-cloud> <pasos.json>
// Imprime en stdout un JSON con la respuesta de cada paso.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [carpeta, archivoPasos] = process.argv.slice(2);
const { default: worker } = await import(pathToFileURL(join(carpeta, "src", "worker.js")).href);
const { crearD1, crearR2 } = await import(pathToFileURL(join(carpeta, "test", "d1_sqlite.js")).href);
const { empresas, pasos } = JSON.parse(readFileSync(archivoPasos, "utf8"));

const sha = (b) => createHash("sha256").update(b).digest("hex");
// Primera empresa por el flujo de una empresa; las demás por el mapa de tokens.
const tokens = Object.fromEntries(empresas.map((e) => [e, `token-sintetico-${e}`]));
const env = {
  DB: crearD1(), DOCUMENTOS_R2: crearR2(),
  CLOUD_MOTOR_AUTH_SECRET: tokens[empresas[0]], CLOUD_MOTOR_EMPRESA_ID: empresas[0],
  CLOUD_MOTOR_TOKENS_JSON: JSON.stringify(Object.fromEntries(empresas.slice(1).map((e) => [sha(tokens[e]), e]))),
};
const leases = {};

async function pedir(empresa, metodo, ruta, cuerpo, extra = {}) {
  const r = await worker.fetch(new Request(`https://local.test${ruta}`, {
    method: metodo, headers: { authorization: `Bearer ${tokens[empresa]}`, ...extra },
    ...(cuerpo === undefined ? {} : { body: cuerpo }),
  }), env);
  const texto = await r.text();
  let body; try { body = JSON.parse(texto); } catch { body = texto; }
  return { status: r.status, body };
}

const prefijo = "/api/motor/custodia/v1/generaciones/";
const resultados = [];
for (const p of pasos) {
  let r;
  const json = { "content-type": "application/json" };
  if (p.op === "adquirir") {
    r = await pedir(p.empresa, "POST", "/api/motor/escritor/adquirir", JSON.stringify({ escritor_id: `pc-${p.empresa}`, protocolo: 2 }), json);
    if (r.status === 200) leases[p.empresa] = r.body.lease_token;
    r = { status: r.status, body: { adquirido: r.status === 200 } };
  } else if (p.op === "subir") {
    const datos = Buffer.from(p.base64, "base64");
    r = await pedir(p.empresa, "PUT", `/api/motor/estado/objetos/${sha(datos)}`, datos, { "x-atlas-lease": leases[p.empresa] });
  } else if (p.op === "preparar") {
    r = await pedir(p.empresa, "POST", prefijo + "preparar", JSON.stringify({
      lease_token: leases[p.lease_de ?? p.empresa], version_base: 0, anterior_id: p.anterior_id, descriptor: p.descriptor }), json);
  } else if (p.op === "publicar") {
    r = await pedir(p.empresa, "POST", prefijo + "publicar", JSON.stringify({ lease_token: leases[p.lease_de ?? p.empresa], generacion_id: p.generacion_id }), json);
  } else if (p.op === "leer") {
    r = await pedir(p.empresa, "GET", prefijo + "actual");
  } else if (p.op === "descargar") {
    const resp = await worker.fetch(new Request(`https://local.test/api/motor/estado/objetos/${p.sha256}`, {
      headers: { authorization: `Bearer ${tokens[p.empresa]}` } }), env);
    r = { status: resp.status, body: { base64: resp.ok ? Buffer.from(await resp.arrayBuffer()).toString("base64") : null } };
  } else {
    throw new Error(`paso desconocido ${p.op}`);
  }
  resultados.push({ op: p.op, etiqueta: p.etiqueta ?? null, ...r });
}
process.stdout.write(JSON.stringify(resultados));
