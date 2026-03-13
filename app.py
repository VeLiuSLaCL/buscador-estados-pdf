import re
from collections import defaultdict

import fitz
import streamlit as st


st.set_page_config(page_title="Buscador de montos", layout="wide")
st.title("Buscador de montos en estados de cuenta")


# ---------------------------
# Utilidades base
# ---------------------------

def normalizar_texto(texto):
    return " ".join(texto.split())


def normalizar_monto_texto(texto):
    """
    Normaliza texto para comparar montos:
    - quita espacios
    - quita comas
    """
    return texto.replace(" ", "").replace(",", "").strip()


def convertir_monto(texto):
    try:
        return float(texto.replace(",", "").strip())
    except ValueError:
        return None


def monto_a_centavos(monto):
    return int(round(monto * 100))


def extraer_fecha(linea):
    m = re.search(r"\b\d{2}-[A-Z]{3}-\d{4}\b", linea.upper())
    if m:
        return m.group(0)
    return None


def extraer_folio(linea):
    m = re.search(r"\b\d{6,8}\b", linea)
    if m:
        return m.group(0)
    return "Sin folio visible"


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


def linea_es_abono(texto):
    """
    True si el texto contiene ABO o ABONO como palabra,
    tolerando espacios raros del OCR.
    """
    texto = texto.upper()
    texto = " ".join(texto.split())

    patrones = [
        r"\bABO\b",
        r"\bABONO\b",
        r"\bA\s*B\s*O\b",
        r"\bA\s*B\s*O\s*N\s*O\b",
    ]

    return any(re.search(patron, texto) for patron in patrones)


# ---------------------------
# Búsqueda exacta
# ---------------------------

def buscar_lineas_con_monto(pdf_bytes, nombre_archivo, monto_busqueda):
    resultados = []
    monto_normalizado = normalizar_monto_texto(monto_busqueda)

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return [{"archivo": nombre_archivo, "error": f"No se pudo abrir el PDF: {e}"}]

    for num_pagina, pagina in enumerate(doc, start=1):
        # Omitir página 1
        if num_pagina == 1:
            continue

        texto_pagina = pagina.get_text("text")
        if not texto_pagina:
            continue

        texto_pagina_normalizado = normalizar_monto_texto(texto_pagina)
        if monto_normalizado not in texto_pagina_normalizado:
            continue

        lineas = texto_pagina.split("\n")

        for i, linea in enumerate(lineas):
            linea_normalizada = normalizar_monto_texto(linea)

            if monto_normalizado not in linea_normalizada:
                continue

            # Revisar contexto: anterior + actual + siguiente
            contexto = []

            if i > 0:
                contexto.append(lineas[i - 1])

            contexto.append(linea)

            if i + 1 < len(lineas):
                contexto.append(lineas[i + 1])

            texto_contexto = " ".join(contexto)

            # Excluir si el contexto parece abono
            if linea_es_abono(texto_contexto):
                continue

            resultados.append({
                "archivo": nombre_archivo,
                "pagina": num_pagina,
                "linea": normalizar_texto(linea),
                "fecha": extraer_fecha(linea),
                "folio": extraer_folio(linea),
                "monto_texto": monto_busqueda,
            })

    return resultados


# ---------------------------
# Recorte dinámico
# ---------------------------

