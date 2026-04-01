"""
Generador de PDF del catálogo de servicios para revisión de Pilar.
Extrae datos directamente de PostgreSQL y genera un PDF con formato limpio.
"""

import json
import subprocess
import sys
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    HRFlowable,
    PageBreak,
    KeepTogether,
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from datetime import datetime

# ── Colores de marca ──────────────────────────────────────────────────────────
COLOR_PRIMARY = colors.HexColor("#1a1a2e")  # azul oscuro
COLOR_ACCENT = colors.HexColor("#c9a96e")  # dorado
COLOR_SECTION = colors.HexColor("#f5f0e8")  # crema suave para fondos
COLOR_ROW_ALT = colors.HexColor("#fafafa")  # gris muy suave filas alternas
COLOR_BORDER = colors.HexColor("#e0d8cc")  # borde suave

# ── Labels para metadatos ─────────────────────────────────────────────────────
FAMILY_LABELS = {
    "haircut": "Corte",
    "hairstyle": "Peinado / Styling",
    "highlights": "Mechas / Reflejos",
    "color": "Coloración",
    "treatment": "Tratamiento capilar",
    "perm": "Moldeado / Permanente",
    "beard": "Barba / Patillas",
    "facial": "Facial",
    "body_treatment": "Tratamiento corporal",
    "waxing": "Depilación con cera",
    "nails": "Uñas / Manicura / Pedicura",
    "lashes": "Pestañas",
    "brows": "Cejas",
    "massage": "Masaje",
    "makeup": "Maquillaje",
}
AUDIENCE_LABELS = {
    "adult_female": "Mujer adulta",
    "adult_male": "Hombre adulto",
    "child_female": "Niña",
    "child_male": "Niño",
    "baby": "Bebé",
}
HAIR_LENGTH_LABELS = {
    "short_medium": "Corto / medio",
    "long": "Largo",
}
HAIR_DENSITY_LABELS = {
    "normal": "Normal",
    "extra": "Alta densidad / extra",
}
VARIANT_LABELS = {
    "standard": "Estándar",
    "extra": "Extra (más denso/largo)",
    "long": "Versión larga",
}
CATEGORY_LABELS = {
    "HAIRDRESSING": "Peluquería",
    "AESTHETICS": "Estética",
}


