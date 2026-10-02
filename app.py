import io
import math
import os
import re
import tempfile
from datetime import datetime

import pandas as pd
import streamlit as st
from PIL import Image, ImageDraw, ImageFont
import qrcode
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.pagesizes import A4, landscape, portrait
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from barcode import Code128 as PyBarcodeCode128
from barcode.writer import ImageWriter

st.set_page_config(page_title='JC Generador de Códigos', page_icon='🏷️', layout='wide')

CODE_TYPES = [
    'CODE128', 'CODE128A', 'CODE128B', 'CODE128C', 'CODE39', 'CODE39Extended',
    'CODE93', 'CODE93Extended', 'EAN13', 'EAN8', 'UPCA', 'ISBN', 'I2of5',
    'Codabar', 'MSI', 'POSTNET', 'QR CODE', 'CONTENIDO LIBRE (QR)'
]
REPORTLAB_MAP = {
    'CODE128': 'Code128', 'CODE128A': 'Code128', 'CODE128B': 'Code128', 'CODE128C': 'Code128',
    'CODE39': 'Standard39', 'CODE39Extended': 'Extended39', 'CODE93': 'Standard93',
    'CODE93Extended': 'Extended93', 'EAN13': 'EAN13', 'EAN8': 'EAN8', 'UPCA': 'UPCA',
    'ISBN': 'ISBN', 'I2of5': 'I2of5', 'Codabar': 'Codabar', 'MSI': 'MSI', 'POSTNET': 'POSTNET'
}


def clean_filename(s):
    s = str(s or '').strip()
    s = re.sub(r'[\\/:*?"<>|]+', '_', s)
    return s or 'codigo'


def font(size, bold=False):
    candidates = []
    if bold:
        candidates += ['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 'C:/Windows/Fonts/arialbd.ttf']
    candidates += ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf']
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=max(8, int(size)))
    return ImageFont.load_default()


def _normalize_barcode_value(tipo, value):
    """Valida/normaliza el contenido para cada estándar."""
    value = str(value).strip()
    if not value:
        raise ValueError('El código no puede estar vacío.')

    numeric = ''.join(ch for ch in value if ch.isdigit())
    if tipo == 'EAN13':
        if len(value) not in (12, 13) or not value.isdigit():
            raise ValueError('EAN13 requiere 12 dígitos (el dígito de control se calcula) o 13 dígitos válidos.')
        if len(value) == 12:
            # ReportLab calcula el dígito de control cuando recibe 12 dígitos.
            value = value
    elif tipo == 'EAN8':
        if len(value) not in (7, 8) or not value.isdigit():
            raise ValueError('EAN8 requiere 7 dígitos (el dígito de control se calcula) o 8 dígitos válidos.')
    elif tipo == 'UPCA':
        if len(value) not in (11, 12) or not value.isdigit():
            raise ValueError('UPC-A requiere 11 dígitos (el dígito de control se calcula) o 12 dígitos válidos.')
    elif tipo == 'I2of5':
        if not value.isdigit() or len(value) % 2:
            raise ValueError('Interleaved 2 of 5 requiere una cantidad par de dígitos.')
    elif tipo == 'POSTNET':
        if not value.isdigit() or len(value) not in (5, 9, 11):
            raise ValueError('POSTNET requiere 5, 9 u 11 dígitos.')
    elif tipo == 'CODE128C':
        if not value.isdigit() or len(value) % 2:
            raise ValueError('CODE128C requiere únicamente dígitos y una cantidad par de caracteres.')
    elif tipo in ('CODE39', 'CODE39Extended'):
        if tipo == 'CODE39' and not re.fullmatch(r'[0-9A-Z .\-$/+%]*', value):
            raise ValueError('CODE39 admite A-Z, 0-9, espacio y - . $ / + %.')
    elif tipo in ('CODE93', 'CODE93Extended'):
        if any(ord(ch) < 32 or ord(ch) > 127 for ch in value):
            raise ValueError('CODE93 admite caracteres ASCII imprimibles.')
    elif tipo == 'Codabar':
        if not re.fullmatch(r'[A-Da-d][0-9\-\$:/.+]+[A-Da-d]', value):
            raise ValueError('Codabar debe iniciar y terminar con A, B, C o D.')
    elif tipo == 'ISBN':
        compact = re.sub(r'[- ]', '', value)
        if not (len(compact) in (10, 13) and (compact[:-1].isdigit() and (compact[-1].isdigit() or compact[-1] in 'Xx'))):
            raise ValueError('ISBN debe tener 10 o 13 caracteres válidos.')
        value = compact
    elif tipo == 'MSI':
        if not value.isdigit():
            raise ValueError('MSI requiere únicamente dígitos.')
    elif tipo in ('CODE128', 'CODE128A', 'CODE128B', 'CODE39Extended', 'CODE93Extended'):
        if any(ord(ch) > 127 for ch in value):
            raise ValueError('Este tipo admite caracteres ASCII; evita tildes y caracteres especiales.')
    return value


