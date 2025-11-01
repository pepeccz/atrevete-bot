# Quick Test Guide - Mensajes y Respuestas Esperadas

## 🚀 Comando Base

```bash
./scripts/send_test_message.sh "TELÉFONO" "MENSAJE" CONV_ID "NOMBRE"
```

---

## 📝 Tests Rápidos

### Test 1: Saludo Inicial (Cliente Nuevo)
```bash
./scripts/send_test_message.sh "+34612345678" "Hola" 1001 "María García"
```
**Respuesta esperada:**
- Saludo de Maite con emojis 🌸
- Pregunta por confirmación de nombre o información del cliente
- Tono amigable y natural

---

### Test 2: Consulta FAQ - Horarios
```bash
./scripts/send_test_message.sh "+34612000002" "¿A qué hora abrís?" 1002 "Pedro López"
```
**Respuesta esperada:**
- Horario del salón
- Información clara y directa
- Posible emoji 🌸

---

### Test 3: Consulta de Precio
```bash
./scripts/send_test_message.sh "+34612000003" "¿Cuánto cuesta un corte?" 1003 "Ana Martínez"
```
**Respuesta esperada:**
- Precio: 25€
- Duración: 30 minutos
- Posible pregunta si desea reservar

---

### Test 4: Consulta de Servicios
```bash
./scripts/send_test_message.sh "+34612000004" "¿Qué servicios tenéis?" 1004 "Laura Sánchez"
```
**Respuesta esperada:**
- Lista de servicios principales
- Mención de peluquería y estética
- Invitación a preguntar por servicios específicos

---

### Test 5: Intención de Reserva (Tier 1 → Tier 2)
```bash
./scripts/send_test_message.sh "+34612000005" "Quiero reservar mechas para el viernes" 1005 "Elena Torres"
```
**Respuesta esperada:**
- Confirmación de la solicitud
- Inicio del proceso de reserva
- Pregunta por detalles (hora preferida, etc.)

---

### Test 6: Pregunta sobre Diferencias entre Servicios
```bash
./scripts/send_test_message.sh "+34612000006" "¿Qué diferencia hay entre mechas y balayage?" 1006 "Carlos Ruiz"
```
**Respuesta esperada:**
- Explicación clara de las diferencias
- Información técnica pero comprensible
- Posible mención de precios

---

### Test 7: Sugerencia de Pack
```bash
./scripts/send_test_message.sh "+34612000007" "Quiero mechas y corte" 1007 "Roberto Díaz"
```
**Respuesta esperada:**
- Sugerencia del pack "Mechas + Corte"
- Mención del ahorro (25€)
- Precio del pack: 60€ vs 85€ individual

---

### Test 8: Indecisión (Oferta de Consultoría)
```bash
./scripts/send_test_message.sh "+34612000008" "No sé si hacerme mechas o balayage" 1008 "Isabel Moreno"
```
**Respuesta esperada:**
- Detección de indecisión
- Oferta de consulta gratuita de 15 minutos
- Tono comprensivo y útil

---

### Test 9: Consulta de Ubicación
```bash
./scripts/send_test_message.sh "+34612000009" "¿Dónde estáis ubicados?" 1009 "Miguel Fernández"
```
**Respuesta esperada:**
- Dirección del salón
- Posible información sobre parking o transporte
- Indicaciones si están disponibles

---

### Test 10: Pregunta Médica (Escalación)
```bash
./scripts/send_test_message.sh "+34612000010" "Tengo una condición médica, ¿puedo hacerme un tratamiento?" 1010 "Patricia Ruiz"
```
**Respuesta esperada:**
- Reconocimiento del tema médico
- Mensaje de escalación a humano
- "Es mejor que hables con el equipo" o similar

---

### Test 11: Cliente que Vuelve (Después de Test 1)
```bash
# Primero ejecuta Test 1, luego:
./scripts/send_test_message.sh "+34612345678" "Hola de nuevo" 1011 "María García"
```
**Respuesta esperada:**
- Saludo personalizado con el nombre
- Reconocimiento como cliente conocido
- "¡Hola de nuevo, María!" o similar

---

### Test 12: Conversación Multi-turno
```bash
# Turno 1
./scripts/send_test_message.sh "+34612000012" "Hola" 1012 "Carmen López"

# Turno 2 (esperar respuesta)
./scripts/send_test_message.sh "+34612000012" "¿Cuánto cuesta un corte?" 1012 "Carmen López"

# Turno 3 (esperar respuesta)
./scripts/send_test_message.sh "+34612000012" "Vale, quiero reservar" 1012 "Carmen López"
```
**Respuestas esperadas:**
- Turno 1: Saludo inicial
- Turno 2: Precio del corte (25€)
- Turno 3: Inicio de proceso de reserva

---

## 🔍 Cómo Monitorear

### Ver logs en tiempo real:
```bash
# En una terminal separada:
docker logs -f atrevete-api

# O todos los servicios:
docker compose logs -f
```

### Ver solo errores:
```bash
docker logs atrevete-api 2>&1 | grep -i error
```

---

## ✅ Checklist de Validación

Para cada test, verifica:

- [ ] **Respuesta rápida** (<5 segundos)
- [ ] **En español** correcto
- [ ] **Tono de Maite** (amigable, emojis 🌸 💕)
- [ ] **Contenido relevante** a la pregunta
- [ ] **Sin errores** en logs
- [ ] **Sin crashes** de la aplicación

---

## 🐛 Señales de Problemas

**❌ Problemas:**
- Respuesta en inglés
- Respuesta genérica "Lo siento, tuve un problema"
- Timeout (>10 segundos)
- Error 500
- Servicio se cae

**✅ Funcionamiento correcto:**
- Respuestas naturales en español
- Información específica y correcta
- Respuesta en 2-5 segundos
- Logs sin errores críticos

---

## 📊 Resumen de Tests

| # | Test | Tier | Tool Esperado |
|---|------|------|---------------|
| 1 | Saludo inicial | 1 | get_customer_by_phone |
| 2 | FAQ horarios | 1 | get_faqs |
| 3 | Precio corte | 1 | get_services |
| 4 | Lista servicios | 1 | get_services |
| 5 | Reserva | 1→2 | - |
| 6 | Diferencias | 1 | get_services |
| 7 | Pack | 1 | suggest_pack_tool |
| 8 | Indecisión | 1 | offer_consultation_tool |
| 9 | Ubicación | 1 | get_faqs |
| 10 | Escalación | 1 | escalate_to_human |
| 11 | Cliente vuelve | 1 | get_customer_by_phone |
| 12 | Multi-turno | 1 | Varios |

---

**Tiempo estimado:** 10-15 minutos para todos los tests
**Orden recomendado:** 1 → 2 → 3 → 5 → 7 → 8 (los más importantes)
