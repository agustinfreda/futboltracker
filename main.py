import os
import re
from typing import List, Optional

import models
import schemas
from database import engine, get_db
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import extract, func, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

# Crear tablas en BD si no existen
models.Base.metadata.create_all(bind=engine)


def _asegurar_columna_temporada_partidos():
    """create_all() SOLO crea tablas que todavía no existen: no agrega
    columnas nuevas a una tabla que ya está en la base (como 'partidos'
    en Render, que ya tiene partidos cargados). Como el modelo Partido
    ahora suma la columna 'temporada', hay que agregarla a mano si
    todavía no está. Es idempotente (chequea antes de tocar nada) y
    funciona tanto en Postgres (Render) como en MySQL (desarrollo
    local). Los partidos ya cargados quedan con temporada = NULL, que
    es exactamente lo mismo que "sin edición específica".
    """
    inspector = inspect(engine)
    if "partidos" not in inspector.get_table_names():
        return  # tabla recién creada por create_all(), ya sale con la columna
    columnas = [c["name"] for c in inspector.get_columns("partidos")]
    if "temporada" not in columnas:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE partidos ADD COLUMN temporada VARCHAR(20)"))


_asegurar_columna_temporada_partidos()

app = FastAPI(title="Futbol Tracker API")

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# MONTAR ARCHIVOS ESTÁTICOS Y SERVIR EL INDEX.HTML
# ---------------------------------------------------------
@app.get("/", response_class=FileResponse)
def leer_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    raise HTTPException(status_code=404, detail="index.html no fue encontrado en la raíz del proyecto")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


# ==========================================
# ENDPOINTS EQUIPOS
# ==========================================
@app.get("/equipos/", response_model=List[schemas.EquipoResponse])
def obtener_equipos(db: Session = Depends(get_db)):
    return db.query(models.Equipo).order_by(models.Equipo.nombre).all()


@app.post("/equipos/", response_model=schemas.EquipoResponse)
def crear_equipo(equipo: schemas.EquipoCreate, db: Session = Depends(get_db)):
    nombre_clean = equipo.nombre.strip()
    if not nombre_clean:
        raise HTTPException(status_code=400, detail="El nombre del equipo no puede estar vacío")

    existente = db.query(models.Equipo).filter(
        func.lower(models.Equipo.nombre) == nombre_clean.lower()
    ).first()
    if existente:
        return existente

    nuevo_equipo = models.Equipo(nombre=nombre_clean)
    db.add(nuevo_equipo)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ese equipo ya existe")
    db.refresh(nuevo_equipo)
    return nuevo_equipo


@app.delete("/equipos/{equipo_id}", status_code=204)
def borrar_equipo(equipo_id: int, db: Session = Depends(get_db)):
    equipo = db.query(models.Equipo).filter(models.Equipo.id == equipo_id).first()
    if not equipo:
        raise HTTPException(status_code=404, detail="Equipo no encontrado")

    # Como equipo_local/equipo_visitante/gol.equipo se guardan como texto
    # (no como FK), hay que chequear a mano que no esté "en uso" antes de borrar.
    en_partido = db.query(models.Partido).filter(
        (models.Partido.equipo_local == equipo.nombre) |
        (models.Partido.equipo_visitante == equipo.nombre)
    ).first()
    if en_partido:
        raise HTTPException(
            status_code=400,
            detail="No se puede borrar: el equipo tiene partidos registrados. Borrá esos partidos primero.",
        )

    db.delete(equipo)
    db.commit()
    return None


# ==========================================
# ENDPOINTS ESTADIOS
# ==========================================
@app.get("/estadios/", response_model=List[schemas.EstadioResponse])
def obtener_estadios(db: Session = Depends(get_db)):
    return db.query(models.Estadio).order_by(models.Estadio.nombre).all()


@app.post("/estadios/", response_model=schemas.EstadioResponse)
def crear_estadio(estadio: schemas.EstadioCreate, db: Session = Depends(get_db)):
    nombre_clean = estadio.nombre.strip()
    if not nombre_clean:
        raise HTTPException(status_code=400, detail="El nombre del estadio no puede estar vacío")

    existente = db.query(models.Estadio).filter(
        func.lower(models.Estadio.nombre) == nombre_clean.lower()
    ).first()
    if existente:
        return existente

    nuevo_estadio = models.Estadio(nombre=nombre_clean, ciudad=(estadio.ciudad or None))
    db.add(nuevo_estadio)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ese estadio ya existe")
    db.refresh(nuevo_estadio)
    return nuevo_estadio