def barcode_pil(tipo, value, width_px, height_px, show_value=True):
    value = _normalize_barcode_value(tipo, value)

    if tipo in ('QR CODE', 'CONTENIDO LIBRE (QR)'):
        qr = qrcode.QRCode(version=None, box_size=10, border=2)
        qr.add_data(value)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white').convert('RGB')
        side = max(80, int(min(width_px, height_px)))
        return img.resize((side, side), Image.Resampling.LANCZOS)

    # Preferimos python-barcode para los tipos 1D que soporta. Así la app
    # NO depende de renderPM/rlPyCairo para generar la vista previa.
    # Esto elimina el error típico: "cannot import desired renderPM backend rlPyCairo".
    python_barcode_types = {
        'CODE128': 'code128',
        'CODE39': 'code39',
        'EAN13': 'ean13',
        'EAN8': 'ean8',
        'UPCA': 'upc',
        'ISBN': 'isbn13',
        'I2of5': 'interleaved2of5',
    }
    if tipo in python_barcode_types:
        module_name = python_barcode_types[tipo]
        module = PyBarcodeCode128
        if module_name != 'code128':
            try:
                import barcode as barcode_pkg
                module = barcode_pkg.get_barcode_class(module_name)
            except Exception:
                module = None
        if module is not None:
            writer = ImageWriter()
            options = {
                'write_text': False,
                'module_width': 0.28,
                'module_height': max(8, height_px / 7.0),
                'quiet_zone': 2.0,
                'dpi': 300,
            }
            try:
                obj = module(value, writer=writer)
                png = io.BytesIO()
                obj.write(png, options=options)
                png.seek(0)
                return Image.open(png).convert('RGB')
            except Exception:
                pass

    # Para los estándares restantes usamos ReportLab directamente.
    # Si el backend de renderizado no está instalado, mostramos un mensaje
    # claro en la etiqueta en lugar de romper toda la aplicación.
    report_code = REPORTLAB_MAP.get(tipo, 'Code128')
    try:
        drawing = createBarcodeDrawing(
            report_code,
            value=value,
            width=max(50, width_px),
            height=max(25, height_px),
            humanReadable=False,
        )
        try:
            from reportlab.graphics import renderPM
            png = renderPM.drawToString(drawing, fmt='PNG', dpi=300)
            return Image.open(io.BytesIO(png)).convert('RGB')
        except Exception as render_error:
            raise RuntimeError(
                'Este tipo de código requiere renderPM. Instala rlPyCairo con: pip install rlPyCairo'
            ) from render_error
    except Exception:
        raise


