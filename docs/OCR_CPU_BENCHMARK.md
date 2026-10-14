# Banco OCR CPU aislado

El banco compara PaddleOCR forzado a CPU y EasyOCR usando copias locales de
fotografías reales. No contiene ni publica fotografías, manifiestos reales ni
resultados: deben quedar bajo `data/ocr_cpu_benchmark/`, directorio ignorado por
Git.

## Manifiesto local

Crear `data/ocr_cpu_benchmark/manifiesto.json` (no versionarlo):

```json
{
  "muestras": [{
    "id": "guia-control-1",
    "origen": "C:\\ruta\\solo-lectura\\guia.jpeg",
    "archivo": "guia-control-1.jpeg",
    "esperado": {
      "numero_guia": "...",
      "numero_transporte": "...",
      "fecha": "...",
      "cliente": "...",
      "obra_destino": "...",
      "chofer": "..."
    }
  }]
}
```

Preparar las copias (no ejecuta OCR):

```powershell
python ocr_benchmark_cpu.py preparar --manifiesto data/ocr_cpu_benchmark/manifiesto.json --destino data/ocr_cpu_benchmark/fotos
```

Después de comprobar que PULL no está activo, ejecutar una vez:

```powershell
python ocr_benchmark_cpu.py comparar --confirmar-ventana-segura --manifiesto data/ocr_cpu_benchmark/manifiesto.json --directorio data/ocr_cpu_benchmark/fotos --salida data/ocr_cpu_benchmark/resultados.json
```

`comparar` vuelve a consultar el scheduler de Windows y se niega a iniciar OCR
si la tarea **Atlas Mobile - PULL Cloud a Motor** está ejecutándose o no puede
ser verificada. El resultado registra texto bruto, acierto por campo, tiempo de
pared y CPU por muestra/motor para distinguir reconocimiento de extracción.
