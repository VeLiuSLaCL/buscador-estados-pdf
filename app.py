import re

import fitz
import streamlit as st


st.set_page_config(page_title="Buscador de montos", layout="wide")
st.title("Buscador de montos en estados de cuenta")


# =========================================================
# Utilidades base
# =========================================================

def normalizar_texto(texto):
    return " ".join(texto.split())


def normalizar_monto_texto(texto):
    return texto.replace(" ", "").replace(",", "").strip()


def convertir_monto(texto):
    try:
        return float(texto.replace(",", "").strip())
    except ValueError:
        return None


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


def linea_es_abono(texto):
    texto = texto.upper()
    texto = " ".join(texto.split())

    patrones = [
        r"\bABO\b",
        r"\bABONO\b",
        r"\bA\s*B\s*O\b",
        r"\bA\s*B\s*O\s*N\s*O\b",
    ]

    return any(re.search(patron, texto) for patron in patrones)


# =========================================================
# Agrupar palabras por línea
# =========================================================

def obtener_lineas_desde_pagina(pagina, tolerancia_y=3):
    palabras = pagina.get_text("words")
    if not palabras:
        return []

    palabras = sorted(palabras, key=lambda w: (round(w[1], 1), w[0]))

    lineas = []

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

    return sorted(lineas, key=lambda l: l["y0"])


# =========================================================
# Búsqueda exacta
# =========================================================

def buscar_lineas_con_monto(pdf_bytes, nombre_archivo, monto_busqueda):
    resultados = []
    monto_normalizado = normalizar_monto_texto(monto_busqueda)

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return [{"archivo": nombre_archivo, "error": f"No se pudo abrir el PDF: {e}"}]

    for num_pagina, pagina in enumerate(doc, start=1):
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

            contexto = []
            if i > 0:
                contexto.append(lineas[i - 1])
            contexto.append(linea)
            if i + 1 < len(lineas):
                contexto.append(lineas[i + 1])

            texto_contexto = " ".join(contexto)

            # Se excluyen líneas que parezcan abonos
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


# =========================================================
# Recorte dinámico
# =========================================================

def generar_recorte_monto(pdf_bytes, numero_pagina, monto_busqueda, zoom=3.0):
    """
    Recorte dinámico del movimiento completo.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pagina = doc[numero_pagina - 1]

        lineas = obtener_lineas_desde_pagina(pagina)
        if not lineas:
            return None

        monto_normalizado = normalizar_monto_texto(monto_busqueda)

        indice_base = None
        for i, linea in enumerate(lineas):
            if monto_normalizado in normalizar_monto_texto(linea["texto"]):
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
            pix = pagina.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
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
        pix = pagina.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)

        return pix.tobytes("png")

    except Exception:
        return None


# =========================================================
# Render
# =========================================================

def mostrar_resultados_exactos(resultados_totales, archivos_bytes, monto_busqueda):
    st.success(f"Se encontraron {len(resultados_totales)} coincidencia(s) exactas válidas.")

    for i, resultado in enumerate(resultados_totales, start=1):
        if "error" in resultado:
            st.error(f"{resultado['archivo']}: {resultado['error']}")
            continue

        with st.container():
            st.markdown(f"### Coincidencia #{i}")
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
                    width="content"
                )

            st.divider()


# =========================================================
# UI principal
# =========================================================

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
        errores = [r for r in resultados_exactos if "error" in r]

        for err in errores:
            st.error(f"{err['archivo']}: {err['error']}")

        if exactos_validos:
            mostrar_resultados_exactos(exactos_validos, archivos_bytes, monto_busqueda.strip())
        else:
            st.info("No se encontró ese monto exacto en los PDFs cargados.")