def make_label(tipo, codigo, titulo, descripcion, ancho_mm, alto_mm, codigo_ancho_mm, codigo_alto_mm,
               mostrar_titulo, mostrar_codigo, mostrar_descripcion, fuente_pt):
    # Renderizamos a alta resolución para que las barras y el texto salgan nítidos
    # tanto en la vista previa como al imprimir el PDF.
    dpi = 200
    W = max(100, round(ancho_mm / 25.4 * dpi))
    H = max(80, round(alto_mm / 25.4 * dpi))
    img = Image.new('RGB', (W, H), 'white')
    draw = ImageDraw.Draw(img)
    scale = dpi / 72

    f_title = font(fuente_pt * scale, True)
    # El código y la descripción tienen tamaños ligeramente mayores para mejorar
    # la lectura a distancia y al imprimir.
    f_code = font(max(fuente_pt * scale * 1.05, 12 * scale), True)
    f_desc = font(max(fuente_pt * scale * 0.90, 10 * scale))
    f_error = font(max(8, fuente_pt * scale * 0.82))

    margin_x = max(10, int(W * 0.025))
    y = max(8, int(H * 0.025))

    # TÍTULO
    if mostrar_titulo and titulo:
        bbox = draw.textbbox((0, 0), str(titulo), font=f_title)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(((W - tw) / 2, y), str(titulo), fill='black', font=f_title)
        y += th + max(3, int(scale * 2))

    # Reservamos solamente el espacio realmente necesario para el contenido que
    # va debajo del código. Así la descripción queda mucho más cerca del código.
    code_text_h = 0
    if mostrar_codigo and codigo:
        bb = draw.textbbox((0, 0), str(codigo), font=f_code)
        code_text_h = bb[3] - bb[1]

    desc_h = 0
    if mostrar_descripcion and descripcion:
        bb = draw.textbbox((0, 0), str(descripcion), font=f_desc)
        desc_h = bb[3] - bb[1]

    gap = max(3, int(scale * 2))
    bottom_reserved = code_text_h + desc_h + (gap * 2 if (mostrar_codigo and codigo and mostrar_descripcion and descripcion) else gap) + margin_x
    available_h = max(35, H - y - bottom_reserved)

    code_h = min(int(codigo_alto_mm / 25.4 * dpi), available_h)
    code_w = min(int(codigo_ancho_mm / 25.4 * dpi), W - (margin_x * 2))
    code_w = max(80, code_w)
    code_h = max(30, code_h)

    try:
        # Para códigos de barras 1D generamos las barras sin texto incorporado.
        # El texto se dibuja aparte, más grande y nítido.
        bc = barcode_pil(tipo, codigo, code_w, code_h, False if tipo not in ('QR CODE', 'CONTENIDO LIBRE (QR)') else mostrar_codigo)
        if tipo in ('QR CODE', 'CONTENIDO LIBRE (QR)'):
            side = min(W - margin_x * 2, max(40, code_w), max(40, code_h))
            bc = bc.resize((side, side), Image.Resampling.LANCZOS)
        else:
            # Hacemos que el código ocupe realmente el ancho solicitado.
            # Esto evita que quede demasiado estrecho dentro de la etiqueta.
            bc = bc.resize((code_w, min(code_h, bc.height)), Image.Resampling.LANCZOS)

        x = (W - bc.width) // 2
        img.paste(bc, (x, y))
        y = y + bc.height + gap

        # TEXTO DEL CÓDIGO: separado del gráfico para que sea más claro.
        if mostrar_codigo and codigo and tipo not in ('QR CODE', 'CONTENIDO LIBRE (QR)'):
            bbox = draw.textbbox((0, 0), str(codigo), font=f_code)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            draw.text(((W - tw) / 2, y), str(codigo), fill='black', font=f_code)
            y += th + gap

        # DESCRIPCIÓN: inmediatamente después del código, sin dejarla pegada
        # al borde inferior como ocurría antes.
        if mostrar_descripcion and descripcion:
            text = str(descripcion)
            bbox = draw.textbbox((0, 0), text, font=f_desc)
            tw = bbox[2] - bbox[0]
            draw.text(((W - tw) / 2, y), text, fill='black', font=f_desc)

    except Exception as e:
        msg = str(e)[:70]
        draw.text((margin_x, y), 'Código no válido', fill='black', font=f_error)
        draw.text((margin_x, y + max(12, int(f_error.size * 1.2))), msg, fill='black', font=f_error)

    draw.rectangle((0, 0, W - 1, H - 1), outline='black', width=max(2, int(dpi / 100)))
    return img


def png_bytes(img):
    b = io.BytesIO(); img.save(b, format='PNG', dpi=(300, 300)); return b.getvalue()