@app.delete("/estadios/{estadio_id}", status_code=204)
def borrar_estadio(estadio_id: int, db: Session = Depends(get_db)):
    estadio = db.query(models.Estadio).filter(models.Estadio.id == estadio_id).first()
    if not estadio:
        raise HTTPException(status_code=404, detail="Estadio no encontrado")

    en_uso = db.query(models.Partido).filter(models.Partido.estadio == estadio.nombre).first()
    if en_uso:
        raise HTTPException(
            status_code=400,
            detail="No se puede borrar: hay partidos jugados en ese estadio.",
        )

    db.delete(estadio)
    db.commit()
    return None


# ==========================================
# ENDPOINTS COMPETICIONES
# ==========================================
@app.get("/competiciones/", response_model=List[schemas.CompeticionResponse])
def obtener_competiciones(db: Session = Depends(get_db)):
    return db.query(models.Competicion).order_by(models.Competicion.nombre, models.Competicion.temporada).all()


@app.post("/competiciones/", response_model=schemas.CompeticionResponse)
def crear_competicion(competicion: schemas.CompeticionCreate, db: Session = Depends(get_db)):
    nombre_clean = competicion.nombre.strip()
    if not nombre_clean:
        raise HTTPException(status_code=400, detail="El nombre de la competición no puede estar vacío")
    temporada_clean = (competicion.temporada or "").strip() or None

    existente = db.query(models.Competicion).filter(
        func.lower(models.Competicion.nombre) == nombre_clean.lower(),
        models.Competicion.temporada == temporada_clean,
    ).first()
    if existente:
        return existente

    nueva_competicion = models.Competicion(nombre=nombre_clean, temporada=temporada_clean)
    db.add(nueva_competicion)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Esa competición ya existe")
    db.refresh(nueva_competicion)
    return nueva_competicion


def _clave_orden_edicion(c: "models.Competicion"):
    """Para ordenar ediciones de una misma competición de la más reciente
    a la más antigua. Busca los primeros 4 dígitos del campo temporada
    (ej. "2026" o "2025/2026" -> 2026... espera, el primer año que
    aparece; para que "2025/2026" no quede antes que "2026" a secas,
    ordenamos por el último grupo de 4 dígitos encontrado, no el primero).
    Si no hay un año detectable (o temporada está vacía), esa edición se
    manda al final y se desempata por id (la creada más recientemente
    en el sistema, ya que no hay forma de saber su año)."""
    anios = re.findall(r"\d{4}", c.temporada or "")
    anio = int(anios[-1]) if anios else -1
    return (anio, c.id)


