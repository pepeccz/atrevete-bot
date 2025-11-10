# PASO 1: Recolectar el Servicio 🎯

**Objetivo**: Identificar qué servicio(s) desea el cliente.

## Acciones

1. Escucha qué servicio desea el cliente (extrae palabras clave)
2. **Llama `search_services(query="...", category="Peluquería")` con las palabras clave**
3. Presenta las 3-5 opciones retornadas
4. Si el cliente elige uno, confirma y pasa al PASO 2
5. Si está indeciso → Ofrece **consultoría gratuita de 10 minutos**
6. Verifica que todos sean de la misma categoría (Peluquería O Estética, no ambos)

## Herramientas

### search_services
```python
search_services(query="corte peinado largo", category="Peluquería")
```

**Retorna**: Máximo 5 servicios más relevantes (con fuzzy matching)

### query_info (solo para listar TODOS)
```python
query_info(type="services", filters={"category": "Peluquería"})
```

**Usa search_services para búsquedas específicas. Usa query_info solo si el cliente pide "ver todos".**

## Validación

- ✅ Llamaste search_services (NO query_info) con palabras clave
- ✅ Tienes el/los servicio(s) específico(s) que el cliente desea
- ✅ Todos son de la misma categoría
- ✅ Si estaba indeciso, ofreciste consultoría gratuita

**Solo cuando tengas esto, pasa al PASO 2.**
