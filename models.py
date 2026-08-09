from sqlalchemy import Column, Integer, String, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base


class Equipo(Base):
    __tablename__ = "equipos"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, index=True, nullable=False)


class Estadio(Base):
    __tablename__ = "estadios"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), unique=True, index=True, nullable=False)
    ciudad = Column(String(100), nullable=True)


class Competicion(Base):
    __tablename__ = "competiciones"
    __table_args__ = (
        # Mismo nombre puede repetirse en distintas temporadas
        # (ej. "Liga Profesional" 2025 y "Liga Profesional" 2026),
        # pero no dos veces la misma temporada.
        UniqueConstraint("nombre", "temporada", name="uq_competicion_nombre_temporada"),
    )

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), nullable=False, index=True)
    temporada = Column(String(20), nullable=True)


class Instancia(Base):
    __tablename__ = "instancias"

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(100), unique=True, index=True, nullable=False)


class Jugador(Base):
    __tablename__ = "jugadores"
    __table_args__ = (
        # Un jugador = una persona = una sola fila, sin importar el
        # club por el que haya anotado (eso se calcula por gol, no acá).
        UniqueConstraint("nombre", name="uq_jugador_nombre"),
    )

    id = Column(Integer, primary_key=True, index=True)
    nombre = Column(String(150), index=True, nullable=False)
    nacionalidad = Column(String(100), nullable=True)
    posicion = Column(String(50), nullable=True)
    edad = Column(Integer, nullable=True)
    # OJO: acá NO va equipo_actual. El club de un jugador queda fijado
    # por partido, en cada Gol (ver Gol.equipo más abajo), porque un
    # jugador puede cambiar de equipo con el tiempo. Ese club histórico
    # se calcula en el endpoint GET /jugadores/ leyendo sus goles, no
    # se guarda como campo fijo acá.

    # Relación con goles. cascade="all, delete-orphan" hace que al borrar
    # un jugador se borren automáticamente sus goles asociados.
    goles = relationship("Gol", back_populates="jugador", cascade="all, delete-orphan")


class Partido(Base):
    __tablename__ = "partidos"
    __table_args__ = (
        # Evita cargar el mismo partido dos veces.
        UniqueConstraint(
            "equipo_local", "equipo_visitante", "fecha_partido", "instancia",
            name="uq_partido_unico",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    competicion = Column(String(100), nullable=False)
    equipo_local = Column(String(100), nullable=False)
    equipo_visitante = Column(String(100), nullable=False)
    estadio = Column(String(150), nullable=True)
    instancia = Column(String(100), nullable=False)
    fecha_partido = Column(Date, nullable=False)

    # Al borrar un partido se borran sus goles automáticamente.
    goles = relationship("Gol", back_populates="partido", cascade="all, delete-orphan")


class Gol(Base):
    __tablename__ = "goles"
    __table_args__ = (
        # Evita cargar el mismo gol dos veces (mismo jugador, mismo
        # partido, mismo minuto).
        UniqueConstraint("partido_id", "jugador_id", "minuto", name="uq_gol_unico"),
    )

    id = Column(Integer, primary_key=True, index=True)
    partido_id = Column(Integer, ForeignKey("partidos.id"), nullable=False)
    jugador_id = Column(Integer, ForeignKey("jugadores.id"), nullable=False)
    # OJO: este campo guarda el equipo por el que anotó EN ESE PARTIDO
    # (sale de equipo_local/equipo_visitante al cargar el gol). Es
    # independiente del club "actual" del jugador (que ya ni existe como
    # campo): cada gol respeta el equipo con el que se jugó ese partido.
    equipo = Column(String(100), nullable=False)
    minuto = Column(String(20), nullable=False)
    tipo = Column(String(50), nullable=False, default="JUGADA")

    partido = relationship("Partido", back_populates="goles")
    jugador = relationship("Jugador", back_populates="goles")