def _page_grid(ancho_mm, alto_mm, orientacion='Vertical', columnas=0, margen_mm=10):
    page = landscape(A4) if orientacion == 'Horizontal' else portrait(A4)
    pw, ph = page
    usable_w = pw - 2 * margen_mm * mm
    usable_h = ph - 2 * margen_mm * mm
    max_cols = int(usable_w // (ancho_mm * mm))
    max_rows = int(usable_h // (alto_mm * mm))
    if max_cols < 1:
        raise ValueError(
            f'La etiqueta mide {ancho_mm:.1f} mm de ancho y no cabe en A4 {orientacion.lower()} con margen de {margen_mm} mm.'
        )
    if max_rows < 1:
        raise ValueError(
            f'La etiqueta mide {alto_mm:.1f} mm de alto y no cabe en A4 {orientacion.lower()} con margen de {margen_mm} mm.'
        )
    requested = int(columnas or 0)
    cols = max_cols if requested <= 0 else requested
    if cols > max_cols:
        raise ValueError(
            f'Con etiquetas de {ancho_mm:.0f} mm de ancho caben como máximo {max_cols} columna(s) en A4 {orientacion.lower()}. Reduce el ancho o cambia la orientación.'
        )
    return page, cols, max_rows, max_cols


def pdf_label_bytes(img, ancho_mm, alto_mm, copias=1, orientacion='Vertical', columnas=0):
    b = io.BytesIO()
    page, cols, rows, _ = _page_grid(ancho_mm, alto_mm, orientacion, columnas)
    c = canvas.Canvas(b, pagesize=page)
    pw, ph = page
    ew, eh = ancho_mm*mm, alto_mm*mm
    total_per_page = cols*rows
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp.write(png_bytes(img)); path=tmp.name
    try:
        for n in range(max(1, int(copias))):
            idx = n % total_per_page
            row, col = divmod(idx, cols)
            x = 10*mm + col*ew
            y = ph-10*mm-(row+1)*eh
            c.drawImage(path, x, y, width=ew, height=eh, preserveAspectRatio=False, mask='auto')
            if idx == total_per_page-1 or n == int(copias)-1:
                c.showPage()
        c.save()
    finally:
        try: os.unlink(path)
        except OSError: pass
    return b.getvalue(), cols, rows


def mass_pdf_bytes(items, settings):
    b = io.BytesIO()
    page, cols, rows_page, _ = _page_grid(settings['ancho'], settings['alto'], settings['orientacion'], settings['columnas'])
    c = canvas.Canvas(b, pagesize=page)
    pw, ph = page
    ew, eh = settings['ancho']*mm, settings['alto']*mm
    i = 0
    with tempfile.TemporaryDirectory() as td:
        for r in items:
            img = make_label(
                settings['tipo'], r['codigo'], r.get('titulo',''), r.get('descripcion',''),
                settings['ancho'], settings['alto'], settings['codigo_ancho'], settings['codigo_alto'],
                settings['mostrar_titulo'], settings['mostrar_codigo'], settings['mostrar_descripcion'],
                settings['fuente'])
            p = os.path.join(td, f'{i}.png')
            img.save(p)
            copies = max(1, int(r.get('copias', 1) or 1))
            for _ in range(copies):
                pos = i % (cols * rows_page)
                row, col = divmod(pos, cols)
                c.drawImage(p, 10*mm + col*ew, ph - 10*mm - (row+1)*eh,
                            width=ew, height=eh, mask='auto')
                i += 1
                if i % (cols * rows_page) == 0:
                    c.showPage()
        if i and i % (cols * rows_page) != 0:
            c.showPage()
    c.save()
    return b.getvalue(), cols, rows_page


def max_columns_for_a4(ancho_mm, orientacion, margen_mm=10):
    page = landscape(A4) if orientacion == 'Horizontal' else portrait(A4)
    pw, _ = page
    usable_w = pw - 2 * margen_mm * mm
    return max(1, int(usable_w // (ancho_mm * mm)))


def settings_panel(prefix='main'):
    c1,c2,c3=st.columns(3)
    with c1:
        tipo=st.selectbox('Tipo de código', CODE_TYPES, key=f'{prefix}_tipo')
        codigo=st.text_input('Código / contenido', '123456789012', key=f'{prefix}_codigo')
        if tipo == 'CONTENIDO LIBRE (QR)':
            st.caption('Acepta cualquier contenido: texto, números, guiones, URLs, correos, etc. No requiere formato numérico.')
        elif tipo == 'CODE128':
            st.caption('CODE128 acepta letras, números, espacios y guiones. Ejemplo válido: L-PALLET-001.')
        titulo=st.text_input('Título', 'JC ALMACÉN', key=f'{prefix}_titulo')
        descripcion=st.text_input('Descripción', 'Producto de ejemplo', key=f'{prefix}_desc')
    with c2:
        ancho=st.number_input('Ancho de etiqueta (mm)', 10.0, 300.0, 100.0, 1.0, key=f'{prefix}_ancho')
        alto=st.number_input('Alto de etiqueta (mm)', 10.0, 300.0, 50.0, 1.0, key=f'{prefix}_alto')
        codigo_ancho=st.number_input('Ancho del código (mm)', 10.0, 290.0, 90.0, 1.0, key=f'{prefix}_cw')
        codigo_alto=st.number_input('Alto del código (mm)', 5.0, 200.0, 25.0, 1.0, key=f'{prefix}_ch')
    with c3:
        fuente=st.number_input('Tamaño de fuente (pt)', 6.0, 40.0, 12.0, 1.0, key=f'{prefix}_font')
        copias=st.number_input('Copias para PDF', 1, 5000, 1, 1, key=f'{prefix}_copies')
        orientacion=st.radio('Orientación', ['Vertical','Horizontal'], horizontal=True, key=f'{prefix}_orient')
        max_cols_ui = max_columns_for_a4(ancho, orientacion)
        columnas=st.number_input('Columnas por hoja A4', 1, max_cols_ui, min(1, max_cols_ui), 1, key=f'{prefix}_cols', help=f'Con {ancho:.0f} mm de ancho caben como máximo {max_cols_ui} columna(s) en A4 {orientacion.lower()}.')
        mostrar_titulo=st.checkbox('Mostrar título', True, key=f'{prefix}_mt')
        mostrar_codigo=st.checkbox('Mostrar código', True, key=f'{prefix}_mc')
        mostrar_descripcion=st.checkbox('Mostrar descripción', True, key=f'{prefix}_md')
    return locals()


def download_buttons(img, name, settings):
    st.download_button('⬇️ Descargar PNG', png_bytes(img), file_name=f'{clean_filename(name)}.png', mime='image/png')
    pdf,cols,rows=pdf_label_bytes(img, settings['ancho'], settings['alto'], settings['copias'], settings['orientacion'], settings.get('columnas', 0))
    st.download_button(f'⬇️ PDF A4 ({cols} × {rows} etiquetas/hoja)', pdf, file_name=f'{clean_filename(name)}.pdf', mime='application/pdf')


def page_individual():
    st.title('🔲 Generar código')
    st.caption('Generación individual de códigos de barras y QR.')
    st.info('💡 Si necesitas codificar cualquier contenido sin restricciones de formato, selecciona **CONTENIDO LIBRE (QR)**. Para códigos de barras tradicionales, el contenido debe respetar las reglas de cada estándar.')
    s=settings_panel('ind')
    try:
        img=make_label(s['tipo'],s['codigo'],s['titulo'],s['descripcion'],s['ancho'],s['alto'],s['codigo_ancho'],s['codigo_alto'],s['mostrar_titulo'],s['mostrar_codigo'],s['mostrar_descripcion'],s['fuente'])
        a,b=st.columns([1,1])
        with a: st.image(img, caption='Vista previa', use_container_width=True)
        with b:
            st.success('Etiqueta lista para generar.')
            download_buttons(img,s['codigo'],s)
    except Exception as e:
        st.error(f'No se pudo generar: {e}')


def page_designer():
    st.title('🎨 Diseñador de etiquetas')
    st.caption('Diseña una etiqueta en milímetros y exporta a PNG o PDF A4.')
    s=settings_panel('des')
    try:
        img=make_label(s['tipo'],s['codigo'],s['titulo'],s['descripcion'],s['ancho'],s['alto'],s['codigo_ancho'],s['codigo_alto'],s['mostrar_titulo'],s['mostrar_codigo'],s['mostrar_descripcion'],s['fuente'])
        st.image(img, caption=f"Vista previa · {s['ancho']} × {s['alto']} mm", width=600)
        download_buttons(img,s['codigo'],s)
    except Exception as e: st.error(str(e))


def page_massive():
    st.title('📦 Generación masiva')
    st.caption('Carga un Excel y genera todas las etiquetas en un solo PDF.')
    st.info('💡 Para valores totalmente libres, selecciona **CONTENIDO LIBRE (QR)** como tipo de código.')
    st.markdown('**Columnas mínimas:** `codigo`. Opcionales: `titulo`, `descripcion`, `copias`.')
    template=pd.DataFrame([{'codigo':'123456789012','titulo':'JC ALMACÉN','descripcion':'Producto de ejemplo','copias':1}])
    tb=io.BytesIO(); template.to_excel(tb, index=False, engine='openpyxl'); tb.seek(0)
    st.download_button('📄 Descargar plantilla Excel', tb.getvalue(), file_name='PLANTILLA_CODIGOS.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    up=st.file_uploader('Sube tu archivo Excel', type=['xlsx','xls'])
    if not up: return
    try:
        df=pd.read_excel(up)
        df.columns=[str(x).strip().lower() for x in df.columns]
        if 'codigo' not in df.columns: st.error('El Excel debe tener una columna llamada codigo.'); return
        st.dataframe(df, use_container_width=True, height=280)
        tipo=st.selectbox('Tipo de código', CODE_TYPES, key='mass_tipo')
        c1,c2,c3=st.columns(3)
        with c1:
            ancho=st.number_input('Ancho (mm)',10.,300.,100.,1.,key='mass_w'); alto=st.number_input('Alto (mm)',10.,300.,50.,1.,key='mass_h')
        with c2:
            cw=st.number_input('Ancho código (mm)',10.,290.,90.,1.,key='mass_cw'); ch=st.number_input('Alto código (mm)',5.,200.,25.,1.,key='mass_ch')
        with c3:
            fuente=st.number_input('Fuente (pt)',6.,40.,12.,1.,key='mass_font'); orient=st.radio('Orientación',['Vertical','Horizontal'],horizontal=True,key='mass_o')
            max_cols_mass = max_columns_for_a4(ancho, orient)
            columnas=st.number_input('Columnas por hoja A4',1,max_cols_mass,min(1,max_cols_mass),1,key='mass_cols')
        mt=st.checkbox('Mostrar título',True,key='mass_mt'); mc=st.checkbox('Mostrar código',True,key='mass_mc'); md=st.checkbox('Mostrar descripción',True,key='mass_md')
        if st.button('🚀 GENERAR PDF MASIVO', type='primary'):
            rows=[]
            for _,r in df.iterrows():
                rows.append({'codigo':str(r['codigo']).strip(), 'titulo':str(r.get('titulo','') if pd.notna(r.get('titulo','')) else ''), 'descripcion':str(r.get('descripcion','') if pd.notna(r.get('descripcion','')) else ''), 'copias':int(r.get('copias',1) if pd.notna(r.get('copias',1)) else 1)})
            pdf,cols,rows_page=mass_pdf_bytes(rows,{'tipo':tipo,'ancho':ancho,'alto':alto,'codigo_ancho':cw,'codigo_alto':ch,'fuente':fuente,'orientacion':orient,'columnas':columnas,'mostrar_titulo':mt,'mostrar_codigo':mc,'mostrar_descripcion':md})
            st.success(f'PDF generado. Distribución aproximada: {cols} × {rows_page} etiquetas por hoja.')
            st.download_button('⬇️ DESCARGAR PDF MASIVO',pdf,file_name=f'ETIQUETAS_MASIVAS_{datetime.now():%Y%m%d_%H%M%S}.pdf',mime='application/pdf')
    except Exception as e:
        st.error(f'No se pudo leer o procesar el Excel: {e}')


def page_home():
    st.title('🏷️ JC Generador de Códigos')
    st.markdown('### Sistema web para generar códigos, diseñar etiquetas y crear PDFs.')
    a,b,c=st.columns(3)
    a.metric('Generación individual','PNG + PDF')
    b.metric('Diseñador','Medidas en mm')
    c.metric('Masivo','Desde Excel')
    st.info('Selecciona una opción en el menú lateral para comenzar.')

with st.sidebar:
    st.markdown('## 🏷️ JC CÓDIGOS')
    page=st.radio('MENÚ',['🏠 Portada','🔲 Generar código','📦 Generación masiva','🎨 Diseñador de etiquetas'])
    st.divider(); st.caption('Versión Streamlit 1.0')

if page=='🏠 Portada': page_home()
elif page=='🔲 Generar código': page_individual()
elif page=='📦 Generación masiva': page_massive()
else: page_designer()
