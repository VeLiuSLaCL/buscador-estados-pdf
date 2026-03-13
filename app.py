import re
import fitz
import streamlit as st


st.set_page_config(page_title="Buscador de montos", layout="wide")
st.title("Buscador de montos en estados de cuenta")


def normalizar_texto(texto):
    return " ".join(texto.split())


def linea_es_abono(texto):
    """
    Devuelve True si el texto contiene ABO o ABONO como palabra,
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


def buscar_lineas_con_monto(pdf_bytes, nombre_archivo, monto_busqueda):
    resultados = []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return [{"archivo": nombre_archivo, "error": f"No se pudo abrir el PDF: {e}"}]

    for num_pagina, pagina in enumerate(doc, start=1):
        # Omitir página 1 (resumen)
        if num_pagina == 1:
            continue

        texto_pagina = pagina.get_text("text")
        if not texto_pagina:
            continue

        if monto_busqueda not in texto_pagina:
            continue

        lineas = texto_pagina.split("\n")

        for i, linea in enumerate(lineas):
            if monto_busqueda not in linea:
                continue

            # Revisar contexto: línea anterior + actual + siguiente
            contexto = []

            if i > 0:
                contexto.append(lineas[i - 1])

            contexto.append(linea)

            if i + 1 < len(lineas):
                contexto.append(lineas[i + 1])

            texto_contexto = " ".join(contexto)

            # Excluir si en el contexto aparece ABO o ABONO
            if linea_es_abono(texto_contexto):
                continue

            resultados.append({
                "archivo": nombre_archivo,
                "pagina": num_pagina,
                "linea": normalizar_texto(linea)
            })

    return resultados


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

        # words: (x0, y0, x1, y1, "texto", block_no, line_no, word_no)
        palabras = sorted(palabras, key=lambda w: (round(w[1], 1), w[0]))

        # Agrupar palabras por línea usando tolerancia vertical
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

        # Ordenar palabras dentro de cada línea y construir texto
        for linea in lineas:
            linea["words"] = sorted(linea["words"], key=lambda w: w[0])
            linea["texto"] = " ".join(w[4] for w in linea["words"])
            linea["x0"] = min(w[0] for w in linea["words"])
            linea["x1"] = max(w[2] for w in linea["words"])

        lineas = sorted(lineas, key=lambda l: l["y0"])

        # Encontrar la línea que contiene el monto
        indice_base = None
        for i, linea in enumerate(lineas):
            if monto_busqueda in linea["texto"]:
                indice_base = i
                break

        if indice_base is None:
            # Fallback visual clásico
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

        # Parámetros de recorte
        inicio_x = 20
        fin_x = min(pagina.rect.width, linea_base["x1"] + 120)

        y_inicio = max(0, linea_base["y0"] - 3)
        y_fin = min(pagina.rect.height, linea_base["y1"] + 3)

        patron_fecha = re.compile(r"^\d{2}-[A-Z]{3}-\d{4}\b", re.IGNORECASE)

        # Extender hacia abajo mientras siga siendo parte del mismo movimiento
        for j in range(indice_base + 1, len(lineas)):
            actual = lineas[j]
            anterior = lineas[j - 1]

            texto_actual = actual["texto"].strip()
            gap_vertical = actual["y0"] - anterior["y1"]

            # Si empieza un nuevo movimiento con fecha, detener
            if patron_fecha.search(texto_actual):
                break

            # Si hay mucho espacio vertical en blanco, detener
            if gap_vertical > 10:
                break

            # Si sigue siendo parte del bloque descriptivo, incluir
            y_fin = min(pagina.rect.height, actual["y1"] + 3)
            fin_x = max(fin_x, min(pagina.rect.width, actual["x1"] + 40))

        clip = fitz.Rect(inicio_x, y_inicio, fin_x, y_fin)

        matriz = fitz.Matrix(zoom, zoom)
        pix = pagina.get_pixmap(matrix=matriz, clip=clip, alpha=False)

        return pix.tobytes("png")

    except Exception:
        return None


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
        resultados_totales = []

        with st.spinner("Buscando en los archivos..."):
            for archivo in uploaded_files:
                pdf_bytes = archivo.read()

                resultados = buscar_lineas_con_monto(
                    pdf_bytes,
                    archivo.name,
                    monto_busqueda.strip()
                )

                for r in resultados:
                    if "error" not in r:
                        recorte = generar_recorte_monto(
                            pdf_bytes,
                            r["pagina"],
                            monto_busqueda.strip()
                        )
                        r["recorte"] = recorte

                resultados_totales.extend(resultados)

        if not resultados_totales:
            st.error("No se encontró el monto en ninguno de los archivos con líneas válidas.")
        else:
            st.success(f"Se encontraron {len(resultados_totales)} coincidencia(s) válidas.")

            for i, resultado in enumerate(resultados_totales, start=1):
                if "error" in resultado:
                    st.error(f"{resultado['archivo']}: {resultado['error']}")
                    continue

                with st.container():
                    st.markdown(f"### Coincidencia #{i}")
                    st.write(f"**Archivo:** {resultado['archivo']}")
                    st.write(f"**Página:** {resultado['pagina']}")
                    st.write(f"**Línea:** {resultado['linea']}")

                    if resultado.get("recorte"):
                        st.image(
                            resultado["recorte"],
                            caption=f"Recorte visual de {resultado['archivo']} - página {resultado['pagina']}",
                            use_container_width=False
                        )

                    st.divider()
