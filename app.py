import fitz
import re
from collections import defaultdict
import streamlit as st

def cargar_pdf(pdf_bytes):
    """Carga un archivo PDF y captura errores al abrir."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        return doc
    except fitz.fitz.FileDataError as e:
        st.error(f"Error al abrir el archivo PDF: {e}")
        return None

def extraer_movimientos(doc):
    """Extracción de movimientos del PDF. Implementa aquí tu lógica."""
    movimientos = []
    # TODO: Implementar la lógica específica para extraer los movimientos del PDF.
    # Puedes utilizar expresiones regulares para encontrar los datos necesarios.
    return movimientos

def validar_datos(movimientos):
    """Realiza validaciones adicionales sobre los movimientos."""
    # TODO: Implementa las validaciones que ya tenías.
    pass

def buscar_opciones_sumatoria_misma_fecha(
    movimientos,
    objetivo_centavos,
    max_opciones=20,
    max_movs_por_fecha=60
):
    grupos = defaultdict(list)

    for mov in movimientos:
        # Asegúrate de validar los datos antes de agrupar.
        grupos[mov["fecha"]].append(mov)

    opciones = []

    for fecha, lista in grupos.items():
        lista = [x for x in lista if x["centavos"] <= objetivo_centavos]
        lista = sorted(lista, key=lambda x: x["centavos"], reverse=True)

        if len(lista) > max_movs_por_fecha:
            continue

        dp = {0: []}
        for idx, mov in enumerate(lista):
            valor = mov["centavos"]
            sums_actuales = list(dp.keys())

            for suma_actual in sums_actuales:
                nueva_suma = suma_actual + valor
                if nueva_suma > objetivo_centavos or nueva_suma in dp:
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
        key=lambda x: (x["cantidad_movimientos"], x["archivo"], x["fecha"])
    )

def main():
    st.title("Aplicación de Extracción y Cálculo de Movimientos")

    pdf_file = st.file_uploader("Sube tu archivo PDF", type="pdf")

    if pdf_file:
        doc = cargar_pdf(pdf_file.read())

        if doc:
            movimientos = extraer_movimientos(doc)
            validar_datos(movimientos)  # Validación de datos

            objetivo_input = st.number_input("Ingresa el monto objetivo en centavos:", min_value=0)
            
            if st.button("Buscar combinaciones"):
                opciones = buscar_opciones_sumatoria_misma_fecha(movimientos, objetivo_input)
                
                if opciones:
                    st.success(f"Se encontraron {len(opciones)} combinaciones.")
                    for opcion in opciones:
                        st.write(opcion)
                else:
                    st.warning("No se encontraron combinaciones.")

if __name__ == "__main__":
    main()