@app.get("/competiciones/ediciones", response_model=List[schemas.CompeticionResponse])
def obtener_ediciones_competicion(nombre: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    """Todas las ediciones/temporadas ya cargadas para una competición
    (ej. todas las filas "Copa Libertadores"), con la más reciente
    primera. Pensado para poblar el selector de edición del frontend
    apenas el usuario elige/crea una competición."""
    filas = db.query(models.Competicion).filter(
        func.lower(models.Competicion.nombre) == nombre.strip().lower()
    ).all()
    filas.sort(key=_clave_orden_edicion, reverse=True)
    return filas


@app.put("/competiciones/{competicion_id}", response_model=schemas.CompeticionResponse)
def actualizar_competicion(competicion_id: int, datos: schemas.CompeticionUpdate, db: Session = Depends(get_db)):
    competicion = db.query(models.Competicion).filter(models.Competicion.id == competicion_id).first()
    if not competicion:
        raise HTTPException(status_code=404, detail="Competición no encontrada")

    nombre_clean = datos.nombre.strip()
    if not nombre_clean:
        raise HTTPException(status_code=400, detail="El nombre de la competición no puede estar vacío")
    # Permite corregir una temporada mal cargada, o directamente vaciarla
    # (queda en None, que es como si "se ignorara" ese dato de nuevo).
    temporada_clean = (datos.temporada or "").strip() or None

    duplicado = db.query(models.Competicion).filter(
        func.lower(models.Competicion.nombre) == nombre_clean.lower(),
        models.Competicion.temporada == temporada_clean,
        models.Competicion.id != competicion_id,
    ).first()
    if duplicado:
        raise HTTPException(
            status_code=400,
            detail="Ya existe otra competición con ese nombre y esa edición/temporada",
        )

    nombre_viejo = competicion.nombre
    # Los partidos guardan el nombre de la competición como texto plano
    # (Partido.competicion no es FK). Si acá se corrige el nombre, hay
    # que propagar el cambio para que esos partidos sigan matcheando
    # con la competición renombrada (mismo criterio que ya se usa al
    # renombrar un equipo en un partido editado).
    if nombre_clean.lower() != nombre_viejo.strip().lower():
        db.query(models.Partido).filter(
            func.lower(models.Partido.competicion) == nombre_viejo.strip().lower()
        ).update({models.Partido.competicion: nombre_clean}, synchronize_session=False)

    competicion.nombre = nombre_clean
    competicion.temporada = temporada_clean

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ya existe otra competición con ese nombre y esa edición/temporada")
    db.refresh(competicion)
    return competicion


@app.delete("/competiciones/{competicion_id}", status_code=204)
def borrar_competicion(competicion_id: int, db: Session = Depends(get_db)):
    competicion = db.query(models.Competicion).filter(models.Competicion.id == competicion_id).first()
    if not competicion:
        raise HTTPException(status_code=404, detail="Competición no encontrada")

    en_uso = db.query(models.Partido).filter(
        func.lower(models.Partido.competicion) == competicion.nombre.lower()
    ).first()
    if en_uso:
        raise HTTPException(
            status_code=400,
            detail="No se puede borrar: hay partidos registrados en esa competición.",
        )

    db.delete(competicion)
    db.commit()
    return None


# ==========================================
# ENDPOINTS INSTANCIAS
# ==========================================
@app.get("/instancias/", response_model=List[schemas.InstanciaResponse])
def obtener_instancias(db: Session = Depends(get_db)):
    return db.query(models.Instancia).order_by(models.Instancia.nombre).all()


@app.post("/instancias/", response_model=schemas.InstanciaResponse)
def crear_instancia(instancia: schemas.InstanciaCreate, db: Session = Depends(get_db)):
    nombre_clean = instancia.nombre.strip()
    if not nombre_clean:
        raise HTTPException(status_code=400, detail="El nombre de la instancia no puede estar vacío")

    existente = db.query(models.Instancia).filter(
        func.lower(models.Instancia.nombre) == nombre_clean.lower()
    ).first()
    if existente:
        return existente

    nueva_instancia = models.Instancia(nombre=nombre_clean)
    db.add(nueva_instancia)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Esa instancia ya existe")
    db.refresh(nueva_instancia)
    return nueva_instancia


@app.delete("/instancias/{instancia_id}", status_code=204)
def borrar_instancia(instancia_id: int, db: Session = Depends(get_db)):
    instancia = db.query(models.Instancia).filter(models.Instancia.id == instancia_id).first()
    if not instancia:
        raise HTTPException(status_code=404, detail="Instancia no encontrada")

    en_uso = db.query(models.Partido).filter(
        func.lower(models.Partido.instancia) == instancia.nombre.lower()
    ).first()
    if en_uso:
        raise HTTPException(
            status_code=400,
            detail="No se puede borrar: hay partidos registrados con esa instancia.",
        )

    db.delete(instancia)
    db.commit()
    return None


# ==========================================
# ENDPOINTS JUGADORES
# ==========================================
def _mapa_equipos_por_jugador(jugador_ids: List[int], db: Session) -> dict[int, list[str]]:
    """Trae en UNA sola query los equipos distintos por los que anotó
    cada jugador (en vez de una query por jugador, que es lo que hacía
    _serializar_jugador antes y generaba un N+1 con listas grandes)."""
    if not jugador_ids:
        return {}
    filas = (
        db.query(models.Gol.jugador_id, models.Gol.equipo)
        .filter(models.Gol.jugador_id.in_(jugador_ids))
        .distinct()
        .all()
    )
    mapa: dict[int, set[str]] = {}
    for jugador_id, equipo in filas:
        mapa.setdefault(jugador_id, set()).add(equipo)
    return {jid: sorted(equipos) for jid, equipos in mapa.items()}


def _serializar_jugadores(jugadores: List[models.Jugador], db: Session) -> List[dict]:
    mapa_equipos = _mapa_equipos_por_jugador([j.id for j in jugadores], db)
    return [
        {
            "id": j.id,
            "nombre": j.nombre,
            "nacionalidad": j.nacionalidad,
            "posicion": j.posicion,
            "edad": j.edad,
            "equipos": mapa_equipos.get(j.id, []),
        }
        for j in jugadores
    ]


def _serializar_jugador(jugador: models.Jugador, db: Session) -> dict:
    """Versión para un solo jugador (alta/edición), donde no tiene
    sentido armar el mapa completo."""
    return _serializar_jugadores([jugador], db)[0]


@app.get("/jugadores/", response_model=List[schemas.JugadorResponse])
def obtener_jugadores(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    equipo: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(models.Jugador)
    if equipo:
        # Jugadores que anotaron al menos un gol para ese equipo.
        query = query.filter(
            models.Jugador.id.in_(
                db.query(models.Gol.jugador_id).filter(
                    func.lower(models.Gol.equipo) == equipo.strip().lower()
                )
            )
        )
    if q:
        query = query.filter(models.Jugador.nombre.ilike(f"%{q.strip()}%"))
    jugadores = query.order_by(models.Jugador.nombre).offset(skip).limit(limit).all()
    return _serializar_jugadores(jugadores, db)


@app.get("/jugadores/buscar/", response_model=List[schemas.JugadorResponse])
def buscar_jugadores(nombre: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    jugadores = db.query(models.Jugador).filter(
        models.Jugador.nombre.ilike(f"%{nombre}%")
    ).limit(10).all()
    return _serializar_jugadores(jugadores, db)


@app.post("/jugadores/", response_model=schemas.JugadorResponse)
def crear_jugador(jugador: schemas.JugadorCreate, db: Session = Depends(get_db)):
    nombre_clean = jugador.nombre.strip()
    if not nombre_clean:
        raise HTTPException(status_code=400, detail="El nombre del jugador no puede estar vacío")

    # Un jugador = una persona. Si ya existe (sin importar el equipo
    # que tenga cargado), no se crea otro: hay que editar el existente.
    existente = db.query(models.Jugador).filter(
        func.lower(models.Jugador.nombre) == nombre_clean.lower(),
    ).first()
    if existente:
        raise HTTPException(
            status_code=400,
            detail=f"Ya existe un jugador llamado '{nombre_clean}'.",
        )

    datos = jugador.model_dump()
    datos["nombre"] = nombre_clean
    nuevo_jugador = models.Jugador(**datos)
    db.add(nuevo_jugador)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ese jugador ya existe")
    db.refresh(nuevo_jugador)
    return _serializar_jugador(nuevo_jugador, db)


@app.put("/jugadores/{jugador_id}", response_model=schemas.JugadorResponse)
def actualizar_jugador(jugador_id: int, datos: schemas.JugadorUpdate, db: Session = Depends(get_db)):
    jugador = db.query(models.Jugador).filter(models.Jugador.id == jugador_id).first()
    if not jugador:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")

    nombre_clean = datos.nombre.strip()
    if not nombre_clean:
        raise HTTPException(status_code=400, detail="El nombre del jugador no puede estar vacío")

    duplicado = db.query(models.Jugador).filter(
        func.lower(models.Jugador.nombre) == nombre_clean.lower(),
        models.Jugador.id != jugador_id,
    ).first()
    if duplicado:
        raise HTTPException(status_code=400, detail=f"Ya existe otro jugador llamado '{nombre_clean}'")

    jugador.nombre = nombre_clean
    jugador.nacionalidad = datos.nacionalidad
    jugador.posicion = datos.posicion
    jugador.edad = datos.edad

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ese jugador ya existe")
    db.refresh(jugador)
    return _serializar_jugador(jugador, db)


@app.delete("/jugadores/{jugador_id}", status_code=204)
def borrar_jugador(jugador_id: int, db: Session = Depends(get_db)):
    jugador = db.query(models.Jugador).filter(models.Jugador.id == jugador_id).first()
    if not jugador:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")
    db.delete(jugador)  # cascade borra también sus goles
    db.commit()
    return None


# ==========================================
# ENDPOINTS PARTIDOS
# ==========================================
def _validar_penales(local: str, visitante: str, penales: bool, penales_ganador: Optional[str]) -> Optional[str]:
    """Chequea la info de penales y devuelve el nombre normalizado
    (con el casing real de local/visitante) del ganador, o None si el
    partido no se definió por penales."""
    if not penales:
        return None

    ganador_clean = (penales_ganador or "").strip()
    if not ganador_clean:
        raise HTTPException(
            status_code=400,
            detail="Si el partido se definió por penales, indicá qué equipo ganó",
        )
    if ganador_clean.lower() == local.lower():
        return local
    if ganador_clean.lower() == visitante.lower():
        return visitante
    raise HTTPException(
        status_code=400,
        detail="El ganador de los penales tiene que ser el equipo local o el visitante de ese partido",
    )


@app.get("/partidos/", response_model=List[schemas.PartidoResponse])
def obtener_partidos(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    competicion: Optional[str] = None,
    temporada: Optional[str] = None,
    anio: Optional[int] = None,
    equipo: Optional[str] = None,
    q: Optional[str] = None,
    db: Session = Depends(get_db),
):
    # Filtros server-side: antes el frontend traía TODOS los partidos y
    # filtraba en JS con partidosMemoria.filter(...). Para poder paginar
    # de a 20 con un botón "Cargar más", el filtrado tiene que pasar acá,
    # si no cada página de 20 solo filtraría dentro de esos 20.
    query = db.query(models.Partido).options(
        selectinload(models.Partido.goles).selectinload(models.Gol.jugador)
    )
    if competicion:
        query = query.filter(func.lower(models.Partido.competicion) == competicion.strip().lower())
    if temporada:
        query = query.filter(func.lower(models.Partido.temporada) == temporada.strip().lower())
    if anio:
        query = query.filter(extract("year", models.Partido.fecha_partido) == anio)
    if equipo:
        query = query.filter(
            (func.lower(models.Partido.equipo_local) == equipo.strip().lower())
            | (func.lower(models.Partido.equipo_visitante) == equipo.strip().lower())
        )
    if q:
        patron = f"%{q.strip().lower()}%"
        query = query.filter(
            func.lower(models.Partido.equipo_local).like(patron)
            | func.lower(models.Partido.equipo_visitante).like(patron)
            | func.lower(models.Partido.competicion).like(patron)
        )
    return (
        query.order_by(models.Partido.fecha_partido.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@app.get("/partidos/anios-disponibles")
def anios_disponibles_partidos(db: Session = Depends(get_db)):
    """Lista de años distintos con partidos cargados, para poblar el
    filtro de año sin tener que traer todos los partidos al frontend."""
    filas = (
        db.query(extract("year", models.Partido.fecha_partido))
        .distinct()
        .order_by(extract("year", models.Partido.fecha_partido).desc())
        .all()
    )
    return [int(fila[0]) for fila in filas]


@app.post("/partidos/", response_model=schemas.PartidoResponse)
def crear_partido(partido: schemas.PartidoCreate, db: Session = Depends(get_db)):
    local = partido.equipo_local.strip()
    visitante = partido.equipo_visitante.strip()

    if local.lower() == visitante.lower():
        raise HTTPException(status_code=400, detail="El equipo local y visitante no pueden ser el mismo")

    existente = db.query(models.Partido).filter(
        func.lower(models.Partido.equipo_local) == local.lower(),
        func.lower(models.Partido.equipo_visitante) == visitante.lower(),
        models.Partido.fecha_partido == partido.fecha_partido,
        func.lower(models.Partido.instancia) == partido.instancia.strip().lower(),
    ).first()
    if existente:
        raise HTTPException(
            status_code=400,
            detail="Ya registraste este partido (mismo enfrentamiento, fecha e instancia)",
        )

    ganador_penales = _validar_penales(local, visitante, partido.penales, partido.penales_ganador)

    datos = partido.model_dump()
    datos["equipo_local"] = local
    datos["equipo_visitante"] = visitante
    datos["penales_ganador"] = ganador_penales
    datos["temporada"] = (partido.temporada or "").strip() or None
    nuevo_partido = models.Partido(**datos)
    db.add(nuevo_partido)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ya existe un partido igual registrado")
    db.refresh(nuevo_partido)
    return nuevo_partido


@app.put("/partidos/{partido_id}", response_model=schemas.PartidoResponse)
def actualizar_partido(partido_id: int, datos: schemas.PartidoUpdate, db: Session = Depends(get_db)):
    partido = db.query(models.Partido).filter(models.Partido.id == partido_id).first()
    if not partido:
        raise HTTPException(status_code=404, detail="Partido no encontrado")

    local = datos.equipo_local.strip()
    visitante = datos.equipo_visitante.strip()

    if local.lower() == visitante.lower():
        raise HTTPException(status_code=400, detail="El equipo local y visitante no pueden ser el mismo")

    duplicado = db.query(models.Partido).filter(
        func.lower(models.Partido.equipo_local) == local.lower(),
        func.lower(models.Partido.equipo_visitante) == visitante.lower(),
        models.Partido.fecha_partido == datos.fecha_partido,
        func.lower(models.Partido.instancia) == datos.instancia.strip().lower(),
        models.Partido.id != partido_id,
    ).first()
    if duplicado:
        raise HTTPException(
            status_code=400,
            detail="Ya existe otro partido igual (mismo enfrentamiento, fecha e instancia)",
        )

    # Si cambiaron los nombres de local/visitante (ej. corregiste un typo),
    # los goles ya cargados para ese partido quedaban con el nombre viejo.
    # Los actualizamos para que sigan coincidiendo.
    local_viejo = partido.equipo_local
    visitante_viejo = partido.equipo_visitante
    for gol in partido.goles:
        if gol.equipo.strip().lower() == local_viejo.strip().lower():
            gol.equipo = local
        elif gol.equipo.strip().lower() == visitante_viejo.strip().lower():
            gol.equipo = visitante

    ganador_penales = _validar_penales(local, visitante, datos.penales, datos.penales_ganador)

    partido.competicion = datos.competicion
    partido.temporada = (datos.temporada or "").strip() or None
    partido.equipo_local = local
    partido.equipo_visitante = visitante
    partido.estadio = datos.estadio
    partido.instancia = datos.instancia
    partido.fecha_partido = datos.fecha_partido
    partido.penales = datos.penales
    partido.penales_ganador = ganador_penales

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ya existe un partido igual registrado")
    db.refresh(partido)
    return partido


@app.delete("/partidos/{partido_id}", status_code=204)
def borrar_partido(partido_id: int, db: Session = Depends(get_db)):
    partido = db.query(models.Partido).filter(models.Partido.id == partido_id).first()
    if not partido:
        raise HTTPException(status_code=404, detail="Partido no encontrado")
    db.delete(partido)  # cascade borra también sus goles
    db.commit()
    return None


# ==========================================
# ENDPOINTS GOLES
# ==========================================
@app.post("/goles/", response_model=schemas.GolResponse)
def registrar_gol(gol: schemas.GolCreate, db: Session = Depends(get_db)):
    partido = db.query(models.Partido).filter(models.Partido.id == gol.partido_id).first()
    if not partido:
        raise HTTPException(status_code=404, detail="Partido no encontrado")

    jugador = db.query(models.Jugador).filter(models.Jugador.id == gol.jugador_id).first()
    if not jugador:
        raise HTTPException(status_code=404, detail="Jugador no encontrado")

    duplicado = db.query(models.Gol).filter(
        models.Gol.partido_id == gol.partido_id,
        models.Gol.jugador_id == gol.jugador_id,
        models.Gol.minuto == gol.minuto,
    ).first()
    if duplicado:
        raise HTTPException(
            status_code=400,
            detail="Ese gol ya fue registrado (mismo jugador, partido y minuto)",
        )

    nuevo_gol = models.Gol(**gol.model_dump())
    db.add(nuevo_gol)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Ese gol ya está registrado")
    db.refresh(nuevo_gol)
    return nuevo_gol


@app.delete("/goles/{gol_id}", status_code=204)
def borrar_gol(gol_id: int, db: Session = Depends(get_db)):
    gol = db.query(models.Gol).filter(models.Gol.id == gol_id).first()
    if not gol:
        raise HTTPException(status_code=404, detail="Gol no encontrado")
    db.delete(gol)
    db.commit()
    return None


# ==========================================
# ENDPOINTS ESTADÍSTICAS
# ==========================================
def _ganador_partido(p: "models.Partido") -> Optional[str]:
    """Devuelve 'local', 'visitante' o None (empate sin penales) para un
    partido, contemplando la definición por penales cuando el resultado
    quedó igualado en el marcador."""
    gl = sum(1 for g in p.goles if g.equipo.strip().lower() == p.equipo_local.strip().lower())
    gv = sum(1 for g in p.goles if g.equipo.strip().lower() == p.equipo_visitante.strip().lower())
    if gl > gv:
        return "local"
    if gv > gl:
        return "visitante"
    # Empate en el marcador: si se definió por penales, ese es el ganador.
    if p.penales and p.penales_ganador:
        if p.penales_ganador.strip().lower() == p.equipo_local.strip().lower():
            return "local"
        if p.penales_ganador.strip().lower() == p.equipo_visitante.strip().lower():
            return "visitante"
    return None


def _filtrar_por_partido(query, competicion: Optional[str], anio: Optional[int], temporada: Optional[str] = None):
    """Aplica los filtros opcionales de competición/año/edición sobre un
    query que ya tiene un JOIN con la tabla partidos."""
    if competicion:
        query = query.filter(func.lower(models.Partido.competicion) == competicion.strip().lower())
    if anio:
        query = query.filter(extract("year", models.Partido.fecha_partido) == anio)
    if temporada:
        query = query.filter(func.lower(models.Partido.temporada) == temporada.strip().lower())
    return query


@app.get("/estadisticas/resumen")
def resumen_estadisticas(competicion: Optional[str] = None, anio: Optional[int] = None, db: Session = Depends(get_db)):
    # Determinar el ganador de cada partido (goles + penales) es lógica
    # que no vale la pena migrar 1:1 a SQL, pero cargar los goles con
    # selectinload evita el N+1 de antes: antes, cada acceso a p.goles
    # dentro del for de más abajo disparaba una query por partido.
    query = db.query(models.Partido).options(selectinload(models.Partido.goles))
    query = _filtrar_por_partido(query, competicion, anio)
    partidos = query.all()

    total_partidos = len(partidos)

    # El conteo de goles sí se resuelve en SQL directamente (una sola
    # query agregada), en vez de sumar len(p.goles) en Python.
    goles_query = db.query(func.count(models.Gol.id)).join(
        models.Partido, models.Gol.partido_id == models.Partido.id
    )
    goles_query = _filtrar_por_partido(goles_query, competicion, anio)
    total_goles = goles_query.scalar() or 0

    promedio = round(total_goles / total_partidos, 2) if total_partidos else 0

    # Nota: un partido definido por penales cuenta como victoria (no
    # empate) para el equipo que se quedó con los penales.
    gana_local = gana_visitante = empates = 0
    for p in partidos:
        ganador = _ganador_partido(p)
        if ganador == "local":
            gana_local += 1
        elif ganador == "visitante":
            gana_visitante += 1
        else:
            empates += 1

    return {
        "total_partidos": total_partidos,
        "total_goles": total_goles,
        "promedio_goles_partido": promedio,
        "gana_local": gana_local,
        "gana_visitante": gana_visitante,
        "empates": empates,
    }


@app.get("/estadisticas/top-goleadores")
def top_goleadores(
    limit: int = 3,
    competicion: Optional[str] = None,
    anio: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(
            models.Jugador.nombre,
            models.Jugador.nacionalidad,
            func.count(models.Gol.id).label("total_goles"),
        )
        .join(models.Gol, models.Jugador.id == models.Gol.jugador_id)
        .join(models.Partido, models.Gol.partido_id == models.Partido.id)
    )
    query = _filtrar_por_partido(query, competicion, anio)
    resultados = (
        query.group_by(models.Jugador.id)
        .order_by(func.count(models.Gol.id).desc())
        .limit(limit)
        .all()
    )
    return [{"nombre": r[0], "nacionalidad": r[1], "total_goles": r[2]} for r in resultados]


@app.get("/estadisticas/top-equipos-goles")
def top_equipos_goles(
    limit: int = 3,
    competicion: Optional[str] = None,
    anio: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(
            models.Gol.equipo,
            func.count(models.Gol.id).label("total_goles"),
        )
        .join(models.Partido, models.Gol.partido_id == models.Partido.id)
    )
    query = _filtrar_por_partido(query, competicion, anio)
    resultados = (
        query.group_by(models.Gol.equipo)
        .order_by(func.count(models.Gol.id).desc())
        .limit(limit)
        .all()
    )
    return [{"equipo": r[0], "total_goles": r[1]} for r in resultados]


@app.get("/estadisticas/top-estadios")
def top_estadios(
    limit: int = 3,
    competicion: Optional[str] = None,
    anio: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = db.query(
        models.Partido.estadio,
        func.count(models.Partido.id).label("total_partidos"),
    ).filter(models.Partido.estadio.isnot(None))
    query = _filtrar_por_partido(query, competicion, anio)
    resultados = (
        query.group_by(models.Partido.estadio)
        .order_by(func.count(models.Partido.id).desc())
        .limit(limit)
        .all()
    )
    return [{"estadio": r[0], "total_partidos": r[1]} for r in resultados]


@app.get("/estadisticas/goles-por-tipo")
def goles_por_tipo(
    competicion: Optional[str] = None,
    anio: Optional[int] = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(
            models.Gol.tipo,
            func.count(models.Gol.id).label("total_goles"),
        )
        .join(models.Partido, models.Gol.partido_id == models.Partido.id)
    )
    query = _filtrar_por_partido(query, competicion, anio)
    resultados = (
        query.group_by(models.Gol.tipo)
        .order_by(func.count(models.Gol.id).desc())
        .all()
    )
    return [{"tipo": r[0], "total_goles": r[1]} for r in resultados]


@app.get("/estadisticas/top-equipos-victorias")
def top_equipos_victorias(
    limit: int = 3,
    competicion: Optional[str] = None,
    anio: Optional[int] = None,
    db: Session = Depends(get_db),
):
    # El ganador se calcula acá partido por partido (goles, y si quedó
    # empatado, quién ganó los penales). Los empates sin definición por
    # penales no suman victoria a nadie. selectinload evita el N+1 al
    # leer p.goles dentro de _ganador_partido más abajo.
    query = db.query(models.Partido).options(selectinload(models.Partido.goles))
    query = _filtrar_por_partido(query, competicion, anio)
    partidos = query.all()

    victorias: dict[str, int] = {}
    for p in partidos:
        resultado = _ganador_partido(p)
        if resultado == "local":
            ganador = p.equipo_local
        elif resultado == "visitante":
            ganador = p.equipo_visitante
        else:
            continue
        victorias[ganador] = victorias.get(ganador, 0) + 1

    ordenado = sorted(victorias.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [{"equipo": equipo, "victorias": v} for equipo, v in ordenado]


# ==========================================
# ENDPOINT DASHBOARD (pantalla de Inicio)
# ==========================================
@app.get("/dashboard/resumen", response_model=schemas.DashboardResponse)
def resumen_dashboard(db: Session = Depends(get_db)):
    total_partidos = db.query(models.Partido).count()
    total_goles = db.query(models.Gol).count()
    # Nombres únicos: si una competición tiene varias temporadas cargadas
    # (ej. "Liga Profesional" 2025 y 2026), cuenta como una sola.
    total_competiciones = db.query(func.count(func.distinct(models.Competicion.nombre))).scalar() or 0
    total_equipos = db.query(models.Equipo).count()

    ultimo_partido = (
        db.query(models.Partido)
        .order_by(models.Partido.fecha_partido.desc(), models.Partido.id.desc())
        .first()
    )

    filas_goleadores = (
        db.query(models.Jugador.nombre, func.count(models.Gol.id).label("total"))
        .join(models.Gol, models.Jugador.id == models.Gol.jugador_id)
        .group_by(models.Jugador.id)
        .order_by(func.count(models.Gol.id).desc())
        .limit(3)
        .all()
    )
    top_goleadores = [{"nombre": nombre, "goles": total} for nombre, total in filas_goleadores]

    return schemas.DashboardResponse(
        total_partidos=total_partidos,
        total_goles=total_goles,
        total_competiciones=total_competiciones,
        total_equipos=total_equipos,
        ultimo_partido=ultimo_partido,
        top_goleadores=top_goleadores,
    )