"""Pestaña Palmarés: títulos (estrellitas) de cada club.

Dos fuentes que se suman solas:
  1) AUTOMÁTICA: toda partido con instancia "Final" que tenga ganador
     (por goles, por penales, o por global si es una final ida y vuelta)
     suma un título al ganador. No se guarda nada: se calcula al consultar,
     así que si editás o borrás la final, el palmarés se corrige solo.
  2) MANUAL: títulos que cargás vos a mano (ej. el campeón de la tabla anual
     de la LPF, que no sale de ningún partido que hayas visto).
Si cargás a mano un título que ya existe por una final (misma competición y
temporada, mismo club), no se cuenta doble: gana el manual.
"""
from datetime import date
from typing import Optional

import models
from database import get_db
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

router = APIRouter(prefix="/palmares", tags=["Palmarés"])

# Es final solo si la instancia es exactamente "Final" (sin importar mayúsculas ni
# espacios). "32avos de final", "Semifinal", etc. no entran.
def _es_final(instancia: str) -> bool:
    return (instancia or "").strip().lower() == "final"


def _k(s: Optional[str]) -> str:
    return (s or "").strip().lower()


class TituloIn(BaseModel):
    equipo_id: int
    competicion: str
    temporada: Optional[str] = None
    fecha: Optional[date] = None
    nota: Optional[str] = None


def _goles(p: models.Partido, club: str) -> int:
    return sum(1 for g in p.goles if _k(g.equipo) == _k(club))


def _campeon_de_final(p: models.Partido, por_id: dict) -> Optional[str]:
    """Nombre del campeón de una final, o None si no se puede determinar."""
    a, b = p.equipo_local, p.equipo_visitante
    ga, gb = _goles(p, a), _goles(p, b)
    if p.partido_ida_id and p.partido_ida_id in por_id:  # vuelta de una llave: vale el global
        ida = por_id[p.partido_ida_id]
        ga += _goles(ida, a)
        gb += _goles(ida, b)
    if ga > gb:
        return a
    if gb > ga:
        return b
    if p.penales and p.penales_ganador:
        if _k(p.penales_ganador) == _k(a):
            return a
        if _k(p.penales_ganador) == _k(b):
            return b
    return None


def _titulos_automaticos(db: Session) -> list:
    partidos = (
        db.query(models.Partido).options(selectinload(models.Partido.goles)).all()
    )
    por_id = {p.id: p for p in partidos}
    finales = [p for p in partidos if _es_final(p.instancia)]
    idas = {p.partido_ida_id for p in finales if p.partido_ida_id}  # la vuelta decide
    out = []
    for p in finales:
        if p.id in idas:
            continue
        campeon = _campeon_de_final(p, por_id)
        if campeon:
            out.append({
                "id": None, "origen": "final", "partido_id": p.id, "club": campeon,
                "competicion": p.competicion, "temporada": p.temporada,
                "fecha": p.fecha_partido, "nota": None,
            })
    return out


@router.get("/")
def palmares(db: Session = Depends(get_db)):
    """Un item por club campeón, con sus títulos, ordenado de más a menos."""
    manuales = []
    for t, nombre in (
        db.query(models.Titulo, models.Equipo.nombre)
        .join(models.Equipo, models.Equipo.id == models.Titulo.equipo_id)
        .all()
    ):
        manuales.append({
            "id": t.id, "origen": "manual", "partido_id": None, "club": nombre,
            "competicion": t.competicion, "temporada": t.temporada,
            "fecha": t.fecha, "nota": t.nota,
        })
    claves_manuales = {(_k(m["club"]), _k(m["competicion"]), _k(m["temporada"])) for m in manuales}
    autos = [
        a for a in _titulos_automaticos(db)
        if (_k(a["club"]), _k(a["competicion"]), _k(a["temporada"])) not in claves_manuales
    ]

    equipos = {_k(e.nombre): e for e in db.query(models.Equipo).all()}
    escudos = {e.equipo_id: e.escudo for e in db.query(models.EquipoEscudo).all()}
    clubes = {}
    for t in manuales + autos:
        k = _k(t["club"])
        eq = equipos.get(k)
        c = clubes.setdefault(k, {
            "equipo_id": eq.id if eq else None,
            "nombre": eq.nombre if eq else t["club"],
            "escudo": escudos.get(eq.id) if eq else None,
            "titulos": [],
        })
        c["titulos"].append({x: t[x] for x in ("id", "origen", "partido_id", "competicion", "temporada", "fecha", "nota")})
    for c in clubes.values():
        c["titulos"].sort(key=lambda t: (t["fecha"] or date.min, t["temporada"] or ""), reverse=True)
        c["total"] = len(c["titulos"])
    return sorted(clubes.values(), key=lambda c: (-c["total"], c["nombre"].lower()))


@router.post("/titulos", status_code=201)
def cargar_titulo(datos: TituloIn, db: Session = Depends(get_db)):
    eq = db.query(models.Equipo).filter(models.Equipo.id == datos.equipo_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Club no encontrado")
    comp = datos.competicion.strip()
    if not comp:
        raise HTTPException(status_code=400, detail="Falta la competición")
    temp = (datos.temporada or "").strip() or None
    for o in db.query(models.Titulo).filter(models.Titulo.equipo_id == eq.id).all():
        if _k(o.competicion) == _k(comp) and _k(o.temporada) == _k(temp):
            raise HTTPException(status_code=400, detail="Ese título ya está cargado")
    t = models.Titulo(equipo_id=eq.id, competicion=comp, temporada=temp,
                      fecha=datos.fecha, nota=(datos.nota or "").strip() or None)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"id": t.id}


@router.delete("/titulos/{titulo_id}", status_code=204)
def borrar_titulo(titulo_id: int, db: Session = Depends(get_db)):
    t = db.query(models.Titulo).filter(models.Titulo.id == titulo_id).first()
    if not t:
        raise HTTPException(status_code=404, detail="Título no encontrado")
    db.delete(t)
    db.commit()
    return None


def anotar_campeon(db: Session, partidos) -> None:
    """Le pega a cada partido `campeon` (nombre del club o None); lo lee
    PartidoResponse para resaltar las finales con ganador. En una llave de
    ida y vuelta solo la VUELTA lleva el campeón (decide el global)."""
    partidos = [p for p in partidos if p is not None]
    finales = [p for p in partidos if _es_final(p.instancia)]
    for p in partidos:
        p.campeon = None
    if not finales:
        return
    ids = [p.id for p in finales]
    es_ida = {r[0] for r in db.query(models.Partido.partido_ida_id)
              .filter(models.Partido.partido_ida_id.in_(ids)).all()}
    for p in finales:
        if p.id in es_ida:
            continue
        por_id = {}
        if p.partido_ida_id:
            ida = db.query(models.Partido).filter(models.Partido.id == p.partido_ida_id).first()
            if ida:
                por_id[ida.id] = ida
        p.campeon = _campeon_de_final(p, por_id)