def get_services_from_db():
    """Extrae servicios directamente via docker exec psql."""
    query = """
        SELECT
            name,
            category,
            duration_minutes,
            description,
            metadata
        FROM services
        ORDER BY category, name;
    """
    cmd = [
        "docker",
        "exec",
        "atrevete-postgres",
        "psql",
        "-U",
        "atrevete",
        "-d",
        "atrevete_db",
        "-t",
        "-A",
        "-F",
        "\t",  # tab-separated, no headers, no alignment
        "-c",
        query,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR psql: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    services = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t", 4)
        if len(parts) < 5:
            continue
        name, category, duration, description, metadata_raw = parts
        try:
            metadata = json.loads(metadata_raw)
        except json.JSONDecodeError:
            metadata = {}
        services.append(
            {
                "name": name,
                "category": category,
                "duration_minutes": int(duration),
                "description": description,
                "metadata": metadata,
            }
        )
    return services


def build_meta_rows(metadata: dict) -> list[tuple[str, str]]:
    """Convierte el dict metadata en filas (etiqueta, valor) para la tabla."""
    rows = []

    family = metadata.get("family")
    if family:
        rows.append(("Familia", FAMILY_LABELS.get(family, family)))

    variant = metadata.get("variant")
    if variant:
        rows.append(("Variante", VARIANT_LABELS.get(variant, variant)))

    audience = metadata.get("audience")
    if audience:
        rows.append(("Público", AUDIENCE_LABELS.get(audience, audience)))

    hair_length = metadata.get("hair_length")
    if hair_length:
        rows.append(("Longitud de cabello", HAIR_LENGTH_LABELS.get(hair_length, hair_length)))

    hair_density = metadata.get("hair_density")
    if hair_density:
        rows.append(("Densidad de cabello", HAIR_DENSITY_LABELS.get(hair_density, hair_density)))

    ask_if_missing = metadata.get("ask_if_missing", [])
    if ask_if_missing:
        ask_labels = {
            "hair_length": "longitud de cabello",
            "hair_density": "densidad",
            "audience": "público",
        }
        labels = [ask_labels.get(k, k) for k in ask_if_missing]
        rows.append(("El bot preguntará por", ", ".join(labels)))

    disambiguation_tags = metadata.get("disambiguation_tags", [])
    if disambiguation_tags:
        rows.append(("Palabras clave (bot)", ", ".join(disambiguation_tags)))

    combo = metadata.get("combo_recommendations", [])
    if combo:
        rows.append(("Add-ons recomendados (upsell)", ", ".join(combo)))
    else:
        rows.append(("Add-ons recomendados (upsell)", "—"))

    return rows


def build_pdf(output_path: str):
    services = get_services_from_db()
    print(f"  {len(services)} servicios extraídos de la BD")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title="Catálogo de Servicios — Atrévete",
        author="Atrévete Bot",
    )

    styles = getSampleStyleSheet()

    style_title = ParagraphStyle(
        "Title",
        parent=styles["Normal"],
        fontSize=22,
        textColor=COLOR_PRIMARY,
        fontName="Helvetica-Bold",
        spaceAfter=4,
        alignment=TA_CENTER,
    )
    style_subtitle = ParagraphStyle(
        "Subtitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#666666"),
        fontName="Helvetica",
        spaceAfter=2,
        alignment=TA_CENTER,
    )
    style_category = ParagraphStyle(
        "Category",
        parent=styles["Normal"],
        fontSize=14,
        textColor=colors.white,
        fontName="Helvetica-Bold",
        spaceBefore=14,
        spaceAfter=6,
    )
    style_service_name = ParagraphStyle(
        "ServiceName",
        parent=styles["Normal"],
        fontSize=11,
        textColor=COLOR_PRIMARY,
        fontName="Helvetica-Bold",
        spaceBefore=2,
        spaceAfter=2,
    )
    style_description = ParagraphStyle(
        "Description",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#444444"),
        fontName="Helvetica-Oblique",
        spaceAfter=4,
    )
    style_meta_label = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#555555"),
        fontName="Helvetica-Bold",
    )
    style_meta_value = ParagraphStyle(
        "MetaValue",
        parent=styles["Normal"],
        fontSize=8,
        textColor=COLOR_PRIMARY,
        fontName="Helvetica",
    )
    style_note = ParagraphStyle(
        "Note",
        parent=styles["Normal"],
        fontSize=7.5,
        textColor=colors.HexColor("#888888"),
        fontName="Helvetica-Oblique",
        spaceBefore=10,
        alignment=TA_CENTER,
    )

    story = []

    # ── PORTADA ───────────────────────────────────────────────────────────────
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("Atrévete", style_title))
    story.append(Paragraph("Catálogo de Servicios — Revisión de Metadatos", style_subtitle))
    story.append(
        Paragraph(
            f"Generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')} · {len(services)} servicios",
            style_subtitle,
        )
    )
    story.append(Spacer(1, 0.5 * cm))
    story.append(HRFlowable(width="100%", thickness=1.5, color=COLOR_ACCENT, spaceAfter=0.3 * cm))

    # Leyenda
    legend_data = [
        [
            Paragraph("<b>Familia</b>", style_meta_label),
            Paragraph(
                "Agrupación interna del servicio (ej. haircut, color, waxing…)", style_meta_value
            ),
        ],
        [
            Paragraph("<b>Variante</b>", style_meta_label),
            Paragraph(
                "Diferencia dentro de la familia: estándar / extra / larga", style_meta_value
            ),
        ],
        [
            Paragraph("<b>Público</b>", style_meta_label),
            Paragraph("A quién va dirigido (mujer adulta, hombre, niño, bebé…)", style_meta_value),
        ],
        [
            Paragraph("<b>Longitud / Densidad de cabello</b>", style_meta_label),
            Paragraph(
                "Condiciona si el bot ofrece esta opción según el perfil del cliente",
                style_meta_value,
            ),
        ],
        [
            Paragraph("<b>El bot preguntará por</b>", style_meta_label),
            Paragraph(
                "Campos que el bot pedirá si el cliente no los menciona espontáneamente",
                style_meta_value,
            ),
        ],
        [
            Paragraph("<b>Palabras clave (bot)</b>", style_meta_label),
            Paragraph(
                "Términos que el bot reconoce para identificar este servicio", style_meta_value
            ),
        ],
        [
            Paragraph("<b>Add-ons recomendados (upsell)</b>", style_meta_label),
            Paragraph(
                "Servicios complementarios que el bot ofrecerá tras confirmar este servicio",
                style_meta_value,
            ),
        ],
    ]
    legend_table = Table(legend_data, colWidths=[5.5 * cm, 11 * cm])
    legend_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_SECTION),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [COLOR_SECTION, colors.white]),
                ("GRID", (0, 0), (-1, -1), 0.3, COLOR_BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        Paragraph(
            "Guía de columnas",
            ParagraphStyle(
                "LegendTitle",
                parent=styles["Normal"],
                fontSize=9,
                fontName="Helvetica-Bold",
                textColor=COLOR_PRIMARY,
                spaceAfter=4,
            ),
        )
    )
    story.append(legend_table)
    story.append(PageBreak())

    # ── SERVICIOS POR CATEGORÍA ───────────────────────────────────────────────
    current_category = None

    for svc in services:
        category = svc["category"]
        meta = svc["metadata"]

        # Header de categoría
        if category != current_category:
            current_category = category
            cat_label = CATEGORY_LABELS.get(category, category)
            cat_header = Table(
                [[Paragraph(f"  {cat_label}", style_category)]],
                colWidths=[doc.width],
            )
            cat_header.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), COLOR_PRIMARY),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("ROUNDEDCORNERS", [3, 3, 3, 3]),
                    ]
                )
            )
            story.append(cat_header)
            story.append(Spacer(1, 0.2 * cm))

        # Bloque de servicio (mantenemos junto nombre + descripción + tabla)
        meta_rows = build_meta_rows(meta)

        # Header del servicio: nombre + duración
        duration_str = f"{svc['duration_minutes']} min"
        service_header = Table(
            [
                [
                    Paragraph(svc["name"], style_service_name),
                    Paragraph(
                        f"<font color='#c9a96e'><b>{duration_str}</b></font>",
                        ParagraphStyle(
                            "Dur",
                            parent=styles["Normal"],
                            fontSize=10,
                            fontName="Helvetica-Bold",
                            alignment=1,
                        ),
                    ),
                ]
            ],
            colWidths=[doc.width - 2.5 * cm, 2.5 * cm],
        )
        service_header.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (0, 0), 0),
                    ("RIGHTPADDING", (-1, 0), (-1, 0), 0),
                ]
            )
        )

        # Descripción
        description_para = Paragraph(svc.get("description") or "—", style_description)

        # Tabla de metadatos
        meta_table_data = [
            [
                Paragraph(label, style_meta_label),
                Paragraph(value, style_meta_value),
            ]
            for label, value in meta_rows
        ]
        meta_table = Table(meta_table_data, colWidths=[5 * cm, doc.width - 5 * cm])
        # Alternar colores de fila
        row_styles = [
            ("BACKGROUND", (0, i), (-1, i), COLOR_SECTION if i % 2 == 0 else colors.white)
            for i in range(len(meta_table_data))
        ]
        meta_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.3, COLOR_BORDER),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ]
                + row_styles
            )
        )

        block = KeepTogether(
            [
                service_header,
                description_para,
                meta_table,
                Spacer(1, 0.35 * cm),
                HRFlowable(width="100%", thickness=0.5, color=COLOR_BORDER, spaceAfter=0.15 * cm),
            ]
        )
        story.append(block)

    # ── PIE ───────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1 * cm))
    story.append(HRFlowable(width="100%", thickness=1, color=COLOR_ACCENT))
    story.append(
        Paragraph(
            "Documento generado automáticamente desde la base de datos de Atrévete Bot. "
            "Cualquier corrección debe aplicarse en el fichero database/seeds/services.py y "
            "repropagarse con el script de seeding.",
            style_note,
        )
    )

    doc.build(story)
    print(f"  PDF generado: {output_path}")


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else "servicios_atrevete.pdf"
    print(f"Generando PDF...")
    build_pdf(output)
    print("Listo.")
