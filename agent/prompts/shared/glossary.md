# Glosario — Taxonomía de Audiencia y Servicios

## Taxonomía de Audiencia

Usa estos valores exactos cuando el cliente describe para quién es el servicio:

| Lo que dice el cliente | Valor en sistema |
|------------------------|------------------|
| señora / mujer / femenino / ella | `adult_female` |
| caballero / hombre / masculino / él | `adult_male` |
| niña / chica menor | `child_female` |
| niño / chico menor | `child_male` |
| bebé / bebe / nene / nena | `baby` |
| unisex / para todos / cualquiera | `unisex` |

Si el cliente dice "para mí" y su género no es conocido, pregunta con quién es el servicio.

## Categorías de Servicios

- **hair** — Servicios de peluquería (cortes, tintes, tratamientos capilares)
- **aesthetics** — Servicios de estética (manicura, pedicura, depilación, tratamientos faciales)

## Tipos de Servicio en Catálogo

- **PRINCIPAL** — Servicio base (ej: Corte Dama, Tinte)
- **VARIANTE** — Variante de un servicio principal (ej: Corte + Secado)
- **ADDON** — Servicio complementario (ej: Tratamiento hidratante)

## Campos del Catálogo

Cada línea del catálogo tiene el formato:
```
[TIPO · dimensión · audiencia] Nombre del servicio — Xmin — Descripción — id=UUID
```

El `id=UUID` al final de cada línea es el identificador que debes usar en las llamadas a herramientas.
