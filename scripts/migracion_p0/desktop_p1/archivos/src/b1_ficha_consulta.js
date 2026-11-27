// Ficha integral de consulta B1. El Motor arma la ficha (`estado: "FICHA"`):
// datos de cada guía y consolidados de su viaje, con valores ausentes o en
// conflicto explícitos. Aquí se presenta una guía por pantalla, con contador
// y Anterior/Siguiente.
//
// Edición integral (P1.2): con «Editar ficha» cada campo editable de la guía
// pasa a ser un campo de texto. Los cambios quedan pendientes por documento
// (se conservan al navegar entre guías); un campo se aplica a todas las guías
// sólo marcando «Aplicar a todas las guías». «Revisar cambios» envía el lote
// al MISMO canal B1 (`@ficha-lote:` + JSON en base64, marcador interno): el
// Motor muestra valor anterior y nuevo, y sólo la confirmación explícita los
// aplica. Este módulo no escribe nada.
(function (global) {
  'use strict';

  const esc = (s) => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');

  const FUENTES = { EXTRACCION: 'Extracción', REPORTE_DESKTOP: 'Desktop', SUMA_GUIAS: 'Suma de las guías' };
  const MARCADOR_LOTE = '@ficha-lote:';
  const COMUNA_POR_CONFIRMAR = 'Comuna por confirmar';
  const MAXIMO_OPCIONES = 3000;

  function fuenteVisible(fuente) {
    const texto = String(fuente || '');
    if (FUENTES[texto]) return FUENTES[texto];
    const guia = /^GUIA (\S+)(?: \((\w+)\))?$/.exec(texto);
    if (guia) return `Guía ${guia[1]}${guia[2] ? ` · ${FUENTES[guia[2]] || guia[2]}` : ''}`;
    return texto;
  }

  function miles(numero) {
    return String(numero).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
  }

  function formatear(campo, valor) {
    const texto = String(valor == null ? '' : valor);
    if (/^peso/.test(campo) && /^\d+(?:[.,]\d+)?$/.test(texto)) return `${miles(Math.round(Number(texto.replace(',', '.'))))} kg`;
    if (campo === 'permanencia_minutos' && /^\d+$/.test(texto)) return `${texto} min`;
    if (campo === 'duracion_min' && /^\d+(?:\.\d+)?$/.test(texto)) return `${Math.round(Number(texto))} min`;
    if (campo === 'distancia_km' && /^\d+(?:\.\d+)?$/.test(texto)) return `${Number(texto).toFixed(1).replace('.', ',')} km`;
    return texto;
  }

  function esFicha(respuesta) {
    return !!respuesta && respuesta.ok !== false && respuesta.estado === 'FICHA'
      && !!respuesta.ficha && Array.isArray(respuesta.ficha.guias) && respuesta.ficha.guias.length > 0;
  }

  // `consulta`: el texto que abrió la ficha (para volver a leerla tras aplicar).
  function crearEstado(respuesta, consulta) {
    if (!esFicha(respuesta)) return null;
    return { ficha: respuesta.ficha, indice: 0, consulta: String(consulta || ''), editando: false,
      cambios: {}, comunes: {}, revision: null, aviso: null };
  }

  function con(estado, cambios) {
    return Object.assign({}, estado, cambios);
  }

  // Índice movido sin salir de los extremos; los cambios pendientes de todas
  // las guías se conservan.
  function mover(estado, paso) {
    if (!estado) return estado;
    const total = estado.ficha.guias.length;
    return con(estado, { indice: Math.min(total - 1, Math.max(0, estado.indice + paso)) });
  }

  function edicionDisponible(estado) {
    return !!(estado && estado.ficha.edicion && estado.ficha.edicion.disponible);
  }

  function camposEditables(estado) {
    return new Set((estado.ficha.edicion && estado.ficha.edicion.campos_editables) || []);
  }

  function editar(estado, activo) {
    return con(estado, { editando: !!activo && edicionDisponible(estado), revision: null, aviso: null });
  }

  function descartar(estado) {
    return con(estado, { editando: false, cambios: {}, comunes: {}, revision: null, aviso: null });
  }

  function campoDe(guia, nombre) {
    return (guia.campos || []).find((c) => c.campo === nombre) || null;
  }

  // Valor vigente de un campo de la guía: '' si falta; null si está en
  // conflicto (no hay un único valor con qué comparar).
  function valorActual(guia, nombre) {
    const c = campoDe(guia, nombre);
    if (!c || c.estado === 'AUSENTE') return '';
    if (c.estado === 'CONFLICTO') return null;
    return String(c.valor == null ? '' : c.valor);
  }

  const normal = (v) => String(v == null ? '' : v).trim().replace(/\s+/g, ' ');
  const igual = (a, b) => normal(a).toUpperCase() === normal(b).toUpperCase();

  function fijarValor(estado, archivo, campo, valor) {
    if (Object.prototype.hasOwnProperty.call(estado.comunes, campo)) {
      return con(estado, { comunes: Object.assign({}, estado.comunes, { [campo]: String(valor) }), aviso: null });
    }
    const cambios = Object.assign({}, estado.cambios);
    const propios = Object.assign({}, cambios[archivo] || {});
    const guia = estado.ficha.guias.find((g) => g.documento.archivo === archivo);
    const actual = guia ? valorActual(guia, campo) : '';
    if (actual !== null && igual(actual, valor)) delete propios[campo];
    else propios[campo] = String(valor);
    if (Object.keys(propios).length) cambios[archivo] = propios; else delete cambios[archivo];
    return con(estado, { cambios, aviso: null });
  }

  // «Aplicar a todas las guías»: sólo por selección explícita. Al marcarlo se
  // usa el valor escrito en la guía visible; al desmarcarlo, cada guía vuelve
  // a su propio valor pendiente (o al vigente).
  function fijarComun(estado, campo, activo, valor) {
    const comunes = Object.assign({}, estado.comunes);
    if (activo) comunes[campo] = String(valor == null ? '' : valor);
    else delete comunes[campo];
    return con(estado, { comunes, aviso: null });
  }

  function valorEditado(estado, guia, campo) {
    if (Object.prototype.hasOwnProperty.call(estado.comunes, campo)) return estado.comunes[campo];
    const propios = estado.cambios[guia.documento.archivo] || {};
    return Object.prototype.hasOwnProperty.call(propios, campo) ? propios[campo] : undefined;
  }

  // Lote a revisar: sólo valores escritos que difieren del vigente.
  function cambiosPendientes(estado) {
    if (!estado) return [];
    const editables = camposEditables(estado);
    const lote = [];
    estado.ficha.guias.forEach((guia) => {
      editables.forEach((campo) => {
        const valor = valorEditado(estado, guia, campo);
        if (valor === undefined || !normal(valor)) return;
        const actual = valorActual(guia, campo);
        if (actual !== null && igual(actual, valor)) return;
        lote.push({ archivo: guia.documento.archivo, numero_guia: guia.documento.numero_guia || '', campo, valor: normal(valor) });
      });
    });
    return lote;
  }

  function base64Url(texto) {
    const bytes = new TextEncoder().encode(texto);
    let binario = '';
    bytes.forEach((b) => { binario += String.fromCharCode(b); });
    const b64 = typeof btoa === 'function' ? btoa(binario) : Buffer.from(bytes).toString('base64');
    return b64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function textoLote(cambios) {
    return MARCADOR_LOTE + base64Url(JSON.stringify({ version: 1, cambios }));
  }

  // `detalleHtml`: el detalle de preview que B1 ya pinta para una corrección
  // en lenguaje natural (HTML escapado por b1HtmlDetalle); el lote trae tabla.
  function conRevision(estado, respuesta, mensaje, detalleHtml) {
    return con(estado, { revision: { respuesta, mensaje: String(mensaje || ''), detalleHtml: String(detalleHtml || '') }, aviso: null });
  }

  function conAviso(estado, respuesta, mensaje, tipo) {
    return con(estado, { revision: null, aviso: { respuesta: respuesta || null, mensaje: String(mensaje || ''), tipo: tipo || 'info' } });
  }

  // Tras aplicar, la ficha se vuelve a leer: misma guía si sigue presente.
  function recargar(anterior, respuesta) {
    const nuevo = crearEstado(respuesta, anterior && anterior.consulta);
    if (!nuevo || !anterior) return nuevo;
    const actual = anterior.ficha.guias[anterior.indice];
    const indice = actual ? nuevo.ficha.guias.findIndex((g) => g.documento.archivo === actual.documento.archivo) : -1;
    return con(nuevo, { indice: indice >= 0 ? indice : 0 });
  }

  function htmlTablas(respuesta) {
    const tablas = (respuesta && Array.isArray(respuesta.tablas)) ? respuesta.tablas : [];
    return tablas.filter((t) => Array.isArray(t.columnas) && Array.isArray(t.filas) && t.filas.length).map((t) => (
      `<table class="b1-ficha-tabla"><thead><tr>${t.columnas.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead>`
      + `<tbody>${t.filas.map((f) => `<tr>${f.map((v) => `<td>${esc(v)}</td>`).join('')}</tr>`).join('')}</tbody></table>`
    )).join('');
  }

  function textoAusente(c) {
    return c.campo === 'localidad_entrega' ? COMUNA_POR_CONFIRMAR : 'Sin dato';
  }

  function htmlValor(c) {
    if (c.estado === 'AUSENTE') return `<span class="b1-ficha-ausente">${textoAusente(c)}</span>`;
    if (c.estado === 'CONFLICTO') {
      const valores = (c.valores || []).map((v) => `<li>${esc(formatear(c.campo, v.valor))} <span class="b1-ficha-fuente">(${esc(fuenteVisible(v.fuente))})</span></li>`).join('');
      return `<span class="b1-ficha-conflicto">En conflicto</span><ul class="b1-ficha-valores">${valores}</ul>`;
    }
    const fuentes = (c.valores || []).map((v) => v.fuente);
    // Un dato que sólo trae una de las fuentes de la guía lo dice.
    const unica = c.nivel === 'GUIA' && fuentes.length === 1
      ? ` <span class="b1-ficha-fuente">(sólo ${esc(fuenteVisible(fuentes[0]))})</span>` : '';
    const faltan = Array.isArray(c.ausente_en) && c.ausente_en.length
      ? ` <span class="b1-ficha-fuente">(sin dato en ${c.ausente_en.length === 1 ? 'la guía' : 'las guías'} ${esc(c.ausente_en.join(', '))})</span>` : '';
    return `${esc(formatear(c.campo, c.valor))}${unica}${faltan}`;
  }

  function htmlEditor(estado, guia, c) {
    const valor = valorEditado(estado, guia, c.campo);
    const comun = Object.prototype.hasOwnProperty.call(estado.comunes, c.campo);
    const actual = valorActual(guia, c.campo);
    const mostrado = valor !== undefined ? valor : (actual || '');
    const cambiado = valor !== undefined && normal(valor) && !(actual !== null && igual(actual, valor));
    const opciones = ((estado.ficha.edicion || {}).opciones || {})[c.campo];
    const lista = Array.isArray(opciones) && opciones.length ? ` list="b1-ficha-opciones-${esc(c.campo)}"` : '';
    const varias = estado.ficha.guias.length > 1;
    return `<div class="b1-ficha-editor${cambiado ? ' b1-ficha-cambiado' : ''}">`
      + `<input type="text" class="b1-ficha-input" maxlength="200" data-ficha-input data-campo="${esc(c.campo)}"`
      + ` aria-label="${esc(c.etiqueta)}" value="${esc(mostrado)}"${lista}>`
      + `<span class="b1-ficha-fuente b1-ficha-vigente">Vigente: ${c.estado === 'OK' ? esc(formatear(c.campo, c.valor)) : htmlValor(c)}</span>`
      + (varias ? `<label class="b1-ficha-comun"><input type="checkbox" data-ficha-comun="${esc(c.campo)}"${comun ? ' checked' : ''}> Aplicar a todas las guías</label>` : '')
      + '</div>';
  }

  function htmlCampos(campos, archivo, estado, guia) {
    // Durante la revisión los valores se muestran fijos hasta confirmar o volver.
    const editables = estado && estado.editando && !estado.revision && guia ? camposEditables(estado) : new Set();
    const grupos = [];
    (campos || []).forEach((c) => {
      let grupo = grupos.find((g) => g.nombre === c.grupo);
      if (!grupo) { grupo = { nombre: c.grupo, campos: [] }; grupos.push(grupo); }
      grupo.campos.push(c);
    });
    return grupos.map((g) => `<div class="b1-ficha-grupo"><h5>${esc(g.nombre)}</h5><dl>${g.campos.map((c) => (
      `<div class="b1-ficha-campo b1-ficha-${esc(String(c.estado || '').toLowerCase())}" data-campo="${esc(c.campo)}" data-nivel="${esc(c.nivel)}"`
      + ` data-estado="${esc(c.estado)}" data-editable="${c.editable ? 'si' : 'no'}"${archivo ? ` data-archivo="${esc(archivo)}"` : ''}>`
      + `<dt>${esc(c.etiqueta)}</dt><dd>${editables.has(c.campo) ? htmlEditor(estado, guia, c) : htmlValor(c)}</dd></div>`
    )).join('')}</dl></div>`).join('');
  }

  function htmlEntregas(entregas) {
    if (!Array.isArray(entregas) || !entregas.length) return '';
    const filas = entregas.map((e) => `<li><strong>${esc(e.comuna || COMUNA_POR_CONFIRMAR)}</strong> · ${esc(e.destino || 'Destino sin dato')}`
      + `${(e.numeros_guia || []).length ? ` · guías ${esc(e.numeros_guia.join(', '))}` : ''}</li>`).join('');
    return `<div class="b1-ficha-grupo"><h5>Entregas (${entregas.length})</h5><ul class="b1-ficha-entregas">${filas}</ul></div>`;
  }

  function htmlOpciones(estado) {
    if (!estado.editando) return '';
    const opciones = (estado.ficha.edicion || {}).opciones || {};
    return Object.keys(opciones).filter((campo) => Array.isArray(opciones[campo]) && opciones[campo].length).map((campo) => (
      `<datalist id="b1-ficha-opciones-${esc(campo)}">${opciones[campo].slice(0, MAXIMO_OPCIONES).map((v) => `<option value="${esc(v)}"></option>`).join('')}</datalist>`
    )).join('');
  }

  function htmlBarraEdicion(estado) {
    if (!edicionDisponible(estado) || estado.revision) return '';
    const pendientes = cambiosPendientes(estado).length;
    const ejemplo = (estado.ficha.guias[estado.indice].documento || {}).numero_guia || 'N';
    const natural = `<form class="b1-ficha-natural" data-ficha-natural>
        <label for="b1-ficha-natural-texto">Corregir con lenguaje natural</label>
        <input id="b1-ficha-natural-texto" name="texto" type="text" maxlength="300" placeholder="Ej.: La comuna de la guía ${esc(ejemplo)} es Quilicura">
        <button type="submit" class="btn btn-ghost">Corregir</button>
      </form>`;
    if (!estado.editando) {
      return `<div class="b1-ficha-edicion"><button type="button" class="btn" data-b1-ficha-editar>Editar ficha</button>${natural}</div>`;
    }
    return `<div class="b1-ficha-edicion">
        <span class="b1-ficha-pendientes" data-ficha-pendientes>${pendientes} ${pendientes === 1 ? 'cambio pendiente' : 'cambios pendientes'}</span>
        <button type="button" class="btn" data-b1-ficha-revisar>Revisar cambios</button>
        <button type="button" class="btn btn-ghost" data-b1-ficha-descartar>Descartar cambios</button>
        ${natural}
      </div>`;
  }

  function htmlRevision(estado) {
    if (!estado.revision) return '';
    const r = estado.revision.respuesta || {};
    return `<section class="b1-ficha-seccion b1-ficha-revision" role="region" aria-label="Revisión de cambios">
        <h4>Revisa los cambios antes de confirmar</h4>
        <p>${esc(estado.revision.mensaje)}</p>
        ${htmlTablas(r) || estado.revision.detalleHtml || ''}
        <div class="b1-ficha-acciones-revision">
          <button type="button" class="btn" data-b1-ficha-confirmar>Confirmar cambios</button>
          <button type="button" class="btn btn-ghost" data-b1-ficha-volver>Volver a la ficha</button>
        </div>
      </section>`;
  }

  function htmlAviso(estado) {
    if (!estado.aviso) return '';
    return `<div class="b1-ficha-aviso-edicion b1-ficha-aviso-${esc(estado.aviso.tipo)}" role="status">
        <p>${esc(estado.aviso.mensaje)}</p>${htmlTablas(estado.aviso.respuesta)}</div>`;
  }

  function html(estado) {
    if (!estado) return '';
    const { ficha, indice } = estado;
    const total = ficha.guias.length;
    const guia = ficha.guias[indice];
    const doc = guia.documento || {};
    const viaje = guia.viaje_indice == null ? null : (ficha.viajes || [])[guia.viaje_indice];
    const nombreGuia = doc.numero_guia ? `Guía ${doc.numero_guia}` : 'Documento sin número de guía';
    const navegacion = total > 1 ? `<div class="b1-ficha-nav" role="group" aria-label="Guías de la ficha">
      <button type="button" class="btn btn-ghost" data-b1-ficha-nav="-1"${indice === 0 ? ' disabled' : ''}>Anterior</button>
      <span class="b1-ficha-contador" aria-live="polite">Documento ${indice + 1} de ${total}</span>
      <button type="button" class="btn btn-ghost" data-b1-ficha-nav="1"${indice === total - 1 ? ' disabled' : ''}>Siguiente</button>
    </div>` : '<div class="b1-ficha-nav"><span class="b1-ficha-contador">Documento 1 de 1</span></div>';
    const original = guia.original && guia.original.archivo
      ? `<a href="#" class="guia-original-enlace" data-b1-ficha-original="${esc(guia.original.archivo)}" data-numero-guia="${esc(doc.numero_guia || '')}">Ver documento original</a>`
      : '<span class="b1-ficha-ausente">Sin documento original registrado</span>';
    const marcas = [
      guia.en_extraccion === false ? 'Sólo en el reporte de Desktop (sin fila en la extracción)' : '',
      guia.en_reporte === false && guia.en_extraccion !== false ? 'No figura en el reporte vigente de Desktop' : '',
      guia.revisiones_pendientes ? `${guia.revisiones_pendientes} revisión(es) pendiente(s)` : '',
    ].filter(Boolean).map((m) => `<p class="b1-ficha-aviso">${esc(m)}</p>`).join('');
    const avisos = (ficha.avisos || []).map((a) => `<p class="b1-ficha-aviso">${esc(a)}</p>`).join('');
    const consolidado = viaje
      ? `<section class="b1-ficha-seccion b1-ficha-viaje" data-viaje-id="${esc(viaje.viaje_id)}">
        <h4>Datos consolidados del viaje · transporte ${esc(viaje.numero_transporte || 'sin dato')}</h4>
        <p class="b1-ficha-nota">Valores de todo el viaje (${(viaje.numeros_guia || []).length} guía(s): ${esc((viaje.numeros_guia || []).join(', '))}), no sólo de esta guía. Se recalculan al aplicar cambios de las guías.</p>
        ${htmlCampos(viaje.campos)}${htmlEntregas(viaje.entregas)}
      </section>`
      : '<section class="b1-ficha-seccion b1-ficha-viaje"><h4>Datos consolidados del viaje</h4><p class="b1-ficha-ausente">Esta guía no tiene un viaje único en el reporte vigente.</p></section>';
    const pie = estado.editando
      ? 'Edición: nada cambia hasta que revises y confirmes los cambios.'
      : 'Consulta de solo lectura: no se cambió nada.';
    return `<div class="b1-ficha${estado.editando ? ' b1-ficha-editando' : ''}" data-b1-ficha="1">
      ${avisos}
      ${htmlAviso(estado)}
      ${htmlRevision(estado)}
      ${htmlBarraEdicion(estado)}
      ${navegacion}
      <section class="b1-ficha-seccion b1-ficha-guia" data-archivo="${esc(doc.archivo || '')}">
        <div class="b1-ficha-encabezado"><h4>${esc(nombreGuia)} · datos de esta guía</h4>${original}</div>
        <p class="b1-ficha-mensaje-original" role="status" hidden></p>
        ${marcas}
        ${htmlCampos(guia.campos, doc.archivo, estado, guia)}
      </section>
      ${consolidado}
      ${htmlOpciones(estado)}
      <p class="b1-ficha-nota">${pie}</p>
    </div>`;
  }

  // Encabezado de la respuesta B1 según el modo de la ficha.
  function encabezado(estado) {
    if (!estado) return null;
    if (estado.revision) return { etiqueta: 'Ficha · revisión de cambios', clase: 'aviso', mensaje: 'Nada cambia hasta que confirmes.' };
    if (estado.editando) return { etiqueta: 'Ficha · edición', clase: 'aviso', mensaje: 'Edita los campos de cada guía; los cambios quedan pendientes hasta revisarlos y confirmarlos.' };
    if (estado.aviso && estado.aviso.tipo === 'ok') return { etiqueta: 'Ficha · actualizada', clase: 'ok', mensaje: 'Datos releídos después de aplicar los cambios.' };
    return null;
  }

  const api = {
    encabezado,
    esFicha, crearEstado, mover, html, formatear, fuenteVisible, editar, descartar, fijarValor, fijarComun,
    cambiosPendientes, textoLote, conRevision, conAviso, recargar, valorActual, MARCADOR_LOTE, COMUNA_POR_CONFIRMAR,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  global.AtlasB1Ficha = api;
})(typeof window !== 'undefined' ? window : globalThis);