def generar_recorte_monto(pdf_bytes, numero_pagina, monto_busqueda, zoom=3.0):
    """
    Genera un recorte dinámico del movimiento completo:
    - empieza en la línea donde está el monto
    - incluye líneas siguientes relacionadas
    - se detiene al detectar un nuevo movimiento o un salto vertical grande
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pagina = doc[numero_pagina - 1]

        palabras = pagina.get_text("words")
        if not palabras:
            return None

        palabras = sorted(palabras, key=lambda w: (round(w[1], 1), w[0]))

        lineas = []
        tolerancia_y = 3

        for w in palabras:
            x0, y0, x1, y1, txt = w[:5]

            asignada = False
            for linea in lineas:
                if abs(linea["y0"] - y0) <= tolerancia_y:
                    linea["words"].append(w)
                    linea["y0"] = min(linea["y0"], y0)
                    linea["y1"] = max(linea["y1"], y1)
                    asignada = True
                    break

            if not asignada:
                lineas.append({
                    "y0": y0,
                    "y1": y1,
                    "words": [w]
                })

        for linea in lineas:
            linea["words"] = sorted(linea["words"], key=lambda w: w[0])
            linea["texto"] = " ".join(w[4] for w in linea["words"])
            linea["x0"] = min(w[0] for w in linea["words"])
            linea["x1"] = max(w[2] for w in linea["words"])

        lineas = sorted(lineas, key=lambda l: l["y0"])

        monto_normalizado = normalizar_monto_texto(monto_busqueda)

        indice_base = None
        for i, linea in enumerate(lineas):
            texto_normalizado = normalizar_monto_texto(linea["texto"])
            if monto_normalizado in texto_normalizado:
                indice_base = i
                break

        if indice_base is None:
            coincidencias = pagina.search_for(monto_busqueda)
            if not coincidencias:
                return None

            rect = coincidencias[0]
            clip = fitz.Rect(
                20,
                max(0, rect.y0 - 3),
                min(pagina.rect.width, rect.x1 + 40),
                min(pagina.rect.height, rect.y1 + 3),
            )
            matriz = fitz.Matrix(zoom, zoom)
            pix = pagina.get_pixmap(matrix=matriz, clip=clip, alpha=False)
            return pix.tobytes("png")

        linea_base = lineas[indice_base]

        inicio_x = 20
        fin_x = min(pagina.rect.width, linea_base["x1"] + 120)

        y_inicio = max(0, linea_base["y0"] - 3)
        y_fin = min(pagina.rect.height, linea_base["y1"] + 3)

        patron_fecha = re.compile(r"^\d{2}-[A-Z]{3}-\d{4}\b", re.IGNORECASE)

        for j in range(indice_base + 1, len(lineas)):
            actual = lineas[j]
            anterior = lineas[j - 1]

            texto_actual = actual["texto"].strip()
            gap_vertical = actual["y0"] - anterior["y1"]

            if patron_fecha.search(texto_actual):
                break

            if gap_vertical > 10:
                break

            y_fin = min(pagina.rect.height, actual["y1"] + 3)
            fin_x = max(fin_x, min(pagina.rect.width, actual["x1"] + 40))

        clip = fitz.Rect(inicio_x, y_inicio, fin_x, y_fin)

        matriz = fitz.Matrix(zoom, zoom)
        pix = pagina.get_pixmap(matrix=matriz, clip=clip, alpha=False)

        return pix.tobytes("png")

    except Exception:
        return None


# ---------------------------
# Extracción de candidatos para sumatoria
# ---------------------------

def extraer_movimientos_candidatos(pdf_bytes, nombre_archivo, objetivo):
    movimientos = []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:
        return movimientos

    for num_pagina, pagina in enumerate(doc, start=1):
        if num_pagina == 1:
            continue

        texto_pagina = pagina.get_text("text")
        if not texto_pagina:
            continue

        lineas = texto_pagina.split("\n")

        for i, linea in enumerate(lineas):
            fecha = extraer_fecha(linea)
            if not fecha:
                continue

            contexto = []

            if i > 0:
                contexto.append(lineas[i - 1])
            contexto.append(linea)
            if i + 1 < len(lineas):
                contexto.append(lineas[i + 1])

            texto_contexto = " ".join(contexto)

            # Excluir abonos
            if linea_es_abono(texto_contexto):
                continue

            montos = extraer_montos_de_linea(linea)
            if not montos:
                continue

            # Tomar solo el último monto útil de la línea
            monto = montos[-1]

            if monto <= 0 or monto > objetivo:
                continue

            movimientos.append({
                "archivo": nombre_archivo,
                "pagina": num_pagina,
                "fecha": fecha,
                "folio": extraer_folio(linea),
                "linea": normalizar_texto(linea),
                "monto": monto,
                "centavos": monto_a_centavos(monto),
            })

    # quitar duplicados
    unicos = []
    vistos = set()

    for mov in movimientos:
        clave = (
            mov["archivo"],
            mov["pagina"],
            mov["fecha"],
            mov["folio"],
            mov["linea"],
            mov["centavos"],
        )
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(mov)

    return unicos


# ---------------------------
# Subset sum por una sola fecha
# ---------------------------

def buscar_opciones_sumatoria_misma_fecha(movimientos, objetivo_centavos, max_opciones=20):
    """
    Devuelve varias opciones de sumatoria.
    Cada opción usa movimientos de una sola fecha.
    """
    grupos = defaultdict(list)
    for mov in movimientos:
        grupos[mov["fecha"]].append(mov)

    opciones = []

    for fecha, lista in grupos.items():
        lista = sorted(lista, key=lambda x: x["centavos"], reverse=True)

        dp = {0: []}

        for idx, mov in enumerate(lista):
            valor = mov["centavos"]
            sums_actuales = list(dp.keys())

            for suma_actual in sums_actuales:
                nueva_suma = suma_actual + valor

                if nueva_suma > objetivo_centavos:
                    continue

                if nueva_suma in dp:
                    continue

                nueva_ruta = dp[suma_actual] + [idx]
                dp[nueva_suma] = nueva_ruta

                if nueva_suma == objetivo_centavos:
                    combo = [lista[i] for i in nueva_ruta]
                    opciones.append({
                        "archivo": combo[0]["archivo"],
                        "fecha": fecha,
                        "movimientos": combo,
                        "total": sum(x["monto"] for x in combo),
                        "cantidad_movimientos": len(combo),
                    })

                    if len(opciones) >= max_opciones:
                        return ordenar_opciones(opciones)

        if len(opciones) >= max_opciones:
            break

    return ordenar_opciones(opciones)


def ordenar_opciones(opciones):
    return sorted(
        opciones,
        key=lambda x: (
            x["cantidad_movimientos"],
            x["archivo"],
            x["fecha"],
        )
    )


# ---------------------------
# Render
# ---------------------------

def mostrar_resultados_exactos(resultados_totales, archivos_bytes, monto_busqueda):
    st.success(f"Se encontraron {len(resultados_totales)} coincidencia(s) exactas válidas.")

    for i, resultado in enumerate(resultados_totales, start=1):
        if "error" in resultado:
            st.error(f"{resultado['archivo']}: {resultado['error']}")
            continue

        with st.container():
            st.markdown(f"### Coincidencia exacta #{i}")
            st.write(f"**Archivo:** {resultado['archivo']}")
            st.write(f"**Página:** {resultado['pagina']}")
            if resultado.get("fecha"):
                st.write(f"**Fecha:** {resultado['fecha']}")
            st.write(f"**Folio:** {resultado['folio']}")
            st.write(f"**Línea:** {resultado['linea']}")

            recorte = generar_recorte_monto(
                archivos_bytes[resultado["archivo"]],
                resultado["pagina"],
                monto_busqueda
            )

            if recorte:
                st.image(
                    recorte,
                    caption=f"Recorte visual de {resultado['archivo']} - página {resultado['pagina']}",
                    use_container_width=False
                )

            st.divider()


def mostrar_selector_opciones(opciones):
    etiquetas = []
    for i, op in enumerate(opciones, start=1):
        etiquetas.append(
            f"Opción {i} | Archivo: {op['archivo']} | Fecha: {op['fecha']} | "
            f"Movimientos: {op['cantidad_movimientos']} | Total: {op['total']:,.2f}"
        )

    seleccion = st.selectbox(
        "Selecciona una opción de sumatoria",
        options=list(range(len(opciones))),
        format_func=lambda idx: etiquetas[idx]
    )
    return seleccion


def mostrar_detalle_opcion(opcion, archivos_bytes):
    st.markdown("## Detalle de la opción seleccionada")
    st.write(f"**Archivo:** {opcion['archivo']}")
    st.write(f"**Fecha:** {opcion['fecha']}")
    st.write(f"**Cantidad de movimientos:** {opcion['cantidad_movimientos']}")
    st.write(f"**Suma total:** {opcion['total']:,.2f}")

    st.divider()

    for i, mov in enumerate(opcion["movimientos"], start=1):
        st.markdown(f"### Movimiento #{i}")
        st.write(f"**Monto:** {mov['monto']:,.2f}")
        st.write(f"**Página:** {mov['pagina']}")
        st.write(f"**Fecha:** {mov['fecha']}")
        st.write(f"**Folio:** {mov['folio']}")
        st.write(f"**Línea:** {mov['linea']}")

        recorte = generar_recorte_monto(
            archivos_bytes[mov["archivo"]],
            mov["pagina"],
            f"{mov['monto']:,.2f}"
        )

        if not recorte:
            recorte = generar_recorte_monto(
                archivos_bytes[mov["archivo"]],
                mov["pagina"],
                f"{mov['monto']:.2f}"
            )

        if recorte:
            st.image(
                recorte,
                caption=f"Recorte visual de {mov['archivo']} - página {mov['pagina']}",
                use_container_width=False
            )

        st.divider()


# ---------------------------
# UI principal
# ---------------------------

uploaded_files = st.file_uploader(
    "Sube los PDFs",
    type=["pdf"],
    accept_multiple_files=True
)

monto_busqueda = st.text_input(
    "Monto a buscar",
    placeholder="Ejemplo: 18808.16"
)

if st.button("Buscar"):
    if not uploaded_files:
        st.warning("Sube al menos un PDF.")
    elif not monto_busqueda.strip():
        st.warning("Escribe un monto.")
    else:
        objetivo = convertir_monto(monto_busqueda.strip())
        if objetivo is None:
            st.error("Monto inválido. Ejemplo correcto: 18808.16")
            st.stop()

        archivos_bytes = {}
        resultados_exactos = []

        with st.spinner("Buscando monto exacto en los archivos..."):
            for archivo in uploaded_files:
                pdf_bytes = archivo.read()
                archivos_bytes[archivo.name] = pdf_bytes

                resultados = buscar_lineas_con_monto(
                    pdf_bytes,
                    archivo.name,
                    monto_busqueda.strip()
                )
                resultados_exactos.extend(resultados)

        exactos_validos = [r for r in resultados_exactos if "error" not in r]

        if exactos_validos:
            mostrar_resultados_exactos(exactos_validos, archivos_bytes, monto_busqueda.strip())
        else:
            st.info("No se encontró monto exacto. Buscando opciones de sumatoria por un solo día...")

            todos_los_movimientos = []

            for nombre_archivo, pdf_bytes in archivos_bytes.items():
                movimientos = extraer_movimientos_candidatos(
                    pdf_bytes=pdf_bytes,
                    nombre_archivo=nombre_archivo,
                    objetivo=objetivo
                )
                todos_los_movimientos.extend(movimientos)

            objetivo_centavos = monto_a_centavos(objetivo)
            opciones = buscar_opciones_sumatoria_misma_fecha(
                todos_los_movimientos,
                objetivo_centavos,
                max_opciones=20
            )

            if not opciones:
                st.error("No se encontraron opciones de sumatoria válidas en un solo día.")
            else:
                st.success(f"Se encontraron {len(opciones)} opción(es) de sumatoria.")
                idx = mostrar_selector_opciones(opciones)
                mostrar_detalle_opcion(opciones[idx], archivos_bytes)
