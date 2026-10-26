"""Pestaña DTs: escudo + director técnico actual de cada club.

Los clubes salen de la tabla 'equipos' que ya existe, así que cualquier
club nuevo que se registre al cargar un partido aparece solo en la grilla
(sin DT, esperando que lo cargues). No toca ninguna tabla existente.
"""
from datetime import date
from typing import List, Optional

import models
from database import get_db
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(prefix="/dts", tags=["DTs"])

MAX_ESCUDO = 300_000  # caracteres; el front lo achica a ~96px, pesa muy poco


class CambioDT(BaseModel):
    nombre: str
    desde: Optional[date] = None  # fecha en que asume; por defecto, hoy


class EditarDT(BaseModel):
    nombre: str


class EscudoIn(BaseModel):
    escudo: Optional[str] = None  # None o "" = quitar el escudo


def _equipo_o_404(db: Session, equipo_id: int) -> models.Equipo:
    eq = db.query(models.Equipo).filter(models.Equipo.id == equipo_id).first()
    if not eq:
        raise HTTPException(status_code=404, detail="Club no encontrado")
    return eq


def _dt_json(d: models.DT) -> dict:
    return {"id": d.id, "nombre": d.nombre, "desde": d.desde, "hasta": d.hasta}


@router.get("/clubes")
def listar_clubes(db: Session = Depends(get_db)):
    """Todos los clubes con su escudo y DT actual (o null si falta cargarlo)."""
    equipos = db.query(models.Equipo).order_by(models.Equipo.nombre).all()
    escudos = {e.equipo_id: e.escudo for e in db.query(models.EquipoEscudo).all()}
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