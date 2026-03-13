import streamlit as st
import fitz

st.title("Buscador de montos en estados de cuenta")

uploaded_pdfs = st.file_uploader(
    "Sube los PDFs",
    accept_multiple_files=True
)

monto = st.text_input("Monto a buscar")

if st.button("Buscar"):

    if not uploaded_pdfs:
        st.warning("Sube al menos un PDF")
    elif not monto:
        st.warning("Escribe un monto")
    else:
        for archivo in uploaded_pdfs:

            pdf = fitz.open(stream=archivo.read(), filetype="pdf")

            for pagina in pdf:
                texto = pagina.get_text()

                if monto in texto:
                    st.success(f"Monto encontrado en {archivo.name}")
