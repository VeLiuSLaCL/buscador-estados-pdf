import re
import fitz
import streamlit as st


st.set_page_config(page_title="Buscador de montos", layout="wide")
st.title("Buscador de montos en estados de cuenta")


def normalizar_texto(texto):
    return " ".join(texto.split())


def buscar_lineas_con_monto(pdf_bytes, nombre_archivo, monto_busqueda):

    resultados = []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        return [{"archivo": nombre_archivo, "error": f"No se pudo abrir el PDF: {e}"}]

    for num_pagina, pagina in enumerate(doc, start=1):

        texto_pagina = pagina.get_text("text")

        if not texto_pagina:
            continue

        if monto_busqueda not in texto_pagina:
            continue

        lineas = texto_pagina.split("\n")

        for linea in lineas:

            if monto_busqueda in linea:

                resultados.append({
                    "archivo": nombre_archivo,
                    "pagina": num_pagina,
                    "linea": normalizar_texto(linea)
                })

    return resultados


def generar_recorte_monto(pdf_bytes, numero_pagina, monto_busqueda, zoom=3.0):
    """
    Genera un recorte horizontal tipo renglón:
    desde el inicio de la hoja hasta un poco después del monto.
    """

    try:

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pagina = doc[numero_pagina - 1]

        coincidencias = pagina.search_for(monto_busqueda)

        if not coincidencias:
            return None

        rect = coincidencias[0]

        # Ajustes del recorte
        margen_superior = 6
        margen_inferior = 6

        inicio_x = 0
        fin_x = min(pagina.rect.width, rect.x1 + 40)

        clip = fitz.Rect(
            inicio_x,
            max(0, rect.y0 - margen_superior),
            fin_x,
            min(pagina.rect.height, rect.y1 + margen_inferior),
        )

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

            st.error("No se encontró el monto en ninguno de los archivos.")

        else:

            st.success(f"Se encontraron {len(resultados_totales)} coincidencia(s).")

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
