// Pasarela de pruebas al modelo Cloud v2 publicado por Codex (Atlas-Mobile-Cloud 79de408).
// Evalúa, sin modificarlas, las funciones crear/verificar de test/contrato_cloud_v2_modelo.test.js
// y responde por stdout a los casos JSON recibidos por stdin. Sin red ni escrituras.
// Uso: node modelo_cloud_v2.mjs <ruta a contrato_cloud_v2_modelo.test.js> < casos.json
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import assert from "node:assert/strict";

const fuente = readFileSync(process.argv[2], "utf8");
const inicio = fuente.indexOf("const H = ");
const fin = fuente.indexOf("\nconst entradas = [objeto(");
if (inicio < 0 || fin < 0 || fin < inicio) throw new Error("estructura del modelo Cloud no reconocida");
const modelo = new Function("assert", "createHash", "readFileSync",
  `${fuente.slice(inicio, fin)}\nreturn { crear, verificar, canon, hash, hex, H };`)(assert, createHash, readFileSync);

const casos = JSON.parse(readFileSync(0, "utf8"));
const salida = casos.map((c) => {
  try {
    if (c.op === "crear") {
      const r = modelo.crear(c.empresa, c.generacion, c.anterior, c.entradas);
      return {
        ok: true,
        cabecera_hex: modelo.canon(r.cabecera).toString("hex"),
        partes_sha256: r.partes.map((p) => modelo.hex(modelo.H(modelo.canon(p)))),
        hojas: r.partes.map((p) => modelo.hex(modelo.hash("parte", modelo.canon(p)))),
        huella: r.huella,
      };
    }
    if (c.op === "verificar") {
      modelo.verificar({ cabecera: c.cabecera, partes: c.partes, huella: c.huella }, c.empresa);
      return { ok: true };
    }
    return { ok: false, error: `operación ${c.op}` };
  } catch (e) {
    return { ok: false, error: String(e && e.message || e).slice(0, 200) };
  }
});
process.stdout.write(JSON.stringify(salida));
