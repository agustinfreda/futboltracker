"""Pestaña DTs: escudo + director técnico actual de cada club.

Los clubes salen de la tabla 'equipos' que ya existe, así que cualquier
club nuevo que se registre al cargar un partido aparece solo en la grilla
(sin DT, esperando que lo cargues). No toca ninguna tabla existente.
"""
from collections import defaultdict
from datetime import date
from typing import List, Optional

import models
from database import get_db
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

router = APIRouter(prefix="/dts", tags=["DTs"])

MAX_ESCUDO = 300_000  # caracteres; el front lo achica a ~96px, pesa muy poco


class CambioDT(BaseModel):
    nombre: str
    desde: Optional[date] = None  # fecha en que asume; por defecto, hoy


class EditarDT(BaseModel):
    nombre: str


class PeriodoDT(BaseModel):
    nombre: str
    desde: date
    hasta: date  # fecha en que dejó el cargo (ya cerrado)


class EscudoIn(BaseModel):
    escudo: Optional[str] = None  # None o "" = quitar el escudo


def _equipo_o_404(db: Session, equipo_id: int) -> models.Equipo:
    eq = db.query(models.Equipo).filter(models.Equipo.id == equipo_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Club no encontrado")
    return eq


def _dt_json(d: models.DT) -> dict:
    return {"id": d.id, "nombre": d.nombre, "desde": d.desde, "hasta": d.hasta}


# ---------- Qué DT tenía cada club en cada fecha ----------
def cargar_indice(db: Session) -> dict:
    """nombre de club (minúsculas) -> lista de (desde, hasta, nombre del DT)."""
    idx = defaultdict(list)
    filas = (
        db.query(models.DT, models.Equipo.nombre)
        .join(models.Equipo, models.Equipo.id == models.DT.equipo_id)
        .all()
    )
    for dt, club in filas:
        idx[club.strip().lower()].append((dt.desde, dt.hasta, dt.nombre))
    return idx


def dt_en_fecha(idx: dict, club: str, fecha: date) -> Optional[str]:
    """DT que dirigía al club ese día. El que asume en una fecha ya dirige
    ese mismo día; el anterior dirige hasta el día anterior."""
    for desde, hasta, nombre in idx.get((club or "").strip().lower(), ()):
        if desde <= fecha and (hasta is None or fecha < hasta):
            return nombre
    return None


def anotar_dts(db: Session, partidos) -> None:
    """Le pega a cada partido dt_local / dt_visitante (los lee PartidoResponse)."""
    idx = cargar_indice(db)
    for p in partidos:
        p.dt_local = dt_en_fecha(idx, p.equipo_local, p.fecha_partido)
        p.dt_visitante = dt_en_fecha(idx, p.equipo_visitante, p.fecha_partido)


@router.get("/clubes")
def listar_clubes(db: Session = Depends(get_db)):
    """Todos los clubes con su escudo y DT actual (o null si falta cargarlo)."""
    equipos = db.query(models.Equipo).order_by(models.Equipo.nombre).all()
    escudos = {e.equipo_id: e.escudo for e in db.query(models.EquipoEscudo).all()}
    primero = {}
    for col in (models.Partido.equipo_local, models.Partido.equipo_visitante):
        for nombre, f in db.query(col, func.min(models.Partido.fecha_partido)).group_by(col).all():
            k = (nombre or "").strip().lower()
            if k not in primero or f < primero[k]:
                primero[k] = f
    actuales, totales = {}, {}
    for d in db.query(models.DT).all():
        totales[d.equipo_id] = totales.get(d.equipo_id, 0) + 1
        if d.hasta is None:
            actuales[d.equipo_id] = d
    return [
        {
            "equipo_id": e.id,
            "nombre": e.nombre,
            "escudo": escudos.get(e.id),
            "dt_actual": _dt_json(actuales[e.id]) if e.id in actuales else None,
            "total_dts": totales.get(e.id, 0),
            "primer_partido": primero.get(e.nombre.strip().lower()),
        }
        for e in equipos
    ]


@router.post("/clubes/{equipo_id}/dt")
def poner_o_cambiar_dt(equipo_id: int, datos: CambioDT, db: Session = Depends(get_db)):
    """Un solo endpoint para los dos casos:
    - el club no tiene DT  -> lo crea como actual.
    - el club ya tiene DT  -> cierra el anterior (hasta = fecha) y deja el nuevo como actual.
    """
    _equipo_o_404(db, equipo_id)
    nombre = datos.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del DT no puede estar vacío")
    desde = datos.desde or date.today()

    actual = db.query(models.DT).filter(
        models.DT.equipo_id == equipo_id, models.DT.hasta.is_(None)
    ).first()
    if actual:
        if actual.nombre.strip().lower() == nombre.lower():
            raise HTTPException(status_code=400, detail="Ese ya es el DT actual del club")
        if desde < actual.desde:
            raise HTTPException(
                status_code=400,
                detail=f"La fecha no puede ser anterior a cuando asumió el DT actual ({actual.desde.isoformat()})",
            )
        actual.hasta = desde

    nuevo = models.DT(equipo_id=equipo_id, nombre=nombre, desde=desde, hasta=None)
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return _dt_json(nuevo)


@router.post("/clubes/{equipo_id}/periodo")
def cargar_periodo_anterior(equipo_id: int, datos: PeriodoDT, db: Session = Depends(get_db)):
    """Agrega un DT que ya se fue (con fecha de entrada y de salida), para
    completar la historia hacia atrás sin tocar al DT actual. No puede
    pisarse con otro período del mismo club."""
    _equipo_o_404(db, equipo_id)
    nombre = datos.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del DT no puede estar vacío")
    if datos.hasta <= datos.desde:
        raise HTTPException(status_code=400, detail="La fecha de salida tiene que ser posterior a la de entrada")
    for o in db.query(models.DT).filter(models.DT.equipo_id == equipo_id).all():
        if datos.desde < (o.hasta or date.max) and o.desde < datos.hasta:
            raise HTTPException(
                status_code=400,
                detail=f"Se superpone con {o.nombre} ({o.desde.isoformat()} a {o.hasta.isoformat() if o.hasta else 'hoy'})",
            )
    nuevo = models.DT(equipo_id=equipo_id, nombre=nombre, desde=datos.desde, hasta=datos.hasta)
    db.add(nuevo)
    db.commit()
    db.refresh(nuevo)
    return _dt_json(nuevo)


@router.get("/clubes/{equipo_id}/historial")
def historial_dts(equipo_id: int, db: Session = Depends(get_db)):
    _equipo_o_404(db, equipo_id)
    filas = (
        db.query(models.DT)
        .filter(models.DT.equipo_id == equipo_id)
        .order_by(models.DT.desde.desc(), models.DT.id.desc())
        .all()
    )
    return [_dt_json(d) for d in filas]


@router.put("/{dt_id}")
def corregir_nombre_dt(dt_id: int, datos: EditarDT, db: Session = Depends(get_db)):
    """Para arreglar un error de tipeo en el nombre."""
    d = db.query(models.DT).filter(models.DT.id == dt_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="DT no encontrado")
    nombre = datos.nombre.strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre del DT no puede estar vacío")
    d.nombre = nombre
    db.commit()
    return _dt_json(d)


@router.delete("/{dt_id}", status_code=204)
def borrar_dt(dt_id: int, db: Session = Depends(get_db)):
    """Deshace una carga equivocada. Si se borra el DT actual y había uno
    anterior, ese anterior vuelve a ser el actual."""
    d = db.query(models.DT).filter(models.DT.id == dt_id).first()
    if not d:
        raise HTTPException(status_code=404, detail="DT no encontrado")
    era_actual = d.hasta is None
    equipo_id = d.equipo_id
    db.delete(d)
    db.flush()
    if era_actual:
        anterior = (
            db.query(models.DT)
            .filter(models.DT.equipo_id == equipo_id)
            .order_by(models.DT.desde.desc(), models.DT.id.desc())
            .first()
        )
        if anterior:
            anterior.hasta = None
    db.commit()
    return None


@router.put("/clubes/{equipo_id}/escudo")
def guardar_escudo(equipo_id: int, datos: EscudoIn, db: Session = Depends(get_db)):
    _equipo_o_404(db, equipo_id)
    valor = (datos.escudo or "").strip()
    fila = db.query(models.EquipoEscudo).filter(models.EquipoEscudo.equipo_id == equipo_id).first()

    if not valor:
        if fila:
            db.delete(fila)
            db.commit()
        return {"equipo_id": equipo_id, "escudo": None}

    if not (valor.startswith("http://") or valor.startswith("https://") or valor.startswith("data:image/")):
        raise HTTPException(status_code=400, detail="El escudo tiene que ser una URL http(s) o una imagen")
    if len(valor) > MAX_ESCUDO:
        raise HTTPException(status_code=400, detail="La imagen del escudo es demasiado pesada")

    if fila:
        fila.escudo = valor
    else:
        db.add(models.EquipoEscudo(equipo_id=equipo_id, escudo=valor))
    db.commit()
    return {"equipo_id": equipo_id, "escudo": valor}