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

# Se usa para editar (PUT) un estadio: mismos campos que al crear.
class EstadioUpdate(EstadioBase):
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
    # Dato real que se guarda. La edad se calcula a partir de esta fecha.
    fecha_nacimiento: Optional[date] = None
    # En la entrada: solo respaldo para jugadores sin fecha cargada.
    # En la respuesta: edad ya calculada al día de hoy.
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
    # True si la edad es la vieja cargada a mano (todavía no hay fecha de
    # nacimiento): en ese caso es aproximada y no avanza sola.
    edad_aproximada: bool = False

    class Config:
        from_attributes = True


# Para cargar fechas de nacimiento en lote desde un CSV (nombre, fecha_nacimiento).
class ImportarFechasRequest(BaseModel):
    csv_texto: str


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
    # Si este partido es la VUELTA de una llave de ida y vuelta, id del
    # partido de ida. None = partido suelto (o partido de ida).
    partido_ida_id: Optional[int] = None

class PartidoCreate(PartidoBase):
    pass

# Se usa para editar (PUT) un partido ya cargado: mismos campos que al crear.
class PartidoUpdate(PartidoBase):
    pass

class PartidoResponse(PartidoBase):
    id: int
    goles: List[GolResponse] = []
    # DT de cada equipo EN LA FECHA del partido (sale de la pestaña DTs).
    # None si todavía no hay un DT cargado para esa fecha.
    dt_local: Optional[str] = None
    dt_visitante: Optional[str] = None
    # Datos de la llave (ida y vuelta), calculados al responder: rol de este
    # partido ("ida" o "vuelta"), resultado del otro partido y marcador
    # global. None si el partido no forma parte de una llave.
    llave: Optional[dict] = None

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