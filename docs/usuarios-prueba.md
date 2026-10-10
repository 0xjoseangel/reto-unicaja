# Usuarios de prueba

Usuarios creados por `backend/seed.py` para probar la app (login, chat y dashboard proactivo).

## Crear los usuarios

Con los contenedores levantados:

```bash
docker compose up -d --build backend   # --build si cambió requirements.txt
docker exec reto-unicaja-backend-1 python seed.py
```

Las migraciones se aplican solas al arrancar el backend (`alembic upgrade head` en `docker-compose.yml`). El seed salta los usuarios que ya existen, así que se puede ejecutar varias veces.

## Usuarios actuales

Contraseña de todos: `test1234`

| Usuario | Email | Perfil | Cuenta / Ahorro | Ingresos/mes | Metas |
|---|---|---|---|---|---|
| Alejandro Fernández Ruiz | `alejandro.fernandez@test.com` | Alto patrimonio, cartera de inversión (AAPL, MSFT, VOO, IWDA.AS, SAN.MC) | 15.420,90 € / 92.000 € | 6.500–7.200 € | Segunda vivienda en la costa (220.000 €), Jubilación anticipada (500.000 €) |
| Lucía Moreno Díaz | `lucia.moreno@test.com` | Estudiante, ingresos bajos e irregulares (beca + trabajo parcial) | 42,15 € / 0 € | 350–480 € | Portátil nuevo para clase (900 €) |
| Manuel Torres Jiménez | `manuel.torres@test.com` | Pensionista, ingreso fijo y gasto conservador | 2.180,60 € / 48.500 € | 1.250 € | Crucero por el Mediterráneo (6.000 €) |

### Qué probar con cada uno en el dashboard

- **Alejandro**: progreso de metas y oportunidades de inversión, no avisos de gasto.
- **Lucía**: avisos de presupuesto ajustado, no oportunidades de inversión.
- **Manuel**: estabilidad sin anomalías, con foco en salud y ocio.

Para generar las tarjetas al momento, sin esperar al job de las 22:00: `POST /dashboard/refresh` (con el token del usuario en `Authorization: Bearer ...`).

## Usuario demo

| Usuario | Email | Contraseña |
|---|---|---|
| Jose Angel Carretero | `joseangelcarretero300@gmail.com` | `demo1234` |

## Usuarios antiguos

Si la base de datos se creó con una versión anterior del seed, pueden existir también estos (contraseña `test1234`). Ya no los crea el seed actual:

- `maria.garcia@test.com`
- `carlos.ruiz@test.com`
- `ana.lopez@test.com`
- `eduardopr94g@gmail.com` — cuenta creada manualmente vía `/auth/register`, sin cuentas, transacciones ni metas asociadas, por lo que el chat y el dashboard no tienen nada que mostrarle. No usar para demos.
