import os
import re
import fitz
from itertools import combinations

TOLERANCIA_CENTAVOS = 1


def normalizar_texto(texto):
    return " ".join(texto.split())


def convertir_monto(texto):
    try:
        return float(texto.replace(",", "").strip())
    except ValueError:
        return None


def monto_a_centavos(monto):
    return int(round(monto * 100))


def extraer_folio(linea):
    m = re.search(r"\b\d{6,8}\b", linea)
    if m:
        return m.group(0)
    return "Sin folio visible"


def extraer_fecha(linea):
    m = re.search(r"\b\d{2}-[A-Z]{3}-\d{4}\b", linea.upper())
    if m:
        return m.group(0)
    return None


def extraer_montos_de_linea(linea):
    patrones = [
        r"\b\d{1,3}(?:,\d{3})*\.\d{2}\b",
        r"\b\d+\.\d{2}\b"
    ]

    encontrados = []
    for patron in patrones:
        encontrados.extend(re.findall(patron, linea))

    montos = []
    vistos = set()

    for texto in encontrados:
        monto = convertir_monto(texto)
        if monto is not None and monto not in vistos:
            montos.append(monto)
            vistos.add(monto)

    return montos


def buscar_monto_exacto_como_texto(ruta_pdf, texto_busqueda):
    hallazgos = []

    with fitz.open(ruta_pdf) as pdf:
        for num_pagina, pagina in enumerate(pdf, start=1):
            texto = pagina.get_text("text")
            if not texto:
                continue

            if texto_busqueda.lower() not in texto.lower():
                continue

            lineas = texto.split("\n")

            for linea in lineas:
                if texto_busqueda.lower() in linea.lower():
                    hallazgos.append({
                        "archivo": os.path.basename(ruta_pdf),
                        "pagina": num_pagina,
                        "linea": normalizar_texto(linea),
                        "folio": extraer_folio(linea),
                        "fecha": extraer_fecha(linea)
                    })

    return hallazgos


def extraer_movimientos_candidatos(ruta_pdf, objetivo):

    movimientos = []

    with fitz.open(ruta_pdf) as pdf:
        for num_pagina, pagina in enumerate(pdf, start=1):

            texto = pagina.get_text("text")
            if not texto:
                continue

            lineas = texto.split("\n")

            for linea in lineas:

                # Ignorar líneas con ABONO (depósitos)
                if "ABONO" in linea.upper():
                    continue

                fecha = extraer_fecha(linea)
                montos = extraer_montos_de_linea(linea)

                if not montos:
                    continue

                for monto in montos:
                    if monto <= objetivo:
                        movimientos.append({
                            "archivo": os.path.basename(ruta_pdf),
                            "pagina": num_pagina,
                            "linea": normalizar_texto(linea),
                            "folio": extraer_folio(linea),
                            "fecha": fecha,
                            "retiro": monto,
                            "centavos": monto_a_centavos(monto)
                        })

    unicos = []
    vistos = set()

    for mov in movimientos:
        clave = (
            mov["pagina"],
            mov["linea"],
            mov["folio"],
            mov["fecha"],
            mov["centavos"]
        )

        if clave not in vistos:
            vistos.add(clave)
            unicos.append(mov)

    return unicos


def buscar_subset_sum(movimientos, objetivo_centavos, max_movimientos=None):

    dp = {0: None}
    usados = {0: 0}

    for idx, mov in enumerate(movimientos):

        valor = mov["centavos"]

        if valor > objetivo_centavos:
            continue

        sums_actuales = list(dp.keys())

        for suma_actual in sums_actuales:

            cantidad_actual = usados[suma_actual]
            nueva_cantidad = cantidad_actual + 1

            if max_movimientos is not None and nueva_cantidad > max_movimientos:
                continue

            nueva_suma = suma_actual + valor

            if nueva_suma > objetivo_centavos + TOLERANCIA_CENTAVOS:
                continue

            if nueva_suma not in dp:
                dp[nueva_suma] = (suma_actual, idx, nueva_cantidad)
                usados[nueva_suma] = nueva_cantidad

            if abs(nueva_suma - objetivo_centavos) <= TOLERANCIA_CENTAVOS:
                return reconstruir_combinacion(dp, movimientos, nueva_suma)

    return None


def reconstruir_combinacion(dp, movimientos, suma_final):

    resultado = []
    suma = suma_final

    while suma != 0:
        anterior, idx, _cantidad = dp[suma]
        resultado.append(movimientos[idx])
        suma = anterior

    resultado.reverse()

    return resultado


def agrupar_por_fecha(movimientos):

    grupos = {}

    for mov in movimientos:

        fecha = mov["fecha"]

        if not fecha:
            continue

        grupos.setdefault(fecha, []).append(mov)

    return grupos


