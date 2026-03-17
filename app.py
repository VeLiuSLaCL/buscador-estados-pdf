import re
import fitz
import streamlit as st

# Configuración inicial de la página
st.set_page_config(page_title="Buscador de Montos Pro", layout="wide")
st.title("🔍 Buscador de montos y sumas consecutivas")

# =========================================================
# Funciones de Utilidad
# =========================================================

def normalizar_texto(texto):
    return " ".join(texto.split()) if texto else ""

def convertir_monto(texto):
    if not texto: return None
    try:
        # Limpia símbolos y espacios para convertir a float
        limpio = texto.replace("$", "").replace(",", "").strip()
        return float(limpio)
    except ValueError:
        return None

def monto_a_centavos(monto):
    """Evita errores de redondeo de punto flotante usando enteros."""
    return int(round(monto * 100))

def extraer_fecha(linea):
    # Busca formato DD-MMM-AAAA (ej. 15-MAR-2024)
    m = re.search(r"\b\d{2}-[A-Z]{3}-\d{4}\b", linea.upper())
    return m.group(0) if m else None

# =========================================================
# Procesamiento de PDF y Renglones
# =========================================================

def extraer_movimientos_pdf(pdf_bytes, nombre_archivo):
    """Extrae renglones del PDF manteniendo el orden visual y detectando montos."""
    movimientos = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            for num_pag, pagina in enumerate(doc, start=1):
                # Extraer palabras agrupadas en bloques de texto
                bloques = pagina.get_text("dict")["blocks"]
                
                lineas_temp = []
                for b in bloques:
                    if "lines" in b:
                        for l in b["lines"]:
                            # Unir spans de texto en una sola línea
                            texto_linea = "".join([s["text"] for s in l["spans"]])
                            bbox = l["bbox"] # (x0, y0, x1, y1)
                            lineas_temp.append({
                                "y0": bbox[1],
                                "y1": bbox[3],
                                "x0": bbox[0],
                                "x1": bbox[2],
                                "texto": texto_linea,
                                "pagina": num_pag
                            })
                
                # Ordenar líneas de la página por su posición vertical (Y)
                lineas_temp.sort(key=lambda x: x["y0"])

                for linea in lineas_temp:
                    # Buscar patrones de montos financieros (ej: 1,234.50 o 1234.50)
                    hallazgos = re.findall(r"(\d{1,3}(?:,\d{3})*\.\d{2})", linea["texto"])
                    for h in hallazgos:
                        valor = convertir_monto(h)
                        if valor and valor > 0:
                            movimientos.append({
                                "archivo": nombre_archivo,
                                "pagina": linea["pagina"],
                                "texto": normalizar_texto(linea["texto"]),
                                "monto": valor,
                                "monto_texto": h,
                                "centavos": monto_a_centavos(valor),
                                "bbox": (linea["x0"], linea["y0"], linea["x1"], linea["y1"]),
                                "fecha": extraer_fecha(linea["texto"]) or f"Pág {num_pag}"
                            })
    except Exception as e:
        st.error(f"Error procesando {nombre_archivo}: {e}")
    return movimientos

def buscar_secuencias_consecutivas(movimientos, objetivo_centavos):
    """Busca renglones seguidos que sumen exactamente el monto deseado."""
    resultados = []
    n = len(movimientos)
    
    for i in range(n):
        suma_actual = 0
        secuencia = []
        for j in range(i, n):
            # No permitir sumas entre archivos distintos
            if movimientos[j]["archivo"] != movimientos[i]["archivo"]: break
            
            suma_actual += movimientos[j]["centavos"]
            secuencia.append(movimientos[j])
            
            if suma_actual == objetivo_centavos:
                resultados.append({
                    "archivo": movimientos[i]["archivo"],
                    "movimientos": list(secuencia),
                    "total": suma_actual / 100,
                    "es_exacto": len(secuencia) == 1
                })
                break
            elif suma_actual > objetivo_centavos:
                break
    return resultados

# =========================================================
# Recorte Visual
# =========================================================

def obtener_recorte_evidencia(pdf_bytes, lista_movs, zoom=2.0):
    """Genera una imagen del área del PDF donde están los renglones encontrados."""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            m1 = lista_movs[0]
            pagina = doc[m1["pagina"] - 1]
            
            # Definir el rectángulo que abarca todos los movimientos de la secuencia
            y_min = min(m["bbox"][1] for m in lista_movs) - 10
            y_max = max(m["bbox"][3] for m in lista_movs) + 10
            
            # Rectángulo (x0, y0, x1, y1) usando el ancho completo de la página
            rect = fitz.Rect(0, y_min, pagina.rect.width, y_max)
            pix = pagina.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
            return pix.tobytes("png")
    except:
        return None

# =========================================================
# Interfaz de Usuario
# =========================================================

archivos = st.file_uploader("Sube tus estados de cuenta (PDF)", type=["pdf"], accept_multiple_files=True)
monto_objetivo_str = st.text_input("Monto total a buscar", placeholder="Ej: 12500.00")

if st.button("Analizar Renglones"):
    if not archivos or not monto_objetivo_str:
        st.warning("Faltan archivos o el monto de búsqueda.")
    else:
        monto_obj = convertir_monto(monto_objetivo_str)
        if not monto_obj:
            st.error("Monto inválido. Usa formato decimal (100.00)")
        else:
            obj_cts = monto_a_centavos(monto_obj)
            todos_los_datos = []
            archivos_cache = {}

            with st.spinner("Leyendo y ordenando renglones del PDF..."):
                for f in archivos:
                    contenido = f.read()
                    archivos_cache[f.name] = contenido
                    todos_los_datos.extend(extraer_movimientos_pdf(contenido, f.name))

            resultados = buscar_secuencias_consecutivas(todos_los_datos, obj_cts)

            if not resultados:
                st.info("No se encontraron coincidencias exactas ni consecutivas.")
            else:
                st.success(f"Se encontraron {len(resultados)} resultados.")
                for idx, res in enumerate(resultados):
                    etiqueta = "🎯 MONTO EXACTO" if res["es_exacto"] else f"🔗 SUMA DE {len(res['movimientos'])} RENGLONES"
                    with st.expander(f"{etiqueta} | {res['archivo']} | ${res['total']:,.2f}"):
                        
                        # Lista de textos
                        for m in res["movimientos"]:
                            st.write(f"• **Pág {m['pagina']}**: `{m['texto']}`")
                        
                        # Evidencia visual
                        img = obtener_recorte_evidencia(archivos_cache[res['archivo']], res["movimientos"])
                        if img:
                            st.image(img, caption="Fragmento extraído del PDF")
