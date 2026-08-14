from pydantic import BaseModel
from datetime import date
from typing import List, Optional

# --- SCHEMAS EQUIPO ---
class EquipoBase(BaseModel):
    nombre: str

class EquipoCreate(EquipoBase):
    pass

class EquipoResponse(EquipoBase):
    id: int

    class Config:
        from_attributes = True


# --- SCHEMAS ESTADIO ---
class EstadioBase(BaseModel):
    nombre: str
    ciudad: Optional[str] = None

class EstadioCreate(EstadioBase):
    pass

class EstadioResponse(EstadioBase):
    id: int

    class Config:
        from_attributes = True


# --- SCHEMAS COMPETICION ---
class CompeticionBase(BaseModel):
    nombre: str
    temporada: Optional[str] = None

class CompeticionCreate(CompeticionBase):
    pass

# Se usa para editar (PUT) una competición/edición ya cargada: mismos
# campos que al crear (nombre + temporada opcional).
class CompeticionUpdate(CompeticionBase):
    pass

class CompeticionResponse(CompeticionBase):
    id: int

    class Config:
        from_attributes = True


# --- SCHEMAS INSTANCIA ---
class InstanciaBase(BaseModel):
    nombre: str

class InstanciaCreate(InstanciaBase):
    pass

class InstanciaResponse(InstanciaBase):
    id: int

    class Config:
        from_attributes = True


# --- SCHEMAS JUGADOR ---
class JugadorBase(BaseModel):
    nombre: str
    nacionalidad: Optional[str] = None
    posicion: Optional[str] = None
    edad: Optional[int] = None

class JugadorCreate(JugadorBase):
    pass

# Se usa tanto para crear como para editar (PUT): mismos campos.
class JugadorUpdate(JugadorBase):
    pass

class JugadorResponse(JugadorBase):
    id: int
    # Calculado a partir de los goles del jugador (equipos distintos
    # por los que anotó), no es un campo que se guarde ni se edite.
    equipos: List[str] = []

    class Config:
        from_attributes = True


# --- SCHEMAS GOL ---
class GolBase(BaseModel):
    partido_id: int
    jugador_id: int
    equipo: str
    minuto: str
    tipo: Optional[str] = "JUGADA"

class GolCreate(GolBase):
    pass

class GolResponse(BaseModel):
    id: int
    equipo: str
    minuto: str
    tipo: str
    jugador: JugadorResponse

    class Config:
        from_attributes = True


# --- SCHEMAS PARTIDO ---
class PartidoBase(BaseModel):
    competicion: str
    # Edición/temporada puntual dentro de esa competición (ej. "2026").
    # Opcional: partidos viejos, ya cargados antes de este campo, quedan
    # con temporada=None y se siguen viendo bien (solo no van a filtrar
    # por edición específica).
    temporada: Optional[str] = None
    equipo_local: str
    equipo_visitante: str
    estadio: Optional[str] = None
    instancia: str
    fecha_partido: date
    # Si el partido (mata-mata) terminó empatado y se definió por penales.
    penales: bool = False
    # Nombre del equipo que ganó en penales (tiene que ser el local o el
    # visitante). Solo tiene sentido si penales=True.
    penales_ganador: Optional[str] = None

class PartidoCreate(PartidoBase):
    pass

# Se usa para editar (PUT) un partido ya cargado: mismos campos que al crear.
class PartidoUpdate(PartidoBase):
    pass

class PartidoResponse(PartidoBase):
    id: int
    goles: List[GolResponse] = []

    class Config:
        from_attributes = True


# --- SCHEMAS DASHBOARD (pantalla de Inicio) ---
class TopGoleadorDashboard(BaseModel):
    nombre: str
    goles: int

class DashboardResponse(BaseModel):
    total_partidos: int
    total_goles: int
    total_competiciones: int
    total_equipos: int
    ultimo_partido: Optional[PartidoResponse] = None
    top_goleadores: List[TopGoleadorDashboard] = []