def buscar_combinacion_misma_fecha(movimientos, objetivo_centavos):

    grupos = agrupar_por_fecha(movimientos)

    for fecha, lista in grupos.items():

        resultado = buscar_subset_sum(lista, objetivo_centavos)

        if resultado:
            return {
                "tipo": "misma_fecha",
                "fechas": [fecha],
                "movimientos": resultado
            }

    return None


def buscar_combinacion_dos_fechas(movimientos, objetivo_centavos):

    grupos = agrupar_por_fecha(movimientos)
    fechas = list(grupos.keys())

    for i in range(len(fechas)):

        fecha1 = fechas[i]
        lista1 = grupos[fecha1]

        for j in range(len(fechas)):

            if i == j:
                continue

            fecha2 = fechas[j]
            lista2 = grupos[fecha2]

            for cantidad in range(1, min(5, len(lista2)) + 1):

                for subset2 in combinations(lista2, cantidad):

                    suma2 = sum(x["centavos"] for x in subset2)

                    if suma2 > objetivo_centavos + TOLERANCIA_CENTAVOS:
                        continue

                    faltante = objetivo_centavos - suma2

                    if abs(faltante) <= TOLERANCIA_CENTAVOS:
                        return {
                            "tipo": "dos_fechas",
                            "fechas": [fecha1, fecha2],
                            "movimientos": list(subset2)
                        }

                    combo1 = buscar_subset_sum(lista1, faltante)

                    if combo1:
                        return {
                            "tipo": "dos_fechas",
                            "fechas": [fecha1, fecha2],
                            "movimientos": combo1 + list(subset2)
                        }

    return None


def imprimir_resultado_exacto(archivo, exactos):

    print(f"\nMonto exacto encontrado en: {archivo}")

    for i, item in enumerate(exactos, start=1):

        print(f"\nCoincidencia #{i}")
        print(f"Página: {item['pagina']}")
        print(f"Fecha: {item['fecha'] or 'Sin fecha visible'}")
        print(f"Folio: {item['folio']}")
        print(f"Línea: {item['linea']}")


def imprimir_resultado_combinacion(archivo, resultado):

    print(f"\nCombinación encontrada en: {archivo}")
    print(f"Tipo: {resultado['tipo']}")
    print(f"Fechas involucradas: {', '.join(resultado['fechas'])}")

    total = 0.0

    for item in resultado["movimientos"]:

        total += item["retiro"]

        print(
            f"Fecha: {item['fecha'] or 'Sin fecha'} | "
            f"Folio: {item['folio']} | "
            f"Página: {item['pagina']} | "
            f"Monto: {item['retiro']:.2f}"
        )

        print(f"Línea: {item['linea']}")

    print(f"\nSuma total: {total:.2f}")


def main():

    carpeta = os.path.dirname(os.path.abspath(__file__))

    archivos_pdf = sorted(
        [f for f in os.listdir(carpeta) if f.lower().endswith(".pdf")]
    )

    if not archivos_pdf:
        print("No hay archivos PDF en la carpeta.")
        return

    texto_busqueda = input("Escribe el monto a buscar: ").strip()

    objetivo = convertir_monto(texto_busqueda)

    if objetivo is None:
        print("Monto inválido. Ejemplo: 18808.16")
        return

    objetivo_centavos = monto_a_centavos(objetivo)

    for archivo in archivos_pdf:

        ruta_pdf = os.path.join(carpeta, archivo)

        exactos = buscar_monto_exacto_como_texto(ruta_pdf, texto_busqueda)

        if exactos:
            imprimir_resultado_exacto(archivo, exactos)
            return

    for archivo in archivos_pdf:

        ruta_pdf = os.path.join(carpeta, archivo)

        print(f"\nRevisando sumatorias en: {archivo}")

        movimientos = extraer_movimientos_candidatos(ruta_pdf, objetivo)

        print(f"  Movimientos candidatos detectados: {len(movimientos)}")

        if not movimientos:
            print("  No hay movimientos candidatos en este PDF.")
            continue

        resultado = buscar_combinacion_misma_fecha(movimientos, objetivo_centavos)

        if resultado:
            imprimir_resultado_combinacion(archivo, resultado)
            return

        resultado = buscar_combinacion_dos_fechas(movimientos, objetivo_centavos)

        if resultado:
            imprimir_resultado_combinacion(archivo, resultado)
            return

        print("  No se encontró sumatoria válida en este PDF.")

    print("\nNo se encontró monto exacto ni sumatoria válida en ningún archivo.")


if __name__ == "__main__":
    main()