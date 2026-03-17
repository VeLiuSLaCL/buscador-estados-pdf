import re
from collections import defaultdict
import fitz
import streamlit as st

# Configuración de página
st.set_page_config(page_title="Buscador de Montos Pro", layout="wide")
st.title("🔍 Buscador de montos y sumas consecutivas")

# =========================================================
# 1. Utilidades de Procesamiento y Normalización
# =========================================================

def normalizar_texto(texto):
    return " ".join(texto.split())

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
    m = re.search(r"\b\d{2}-[A-Z]{3}-\d{4}\b", linea.upper())
    if m: return m.group(0)
    return None

def extraer_folio(linea):
    m = re.search(r"\b\d{6,8}\b", linea)
    return m.group(0) if m else "Sin folio"

def es_token_monto(texto):
    texto = texto.strip()
    return re.fullmatch(r"\d{1,3}(?:,\d{3})*\.\d{2}", texto) is not None or \
           re.fullmatch(r"\d+\.\d{2}", texto) is not None

# =========================================================
# 2. Análisis de Estructura de PDF (Columnas y Líneas)
# =========================================================

def obtener_lineas_detalladas(pagina, tolerancia_y=3):
    """Extrae palabras y las agrupa en líneas basadas en su posición vertical."""
    palabras = pagina.get_text("words")
    if not palabras: return []
    
    # Ordenar por Y (arriba-abajo) y luego por X (izquierda-derecha)
    palabras = sorted(palabras, key=lambda w: (round(w[1], 1), w[0]))
    lineas = []

    for w in palabras:
        x0, y0, x1, y1, txt = w[:5]
        asignada = False
        for linea in lineas:
            if abs(linea["y_ref"] - y0) <= tolerancia_y:
                linea["words"].append(w)
                asignada = True
                break
        if not asignada:
            lineas.append({"y_ref": y0, "words": [w], "y0": y0, "y1": y1})

    for linea in lineas:
        linea["words"].sort(key=lambda w: w[0])
        linea["texto"] = " ".join(w[4] for w in linea["words"])
        linea["x0"] = min(w[0] for w in linea["words"])
        linea["x1"] = max(w[2] for w in linea["words"])
        linea["y1"] = max(w[3] for w in linea["words"])
        
    return lineas

def detectar_columna_retiro(pagina):
    """Detecta el área X donde suelen estar los cargos/retiros."""
    palabras = pagina.get_text("words")
    x_retiro = None
    for w in palabras:
        if w[4].upper() in ["RETIRO", "EGRESO", "CARGO"]:
            x_retiro = (w[0], w[2])
            break
    return x_retiro

# =========================================================
# 3. Lógica de Extracción y Búsqueda Consecutiva
# =========================================================

def extraer_movimientos_limpios(pdf_bytes, nombre_archivo):
    """Analiza el PDF y devuelve una lista plana de movimientos con valor numérico."""
    movimientos = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except: return []

    for num_pag, pagina in enumerate(doc, start=1):
        x_limite = detectar_columna_retiro(pagina)
        lineas = obtener_lineas_detalladas(pagina)
        
        for linea in lineas:
            # Buscamos números con formato decimal
            hallazgos = re.findall(r"(\d{1,3}(?:,\d{3})*\.\d{2})", linea["texto"])
            for h in hallazgos:
                valor = convertir_monto(h)
                if valor and valor > 0:
                    movimientos.append({
                        "archivo": nombre_archivo,
                        "pagina": num_pag,
                        "texto": normalizar_texto(linea["texto"]),
                        "monto": valor,
                        "monto_texto": h,
                        "centavos": monto_a_centavos(valor),
                        "bbox": (linea["x0"], linea["y0"], linea["x1"], linea["y1"]),
                        "fecha": extraer_fecha(linea["texto"]) or f"Pág {num_pag}"
                    })
    return movimientos

def buscar_combinaciones_consecutivas(movimientos, objetivo_centavos):
    """
    Algoritmo de Ventana Deslizante: busca si el renglón N + N+1 + ... suma el objetivo.
    """
    resultados = []
    n = len(movimientos)
    
    for i in range(n):
        suma_actual = 0
        secuencia = []
        for j in range(i, n):
            # No sumar movimientos de archivos distintos
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
# 4. Visualización y Recortes
# =========================================================

def generar_recorte_multiple(pdf_bytes, lista_movs, zoom=3.0):
    """Crea una imagen que abarca todos los renglones de una combinación."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        # Asumimos que la secuencia consecutiva está en la misma página o páginas cercanas
        # Para simplificar, recortamos el área de la página del primer movimiento
        m1 = lista_movs[0]
        pag_idx = m1["pagina"] - 1
        pagina = doc[pag_idx]
        
        # Determinar el área que cubre toda la secuencia
        y_min = min(m["bbox"][1] for m in lista_movs) - 5
        y_max = max(m["bbox"][3] for m in lista_movs) + 5
        
        clip = fitz.Rect(0, y_min, pagina.rect.width, y_max)
        pix = pagina.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
        return pix.tobytes("png")
    except: return None

# =========================================================
# 5. Interfaz Principal (Streamlit)
# =========================================================

col_main, _ = st.columns([4, 1])
with col_main:
    uploaded_files = st.file_uploader("Sube tus estados de cuenta (PDF)", type=["pdf"], accept_multiple_files=True)
    monto_str = st.text_input("Monto a buscar o sumar", placeholder="Ej: 1540.50")

if st.button("🚀 Iniciar Búsqueda Inteligente"):
    if not uploaded_files or not monto_str:
        st.error("Por favor, sube archivos y especifica un monto.")
    else:
        objetivo = convertir_monto(monto_str)
        if not objetivo:
            st.error("Monto no válido. Usa el formato 0000.00")
        else:
            obj_cts = monto_a_centavos(objetivo)
            archivos_data = {}
            todos_movs = []
            
            with st.spinner("Analizando renglones consecutivamente..."):
                for f in uploaded_files:
                    f_bytes = f.read()
                    archivos_data[f.name] = f_bytes
                    todos_movs.extend(extraer_movimientos_limpios(f_bytes, f.name))
            
            resultados = buscar_combinaciones_consecutivas(todos_movs, obj_cts)
            
            if not resultados:
                st.warning("No se encontró el monto exacto ni combinaciones consecutivas.")
            else:
                st.success(f"Se encontraron {len(resultados)} posibles coincidencias.")
                
                for idx, res in enumerate(resultados):
                    tipo = "MONTO EXACTO" if res["es_exacto"] else f"SUMA DE {len(res['movimientos'])} RENGLONES"
                    with st.expander(f"📍 {tipo} en {res['archivo']} (Total: ${res['total']:,.2f})"):
                        
                        # Mostrar detalle de texto
                        for m in res["movimientos"]:
                            st.caption(f"Página {m['pagina']} | {m['fecha']}")
                            st.write(f"➡️ `{m['texto']}`")
                        
                        # Mostrar imagen del bloque
                        recorte = generar_recorte_multiple(archivos_data[res['archivo']], res["movimientos"])
                        if recorte:
                            st.image(recorte, caption="Evidencia visual del documento", use_container_width=False)
                        st.divider()

st.info("Nota: Esta herramienta busca renglones que aparecen uno seguido de otro para garantizar la validez contable.")
