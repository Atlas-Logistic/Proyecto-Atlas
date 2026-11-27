(function (raiz, fabrica) {
  const api = fabrica();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (raiz) raiz.AtlasExportacionMBT = api;
})(typeof window !== 'undefined' ? window : globalThis, function () {
  'use strict';

  // Exportación operacional MBT. Es deliberadamente pura: recibe los viajes
  // ya publicados por Atlas y los eventos canónicos ya persistidos; no llama
  // OCR, red, routing ni escribe estado alguno.
  const ENCABEZADOS = [
    'Fecha', 'Origen', 'Chofer', 'Rut', 'Patente', 'Nro Guía', 'Cliente',
    '# de Región', 'Comuna', 'Destino', 'Observación', 'Fecha recibo', 'Observaciones 2',
  ];

  const REGION_MBT_POR_CODIGO = {
    '1': 'I', '2': 'II', '3': 'III', '4': 'IV', '5': 'V', '6': 'VI',
    '7': 'VII', '8': 'VIII', '9': 'IX', '10': 'X', '11': 'XI', '12': 'XII',
    '13': 'RM', '14': 'XIV', '15': 'XV', '16': 'XVI',
  };
  const CODIGO_REGION_POR_NOMBRE = {
    'arica y parinacota': '15', 'tarapaca': '1', 'antofagasta': '2', 'atacama': '3', 'coquimbo': '4',
    'valparaiso': '5', 'ohiggins': '6', 'libertador general bernardo ohiggins': '6',
    'maule': '7', 'nuble': '16', 'biobio': '8', 'araucania': '9',
    'los rios': '14', 'los lagos': '10', 'aysen': '11', 'magallanes': '12',
    'metropolitana': '13', 'metropolitana de santiago': '13',
  };

  function texto(valor) { return String(valor == null ? '' : valor).trim(); }
  function clave(valor) {
    return texto(valor).normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/\s+/g, ' ');
  }
  function presente(valor) {
    return !!texto(valor) && !['no encontrado', 'revisar', 'ilegible', 'no disponible'].includes(clave(valor));
  }
  function jsonLista(valor) {
    if (Array.isArray(valor)) return valor;
    try { const dato = JSON.parse(texto(valor) || '[]'); return Array.isArray(dato) ? dato : []; } catch (_) { return []; }
  }
  function primero(...valores) { return valores.find(presente) || ''; }
  function primeraLista(valor) { return texto(valor).split('|').map(texto).find(presente) || ''; }

  // El código CUT de región llega con cero inicial ("08"); "8" y "08" son
  // la misma región.
  function codigoRegionNormalizado(valor) {
    const codigo = texto(valor).replace(/^0+(?=\d)/, '');
    return /^(?:[1-9]|1[0-6])$/.test(codigo) ? codigo : '';
  }

  // Nombre de región comparable entre escrituras: "Del Bio-Bio", "Biobío",
  // "Región del Biobío" y "O'Higgins" quedan en una sola forma.
  function claveRegion(valor) {
    return clave(valor).replace(/['’-]/g, '').replace(/^region\s+/, '')
      .replace(/^(?:del|de)\s+/, '').replace(/^la\s+(?=araucania)/, '').replace(/\s+/g, '');
  }
  const CODIGO_POR_CLAVE_REGION = Object.fromEntries(
    Object.entries(CODIGO_REGION_POR_NOMBRE).map(([nombre, codigo]) => [claveRegion(nombre), codigo]),
  );

  // Índice comuna → código de región construido desde el catálogo
  // territorial oficial (CUT) que entrega Desktop; aquí no se escribe
  // ninguna comuna. Un nombre presente en dos regiones queda ambiguo y no
  // resuelve nada.
  function indiceTerritorial(territorio) {
    const indice = new Map();
    (Array.isArray(territorio) ? territorio : []).forEach((comuna) => {
      const nombre = clave(comuna && (comuna.nombre_comuna_sin_tildes || comuna.nombre_comuna));
      const codigo = codigoRegionNormalizado(comuna && comuna.codigo_region);
      if (!nombre || !codigo) return;
      indice.set(nombre, indice.has(nombre) && indice.get(nombre) !== codigo ? '' : codigo);
    });
    return indice;
  }

  function codigoRegion(doc, entrega, contexto = {}, comunas = [], indice = null) {
    const codigo = codigoRegionNormalizado(doc.codigo_contexto || doc.numero_region || entrega.numero_region || contexto.codigo_region);
    if (codigo) return codigo;
    const porNombre = CODIGO_POR_CLAVE_REGION[claveRegion(primero(doc.region_entrega, entrega.region_entrega, contexto.region_entrega))];
    if (porNombre) return porNombre;
    // Último recurso: la comuna ya mostrada para la guía, resuelta contra el
    // catálogo territorial oficial.
    if (!indice) return '';
    return comunas.filter(presente).map((comuna) => indice.get(clave(comuna))).find(Boolean) || '';
  }

  function regionMBT(doc, entrega, contexto, comunas, indice) {
    return REGION_MBT_POR_CODIGO[codigoRegion(doc, entrega, contexto, comunas, indice)] || '';
  }

  function esRegional(doc, entrega, contexto) {
    const region = codigoRegion(doc, entrega, contexto);
    return !!region && region !== '13';
  }

  function fechaRecibo(doc, entrega, contexto) {
    // Sólo una fecha de recibo explícita es válida siempre. La fecha de
    // llegada documental es la regla MBT local existente; para regional se
    // deja vacía salvo recibo explícito: llegada no demuestra recepción.
    const explicita = primero(doc.fecha_recibo, entrega.fecha_recibo);
    if (explicita) return explicita;
    if (esRegional(doc, entrega, contexto)) return '';
    return primero(doc.fecha_llegada, entrega.fecha_llegada);
  }

  function clasificacion(entregas) {
    const destinos = new Set(entregas.map((e) => clave(e.destino_operacional)).filter(Boolean));
    const cantidad = destinos.size;
    return ({ 1: 'DIRECTO', 2: 'REPARTO', 3: 'REPARTO - 2 CLIENTES', 4: 'REPARTO - 3 CLIENTES' })[cantidad] || '';
  }

  function indiceEntregas(entregas) {
    const indice = new Map();
    entregas.forEach((entrega) => {
      (entrega.numeros_guia || []).forEach((guia) => indice.set(texto(guia), entrega));
    });
    return indice;
  }

  function unico(valores) {
    const encontrados = new Map();
    valores.filter(presente).forEach((valor) => encontrados.set(clave(valor), texto(valor)));
    return encontrados.size === 1 ? [...encontrados.values()][0] : '';
  }

  // No geocodifica ni consulta nada: sólo extrae una comuna escrita
  // explícitamente dentro del destino operacional ya persistido. Se usa
  // antes de la localidad genérica (p.ej. "Santiago") cuando el destino
  // precisa una comuna ("... SAN MIGUEL SAN MIGUEL" o "SANTIAGO LA CISTERNA").
  function comunaExplicitaEnDestino(destino) {
    const partes = texto(destino).split(/\s+/).filter(Boolean);
    if (partes.length < 2) return '';
    for (let largo = Math.min(3, Math.floor(partes.length / 2)); largo >= 1; largo -= 1) {
      const cola = partes.slice(-largo).join(' ');
      const previa = partes.slice(-2 * largo, -largo).join(' ');
      if (clave(cola) === clave(previa)) return cola;
    }
    const indiceSantiago = partes.map(clave).lastIndexOf('santiago');
    return indiceSantiago >= 0 && indiceSantiago < partes.length - 1
      ? partes.slice(indiceSantiago + 1).join(' ') : '';
  }

  function contextoComun(viaje, documentos, entregas) {
    const codigoRegionComun = unico([
      ...documentos.map((d) => d.codigo_contexto || d.numero_region),
      ...entregas.map((e) => e.numero_region),
    ]);
    return {
      origen: primero(viaje.planta_origen_nombre, viaje.planta_origen, primeraLista(viaje.origenes), unico(documentos.map((d) => d.planta_origen_nombre))),
      chofer: primero(primeraLista(viaje.choferes), unico(documentos.map((d) => d.chofer))),
      rut_chofer: primero(primeraLista(viaje.ruts_chofer), unico(documentos.map((d) => d.rut_chofer))),
      patente_tracto: primero(primeraLista(viaje.patentes), primeraLista(viaje.patentes_tracto), unico(documentos.map((d) => d.patente_tracto))),
      codigo_region: codigoRegionComun,
      region_entrega: unico([...documentos.map((d) => d.region_entrega), ...entregas.map((e) => e.region_entrega)]),
    };
  }

  function textoEventoMBT(evento) {
    const tipo = clave(evento.tipo_evento).toUpperCase();
    const gestion = clave(evento.estado_gestion).toUpperCase();
    const estadoIncidencia = texto(evento.estado_incidencia).toUpperCase();
    const nota = clave(evento.nota);
    const espera = estadoIncidencia === 'ESPERA_ESTADIA'
      || tipo === 'ESPERA_ESTADIA' || tipo === 'ESPERA_AUTORIZACION_ESTADIA'
      || tipo === 'ESPERA_DOBLE_VUELTA'
      || (nota.includes('espera') && (nota.includes('autori') || nota.includes('firmen')));
    const aprobada = estadoIncidencia === 'ESTADIA_APROBADA' || gestion === 'APROBADA';
    if (tipo === 'TIENE_ESTADIA' || tipo === 'ESPERA_ESTADIA' || tipo === 'ESPERA_AUTORIZACION_ESTADIA') {
      if (espera) return 'EL CHOFER ESTA A LA ESPERA DE QUE LE AUTORICEN ESTADÍA';
      return aprobada ? 'ESTE VIAJE TIENE ESTADÍA, SE ENVIA GUÍA FIRMADA AL CORREO' : '';
    }
    if (tipo === 'DOBLE_VUELTA' || tipo === 'TIENE_DOBLE_VUELTA' || tipo === 'ESPERA_DOBLE_VUELTA') {
      if (espera) return 'EL CHOFER ESTA A LA ESPERA DE QUE LE FIRMEN LA GUÍA POR DOBLE VUELTA';
      return aprobada ? 'ESTE VIAJE TIENE DOBLE VUELTA, SE ENVIA GUÍA FIRMADA AL CORREO' : '';
    }
    return '';
  }

  function eventosPorTransporte(eventos) {
    const indice = new Map();
    eventos.filter((e) => e && e.estado === 'ACTIVO').forEach((evento) => {
      const transporte = texto(evento.numero_transporte);
      const mensaje = textoEventoMBT(evento);
      if (!transporte || !mensaje) return;
      const actuales = indice.get(transporte) || new Set();
      actuales.add(mensaje);
      indice.set(transporte, actuales);
    });
    return indice;
  }

  function claveMensaje(valor) {
    return clave(valor).replace(/\s+/g, ' ');
  }

  function observacionesSecundarias(incidencias, notaManual) {
    const textos = [...(incidencias || []), texto(notaManual)].filter(presente);
    const vistos = new Set();
    return textos.filter((mensaje) => {
      const claveActual = claveMensaje(mensaje);
      if (vistos.has(claveActual)) return false;
      vistos.add(claveActual);
      return true;
    }).join('\n');
  }

  function documentosDeViaje(viaje) {
    const evidencias = jsonLista(viaje.evidencias_documentos);
    const operacionales = jsonLista(viaje.documentos_operacionales);
    const operacionPorGuia = new Map(operacionales.map((d) => [texto(d.numero_guia), d]));
    if (evidencias.length) {
      return evidencias.map((doc) => Object.assign({}, doc, operacionPorGuia.get(texto(doc.numero_guia)) || {}));
    }
    // Un reporte legado sin detalle por documento sigue siendo exportable,
    // pero sólo como una fila por guía y sin repetir/concentrar destinos.
    return texto(viaje.numeros_guia).split('|').map(texto).filter(Boolean).map((numero_guia) => ({ numero_guia }));
  }

  // Un destino confirmado por una persona (publicado por el Motor como
  // `direccion_operacional` de ESTA guía) reemplaza la lectura impresa.
  function destinoDocumental(doc, entrega) {
    return primero(doc.direccion_operacional, doc.direccion_entrega, entrega.destino_operacional, doc.despachar_a_crudo);
  }

  // Comuna sin resolver: se dice explícitamente, nunca una celda vacía.
  const COMUNA_POR_CONFIRMAR = 'Comuna por confirmar';

  function conCodigoTerritorial(doc) {
    return [doc.codigo_pais, doc.codigo_unidad, doc.codigo_contexto].every(presente);
  }

  // `largo` es `corto` palabra por palabra más sólo el nombre de una comuna
  // ya conocida de la entrega (o SANTIAGO): "LAS PALMERAS 520" / "... 520
  // LA SERENA LA SERENA". No tolera ninguna otra diferencia.
  function soloAgregaComuna(corto, largo, comunas) {
    const a = clave(corto).split(' ');
    const b = clave(largo).split(' ');
    if (!a[0] || b.length <= a.length || a.some((palabra, i) => palabra !== b[i])) return false;
    let resto = b.slice(a.length).join(' ');
    const nombres = [...comunas, 'santiago'].filter(Boolean).sort((x, y) => y.length - x.length);
    while (resto) {
      const nombre = nombres.find((n) => resto === n || resto.startsWith(`${n} `));
      if (!nombre) return false;
      resto = resto.slice(nombre.length).trim();
    }
    return true;
  }

  // Destino común de una entrega con varias guías: `entrega.destino_
  // operacional` del Motor sólo cuando la equivalencia de TODAS sus guías
  // está demostrada. El Motor agrupa por código territorial ANTES que por
  // dirección: si dos guías traen ese código completo, quedaron juntas sin
  // comparar sus direcciones (caso 0000359000, "LO RUIZ 901" / "LO RUI2
  // 2901", destino elegido por desempate) y sólo se aceptan con textos
  // iguales o que difieran únicamente en la comuna. Si a una de las dos le
  // falta el código, el Motor ya exigió direcciones compatibles para
  // juntarlas. Ante cualquier duda, cada guía conserva su propio destino.
  function destinoComunDeEntrega(entrega, documentosEntrega) {
    if (documentosEntrega.length < 2 || !presente(entrega.destino_operacional)) return '';
    const comunas = new Set([entrega.localidad_entrega, ...documentosEntrega.map((d) => d.localidad_entrega)]
      .filter(presente).map(clave));
    for (let i = 0; i < documentosEntrega.length; i += 1) {
      for (let j = i + 1; j < documentosEntrega.length; j += 1) {
        const a = documentosEntrega[i];
        const b = documentosEntrega[j];
        if (!conCodigoTerritorial(a) || !conCodigoTerritorial(b)) continue;
        const da = destinoDocumental(a, entrega);
        const db = destinoDocumental(b, entrega);
        if (clave(da) === clave(db) || soloAgregaComuna(da, db, comunas) || soloAgregaComuna(db, da, comunas)) continue;
        return '';
      }
    }
    return texto(entrega.destino_operacional);
  }

  function filasParaViaje(viaje, eventos, indiceComunas, notasManuales = {}) {
    const entregas = jsonLista(viaje.entregas);
    const documentos = documentosDeViaje(viaje);
    const porGuia = indiceEntregas(entregas);
    const comun = contextoComun(viaje, documentos, entregas);
    const observacion = clasificacion(entregas);
    const secundarios = observacionesSecundarias(
      [...(eventos.get(texto(viaje.numero_transporte)) || new Set())],
      notasManuales[texto(viaje.numero_transporte)],
    );
    const destinosComunes = new Map(entregas.map((entrega) => [entrega, destinoComunDeEntrega(
      entrega, documentos.filter((d) => porGuia.get(texto(d.numero_guia)) === entrega),
    )]));
    return documentos.map((doc) => {
      const entrega = porGuia.get(texto(doc.numero_guia)) || {};
      // La Comuna sigue saliendo del texto propio de la guía: el Destino
      // común nunca cambia la comuna mostrada.
      const documental = destinoDocumental(doc, entrega);
      const destino = destinosComunes.get(entrega) || documental;
      const comuna = primero(doc.comuna_operacional, entrega.comuna_operacional, entrega.comuna_entrega, comunaExplicitaEnDestino(documental), doc.localidad_entrega, entrega.localidad_entrega);
      return [
        // Fecha de emisión documental de ESTA guía; la del viaje es sólo
        // respaldo para reportes legados sin detalle por documento.
        primero(doc.fecha, viaje.fecha),
        primero(doc.planta_origen_nombre, comun.origen),
        primero(doc.chofer, comun.chofer),
        primero(doc.rut_chofer, comun.rut_chofer),
        primero(doc.patente_tracto, comun.patente_tracto),
        texto(doc.numero_guia),
        primero(doc.cliente, (entrega.clientes || [])[0]),
        regionMBT(doc, entrega, comun, [comuna, doc.localidad_entrega, entrega.localidad_entrega], indiceComunas),
        comuna || COMUNA_POR_CONFIRMAR,
        destino,
        observacion,
        fechaRecibo(doc, entrega, comun),
        secundarios,
      ];
    });
  }

  function fechaEnDiaIngesta(fechaIngesta, dia) {
    if (!fechaIngesta) return false;
    const fecha = new Date(fechaIngesta);
    if (Number.isNaN(fecha.getTime())) return false;
    return fecha.getFullYear() === dia.getFullYear()
      && fecha.getMonth() === dia.getMonth() && fecha.getDate() === dia.getDate();
  }

  function filtrarHoyPorIngesta(viajes, hoy = new Date()) {
    return (viajes || []).filter((viaje) => fechaEnDiaIngesta(viaje.fecha_ingesta, hoy));
  }

  // `opciones.territorio`: filas del catálogo territorial oficial de Chile
  // (catalogos_privados/geografia_chile.json del Motor). Sin él, la región
  // sólo sale de los códigos y nombres que ya trae cada guía.
  function construirMatriz(viajes, eventos = [], opciones = {}) {
    const indiceEventos = eventosPorTransporte(eventos);
    const indiceComunas = opciones.territorio ? indiceTerritorial(opciones.territorio) : null;
    return [ENCABEZADOS, ...(viajes || []).flatMap((viaje) => filasParaViaje(viaje, indiceEventos, indiceComunas, opciones.notasManuales || {}))];
  }

  return { ENCABEZADOS, construirMatriz, filtrarHoyPorIngesta, fechaEnDiaIngesta };
});
