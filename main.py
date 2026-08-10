import os
from typing import List, Optional

import models
import schemas
from database import engine, get_db
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import extract, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Crear tablas en BD si no existen
models.Base.metadata.create_all(bind=engine)

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
def _serializar_jugador(jugador: models.Jugador, db: Session) -> dict:
    # El club de un jugador NO se guarda como campo fijo: se calcula acá,
    # leyendo los equipos distintos por los que anotó (Gol.equipo), que
    # a su vez sale del partido en el que se cargó cada gol. Así, si
    # Cavani anotó para Boca y después para Nacional, esta lista muestra
    # ambos — cada gol respeta el club de su propio partido.
    filas = db.query(models.Gol.equipo).filter(models.Gol.jugador_id == jugador.id).distinct().all()
    return {
        "id": jugador.id,
        "nombre": jugador.nombre,
        "nacionalidad": jugador.nacionalidad,
        "posicion": jugador.posicion,
        "edad": jugador.edad,
        "equipos": sorted({fila[0] for fila in filas}),
    }


@app.get("/jugadores/", response_model=List[schemas.JugadorResponse])
def obtener_jugadores(db: Session = Depends(get_db)):
    jugadores = db.query(models.Jugador).order_by(models.Jugador.nombre).all()
    return [_serializar_jugador(j, db) for j in jugadores]


@app.get("/jugadores/buscar/", response_model=List[schemas.JugadorResponse])
def buscar_jugadores(nombre: str = Query(..., min_length=1), db: Session = Depends(get_db)):
    jugadores = db.query(models.Jugador).filter(
        models.Jugador.nombre.ilike(f"%{nombre}%")
    ).limit(10).all()
    return [_serializar_jugador(j, db) for j in jugadores]


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
def obtener_partidos(db: Session = Depends(get_db)):
    return db.query(models.Partido).order_by(models.Partido.fecha_partido.desc()).all()


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


def _filtrar_por_partido(query, competicion: Optional[str], anio: Optional[int]):
    """Aplica los filtros opcionales de competición/año sobre un query
    que ya tiene un JOIN con la tabla partidos."""
    if competicion:
        query = query.filter(func.lower(models.Partido.competicion) == competicion.strip().lower())
    if anio:
        query = query.filter(extract("year", models.Partido.fecha_partido) == anio)
    return query


@app.get("/estadisticas/resumen")
def resumen_estadisticas(competicion: Optional[str] = None, anio: Optional[int] = None, db: Session = Depends(get_db)):
    query = db.query(models.Partido)
    query = _filtrar_por_partido(query, competicion, anio)
    partidos = query.all()

    total_partidos = len(partidos)
    total_goles = sum(len(p.goles) for p in partidos)
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
    # penales no suman victoria a nadie.
    query = db.query(models.Partido)
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