# Docker — Guía completa para este proyecto

Autor: Jose Angel Carretero Montes  
Proyecto: "Habla con tu dinero" · Reto Cátedra Unicaja · UGR

---

## Índice

1. [¿Qué problema resuelve Docker?](#1-qué-problema-resuelve-docker)
2. [Conceptos clave](#2-conceptos-clave)
3. [Dockerfile — cómo se construye una imagen](#3-dockerfile--cómo-se-construye-una-imagen)
4. [Docker Compose — orquestar varios contenedores](#4-docker-compose--orquestar-varios-contenedores)
5. [Cómo funciona en este proyecto](#5-cómo-funciona-en-este-proyecto)
6. [Comandos del día a día](#6-comandos-del-día-a-día)
7. [Preguntas frecuentes](#7-preguntas-frecuentes)

---

## 1. ¿Qué problema resuelve Docker?

Imagina que le mandas tu proyecto a un compañero. Él tiene Python 3.10, tú 3.12. Él tiene Node 18, tú 20. Su máquina es Windows, la tuya Linux. El proyecto falla en su entorno aunque en el tuyo funcione perfectamente. Esto se conoce como el problema *"en mi máquina sí funciona"*.

Docker lo resuelve empaquetando la aplicación junto con **todo lo que necesita para ejecutarse**: el sistema operativo base, la versión exacta de Python o Node, las dependencias, las variables de entorno... Todo en una caja sellada llamada **contenedor**.

```
Sin Docker                     Con Docker
─────────────────────          ─────────────────────────────────
Tu máquina                     Tu máquina
  Python 3.12                    Docker
  Node 20                          └── Contenedor backend
  venv activado                    │     Python 3.12
  npm install hecho                │     dependencias instaladas
  .env configurado                 │     .env cargado
                                   └── Contenedor frontend
                                         Node 20
                                         npm install hecho
```

Ventajas concretas para este proyecto:
- Arrancas todo con **un solo comando** en lugar de dos terminales
- El entorno es idéntico en cualquier máquina (local, servidor, CI)
- No necesitas tener Python ni Node instalados globalmente

---

## 2. Conceptos clave

### Imagen

Una imagen es una **plantilla de solo lectura** que describe cómo debe ser un entorno. Es como una receta. Se construye una vez y se puede reutilizar.

```
Imagen de backend:
  - Parte de Python 3.12
  - Instala las dependencias del requirements.txt
  - Copia el código fuente
  - Expone el puerto 8000
```

### Contenedor

Un contenedor es una **instancia en ejecución de una imagen**. La imagen es la receta; el contenedor es el plato cocinado. Puedes tener varios contenedores corriendo a partir de la misma imagen.

```
Imagen  ──────►  Contenedor 1 (ejecutándose)
        ──────►  Contenedor 2 (ejecutándose)
        ──────►  Contenedor 3 (parado)
```

### Volumen

Un volumen es una forma de **persistir datos fuera del contenedor**. Los contenedores son efímeros — si paras y eliminas un contenedor, todo lo que guardaste dentro desaparece. Con un volumen, los datos viven en tu disco local aunque el contenedor se destruya.

También se usa para **montar código en tiempo real**: en lugar de copiar el código dentro del contenedor al construirlo, montas la carpeta de tu máquina directamente. Así Vite y uvicorn detectan cambios al guardar sin necesidad de reconstruir.

### Red (network)

Por defecto, los contenedores están aislados entre sí. Para que puedan comunicarse hay que ponerlos en la misma **red**. Dentro de esa red, cada contenedor es accesible por su nombre de servicio (como si fuera un dominio).

```
Red app_network:
  backend  →  accesible en http://backend:8000
  frontend →  accesible en http://frontend:3000
```

Esto es crucial: desde dentro del contenedor de frontend, `localhost` es el propio contenedor de frontend. Para llegar al backend hay que usar `http://backend:8000`.

---

## 3. Dockerfile — cómo se construye una imagen

Un `Dockerfile` es el fichero que le dice a Docker cómo construir una imagen. Es una lista de instrucciones que se ejecutan en orden.

### Dockerfile del backend (`backend/Dockerfile`)

```dockerfile
FROM python:3.12-slim          # 1. Parte de una imagen oficial de Python 3.12 (versión ligera)

WORKDIR /app                   # 2. Todos los comandos siguientes se ejecutan desde /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 espeak-ng && rm -rf /var/lib/apt/lists/*
# 3. Paquetes del sistema que necesita el modo voz: ffmpeg/libsndfile1 para decodificar
#    audio (Whisper), espeak-ng como voz de respaldo de Piper.

COPY requirements.txt .        # 4. Copia solo el requirements.txt (antes que el código)
RUN pip install --no-cache-dir -r requirements.txt  # 5. Instala dependencias

COPY . .                       # 6. Copia el resto del código

RUN mkdir -p /app/data         # 7. Crea la carpeta donde vivirá la base de datos SQLite

EXPOSE 8000                    # 8. Documenta que este contenedor usa el puerto 8000
```

**¿Por qué copiar `requirements.txt` antes que el código?**  
Docker construye las imágenes por capas. Si copias el código y las dependencias juntos, cualquier cambio en el código obliga a reinstalar todas las dependencias. Separándolo, Docker cachea la capa de dependencias y solo la reconstruye cuando cambia `requirements.txt`.

### Dockerfile del frontend (`frontend/Dockerfile`)

```dockerfile
FROM node:20-alpine            # 1. Imagen oficial de Node 20 (Alpine = muy ligera)

WORKDIR /app                   # 2. Directorio de trabajo

COPY package*.json ./          # 3. Copia package.json y package-lock.json
RUN npm install                # 4. Instala dependencias (cacheado)

COPY . .                       # 5. Copia el código fuente

EXPOSE 3000                    # 6. Puerto del servidor de desarrollo de Vite

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
# 7. Comando por defecto al arrancar el contenedor
#    --host 0.0.0.0 es necesario para que Vite sea accesible desde fuera del contenedor
```

---

## 4. Docker Compose — orquestar varios contenedores

Docker Compose es una herramienta que permite **definir y arrancar múltiples contenedores a la vez** mediante un fichero `docker-compose.yml`. En lugar de ejecutar tres comandos `docker run ...` distintos, ejecutas uno solo: `docker compose up`.

### Estructura de un docker-compose.yml

```yaml
services:        # Lista de contenedores que quieres arrancar
  nombre:
    build: ...   # Dónde está el Dockerfile para construir la imagen
    ports: ...   # Mapeo de puertos: "HOST:CONTENEDOR"
    volumes: ... # Montaje de ficheros o carpetas
    environment: # Variables de entorno
    depends_on:  # Espera a que otro servicio esté listo antes de arrancar
    networks:    # A qué redes pertenece

volumes:         # Volúmenes con nombre (para datos persistentes)
networks:        # Redes definidas
```

---

## 5. Cómo funciona en este proyecto

### El fichero `docker-compose.yml`

```yaml
services:
  ollama:
    image: ollama/ollama          # Opcional: solo arranca con `docker compose --profile ollama up`
    profiles: ["ollama"]          # No se levanta en un `docker compose up` normal
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia      # Requiere GPU Nvidia — pensado para correr modelos locales
              count: 1
              capabilities: [gpu]
    networks:
      - app_network

  backend:
    build: ./backend              # Construye la imagen usando backend/Dockerfile
    ports:
      - "8000:8000"               # Puerto 8000 del host → puerto 8000 del contenedor
    volumes:
      - ./backend:/app            # Monta el código local en /app (hot-reload)
      - sqlite_data:/app/data     # Volumen persistente para la base de datos SQLite
      - ml_models:/app/models     # Volumen persistente para los modelos de Whisper/Piper
    env_file:
      - ./backend/.env            # Carga las API keys (Anthropic, Gemini, Groq...) y demás settings
    environment:
      - DATABASE_URL=sqlite:////app/data/db.sqlite3
      - MODEL_CACHE_DIR=/app/models
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    # Las migraciones de Alembic se aplican solas en cada arranque, antes de levantar uvicorn.
    networks:
      - app_network

  frontend:
    build: ./frontend             # Construye la imagen usando frontend/Dockerfile
    ports:
      - "3000:3000"               # Puerto 3000 del host → puerto 3000 del contenedor
    volumes:
      - ./frontend:/app           # Monta el código local en /app (hot-reload)
      - /app/node_modules         # Excepción: node_modules viene de la imagen, no del host
    environment:
      - VITE_BACKEND_URL=http://backend:8000  # URL interna de Docker para el proxy de Vite
    depends_on:
      - backend                   # No arranca hasta que el contenedor backend esté listo
    networks:
      - app_network

volumes:
  sqlite_data:                    # Volumen con nombre: los datos de SQLite sobreviven reinicios
  ollama_data:                    # Modelos descargados por Ollama (solo si se usa el perfil "ollama")
  ml_models:                      # Modelos de Whisper/Piper descargados en el primer arranque

networks:
  app_network:
    driver: bridge                # Red tipo bridge: contenedores aislados pero conectados entre sí
```

### El flujo de una petición dentro de Docker

```
Navegador (tu máquina)
  │
  │  GET http://localhost:3000
  ▼
Contenedor frontend (Vite, puerto 3000)
  │
  │  POST /chat/ → Vite proxy detecta la ruta y redirige a...
  │
  │  http://backend:8000/chat/   ← nombre del servicio en la red Docker
  ▼
Contenedor backend (FastAPI, puerto 8000)
  │
  │  Consulta la base de datos SQLite en /app/data/db.sqlite3
  │  Llama al proveedor de IA configurado en litellm_model (Anthropic Claude por
  │  defecto; también soporta Gemini, Groq, Mistral u Ollama local)
  ▼
Respuesta JSON → Vite → Navegador
```

### ¿Por qué `VITE_BACKEND_URL=http://backend:8000`?

El proxy de Vite vive **dentro del contenedor de frontend**. Desde ahí, `localhost` es el propio contenedor de frontend — el backend no está en ese localhost. En la red Docker `app_network`, el backend es accesible por su nombre de servicio: `backend`. Por eso el target del proxy es `http://backend:8000`.

Esto no afecta al navegador: el navegador siempre habla con `localhost:3000` (Vite), y Vite es quien hace el proxy internamente.

### El volumen `node_modules`

```yaml
volumes:
  - ./frontend:/app           # Monta TODO el directorio frontend en /app
  - /app/node_modules         # PERO /app/node_modules viene de la imagen, no del host
```

Sin la segunda línea, el montaje de `./frontend:/app` sobreescribiría los `node_modules` instalados dentro del contenedor con los de tu máquina local (que podrían no existir o ser incompatibles con Linux). La segunda línea le dice a Docker: *"para esta subcarpeta concreta, usa lo que hay en la imagen, no lo que hay en el host"*.

### Hot-reload con volúmenes

```
Tu editor (guarda ChatBox.jsx)
    │
    │  El cambio aparece en ./frontend/src/components/ChatBox.jsx
    ▼
Volumen: ./frontend:/app  (montaje en tiempo real)
    │
    │  Vite detecta el cambio en /app/src/components/ChatBox.jsx
    ▼
Recarga automática en el navegador — sin reconstruir la imagen
```

Lo mismo ocurre con el backend: uvicorn tiene `--reload`, así que detecta cambios en los `.py` y reinicia automáticamente.

---

## 6. Comandos del día a día

### Arrancar el proyecto

```bash
docker compose up
```

Primera vez (o cuando cambias un Dockerfile o requirements.txt):

```bash
docker compose up --build
```

En segundo plano (no ocupa la terminal):

```bash
docker compose up -d
```

### Parar el proyecto

```bash
docker compose down
```

Para y **borra también los volúmenes** (útil para resetear la base de datos):

```bash
docker compose down -v
```

### Ver los logs

```bash
docker compose logs -f            # todos los servicios
docker compose logs -f backend    # solo el backend
docker compose logs -f frontend   # solo el frontend
```

### Ejecutar comandos dentro de un contenedor

```bash
docker compose exec backend bash      # abrir shell en el backend
docker compose exec frontend sh       # abrir shell en el frontend (Alpine usa sh)
```

Por ejemplo, para ejecutar el script de seed de la base de datos:

```bash
docker compose exec backend python seed.py
```

### Estado de los contenedores

```bash
docker compose ps
```

### Reconstruir solo un servicio

```bash
docker compose up --build backend
```

---

## 7. Preguntas frecuentes

**¿Tengo que hacer `--build` cada vez?**  
No. Solo cuando cambias un `Dockerfile`, `requirements.txt` o `package.json`. Para cambios en el código Python o React, el hot-reload de uvicorn y Vite se encarga.

**¿Por qué el primer arranque es lento?**  
Docker descarga las imágenes base (`python:3.12-slim`, `node:20-alpine`) e instala todas las dependencias. Las siguientes veces usa la caché y es mucho más rápido.

**¿Dónde se guarda la base de datos SQLite?**  
En el volumen `sqlite_data`, gestionado por Docker. Persiste aunque pares y reinicies los contenedores. Solo se borra con `docker compose down -v`.

**¿Puedo seguir arrancando el proyecto a mano sin Docker?**  
Sí. `vite.config.js` tiene el proxy apuntando a `http://localhost:8000` por defecto cuando no está definida `VITE_BACKEND_URL`. Funciona exactamente igual que antes.

**¿Qué diferencia hay entre `docker compose stop` y `docker compose down`?**  
`stop` para los contenedores pero los conserva (puedes volver a arrancar con `start`). `down` los para y los **elimina** — la próxima vez se recrean desde la imagen.
